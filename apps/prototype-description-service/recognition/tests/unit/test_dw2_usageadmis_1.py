from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from recognition.application.services.usage_admission_service import (
    UsageAdmissionService,
    UsageAdmissionTimeoutError,
)
from recognition.domain.portal_contracts import UsageTicket


class _BlockingUsageRepository:
    async def reserve(self, *_args, **_kwargs) -> UsageTicket:
        await asyncio.Event().wait()

    async def commit(self, _ticket: UsageTicket) -> None:
        await asyncio.Event().wait()

    async def release(self, _ticket: UsageTicket) -> None:
        await asyncio.Event().wait()


@pytest.mark.parametrize("operation", ("reserve", "commit", "release"))
@pytest.mark.asyncio
async def test_injected_repository_operations_obey_service_timeout(operation: str) -> None:
    service = UsageAdmissionService(repository=_BlockingUsageRepository(), timeout_s=0.001)
    ticket = UsageTicket(uuid4(), uuid4(), "request-1", 1)

    async def invoke() -> None:
        if operation == "reserve":
            await service.reserve(
                ticket.tenant_id,
                idempotency_key=ticket.idempotency_key,
                job_id=None,
                cost_units=ticket.cost_units,
            )
        elif operation == "commit":
            await service.commit(ticket)
        else:
            await service.release(ticket)

    with pytest.raises(UsageAdmissionTimeoutError):
        await asyncio.wait_for(invoke(), timeout=0.05)
