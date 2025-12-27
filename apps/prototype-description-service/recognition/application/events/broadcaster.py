"""In-memory event broadcaster for SSE notifications."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BroadcastEvent:
    """Immutable event payload for SSE broadcast."""

    event_type: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class EventBroadcaster:
    """Manages SSE connections and broadcasts events to subscribers.

    Thread-safe via asyncio.Queue per subscriber. Designed for single-process
    prototype; production would use Redis pub/sub for horizontal scaling.
    """

    def __init__(self) -> None:
        """Initialize broadcaster with empty subscriber registry."""
        self._subscribers: dict[str, list[asyncio.Queue[BroadcastEvent]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, tenant_id: str) -> AsyncIterator[BroadcastEvent]:
        """Subscribe to events for a tenant.

        Args:
            tenant_id: Tenant to receive events for.

        Yields:
            BroadcastEvent instances as they are published.
        """
        queue: asyncio.Queue[BroadcastEvent] = asyncio.Queue()
        async with self._lock:
            if tenant_id not in self._subscribers:
                self._subscribers[tenant_id] = []
            self._subscribers[tenant_id].append(queue)

        logger.info(
            "[sse] Client subscribed tenant_id=%s total_subscribers=%d", tenant_id, len(self._subscribers[tenant_id])
        )
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                if tenant_id in self._subscribers:
                    self._subscribers[tenant_id].remove(queue)
                    if not self._subscribers[tenant_id]:
                        del self._subscribers[tenant_id]
            logger.info("[sse] Client unsubscribed tenant_id=%s", tenant_id)

    async def broadcast(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        tenant_id: str | None = None,
    ) -> int:
        """Broadcast an event to all subscribers (optionally filtered by tenant).

        Args:
            event_type: Event name for client routing.
            data: JSON-serializable payload.
            tenant_id: If provided, only broadcast to this tenant's subscribers.

        Returns:
            Number of subscribers notified.
        """
        event = BroadcastEvent(event_type=event_type, data=data)
        notified = 0

        async with self._lock:
            tenants = [tenant_id] if tenant_id else list(self._subscribers.keys())
            for tid in tenants:
                for queue in self._subscribers.get(tid, []):
                    await queue.put(event)
                    notified += 1

        if notified > 0:
            logger.info("[sse] Broadcast event_type=%s tenant_id=%s notified=%d", event_type, tenant_id, notified)
        return notified


# Module-level singleton
_broadcaster: EventBroadcaster | None = None


def get_event_broadcaster() -> EventBroadcaster:
    """Get or create the global EventBroadcaster singleton."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = EventBroadcaster()
    return _broadcaster
