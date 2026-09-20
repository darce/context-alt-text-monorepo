"""Regression coverage for the tenant entitlement state machine."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.base import Base
from db.models import AuditEvent, Tenant, TenantEntitlement, UsageReservation
from recognition.application.services.tenant_entitlement_service import TenantEntitlementService
from recognition.domain.portal_contracts import (
    BillingState,
    BillingSubscriptionStatus,
    EntitlementStatus,
    UsageReservationStatus,
)
from recognition.infrastructure.repositories.tenant_entitlement_repository import (
    SqlAlchemyTenantEntitlementRepository,
)


class _AsyncSessionAdapter:
    """Async-shaped wrapper around a synchronous SQLite session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def bind(self):
        return self._session.get_bind()

    def add(self, value: object) -> None:
        self._session.add(value)

    async def execute(self, statement):
        return self._session.execute(statement)

    async def flush(self) -> None:
        self._session.flush()

    async def refresh(self, value: object) -> None:
        self._session.refresh(value)

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    async def close(self) -> None:
        self._session.close()

    async def __aenter__(self) -> _AsyncSessionAdapter:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()


@pytest.fixture
def database() -> Iterator[tuple[Callable[[], _AsyncSessionAdapter], UUID, datetime]]:
    """Create only the portal tables needed by this lane's tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Tenant.__table__, TenantEntitlement.__table__, UsageReservation.__table__, AuditEvent.__table__],
    )
    tenant_id = uuid4()
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    with Session(engine) as setup_session:
        setup_session.add(Tenant(id=tenant_id, site_url=f"https://{tenant_id}.example.test"))
        setup_session.commit()

    def session_factory() -> _AsyncSessionAdapter:
        return _AsyncSessionAdapter(Session(engine))

    try:
        yield session_factory, tenant_id, now
    finally:
        engine.dispose()


def _paid_settings() -> SimpleNamespace:
    return SimpleNamespace(plan_allowances={"paid": 5000})


def _billing_state(
    tenant_id: UUID,
    status: BillingSubscriptionStatus,
    now: datetime,
) -> BillingState:
    return BillingState(
        tenant_id=tenant_id,
        status=status,
        provider_customer_id="customer-app-1",
        current_period_end=now + timedelta(days=30),
        past_due_since=now if status is BillingSubscriptionStatus.PAST_DUE else None,
    )


@pytest.mark.asyncio
async def test_first_paid_activation_uses_settings_allowance(database, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory, tenant_id, now = database
    import recognition.application.services.tenant_entitlement_service as service_module

    monkeypatch.setattr(service_module, "RecognitionSettings", _paid_settings)
    async with session_factory() as session:
        service = TenantEntitlementService(session, clock=lambda: now)
        snapshot = await service.apply_billing_state(
            tenant_id,
            _billing_state(tenant_id, BillingSubscriptionStatus.ACTIVE, now),
        )

    assert snapshot.status is EntitlementStatus.PAID_ACTIVE
    assert snapshot.allowance_jobs == 5000


@pytest.mark.asyncio
async def test_beta_to_paid_opens_fresh_period_without_beta_usage(database) -> None:
    session_factory, tenant_id, now = database
    beta_start = now - timedelta(hours=1)
    async with session_factory() as session:
        session.add(
            TenantEntitlement(
                tenant_id=tenant_id,
                plan_code="beta",
                allowance_version="beta-v1",
                allowance_jobs=10,
                period_start=beta_start,
                period_end=now + timedelta(days=1),
                status=EntitlementStatus.BETA_ACTIVE,
                source="operator:alice",
            )
        )
        session.add(
            UsageReservation(
                tenant_id=tenant_id,
                period_start=beta_start,
                idempotency_key="beta-used-all-10",
                status=UsageReservationStatus.COMMITTED,
                cost_units=10,
            )
        )
        await session.commit()

    async with session_factory() as session:
        service = TenantEntitlementService(
            session,
            clock=lambda: now,
            settings=_paid_settings(),
        )
        snapshot = await service.apply_billing_state(
            tenant_id,
            _billing_state(tenant_id, BillingSubscriptionStatus.ACTIVE, now),
        )

    assert snapshot.status is EntitlementStatus.PAID_ACTIVE
    assert snapshot.allowance_jobs == 5000
    assert snapshot.used_jobs == 0
    assert snapshot.period_start == now


@pytest.mark.asyncio
async def test_beta_grant_cannot_replace_past_due_paid_state_and_recovery_recomputes_plan(
    database,
) -> None:
    session_factory, tenant_id, now = database
    repository_kwargs = {
        "plan_allowances": {"paid": 5000},
        "past_due_grace": timedelta(days=1),
    }
    async with session_factory() as session:
        repository = SqlAlchemyTenantEntitlementRepository(session, **repository_kwargs)
        service = TenantEntitlementService(repository=repository, clock=lambda: now)
        await service.apply_billing_state(
            tenant_id,
            _billing_state(tenant_id, BillingSubscriptionStatus.ACTIVE, now),
        )
        past_due_snapshot = await service.apply_billing_state(
            tenant_id,
            _billing_state(tenant_id, BillingSubscriptionStatus.PAST_DUE, now),
        )
        past_due_row = await repository.get(tenant_id)
        granted_snapshot = await service.grant_beta(
            tenant_id,
            allowance_jobs=10,
            allowance_version="beta-v1",
            period_start=now,
            period_end=now + timedelta(days=30),
            source="operator:goodwill",
        )
        granted_row = await repository.get(tenant_id)
        recovered_snapshot = await service.apply_billing_state(
            tenant_id,
            _billing_state(tenant_id, BillingSubscriptionStatus.ACTIVE, now),
        )

    assert past_due_snapshot.status is EntitlementStatus.PAST_DUE
    assert past_due_row is not None
    assert past_due_row.allowance_jobs == 5000
    assert granted_snapshot.status is EntitlementStatus.PAST_DUE
    assert granted_row is not None
    assert granted_row.allowance_jobs == 5000
    assert recovered_snapshot.status is EntitlementStatus.PAID_ACTIVE
    assert recovered_snapshot.allowance_jobs == 5000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "billing_status",
    (
        BillingSubscriptionStatus.PAST_DUE,
        BillingSubscriptionStatus.CANCELED,
        BillingSubscriptionStatus.REFUND_HOLD,
    ),
)
async def test_unexpired_beta_grant_survives_non_active_billing_states(
    database,
    billing_status: BillingSubscriptionStatus,
) -> None:
    session_factory, tenant_id, now = database
    async with session_factory() as session:
        session.add(
            TenantEntitlement(
                tenant_id=tenant_id,
                plan_code="beta",
                allowance_version="beta-v1",
                allowance_jobs=10,
                period_start=now,
                period_end=now + timedelta(days=30),
                status=EntitlementStatus.BETA_ACTIVE,
                source="operator:alice",
            )
        )
        await session.commit()

    async with session_factory() as session:
        repository = SqlAlchemyTenantEntitlementRepository(
            session,
            plan_allowances={"paid": 5000},
            past_due_grace=timedelta(days=1),
        )
        service = TenantEntitlementService(repository=repository, clock=lambda: now)
        snapshot = await service.apply_billing_state(
            tenant_id,
            _billing_state(tenant_id, billing_status, now),
        )

    assert snapshot.status is EntitlementStatus.BETA_ACTIVE
    assert snapshot.allowance_jobs == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("allowances", ({}, {"other": 20}))
async def test_invalid_plan_allowances_fail_at_service_construction(database, allowances) -> None:
    session_factory, _tenant_id, now = database
    async with session_factory() as session:
        with pytest.raises(ValueError, match="plan_allowances"):
            TenantEntitlementService(
                session,
                clock=lambda: now,
                settings=SimpleNamespace(plan_allowances=allowances),
            )
