"""PostgreSQL C0 fence/progress proof for the R1 billing reconcile worker.

N1 item leases are not claimed as production-integrated here. The injected
factory supplies a fenced N1 fake around real admitted Tenant + projection
rows and the landed C0 BillingReconciliationRepository. Skip is missing
release evidence, not a passing result.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import BillingSubscriptionProjection, Tenant
from db.tenant_context import set_tenant_context
from recognition.domain.portal_contracts import (
    BillingState,
    BillingSubscriptionStatus,
    EnumerationPage,
    ReconciliationCursorKey,
    ReconciliationKind,
)
from recognition.infrastructure.repositories.billing_reconciliation_repository import (
    BillingReconciliationRepository,
)
from recognition.infrastructure.repositories.billing_repository import BillingRepository
from recognition.tests.integration.test_app1_billing_recovery_postgres import _async_url
from recognition.tests.unit.test_app1_billing_reconcile import _WorkLease, _config, _no_sleep
from scripts.billing_reconcile import reconcile

pytestmark = pytest.mark.pg

_NOW = datetime(2026, 9, 22, 19, 0, tzinfo=UTC)
_SELLER = "org_sandbox"


def _n1_methods_present(repository: object) -> bool:
    required = (
        "list_known_projections",
        "claim_reconcile_item",
        "lock_reconcile_item",
        "finish_reconcile_item",
    )
    return all(callable(getattr(repository, name, None)) for name in required)


class _Runtime:
    def __init__(self, session: AsyncSession, repository: object, recovery: object) -> None:
        self.session = session
        self.repository = repository
        self.recovery_repository = recovery
        self.n1_integrated = _n1_methods_present(BillingRepository)

    async def close(self) -> None:
        await self.session.close()


class _N1Shim:
    """Fenced N1 seam used until BillingRepository grows the frozen methods."""

    def __init__(self, inner: BillingRepository, *, environment: str, seller_account: str) -> None:
        self._inner = inner
        self.environment = environment
        self.seller_account = seller_account
        self._fences: dict[tuple[str, str], int] = {}
        self.session = inner.session
        self.tenants: set = set()

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    async def list_known_projections(self, *, provider: str, limit: int, after_tenant_id=None):
        method = getattr(self._inner, "list_known_projections", None)
        if callable(method):
            return await method(provider=provider, limit=limit, after_tenant_id=after_tenant_id)
        rows = []
        for tenant_id in sorted(self.tenants, key=str):
            if after_tenant_id is not None and tenant_id <= after_tenant_id:
                continue
            projection = await self._inner.get_projection(tenant_id, provider=provider)
            if projection is None:
                continue
            environment = getattr(projection, "environment", None)
            seller = getattr(projection, "seller_account", None)
            if environment != self.environment or seller != self.seller_account:
                continue
            rows.append(projection)
            if len(rows) >= limit:
                break
        return rows

    async def claim_reconcile_item(self, *, provider: str, kind: str, remote_id: str, owner: str, lease_ttl, now):
        method = getattr(self._inner, "claim_reconcile_item", None)
        if callable(method):
            return await method(
                provider=provider,
                kind=kind,
                remote_id=remote_id,
                owner=owner,
                lease_ttl=lease_ttl,
                now=now,
            )
        key = (kind, remote_id)
        fence = self._fences.get(key, 0) + 1
        self._fences[key] = fence
        return _WorkLease(
            provider=provider,
            environment=self.environment,
            seller_account=self.seller_account,
            kind=kind,
            remote_id=remote_id,
            owner=owner,
            fence=fence,
            lease_until=now + lease_ttl,
        )

    async def lock_reconcile_item(self, lease, *, now) -> None:
        method = getattr(self._inner, "lock_reconcile_item", None)
        if callable(method):
            await method(lease, now=now)
            return
        if getattr(lease, "fence", 0) != self._fences.get((lease.kind, lease.remote_id)):
            raise RuntimeError("stale reconcile lease")

    async def finish_reconcile_item(self, lease, *, now) -> None:
        method = getattr(self._inner, "finish_reconcile_item", None)
        if callable(method):
            await method(lease, now=now)


class _FakeProvider:
    def __init__(self, page: EnumerationPage, *, tenant_id, customer_id: str, subscription_id: str) -> None:
        self.pages = {None: page}
        self.environment = "sandbox"
        self.seller_account = _SELLER
        self.tenant_id = tenant_id
        self.customer_id = customer_id
        self.subscription_id = subscription_id
        self.enumerate_calls: list[dict[str, object]] = []

    async def retrieve_state(self, *, provider_customer_id: str, provider_subscription_id: str | None, request_timeout: float):
        return BillingState(
            tenant_id=self.tenant_id,
            status=BillingSubscriptionStatus.ACTIVE,
            provider_customer_id=provider_customer_id,
            current_period_end=_NOW + timedelta(days=30),
            past_due_since=None,
            provider_subscription_id=provider_subscription_id,
            event_position=_NOW,
        )

    async def retrieve_checkout(self, *, provider_checkout_id: str, request_timeout: float):
        return {"id": provider_checkout_id, "status": "open"}

    async def enumerate_subscriptions(self, *, cursor: str | None, limit: int, request_timeout: float):
        self.enumerate_calls.append({"cursor": cursor, "limit": limit, "timeout": request_timeout})
        return self.pages[cursor]

    async def create_checkout_session(self, **kwargs: object) -> object:
        raise AssertionError("worker must not POST checkout")


class _Entitlement:
    def __init__(self) -> None:
        self.states: list[BillingState] = []

    async def apply_billing_state(self, tenant_id, state: BillingState) -> None:
        self.states.append(state)


@pytest.mark.asyncio
async def test_postgres_c0_orphan_fence_with_fake_provider_and_admitted_tenant(pg_empty_engine) -> None:
    import importlib

    migration = importlib.import_module("db.migrations.versions.001_identity_schema")
    with pg_empty_engine.begin() as conn:
        migration.heal(conn)

    engine = create_async_engine(_async_url(pg_empty_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    now = _NOW
    try:
        async with session_factory() as session:
            tenant = Tenant(site_url=f"https://reconcile-r1-{uuid4().hex}.example.test")
            session.add(tenant)
            await session.flush()
            await set_tenant_context(session, tenant.id)
            session.add(
                BillingSubscriptionProjection(
                    tenant_id=tenant.id,
                    provider="fake",
                    provider_customer_id="cus-admitted",
                    provider_subscription_id="sub-admitted",
                    status=BillingSubscriptionStatus.ACTIVE.value,
                    environment="sandbox",
                    seller_account=_SELLER,
                    last_event_id="evt-seed",
                    updated_at=now - timedelta(days=1),
                )
            )
            await session.commit()
            tenant_id = tenant.id

        page = EnumerationPage(
            items=(
                BillingState(
                    tenant_id=tenant_id,
                    status=BillingSubscriptionStatus.ACTIVE,
                    provider_customer_id="cus-admitted",
                    current_period_end=now + timedelta(days=30),
                    past_due_since=None,
                    provider_subscription_id="sub-admitted",
                    event_position=now,
                ),
            ),
            next_cursor=None,
            exhausted=True,
        )
        provider = _FakeProvider(
            page,
            tenant_id=tenant_id,
            customer_id="cus-admitted",
            subscription_id="sub-admitted",
        )
        entitlement = _Entitlement()
        session = session_factory()
        inner = BillingRepository(session)
        shim = _N1Shim(inner, environment="sandbox", seller_account=_SELLER)
        shim.tenants.add(tenant_id)
        recovery = BillingReconciliationRepository(session)
        runtime = _Runtime(session, shim, recovery)
        try:
            report = await reconcile(
                runtime.repository,
                provider,
                entitlement_service=entitlement,
                recovery_repository=runtime.recovery_repository,
                config=_config(),
                clock=lambda: now,
                sleeper=_no_sleep,
            )
            await session.commit()
        finally:
            await runtime.close()

        assert report.exit_code == 0
        assert provider.enumerate_calls
        assert entitlement.states
        assert runtime.n1_integrated is False

        async with session_factory() as session:
            recovery = BillingReconciliationRepository(session)
            key = ReconciliationCursorKey(
                provider="fake",
                environment="sandbox",
                seller_account=_SELLER,
                kind=ReconciliationKind.SUBSCRIPTIONS,
            )
            lease = await recovery.acquire_lease(
                key,
                owner="inspector",
                lease_ttl=timedelta(seconds=30),
                now=now + timedelta(seconds=31),
            )
            await session.commit()
        assert lease is not None
        assert lease.exhausted is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_injected_factory_is_required_until_n1_lands(pg_empty_engine) -> None:
    inner_params = inspect.signature(BillingRepository.__init__).parameters
    n1_ctor = "environment" in inner_params and "seller_account" in inner_params
    if n1_ctor and _n1_methods_present(BillingRepository):
        pytest.fail("N1 landed; coordinator must run the production integration receipt")
    assert not _n1_methods_present(BillingRepository)
