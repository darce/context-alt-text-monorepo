"""UXP-2 Slice 3a: the ROW_NUMBER windowed batch query proven against Postgres.

The sqlite+aiosqlite suite (``test_identity_suggestions_batch.py``) carries the
full 60-identity parity fixture; this pg-marked test executes the same
repository query (``SqlAlchemySuggestionRepository.list_for_identities``)
against a real migrated Postgres scratch DB (``pg_migrated_engine``) with a
minimal fixture, closing the plan's "SQLite AND Postgres" portability
requirement. Skips cleanly (never fails) when Postgres is unreachable,
matching the rest of the pg suite (see ``recognition/tests/conftest.py``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import IdentityCluster as ClusterModel
from db.models import IdentitySuggestion as SuggestionModel
from db.models import MediaIdentity as MediaIdentityModel
from db.models import Tenant
from recognition.domain.suggestion import SuggestionStatus
from recognition.infrastructure.repositories import SqlAlchemySuggestionRepository

pytestmark = pytest.mark.pg

BASE_TIME = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
EMBEDDING_DIM = 512


def _unit_embedding() -> list[float]:
    embedding = [0.0] * EMBEDDING_DIM
    embedding[0] = 1.0
    return embedding


async def _seed_identity(session: AsyncSession, tenant_id: uuid.UUID, media_id: int) -> str:
    identity = MediaIdentityModel(
        tenant_id=tenant_id,
        media_id=media_id,
        media_url=f"http://example.test/{media_id}.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=_unit_embedding(),
    )
    session.add(identity)
    await session.flush()
    return str(identity.id)


async def _seed_cluster(session: AsyncSession, tenant_id: uuid.UUID, label: str | None) -> str:
    cluster = ClusterModel(tenant_id=tenant_id, label=label, identity_count=1)
    session.add(cluster)
    await session.flush()
    return str(cluster.id)


def _add_suggestion(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    identity_id: str,
    cluster_id: str,
    similarity: float,
    created_at: datetime,
    resolution: str = SuggestionStatus.PENDING.value,
) -> None:
    session.add(
        SuggestionModel(
            tenant_id=tenant_id,
            identity_id=uuid.UUID(identity_id),
            suggested_cluster_id=uuid.UUID(cluster_id),
            representative_similarity=similarity,
            avg_member_similarity=similarity,
            confidence_score=similarity,
            resolution=resolution,
            created_at=created_at,
        )
    )


@pytest.mark.asyncio
async def test_row_number_window_query_runs_on_postgres(pg_migrated_engine) -> None:
    """list_for_identities executes on Postgres: filter-inside-window + per-identity top_k bound.

    Everything runs inside one rolled-back transaction so the session-scoped
    scratch DB stays clean for the other pg tests.
    """
    async_url = pg_migrated_engine.url.render_as_string(hide_password=False)
    engine = create_async_engine(async_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            tenant = Tenant(site_url="http://uxp2-pg.example.test")
            session.add(tenant)
            await session.flush()
            # Satisfy the forced-RLS tenant policies for the rest of the transaction.
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": str(tenant.id)},
            )

            unlabeled_first = await _seed_identity(session, tenant.id, media_id=1)
            unlabeled_cluster = await _seed_cluster(session, tenant.id, None)
            labeled_second = await _seed_cluster(session, tenant.id, "PG Labeled Second")
            _add_suggestion(session, tenant.id, unlabeled_first, unlabeled_cluster, 0.95, BASE_TIME)
            _add_suggestion(session, tenant.id, unlabeled_first, labeled_second, 0.85, BASE_TIME)

            multi = await _seed_identity(session, tenant.id, media_id=2)
            multi_clusters = [await _seed_cluster(session, tenant.id, f"PG Multi {rank}") for rank in range(3)]
            for rank, (cluster_id, similarity) in enumerate(zip(multi_clusters, (0.90, 0.80, 0.70), strict=True)):
                _add_suggestion(session, tenant.id, multi, cluster_id, similarity, BASE_TIME - timedelta(minutes=rank))

            resolved_first = await _seed_identity(session, tenant.id, media_id=3)
            accepted_cluster = await _seed_cluster(session, tenant.id, "PG Already Accepted")
            pending_second = await _seed_cluster(session, tenant.id, "PG Pending Second")
            _add_suggestion(
                session,
                tenant.id,
                resolved_first,
                accepted_cluster,
                0.97,
                BASE_TIME,
                resolution=SuggestionStatus.ACCEPTED.value,
            )
            _add_suggestion(session, tenant.id, resolved_first, pending_second, 0.87, BASE_TIME)
            await session.flush()

            repo = SqlAlchemySuggestionRepository(session)
            identity_ids = [unlabeled_first, multi, resolved_first]

            top_one = await repo.list_for_identities(str(tenant.id), identity_ids, top_k=1)
            by_identity = {row.identity_id: row for row in top_one}
            assert len(top_one) == 3, "top_k=1 must yield exactly one row per identity"
            assert set(by_identity) == set(identity_ids)
            assert by_identity[unlabeled_first].cluster_id == labeled_second
            assert by_identity[unlabeled_first].cluster_label == "PG Labeled Second"
            assert by_identity[multi].cluster_id == multi_clusters[0]
            assert by_identity[resolved_first].cluster_id == pending_second

            top_two = await repo.list_for_identities(str(tenant.id), [multi], top_k=2)
            assert [row.cluster_id for row in top_two] == multi_clusters[:2]
            similarities = [row.representative_similarity for row in top_two]
            assert similarities == sorted(similarities, reverse=True)

            await session.rollback()
    finally:
        await engine.dispose()
