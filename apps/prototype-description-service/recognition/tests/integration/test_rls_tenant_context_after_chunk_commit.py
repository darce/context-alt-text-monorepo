"""Integration tests for RLS tenant context restoration after per-chunk commits.

Covers the bug documented in:
  docs/tasks/10.0/rls-tenant-context-lost-after-chunk-commit-investigation-2026-03-24.md

Root cause: orchestrator._process_chunks() calls await self._session.commit() after
each chunk to create durable checkpoint boundaries (finding 1164).  PostgreSQL
SET LOCAL variables (app.current_tenant, app.bypass_rls) are transaction-scoped
and are cleared when the transaction commits.  Without an explicit context
restoration step, subsequent chunks run with no tenant context and RLS rejects
INSERT operations on recognition_events during SQLAlchemy autoflush.

Fix: orchestrator._process_chunks() now calls set_tenant_context() +
enable_rls_bypass() immediately after each await self._session.commit().
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from asyncpg.exceptions import PostgresError
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Tenant
from db.settings import (
    DEFAULT_ASYNC_DSN_TEMPLATE,
    DEFAULT_DB_NAME,
    DEFAULT_PGHOST,
    DEFAULT_PGPASSWORD,
    DEFAULT_PGPORT,
    DEFAULT_PGUSER,
    DatabaseSettings,
    get_database_settings,
)
from recognition.application.assignment.gate import AssignmentGate
from recognition.application.discovery.centroid import CentroidDiscovery
from recognition.application.discovery.graph.discovery import GraphDiscovery
from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.orchestration.cluster_service import ClusterService
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.service import SuggestionService
from recognition.infrastructure.clustering.hdbscan_adapter import HdbscanGraphAlgorithm
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.infrastructure.repositories.member_repository import SqlAlchemyMemberRepository
from recognition.infrastructure.repositories.suggestion_repository import SqlAlchemySuggestionRepository

# ---------------------------------------------------------------------------
# Helper: identities for multi-chunk test
# ---------------------------------------------------------------------------


def _make_media_identity_rows(tenant_id: uuid.UUID, count: int, db_session) -> list:
    """Return unsaved MediaIdentity ORM rows."""
    import numpy as np

    from db.models import MediaIdentity

    rows = []
    for i in range(count):
        rng = np.random.default_rng(i)
        embedding = rng.random(512).astype(np.float32)
        embedding = embedding / float(np.linalg.norm(embedding))
        rows.append(
            MediaIdentity(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                media_id=i + 1,
                media_url=f"http://example.test/{i + 1}.jpg",
                bbox_x=0,
                bbox_y=0,
                bbox_width=10,
                bbox_height=10,
                confidence=0.99,
                embedding=embedding.tolist(),
            )
        )
    return rows


DEFAULT_POSTGRES_TEST_DSN = DEFAULT_ASYNC_DSN_TEMPLATE.format(
    PGUSER=DEFAULT_PGUSER,
    PGPASSWORD=DEFAULT_PGPASSWORD,
    PGHOST=DEFAULT_PGHOST,
    PGPORT=DEFAULT_PGPORT,
    DB_NAME=DEFAULT_DB_NAME,
)


def _postgres_test_environment_error(exc: Exception) -> bool:
    return isinstance(exc, (SQLAlchemyError, PostgresError, OSError))


def _resolve_postgres_test_dsn() -> str:
    explicit_dsn = os.environ.get("POSTGRES_TEST_URL")
    if explicit_dsn:
        return explicit_dsn

    resolved_dsn = get_database_settings().postgres_dsn
    if os.environ.get("POSTGRES_DSN") is None and resolved_dsn == DEFAULT_POSTGRES_TEST_DSN:
        return ""

    return resolved_dsn


@pytest_asyncio.fixture
async def postgres_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a Postgres-backed session with schema and RLS checks for seam regression tests."""

    postgres_dsn = _resolve_postgres_test_dsn()
    if not postgres_dsn:
        pytest.skip(
            "Postgres RLS regression environment is not configured; set POSTGRES_TEST_URL or POSTGRES_DSN to run this regression test"
        )

    engine = create_async_engine(postgres_dsn, pool_pre_ping=True)

    try:
        async with engine.connect() as connection:
            try:
                table_exists = await connection.scalar(
                    text("SELECT to_regclass('public.recognition_events') IS NOT NULL")
                )
                if not table_exists:
                    pytest.skip(
                        "recognition_events table is not present; run scripts/reset_dev_db.sh before the Postgres RLS regression test"
                    )

                rls_enabled = await connection.scalar(
                    text("SELECT relrowsecurity FROM pg_class WHERE oid = 'public.recognition_events'::regclass")
                )
                if not rls_enabled:
                    pytest.skip(
                        "recognition_events RLS policies are not active; reset the local Postgres schema before running this regression test"
                    )
            except Exception as exc:
                if _postgres_test_environment_error(exc):
                    pytest.skip(f"Postgres RLS regression environment is unavailable: {exc}")
                raise

            outer_transaction = await connection.begin()
            session_factory = async_sessionmaker(bind=connection, expire_on_commit=False)

            async with session_factory() as session:
                await session.begin_nested()

                @event.listens_for(session.sync_session, "after_transaction_end")
                def _restart_savepoint(sess, transaction):
                    if transaction.nested and not transaction._parent.nested:
                        sess.begin_nested()

                try:
                    yield session
                finally:
                    await session.rollback()

            await outer_transaction.rollback()
    except Exception as exc:
        if _postgres_test_environment_error(exc):
            pytest.skip(f"Postgres RLS regression environment is unavailable: {exc}")
        raise
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def postgres_tenant(postgres_db_session: AsyncSession) -> Tenant:
    """Insert a tenant row into the Postgres-backed regression session."""

    tenant = Tenant(site_url=f"http://postgres-rls-{uuid.uuid4().hex}.test")
    postgres_db_session.add(tenant)
    await postgres_db_session.commit()
    await postgres_db_session.refresh(tenant)
    return tenant


@pytest.fixture
def postgres_cluster_service(postgres_db_session: AsyncSession, postgres_tenant: Tenant) -> ClusterService:
    """Build a ClusterService against the Postgres-backed session used by the seam regression."""

    settings = ClusteringSettings()
    cluster_repository = SqlAlchemyClusterRepository(postgres_db_session)
    member_repository = SqlAlchemyMemberRepository(postgres_db_session, tenant_id=postgres_tenant.id)
    assignment_writer = AssignmentWriter(settings, cluster_repository, member_repository)
    suggestion_repository = SqlAlchemySuggestionRepository(postgres_db_session)

    gate = AssignmentGate(settings, cluster_repository)
    rep_discovery = RepresentativeDiscovery(settings)
    centroid_discovery = CentroidDiscovery(settings)
    graph_discovery = GraphDiscovery(settings, HdbscanGraphAlgorithm())
    suggestions = SuggestionService(
        suggestion_repository,
        tenant_id=str(postgres_tenant.id),
        cluster_repository=cluster_repository,
    )

    return ClusterService(
        gate=gate,
        representative_discovery=rep_discovery,
        centroid_discovery=centroid_discovery,
        graph_discovery=graph_discovery,
        assignment_writer=assignment_writer,
        suggestion_service=suggestions,
        logger=None,
        session=postgres_db_session,
    )


# ---------------------------------------------------------------------------
# Unit-level: verify set_tenant_context + enable_rls_bypass are called per chunk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_restores_context_after_each_chunk_commit(
    db_session,
    tenant: Tenant,
    cluster_service: ClusterService,
    monkeypatch,
) -> None:
    """set_tenant_context and enable_rls_bypass must be called after each chunk commit.

    This test uses monkeypatching in SQLite to verify the structural behaviour
    without requiring a real Postgres connection.  It seeds enough identities
    to produce at least two chunks (chunk_size starts at 5), then asserts that
    set_tenant_context and enable_rls_bypass are each called at least once per
    committed chunk.
    """
    identity_rows = _make_media_identity_rows(tenant.id, 12, db_session)
    db_session.add_all(identity_rows)
    await db_session.commit()

    set_ctx_mock = AsyncMock()
    bypass_mock = AsyncMock()
    monkeypatch.setattr(
        "recognition.application.orchestration.clustering.orchestrator.set_tenant_context",
        set_ctx_mock,
    )
    monkeypatch.setattr(
        "recognition.application.orchestration.clustering.orchestrator.enable_rls_bypass",
        bypass_mock,
    )

    await cluster_service.cluster_unclustered_identities(
        tenant_id=str(tenant.id),
        job_id=None,
    )

    # With 12 identities and chunk_size=5, there will be at least 2 chunk commits.
    # After each commit the context must be restored.
    assert set_ctx_mock.call_count >= 2, (
        f"set_tenant_context should be called once per chunk commit (>= 2 chunks); "
        f"got {set_ctx_mock.call_count} call(s)"
    )
    assert bypass_mock.call_count >= 2, (
        f"enable_rls_bypass should be called once per chunk commit (>= 2 chunks); got {bypass_mock.call_count} call(s)"
    )

    # Each call to set_tenant_context must pass the correct tenant UUID.
    tenant_uuid = uuid.UUID(str(tenant.id))
    for c in set_ctx_mock.call_args_list:
        # Signature: set_tenant_context(session, tenant_id_uuid)
        passed_uuid = c.args[1] if c.args else c.kwargs.get("tenant_id")
        assert passed_uuid == tenant_uuid, f"set_tenant_context called with wrong tenant UUID: {passed_uuid!r}"


def test_resolve_postgres_test_dsn_returns_empty_when_no_real_postgres_config(monkeypatch) -> None:
    monkeypatch.delenv("POSTGRES_TEST_URL", raising=False)
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.setattr(
        "recognition.tests.integration.test_rls_tenant_context_after_chunk_commit.get_database_settings",
        lambda: DatabaseSettings(
            postgres_dsn=DEFAULT_POSTGRES_TEST_DSN,
            postgres_sync_dsn="postgresql+psycopg://context:context@localhost:5432/context_alt_text",
            pgvector_dimension=512,
            pool_size=20,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=3600,
        ),
    )

    assert _resolve_postgres_test_dsn() == ""


def test_resolve_postgres_test_dsn_prefers_explicit_test_url(monkeypatch) -> None:
    explicit_dsn = "postgresql+asyncpg://acx:secret@db.example.test:5432/acx_test"
    monkeypatch.setenv("POSTGRES_TEST_URL", explicit_dsn)

    assert _resolve_postgres_test_dsn() == explicit_dsn


# ---------------------------------------------------------------------------
# Postgres regression test (uses the service's standard Postgres settings when available)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multi_chunk_clustering_does_not_fail_rls_on_second_chunk(
    postgres_db_session: AsyncSession,
    postgres_tenant: Tenant,
    postgres_cluster_service: ClusterService,
) -> None:
    """Postgres-backed regression: chunk 2+ must not raise InsufficientPrivilegeError.

    Regression for:
      asyncpg.exceptions.InsufficientPrivilegeError:
        new row violates row-level security policy for table "recognition_events"

    Preconditions (Postgres only):
    - RLS policy tenant_isolation_recognition_events is active on recognition_events
    - Session starts without app.current_tenant or app.bypass_rls set
    - GraphDiscovery adds a graph_run RecognitionEvent to the session
    - A later query (e.g. block_repository.is_blocked()) triggers autoflush

    After the fix:
    - set_tenant_context + enable_rls_bypass are called after each chunk commit
    - autoflush inserts succeed because the bypass flag is still set
    """
    identity_rows = _make_media_identity_rows(postgres_tenant.id, 12, postgres_db_session)
    postgres_db_session.add_all(identity_rows)
    await postgres_db_session.commit()

    # Should complete without InsufficientPrivilegeError
    result = await postgres_cluster_service.cluster_unclustered_identities(
        tenant_id=str(postgres_tenant.id),
        job_id=None,
    )
    assert result.completed == 12
