"""FIR-9 S1a: atlas persistence — cascades, purge counts, uniqueness, RLS membership."""

from __future__ import annotations

import importlib
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import Table, delete, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import (
    AtlasDispositionAction,
    AtlasRunStatus,
    IdentityAtlasPoint,
    IdentityAtlasQueueDisposition,
    IdentityAtlasRun,
    MediaIdentity,
    Tenant,
)
from db.settings import get_database_settings
from recognition.application.services.purge_service import TenantPurgeService
from recognition.tests.conftest import _sqlite_vector_norm

identity_schema = importlib.import_module("db.migrations.versions.001_identity_schema")

_DB_SETTINGS = get_database_settings()
_EMBEDDING_MODEL = "buffalo_l@insightface"
_UNIT_EMBEDDING = [1.0] + [0.0] * (_DB_SETTINGS.pgvector_dimension - 1)


def _atlas_params() -> dict:
    return {
        "umap": {"n_neighbors": 15, "min_dist": 0.1, "random_state": 42},
        "score_recipe": "margin_v1",
        "package_versions": {"umap-learn": "0.5.6"},
    }


def _uncertainty(margin: float = 0.12) -> dict:
    return {
        "margin": margin,
        "intra_cluster_percentile": 0.35,
        "near_threshold": False,
        "composite": 0.41,
    }


@pytest_asyncio.fixture
async def atlas_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite session including atlas tables (conftest omits them)."""
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
            Table("identity_atlas_runs", Base.metadata),
            Table("identity_atlas_points", Base.metadata),
            Table("identity_atlas_queue_dispositions", Base.metadata),
            Table("audit_events", Base.metadata),
            Table("identity_clusters", Base.metadata),
            Table("identity_members", Base.metadata),
            Table("identity_cluster_representatives", Base.metadata),
            Table("identity_constraints", Base.metadata),
            Table("identity_suggestions", Base.metadata),
            Table("cluster_merge_suggestions", Base.metadata),
            Table("name_suggestions", Base.metadata),
            Table("identity_cluster_blocks", Base.metadata),
            Table("recognition_runs", Base.metadata),
            Table("recognition_events", Base.metadata),
            Table("clustering_feedback", Base.metadata),
            Table("assignment_decisions", Base.metadata),
            Table("clustering_job_reports", Base.metadata),
            Table("curation_replay_records", Base.metadata),
            Table("identity_scan_jobs", Base.metadata),
            Table("identity_scan_job_items", Base.metadata),
            Table("identity_clustering_jobs", Base.metadata),
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


@pytest_asyncio.fixture
async def atlas_tenant(atlas_db_session: AsyncSession) -> Tenant:
    tenant = Tenant(site_url="https://atlas.example.edu/wp")
    atlas_db_session.add(tenant)
    await atlas_db_session.commit()
    await atlas_db_session.refresh(tenant)
    return tenant


async def _seed_identity(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    media_id: int = 4201,
) -> MediaIdentity:
    identity = MediaIdentity(
        tenant_id=tenant_id,
        media_id=media_id,
        media_url=f"https://atlas.example.edu/media/{media_id}.jpg",
        bbox_x=12,
        bbox_y=18,
        bbox_width=96,
        bbox_height=112,
        confidence=0.94,
        embedding=list(_UNIT_EMBEDDING),
        embedding_model=_EMBEDDING_MODEL,
    )
    session.add(identity)
    await session.flush()
    return identity


async def _seed_atlas_graph(
    session: AsyncSession,
    tenant: Tenant,
    identity: MediaIdentity,
    *,
    queue_rank: int = 0,
    x: float = -1.25,
    y: float = 0.87,
) -> tuple[IdentityAtlasRun, IdentityAtlasPoint, IdentityAtlasQueueDisposition]:
    run = IdentityAtlasRun(
        tenant_id=tenant.id,
        embedding_model=_EMBEDDING_MODEL,
        status=AtlasRunStatus.COMPLETE.value,
        params=_atlas_params(),
        point_count=1,
    )
    session.add(run)
    await session.flush()

    point = IdentityAtlasPoint(
        run_id=run.id,
        tenant_id=tenant.id,
        identity_id=identity.id,
        media_id=identity.media_id,
        cluster_id=None,
        x=x,
        y=y,
        queue_rank=queue_rank,
        uncertainty=_uncertainty(),
    )
    session.add(point)
    await session.flush()

    disposition = IdentityAtlasQueueDisposition(
        run_id=run.id,
        point_id=point.id,
        tenant_id=tenant.id,
        action=AtlasDispositionAction.REVIEWED.value,
        actor="admin:atlas-curator",
    )
    session.add(disposition)
    await session.commit()
    return run, point, disposition


@pytest.mark.asyncio
async def test_atlas_cascade_identity_deletes_points_and_dispositions(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    identity = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=4201)
    run, point, disposition = await _seed_atlas_graph(atlas_db_session, atlas_tenant, identity)

    await atlas_db_session.execute(delete(MediaIdentity).where(MediaIdentity.id == identity.id))
    await atlas_db_session.commit()

    remaining_points = (
        await atlas_db_session.execute(select(IdentityAtlasPoint).where(IdentityAtlasPoint.id == point.id))
    ).scalars().all()
    remaining_dispositions = (
        await atlas_db_session.execute(
            select(IdentityAtlasQueueDisposition).where(IdentityAtlasQueueDisposition.id == disposition.id)
        )
    ).scalars().all()
    remaining_run = await atlas_db_session.get(IdentityAtlasRun, run.id)

    assert remaining_points == [], (
        f"deleting media_identities must CASCADE-delete identity_atlas_points; "
        f"still have {len(remaining_points)} point(s)"
    )
    assert remaining_dispositions == [], (
        f"deleting media_identities must CASCADE-delete identity_atlas_queue_dispositions via points; "
        f"still have {len(remaining_dispositions)} disposition(s)"
    )
    assert remaining_run is not None, "deleting an identity must not remove the atlas run itself"


@pytest.mark.asyncio
async def test_atlas_cascade_run_deletes_points_and_dispositions(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    identity = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=4202)
    run, point, disposition = await _seed_atlas_graph(
        atlas_db_session, atlas_tenant, identity, queue_rank=3, x=0.15, y=-2.4
    )

    await atlas_db_session.execute(delete(IdentityAtlasRun).where(IdentityAtlasRun.id == run.id))
    await atlas_db_session.commit()

    remaining_points = (
        await atlas_db_session.execute(select(IdentityAtlasPoint).where(IdentityAtlasPoint.id == point.id))
    ).scalars().all()
    remaining_dispositions = (
        await atlas_db_session.execute(
            select(IdentityAtlasQueueDisposition).where(IdentityAtlasQueueDisposition.id == disposition.id)
        )
    ).scalars().all()
    remaining_identity = await atlas_db_session.get(MediaIdentity, identity.id)

    assert remaining_points == [], (
        f"deleting identity_atlas_runs must CASCADE-delete points; still have {len(remaining_points)}"
    )
    assert remaining_dispositions == [], (
        f"deleting identity_atlas_runs must CASCADE-delete dispositions; still have {len(remaining_dispositions)}"
    )
    assert remaining_identity is not None, "deleting an atlas run must not remove media_identities"


@pytest.mark.asyncio
async def test_atlas_cascade_tenant_empties_all_three_tables(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    identity = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=4203)
    run, point, disposition = await _seed_atlas_graph(
        atlas_db_session, atlas_tenant, identity, queue_rank=1, x=2.05, y=1.11
    )
    tenant_id = atlas_tenant.id

    await atlas_db_session.execute(delete(Tenant).where(Tenant.id == tenant_id))
    await atlas_db_session.commit()

    runs = (
        await atlas_db_session.execute(select(IdentityAtlasRun).where(IdentityAtlasRun.tenant_id == tenant_id))
    ).scalars().all()
    points = (
        await atlas_db_session.execute(select(IdentityAtlasPoint).where(IdentityAtlasPoint.tenant_id == tenant_id))
    ).scalars().all()
    dispositions = (
        await atlas_db_session.execute(
            select(IdentityAtlasQueueDisposition).where(IdentityAtlasQueueDisposition.tenant_id == tenant_id)
        )
    ).scalars().all()

    assert runs == [], f"deleting tenants must CASCADE-empty identity_atlas_runs; still have {len(runs)}"
    assert points == [], f"deleting tenants must CASCADE-empty identity_atlas_points; still have {len(points)}"
    assert dispositions == [], (
        f"deleting tenants must CASCADE-empty identity_atlas_queue_dispositions; still have {len(dispositions)}"
    )
    # silence unused binding warnings when cascade removes children first
    assert run.id and point.id and disposition.id


@pytest.mark.asyncio
async def test_atlas_purge_counts_include_non_zero_atlas_rows(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    identity_a = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=5101)
    identity_b = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=5102)

    run = IdentityAtlasRun(
        tenant_id=atlas_tenant.id,
        embedding_model=_EMBEDDING_MODEL,
        status=AtlasRunStatus.COMPLETE.value,
        params=_atlas_params(),
        point_count=2,
    )
    atlas_db_session.add(run)
    await atlas_db_session.flush()

    point_a = IdentityAtlasPoint(
        run_id=run.id,
        tenant_id=atlas_tenant.id,
        identity_id=identity_a.id,
        media_id=identity_a.media_id,
        cluster_id=None,
        x=-0.42,
        y=1.73,
        queue_rank=0,
        uncertainty=_uncertainty(0.08),
    )
    point_b = IdentityAtlasPoint(
        run_id=run.id,
        tenant_id=atlas_tenant.id,
        identity_id=identity_b.id,
        media_id=identity_b.media_id,
        cluster_id=None,
        x=1.02,
        y=-0.55,
        queue_rank=1,
        uncertainty=_uncertainty(0.22),
    )
    atlas_db_session.add_all([point_a, point_b])
    await atlas_db_session.flush()

    atlas_db_session.add_all(
        [
            IdentityAtlasQueueDisposition(
                run_id=run.id,
                point_id=point_a.id,
                tenant_id=atlas_tenant.id,
                action=AtlasDispositionAction.REVIEWED.value,
                actor="admin:purge-fixture",
            ),
            IdentityAtlasQueueDisposition(
                run_id=run.id,
                point_id=point_b.id,
                tenant_id=atlas_tenant.id,
                action=AtlasDispositionAction.SKIPPED.value,
                actor="admin:purge-fixture",
            ),
        ]
    )
    await atlas_db_session.commit()

    purge_result = await TenantPurgeService(atlas_db_session).purge_tenant_data(
        str(atlas_tenant.id), "admin:purge-fixture", scope="all"
    )
    counts = purge_result["deleted_counts"]
    assert isinstance(counts, dict)

    points_deleted = counts.get("identity_atlas_points", 0)
    dispositions_deleted = counts.get("identity_atlas_queue_dispositions", 0)
    runs_deleted = counts.get("identity_atlas_runs", 0)

    assert points_deleted == 2, (
        f"purging tenant must delete atlas points; got {points_deleted}"
    )
    assert dispositions_deleted == 2, (
        f"purging tenant must delete atlas dispositions; got {dispositions_deleted}"
    )
    assert runs_deleted == 1, (
        f"purging tenant must delete atlas runs; got {runs_deleted}"
    )


@pytest.mark.asyncio
async def test_atlas_unique_points_reject_duplicate_run_identity(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    tenant_id = atlas_tenant.id
    identity = await _seed_identity(atlas_db_session, tenant_id, media_id=6101)
    run, _point, _disposition = await _seed_atlas_graph(
        atlas_db_session, atlas_tenant, identity, queue_rank=5, x=0.33, y=0.66
    )
    run_id = run.id
    identity_id = identity.id
    media_id = identity.media_id

    atlas_db_session.add(
        IdentityAtlasPoint(
            run_id=run_id,
            tenant_id=tenant_id,
            identity_id=identity_id,
            media_id=media_id,
            cluster_id=None,
            x=9.9,
            y=9.9,
            queue_rank=99,
            uncertainty=_uncertainty(0.01),
        )
    )
    with pytest.raises(IntegrityError) as point_exc:
        await atlas_db_session.flush()
    message = str(point_exc.value).upper()
    assert "UNIQUE" in message, (
        f"duplicate (run_id, identity_id) must violate uniqueness; got {point_exc.value!r}"
    )


@pytest.mark.asyncio
async def test_atlas_unique_dispositions_reject_duplicate_run_point(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    tenant_id = atlas_tenant.id
    identity = await _seed_identity(atlas_db_session, tenant_id, media_id=6102)
    run, point, _disposition = await _seed_atlas_graph(
        atlas_db_session, atlas_tenant, identity, queue_rank=6, x=0.44, y=0.77
    )
    run_id = run.id
    point_id = point.id

    atlas_db_session.add(
        IdentityAtlasQueueDisposition(
            run_id=run_id,
            point_id=point_id,
            tenant_id=tenant_id,
            action=AtlasDispositionAction.SKIPPED.value,
            actor="admin:duplicate-attempt",
        )
    )
    with pytest.raises(IntegrityError) as disp_exc:
        await atlas_db_session.flush()
    message = str(disp_exc.value).upper()
    assert "UNIQUE" in message, (
        f"duplicate (run_id, point_id) must violate uniqueness; got {disp_exc.value!r}"
    )


def test_atlas_tables_are_in_tenant_tables() -> None:
    tenant_tables = set(identity_schema.TENANT_TABLES)
    for name in (
        "identity_atlas_runs",
        "identity_atlas_points",
        "identity_atlas_queue_dispositions",
    ):
        assert name in tenant_tables, (
            f"{name} must be in TENANT_TABLES so RLS enable/force + policies apply"
        )
    assert "identity_atlas_runs" not in identity_schema.RAW_SQL_TABLES
    assert "identity_atlas_points" not in identity_schema.RAW_SQL_TABLES
    assert "identity_atlas_queue_dispositions" not in identity_schema.RAW_SQL_TABLES
