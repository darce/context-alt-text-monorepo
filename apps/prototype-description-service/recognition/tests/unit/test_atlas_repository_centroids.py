"""FIR-9 B1: atlas centroid fetch must stay inside the requested embedding space."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import Table, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import (
    IdentityCluster,
    IdentityClusterRepresentative,
    IdentityMember,
    MediaIdentity,
    Tenant,
)
from db.settings import get_database_settings
from recognition.infrastructure.repositories.atlas_repository import AtlasRepository
from recognition.tests.conftest import _sqlite_vector_norm

_DB_SETTINGS = get_database_settings()
_MODEL_X = "model_x@vendor"
_MODEL_Y = "model_y@vendor"
_DIM = _DB_SETTINGS.pgvector_dimension


def _embedding_y() -> list[float]:
    """Unit-axis embedding in Y space (first component 1)."""
    vec = [0.0] * _DIM
    vec[0] = 1.0
    return vec


def _embedding_x() -> list[float]:
    """Unit-axis embedding in X space (second component 1) — orthogonal to Y."""
    vec = [0.0] * _DIM
    vec[1] = 1.0
    return vec


@pytest_asyncio.fixture
async def centroid_db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _register_vector_functions(dbapi_connection, _connection_record) -> None:
        dbapi_connection.create_function("vector_norm", 1, _sqlite_vector_norm)

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        tables = [
            Table("tenants", Base.metadata),
            Table("media_identities", Base.metadata),
            Table("identity_clusters", Base.metadata),
            Table("identity_members", Base.metadata),
            Table("identity_cluster_representatives", Base.metadata),
        ]
        await conn.run_sync(Base.metadata.create_all, tables=tables)
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS mv_identity_cluster_centroids (
                    cluster_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    identity_count INTEGER NOT NULL DEFAULT 0,
                    centroid BLOB,
                    refreshed_at TIMESTAMP
                )
                """
            )
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.begin_nested()

        @event.listens_for(session.sync_session, "after_transaction_end")
        def _restart_savepoint(sess, transaction):
            if transaction.nested and not transaction._parent.nested:
                sess.begin_nested()

        try:
            yield session
            await session.rollback()
        finally:
            await session.close()

    await engine.dispose()


async def _seed_mixed_model_cluster(session: AsyncSession) -> tuple[Tenant, IdentityCluster]:
    tenant = Tenant(site_url=f"https://centroid-{uuid4().hex[:8]}.example.edu/wp")
    session.add(tenant)
    await session.flush()

    cluster = IdentityCluster(tenant_id=tenant.id, label="Mixed", identity_count=3)
    session.add(cluster)
    await session.flush()

    # Majority model Y (2 members) + minority model X (1 member).
    y1 = MediaIdentity(
        tenant_id=tenant.id,
        media_id=1,
        media_url="http://example.test/y1.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.9,
        embedding=_embedding_y(),
        embedding_model=_MODEL_Y,
    )
    y2 = MediaIdentity(
        tenant_id=tenant.id,
        media_id=2,
        media_url="http://example.test/y2.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.91,
        embedding=_embedding_y(),
        embedding_model=_MODEL_Y,
    )
    x1 = MediaIdentity(
        tenant_id=tenant.id,
        media_id=3,
        media_url="http://example.test/x1.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.92,
        embedding=_embedding_x(),
        embedding_model=_MODEL_X,
    )
    session.add_all([y1, y2, x1])
    await session.flush()

    session.add_all(
        [
            IdentityMember(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                identity_id=y1.id,
                similarity=0.99,
            ),
            IdentityMember(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                identity_id=y2.id,
                similarity=0.98,
            ),
            IdentityMember(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                identity_id=x1.id,
                similarity=0.5,
            ),
            IdentityClusterRepresentative(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                identity_id=y1.id,
                embedding=_embedding_y(),
                quality_score=0.99,
            ),
            IdentityClusterRepresentative(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                identity_id=x1.id,
                embedding=_embedding_x(),
                quality_score=0.5,
            ),
        ]
    )
    await session.flush()

    # MV centroid is majority-model (Y) space — e0=1, e1=0 (not X's e0=0, e1=1).
    y_centroid = np.asarray(_embedding_y(), dtype=np.float32).tobytes()
    await session.execute(
        text(
            """
            INSERT INTO mv_identity_cluster_centroids
                (cluster_id, tenant_id, identity_count, centroid, refreshed_at)
            VALUES
                (:cluster_id, :tenant_id, 2, :centroid, :refreshed_at)
            """
        ),
        {
            "cluster_id": str(cluster.id),
            "tenant_id": str(tenant.id),
            "centroid": y_centroid,
            "refreshed_at": datetime.now(tz=UTC).isoformat(),
        },
    )
    await session.commit()
    return tenant, cluster


@pytest.mark.asyncio
async def test_get_tenant_cluster_centroids_omits_foreign_model_majority_mv(
    centroid_db_session: AsyncSession,
) -> None:
    """Requesting model X must not return the majority-Y MV centroid (space mix)."""
    tenant, cluster = await _seed_mixed_model_cluster(centroid_db_session)
    repo = AtlasRepository(centroid_db_session)

    pairs, _refreshed = await repo.get_tenant_cluster_centroids(
        str(tenant.id),
        _MODEL_X,
        cluster_ids=[cluster.id],
    )

    assert len(pairs) == 1, f"expected X-space centroid for mixed cluster; got {pairs!r}"
    assert pairs[0][0] == cluster.id
    emb = pairs[0][1]
    # X embedding is e1=1; Y MV is e0=1. Must be X, not majority-Y MV.
    assert float(emb[0]) == pytest.approx(0.0), (
        f"centroid for {_MODEL_X!r} must not be the majority-Y MV (e0=1); got e0={emb[0]!r}"
    )
    assert float(emb[1]) == pytest.approx(1.0), (
        f"centroid for {_MODEL_X!r} must come from X embeddings (e1=1); got e1={emb[1]!r}"
    )


@pytest.mark.asyncio
async def test_get_tenant_cluster_centroids_absent_when_no_requested_model_embeddings(
    centroid_db_session: AsyncSession,
) -> None:
    """Cluster with only model Y embeddings is absent when caller asks for model X."""
    tenant = Tenant(site_url=f"https://centroid-absent-{uuid4().hex[:8]}.example.edu/wp")
    centroid_db_session.add(tenant)
    await centroid_db_session.flush()

    cluster = IdentityCluster(tenant_id=tenant.id, label="Y-only", identity_count=1)
    centroid_db_session.add(cluster)
    await centroid_db_session.flush()

    identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=10,
        media_url="http://example.test/y-only.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.9,
        embedding=_embedding_y(),
        embedding_model=_MODEL_Y,
    )
    centroid_db_session.add(identity)
    await centroid_db_session.flush()
    centroid_db_session.add(
        IdentityMember(
            tenant_id=tenant.id,
            cluster_id=cluster.id,
            identity_id=identity.id,
            similarity=0.99,
        )
    )
    y_centroid = np.asarray(_embedding_y(), dtype=np.float32).tobytes()
    await centroid_db_session.execute(
        text(
            """
            INSERT INTO mv_identity_cluster_centroids
                (cluster_id, tenant_id, identity_count, centroid, refreshed_at)
            VALUES
                (:cluster_id, :tenant_id, 1, :centroid, :refreshed_at)
            """
        ),
        {
            "cluster_id": str(cluster.id),
            "tenant_id": str(tenant.id),
            "centroid": y_centroid,
            "refreshed_at": datetime.now(tz=UTC).isoformat(),
        },
    )
    await centroid_db_session.commit()

    repo = AtlasRepository(centroid_db_session)
    pairs, _refreshed = await repo.get_tenant_cluster_centroids(
        str(tenant.id),
        _MODEL_X,
        cluster_ids=[cluster.id],
    )

    assert pairs == [], (
        f"cluster with no {_MODEL_X!r} embeddings must be reported absent; got {pairs!r}"
    )


@pytest.mark.asyncio
async def test_get_tenant_cluster_centroids_uses_mv_when_majority_matches_request(
    centroid_db_session: AsyncSession,
) -> None:
    """When majority model equals the request, the MV centroid in that space is used."""
    tenant, cluster = await _seed_mixed_model_cluster(centroid_db_session)
    repo = AtlasRepository(centroid_db_session)

    pairs, _refreshed = await repo.get_tenant_cluster_centroids(
        str(tenant.id),
        _MODEL_Y,
        cluster_ids=[cluster.id],
    )

    assert len(pairs) == 1
    assert pairs[0][0] == cluster.id
    # MV was seeded with Y-space unit vector e0=1
    assert float(pairs[0][1][0]) == pytest.approx(1.0)
    assert float(pairs[0][1][1]) == pytest.approx(0.0)
