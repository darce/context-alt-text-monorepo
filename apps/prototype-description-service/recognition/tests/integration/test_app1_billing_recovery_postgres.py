"""PostgreSQL proof for C0 recovery cursor/lease/quarantine fencing.

Skip is missing release evidence, not a passing result. The pg_empty_engine
fixture refuses privileged roles; IDENTITY_PG_REQUIRED=1 fails instead of skip.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.tenant import Tenant
from db.tenant_context import set_tenant_context
from recognition.domain.portal_contracts import (
    EnumerationObservation,
    EnumerationObservationReason,
    QuarantineStatus,
    ReconciliationCursorAdvanceError,
    ReconciliationCursorKey,
    ReconciliationKind,
    ReconciliationLeaseConflictError,
    ReconciliationQuarantineConflictError,
)
from recognition.infrastructure.repositories.billing_reconciliation_repository import (
    BillingReconciliationRepository,
)

pytestmark = pytest.mark.pg

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")


def _async_url(engine) -> str:
    return (
        engine.url.render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def _key() -> ReconciliationCursorKey:
    return ReconciliationCursorKey(
        provider="fake",
        environment="sandbox",
        seller_account="org_sandbox",
        kind=ReconciliationKind.SUBSCRIPTIONS,
    )


@pytest.mark.asyncio
async def test_postgres_recovery_fencing_isolation_and_page_idempotency(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        flags = {
            table: conn.execute(
                text(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() AND c.relname = :table"
                ),
                {"table": table},
            ).one()
            for table in (
                "billing_reconciliation_cursor",
                "billing_reconciliation_quarantine",
                "billing_reconciliation_item_progress",
            )
        }
        role = conn.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
        inbox_columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'billing_webhook_inbox'"
                )
            )
        }
        invitation_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'portal_tenant_invitation' "
                "AND column_name = 'tenant_id'"
            )
        ).scalar()
        fence_epoch = conn.execute(
            text("SELECT fence_epoch FROM usage_admission_global_state WHERE id = 'global'")
        ).scalar()

    assert role[1] is False
    assert role[2] is False
    for table, (enabled, forced) in flags.items():
        assert (enabled, forced) == (True, True), table
    assert {"environment", "seller_account"} <= inbox_columns
    assert invitation_nullable == "YES"
    assert int(fence_epoch) >= 1

    inspector = inspect(pg_empty_engine)
    assert "billing_reconciliation_cursor" in inspector.get_table_names()
    pk = inspector.get_pk_constraint("billing_reconciliation_cursor")
    assert pk["constrained_columns"] == ["provider", "environment", "seller_account", "kind"]

    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    key = _key()
    now = datetime(2026, 9, 22, 15, 0, tzinfo=UTC)
    try:
        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)
            first = await repo.acquire_lease(key, owner="worker-a", lease_ttl=timedelta(seconds=30), now=now)
            await session.commit()
        assert first is not None
        assert first.fence == 1

        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)
            blocked = await repo.acquire_lease(key, owner="worker-b", lease_ttl=timedelta(seconds=30), now=now)
            await session.commit()
        assert blocked is None

        async with session_factory() as session:
            tenant = Tenant(site_url="https://recovery-rls.example.test")
            session.add(tenant)
            await session.flush()
            await set_tenant_context(session, tenant.id)
            visible = await session.execute(text("SELECT count(*) FROM billing_reconciliation_cursor"))
            assert visible.scalar_one() == 0
            await session.rollback()

        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)
            stolen = await repo.acquire_lease(
                key,
                owner="worker-b",
                lease_ttl=timedelta(seconds=30),
                now=now + timedelta(seconds=31),
            )
            await session.commit()
        assert stolen is not None
        assert stolen.fence == 2
        assert stolen.owner == "worker-b"

        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)
            with pytest.raises(ReconciliationLeaseConflictError):
                await repo.heartbeat(first, now=now + timedelta(seconds=32), lease_ttl=timedelta(seconds=30))
            await session.rollback()

        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)
            await repo.complete_item(stolen, remote_id="sub-ok", now=now + timedelta(seconds=32))
            await repo.quarantine_item(
                stolen,
                observation=EnumerationObservation(
                    reason=EnumerationObservationReason.SELLER_MISMATCH,
                    remote_id="sub-foreign",
                    details={"organization_id": "org-other"},
                ),
                now=now + timedelta(seconds=32),
            )
            advanced = await repo.advance_cursor(
                stolen,
                next_cursor="2",
                exhausted=False,
                page_remote_ids=("sub-ok", "sub-foreign"),
                now=now + timedelta(seconds=32),
            )
            await repo.complete_item(stolen, remote_id="sub-ok", now=now + timedelta(seconds=33))
            retry = await repo.audited_retry(
                stolen,
                remote_id="sub-foreign",
                operator_identity="ops-1",
                operator_reason="seller confirmed foreign org",
                now=now + timedelta(seconds=33),
            )
            await session.commit()
        assert advanced.cursor == "2"
        assert retry.status is QuarantineStatus.RETRY_PENDING
        assert retry.operator_reason == "seller confirmed foreign org"

        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)
            with pytest.raises(ReconciliationCursorAdvanceError):
                await repo.advance_cursor(
                    stolen,
                    next_cursor="3",
                    exhausted=False,
                    page_remote_ids=("sub-ok", "sub-missing"),
                    now=now + timedelta(seconds=34),
                )
            await session.rollback()

        async def _raced_acquire(owner: str):
            async with session_factory() as session:
                repo = BillingReconciliationRepository(session)
                lease = await repo.acquire_lease(
                    key,
                    owner=owner,
                    lease_ttl=timedelta(seconds=30),
                    now=now + timedelta(seconds=70),
                )
                await session.commit()
                return lease

        raced = await asyncio.gather(_raced_acquire("worker-c"), _raced_acquire("worker-d"))
        winners = [lease for lease in raced if lease is not None]
        assert len(winners) == 1
        assert winners[0].fence == 3
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_acquire_rollback_releases_cursor(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    engine = create_async_engine(_async_url(pg_empty_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    key = ReconciliationCursorKey(
        provider="fake",
        environment="live",
        seller_account="org_live",
        kind=ReconciliationKind.AMBIGUOUS_CHECKOUTS,
    )
    now = datetime(2026, 9, 22, 16, 0, tzinfo=UTC)
    try:
        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)
            first = await repo.acquire_lease(key, owner="worker-a", lease_ttl=timedelta(seconds=30), now=now)
            assert first is not None
            await session.rollback()

        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)
            second = await repo.acquire_lease(key, owner="worker-b", lease_ttl=timedelta(seconds=30), now=now)
            await session.commit()
        assert second is not None
        assert second.owner == "worker-b"
        assert second.fence == 1
    finally:
        await engine.dispose()


def _guc_on(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "on", "yes"}


async def _current_setting(session: AsyncSession, name: str) -> str:
    result = await session.execute(text("SELECT current_setting(:name, true)"), {"name": name})
    value = result.scalar()
    return "" if value is None else str(value)


@pytest.mark.asyncio
async def test_postgres_same_session_reacquire_returns_fresh_fence(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        role = conn.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
    assert role[1] is False
    assert role[2] is False

    engine = create_async_engine(_async_url(pg_empty_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    key = _key()
    now = datetime(2026, 9, 22, 17, 0, tzinfo=UTC)
    try:
        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)
            first = await repo.acquire_lease(key, owner="worker-a", lease_ttl=timedelta(seconds=30), now=now)
            await session.commit()
            assert first is not None
            assert first.fence == 1
            stolen = await repo.acquire_lease(
                key,
                owner="worker-b",
                lease_ttl=timedelta(seconds=30),
                now=now + timedelta(seconds=31),
            )
            assert stolen is not None
            assert stolen.owner == "worker-b"
            assert stolen.fence == 2
            await session.commit()
            with pytest.raises(ReconciliationLeaseConflictError):
                await repo.heartbeat(first, now=now + timedelta(seconds=32), lease_ttl=timedelta(seconds=30))
            live = await repo.heartbeat(stolen, now=now + timedelta(seconds=32), lease_ttl=timedelta(seconds=30))
            await session.commit()
            assert live.owner == "worker-b"
            assert live.fence == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_operator_bypass_restored_and_rejects_tenant_bound(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        role = conn.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
    assert role[1] is False
    assert role[2] is False

    engine = create_async_engine(_async_url(pg_empty_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    key = _key()
    now = datetime(2026, 9, 22, 18, 0, tzinfo=UTC)
    try:
        async with session_factory() as session:
            tenant_a = Tenant(site_url="https://recovery-a.example.test")
            tenant_b = Tenant(site_url="https://recovery-b.example.test")
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

            repo = BillingReconciliationRepository(session)
            lease = await repo.acquire_lease(key, owner="worker-a", lease_ttl=timedelta(seconds=30), now=now)
            assert lease is not None
            assert not _guc_on(await _current_setting(session, "app.bypass_rls"))

            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": str(tenant_a.id)},
            )
            cursor_visible = await session.execute(text("SELECT count(*) FROM billing_reconciliation_cursor"))
            own_identity = await session.execute(
                text("SELECT count(*) FROM portal_identity WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_a.id},
            )
            foreign_identity = await session.execute(
                text("SELECT count(*) FROM portal_identity WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_b.id},
            )
            assert cursor_visible.scalar_one() == 0
            assert own_identity.scalar_one() == 1
            assert foreign_identity.scalar_one() == 0
            await session.rollback()

        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)
            durable = await repo.acquire_lease(key, owner="worker-durable", lease_ttl=timedelta(seconds=30), now=now)
            await session.commit()
            assert durable is not None

        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)
            with pytest.raises(ValueError, match="owner"):
                await repo.acquire_lease(key, owner="", lease_ttl=timedelta(seconds=30), now=now)
            assert not _guc_on(await _current_setting(session, "app.bypass_rls"))
            tenant = Tenant(site_url="https://recovery-validation.example.test")
            session.add(tenant)
            await session.flush()
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": str(tenant.id)},
            )
            visible = await session.execute(text("SELECT count(*) FROM billing_reconciliation_cursor"))
            assert visible.scalar_one() == 0
            await session.rollback()

        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)

            async def _explode(_key: object, _remote_id: str) -> None:
                await session.execute(text("SELECT 1 / 0"))

            repo._get_quarantine_row = _explode  # type: ignore[method-assign]
            with pytest.raises(DBAPIError):
                await repo.get_quarantine(key, "sub-sql")
            assert not _guc_on(await _current_setting(session, "app.bypass_rls"))
            tenant = Tenant(site_url="https://recovery-sql.example.test")
            session.add(tenant)
            await session.flush()
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": str(tenant.id)},
            )
            visible = await session.execute(text("SELECT count(*) FROM billing_reconciliation_cursor"))
            assert visible.scalar_one() == 0
            await session.rollback()

        async with session_factory() as session:
            tenant = Tenant(site_url="https://recovery-bound.example.test")
            session.add(tenant)
            await session.flush()
            await set_tenant_context(session, tenant.id)
            repo = BillingReconciliationRepository(session)
            with pytest.raises(ValueError, match="tenant-bound"):
                await repo.get_quarantine(key, "sub-bound")
            assert not _guc_on(await _current_setting(session, "app.bypass_rls"))
            visible = await session.execute(text("SELECT count(*) FROM billing_reconciliation_cursor"))
            assert visible.scalar_one() == 0
            await session.rollback()

        async with session_factory() as session:
            repo = BillingReconciliationRepository(session)
            stolen = await repo.acquire_lease(
                key,
                owner="worker-b",
                lease_ttl=timedelta(seconds=30),
                now=now + timedelta(seconds=31),
            )
            assert stolen is not None
            await repo.quarantine_item(
                stolen,
                observation=EnumerationObservation(
                    reason=EnumerationObservationReason.SELLER_MISMATCH,
                    remote_id="sub-foreign",
                    details={"organization_id": "org-other"},
                ),
                now=now + timedelta(seconds=32),
            )
            retry = await repo.audited_retry(
                stolen,
                remote_id="sub-foreign",
                operator_identity="ops-1",
                operator_reason="seller confirmed",
                now=now + timedelta(seconds=33),
            )
            assert retry.status is QuarantineStatus.RETRY_PENDING
            with pytest.raises(ReconciliationQuarantineConflictError):
                await repo.audited_retry(
                    stolen,
                    remote_id="sub-foreign",
                    operator_identity="ops-1",
                    operator_reason="repeat",
                    now=now + timedelta(seconds=34),
                )
            await repo.complete_item(stolen, remote_id="sub-foreign", now=now + timedelta(seconds=35))
            loaded = await repo.get_quarantine(key, "sub-foreign")
            await session.commit()
            assert loaded is not None
            assert loaded.status is QuarantineStatus.RESOLVED
            assert loaded.attempt_count == 2
            with pytest.raises(ReconciliationQuarantineConflictError):
                await repo.audited_retry(
                    stolen,
                    remote_id="sub-foreign",
                    operator_identity="ops-1",
                    operator_reason="reopen",
                    now=now + timedelta(seconds=36),
                )
    finally:
        await engine.dispose()
