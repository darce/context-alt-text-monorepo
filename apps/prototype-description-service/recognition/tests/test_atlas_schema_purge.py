"""FIR-9 S1a: atlas persistence — cascades, purge counts, uniqueness, RLS membership."""

from __future__ import annotations

import importlib
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import Table, delete, event, func, select, text
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
    IdentityCluster,
    IdentityMember,
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


_ATLAS_PURGE_TABLE_NAMES: tuple[str, ...] = (
    "tenants",
    "media_identities",
    "identity_atlas_runs",
    "identity_atlas_points",
    "identity_atlas_queue_dispositions",
    "audit_events",
    "identity_clusters",
    "identity_members",
    "identity_cluster_representatives",
    "identity_constraints",
    "identity_suggestions",
    "cluster_merge_suggestions",
    "name_suggestions",
    "identity_cluster_blocks",
    "recognition_runs",
    "recognition_events",
    "clustering_feedback",
    "assignment_decisions",
    "clustering_job_reports",
    "curation_replay_records",
    "identity_scan_jobs",
    "identity_scan_job_items",
    "identity_clustering_jobs",
)


async def _atlas_db_session(*, foreign_keys: bool) -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite session with atlas (+ purge) tables; FK enforcement optional."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _register_vector_functions(dbapi_connection, _connection_record) -> None:
        dbapi_connection.create_function("vector_norm", 1, _sqlite_vector_norm)

    fk_pragma = "ON" if foreign_keys else "OFF"
    async with engine.begin() as conn:
        await conn.execute(text(f"PRAGMA foreign_keys={fk_pragma}"))
        tables: list[Table] = [Table(name, Base.metadata) for name in _ATLAS_PURGE_TABLE_NAMES]
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
        # Re-apply on the live connection: StaticPool shares it, but begin() may
        # not leave the pragma sticky for every SQLite/aiosqlite build.
        await session.execute(text(f"PRAGMA foreign_keys={fk_pragma}"))
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
async def atlas_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite session including atlas tables (conftest omits them)."""
    async for session in _atlas_db_session(foreign_keys=True):
        yield session


@pytest_asyncio.fixture
async def atlas_db_session_fk_off() -> AsyncGenerator[AsyncSession, None]:
    """Same schema as atlas_db_session but CASCADE cannot fire (PRAGMA foreign_keys=OFF)."""
    async for session in _atlas_db_session(foreign_keys=False):
        yield session


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
async def test_atlas_purge_disposed_scope_keeps_live_points_and_runs(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    """FIR-9-BR-01: scope=disposed must narrow atlas deletes (kills M1/M2/M3).

    Fixture discriminates three identity arms:
    - disposed identity → point deleted via identity_ids arm of _atlas_point_predicate
    - pure-live identity → point retained
    - live identity that is an identity_members member of a disposed cluster →
      point deleted via membership arm (not denormalized point.cluster_id)

    Predicted RED if predicates return None under disposed (TEST-15):
    - M1 point predicate None → pure-live point deleted / TypeError
    - M2 disposition predicate None → live disposition deleted / TypeError
    - M3 run predicate None → run deleted / TypeError
    """
    live_identity = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=5201)
    disposed_identity = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=5202)
    member_identity = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=5203)
    disposed_identity.disposed_at = datetime.now(tz=UTC)

    disposed_cluster = IdentityCluster(
        tenant_id=atlas_tenant.id,
        label="Disposed membership cluster",
        identity_count=1,
        disposed_at=datetime.now(tz=UTC),
    )
    atlas_db_session.add(disposed_cluster)
    await atlas_db_session.flush()

    # Live cluster with a live member: proves the membership arm is narrowed to
    # *disposed* clusters, not merely "has any identity_members row". Without
    # this, widening the arm to IdentityMember.cluster_id.is_not(None) survives.
    live_cluster = IdentityCluster(
        tenant_id=atlas_tenant.id,
        label="Live membership cluster",
        identity_count=1,
        disposed_at=None,
    )
    atlas_db_session.add(live_cluster)
    await atlas_db_session.flush()

    atlas_db_session.add_all(
        [
            IdentityMember(
                tenant_id=atlas_tenant.id,
                cluster_id=disposed_cluster.id,
                identity_id=member_identity.id,
                similarity=0.96,
            ),
            IdentityMember(
                tenant_id=atlas_tenant.id,
                cluster_id=live_cluster.id,
                identity_id=live_identity.id,
                similarity=0.94,
            ),
        ]
    )

    run = IdentityAtlasRun(
        tenant_id=atlas_tenant.id,
        embedding_model=_EMBEDDING_MODEL,
        status=AtlasRunStatus.COMPLETE.value,
        params=_atlas_params(),
        point_count=3,
    )
    atlas_db_session.add(run)
    await atlas_db_session.flush()

    live_point = IdentityAtlasPoint(
        run_id=run.id,
        tenant_id=atlas_tenant.id,
        identity_id=live_identity.id,
        media_id=live_identity.media_id,
        cluster_id=None,
        x=-0.1,
        y=0.2,
        queue_rank=0,
        uncertainty=_uncertainty(0.15),
    )
    disposed_point = IdentityAtlasPoint(
        run_id=run.id,
        tenant_id=atlas_tenant.id,
        identity_id=disposed_identity.id,
        media_id=disposed_identity.media_id,
        cluster_id=None,
        x=1.1,
        y=-0.3,
        queue_rank=1,
        uncertainty=_uncertainty(0.05),
    )
    # cluster_id deliberately NULL: only identity_members can place this in scope.
    member_point = IdentityAtlasPoint(
        run_id=run.id,
        tenant_id=atlas_tenant.id,
        identity_id=member_identity.id,
        media_id=member_identity.media_id,
        cluster_id=None,
        x=0.4,
        y=0.9,
        queue_rank=2,
        uncertainty=_uncertainty(0.07),
    )
    atlas_db_session.add_all([live_point, disposed_point, member_point])
    await atlas_db_session.flush()

    live_disposition = IdentityAtlasQueueDisposition(
        run_id=run.id,
        point_id=live_point.id,
        tenant_id=atlas_tenant.id,
        action=AtlasDispositionAction.REVIEWED.value,
        actor="admin:disposed-scope",
    )
    disposed_disposition = IdentityAtlasQueueDisposition(
        run_id=run.id,
        point_id=disposed_point.id,
        tenant_id=atlas_tenant.id,
        action=AtlasDispositionAction.SKIPPED.value,
        actor="admin:disposed-scope",
    )
    member_disposition = IdentityAtlasQueueDisposition(
        run_id=run.id,
        point_id=member_point.id,
        tenant_id=atlas_tenant.id,
        action=AtlasDispositionAction.REVIEWED.value,
        actor="admin:disposed-scope",
    )
    atlas_db_session.add_all([live_disposition, disposed_disposition, member_disposition])
    await atlas_db_session.commit()

    live_point_id = live_point.id
    disposed_point_id = disposed_point.id
    member_point_id = member_point.id
    live_disposition_id = live_disposition.id
    disposed_disposition_id = disposed_disposition.id
    member_disposition_id = member_disposition.id
    run_id = run.id
    live_identity_id = live_identity.id
    member_identity_id = member_identity.id
    disposed_cluster_id = disposed_cluster.id

    purge_result = await TenantPurgeService(atlas_db_session).purge_tenant_data(
        str(atlas_tenant.id), "admin:disposed-scope", scope="disposed"
    )
    counts = purge_result["deleted_counts"]
    assert isinstance(counts, dict)

    assert counts.get("identity_atlas_points", 0) == 2, (
        "disposed scope must delete disposed-identity + disposed-cluster-member points "
        f"(not the pure-live point); got {counts.get('identity_atlas_points')}"
    )
    assert counts.get("identity_atlas_runs", 0) == 0, (
        f"disposed scope must not delete atlas runs; got {counts.get('identity_atlas_runs')}"
    )
    assert counts.get("identity_atlas_queue_dispositions", 0) == 2, (
        "disposed scope must report dispositions removed via point CASCADE for the two "
        f"purged points; got {counts.get('identity_atlas_queue_dispositions')}"
    )

    # Expire identity map: FK cascades are not reflected in cached instances.
    atlas_db_session.expire_all()

    remaining_live_point = await atlas_db_session.get(IdentityAtlasPoint, live_point_id)
    remaining_disposed_point = await atlas_db_session.get(IdentityAtlasPoint, disposed_point_id)
    remaining_member_point = await atlas_db_session.get(IdentityAtlasPoint, member_point_id)
    remaining_run = await atlas_db_session.get(IdentityAtlasRun, run_id)
    remaining_live_disposition = await atlas_db_session.get(
        IdentityAtlasQueueDisposition, live_disposition_id
    )
    remaining_disposed_disposition = await atlas_db_session.get(
        IdentityAtlasQueueDisposition, disposed_disposition_id
    )
    remaining_member_disposition = await atlas_db_session.get(
        IdentityAtlasQueueDisposition, member_disposition_id
    )

    assert remaining_live_point is not None, (
        f"pure-live identity point {live_point_id} must SURVIVE disposed purge"
    )
    assert remaining_disposed_point is None, (
        f"disposed identity point {disposed_point_id} must be REMOVED"
    )
    assert remaining_member_point is None, (
        f"membership-scoped point {member_point_id} (live identity member of disposed "
        f"cluster {disposed_cluster_id}) must be REMOVED"
    )
    assert remaining_run is not None, f"atlas run {run_id} must SURVIVE disposed purge"
    assert remaining_live_disposition is not None, (
        f"live point disposition {live_disposition_id} must SURVIVE disposed purge "
        "(disposition predicate is NO_ROWS; only point CASCADE removes dispositions)"
    )
    assert remaining_disposed_disposition is None, (
        f"disposition {disposed_disposition_id} attached to purged point must cascade away"
    )
    assert remaining_member_disposition is None, (
        f"disposition {member_disposition_id} attached to membership-purged point must cascade away"
    )
    assert await atlas_db_session.get(MediaIdentity, live_identity_id) is not None, (
        f"pure-live identity {live_identity_id} row must SURVIVE"
    )
    assert await atlas_db_session.get(MediaIdentity, member_identity_id) is not None, (
        f"member identity {member_identity_id} is not disposed and must SURVIVE"
    )


@pytest.mark.asyncio
async def test_atlas_purge_disposed_scope_with_no_disposed_ids_deletes_zero_atlas_points(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    """FIR-9-BR-01 / TEST-15: NO_ROWS branch of _atlas_point_predicate (second M1 kill).

    Tenant has live atlas data only — no disposed identities and no disposed clusters.
    scope=disposed must delete zero atlas points (and leave runs/dispositions intact).
    Under M1 (point predicate returns None) this fails with TypeError or wipes live rows.
    """
    live_identity = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=5301)
    live_cluster = IdentityCluster(
        tenant_id=atlas_tenant.id,
        label="Live cluster not disposed",
        identity_count=1,
        disposed_at=None,
    )
    atlas_db_session.add(live_cluster)
    await atlas_db_session.flush()

    atlas_db_session.add(
        IdentityMember(
            tenant_id=atlas_tenant.id,
            cluster_id=live_cluster.id,
            identity_id=live_identity.id,
            similarity=0.91,
        )
    )

    run = IdentityAtlasRun(
        tenant_id=atlas_tenant.id,
        embedding_model=_EMBEDDING_MODEL,
        status=AtlasRunStatus.COMPLETE.value,
        params=_atlas_params(),
        point_count=1,
    )
    atlas_db_session.add(run)
    await atlas_db_session.flush()

    live_point = IdentityAtlasPoint(
        run_id=run.id,
        tenant_id=atlas_tenant.id,
        identity_id=live_identity.id,
        media_id=live_identity.media_id,
        cluster_id=live_cluster.id,
        x=0.25,
        y=-0.5,
        queue_rank=0,
        uncertainty=_uncertainty(0.1),
    )
    atlas_db_session.add(live_point)
    await atlas_db_session.flush()

    live_disposition = IdentityAtlasQueueDisposition(
        run_id=run.id,
        point_id=live_point.id,
        tenant_id=atlas_tenant.id,
        action=AtlasDispositionAction.REVIEWED.value,
        actor="admin:no-disposed",
    )
    atlas_db_session.add(live_disposition)
    await atlas_db_session.commit()

    live_point_id = live_point.id
    live_disposition_id = live_disposition.id
    run_id = run.id
    live_cluster_id = live_cluster.id
    live_identity_id = live_identity.id

    purge_result = await TenantPurgeService(atlas_db_session).purge_tenant_data(
        str(atlas_tenant.id), "admin:no-disposed", scope="disposed"
    )
    counts = purge_result["deleted_counts"]
    assert isinstance(counts, dict)

    assert counts.get("identity_atlas_points", 0) == 0, (
        "NO_ROWS: disposed scope with no disposed identity_ids/cluster_ids must delete "
        f"zero atlas points; got {counts.get('identity_atlas_points')}"
    )
    assert counts.get("identity_atlas_runs", 0) == 0, (
        f"NO_ROWS: atlas runs must not be deleted; got {counts.get('identity_atlas_runs')}"
    )
    assert counts.get("identity_atlas_queue_dispositions", 0) == 0, (
        "NO_ROWS: atlas dispositions must not be deleted when no points are purged; "
        f"got {counts.get('identity_atlas_queue_dispositions')}"
    )
    assert counts.get("media_identities", 0) == 0, (
        f"NO_ROWS: no disposed identities to delete; got {counts.get('media_identities')}"
    )
    assert counts.get("identity_clusters", 0) == 0, (
        f"NO_ROWS: no disposed clusters to delete; got {counts.get('identity_clusters')}"
    )

    atlas_db_session.expire_all()

    remaining_point = await atlas_db_session.get(IdentityAtlasPoint, live_point_id)
    remaining_disposition = await atlas_db_session.get(
        IdentityAtlasQueueDisposition, live_disposition_id
    )
    remaining_run = await atlas_db_session.get(IdentityAtlasRun, run_id)
    remaining_cluster = await atlas_db_session.get(IdentityCluster, live_cluster_id)
    remaining_identity = await atlas_db_session.get(MediaIdentity, live_identity_id)

    assert remaining_point is not None, (
        f"live atlas point {live_point_id} must SURVIVE empty disposed-scope purge"
    )
    assert remaining_disposition is not None, (
        f"live disposition {live_disposition_id} must SURVIVE empty disposed-scope purge"
    )
    assert remaining_run is not None, f"atlas run {run_id} must SURVIVE empty disposed-scope purge"
    assert remaining_cluster is not None, (
        f"live cluster {live_cluster_id} must SURVIVE empty disposed-scope purge"
    )
    assert remaining_identity is not None, (
        f"live identity {live_identity_id} must SURVIVE empty disposed-scope purge"
    )


@pytest.mark.asyncio
async def test_atlas_purge_disposed_identities_without_disposed_clusters_uses_single_arm(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    """FIR-9-AMG-02: the single-clause branch of _atlas_point_predicate.

    Disposed identities but NO disposed clusters is the most common production
    shape, and it is the only one that reaches ``if len(clauses) == 1: return
    clauses[0]``. The disposed-scope fixture above always has both arms, so
    without this test that branch is unexercised.

    Goes red if the single-clause branch returns NO_ROWS (disposed point
    survives) or ALL_TENANT_ROWS (live point deleted).
    """
    live_identity = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=5401)
    disposed_identity = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=5402)
    disposed_identity.disposed_at = datetime.now(tz=UTC)

    run = IdentityAtlasRun(
        tenant_id=atlas_tenant.id,
        embedding_model=_EMBEDDING_MODEL,
        status=AtlasRunStatus.COMPLETE.value,
        params=_atlas_params(),
        point_count=2,
    )
    atlas_db_session.add(run)
    await atlas_db_session.flush()

    live_point = IdentityAtlasPoint(
        run_id=run.id,
        tenant_id=atlas_tenant.id,
        identity_id=live_identity.id,
        media_id=live_identity.media_id,
        cluster_id=None,
        x=0.3,
        y=0.3,
        queue_rank=0,
        uncertainty=_uncertainty(0.11),
    )
    disposed_point = IdentityAtlasPoint(
        run_id=run.id,
        tenant_id=atlas_tenant.id,
        identity_id=disposed_identity.id,
        media_id=disposed_identity.media_id,
        cluster_id=None,
        x=-0.7,
        y=0.8,
        queue_rank=1,
        uncertainty=_uncertainty(0.04),
    )
    atlas_db_session.add_all([live_point, disposed_point])
    await atlas_db_session.commit()

    live_point_id = live_point.id
    disposed_point_id = disposed_point.id

    purge_result = await TenantPurgeService(atlas_db_session).purge_tenant_data(
        str(atlas_tenant.id), "admin:single-arm", scope="disposed"
    )
    counts = purge_result["deleted_counts"]
    assert isinstance(counts, dict)
    assert counts.get("identity_atlas_points", 0) == 1, (
        "single-arm disposed scope must delete exactly the disposed identity's point; "
        f"got {counts.get('identity_atlas_points')}"
    )

    atlas_db_session.expire_all()

    remaining_live = await atlas_db_session.get(IdentityAtlasPoint, live_point_id)
    remaining_disposed = await atlas_db_session.get(IdentityAtlasPoint, disposed_point_id)

    assert remaining_live is not None, (
        f"live atlas point {live_point_id} must SURVIVE a single-arm disposed-scope purge "
        "(ALL_TENANT_ROWS on the single-clause branch would delete it)"
    )
    assert remaining_disposed is None, (
        f"disposed atlas point {disposed_point_id} must be DELETED by a single-arm "
        "disposed-scope purge (NO_ROWS on the single-clause branch would retain it)"
    )


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


@pytest.mark.asyncio
async def test_atlas_purge_disposed_cluster_keeps_live_identity_point_with_cluster_id(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    """FIR-9 / FL30-B-03: denormalized point.cluster_id must not drag live points into purge.

    Predicted RED mutation: restore ``or_(..., IdentityAtlasPoint.cluster_id.in_(cluster_ids))``
    → this live-identity point is deleted despite no identity_members ownership row.
    """
    live_identity = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=7201)
    disposed_cluster = IdentityCluster(
        tenant_id=atlas_tenant.id,
        label="Disposed denorm cluster",
        identity_count=0,
        disposed_at=datetime.now(tz=UTC),
    )
    atlas_db_session.add(disposed_cluster)
    await atlas_db_session.flush()

    run = IdentityAtlasRun(
        tenant_id=atlas_tenant.id,
        embedding_model=_EMBEDDING_MODEL,
        status=AtlasRunStatus.COMPLETE.value,
        params=_atlas_params(),
        point_count=1,
    )
    atlas_db_session.add(run)
    await atlas_db_session.flush()

    live_point = IdentityAtlasPoint(
        run_id=run.id,
        tenant_id=atlas_tenant.id,
        identity_id=live_identity.id,
        media_id=live_identity.media_id,
        cluster_id=disposed_cluster.id,
        x=0.5,
        y=-0.25,
        queue_rank=0,
        uncertainty=_uncertainty(0.11),
    )
    atlas_db_session.add(live_point)
    await atlas_db_session.commit()

    live_point_id = live_point.id
    disposed_cluster_id = disposed_cluster.id

    purge_result = await TenantPurgeService(atlas_db_session).purge_tenant_data(
        str(atlas_tenant.id), "admin:cluster-denorm", scope="disposed"
    )
    counts = purge_result["deleted_counts"]
    assert isinstance(counts, dict)

    assert counts.get("identity_clusters", 0) == 1, (
        f"disposed cluster must be purged; got {counts.get('identity_clusters')}"
    )
    assert counts.get("identity_atlas_points", 0) == 0, (
        f"live-identity atlas point must not be purged via denormalized cluster_id; "
        f"got {counts.get('identity_atlas_points')}"
    )

    atlas_db_session.expire_all()
    remaining_point = await atlas_db_session.get(IdentityAtlasPoint, live_point_id)
    remaining_cluster = await atlas_db_session.get(IdentityCluster, disposed_cluster_id)

    assert remaining_point is not None, (
        "point owned by a live identity must SURVIVE purge even when cluster_id "
        "references a disposed cluster"
    )
    assert remaining_point.cluster_id == disposed_cluster_id, (
        "surviving point must retain its denormalized cluster_id value"
    )
    assert remaining_cluster is None, "disposed cluster row must be removed"


@pytest.mark.asyncio
async def test_atlas_purge_disposed_cluster_deletes_points_via_membership(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    """FL30-B-03: disposed-cluster points must be erased via identity_members ownership.

    Live identity remains (not disposed); authoritative membership of a disposed
    cluster still places the atlas point in disposed scope. Denormalized
    cluster_id alone is not trusted — membership is.

    Predicted RED mutation: scope points by ``identity_id.in_(identity_ids)`` only
    (ignoring membership of disposed clusters) → point retained forever after the
    cluster hard-delete, with a dangling ownership relationship erased from members.
    """
    live_identity = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=7210)
    disposed_cluster = IdentityCluster(
        tenant_id=atlas_tenant.id,
        label="Disposed owned cluster",
        identity_count=1,
        disposed_at=datetime.now(tz=UTC),
    )
    atlas_db_session.add(disposed_cluster)
    await atlas_db_session.flush()

    atlas_db_session.add(
        IdentityMember(
            tenant_id=atlas_tenant.id,
            cluster_id=disposed_cluster.id,
            identity_id=live_identity.id,
            similarity=0.97,
        )
    )

    run = IdentityAtlasRun(
        tenant_id=atlas_tenant.id,
        embedding_model=_EMBEDDING_MODEL,
        status=AtlasRunStatus.COMPLETE.value,
        params=_atlas_params(),
        point_count=1,
    )
    atlas_db_session.add(run)
    await atlas_db_session.flush()

    # Deliberately leave denormalized cluster_id NULL so only membership can
    # place this point in disposed scope (not the denorm column).
    owned_point = IdentityAtlasPoint(
        run_id=run.id,
        tenant_id=atlas_tenant.id,
        identity_id=live_identity.id,
        media_id=live_identity.media_id,
        cluster_id=None,
        x=0.7,
        y=-0.4,
        queue_rank=0,
        uncertainty=_uncertainty(0.09),
    )
    atlas_db_session.add(owned_point)
    await atlas_db_session.commit()

    owned_point_id = owned_point.id
    live_identity_id = live_identity.id
    disposed_cluster_id = disposed_cluster.id

    purge_result = await TenantPurgeService(atlas_db_session).purge_tenant_data(
        str(atlas_tenant.id), "admin:cluster-membership", scope="disposed"
    )
    counts = purge_result["deleted_counts"]
    assert isinstance(counts, dict)

    assert counts.get("identity_clusters", 0) == 1, (
        f"disposed cluster must be purged; got {counts.get('identity_clusters')}"
    )
    assert counts.get("identity_atlas_points", 0) == 1, (
        f"point of a disposed-cluster member must be deleted; "
        f"got {counts.get('identity_atlas_points')}"
    )
    assert counts.get("media_identities", 0) == 0, (
        f"live identity must not be deleted; got {counts.get('media_identities')}"
    )

    atlas_db_session.expire_all()
    assert await atlas_db_session.get(IdentityAtlasPoint, owned_point_id) is None, (
        "atlas point belonging to a disposed cluster via identity_members must be removed"
    )
    assert await atlas_db_session.get(MediaIdentity, live_identity_id) is not None, (
        "live identity row must survive (only its disposed-cluster point is erased)"
    )
    assert await atlas_db_session.get(IdentityCluster, disposed_cluster_id) is None


@pytest.mark.asyncio
async def test_atlas_purge_disposed_reports_cascaded_disposition_count(
    atlas_db_session: AsyncSession, atlas_tenant: Tenant
) -> None:
    """FIR-9 / FL30-B-04: disposition deleted_counts must match post-delete reality.

    Predicted RED mutation: report the pre-delete JOIN count without re-checking
    remaining rows (and skip actual cascade) → counter can claim 1 while a row
    still exists. This test asserts count == observed gone rows.
    """
    disposed_identity = await _seed_identity(atlas_db_session, atlas_tenant.id, media_id=7301)
    disposed_identity.disposed_at = datetime.now(tz=UTC)
    await atlas_db_session.flush()

    run = IdentityAtlasRun(
        tenant_id=atlas_tenant.id,
        embedding_model=_EMBEDDING_MODEL,
        status=AtlasRunStatus.COMPLETE.value,
        params=_atlas_params(),
        point_count=1,
    )
    atlas_db_session.add(run)
    await atlas_db_session.flush()

    point = IdentityAtlasPoint(
        run_id=run.id,
        tenant_id=atlas_tenant.id,
        identity_id=disposed_identity.id,
        media_id=disposed_identity.media_id,
        cluster_id=None,
        x=1.0,
        y=2.0,
        queue_rank=0,
        uncertainty=_uncertainty(0.2),
    )
    atlas_db_session.add(point)
    await atlas_db_session.flush()

    disposition = IdentityAtlasQueueDisposition(
        run_id=run.id,
        point_id=point.id,
        tenant_id=atlas_tenant.id,
        action=AtlasDispositionAction.REVIEWED.value,
        actor="admin:cascade-count",
    )
    atlas_db_session.add(disposition)
    await atlas_db_session.commit()

    disposition_id = disposition.id
    point_id = point.id
    tenant_id = atlas_tenant.id

    dispositions_before = int(
        (
            await atlas_db_session.execute(
                select(func.count())
                .select_from(IdentityAtlasQueueDisposition)
                .where(IdentityAtlasQueueDisposition.tenant_id == tenant_id)
            )
        ).scalar_one()
        or 0
    )
    assert dispositions_before == 1

    purge_result = await TenantPurgeService(atlas_db_session).purge_tenant_data(
        str(tenant_id), "admin:cascade-count", scope="disposed"
    )
    counts = purge_result["deleted_counts"]
    assert isinstance(counts, dict)

    atlas_db_session.expire_all()
    dispositions_after = int(
        (
            await atlas_db_session.execute(
                select(func.count())
                .select_from(IdentityAtlasQueueDisposition)
                .where(IdentityAtlasQueueDisposition.tenant_id == tenant_id)
            )
        ).scalar_one()
        or 0
    )
    observed_gone = dispositions_before - dispositions_after

    assert counts.get("identity_atlas_points", 0) == 1, (
        f"disposed identity point must be deleted; got {counts.get('identity_atlas_points')}"
    )
    assert counts.get("identity_atlas_queue_dispositions", 0) == observed_gone, (
        f"reported disposition deletes must equal post-delete row count delta "
        f"({observed_gone}); got {counts.get('identity_atlas_queue_dispositions')}"
    )
    assert observed_gone == 1, f"disposition must actually be gone; remaining={dispositions_after}"

    assert await atlas_db_session.get(IdentityAtlasPoint, point_id) is None
    assert await atlas_db_session.get(IdentityAtlasQueueDisposition, disposition_id) is None


@pytest.mark.asyncio
async def test_atlas_purge_disposed_cascade_count_observes_absent_rows_when_fk_off(
    atlas_db_session_fk_off: AsyncSession,
) -> None:
    """FL30-B-08: disposition count must reflect rows actually gone, not pre-delete intent.

    With foreign_keys=OFF the point delete does not cascade, so a disposition row
    listed pre-delete still exists post-delete. Honest observation reports 0;
    ``cascaded = len(disposition_ids)`` would falsely report 1.
    """
    session = atlas_db_session_fk_off
    # Ensure the live connection still has cascade suppressed (savepoint start).
    await session.execute(text("PRAGMA foreign_keys=OFF"))
    fk_row = (await session.execute(text("PRAGMA foreign_keys"))).one()
    assert int(fk_row[0]) == 0, f"test requires foreign_keys=OFF; got {fk_row!r}"

    tenant = Tenant(site_url="https://atlas-fk-off.example.edu/wp")
    session.add(tenant)
    await session.flush()

    disposed_identity = await _seed_identity(session, tenant.id, media_id=7401)
    disposed_identity.disposed_at = datetime.now(tz=UTC)
    await session.flush()

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
        identity_id=disposed_identity.id,
        media_id=disposed_identity.media_id,
        cluster_id=None,
        x=3.0,
        y=4.0,
        queue_rank=0,
        uncertainty=_uncertainty(0.15),
    )
    session.add(point)
    await session.flush()

    disposition = IdentityAtlasQueueDisposition(
        run_id=run.id,
        point_id=point.id,
        tenant_id=tenant.id,
        action=AtlasDispositionAction.REVIEWED.value,
        actor="admin:cascade-observe",
    )
    session.add(disposition)
    await session.commit()

    disposition_id = disposition.id
    point_id = point.id
    tenant_id = tenant.id

    dispositions_before = int(
        (
            await session.execute(
                select(func.count())
                .select_from(IdentityAtlasQueueDisposition)
                .where(IdentityAtlasQueueDisposition.tenant_id == tenant_id)
            )
        ).scalar_one()
        or 0
    )
    assert dispositions_before == 1

    purge_result = await TenantPurgeService(session).purge_tenant_data(
        str(tenant_id), "admin:cascade-observe", scope="disposed"
    )
    counts = purge_result["deleted_counts"]
    assert isinstance(counts, dict)

    session.expire_all()
    dispositions_after = int(
        (
            await session.execute(
                select(func.count())
                .select_from(IdentityAtlasQueueDisposition)
                .where(IdentityAtlasQueueDisposition.tenant_id == tenant_id)
            )
        ).scalar_one()
        or 0
    )
    observed_gone = dispositions_before - dispositions_after

    assert await session.get(IdentityAtlasPoint, point_id) is None, (
        "point must still be deleted by the purge even when cascade is suppressed"
    )
    assert await session.get(IdentityAtlasQueueDisposition, disposition_id) is not None, (
        "with foreign_keys=OFF the disposition must survive point delete — "
        "otherwise this test cannot discriminate pre-delete vs observed counts"
    )
    assert observed_gone == 0, (
        f"cascade suppressed: disposition must remain; remaining={dispositions_after}"
    )
    assert counts.get("identity_atlas_queue_dispositions", 0) == observed_gone, (
        f"reported disposition deletes must equal rows actually gone ({observed_gone}); "
        f"got {counts.get('identity_atlas_queue_dispositions')} "
        f"(defective pre-delete JOIN count would report 1)"
    )


async def _shipped_atlas_schema_engine():
    """In-memory engine with Base.metadata atlas tables and foreign_keys=ON."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        tables: list[Table] = [
            Table("tenants", Base.metadata),
            Table("media_identities", Base.metadata),
            Table("identity_atlas_runs", Base.metadata),
            Table("identity_atlas_points", Base.metadata),
            Table("identity_atlas_queue_dispositions", Base.metadata),
        ]
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    return engine


@pytest.mark.asyncio
async def test_atlas_disposition_rejects_cross_run_point_attachment() -> None:
    """FIR-9: composite FK on the shipped ORM schema forces disposition.run_id == point.run_id.

    Builds schema from Base.metadata (the application ships this, not hand-written DDL).
    Predicted RED mutations:
    - Drop ``ForeignKeyConstraint`` / ``uq_identity_atlas_points_id_run`` from the ORM
      model → cross-run insert succeeds (no IntegrityError).
    - Drop ``ondelete='CASCADE'`` from that FK → point delete leaves the disposition row.
    """
    engine = await _shipped_atlas_schema_engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        await session.execute(text("PRAGMA foreign_keys=ON"))

        tenant = Tenant(site_url="https://atlas-cross-run.example.edu/wp")
        session.add(tenant)
        await session.flush()

        identity = MediaIdentity(
            tenant_id=tenant.id,
            media_id=9901,
            media_url="https://atlas-cross-run.example.edu/media/9901.jpg",
            bbox_x=1,
            bbox_y=1,
            bbox_width=10,
            bbox_height=10,
            confidence=0.9,
            embedding=list(_UNIT_EMBEDDING),
            embedding_model=_EMBEDDING_MODEL,
        )
        session.add(identity)
        await session.flush()

        run_a = IdentityAtlasRun(
            tenant_id=tenant.id,
            embedding_model=_EMBEDDING_MODEL,
            status=AtlasRunStatus.COMPLETE.value,
            params=_atlas_params(),
            point_count=1,
        )
        run_b = IdentityAtlasRun(
            tenant_id=tenant.id,
            embedding_model=_EMBEDDING_MODEL,
            status=AtlasRunStatus.COMPLETE.value,
            params=_atlas_params(),
            point_count=0,
        )
        session.add_all([run_a, run_b])
        await session.flush()

        point = IdentityAtlasPoint(
            run_id=run_a.id,
            tenant_id=tenant.id,
            identity_id=identity.id,
            media_id=identity.media_id,
            cluster_id=None,
            x=0.0,
            y=0.0,
            queue_rank=0,
            uncertainty=_uncertainty(0.1),
        )
        session.add(point)
        await session.flush()

        session.add(
            IdentityAtlasQueueDisposition(
                run_id=run_b.id,
                point_id=point.id,
                tenant_id=tenant.id,
                action=AtlasDispositionAction.REVIEWED.value,
                actor="admin:cross-run",
            )
        )
        with pytest.raises(IntegrityError) as cross_run_exc:
            await session.flush()
        message = str(cross_run_exc.value).upper()
        assert "FOREIGN KEY" in message or "CONSTRAINT" in message, (
            f"cross-run disposition must be rejected by composite FK; got {cross_run_exc.value!r}"
        )

    # Separate session: prove ON DELETE CASCADE on the shipped composite FK.
    async with session_factory() as session:
        await session.execute(text("PRAGMA foreign_keys=ON"))
        tenant = Tenant(site_url="https://atlas-cascade.example.edu/wp")
        session.add(tenant)
        await session.flush()
        identity = MediaIdentity(
            tenant_id=tenant.id,
            media_id=9902,
            media_url="https://atlas-cascade.example.edu/media/9902.jpg",
            bbox_x=1,
            bbox_y=1,
            bbox_width=10,
            bbox_height=10,
            confidence=0.9,
            embedding=list(_UNIT_EMBEDDING),
            embedding_model=_EMBEDDING_MODEL,
        )
        session.add(identity)
        await session.flush()
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
            x=1.0,
            y=1.0,
            queue_rank=0,
            uncertainty=_uncertainty(0.2),
        )
        session.add(point)
        await session.flush()
        disposition = IdentityAtlasQueueDisposition(
            run_id=run.id,
            point_id=point.id,
            tenant_id=tenant.id,
            action=AtlasDispositionAction.SKIPPED.value,
            actor="admin:cascade-fk",
        )
        session.add(disposition)
        await session.flush()
        disposition_id = disposition.id
        point_id = point.id

        # Bulk SQL DELETE (not session.delete) so ORM relationship cascade cannot
        # paper over a missing DB-level ON DELETE CASCADE on the composite FK.
        await session.execute(delete(IdentityAtlasPoint).where(IdentityAtlasPoint.id == point_id))
        await session.commit()
        session.expire_all()

        remaining_point = await session.get(IdentityAtlasPoint, point_id)
        remaining_disp = await session.get(IdentityAtlasQueueDisposition, disposition_id)
        assert remaining_point is None, "point must be deleted"
        assert remaining_disp is None, (
            "ON DELETE CASCADE on the shipped composite FK must remove dispositions "
            f"when their point is deleted; disposition {disposition_id} still present"
        )

    await engine.dispose()


# ---------------------------------------------------------------------------
# FIR-9 B-02: structural migration↔ORM parity (object graphs, not source text)
# ---------------------------------------------------------------------------


class _EnsureTablesRecorder:
    """Recording alembic ``op`` for ``ensure_tables`` — captures declared DDL objects."""

    def __init__(self) -> None:
        self.table_args: dict[str, tuple[object, ...]] = {}
        self.indexes: list[tuple[str, str, list[str]]] = []

    def get_bind(self):
        class _Result:
            def __init__(self, row):
                self._row = row

            def scalar(self):
                return self._row[0] if self._row else None

            def __iter__(self):
                return iter(())

            def first(self):
                return self._row

        class _Bind:
            def execute(self, stmt, params=None):  # noqa: ANN001
                # Nothing exists → every create_table / create_index is recorded.
                return _Result(None)

        return _Bind()

    def create_table(self, name: str, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.table_args[name] = args

    def create_index(
        self, name: str, table_name: str, columns: list[str], *args, **kwargs
    ) -> None:  # noqa: ANN002, ANN003
        self.indexes.append((name, table_name, list(columns)))

    def add_column(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise AssertionError("add_column unexpected while recording ensure_tables")


def _record_ensure_tables() -> _EnsureTablesRecorder:
    recorder = _EnsureTablesRecorder()
    identity_schema.ensure_tables(recorder)
    return recorder


def _named_table_constraints(elements: tuple[object, ...]) -> dict[str, object]:
    import sqlalchemy as sa

    out: dict[str, object] = {}
    for el in elements:
        if isinstance(el, (sa.UniqueConstraint, sa.ForeignKeyConstraint, sa.CheckConstraint)):
            name = getattr(el, "name", None)
            if name:
                out[str(name)] = el
    return out


def _unique_columns(constraint) -> tuple[str, ...]:
    # Unbound UniqueConstraint (fresh from ensure_tables) keeps names in
    # _pending_colargs until attached to a Table; bound ORM constraints use .columns.
    cols = tuple(col.name for col in constraint.columns)
    if cols:
        return cols
    pending = getattr(constraint, "_pending_colargs", None) or ()
    return tuple(str(c) for c in pending)


def _fk_local_columns(constraint) -> tuple[str, ...]:
    # ForeignKeyConstraint.column_keys is the local side in declaration order.
    return tuple(constraint.column_keys)


def _fk_remote_columns(constraint) -> tuple[str, ...]:
    return tuple(str(el.target_fullname) for el in constraint.elements)


def _fk_ondelete(constraint) -> str | None:
    # Table-level FK: ondelete lives on the constraint or its elements.
    ondelete = getattr(constraint, "ondelete", None)
    if ondelete is not None:
        return str(ondelete)
    for el in constraint.elements:
        if el.ondelete is not None:
            return str(el.ondelete)
    return None


def _orm_named_constraints(table_name: str) -> dict[str, object]:
    from db.base import Base

    table = Base.metadata.tables[table_name]
    out: dict[str, object] = {}
    for c in table.constraints:
        name = getattr(c, "name", None)
        if name:
            out[str(name)] = c
    return out


def _orm_index_columns(table_name: str) -> dict[str, tuple[str, ...]]:
    from db.base import Base

    table = Base.metadata.tables[table_name]
    return {idx.name: tuple(col.name for col in idx.columns) for idx in table.indexes if idx.name}


def test_atlas_purge_supporting_indexes_declared_in_schema() -> None:
    """FIR-9 B4: purge/CASCADE supporting indexes — structural migration↔ORM parity.

    Compares index *objects* captured from ``ensure_tables`` against
    ``Base.metadata`` indexes for the same tables. Reformatting the migration
    source cannot green this; removing either side turns it red.
    """
    recorder = _record_ensure_tables()
    mig_indexes = {
        name: (table, tuple(cols)) for name, table, cols in recorder.indexes
    }

    required = {
        "idx_identity_atlas_points_tenant_identity": (
            "identity_atlas_points",
            ("tenant_id", "identity_id"),
        ),
        "idx_identity_atlas_queue_dispositions_point": (
            "identity_atlas_queue_dispositions",
            ("point_id",),
        ),
    }
    for name, (table, cols) in required.items():
        assert name in mig_indexes, f"migration ensure_tables missing index {name!r}"
        assert mig_indexes[name] == (table, cols), (
            f"migration index {name!r} declared as {mig_indexes[name]!r}, expected {(table, cols)!r}"
        )
        orm_idx = _orm_index_columns(table)
        assert name in orm_idx, f"ORM model for {table!r} missing index {name!r}"
        assert orm_idx[name] == cols, (
            f"ORM index {name!r} columns {orm_idx[name]!r} != migration {cols!r}"
        )


def test_atlas_disposition_run_matches_point_constraint_declared() -> None:
    """FIR-9 B3: composite unique + FK — structural migration↔ORM parity.

    Captures ``UniqueConstraint`` / ``ForeignKeyConstraint`` objects from
    ``ensure_tables`` and compares name, column tuples, and ``ondelete`` to
    ``Base.metadata``. A comment that still contains the constraint name cannot
    pass; removing the constraint from either side fails.
    """
    import sqlalchemy as sa

    recorder = _record_ensure_tables()

    points_mig = _named_table_constraints(recorder.table_args["identity_atlas_points"])
    disp_mig = _named_table_constraints(recorder.table_args["identity_atlas_queue_dispositions"])
    points_orm = _orm_named_constraints("identity_atlas_points")
    disp_orm = _orm_named_constraints("identity_atlas_queue_dispositions")

    # Composite unique target on points (id, run_id).
    uq_name = "uq_identity_atlas_points_id_run"
    assert uq_name in points_mig, "migration must declare composite unique on points"
    assert uq_name in points_orm, "ORM must declare composite unique on points"
    assert isinstance(points_mig[uq_name], sa.UniqueConstraint)
    assert isinstance(points_orm[uq_name], sa.UniqueConstraint)
    mig_uq_cols = _unique_columns(points_mig[uq_name])
    orm_uq_cols = _unique_columns(points_orm[uq_name])
    assert mig_uq_cols == ("id", "run_id"), f"migration unique columns {mig_uq_cols!r}"
    assert orm_uq_cols == ("id", "run_id"), f"ORM unique columns {orm_uq_cols!r}"
    assert mig_uq_cols == orm_uq_cols

    # Composite FK on dispositions: (point_id, run_id) → points (id, run_id) ON DELETE CASCADE.
    fk_name = "fk_identity_atlas_dispositions_point_run"
    assert fk_name in disp_mig, "migration must declare composite FK on dispositions"
    assert fk_name in disp_orm, "ORM must declare composite FK on dispositions"
    assert isinstance(disp_mig[fk_name], sa.ForeignKeyConstraint)
    assert isinstance(disp_orm[fk_name], sa.ForeignKeyConstraint)

    mig_local = _fk_local_columns(disp_mig[fk_name])
    orm_local = _fk_local_columns(disp_orm[fk_name])
    assert mig_local == ("point_id", "run_id"), f"migration FK local cols {mig_local!r}"
    assert orm_local == ("point_id", "run_id"), f"ORM FK local cols {orm_local!r}"
    assert mig_local == orm_local

    mig_remote = _fk_remote_columns(disp_mig[fk_name])
    orm_remote = _fk_remote_columns(disp_orm[fk_name])
    assert mig_remote == (
        "identity_atlas_points.id",
        "identity_atlas_points.run_id",
    ), f"migration FK remote {mig_remote!r}"
    assert orm_remote == (
        "identity_atlas_points.id",
        "identity_atlas_points.run_id",
    ), f"ORM FK remote {orm_remote!r}"
    assert mig_remote == orm_remote

    mig_ondelete = _fk_ondelete(disp_mig[fk_name])
    orm_ondelete = _fk_ondelete(disp_orm[fk_name])
    assert mig_ondelete == "CASCADE", f"migration ondelete={mig_ondelete!r}"
    assert orm_ondelete == "CASCADE", f"ORM ondelete={orm_ondelete!r}"
    assert mig_ondelete == orm_ondelete
