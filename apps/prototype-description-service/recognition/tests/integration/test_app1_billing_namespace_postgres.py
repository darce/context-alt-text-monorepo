"""PostgreSQL proof for N1 namespace isolation, drain, and known-item leases.

Skip is missing release evidence, not a passing result. IDENTITY_PG_REQUIRED=1
fails instead of skip. Role must be NOSUPERUSER / NOBYPASSRLS.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.tenant import Tenant
from db.tenant_context import set_tenant_context
from recognition.domain.billing_work_lease import (
    BillingNamespaceConflictError,
    BillingWorkLeaseConflictError,
)
from recognition.domain.portal_contracts import BillingSubscriptionStatus
from recognition.infrastructure.repositories.billing_repository import BillingRepository

pytestmark = pytest.mark.pg

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")
NOW = datetime(2026, 9, 22, 16, 0, tzinfo=UTC)


def _async_url(engine) -> str:
    return (
        engine.url.render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


@pytest.mark.asyncio
async def test_postgres_namespace_isolation_legacy_fail_closed_leases_and_rls(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        role = conn.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
        flags = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = 'billing_known_item_lease'"
            )
        ).one()
        policy = conn.execute(
            text(
                "SELECT pg_get_expr(p.polqual, p.polrelid) FROM pg_policy p "
                "JOIN pg_class c ON c.oid = p.polrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = 'billing_known_item_lease'"
            )
        ).scalar()
        inbox_unique = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT c.conname FROM pg_constraint c "
                    "JOIN pg_class t ON c.conrelid = t.oid "
                    "JOIN pg_namespace n ON t.relnamespace = n.oid "
                    "WHERE n.nspname = current_schema() AND t.relname = 'billing_webhook_inbox' "
                    "AND c.contype = 'u' ORDER BY c.conname"
                )
            )
        ]
        projection_unique = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT c.conname FROM pg_constraint c "
                    "JOIN pg_class t ON c.conrelid = t.oid "
                    "JOIN pg_namespace n ON t.relnamespace = n.oid "
                    "WHERE n.nspname = current_schema() AND t.relname = 'billing_subscription_projection' "
                    "AND c.contype = 'u' ORDER BY c.conname"
                )
            )
        ]

    assert role[1] is False
    assert role[2] is False
    assert flags == (True, True)
    assert policy is not None
    assert "app.bypass_rls" in policy
    assert "tenant_id" not in policy
    assert "uq_billing_webhook_inbox_provider_event" not in inbox_unique
    assert "uq_billing_webhook_inbox_provider_namespace_event" in inbox_unique
    assert "uq_billing_subscription_projection_provider_customer" not in projection_unique
    assert "uq_billing_subscription_projection_provider_namespace_customer" in projection_unique

    inspector = inspect(pg_empty_engine)
    assert "billing_known_item_lease" in inspector.get_table_names()
    pk = inspector.get_pk_constraint("billing_known_item_lease")
    assert pk["constrained_columns"] == ["provider", "environment", "seller_account", "kind", "remote_id"]

    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant_a = Tenant(site_url="https://ns-a.example.test")
            tenant_b = Tenant(site_url="https://ns-b.example.test")
            session.add_all([tenant_a, tenant_b])
            await session.flush()
            repo_a = BillingRepository(session, environment="sandbox", seller_account="org-a")
            repo_b = BillingRepository(session, environment="live", seller_account="org-b")
            assert (
                await repo_a.record_webhook(
                    provider="polar",
                    provider_event_id="evt-shared",
                    event_type="subscription.active",
                    signature_verified=True,
                    payload={"id": "evt-shared"},
                )
                is True
            )
            assert (
                await repo_b.record_webhook(
                    provider="polar",
                    provider_event_id="evt-shared",
                    event_type="subscription.active",
                    signature_verified=True,
                    payload={"id": "evt-shared"},
                )
                is True
            )
            assert (
                await repo_a.upsert_projection(
                    tenant_id=tenant_a.id,
                    provider="polar",
                    provider_customer_id="cus-shared",
                    provider_subscription_id="sub-a",
                    status=BillingSubscriptionStatus.ACTIVE,
                    current_period_end=None,
                    past_due_since=None,
                    provider_event_id="evt-shared",
                    event_position=NOW,
                )
                is True
            )
            assert (
                await repo_b.upsert_projection(
                    tenant_id=tenant_b.id,
                    provider="polar",
                    provider_customer_id="cus-shared",
                    provider_subscription_id="sub-b",
                    status=BillingSubscriptionStatus.ACTIVE,
                    current_period_end=None,
                    past_due_since=None,
                    provider_event_id="evt-shared",
                    event_position=NOW,
                )
                is True
            )
            with pytest.raises(BillingNamespaceConflictError):
                await repo_b.upsert_projection(
                    tenant_id=tenant_a.id,
                    provider="polar",
                    provider_customer_id="cus-other",
                    provider_subscription_id="sub-x",
                    status=BillingSubscriptionStatus.ACTIVE,
                    current_period_end=None,
                    past_due_since=None,
                    provider_event_id="evt-x",
                    event_position=NOW,
                )
            await session.commit()
            tenant_a_id = tenant_a.id
            tenant_b_id = tenant_b.id

        async with session_factory() as session:
            repo_a = BillingRepository(session, environment="sandbox", seller_account="org-a")
            row = await repo_a.get_webhook(provider="polar", provider_event_id="evt-shared")
            assert row is not None
            assert row.seller_account == "org-a"
            projection = await repo_a.get_projection(tenant_a_id, provider="polar")
            assert projection is not None
            assert projection.provider_customer_id == "cus-shared"
            assert await repo_a.get_projection(tenant_b_id, provider="polar") is None
            assert (
                await repo_a.record_webhook(
                    provider="polar",
                    provider_event_id="evt-shared",
                    event_type="subscription.active",
                    signature_verified=True,
                    payload={"id": "evt-shared"},
                )
                is False
            )

        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO billing_webhook_inbox "
                    "(id, provider, provider_event_id, event_type, signature_verified, payload, status) "
                    "VALUES (:id, 'polar', 'evt-legacy', 'subscription.active', true, '{}'::jsonb, 'received')"
                ),
                {"id": uuid4()},
            )
            await session.commit()
        async with session_factory() as session:
            repo_a = BillingRepository(session, environment="sandbox", seller_account="org-a")
            assert await repo_a.get_webhook(provider="polar", provider_event_id="evt-legacy") is None

        async with session_factory() as session:
            await set_tenant_context(session, tenant_a_id)
            visible = await session.execute(text("SELECT count(*) FROM billing_known_item_lease"))
            assert visible.scalar_one() == 0
            await session.rollback()

        async with session_factory() as session:
            repo = BillingRepository(session, environment="sandbox", seller_account="org-a")
            first = await repo.claim_reconcile_item(
                provider="polar",
                kind="inbox",
                remote_id="evt-shared",
                owner="worker-a",
                lease_ttl=timedelta(seconds=30),
                now=NOW,
            )
            await session.commit()
        assert first is not None
        assert first.fence == 1

        async def _raced_claim(owner: str):
            async with session_factory() as session:
                repo = BillingRepository(session, environment="sandbox", seller_account="org-a")
                lease = await repo.claim_reconcile_item(
                    provider="polar",
                    kind="inbox",
                    remote_id="evt-race",
                    owner=owner,
                    lease_ttl=timedelta(seconds=30),
                    now=NOW,
                )
                await session.commit()
                return None if lease is None else lease.owner

        raced = await asyncio.gather(_raced_claim("racer-a"), _raced_claim("racer-b"))
        assert set(raced) - {None} == {next(owner for owner in raced if owner is not None)}
        assert raced.count(None) == 1

        async with session_factory() as session:
            repo = BillingRepository(session, environment="sandbox", seller_account="org-a")
            stolen = await repo.claim_reconcile_item(
                provider="polar",
                kind="inbox",
                remote_id="evt-shared",
                owner="worker-b",
                lease_ttl=timedelta(seconds=30),
                now=NOW + timedelta(seconds=31),
            )
            await session.commit()
        assert stolen is not None
        assert stolen.fence == 2

        async with session_factory() as session:
            repo = BillingRepository(session, environment="sandbox", seller_account="org-a")
            with pytest.raises(BillingWorkLeaseConflictError):
                await repo.lock_reconcile_item(first, now=NOW + timedelta(seconds=32))
            await session.rollback()

        async with session_factory() as session:
            repo = BillingRepository(session, environment="sandbox", seller_account="org-a")
            await repo.lock_reconcile_item(stolen, now=NOW + timedelta(seconds=32))
            applied = await repo.upsert_projection(
                tenant_id=tenant_a_id,
                provider="polar",
                provider_customer_id="cus-shared",
                provider_subscription_id="sub-a",
                status=BillingSubscriptionStatus.ACTIVE,
                current_period_end=None,
                past_due_since=None,
                provider_event_id="evt-shared-2",
                event_position=NOW + timedelta(seconds=1),
            )
            await repo.finish_reconcile_item(stolen, now=NOW + timedelta(seconds=32))
            await session.commit()
        assert applied is True

        async with session_factory() as session:
            repo = BillingRepository(session, environment="sandbox", seller_account="org-a")
            with pytest.raises(BillingWorkLeaseConflictError):
                await repo.lock_reconcile_item(stolen, now=NOW + timedelta(seconds=33))
            with pytest.raises(BillingWorkLeaseConflictError):
                await repo.finish_reconcile_item(first, now=NOW + timedelta(seconds=33))
            await session.rollback()
    finally:
        await engine.dispose()


def _inbox_uniques(conn) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            text(
                "SELECT c.conname FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "JOIN pg_namespace n ON t.relnamespace = n.oid "
                "WHERE n.nspname = current_schema() AND t.relname = 'billing_webhook_inbox' "
                "AND c.contype = 'u'"
            )
        )
    }


def test_existing_unique_drop_requires_drain_and_rolls_back(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        conn.execute(
            text(
                "ALTER TABLE billing_webhook_inbox "
                "ADD CONSTRAINT uq_billing_webhook_inbox_provider_event "
                "UNIQUE (provider, provider_event_id)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE billing_subscription_projection "
                "ADD CONSTRAINT uq_billing_subscription_projection_provider_customer "
                "UNIQUE (provider, provider_customer_id)"
            )
        )

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        inbox_uniques = _inbox_uniques(conn)
        assert "uq_billing_webhook_inbox_provider_event" in inbox_uniques
        assert "uq_billing_webhook_inbox_provider_namespace_event" in inbox_uniques

    nested = pg_empty_engine.connect()
    trans = nested.begin()
    try:
        nested.execute(text("SELECT set_config('app.billing_namespace_writers_drained', 'true', true)"))
        MIGRATION.heal(nested)
        drained = _inbox_uniques(nested)
        assert "uq_billing_webhook_inbox_provider_event" not in drained
        trans.rollback()
    finally:
        nested.close()

    with pg_empty_engine.connect() as conn:
        restored = _inbox_uniques(conn)
        assert "uq_billing_webhook_inbox_provider_event" in restored


def _guc_on(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "on", "yes"}


async def _current_setting(session: AsyncSession, name: str) -> str:
    result = await session.execute(text("SELECT current_setting(:name, true)"), {"name": name})
    value = result.scalar()
    return "" if value is None else str(value)


async def _assert_foreign_query_denied(session: AsyncSession, tenant_id: object) -> None:
    previous = await _current_setting(session, "app.current_tenant")
    try:
        await session.execute(
            text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        visible = await session.execute(text("SELECT count(*) FROM billing_known_item_lease"))
        assert visible.scalar_one() == 0
        foreign = await session.execute(
            text("SELECT count(*) FROM portal_identity WHERE tenant_id <> :tenant_id"),
            {"tenant_id": tenant_id},
        )
        assert foreign.scalar_one() == 0
    finally:
        await session.execute(
            text("SELECT set_config('app.current_tenant', :value, true)"),
            {"value": previous},
        )


@pytest.mark.asyncio
async def test_postgres_operator_bypass_restored_after_every_path(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        role = conn.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
    assert role[1] is False
    assert role[2] is False

    engine = create_async_engine(_async_url(pg_empty_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant_a = Tenant(site_url="https://ns-op-a.example.test")
            tenant_b = Tenant(site_url="https://ns-op-b.example.test")
            session.add_all([tenant_a, tenant_b])
            await session.flush()
            await session.execute(text("SELECT set_config('app.bypass_rls', 'true', true)"))
            await session.execute(
                text(
                    "INSERT INTO portal_identity (id, tenant_id, issuer, subject, status) "
                    "VALUES (:id, :tenant_id, :issuer, :subject, 'active')"
                ),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_a.id,
                    "issuer": "https://issuer.example.test",
                    "subject": "user-a",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO portal_identity (id, tenant_id, issuer, subject, status) "
                    "VALUES (:id, :tenant_id, :issuer, :subject, 'active')"
                ),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_b.id,
                    "issuer": "https://issuer.example.test",
                    "subject": "user-b",
                },
            )
            await session.execute(text("SELECT set_config('app.bypass_rls', '', true)"))

            repo = BillingRepository(session, environment="sandbox", seller_account="org-a")
            first = await repo.claim_reconcile_item(
                provider="polar",
                kind="inbox",
                remote_id="evt-op",
                owner="worker-a",
                lease_ttl=timedelta(seconds=30),
                now=NOW,
            )
            assert first is not None
            assert not _guc_on(await _current_setting(session, "app.bypass_rls"))
            await _assert_foreign_query_denied(session, tenant_a.id)

            busy = await repo.claim_reconcile_item(
                provider="polar",
                kind="inbox",
                remote_id="evt-op",
                owner="worker-b",
                lease_ttl=timedelta(seconds=30),
                now=NOW + timedelta(seconds=1),
            )
            assert busy is None
            assert not _guc_on(await _current_setting(session, "app.bypass_rls"))
            await _assert_foreign_query_denied(session, tenant_a.id)

            with pytest.raises(BillingWorkLeaseConflictError):
                await repo.lock_reconcile_item(first, now=NOW + timedelta(seconds=32))
            assert not _guc_on(await _current_setting(session, "app.bypass_rls"))
            await _assert_foreign_query_denied(session, tenant_a.id)

            stolen = await repo.claim_reconcile_item(
                provider="polar",
                kind="inbox",
                remote_id="evt-op",
                owner="worker-b",
                lease_ttl=timedelta(seconds=30),
                now=NOW + timedelta(seconds=31),
            )
            assert stolen is not None
            await repo.lock_reconcile_item(stolen, now=NOW + timedelta(seconds=32))
            await repo.finish_reconcile_item(stolen, now=NOW + timedelta(seconds=32))
            assert not _guc_on(await _current_setting(session, "app.bypass_rls"))
            await _assert_foreign_query_denied(session, tenant_a.id)

            with pytest.raises(ValueError, match="owner"):
                await repo.claim_reconcile_item(
                    provider="polar",
                    kind="inbox",
                    remote_id="evt-op",
                    owner="",
                    lease_ttl=timedelta(seconds=30),
                    now=NOW + timedelta(seconds=33),
                )
            assert not _guc_on(await _current_setting(session, "app.bypass_rls"))
            await session.rollback()

        async with session_factory() as session:
            tenant = Tenant(site_url="https://ns-bound.example.test")
            session.add(tenant)
            await session.flush()
            await set_tenant_context(session, tenant.id)
            repo = BillingRepository(session, environment="sandbox", seller_account="org-a")
            with pytest.raises(ValueError, match="tenant-bound"):
                await repo.claim_reconcile_item(
                    provider="polar",
                    kind="inbox",
                    remote_id="evt-bound",
                    owner="worker-a",
                    lease_ttl=timedelta(seconds=30),
                    now=NOW,
                )
            assert not _guc_on(await _current_setting(session, "app.bypass_rls"))
            visible = await session.execute(text("SELECT count(*) FROM billing_known_item_lease"))
            assert visible.scalar_one() == 0
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_same_session_returning_lease_is_fresh(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        role = conn.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
    assert role[1] is False
    assert role[2] is False

    engine = create_async_engine(_async_url(pg_empty_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            repo = BillingRepository(session, environment="sandbox", seller_account="org-a")
            first = await repo.claim_reconcile_item(
                provider="polar",
                kind="inbox",
                remote_id="evt-fresh",
                owner="worker-a",
                lease_ttl=timedelta(seconds=30),
                now=NOW,
            )
            await session.commit()
            assert first is not None
            assert first.fence == 1
            stolen = await repo.claim_reconcile_item(
                provider="polar",
                kind="inbox",
                remote_id="evt-fresh",
                owner="worker-b",
                lease_ttl=timedelta(seconds=30),
                now=NOW + timedelta(seconds=31),
            )
            assert stolen is not None
            assert stolen.owner == "worker-b"
            assert stolen.fence == 2
            await session.commit()
            with pytest.raises(BillingWorkLeaseConflictError):
                await repo.lock_reconcile_item(first, now=NOW + timedelta(seconds=32))
            with pytest.raises(BillingWorkLeaseConflictError):
                await repo.finish_reconcile_item(first, now=NOW + timedelta(seconds=32))
            await repo.lock_reconcile_item(stolen, now=NOW + timedelta(seconds=32))
            await repo.finish_reconcile_item(stolen, now=NOW + timedelta(seconds=32))
            await session.commit()
            assert stolen.fence == 2
    finally:
        await engine.dispose()
