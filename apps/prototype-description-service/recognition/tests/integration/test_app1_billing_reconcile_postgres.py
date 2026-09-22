"""PostgreSQL C0/N1 proof for the R1 billing reconcile worker.

Exercises the landed namespaced BillingRepository plus the real worker with
an offline provider double. Skip is missing release evidence, not a passing
result. IDENTITY_PG_REQUIRED=1 fails instead of skip.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.portal_billing import TenantEntitlement
from db.models.tenant import Tenant
from db.tenant_context import set_tenant_context
from recognition.application.services.tenant_entitlement_service import TenantEntitlementService
from recognition.domain.billing_work_lease import BillingWorkLeaseConflictError
from recognition.domain.portal_contracts import (
    BillingState,
    BillingSubscriptionStatus,
    EntitlementStatus,
    WebhookInboxStatus,
)
from recognition.infrastructure.repositories.billing_repository import BillingRepository
from recognition.tests.integration.test_app1_billing_recovery_postgres import _async_url
from recognition.tests.unit.test_app1_billing_reconcile import _config, _no_sleep
from scripts.billing_reconcile import reconcile

pytestmark = pytest.mark.pg

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")
_NOW = datetime(2026, 9, 22, 19, 0, tzinfo=UTC)
_SELLER = "org_sandbox"
_OTHER_SELLER = "org_other"
_PLAN_ALLOWANCES = {"paid": 50}
StealHook = Callable[[], Awaitable[None]]


def _n1_methods_present(repository: object) -> bool:
    required = (
        "list_known_projections",
        "claim_reconcile_item",
        "lock_reconcile_item",
        "finish_reconcile_item",
    )
    return all(callable(getattr(repository, name, None)) for name in required)


class _ObservingRepository:
    """Record N1 seam calls while delegating to the real namespaced repository."""

    def __init__(self, inner: BillingRepository) -> None:
        self._inner = inner
        self.claims: list[dict[str, object]] = []
        self.locks: list[object] = []
        self.finishes: list[object] = []

    @property
    def session(self) -> AsyncSession:
        return self._inner.session

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    async def list_known_projections(self, *, provider: str, limit: int, after_tenant_id=None):
        return await self._inner.list_known_projections(
            provider=provider,
            limit=limit,
            after_tenant_id=after_tenant_id,
        )

    async def claim_reconcile_item(self, *, provider: str, kind: str, remote_id: str, owner: str, lease_ttl, now):
        lease = await self._inner.claim_reconcile_item(
            provider=provider,
            kind=kind,
            remote_id=remote_id,
            owner=owner,
            lease_ttl=lease_ttl,
            now=now,
        )
        self.claims.append(
            {
                "kind": kind,
                "remote_id": remote_id,
                "owner": owner,
                "lease": lease,
                "in_txn": self.session.in_transaction(),
            }
        )
        return lease

    async def lock_reconcile_item(self, lease, *, now) -> None:
        await self._inner.lock_reconcile_item(lease, now=now)
        self.locks.append(lease)

    async def finish_reconcile_item(self, lease, *, now) -> None:
        await self._inner.finish_reconcile_item(lease, now=now)
        self.finishes.append(lease)


class _Provider:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        customer_id: str,
        subscription_id: str,
        session: AsyncSession,
        steal: StealHook | None = None,
    ) -> None:
        self.environment = "sandbox"
        self.seller_account = _SELLER
        self.tenant_id = tenant_id
        self.customer_id = customer_id
        self.subscription_id = subscription_id
        self.session = session
        self.steal = steal
        self.calls: list[dict[str, object]] = []
        self.create_calls: list[dict[str, object]] = []

    async def retrieve_state(
        self,
        *,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        request_timeout: float,
    ):
        self.calls.append(
            {
                "customer_id": provider_customer_id,
                "subscription_id": provider_subscription_id,
                "timeout": request_timeout,
                "txn_open": bool(self.session.in_transaction()),
            }
        )
        if self.steal is not None:
            await self.steal()
            self.steal = None
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

    async def create_checkout_session(self, **kwargs: object) -> object:
        self.create_calls.append(dict(kwargs))
        raise AssertionError("worker must not POST checkout")


def _entitlement(session: AsyncSession) -> TenantEntitlementService:
    return TenantEntitlementService(session, plan_allowances=_PLAN_ALLOWANCES, clock=lambda: _NOW)


async def _seed_tenant(session: AsyncSession, *, site_url: str) -> Tenant:
    tenant = Tenant(site_url=site_url)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)
    return tenant


async def _seed_inbox(
    repo: BillingRepository,
    *,
    tenant_id: UUID,
    event_id: str,
    customer_id: str,
    subscription_id: str,
) -> None:
    inserted = await repo.record_webhook(
        provider="fake",
        provider_event_id=event_id,
        event_type="subscription.active",
        signature_verified=True,
        payload={
            "type": "subscription.active",
            "data": {
                "tenant_id": str(tenant_id),
                "customer_id": customer_id,
                "subscription_id": subscription_id,
            },
        },
    )
    assert inserted is True


async def _seed_projection(
    repo: BillingRepository,
    *,
    tenant_id: UUID,
    customer_id: str,
    subscription_id: str,
    event_id: str,
    status: BillingSubscriptionStatus = BillingSubscriptionStatus.ACTIVE,
    position: datetime | None = None,
) -> None:
    await set_tenant_context(repo.session, tenant_id)
    applied = await repo.upsert_projection(
        tenant_id=tenant_id,
        provider="fake",
        provider_customer_id=customer_id,
        provider_subscription_id=subscription_id,
        status=status,
        current_period_end=_NOW + timedelta(days=14),
        past_due_since=None,
        provider_event_id=event_id,
        event_position=position or (_NOW - timedelta(days=1)),
    )
    assert applied is True


async def _entitlement_status(session: AsyncSession, tenant_id: UUID) -> str | None:
    await set_tenant_context(session, tenant_id)
    result = await session.execute(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id).limit(1))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return row.status if isinstance(row.status, str) else row.status.value


async def _steal(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    kind: str,
    remote_id: str,
) -> None:
    async with session_factory() as thief_session:
        thief = BillingRepository(thief_session, environment="sandbox", seller_account=_SELLER)
        stolen = await thief.claim_reconcile_item(
            provider="fake",
            kind=kind,
            remote_id=remote_id,
            owner="thief",
            lease_ttl=timedelta(seconds=30),
            now=_NOW + timedelta(seconds=31),
        )
        await thief_session.commit()
    assert stolen is not None
    assert stolen.fence >= 2


async def _run_worker(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    customer_id: str,
    subscription_id: str,
    steal: StealHook | None = None,
):
    session = session_factory()
    inner = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
    observer = _ObservingRepository(inner)
    provider = _Provider(
        tenant_id=tenant_id,
        customer_id=customer_id,
        subscription_id=subscription_id,
        session=session,
        steal=steal,
    )
    entitlement = _entitlement(session)
    try:
        report = await reconcile(
            observer,
            provider,
            entitlement_service=entitlement,
            config=_config(),
            clock=lambda: _NOW,
            sleeper=_no_sleep,
            environment="sandbox",
            seller_account=_SELLER,
        )
    finally:
        await session.close()
    return report, observer, provider


def test_postgres_n1_methods_are_production_wired() -> None:
    params = BillingRepository.__init__.__code__.co_varnames
    assert "environment" in params
    assert "seller_account" in params
    assert _n1_methods_present(BillingRepository)


@pytest.mark.asyncio
async def test_postgres_real_repo_claim_commit_before_get_apply_finish(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = await _seed_tenant(session, site_url=f"https://r1-happy-{uuid4().hex}.example.test")
            repo = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            await _seed_inbox(
                repo,
                tenant_id=tenant.id,
                event_id="evt-admitted",
                customer_id="cus-admitted",
                subscription_id="sub-admitted",
            )
            await session.commit()
            tenant_id = tenant.id

        report, observer, provider = await _run_worker(
            session_factory,
            tenant_id=tenant_id,
            customer_id="cus-admitted",
            subscription_id="sub-admitted",
        )

        assert report.exit_code == 0
        assert report.n1_methods_available is True
        assert provider.create_calls == []
        assert provider.calls
        assert all(call["txn_open"] is False for call in provider.calls)
        assert any(claim["kind"] == "inbox" and claim["in_txn"] is True for claim in observer.claims)
        assert observer.locks
        assert observer.finishes
        assert any(claim["lease"] is not None for claim in observer.claims)

        async with session_factory() as session:
            repo = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            inbox = await repo.get_webhook(provider="fake", provider_event_id="evt-admitted")
            assert inbox is not None
            assert inbox.status == WebhookInboxStatus.PROCESSED.value
            projection = await repo.get_projection(tenant_id, provider="fake")
            assert projection is not None
            assert projection.environment == "sandbox"
            assert projection.seller_account == _SELLER
            assert projection.provider_subscription_id == "sub-admitted"
            assert await _entitlement_status(session, tenant_id) == EntitlementStatus.PAID_ACTIVE.value
            finished = observer.finishes[0]
            with pytest.raises(BillingWorkLeaseConflictError):
                await repo.lock_reconcile_item(finished, now=_NOW)
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_stale_inbox_lease_refuses_paid_and_failure_marks(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = await _seed_tenant(session, site_url=f"https://r1-stale-inbox-{uuid4().hex}.example.test")
            repo = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            await _seed_inbox(
                repo,
                tenant_id=tenant.id,
                event_id="evt-stale",
                customer_id="cus-stale",
                subscription_id="sub-stale",
            )
            await session.commit()
            tenant_id = tenant.id

        report, observer, provider = await _run_worker(
            session_factory,
            tenant_id=tenant_id,
            customer_id="cus-stale",
            subscription_id="sub-stale",
            steal=lambda: _steal(session_factory, kind="inbox", remote_id="evt-stale"),
        )

        assert report.failed >= 1
        assert provider.calls
        assert all(call["txn_open"] is False for call in provider.calls)
        assert any(claim["kind"] == "inbox" for claim in observer.claims)
        assert observer.finishes == []

        async with session_factory() as session:
            repo = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            inbox = await repo.get_webhook(provider="fake", provider_event_id="evt-stale")
            assert inbox is not None
            assert inbox.status == WebhookInboxStatus.RECEIVED.value
            assert await repo.get_projection(tenant_id, provider="fake") is None
            assert await _entitlement_status(session, tenant_id) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_stale_projection_lease_refuses_paid_state(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = await _seed_tenant(session, site_url=f"https://r1-stale-proj-{uuid4().hex}.example.test")
            repo = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            await _seed_projection(
                repo,
                tenant_id=tenant.id,
                customer_id="cus-proj-stale",
                subscription_id="sub-proj-stale",
                event_id="evt-proj-seed",
            )
            await session.commit()
            tenant_id = tenant.id

        report, observer, provider = await _run_worker(
            session_factory,
            tenant_id=tenant_id,
            customer_id="cus-proj-stale",
            subscription_id="sub-proj-stale",
            steal=lambda: _steal(session_factory, kind="projection", remote_id="sub-proj-stale"),
        )

        assert provider.calls
        assert all(call["txn_open"] is False for call in provider.calls)
        assert any(claim["kind"] == "projection" for claim in observer.claims)
        assert observer.finishes == []

        async with session_factory() as session:
            repo = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            projection = await repo.get_projection(tenant_id, provider="fake")
            assert projection is not None
            assert projection.last_event_id == "evt-proj-seed"
            assert await _entitlement_status(session, tenant_id) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_namespace_isolation_on_real_repository(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            local_tenant = await _seed_tenant(session, site_url=f"https://r1-ns-local-{uuid4().hex}.example.test")
            foreign_tenant = await _seed_tenant(session, site_url=f"https://r1-ns-foreign-{uuid4().hex}.example.test")
            local = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            foreign = BillingRepository(session, environment="live", seller_account=_OTHER_SELLER)
            await _seed_inbox(
                local,
                tenant_id=local_tenant.id,
                event_id="evt-shared",
                customer_id="cus-local",
                subscription_id="sub-local",
            )
            await _seed_inbox(
                foreign,
                tenant_id=foreign_tenant.id,
                event_id="evt-shared",
                customer_id="cus-foreign",
                subscription_id="sub-foreign",
            )
            await _seed_projection(
                foreign,
                tenant_id=foreign_tenant.id,
                customer_id="cus-foreign",
                subscription_id="sub-foreign",
                event_id="evt-foreign-seed",
            )
            await session.commit()
            local_id = local_tenant.id
            foreign_id = foreign_tenant.id

            known_local = await local.list_known_projections(provider="fake", limit=50)
            known_foreign = await foreign.list_known_projections(provider="fake", limit=50)
            assert all(row.seller_account == _SELLER for row in known_local)
            assert {row.tenant_id for row in known_foreign} == {foreign_id}

        report, observer, provider = await _run_worker(
            session_factory,
            tenant_id=local_id,
            customer_id="cus-local",
            subscription_id="sub-local",
        )

        assert report.exit_code == 0
        assert provider.create_calls == []
        assert all(getattr(lease, "seller_account", _SELLER) == _SELLER for lease in observer.locks)
        assert all(getattr(lease, "environment", "sandbox") == "sandbox" for lease in observer.locks)

        async with session_factory() as session:
            local = BillingRepository(session, environment="sandbox", seller_account=_SELLER)
            foreign = BillingRepository(session, environment="live", seller_account=_OTHER_SELLER)
            local_inbox = await local.get_webhook(provider="fake", provider_event_id="evt-shared")
            foreign_inbox = await foreign.get_webhook(provider="fake", provider_event_id="evt-shared")
            assert local_inbox is not None
            assert local_inbox.status == WebhookInboxStatus.PROCESSED.value
            assert foreign_inbox is not None
            assert foreign_inbox.status == WebhookInboxStatus.RECEIVED.value
            foreign_projection = await foreign.get_projection(foreign_id, provider="fake")
            assert foreign_projection is not None
            assert foreign_projection.last_event_id == "evt-foreign-seed"
            assert await local.get_projection(foreign_id, provider="fake") is None
            assert await _entitlement_status(session, foreign_id) is None
            assert await _entitlement_status(session, local_id) == EntitlementStatus.PAID_ACTIVE.value
    finally:
        await engine.dispose()
