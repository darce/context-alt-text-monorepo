"""
Server-Sent Events (SSE) endpoint for real-time notifications.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from recognition.application.events.broadcaster import get_event_broadcaster
from recognition.interface_adapters.http.deps.auth import require_auth
from recognition.interface_adapters.http.deps.tenant import get_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"], dependencies=[Depends(require_auth)])


async def _event_generator(request: Request, tenant_id: str):
    """Generate SSE-formatted events for a tenant."""
    broadcaster = get_event_broadcaster()

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
