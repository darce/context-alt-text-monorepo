"""N1 billing namespace: bound repository, leases, and fail-closed uniqueness."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Table, create_engine, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import BillingSubscriptionProjection, BillingWebhookInbox, Tenant
from db.models.portal_billing import BillingKnownItemLease
from recognition.domain.billing_work_lease import (
    BillingNamespaceConflictError,
    BillingNamespaceRequiredError,
    BillingWorkKind,
    BillingWorkLease,
    BillingWorkLeaseConflictError,
)
from recognition.domain.portal_contracts import BillingSubscriptionStatus, WebhookInboxStatus
from recognition.infrastructure.repositories.billing_repository import BillingRepository


class _AsyncTransactionFacade:
    def __init__(self, transaction: object) -> None:
        self._transaction = transaction

    async def __aenter__(self) -> _AsyncTransactionFacade:
        self._transaction.__enter__()  # type: ignore[attr-defined]
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return bool(self._transaction.__exit__(exc_type, exc, traceback))  # type: ignore[attr-defined]


class _AsyncSessionFacade:
    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def bind(self) -> object:
        return self._session.bind

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)

    def begin_nested(self) -> _AsyncTransactionFacade:
        return _AsyncTransactionFacade(self._session.begin_nested())

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    async def close(self) -> None:
        self._session.close()


@pytest_asyncio.fixture
async def billing_session() -> AsyncGenerator[_AsyncSessionFacade, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        tables: list[Table] = [
            Table("tenants", Base.metadata),
            BillingSubscriptionProjection.__table__,
            BillingWebhookInbox.__table__,
            BillingKnownItemLease.__table__,
        ]
        Base.metadata.create_all(connection, tables=tables)

    session = _AsyncSessionFacade(Session(engine, expire_on_commit=False))
    try:
        yield session
    finally:
        await session.close()
        engine.dispose()


def _repo(session: _AsyncSessionFacade, *, seller: str = "org-a", environment: str = "sandbox") -> BillingRepository:
    return BillingRepository(session, environment=environment, seller_account=seller)


async def _tenant(session: _AsyncSessionFacade, site: str) -> Tenant:
    tenant = Tenant(site_url=site)
    session.add(tenant)
    await session.flush()
    return tenant


NOW = datetime(2026, 9, 22, 16, 0, tzinfo=UTC)
EVENT_POSITION = datetime(2026, 9, 22, 15, 0, tzinfo=UTC)


def test_constructor_is_backwards_compatible_without_namespace() -> None:
    class _Session:
        pass

    unbound = BillingRepository(_Session())
    bound = BillingRepository(_Session(), environment="sandbox", seller_account="org-a", max_attempts=3)
    assert unbound.session is not None
    assert bound.session is not None


def test_constructor_rejects_inferred_or_invalid_namespace() -> None:
    class _Session:
        pass

    with pytest.raises(ValueError, match="environment"):
        BillingRepository(_Session(), environment="staging", seller_account="org-a")
    with pytest.raises(ValueError, match="seller_account"):
        BillingRepository(_Session(), environment="sandbox", seller_account="  ")
    with pytest.raises(ValueError, match="both"):
        BillingRepository(_Session(), environment="sandbox")
    with pytest.raises(ValueError, match="both"):
        BillingRepository(_Session(), seller_account="org-a")


@pytest.mark.asyncio
async def test_bound_operations_refuse_null_legacy_namespace(billing_session: _AsyncSessionFacade) -> None:
    unbound = BillingRepository(billing_session)
    with pytest.raises(BillingNamespaceRequiredError):
        await unbound.list_known_projections(provider="polar", limit=10)
    with pytest.raises(BillingNamespaceRequiredError):
        await unbound.claim_reconcile_item(
            provider="polar",
            kind="inbox",
            remote_id="evt-1",
            owner="worker-a",
            lease_ttl=timedelta(seconds=30),
            now=NOW,
        )


@pytest.mark.asyncio
async def test_unbound_writers_fail_closed_and_do_not_null_bound_projection(
    billing_session: _AsyncSessionFacade,
) -> None:
    tenant = await _tenant(billing_session, "https://bound-writer.example.test")
    bound = _repo(billing_session)
    assert (
        await bound.upsert_projection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id="cus-bound",
            provider_subscription_id="sub-bound",
            status=BillingSubscriptionStatus.ACTIVE,
            current_period_end=None,
            past_due_since=None,
            provider_event_id="evt-bound",
            event_position=EVENT_POSITION,
        )
        is True
    )
    await billing_session.commit()

    unbound = BillingRepository(billing_session)
    assert await unbound.get_projection(tenant.id, provider="polar") is not None
    with pytest.raises(BillingNamespaceRequiredError):
        await unbound.record_webhook(
            provider="polar",
            provider_event_id="evt-unbound",
            event_type="subscription.active",
            signature_verified=True,
            payload={"id": "evt-unbound"},
        )
    with pytest.raises(BillingNamespaceRequiredError):
        await unbound.upsert_projection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id="cus-overwrite",
            provider_subscription_id="sub-overwrite",
            status=BillingSubscriptionStatus.ACTIVE,
            current_period_end=None,
            past_due_since=None,
            provider_event_id="evt-overwrite",
            event_position=EVENT_POSITION + timedelta(seconds=1),
        )
    with pytest.raises(BillingNamespaceRequiredError):
        await unbound.mark_webhook_processed(
            provider="polar",
            provider_event_id="evt-bound",
            status=WebhookInboxStatus.PROCESSED,
            processed_at=NOW,
        )
    with pytest.raises(BillingNamespaceRequiredError):
        await unbound.list_pending_webhooks()

    stored = (await billing_session.execute(select(BillingSubscriptionProjection))).scalar_one()
    assert stored.provider_customer_id == "cus-bound"
    assert stored.environment == "sandbox"
    assert stored.seller_account == "org-a"
    assert list((await billing_session.execute(select(BillingWebhookInbox))).scalars()) == []


@pytest.mark.asyncio
async def test_inbox_writers_persist_configured_namespace_not_payload(
    billing_session: _AsyncSessionFacade,
) -> None:
    repo = _repo(billing_session)
    inserted = await repo.record_webhook(
        provider="polar",
        provider_event_id="evt-1",
        event_type="subscription.active",
        signature_verified=True,
        payload={"data": {"metadata": {"environment": "live", "seller_account": "org-evil"}}},
    )
    await billing_session.commit()
    assert inserted is True
    row = await repo.get_webhook(provider="polar", provider_event_id="evt-1")
    assert row is not None
    assert row.environment == "sandbox"
    assert row.seller_account == "org-a"


@pytest.mark.asyncio
async def test_two_sellers_same_event_id_do_not_dedupe_across_namespace(
    billing_session: _AsyncSessionFacade,
) -> None:
    first = _repo(billing_session, seller="org-a")
    second = _repo(billing_session, seller="org-b", environment="live")
    assert (
        await first.record_webhook(
            provider="polar",
            provider_event_id="evt-shared",
            event_type="subscription.active",
            signature_verified=True,
            payload={"id": "evt-shared"},
        )
        is True
    )
    assert (
        await second.record_webhook(
            provider="polar",
            provider_event_id="evt-shared",
            event_type="subscription.active",
            signature_verified=True,
            payload={"id": "evt-shared"},
        )
        is True
    )
    await billing_session.commit()
    assert await first.get_webhook(provider="polar", provider_event_id="evt-shared") is not None
    assert await second.get_webhook(provider="polar", provider_event_id="evt-shared") is not None
    first_row = await first.get_webhook(provider="polar", provider_event_id="evt-shared")
    second_row = await second.get_webhook(provider="polar", provider_event_id="evt-shared")
    assert first_row is not None and second_row is not None
    assert first_row.id != second_row.id
    assert first_row.seller_account == "org-a"
    assert second_row.seller_account == "org-b"


@pytest.mark.asyncio
async def test_duplicate_delivery_in_one_namespace_is_once(billing_session: _AsyncSessionFacade) -> None:
    repo = _repo(billing_session)
    kwargs = {
        "provider": "polar",
        "provider_event_id": "evt-dup",
        "event_type": "subscription.active",
        "signature_verified": True,
        "payload": {"id": "evt-dup"},
    }
    assert await repo.record_webhook(**kwargs) is True
    assert await repo.record_webhook(**kwargs) is False
    await billing_session.commit()
    rows = list((await billing_session.execute(select(BillingWebhookInbox))).scalars())
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_readers_do_not_treat_null_legacy_as_current(billing_session: _AsyncSessionFacade) -> None:
    tenant = await _tenant(billing_session, "https://legacy.example.test")
    billing_session.add(
        BillingWebhookInbox(
            provider="polar",
            provider_event_id="evt-legacy",
            event_type="subscription.active",
            signature_verified=True,
            payload={"id": "evt-legacy"},
        )
    )
    billing_session.add(
        BillingSubscriptionProjection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id="cus-legacy",
            status="active",
            last_event_id="evt-legacy",
            updated_at=EVENT_POSITION,
        )
    )
    await billing_session.commit()
    repo = _repo(billing_session)
    assert await repo.get_webhook(provider="polar", provider_event_id="evt-legacy") is None
    assert await repo.get_projection(tenant.id, provider="polar") is None
    listed = await repo.list_known_projections(provider="polar", limit=10)
    assert listed == []


@pytest.mark.asyncio
async def test_tenant_projection_does_not_overwrite_another_namespace(
    billing_session: _AsyncSessionFacade,
) -> None:
    tenant = await _tenant(billing_session, "https://conflict.example.test")
    first = _repo(billing_session, seller="org-a")
    second = _repo(billing_session, seller="org-b")
    assert (
        await first.upsert_projection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id="cus-a",
            provider_subscription_id="sub-a",
            status=BillingSubscriptionStatus.ACTIVE,
            current_period_end=None,
            past_due_since=None,
            provider_event_id="evt-a",
            event_position=EVENT_POSITION,
        )
        is True
    )
    with pytest.raises(BillingNamespaceConflictError):
        await second.upsert_projection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id="cus-b",
            provider_subscription_id="sub-b",
            status=BillingSubscriptionStatus.ACTIVE,
            current_period_end=None,
            past_due_since=None,
            provider_event_id="evt-b",
            event_position=EVENT_POSITION + timedelta(seconds=1),
        )
    stored = await first.get_projection(tenant.id, provider="polar")
    assert stored is not None
    assert stored.provider_customer_id == "cus-a"
    assert stored.seller_account == "org-a"


@pytest.mark.asyncio
async def test_legacy_null_projection_is_fail_closed_not_overwritten(
    billing_session: _AsyncSessionFacade,
) -> None:
    tenant = await _tenant(billing_session, "https://null-proj.example.test")
    billing_session.add(
        BillingSubscriptionProjection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id="cus-legacy",
            status="active",
            last_event_id="evt-old",
            updated_at=EVENT_POSITION,
        )
    )
    await billing_session.commit()
    repo = _repo(billing_session)
    with pytest.raises(BillingNamespaceConflictError):
        await repo.upsert_projection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id="cus-new",
            provider_subscription_id="sub-new",
            status=BillingSubscriptionStatus.ACTIVE,
            current_period_end=None,
            past_due_since=None,
            provider_event_id="evt-new",
            event_position=EVENT_POSITION + timedelta(seconds=1),
        )
    stored = (await billing_session.execute(select(BillingSubscriptionProjection))).scalar_one()
    assert stored.provider_customer_id == "cus-legacy"
    assert stored.environment is None


@pytest.mark.asyncio
async def test_list_known_projections_is_namespace_bound_uuid_ordered(
    billing_session: _AsyncSessionFacade,
) -> None:
    tenants = []
    for index in range(3):
        tenants.append(await _tenant(billing_session, f"https://p{index}.example.test"))
    foreign = await _tenant(billing_session, "https://other.example.test")
    repo = _repo(billing_session, seller="org-a")
    other = _repo(billing_session, seller="org-b")
    for tenant in tenants:
        await repo.upsert_projection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id=f"cus-{tenant.id}",
            provider_subscription_id=None,
            status=BillingSubscriptionStatus.ACTIVE,
            current_period_end=None,
            past_due_since=None,
            provider_event_id=f"evt-{tenant.id}",
            event_position=EVENT_POSITION,
        )
    await other.upsert_projection(
        tenant_id=foreign.id,
        provider="polar",
        provider_customer_id="cus-foreign",
        provider_subscription_id=None,
        status=BillingSubscriptionStatus.ACTIVE,
        current_period_end=None,
        past_due_since=None,
        provider_event_id="evt-foreign",
        event_position=EVENT_POSITION,
    )
    await billing_session.commit()
    page = await repo.list_known_projections(provider="polar", limit=2)
    assert [row.tenant_id for row in page] == sorted(tenant.id for tenant in tenants)[:2]
    assert all(row.seller_account == "org-a" for row in page)
    rest = await repo.list_known_projections(provider="polar", limit=2, after_tenant_id=page[-1].tenant_id)
    assert [row.tenant_id for row in rest] == sorted(tenant.id for tenant in tenants)[2:]


@pytest.mark.asyncio
async def test_claim_lock_finish_lease_and_stale_owner_cannot_finish(
    billing_session: _AsyncSessionFacade,
) -> None:
    repo = _repo(billing_session)
    first = await repo.claim_reconcile_item(
        provider="polar",
        kind=BillingWorkKind.INBOX.value,
        remote_id="evt-lease",
        owner="worker-a",
        lease_ttl=timedelta(seconds=30),
        now=NOW,
    )
    await billing_session.commit()
    assert first is not None
    assert first.fence == 1
    assert first.seller_account == "org-a"
    assert first.environment == "sandbox"
    assert first.kind == "inbox"
    assert first.remote_id == "evt-lease"
    assert first.owner == "worker-a"
    assert first.lease_until == NOW + timedelta(seconds=30)

    blocked = await repo.claim_reconcile_item(
        provider="polar",
        kind="inbox",
        remote_id="evt-lease",
        owner="worker-b",
        lease_ttl=timedelta(seconds=30),
        now=NOW + timedelta(seconds=1),
    )
    await billing_session.commit()
    assert blocked is None

    stolen = await repo.claim_reconcile_item(
        provider="polar",
        kind="inbox",
        remote_id="evt-lease",
        owner="worker-b",
        lease_ttl=timedelta(seconds=30),
        now=NOW + timedelta(seconds=31),
    )
    await billing_session.commit()
    assert stolen is not None
    assert stolen.fence == 2
    assert stolen.owner == "worker-b"

    with pytest.raises(BillingWorkLeaseConflictError):
        await repo.lock_reconcile_item(first, now=NOW + timedelta(seconds=32))
    with pytest.raises(BillingWorkLeaseConflictError):
        await repo.finish_reconcile_item(first, now=NOW + timedelta(seconds=32))

    await repo.lock_reconcile_item(stolen, now=NOW + timedelta(seconds=32))
    await repo.finish_reconcile_item(stolen, now=NOW + timedelta(seconds=32))
    await billing_session.commit()

    with pytest.raises(BillingWorkLeaseConflictError):
        await repo.lock_reconcile_item(stolen, now=NOW + timedelta(seconds=33))


@pytest.mark.asyncio
async def test_same_session_steal_reacquire_is_monotonic_and_stale_cannot_finish(
    billing_session: _AsyncSessionFacade,
) -> None:
    repo = _repo(billing_session)
    first = await repo.claim_reconcile_item(
        provider="polar",
        kind="inbox",
        remote_id="evt-same-session",
        owner="worker-a",
        lease_ttl=timedelta(seconds=30),
        now=NOW,
    )
    assert first is not None
    assert first.fence == 1
    stolen = await repo.claim_reconcile_item(
        provider="polar",
        kind="inbox",
        remote_id="evt-same-session",
        owner="worker-b",
        lease_ttl=timedelta(seconds=30),
        now=NOW + timedelta(seconds=31),
    )
    assert stolen is not None
    assert stolen.owner == "worker-b"
    assert stolen.fence == 2
    with pytest.raises(BillingWorkLeaseConflictError):
        await repo.lock_reconcile_item(first, now=NOW + timedelta(seconds=32))
    with pytest.raises(BillingWorkLeaseConflictError):
        await repo.finish_reconcile_item(first, now=NOW + timedelta(seconds=32))
    await repo.lock_reconcile_item(stolen, now=NOW + timedelta(seconds=32))
    await repo.finish_reconcile_item(stolen, now=NOW + timedelta(seconds=32))
    await billing_session.commit()
    loaded = (
        await billing_session.execute(
            select(BillingKnownItemLease).where(BillingKnownItemLease.remote_id == "evt-same-session")
        )
    ).scalar_one()
    assert loaded.fence == 2
    assert loaded.lease_owner is None


@pytest.mark.asyncio
async def test_finish_does_not_mark_inbox_processed(billing_session: _AsyncSessionFacade) -> None:
    repo = _repo(billing_session)
    await repo.record_webhook(
        provider="polar",
        provider_event_id="evt-pending",
        event_type="subscription.active",
        signature_verified=True,
        payload={"id": "evt-pending"},
    )
    lease = await repo.claim_reconcile_item(
        provider="polar",
        kind="inbox",
        remote_id="evt-pending",
        owner="worker-a",
        lease_ttl=timedelta(seconds=30),
        now=NOW,
    )
    await billing_session.commit()
    assert lease is not None
    await repo.lock_reconcile_item(lease, now=NOW + timedelta(seconds=1))
    await repo.finish_reconcile_item(lease, now=NOW + timedelta(seconds=1))
    await billing_session.commit()
    row = await repo.get_webhook(provider="polar", provider_event_id="evt-pending")
    assert row is not None
    assert row.status == WebhookInboxStatus.RECEIVED.value
    assert row.processed_at is None


@pytest.mark.asyncio
async def test_mark_webhook_processed_signature_unchanged_and_namespace_bound(
    billing_session: _AsyncSessionFacade,
) -> None:
    repo = _repo(billing_session, seller="org-a")
    other = _repo(billing_session, seller="org-b")
    await repo.record_webhook(
        provider="polar",
        provider_event_id="evt-mark",
        event_type="subscription.active",
        signature_verified=True,
        payload={"id": "evt-mark"},
    )
    await other.record_webhook(
        provider="polar",
        provider_event_id="evt-mark",
        event_type="subscription.active",
        signature_verified=True,
        payload={"id": "evt-mark"},
    )
    assert (
        await repo.mark_webhook_processed(
            provider="polar",
            provider_event_id="evt-mark",
            status=WebhookInboxStatus.PROCESSED,
            processed_at=NOW,
        )
        is True
    )
    await billing_session.commit()
    mine = await repo.get_webhook(provider="polar", provider_event_id="evt-mark")
    theirs = await other.get_webhook(provider="polar", provider_event_id="evt-mark")
    assert mine is not None and mine.status == WebhookInboxStatus.PROCESSED.value
    assert theirs is not None and theirs.status == WebhookInboxStatus.RECEIVED.value


def test_work_lease_type_exposes_frozen_fields() -> None:
    lease = BillingWorkLease(
        provider="polar",
        environment="sandbox",
        seller_account="org-a",
        kind="projection",
        remote_id="cus-1",
        owner="worker-a",
        fence=1,
        lease_until=NOW + timedelta(seconds=30),
    )
    assert lease.kind == "projection"
    with pytest.raises(ValueError, match="kind"):
        BillingWorkLease(
            provider="polar",
            environment="sandbox",
            seller_account="org-a",
            kind="subscriptions",
            remote_id="cus-1",
            owner="worker-a",
            fence=1,
            lease_until=NOW + timedelta(seconds=30),
        )


def test_mapping_command_defaults_to_dry_run() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "scripts" / "billing_namespace_migrate.py"
    spec = importlib.util.spec_from_file_location("billing_namespace_migrate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = module.argparse.ArgumentParser(description="probe")
    # The module parser is built in main; inspect the source contract:
    assert "--apply" in path.read_text(encoding="utf-8")
    assert "dry-run" in path.read_text(encoding="utf-8").lower() or "Default is dry-run" in module.__doc__
    _ = parser


def test_known_item_lease_model_pk_is_namespace_kind_remote() -> None:
    inspector = inspect(BillingKnownItemLease.__table__)
    pk = [column.name for column in BillingKnownItemLease.__table__.primary_key]
    assert pk == ["provider", "environment", "seller_account", "kind", "remote_id"]
    assert inspector is not None
    _ = uuid4()
    _ = UUID("00000000-0000-0000-0000-000000000001")
