"""Daily refunds must belong to the global period that admitted the work."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.sql.dml import Update

from db.models import UsageReservation
from db.models.portal_billing import GlobalUsageAdmissionState
from recognition.domain.portal_contracts import UsageReservationStatus, UsageTicket
import recognition.infrastructure.repositories.usage_repository as usage_repository
from recognition.infrastructure.repositories.usage_repository import (
    GlobalUsageLimitExceededError,
    SqlAlchemyUsageRepository,
)


DAY_ONE = datetime(2026, 9, 22, tzinfo=UTC)
DAY_TWO = DAY_ONE + timedelta(days=1)


@pytest.mark.parametrize("status", [UsageReservationStatus.RELEASED, UsageReservationStatus.EXPIRED])
@pytest.mark.parametrize("naive", [False, True])
def test_prior_day_settlement_preserves_current_day_capacity(status, naive) -> None:
    repo = SqlAlchemyUsageRepository(None)
    state = GlobalUsageAdmissionState(
        period_start=DAY_ONE,
        period_end=DAY_TWO,
        daily_cost_limit=5,
        daily_cost_units=0,
        inflight_limit=20,
        inflight_units=0,
        queue_limit=20,
        queue_depth=0,
        queue_byte_limit=100,
        queue_bytes=0,
        stop_requested=False,
    )
    old_reservation = UsageReservation(cost_units=2, queue_bytes=7, reserved_at=DAY_TWO - timedelta(seconds=1))
    repo._apply_reserve_counters(state, cost_units=2, queue_bytes=7, now=old_reservation.reserved_at)
    repo._roll_global_period_if_needed(state, DAY_TWO)
    repo._apply_reserve_counters(state, cost_units=3, queue_bytes=11, now=DAY_TWO)
    if naive:
        old_reservation.reserved_at = old_reservation.reserved_at.replace(tzinfo=None)
        state.period_start = state.period_start.replace(tzinfo=None)
        state.period_end = state.period_end.replace(tzinfo=None)

    repo._apply_settle_counters(state, old_reservation, target_status=status, now=DAY_TWO)

    assert state.daily_cost_units == 3
    assert (state.inflight_units, state.queue_depth, state.queue_bytes) == (3, 1, 11)
    with pytest.raises(GlobalUsageLimitExceededError, match="daily"):
        repo._assert_global_capacity(state, cost_units=4, queue_bytes=0)


@pytest.mark.parametrize("settlement_method", ["release", "commit"])
@pytest.mark.asyncio
async def test_public_prior_day_settlement_keeps_daily_capacity_at_cap(
    monkeypatch: pytest.MonkeyPatch,
    settlement_method: str,
) -> None:
    settlement_at = DAY_TWO

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return settlement_at if tz is not None else settlement_at.replace(tzinfo=None)

    monkeypatch.setattr(usage_repository, "datetime", _FixedDateTime)
    tenant_id = uuid4()
    reservation_id = uuid4()
    fence_token = f"1:{uuid4()}"
    daily_limit = 5
    global_state = GlobalUsageAdmissionState(
        id="global",
        period_start=DAY_TWO,
        period_end=DAY_TWO + timedelta(days=1),
        daily_cost_limit=daily_limit,
        daily_cost_units=daily_limit,
        inflight_limit=20,
        inflight_units=7,
        queue_limit=20,
        queue_depth=2,
        queue_byte_limit=100,
        queue_bytes=18,
        stop_requested=False,
        fence_epoch=1,
        config_version="test",
    )
    old_reservation = UsageReservation(
        id=reservation_id,
        tenant_id=tenant_id,
        period_start=DAY_ONE,
        idempotency_key="prior-day-ticket",
        operation_id="prior-day-operation",
        request_fingerprint="prior-day-fingerprint",
        job_id="prior-day-job",
        fence_token=fence_token,
        cost_units=2,
        queue_bytes=7,
        status=UsageReservationStatus.RESERVED,
        reserved_at=settlement_at - timedelta(seconds=1),
    )
    ticket = UsageTicket(
        reservation_id=reservation_id,
        tenant_id=tenant_id,
        idempotency_key=old_reservation.idempotency_key,
        cost_units=old_reservation.cost_units,
        operation_id=old_reservation.operation_id,
        request_fingerprint=old_reservation.request_fingerprint,
        job_id=old_reservation.job_id,
        fence_token=fence_token,
    )
    entitlement = SimpleNamespace(period_start=DAY_TWO, allowance_jobs=100)

    class _Result:
        def __init__(self, *, row=None, scalar=None) -> None:
            self._row = row
            self._scalar = scalar

        def scalar_one_or_none(self):
            return self._row

        def scalar_one(self):
            return self._scalar

    class _Session:
        def __init__(self, reservation) -> None:
            self.reservation = reservation

        async def execute(self, statement):
            if isinstance(statement, Update):
                row = self.reservation.id if self.reservation is not None else None
                return _Result(row=row)
            if statement.selected_columns[0].name == "coalesce":
                return _Result(scalar=0)
            entity = statement.column_descriptions[0].get("entity")
            if entity is GlobalUsageAdmissionState:
                return _Result(row=global_state)
            if entity is UsageReservation:
                return _Result(row=self.reservation)
            if entity is not None and entity.__name__ == "TenantEntitlement":
                return _Result(row=entitlement)
            raise AssertionError(f"unexpected repository query: {statement!r}")

    repo = SqlAlchemyUsageRepository(_Session(old_reservation))
    await getattr(repo, settlement_method)(ticket)

    assert global_state.daily_cost_units == daily_limit
    assert (global_state.inflight_units, global_state.queue_depth, global_state.queue_bytes) == (5, 1, 11)
    with pytest.raises(GlobalUsageLimitExceededError, match="daily"):
        await SqlAlchemyUsageRepository(_Session(None)).reserve(
            tenant_id,
            idempotency_key="new-work-after-settlement",
            job_id="new-work-after-settlement",
            cost_units=1,
        )


@pytest.mark.parametrize(
    ("status", "remaining"),
    [(UsageReservationStatus.RELEASED, 1), (UsageReservationStatus.EXPIRED, 1), (UsageReservationStatus.COMMITTED, 3)],
)
def test_current_day_settlement_refunds_only_unconsumed_work(status, remaining) -> None:
    repo = SqlAlchemyUsageRepository(None)
    state = GlobalUsageAdmissionState(
        period_start=DAY_TWO, period_end=DAY_TWO + timedelta(days=1),
        daily_cost_units=3, inflight_units=2, queue_depth=1, queue_bytes=7,
    )
    reservation = UsageReservation(cost_units=2, queue_bytes=7, reserved_at=DAY_TWO)

    repo._apply_settle_counters(state, reservation, target_status=status, now=DAY_TWO)

    assert state.daily_cost_units == remaining
    assert (state.inflight_units, state.queue_depth, state.queue_bytes) == (0, 0, 0)


@pytest.mark.asyncio
async def test_reservation_timestamp_matches_the_rolled_admission_period_and_release_refunds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission_at = datetime(2031, 3, 2, 0, 0, 0, 250000, tzinfo=UTC)
    prior_day = datetime(2031, 3, 1, tzinfo=UTC)
    following_day = datetime(2031, 3, 2, tzinfo=UTC)
    events: list[str] = []

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            events.append("clock")
            return admission_at if tz is not None else admission_at.replace(tzinfo=None)

    monkeypatch.setattr(usage_repository, "datetime", _FixedDateTime)
    tenant_id = uuid4()
    global_state = GlobalUsageAdmissionState(
        id="global",
        period_start=prior_day,
        period_end=following_day,
        daily_cost_limit=10,
        daily_cost_units=7,
        inflight_limit=20,
        inflight_units=0,
        queue_limit=20,
        queue_depth=0,
        queue_byte_limit=100,
        queue_bytes=0,
        stop_requested=False,
        fence_epoch=1,
        config_version="test",
    )
    entitlement = SimpleNamespace(period_start=prior_day, allowance_jobs=10)

    class _Result:
        def __init__(self, *, row=None, scalar=None, rowcount=None) -> None:
            self._row = row
            self._scalar = scalar
            self.rowcount = rowcount

        def scalar_one_or_none(self):
            return self._row

        def scalar_one(self):
            return self._scalar

    class _Session:
        def __init__(self) -> None:
            self.reservation = None
            self.lookup_inserted_reservation = False

        async def execute(self, statement):
            if isinstance(statement, Update):
                if self.reservation is None:
                    return _Result(rowcount=0)
                return _Result(row=self.reservation.id, rowcount=1)
            if statement.selected_columns[0].name == "coalesce":
                return _Result(scalar=0)
            entity = statement.column_descriptions[0].get("entity")
            if entity is UsageReservation:
                row = self.reservation if self.lookup_inserted_reservation else None
                return _Result(row=row)
            if entity is GlobalUsageAdmissionState:
                events.append("global lock")
                return _Result(row=global_state)
            if entity is not None and entity.__name__ == "TenantEntitlement":
                return _Result(row=entitlement)
            raise AssertionError(f"unexpected repository query: {statement!r}")

        def add(self, reservation) -> None:
            self.reservation = reservation

        async def flush(self) -> None:
            return None

        @asynccontextmanager
        async def begin_nested(self):
            yield self

    session = _Session()
    repo = SqlAlchemyUsageRepository(session)
    reservation = await repo.reserve(
        tenant_id,
        idempotency_key="rollover-release",
        job_id="rollover-release-job",
        cost_units=2,
    )

    assert global_state.period_start == following_day
    assert global_state.period_end == following_day + timedelta(days=1)
    assert global_state.daily_cost_units == 2
    assert reservation.reserved_at == admission_at
    assert events.index("global lock") < events.index("clock")

    session.lookup_inserted_reservation = True
    await repo.release(
        UsageTicket(
            reservation_id=reservation.id,
            tenant_id=tenant_id,
            idempotency_key=reservation.idempotency_key,
            cost_units=reservation.cost_units,
            operation_id=reservation.operation_id,
            request_fingerprint=reservation.request_fingerprint,
            job_id=reservation.job_id,
            fence_token=reservation.fence_token,
        )
    )

    assert global_state.daily_cost_units == 0
