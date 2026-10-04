"""PostgreSQL receipts for R1 reconcile-fix-worker lock and transaction order."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.portal_billing import BillingCheckoutAttempt, TenantEntitlement
from db.models.tenant import Tenant
from db.tenant_context import set_tenant_context
from recognition.application.services.tenant_entitlement_service import TenantEntitlementService
from recognition.domain.portal_contracts import (
    BillingState,
    BillingSubscriptionStatus,
    EntitlementStatus,
    EnumerationPage,
    ReconciliationCursorKey,
    ReconciliationKind,
)
from recognition.infrastructure.repositories.billing_reconciliation_repository import (
    BillingReconciliationRepository,
)
from recognition.infrastructure.repositories.billing_repository import BillingRepository
from recognition.infrastructure.repositories.checkout_attempt_repository import CheckoutAttemptRepository
from recognition.tests.integration.test_app1_billing_recovery_postgres import _async_url
from recognition.tests.unit.test_app1_billing_reconcile import _config, _no_sleep
from scripts.billing_reconcile import reconcile

pytestmark = pytest.mark.pg

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")
_NOW = datetime(2026, 9, 22, 19, 0, tzinfo=UTC)
_SELLER = "org_sandbox"
_PLAN_ALLOWANCES = {"paid": 50}


class _PaidOmitCustomerProvider:
    def __init__(self, *, tenant_id: UUID, customer_id: str, subscription_id: str, session: AsyncSession) -> None:
        self.environment = "sandbox"
        self.seller_account = _SELLER
        self.tenant_id = tenant_id
        self.customer_id = customer_id
        self.subscription_id = subscription_id
        self.session = session
        self.retrieve_calls: list[dict[str, object]] = []
        self.checkout_calls: list[dict[str, object]] = []
        self.create_calls: list[dict[str, object]] = []

    async def retrieve_state(
        self,
        *,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        request_timeout: float,
    ) -> BillingState:
        self.retrieve_calls.append(
            {
                "customer_id": provider_customer_id,
                "subscription_id": provider_subscription_id,
                "timeout": request_timeout,
                "txn_open": bool(self.session.in_transaction()),
            }
        )
        return BillingState(
            tenant_id=self.tenant_id,
            status=BillingSubscriptionStatus.ACTIVE,
            provider_customer_id=provider_customer_id,
            current_period_end=_NOW + timedelta(days=30),
            past_due_since=None,
            provider_subscription_id=provider_subscription_id,
            event_position=_NOW,
        )

    async def retrieve_checkout(self, *, provider_checkout_id: str, request_timeout: float) -> dict[str, object]:
        self.checkout_calls.append(
            {
                "id": provider_checkout_id,
                "timeout": request_timeout,
                "txn_open": bool(self.session.in_transaction()),
            }
        )
        return {
            "id": provider_checkout_id,
            "status": "succeeded",
            "subscription_id": self.subscription_id,
        }

    async def enumerate_subscriptions(
        self, *, cursor: str | None, limit: int, request_timeout: float
    ) -> EnumerationPage:
        return EnumerationPage((), None, True)

    async def create_checkout_session(self, **kwargs: object) -> object:
        self.create_calls.append(dict(kwargs))
        raise AssertionError("worker must not POST checkout")


class _MismatchCustomerProvider(_PaidOmitCustomerProvider):
    async def retrieve_state(
        self,
        *,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        request_timeout: float,
    ) -> BillingState:
        self.retrieve_calls.append(
            {
                "customer_id": provider_customer_id,
                "subscription_id": provider_subscription_id,
                "timeout": request_timeout,
                "txn_open": bool(self.session.in_transaction()),
            }
        )
        return BillingState(
            tenant_id=self.tenant_id,
            status=BillingSubscriptionStatus.ACTIVE,
            provider_customer_id="cus-wrong",
            current_period_end=_NOW + timedelta(days=30),
            past_due_since=None,
            provider_subscription_id=provider_subscription_id,
            event_position=_NOW,
        )


class _MissingPositionProvider:
    def __init__(self, *, tenant_id: UUID, session: AsyncSession) -> None:
        self.environment = "sandbox"
        self.seller_account = _SELLER
        self.tenant_id = tenant_id
        self.session = session
        self.create_calls: list[dict[str, object]] = []

    async def retrieve_state(self, **_kwargs: object) -> BillingState:
        raise AssertionError("missing-position orphan must not retrieve")

    async def enumerate_subscriptions(
        self, *, cursor: str | None, limit: int, request_timeout: float
    ) -> EnumerationPage:
        return EnumerationPage(
            (
                BillingState(
                    tenant_id=self.tenant_id,
                    status=BillingSubscriptionStatus.ACTIVE,
                    provider_customer_id="cus-orphan",
                    current_period_end=_NOW + timedelta(days=30),
                    past_due_since=None,
                    provider_subscription_id="sub-no-pos",
                    event_position=None,
                ),
            ),
            None,
            True,
        )

    async def create_checkout_session(self, **kwargs: object) -> object:
        self.create_calls.append(dict(kwargs))
        raise AssertionError("worker must not POST checkout")


async def _seed_tenant(session: AsyncSession, *, site_url: str) -> Tenant:
    tenant = Tenant(site_url=site_url)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)
    return tenant


async def _entitlement_status(session: AsyncSession, tenant_id: UUID) -> str | None:
    await set_tenant_context(session, tenant_id)
    result = await session.execute(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id).limit(1))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return row.status if isinstance(row.status, str) else row.status.value


@pytest.mark.asyncio
async def test_postgres_rv07_paid_checkout_lookup_closes_txn_before_retrieve(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = await _seed_tenant(session, site_url=f"https://r1-rv07-{uuid4().hex}.example.test")
            billing = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            await billing.upsert_projection(
                tenant_id=tenant.id,
                provider="fake",
                provider_customer_id="cus-paid",
                provider_subscription_id="sub-paid",
                status=BillingSubscriptionStatus.ACTIVE,
                current_period_end=_NOW + timedelta(days=14),
                past_due_since=None,
                provider_event_id="evt-seed",
                event_position=_NOW - timedelta(days=1),
            )
            checkout = CheckoutAttemptRepository(session)
            begun = await checkout.begin_attempt(
                tenant_id=tenant.id,
                provider="fake",
                environment="sandbox",
                seller_account=_SELLER,
                plan_code="pro",
                idempotency_key=f"provider-{uuid4().hex}",
                client_idempotency_key=f"client-{uuid4().hex}",
                request_fingerprint="fp-rv07",
            )
            await checkout.record_provider_checkout(
                tenant.id,
                begun.attempt.id,
                provider_checkout_id="chk-rv07",
                checkout_url="https://pay.example/rv07",
            )
            await checkout.mark_ambiguous(tenant.id, begun.attempt.id)
            await session.execute(
                update(BillingCheckoutAttempt)
                .where(BillingCheckoutAttempt.id == begun.attempt.id)
                .values(updated_at=_NOW - timedelta(seconds=30))
            )
            await session.commit()
            tenant_id = tenant.id

        session = session_factory()
        billing = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
        recovery = BillingReconciliationRepository(session)
        checkout_repo = CheckoutAttemptRepository(session)
        provider = _PaidOmitCustomerProvider(
            tenant_id=tenant_id,
            customer_id="cus-paid",
            subscription_id="sub-paid",
            session=session,
        )
        try:
            report = await reconcile(
                billing,
                provider,
                entitlement_service=TenantEntitlementService(
                    session, plan_allowances=_PLAN_ALLOWANCES, clock=lambda: _NOW
                ),
                recovery_repository=recovery,
                checkout_repository=checkout_repo,
                config=_config(provider_timeout_s=8.0),
                clock=lambda: _NOW,
                sleeper=_no_sleep,
                environment="sandbox",
                seller_account=_SELLER,
            )
        finally:
            await session.close()

        assert provider.create_calls == []
        assert provider.checkout_calls
        assert provider.retrieve_calls
        assert all(call["txn_open"] is False for call in provider.checkout_calls)
        assert all(call["txn_open"] is False for call in provider.retrieve_calls)
        assert report.exit_code == 0

        async with session_factory() as session:
            billing = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            projection = await billing.get_projection(tenant_id, provider="fake")
            assert projection is not None
            assert projection.provider_customer_id == "cus-paid"
            assert await _entitlement_status(session, tenant_id) == EntitlementStatus.PAID_ACTIVE.value
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_rv05_known_projection_mismatch_does_not_rebind(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = await _seed_tenant(session, site_url=f"https://r1-rv05-{uuid4().hex}.example.test")
            billing = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            await billing.upsert_projection(
                tenant_id=tenant.id,
                provider="fake",
                provider_customer_id="cus-expected",
                provider_subscription_id="sub-expected",
                status=BillingSubscriptionStatus.ACTIVE,
                current_period_end=_NOW + timedelta(days=14),
                past_due_since=None,
                provider_event_id="evt-seed",
                event_position=_NOW - timedelta(days=1),
            )
            await session.commit()
            tenant_id = tenant.id

        session = session_factory()
        billing = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
        provider = _MismatchCustomerProvider(
            tenant_id=tenant_id,
            customer_id="cus-expected",
            subscription_id="sub-expected",
            session=session,
        )
        try:
            report = await reconcile(
                billing,
                provider,
                entitlement_service=TenantEntitlementService(
                    session, plan_allowances=_PLAN_ALLOWANCES, clock=lambda: _NOW
                ),
                config=_config(),
                clock=lambda: _NOW,
                sleeper=_no_sleep,
                environment="sandbox",
                seller_account=_SELLER,
            )
        finally:
            await session.close()

        assert report.exit_code == 1
        assert report.failed >= 1

        async with session_factory() as session:
            billing = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            projection = await billing.get_projection(tenant_id, provider="fake")
            assert projection is not None
            assert projection.provider_customer_id == "cus-expected"
            assert projection.last_event_id == "evt-seed"
            assert await _entitlement_status(session, tenant_id) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_rv08_missing_event_position_quarantines_without_entitlement(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = await _seed_tenant(session, site_url=f"https://r1-rv08-{uuid4().hex}.example.test")
            await session.commit()
            tenant_id = tenant.id

        session = session_factory()
        inner = BillingRepository(session, environment="sandbox", seller_account=_SELLER)

        class _TenantAwareRepository:
            def __init__(self, wrapped: BillingRepository, tenants: set[UUID]) -> None:
                self._wrapped = wrapped
                self.tenants = tenants

            @property
            def session(self) -> AsyncSession:
                return self._wrapped.session

            def __getattr__(self, name: str):
                return getattr(self._wrapped, name)

        billing = _TenantAwareRepository(inner, {tenant_id})
        recovery = BillingReconciliationRepository(session)
        provider = _MissingPositionProvider(tenant_id=tenant_id, session=session)
        try:
            report = await reconcile(
                billing,
                provider,
                entitlement_service=TenantEntitlementService(
                    session, plan_allowances=_PLAN_ALLOWANCES, clock=lambda: _NOW
                ),
                recovery_repository=recovery,
                config=_config(provider_timeout_s=8.0),
                clock=lambda: _NOW,
                sleeper=_no_sleep,
                environment="sandbox",
                seller_account=_SELLER,
            )
        finally:
            await session.close()

        assert provider.create_calls == []
        assert report.exit_code == 0

        async with session_factory() as session:
            recovery = BillingReconciliationRepository(session)
            record = await recovery.get_quarantine(
                ReconciliationCursorKey(
                    provider="fake",
                    environment="sandbox",
                    seller_account=_SELLER,
                    kind=ReconciliationKind.SUBSCRIPTIONS,
                ),
                "sub-no-pos",
            )
            assert record is not None
            billing = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            assert await billing.get_projection(tenant_id, provider="fake") is None
            assert await _entitlement_status(session, tenant_id) is None
    finally:
        await engine.dispose()
