"""FIR-9 S1b: AtlasRepository read path — SQL model filter, EMB-01, centroid MV fallback."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import Table, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import IdentityCluster, IdentityClusterRepresentative, IdentityMember, MediaIdentity, Tenant
from db.settings import get_database_settings
from recognition.application.clustering.centroid_utils import compute_centroid
from recognition.infrastructure.repositories.atlas_repository import (
    AtlasRepository,
    MixedEmbeddingModelError,
    _coerce_cluster_ids,
    _require_tenant_uuid,
)
from recognition.tests.conftest import _sqlite_vector_norm

_DB_SETTINGS = get_database_settings()
_MODEL_A = "buffalo_l@insightface"
_MODEL_B = "foreign_model@other"
_UNIT_EMBEDDING = [1.0] + [0.0] * (_DB_SETTINGS.pgvector_dimension - 1)
_ALT_EMBEDDING = [0.0, 1.0] + [0.0] * (_DB_SETTINGS.pgvector_dimension - 2)


@pytest_asyncio.fixture
async def atlas_db_session() -> AsyncGenerator[AsyncSession, None]:
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
        tables: list[Table] = [
            Table("tenants", Base.metadata),
            Table("media_identities", Base.metadata),
            Table("identity_clusters", Base.metadata),
            Table("identity_members", Base.metadata),
            Table("identity_cluster_representatives", Base.metadata),
            Table("mv_identity_cluster_centroids", Base.metadata),
        ]
        # ClusterCentroid maps to mv_identity_cluster_centroids; prefer explicit SQL
        # shadow table (matches conftest) so SQLite has identity_count if needed.
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[t for t in tables if t.name != "mv_identity_cluster_centroids"],
        )
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


@pytest_asyncio.fixture
async def atlas_tenant(atlas_db_session: AsyncSession) -> Tenant:
    tenant = Tenant(site_url="https://atlas-repo.example.edu/wp")
    atlas_db_session.add(tenant)
    await atlas_db_session.commit()
    await atlas_db_session.refresh(tenant)
    return tenant


async def _seed_identity(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    media_id: int,
    embedding_model: str = _MODEL_A,
    embedding: list[float] | None = None,
    disposed_at: datetime | None = None,
) -> MediaIdentity:
    identity = MediaIdentity(
        tenant_id=tenant_id,
        media_id=media_id,
        media_url=f"https://atlas-repo.example.edu/media/{media_id}.jpg",
        bbox_x=10,
        bbox_y=12,
        bbox_width=80,
        bbox_height=90,
        confidence=0.91,
        embedding=list(embedding if embedding is not None else _UNIT_EMBEDDING),
        embedding_model=embedding_model,
        disposed_at=disposed_at,
    )
    session.add(identity)
    await session.flush()
    return identity


async def _seed_tenant(session: AsyncSession, site_url: str) -> Tenant:
    tenant = Tenant(site_url=site_url)
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    return tenant


@pytest.mark.asyncio
async def test_iter_tenant_embeddings_filters_model_at_sql_boundary(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    """Only requested-model rows are yielded; foreign model excluded without allow_partial failure path."""
    cluster = IdentityCluster(
        tenant_id=atlas_tenant.id,
        label="C1",
        identity_count=1,
    )
    atlas_db_session.add(cluster)
    await atlas_db_session.flush()

    match = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=7001, embedding_model=_MODEL_A)
    foreign = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=7002, embedding_model=_MODEL_B)
    atlas_db_session.add(
        IdentityMember(
            tenant_id=atlas_tenant.id,
            cluster_id=cluster.id,
            identity_id=match.id,
            similarity=0.99,
        )
    )
    await atlas_db_session.commit()

    repo = AtlasRepository(atlas_db_session)
    # allow_partial so mixed-model fixture does not fail EMB-01 before SQL filter is exercised
    rows = [
        row
        async for row in repo.iter_tenant_embeddings(
            str(atlas_tenant.id), _MODEL_A, allow_partial=True
        )
    ]

    assert len(rows) == 1, f"expected only requested-model row; got {len(rows)}"
    identity_id, media_id, cluster_id, embedding = rows[0]
    assert identity_id == match.id
    assert media_id == 7001
    assert cluster_id == cluster.id
    assert foreign.id not in {r[0] for r in rows}
    assert isinstance(embedding, np.ndarray)
    assert embedding.shape[0] == _DB_SETTINGS.pgvector_dimension


@pytest.mark.asyncio
async def test_emb01_mixed_model_fails_closed_without_allow_partial(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    """Predicted first-run failure: MixedEmbeddingModelError naming foreign model.

    Mutating the guard to (i) reuse majority filter or (ii) skip the COUNT must
    turn this assertion red — verified manually in lane mutation probes.
    """
    await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=7101, embedding_model=_MODEL_A)
    await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=7102, embedding_model=_MODEL_B)
    await atlas_db_session.commit()

    repo = AtlasRepository(atlas_db_session)
    with pytest.raises(MixedEmbeddingModelError) as exc_info:
        _ = [
            row
            async for row in repo.iter_tenant_embeddings(str(atlas_tenant.id), _MODEL_A, allow_partial=False)
        ]

    err = exc_info.value
    assert _MODEL_B in err.foreign_models
    assert _MODEL_A not in err.foreign_models
    assert "EMB-01" in str(err)
    assert _MODEL_B in str(err)


@pytest.mark.asyncio
async def test_emb01_allow_partial_yields_only_requested_model(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=7201, embedding_model=_MODEL_A)
    await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=7202, embedding_model=_MODEL_B)
    await atlas_db_session.commit()

    repo = AtlasRepository(atlas_db_session)
    rows = [
        row
        async for row in repo.iter_tenant_embeddings(
            str(atlas_tenant.id), _MODEL_A, allow_partial=True
        )
    ]
    assert len(rows) == 1
    assert rows[0][1] == 7201


@pytest.mark.asyncio
async def test_centroid_mv_read_and_mean_of_representatives_fallback(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    """MV hit returns stored centroid; missing cluster uses rep mean fallback.

    Predicted first-run failure if fallback omitted: only one pair for two cluster_ids.
    """
    cluster_mv = IdentityCluster(tenant_id=atlas_tenant.id, label="InMV", identity_count=1)
    cluster_miss = IdentityCluster(tenant_id=atlas_tenant.id, label="Miss", identity_count=1)
    atlas_db_session.add_all([cluster_mv, cluster_miss])
    await atlas_db_session.flush()

    id_mv = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=7301)
    id_miss = await _seed_identity(
        atlas_db_session, atlas_tenant.id, media_id=7302, embedding=_ALT_EMBEDDING
    )
    atlas_db_session.add_all(
        [
            IdentityMember(
                tenant_id=atlas_tenant.id,
                cluster_id=cluster_mv.id,
                identity_id=id_mv.id,
                similarity=0.95,
            ),
            IdentityMember(
                tenant_id=atlas_tenant.id,
                cluster_id=cluster_miss.id,
                identity_id=id_miss.id,
                similarity=0.94,
            ),
            IdentityClusterRepresentative(
                tenant_id=atlas_tenant.id,
                cluster_id=cluster_miss.id,
                identity_id=id_miss.id,
                embedding=list(_ALT_EMBEDDING),
                quality_score=0.9,
            ),
        ]
    )
    await atlas_db_session.flush()

    refreshed_at = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    mv_centroid = list(_UNIT_EMBEDDING)
    await atlas_db_session.execute(
        text(
            """
            INSERT INTO mv_identity_cluster_centroids
                (cluster_id, tenant_id, identity_count, centroid, refreshed_at)
            VALUES
                (:cluster_id, :tenant_id, 1, :centroid, :refreshed_at)
            """
        ),
        {
            "cluster_id": str(cluster_mv.id),
            "tenant_id": str(atlas_tenant.id),
            "centroid": memoryview(np.asarray(mv_centroid, dtype=np.float32).tobytes()),
            "refreshed_at": refreshed_at.isoformat(),
        },
    )
    await atlas_db_session.commit()

    repo = AtlasRepository(atlas_db_session)
    pairs, mv_ts = await repo.get_tenant_cluster_centroids(
        str(atlas_tenant.id),
        _MODEL_A,
        cluster_ids=[str(cluster_mv.id), str(cluster_miss.id)],
    )
    by_id = {cid: emb for cid, emb in pairs}

    assert cluster_mv.id in by_id, "MV cluster must appear"
    assert cluster_miss.id in by_id, "missing-MV cluster must use mean-of-representatives fallback"
    expected_fallback = compute_centroid([np.asarray(_ALT_EMBEDDING, dtype=np.float32)])
    np.testing.assert_allclose(by_id[cluster_miss.id], expected_fallback, rtol=1e-5)
    assert mv_ts is not None, "MV refresh timestamp must come from MV row"


@pytest.mark.asyncio
async def test_get_centroids_mv_refreshed_at_from_mv_only(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    cluster = IdentityCluster(tenant_id=atlas_tenant.id, label="TS", identity_count=0)
    atlas_db_session.add(cluster)
    await atlas_db_session.flush()
    refreshed_at = datetime(2026, 6, 15, 8, 30, 0, tzinfo=UTC)
    await atlas_db_session.execute(
        text(
            """
            INSERT INTO mv_identity_cluster_centroids
                (cluster_id, tenant_id, identity_count, centroid, refreshed_at)
            VALUES
                (:cluster_id, :tenant_id, 0, NULL, :refreshed_at)
            """
        ),
        {
            "cluster_id": str(cluster.id),
            "tenant_id": str(atlas_tenant.id),
            "refreshed_at": refreshed_at.isoformat(),
        },
    )
    await atlas_db_session.commit()

    repo = AtlasRepository(atlas_db_session)
    ts = await repo.get_centroids_mv_refreshed_at(str(atlas_tenant.id))
    assert ts is not None
    assert ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
    # SQLite may return naive string-parsed datetime; compare wall clock components
    assert ts.year == 2026 and ts.month == 6 and ts.day == 15


# ---------------------------------------------------------------------------
# FIR-9 S1d discrimination: kill surviving mutants in the atlas read path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_iter_tenant_embeddings_isolates_exact_tenant_id_set(
    atlas_db_session: AsyncSession,
) -> None:
    """FIR-9-BR-02A: tenant filter on iter_tenant_embeddings must be non-vacuous.

    Predicted kill of deleting ``MediaIdentity.tenant_id == tenant_uuid``:
    yielded id set becomes {A, B} instead of exactly {A}.
    """
    tenant_a = await _seed_tenant(atlas_db_session, "https://atlas-a.example.edu/wp")
    tenant_b = await _seed_tenant(atlas_db_session, "https://atlas-b.example.edu/wp")
    id_a = await _seed_identity(atlas_db_session, tenant_a.id, media_id=8001)
    id_b = await _seed_identity(atlas_db_session, tenant_b.id, media_id=8002)
    await atlas_db_session.commit()

    repo = AtlasRepository(atlas_db_session)
    rows = [
        row
        async for row in repo.iter_tenant_embeddings(str(tenant_a.id), _MODEL_A, allow_partial=False)
    ]
    yielded_ids = {row[0] for row in rows}

    assert yielded_ids == {id_a.id}, (
        f"iter_tenant_embeddings must yield exactly tenant A identities; got {yielded_ids}"
    )
    assert id_b.id not in yielded_ids


@pytest.mark.asyncio
async def test_list_foreign_embedding_models_ignores_other_tenant_models(
    atlas_db_session: AsyncSession,
) -> None:
    """FIR-9-BR-02B: foreign-model probe must not see other tenants.

    Tenant B holds a model that would be "foreign" for tenant A's request.
    Predicted kill of deleting tenant_id filter on list_foreign_embedding_models:
    assert_requested_embedding_model raises MixedEmbeddingModelError for tenant A
    even though A only has the requested model.
    """
    tenant_a = await _seed_tenant(atlas_db_session, "https://atlas-a-emb.example.edu/wp")
    tenant_b = await _seed_tenant(atlas_db_session, "https://atlas-b-emb.example.edu/wp")
    await _seed_identity(atlas_db_session, tenant_a.id, media_id=8101, embedding_model=_MODEL_A)
    await _seed_identity(atlas_db_session, tenant_b.id, media_id=8102, embedding_model=_MODEL_B)
    await atlas_db_session.commit()

    repo = AtlasRepository(atlas_db_session)
    foreign = await repo.list_foreign_embedding_models(str(tenant_a.id), _MODEL_A)
    assert foreign == [], (
        f"tenant A must see no foreign models; other-tenant {_MODEL_B!r} leaked as {foreign}"
    )

    # EMB-01 must stay silent for tenant A when only B holds the foreign model.
    await repo.assert_requested_embedding_model(str(tenant_a.id), _MODEL_A, allow_partial=False)


@pytest.mark.asyncio
async def test_iter_tenant_embeddings_excludes_disposed_identities(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    """FIR-9-BR-03: disposed_at IS NULL filter on the read path.

    Predicted kill of deleting ``MediaIdentity.disposed_at.is_(None)``:
    disposed identity re-enters the yielded id set.
    """
    live = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=8201)
    disposed = await _seed_identity(
        atlas_db_session,
        atlas_tenant.id,
        media_id=8202,
        disposed_at=datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC),
    )
    await atlas_db_session.commit()

    repo = AtlasRepository(atlas_db_session)
    rows = [
        row
        async for row in repo.iter_tenant_embeddings(
            str(atlas_tenant.id), _MODEL_A, allow_partial=False
        )
    ]
    yielded_ids = {row[0] for row in rows}

    assert yielded_ids == {live.id}, (
        f"disposed identities must not enter atlas read path; got {yielded_ids}"
    )
    assert disposed.id not in yielded_ids


@pytest.mark.asyncio
async def test_centroid_fallback_uses_representatives_not_members(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    """FIR-9-BR-04A: mean-of-representatives tier when cluster absent from MV.

    Cluster has both a representative (distinct vector) and a member (different
    vector). Correct path must return the representative mean. Mutating the
    first assignment in ``_mean_of_representatives_centroid`` to ``embeddings = []``
    forces member fallback and yields the wrong vector.
    """
    cluster = IdentityCluster(tenant_id=atlas_tenant.id, label="RepTier", identity_count=1)
    atlas_db_session.add(cluster)
    await atlas_db_session.flush()

    member_id = await _seed_identity(
        atlas_db_session, atlas_tenant.id, media_id=8301, embedding=_UNIT_EMBEDDING
    )
    # Separate identity supplies the representative embedding so rep vector != member vector.
    rep_source = await _seed_identity(
        atlas_db_session, atlas_tenant.id, media_id=8302, embedding=_ALT_EMBEDDING
    )
    atlas_db_session.add_all(
        [
            IdentityMember(
                tenant_id=atlas_tenant.id,
                cluster_id=cluster.id,
                identity_id=member_id.id,
                similarity=0.99,
            ),
            IdentityClusterRepresentative(
                tenant_id=atlas_tenant.id,
                cluster_id=cluster.id,
                identity_id=rep_source.id,
                embedding=list(_ALT_EMBEDDING),
                quality_score=0.95,
            ),
        ]
    )
    await atlas_db_session.commit()

    repo = AtlasRepository(atlas_db_session)
    pairs, _ = await repo.get_tenant_cluster_centroids(
        str(atlas_tenant.id),
        _MODEL_A,
        cluster_ids=[str(cluster.id)],
    )
    by_id = {cid: emb for cid, emb in pairs}

    assert cluster.id in by_id, "missing-MV cluster must be filled by representative fallback"
    expected_rep = compute_centroid([np.asarray(_ALT_EMBEDDING, dtype=np.float32)])
    expected_member = compute_centroid([np.asarray(_UNIT_EMBEDDING, dtype=np.float32)])
    np.testing.assert_allclose(by_id[cluster.id], expected_rep, rtol=1e-5)
    # Guard: member mean must differ so a silent member-fallback mutant cannot pass.
    assert not np.allclose(expected_rep, expected_member, rtol=1e-5)


@pytest.mark.asyncio
async def test_centroid_fallback_uses_member_embeddings_when_no_reps(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    """FIR-9-BR-04B: member-fallback tier when no representatives exist.

    Predicted kill of forcing ``get_member_fallback_embeddings`` empty:
    cluster absent from returned pairs (no other source).
    """
    cluster = IdentityCluster(tenant_id=atlas_tenant.id, label="MemTier", identity_count=1)
    atlas_db_session.add(cluster)
    await atlas_db_session.flush()

    member = await _seed_identity(
        atlas_db_session, atlas_tenant.id, media_id=8401, embedding=_ALT_EMBEDDING
    )
    atlas_db_session.add(
        IdentityMember(
            tenant_id=atlas_tenant.id,
            cluster_id=cluster.id,
            identity_id=member.id,
            similarity=0.91,
        )
    )
    await atlas_db_session.commit()

    repo = AtlasRepository(atlas_db_session)
    pairs, _ = await repo.get_tenant_cluster_centroids(
        str(atlas_tenant.id),
        _MODEL_A,
        cluster_ids=[str(cluster.id)],
    )
    by_id = {cid: emb for cid, emb in pairs}

    assert cluster.id in by_id, "member-only missing-MV cluster must use member fallback"
    expected = compute_centroid([np.asarray(_ALT_EMBEDDING, dtype=np.float32)])
    np.testing.assert_allclose(by_id[cluster.id], expected, rtol=1e-5)


def test_require_tenant_uuid_rejects_malformed_id() -> None:
    """FIR-9-BR-05: invalid tenant_id must fail closed with ValueError naming the value.

    Predicted kill of replacing the raise with ``return uuid.UUID(int=0)``:
    this assertion never fires (nil UUID is returned instead).
    """
    bad = "not-a-uuid"
    with pytest.raises(ValueError, match=r"invalid tenant_id: 'not-a-uuid'") as exc_info:
        _require_tenant_uuid(bad)
    assert bad in str(exc_info.value)
    assert "invalid tenant_id" in str(exc_info.value)


def test_coerce_cluster_ids_rejects_malformed_id() -> None:
    """FIR-9-BR-05 companion: invalid cluster_id must name the offending value."""
    bad = "not-a-cluster-id"
    with pytest.raises(ValueError, match=r"invalid cluster_id: 'not-a-cluster-id'") as exc_info:
        _coerce_cluster_ids([bad])
    assert bad in str(exc_info.value)
    assert "invalid cluster_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_iter_tenant_embeddings_rejects_malformed_tenant_id(
    atlas_db_session: AsyncSession,
) -> None:
    """Public read surface must surface the tenant_id ValueError (not query nil UUID)."""
    repo = AtlasRepository(atlas_db_session)
    bad = "%%not-a-uuid%%"
    with pytest.raises(ValueError, match=r"invalid tenant_id:") as exc_info:
        _ = [row async for row in repo.iter_tenant_embeddings(bad, _MODEL_A)]
    assert bad in str(exc_info.value)
