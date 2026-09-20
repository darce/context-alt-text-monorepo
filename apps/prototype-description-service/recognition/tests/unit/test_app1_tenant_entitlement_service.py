"""Unit coverage for the tenant entitlement service boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.base import Base
from db.models import AuditEvent, Tenant, TenantEntitlement, UsageReservation
from recognition.application.services.tenant_entitlement_service import TenantEntitlementService
from recognition.domain.portal_contracts import (
    DEFAULT_ALLOWANCE_JOBS,
    DEFAULT_ENTITLEMENT_STATUS,
    BillingState,
    BillingSubscriptionStatus,
    EntitlementStatus,
    UsageReservationStatus,
)
from recognition.domain.portal_contracts import (
    TenantEntitlementService as TenantEntitlementServiceProtocol,
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
    """Create the portal tables needed by this lane's unit tests."""
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


def _service(
    session: _AsyncSessionAdapter,
    now: datetime,
    *,
    audit_service: object | None = None,
    repository: object | None = None,
) -> TenantEntitlementService:
    return TenantEntitlementService(
        repository if repository is not None else session,
        clock=lambda: now,
        audit_service=audit_service,
    )


def test_service_satisfies_published_runtime_protocol() -> None:
    assert isinstance(TenantEntitlementService.__new__(TenantEntitlementService), TenantEntitlementServiceProtocol)


@pytest.mark.asyncio
async def test_missing_snapshot_is_fail_safe_and_uses_injected_clock(database) -> None:
    session_factory, tenant_id, now = database
    async with session_factory() as session:
        snapshot = await _service(session, now).snapshot(tenant_id)

    assert snapshot.tenant_id == tenant_id
    assert snapshot.status is DEFAULT_ENTITLEMENT_STATUS
    assert snapshot.allowance_jobs == DEFAULT_ALLOWANCE_JOBS
    assert snapshot.used_jobs == 0
    assert snapshot.period_start == now
    assert snapshot.period_end == now


@pytest.mark.asyncio
async def test_elapsed_period_without_grace_never_exposes_allowance(database) -> None:
    session_factory, tenant_id, now = database
    async with session_factory() as session:
        session.add(
            TenantEntitlement(
                tenant_id=tenant_id,
                plan_code="beta",
                allowance_version="beta-v1",
                allowance_jobs=50,
                period_start=now - timedelta(hours=2),
                period_end=now - timedelta(minutes=1),
                status=EntitlementStatus.BETA_ACTIVE,
                source="unit-test",
            )
        )
        await session.commit()

    async with session_factory() as session:
        snapshot = await _service(session, now).snapshot(tenant_id)

    assert snapshot.status is DEFAULT_ENTITLEMENT_STATUS
    assert snapshot.allowance_jobs == DEFAULT_ALLOWANCE_JOBS


@pytest.mark.asyncio
async def test_elapsed_period_with_grace_keeps_authorized_allowance(database) -> None:
    session_factory, tenant_id, now = database
    async with session_factory() as session:
        session.add(
            TenantEntitlement(
                tenant_id=tenant_id,
                plan_code="beta",
                allowance_version="beta-v1",
                allowance_jobs=5,
                period_start=now - timedelta(hours=2),
                period_end=now - timedelta(minutes=1),
                status=EntitlementStatus.BETA_ACTIVE,
                source="unit-test",
                grace_until=now + timedelta(hours=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        snapshot = await _service(session, now).snapshot(tenant_id)

    assert snapshot.status is EntitlementStatus.BETA_ACTIVE
    assert snapshot.allowance_jobs == 5


@pytest.mark.asyncio
async def test_grant_beta_is_tenant_bound_audited_and_upserts_metadata(database) -> None:
    session_factory, tenant_id, now = database
    async with session_factory() as session:
        service = _service(session, now)
        first = await service.grant_beta(
            tenant_id,
            allowance_jobs=10,
            allowance_version="beta-v1",
            period_start=now,
            period_end=now + timedelta(days=30),
            source="operator:alice",
        )
        second = await service.grant_beta(
            tenant_id,
            allowance_jobs=12,
            allowance_version="beta-v2",
            period_start=now,
            period_end=now + timedelta(days=30),
            source="operator:bob",
        )
        await session.commit()

    async with session_factory() as session:
        rows = (
            (await session.execute(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        events = (
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.event_type == "tenant.entitlement.grant_beta",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert first.status is EntitlementStatus.BETA_ACTIVE
    assert second.allowance_jobs == 12
    assert len(rows) == 1
    assert rows[0].allowance_version == "beta-v2"
    assert rows[0].source == "operator:bob"
    assert len(events) == 2
    assert events[-1].payload["allowance_version"] == "beta-v2"
    assert events[-1].payload["source"] == "operator:bob"


@pytest.mark.asyncio
async def test_apply_paid_state_preserves_current_period_usage_without_arrears(database) -> None:
    session_factory, tenant_id, now = database
    period_start = now - timedelta(hours=1)
    async with session_factory() as session:
        session.add(
            TenantEntitlement(
                tenant_id=tenant_id,
                plan_code="beta",
                allowance_version="beta-v1",
                allowance_jobs=10,
                period_start=period_start,
                period_end=now + timedelta(hours=1),
                status=EntitlementStatus.BETA_ACTIVE,
                source="operator:alice",
            )
        )
        session.add(
            UsageReservation(
                tenant_id=tenant_id,
                period_start=period_start,
                idempotency_key="already-used",
                status=UsageReservationStatus.COMMITTED,
                cost_units=3,
            )
        )
        await session.commit()

    state = BillingState(
        tenant_id=tenant_id,
        status=BillingSubscriptionStatus.ACTIVE,
        provider_customer_id="customer-1",
        current_period_end=now + timedelta(days=30),
        past_due_since=None,
    )
    async with session_factory() as session:
        snapshot = await _service(session, now).apply_billing_state(tenant_id, state)
        await session.commit()

    assert snapshot.status is EntitlementStatus.PAID_ACTIVE
    assert snapshot.allowance_jobs == 10
    assert snapshot.used_jobs == 3
    assert snapshot.period_start == period_start


@pytest.mark.asyncio
async def test_h4_canceled_billing_state_does_not_revoke_unexpired_beta_grant(database) -> None:
    session_factory, tenant_id, now = database
    period_end = now + timedelta(days=30)
    async with session_factory() as session:
        session.add(
            TenantEntitlement(
                tenant_id=tenant_id,
                plan_code="beta",
                allowance_version="beta-v1",
                allowance_jobs=25,
                period_start=now,
                period_end=period_end,
                status=EntitlementStatus.BETA_ACTIVE,
                source="operator:alice",
            )
        )
        await session.commit()

    state = BillingState(
        tenant_id=tenant_id,
        status=BillingSubscriptionStatus.CANCELED,
        provider_customer_id="customer-1",
        current_period_end=period_end,
        past_due_since=None,
    )
    async with session_factory() as session:
        snapshot = await _service(session, now).apply_billing_state(tenant_id, state)

    assert snapshot.status is EntitlementStatus.BETA_ACTIVE
    assert snapshot.allowance_jobs == 25


@pytest.mark.asyncio
async def test_h4_beta_upsert_does_not_clear_active_paid_status(database) -> None:
    session_factory, tenant_id, now = database
    period_end = now + timedelta(days=30)
    state = BillingState(
        tenant_id=tenant_id,
        status=BillingSubscriptionStatus.ACTIVE,
        provider_customer_id="customer-paid",
        current_period_end=period_end,
        past_due_since=None,
    )
    async with session_factory() as session:
        repository = SqlAlchemyTenantEntitlementRepository(
            session,
            plan_allowances={"paid": 40},
        )
        service = _service(session, now, repository=repository)
        await service.apply_billing_state(tenant_id, state)
        snapshot = await service.grant_beta(
            tenant_id,
            allowance_jobs=12,
            allowance_version="beta-v1",
            period_start=now,
            period_end=period_end,
            source="operator:alice",
        )

    assert snapshot.status is EntitlementStatus.PAID_ACTIVE
    assert snapshot.allowance_jobs == 40


@pytest.mark.asyncio
async def test_h6_active_paid_state_uses_configured_plan_allowance(database) -> None:
    session_factory, tenant_id, now = database
    period_end = now + timedelta(days=30)
    state = BillingState(
        tenant_id=tenant_id,
        status=BillingSubscriptionStatus.ACTIVE,
        provider_customer_id="customer-configured",
        current_period_end=period_end,
        past_due_since=None,
    )

    async with session_factory() as session:
        repository = SqlAlchemyTenantEntitlementRepository(
            session,
            allowance_by_plan={"paid": 73},
        )
        snapshot = await _service(session, now, repository=repository).apply_billing_state(tenant_id, state)

    assert snapshot.status is EntitlementStatus.PAID_ACTIVE
    assert snapshot.allowance_jobs == 73


@pytest.mark.asyncio
async def test_h6_unknown_plan_refuses_instead_of_defaulting_allowance_to_zero(database) -> None:
    session_factory, tenant_id, now = database
    state = BillingState(
        tenant_id=tenant_id,
        status=BillingSubscriptionStatus.ACTIVE,
        provider_customer_id="customer-unknown-plan",
        current_period_end=now + timedelta(days=30),
        past_due_since=None,
    )

    async with session_factory() as session:
        repository = SqlAlchemyTenantEntitlementRepository(session, plan_allowances={"other": 20})
        with pytest.raises(ValueError, match="unknown entitlement plan"):
            await _service(session, now, repository=repository).apply_billing_state(tenant_id, state)


@pytest.mark.asyncio
async def test_h6_past_due_state_gets_configured_allowance_and_grace_window(database) -> None:
    session_factory, tenant_id, now = database
    period_end = now + timedelta(days=1)
    state = BillingState(
        tenant_id=tenant_id,
        status=BillingSubscriptionStatus.PAST_DUE,
        provider_customer_id="customer-past-due",
        current_period_end=period_end,
        past_due_since=now,
    )

    async with session_factory() as session:
        repository = SqlAlchemyTenantEntitlementRepository(
            session,
            plan_allowances={"paid": 73},
            past_due_grace=timedelta(hours=2),
        )
        await _service(session, now, repository=repository).apply_billing_state(tenant_id, state)
        row = await repository.get(tenant_id)

    assert row is not None
    assert row.allowance_jobs == 73
    assert row.grace_until is not None
    assert row.grace_until.replace(tzinfo=UTC) == now + timedelta(hours=2)


@pytest.mark.asyncio
async def test_billing_state_cannot_mutate_another_tenant(database) -> None:
    session_factory, tenant_id, now = database
    foreign_tenant_id = uuid4()
    state = BillingState(
        tenant_id=foreign_tenant_id,
        status=BillingSubscriptionStatus.ACTIVE,
        provider_customer_id="customer-foreign",
        current_period_end=now + timedelta(days=30),
        past_due_since=None,
    )

    async with session_factory() as session:
        with pytest.raises(ValueError, match="tenant_id"):
            await _service(session, now).apply_billing_state(tenant_id, state)


@pytest.mark.asyncio
async def test_failed_audit_does_not_commit_grant(database) -> None:
    session_factory, tenant_id, now = database

    class FailingAudit:
        async def record_event(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("audit unavailable")

    async with session_factory() as session:
        service = _service(session, now, audit_service=FailingAudit())
        with pytest.raises(RuntimeError, match="audit unavailable"):
            await service.grant_beta(
                tenant_id,
                allowance_jobs=10,
                allowance_version="beta-v1",
                period_start=now,
                period_end=now + timedelta(days=30),
                source="operator:alice",
            )
        await session.rollback()

    async with session_factory() as session:
        row = (
            await session.execute(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id))
        ).scalar_one_or_none()

    assert row is None


def test_repository_is_the_sqlalchemy_implementation() -> None:
    assert SqlAlchemyTenantEntitlementRepository.__name__ == "SqlAlchemyTenantEntitlementRepository"
