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
from unittest.mock import AsyncMock, call

import pytest

from db.models import Tenant
from recognition.application.orchestration.cluster_service import ClusterService

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


# ---------------------------------------------------------------------------
# Postgres regression test (requires real Postgres with RLS policies)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("POSTGRES_TEST_URL"),
    reason=(
        "Requires POSTGRES_TEST_URL pointing to a Postgres instance with RLS "
        "policies active.  The default test suite uses SQLite in-memory which "
        "does not support SET LOCAL or row-level security."
    ),
)
@pytest.mark.asyncio
async def test_multi_chunk_clustering_does_not_fail_rls_on_second_chunk(
    db_session,
    tenant: Tenant,
    cluster_service: ClusterService,
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
    identity_rows = _make_media_identity_rows(tenant.id, 12, db_session)
    db_session.add_all(identity_rows)
    await db_session.commit()

    # Should complete without InsufficientPrivilegeError
    result = await cluster_service.cluster_unclustered_identities(
        tenant_id=str(tenant.id),
        job_id=None,
    )
    assert result.completed == 12
