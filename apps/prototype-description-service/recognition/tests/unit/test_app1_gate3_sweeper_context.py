"""Exercise maintenance visibility without a PostgreSQL service."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.sql.elements import TextClause

from recognition.application.services.usage_settlement_service import SettlementOutcome, UsageSettlementService
from recognition.domain.portal_contracts import UsageReservationStatus


class RlsSession:
    """A reservation table hidden unless maintenance bypass is established."""

    def __init__(self) -> None:
        self.bypass = False
        self.lookups = 0
        self.rows = [
            SimpleNamespace(
                id=uuid4(),
                tenant_id=uuid4(),
                job_id=str(uuid4()),
                idempotency_key=f"op-{index}",
                operation_id=f"op-{index}",
                request_fingerprint=f"fp-{index}",
                fence_token="fence",
                cost_units=1,
                status=UsageReservationStatus.RESERVED,
            )
            for index in range(2)
        ]

    async def execute(self, statement):
        if isinstance(statement, TextClause):
            sql = str(statement)
            if sql == "SET LOCAL app.bypass_rls = 'true'":
                self.bypass = True
            elif sql == "RESET app.bypass_rls":
                self.bypass = False
            else:
                raise AssertionError(sql)
            return None
        params = statement.compile().params
        visible = [row for row in self.rows if self.bypass and row.status == UsageReservationStatus.RESERVED]
        if "job_id_1" in params:
            self.lookups += 1
            row = next((row for row in visible if row.job_id == params["job_id_1"]), None)
            return SimpleNamespace(scalar_one_or_none=lambda: row)
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: visible[:1]))

    @asynccontextmanager
    async def begin_nested(self):
        yield self

    async def refresh(self, row):
        assert self.bypass


@pytest.mark.asyncio
async def test_background_sweep_recovers_multiple_tenants_and_resets_bypass() -> None:
    session = RlsSession()
    admission = AsyncMock()

    async def begin_recovery(ticket):
        assert session.bypass
        return next(row for row in session.rows if row.id == ticket.reservation_id)

    async def complete_recovery(row, *, target_status):
        assert session.bypass
        row.status = target_status
        return True

    admission.begin_recovery.side_effect = begin_recovery
    admission.complete_recovery.side_effect = complete_recovery
    service = UsageSettlementService(session, admission=admission)
    # Terminal evidence is supplied here; the real recovery lookup and identity
    # validation must run before it can authorize terminal settlement.
    service._decide = AsyncMock(return_value=SettlementOutcome.COMMITTED)
    report = await service.sweep_stale_reservations(stale_after_seconds=60, max_batches=3, batch_size=1)

    assert session.lookups == 2
    assert report.committed == 2
    assert report.missing == 0
    assert report.exit_code == 0
    assert all(row.status == UsageReservationStatus.COMMITTED for row in session.rows)
    assert not session.bypass


@pytest.mark.asyncio
async def test_sweep_failure_resets_maintenance_bypass() -> None:
    session = RlsSession()
    service = UsageSettlementService(session, admission=AsyncMock())
    service.recover_job = AsyncMock(side_effect=RuntimeError("recovery failed"))
    with pytest.raises(RuntimeError, match="recovery failed"):
        await service.sweep_stale_reservations(stale_after_seconds=60)
    assert not session.bypass
