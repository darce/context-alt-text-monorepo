"""Admission must leave stale reservations for evidence-based recovery."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.sql.dml import Update

from recognition.domain.portal_contracts import UsageReservationStatus
from recognition.infrastructure.repositories.usage_repository import SqlAlchemyUsageRepository


@pytest.mark.asyncio
async def test_admission_keeps_age_only_stale_reservations_chargeable() -> None:
    now = datetime.now(tz=UTC)
    period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    old_reserved_at = now - timedelta(hours=1)
    state = SimpleNamespace(
        period_start=period_start,
        period_end=period_start + timedelta(days=1),
        daily_cost_units=2,
        inflight_units=2,
        queue_depth=1,
        queue_bytes=7,
        daily_cost_limit=10,
        inflight_limit=10,
        queue_limit=10,
        queue_byte_limit=100,
        stop_requested=False,
        fence_epoch=1,
    )
    entitlement_result = MagicMock()
    entitlement_result.scalar_one_or_none.return_value = SimpleNamespace(
        period_start=period_start,
        period_end=period_start + timedelta(days=30),
        allowance_jobs=10,
    )
    used_result = MagicMock()
    used_result.scalar_one.return_value = 2

    statements = []
    session = MagicMock()

    async def execute(statement):
        statements.append(statement)
        if isinstance(statement, Update):
            return [(2, 7, old_reserved_at)]
        if len(statements) == 1:
            return entitlement_result
        return used_result

    session.execute = AsyncMock(side_effect=execute)
    session.flush = AsyncMock()
    session.begin_nested.return_value = AsyncMock()
    repo = SqlAlchemyUsageRepository(session)
    repo._get_by_idempotency_key = AsyncMock(return_value=None)
    repo._get_by_operation_id = AsyncMock(return_value=None)
    repo._lock_global_state = AsyncMock(return_value=state)

    reservation = await repo.reserve(
        uuid4(),
        idempotency_key="new-request",
        job_id="new-job",
        cost_units=1,
        queue_bytes=19,
    )

    assert reservation.status is UsageReservationStatus.RESERVED
    assert not any(isinstance(statement, Update) for statement in statements)
    used_sql = str(statements[-1].compile(compile_kwargs={"literal_binds": True}))
    assert "reserved_at" not in used_sql
    assert state.daily_cost_units == 3
    assert state.inflight_units == 3
    assert state.queue_depth == 2
    assert state.queue_bytes == 26
