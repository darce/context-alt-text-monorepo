"""Regression cases for ledger expiry, terminal settlement, and sweep paging."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from recognition.infrastructure.repositories.usage_repository import SqlAlchemyUsageRepository
from recognition.tests.unit.test_app1_usage_sweeper import (
    _advfix_ledger_h1_expiry_releases_counters,
    _advfix_ledger_h2_terminal_commit_keeps_daily_charge,
    _advfix_ledger_m1_sweeper_pages_past_active_prefix,
)


@pytest.mark.asyncio
async def test_admission_expiry_releases_global_counters_before_new_reserve(monkeypatch) -> None:
    await _advfix_ledger_h1_expiry_releases_counters(monkeypatch)


@pytest.mark.asyncio
async def test_stale_started_terminal_job_commits_and_keeps_daily_charge(monkeypatch) -> None:
    await _advfix_ledger_h2_terminal_commit_keeps_daily_charge(monkeypatch)


@pytest.mark.asyncio
async def test_sweeper_pages_past_active_prefix_to_release_missing_job() -> None:
    await _advfix_ledger_m1_sweeper_pages_past_active_prefix()


@pytest.mark.asyncio
async def test_expiry_preserves_incoming_cost_and_bytes() -> None:
    """Expired rows must not replace the new request's capacity or ledger values."""
    now = datetime.now(tz=UTC)
    state = SimpleNamespace(
        period_start=now.replace(hour=0, minute=0, second=0, microsecond=0),
        period_end=now + timedelta(days=1),
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
        period_start=state.period_start,
        period_end=state.period_end,
        allowance_jobs=10,
    )
    used_result = MagicMock()
    used_result.scalar_one.return_value = 0
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[entitlement_result, [(2, 7, state.period_start)], used_result])
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

    assert reservation.cost_units == 1
    assert reservation.queue_bytes == 19
    assert state.daily_cost_units == 1
    assert state.inflight_units == 1
    assert state.queue_depth == 1
    assert state.queue_bytes == 19
