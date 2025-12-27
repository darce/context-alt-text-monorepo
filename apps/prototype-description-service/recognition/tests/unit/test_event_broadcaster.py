"""Unit tests for EventBroadcaster."""

import asyncio

import pytest

from recognition.application.events.broadcaster import BroadcastEvent, EventBroadcaster


class TestEventBroadcaster:
    """Tests for in-memory event broadcasting."""

    @pytest.fixture
    def broadcaster(self) -> EventBroadcaster:
        return EventBroadcaster()

    @pytest.mark.asyncio
    async def test_subscribe_receives_broadcast(self, broadcaster: EventBroadcaster) -> None:
        """Subscriber receives events after broadcast."""
        received: list[BroadcastEvent] = []

        async def subscriber():
            async for event in broadcaster.subscribe("tenant-1"):
                received.append(event)
                if len(received) >= 1:
                    break

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.05)  # Let subscriber start

        count = await broadcaster.broadcast("test_event", {"key": "value"}, tenant_id="tenant-1")

        await asyncio.wait_for(task, timeout=1.0)

        assert count == 1
        assert len(received) == 1
        assert received[0].event_type == "test_event"
        assert received[0].data == {"key": "value"}

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, broadcaster: EventBroadcaster) -> None:
        """Events only go to matching tenant subscribers."""
        received_t1: list[BroadcastEvent] = []
        received_t2: list[BroadcastEvent] = []

        async def sub_t1():
            async for event in broadcaster.subscribe("tenant-1"):
                received_t1.append(event)
                break

        async def sub_t2():
            async for event in broadcaster.subscribe("tenant-2"):
                received_t2.append(event)
                break

        task1 = asyncio.create_task(sub_t1())
        task2 = asyncio.create_task(sub_t2())
        await asyncio.sleep(0.05)

        await broadcaster.broadcast("event", {"x": 1}, tenant_id="tenant-1")

        await asyncio.wait_for(task1, timeout=1.0)

        # Give t2 a moment to NOT receive it
        await asyncio.sleep(0.05)
        task2.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task2

        assert len(received_t1) == 1
        assert len(received_t2) == 0

    @pytest.mark.asyncio
    async def test_broadcast_without_tenant_goes_to_all(self, broadcaster: EventBroadcaster) -> None:
        """Events without tenant_id go to all subscribers."""
        received: list[BroadcastEvent] = []

        async def sub(tid):
            async for event in broadcaster.subscribe(tid):
                received.append(event)
                if len(received) >= 2:
                    break

        task1 = asyncio.create_task(sub("t1"))
        task2 = asyncio.create_task(sub("t2"))
        await asyncio.sleep(0.05)

        count = await broadcaster.broadcast("global", {"msg": "hello"})

        assert count == 2
        await asyncio.sleep(0.05)
        assert len(received) == 2
        task1.cancel()
        task2.cancel()
