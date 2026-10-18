"""Cancellation cannot prove that dispatched work consumed no compute."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from recognition.domain.portal_contracts import UsageTicket
from recognition.interface_adapters.http.deps.usage_admission import admit_usage


@pytest.mark.asyncio
async def test_disconnect_after_compute_dispatch_preserves_reservation() -> None:
    ticket = UsageTicket(uuid4(), uuid4(), "operation", 1, job_id=str(uuid4()))
    service = AsyncMock()
    service.reserve.return_value = ticket
    dispatched = asyncio.Event()

    async def handler() -> None:
        async with admit_usage(
            service,
            tenant_id=ticket.tenant_id,
            idempotency_key=ticket.idempotency_key,
            job_id=ticket.job_id,
            cost_units=ticket.cost_units,
        ) as reserved:
            assert reserved is ticket
            dispatched.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(handler())
    await dispatched.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    service.reserve.assert_awaited_once()
    # No terminal evidence exists yet. Recovery must retain the capacity hold.
    service.release.assert_not_awaited()
    service.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_refusal_still_releases_once() -> None:
    ticket = UsageTicket(uuid4(), uuid4(), "operation", 1)
    service = AsyncMock()
    service.reserve.return_value = ticket
    with pytest.raises(RuntimeError, match="queue refused"):
        async with admit_usage(
            service,
            tenant_id=ticket.tenant_id,
            idempotency_key=ticket.idempotency_key,
            job_id=None,
            cost_units=ticket.cost_units,
        ):
            raise RuntimeError("queue refused")
    service.release.assert_awaited_once_with(ticket)
    service.commit.assert_not_awaited()
