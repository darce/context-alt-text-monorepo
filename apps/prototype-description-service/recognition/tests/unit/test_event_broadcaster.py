"""Unit tests for EventBroadcaster."""

import asyncio

import pytest

from recognition.application.events.broadcaster import BroadcastEvent, EventBroadcaster


class TestEventBroadcaster:
    """Tests for in-memory event broadcasting."""

    @pytest.fixture
    def broadcaster(self) -> EventBroadcaster:
        return EventBroadcaster()

    async def _wait_for_subscribers(
        self,
        broadcaster: EventBroadcaster,
        tenant_id: str,
        *,
        expected: int = 1,
        max_wait: float = 1.0,
    ) -> None:
        async with asyncio.timeout(max_wait):
            while True:
                async with broadcaster._lock:
                    count = len(broadcaster._subscribers.get(tenant_id, []))
                if count >= expected:
                    return
                await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_subscribe_receives_broadcast(self, broadcaster: EventBroadcaster) -> None:
        """Subscriber receives events after broadcast."""
        queue: asyncio.Queue[BroadcastEvent] = asyncio.Queue()

        async def subscriber() -> None:
            async for event in broadcaster.subscribe("tenant-1"):
                await queue.put(event)

        task = asyncio.create_task(subscriber())
        await self._wait_for_subscribers(broadcaster, "tenant-1")

        count = await broadcaster.broadcast("test_event", {"key": "value"}, tenant_id="tenant-1")

        event = await asyncio.wait_for(queue.get(), timeout=1.0)

        assert count == 1
        assert event.event_type == "test_event"
        assert event.data == {"key": "value"}

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, broadcaster: EventBroadcaster) -> None:
        """Events only go to matching tenant subscribers."""
        queue_t1: asyncio.Queue[BroadcastEvent] = asyncio.Queue()
        queue_t2: asyncio.Queue[BroadcastEvent] = asyncio.Queue()

        async def sub_t1() -> None:
            async for event in broadcaster.subscribe("tenant-1"):
                await queue_t1.put(event)

        async def sub_t2() -> None:
            async for event in broadcaster.subscribe("tenant-2"):
                await queue_t2.put(event)

        task1 = asyncio.create_task(sub_t1())
        task2 = asyncio.create_task(sub_t2())
        await self._wait_for_subscribers(broadcaster, "tenant-1")
        await self._wait_for_subscribers(broadcaster, "tenant-2")

        await broadcaster.broadcast("event", {"x": 1}, tenant_id="tenant-1")

        event_t1 = await asyncio.wait_for(queue_t1.get(), timeout=1.0)
        assert event_t1.event_type == "event"

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue_t2.get(), timeout=0.1)

        task1.cancel()
        task2.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task1
        with pytest.raises(asyncio.CancelledError):
            await task2

    @pytest.mark.asyncio
    async def test_broadcast_without_tenant_goes_to_all(self, broadcaster: EventBroadcaster) -> None:
        """Events without tenant_id go to all subscribers."""
        queue_t1: asyncio.Queue[BroadcastEvent] = asyncio.Queue()
        queue_t2: asyncio.Queue[BroadcastEvent] = asyncio.Queue()

        async def sub(tid: str, queue: asyncio.Queue[BroadcastEvent]) -> None:
            async for event in broadcaster.subscribe(tid):
                await queue.put(event)

        task1 = asyncio.create_task(sub("t1", queue_t1))
        task2 = asyncio.create_task(sub("t2", queue_t2))
        await self._wait_for_subscribers(broadcaster, "t1")
        await self._wait_for_subscribers(broadcaster, "t2")

        count = await broadcaster.broadcast("global", {"msg": "hello"})

        event_t1 = await asyncio.wait_for(queue_t1.get(), timeout=1.0)
        event_t2 = await asyncio.wait_for(queue_t2.get(), timeout=1.0)

        assert count == 2
        assert event_t1.event_type == "global"
        assert event_t2.event_type == "global"

        task1.cancel()
        task2.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task1
        with pytest.raises(asyncio.CancelledError):
            await task2
