"""
Server-Sent Events (SSE) endpoint for real-time notifications.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Final

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from recognition.application.events.broadcaster import get_event_broadcaster
from recognition.interface_adapters.http.deps.auth import require_auth
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.tenant import get_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"], dependencies=[Depends(require_auth), Depends(enforce_rate_limit)])

#: Floor of the client reconnect delay, in milliseconds.
SSE_RETRY_BASE_MS: Final[int] = 3_000

#: Width of the random window added to the floor, in milliseconds. The delay a
#: given connection is told to use is drawn from
#: ``[SSE_RETRY_BASE_MS, SSE_RETRY_BASE_MS + SSE_RETRY_JITTER_MS]``.
SSE_RETRY_JITTER_MS: Final[int] = 2_000


def _reconnect_delay_ms() -> int:
    """Per-connection reconnect delay for the SSE ``retry:`` field.

    Without a ``retry:`` field every browser falls back to its own fixed
    default (~3s) with no jitter, so a restart or load-balancer event makes
    every connected tab reconnect in lockstep and the herd lands on the first
    healthy instance at the same instant. Spreading the delay across a window
    is the server-side half of "wait, and bound the wait" (RES-06 /
    API-08) -- the retry policy belongs to the server that knows its own
    recovery profile, not to each client's built-in default.
    """
    return SSE_RETRY_BASE_MS + secrets.randbelow(SSE_RETRY_JITTER_MS + 1)


async def _event_generator(request: Request, tenant_id: str):
    """Generate SSE-formatted events for a tenant."""
    broadcaster = get_event_broadcaster()

    # RES-06: tell this client how long to wait before reconnecting, before any
    # data, so the value is already in force if the stream drops immediately.
    yield f"retry: {_reconnect_delay_ms()}\n\n"

    # Yield initial heartbeat to confirm connection
    yield ": connected\n\n"

    async for event in broadcaster.subscribe(tenant_id):
        if await request.is_disconnected():
            break

        payload = {
            "event_type": event.event_type,
            "timestamp": event.timestamp.isoformat(),
            **event.data,
        }
        yield f"data: {json.dumps(payload)}\n\n"


@router.get("/clusters/events")
async def cluster_events_stream(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    """Subscribe to real-time cluster/suggestion update events.

    Returns an SSE stream that emits events when:
    - Suggestions are refreshed (`suggestions_updated`)
    - Clusters are merged (`cluster_merged`)
    - Clusters are split (`cluster_split`)
    """
    return StreamingResponse(
        _event_generator(request, tenant_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
