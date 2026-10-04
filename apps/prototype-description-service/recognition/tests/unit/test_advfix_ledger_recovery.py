"""Recovery must survive billing period changes and the UTC day boundary."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.sql.dml import Update

from db.models import UsageReservation
from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
from recognition.domain.portal_contracts import EntitlementStatus, UsageReservationStatus, UsageTicket
import recognition.infrastructure.repositories.usage_repository as usage_repository
from recognition.infrastructure.repositories.usage_repository import (
    GlobalUsageLimitExceededError,
    SqlAlchemyUsageRepository,
)


class _Result:
    def __init__(self, row=None) -> None:
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class _RecoverySession:
    def __init__(self, *, global_state, entitlement, reservation) -> None:
        self.global_state = global_state
        self.entitlement = entitlement
        self.reservation = reservation

    async def execute(self, statement):
        if isinstance(statement, Update):
            if UsageReservationStatus(self.reservation.status) is UsageReservationStatus.RESERVED:
                return _Result(self.reservation.id)
            return _Result()
        entity = statement.column_descriptions[0].get("entity")
        rows = {
            GlobalUsageAdmissionState: self.global_state,
            TenantEntitlement: self.entitlement,
            UsageReservation: self.reservation,
        }
        return _Result(rows.get(entity))


def _period(start: datetime, *, end: datetime | None = None) -> GlobalUsageAdmissionState:
    return GlobalUsageAdmissionState(
        id="global",
        period_start=start,
        period_end=end or start + timedelta(days=1),
        daily_cost_limit=10,
        daily_cost_units=0,
        inflight_limit=2,
        inflight_units=1,
        queue_limit=2,
        queue_depth=1,
        queue_byte_limit=100,
        queue_bytes=9,
        stop_requested=False,
        fence_epoch=1,
        config_version="test",
    )


def _reservation(tenant_id, *, period_start: datetime, reserved_at: datetime) -> UsageReservation:
    return UsageReservation(
        id=uuid4(),
        tenant_id=tenant_id,
        period_start=period_start,
        idempotency_key="recovery-operation",
        operation_id="recovery-operation",
        request_fingerprint="recovery-fingerprint",
        job_id="recovery-job",
        fence_token=f"1:{uuid4()}",
        cost_units=1,
        queue_bytes=9,
        status=UsageReservationStatus.RESERVED,
        reserved_at=reserved_at,
    )


def _ticket(reservation: UsageReservation) -> UsageTicket:
    return UsageTicket(
        reservation_id=reservation.id,
        tenant_id=reservation.tenant_id,
        idempotency_key=reservation.idempotency_key,
        cost_units=reservation.cost_units,
        operation_id=reservation.operation_id,
        request_fingerprint=reservation.request_fingerprint,
        job_id=reservation.job_id,
        fence_token=reservation.fence_token,
    )


def _fixed_clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(usage_repository, "datetime", _FixedDateTime)


@pytest.mark.asyncio
async def test_begin_recovery_accepts_reservation_from_superseded_entitlement_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_period = datetime(2026, 10, 3, tzinfo=UTC)
    current_period = datetime(2026, 10, 4, tzinfo=UTC)
    now = current_period + timedelta(hours=12)
    _fixed_clock(monkeypatch, now)
    tenant_id = uuid4()
    reservation = _reservation(tenant_id, period_start=prior_period, reserved_at=prior_period + timedelta(hours=1))
    current_entitlement = TenantEntitlement(
        tenant_id=tenant_id,
        period_start=current_period,
        period_end=current_period + timedelta(days=30),
        status=EntitlementStatus.PAID_ACTIVE,
    )
    state = _period(current_period)
    repository = SqlAlchemyUsageRepository(
        _RecoverySession(global_state=state, entitlement=current_entitlement, reservation=reservation)
    )

    recovered = await repository.begin_recovery(_ticket(reservation))
    released = await repository.complete_recovery(recovered, target_status=UsageReservationStatus.RELEASED)

    assert recovered is reservation
    assert released is True
    assert (state.inflight_units, state.queue_depth, state.queue_bytes) == (0, 0, 0)


@pytest.mark.asyncio
async def test_recovery_after_daily_rollover_releases_global_capacity_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_day = datetime(2026, 10, 3, tzinfo=UTC)
    next_day = prior_day + timedelta(days=1)
    now = next_day + timedelta(seconds=1)
    _fixed_clock(monkeypatch, now)
    tenant_id = uuid4()
    reservation = _reservation(tenant_id, period_start=prior_day, reserved_at=next_day - timedelta(seconds=1))
    state = _period(prior_day, end=next_day)
    state.daily_cost_units = 1
    state.inflight_units = 1
    state.inflight_limit = 1
    state.queue_limit = 1
    state.queue_byte_limit = 9
    session = _RecoverySession(
        global_state=state,
        entitlement=TenantEntitlement(
            tenant_id=tenant_id,
            period_start=prior_day,
            period_end=prior_day + timedelta(days=30),
            status=EntitlementStatus.BETA_ACTIVE,
        ),
        reservation=reservation,
    )
    repository = SqlAlchemyUsageRepository(session)
    with pytest.raises(GlobalUsageLimitExceededError, match="in-flight"):
        repository._assert_global_capacity(state, cost_units=1, queue_bytes=9)

    locked = await repository.begin_recovery(_ticket(reservation))
    released = await repository.complete_recovery(locked, target_status=UsageReservationStatus.RELEASED)

    assert released is True
    assert state.period_start == next_day
    assert state.period_end == next_day + timedelta(days=1)
    assert state.daily_cost_units == 0
    assert (state.inflight_units, state.queue_depth, state.queue_bytes) == (0, 0, 0)
    assert reservation.status == UsageReservationStatus.RELEASED
    repository._assert_global_capacity(state, cost_units=1, queue_bytes=9)

    duplicate = await repository.complete_recovery(locked, target_status=UsageReservationStatus.RELEASED)
    assert duplicate is False
    assert (state.inflight_units, state.queue_depth, state.queue_bytes) == (0, 0, 0)
