"""Daily refunds must belong to the global period that admitted the work."""

from datetime import UTC, datetime, timedelta

import pytest

from db.models import UsageReservation
from db.models.portal_billing import GlobalUsageAdmissionState
from recognition.domain.portal_contracts import UsageReservationStatus
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
