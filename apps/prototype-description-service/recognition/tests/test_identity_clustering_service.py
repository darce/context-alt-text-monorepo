"""Tests for the recognition clustering service."""

from __future__ import annotations

import asyncio
import logging
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import numpy as np
import pytest
from sqlalchemy import select, text

if os.getenv("RUN_DB_TESTS") != "1":
    pytest.skip("Skipping DB-backed clustering tests; set RUN_DB_TESTS=1 to enable", allow_module_level=True)

from db.models import (
    ClusterCentroid,
    IdentityCluster,
    IdentityClusterRepresentative,
    IdentityMember,
    MediaIdentity,
    Tenant,
)
from db.session import async_session_factory
from db.settings import get_database_settings
from db.tenant_context import (
    clear_tenant_context,
    disable_rls_bypass,
    enable_rls_bypass,
    set_tenant_context,
)
from recognition.application.centroid_utils import _normalize_vector, compute_similarity
from recognition.application.cluster_repository import ClusterSearchEntry
from recognition.application.clustering_settings import ClusteringSettings
from recognition.application.identity_clustering_service import (
    IdentityClusteringService,
)
from recognition.application.representative_selection import decide_representative_acceptance
from recognition.tests.fakes import DummySession, FakeResult, make_media_identity


def make_stub_identity(vector):
    return SimpleNamespace(
        id=uuid4(),
        embedding=vector,
        confidence=0.9,
        media_id=1,
        created_by_user_id=None,
    )


class ClusterServiceHarness(IdentityClusteringService):
    """Overrides data access to exercise coordinator logic deterministically."""

    def __init__(self, unclustered, existing_entries=None, representatives=None):
        super().__init__(session=DummySession(), tenant_id=uuid4())
        self._unclustered = unclustered
        self._existing_entries = existing_entries or []
        self._representatives = representatives or {}
        self.created_clusters: list[IdentityCluster] = []
        self.assigned_identities: list[UUID] = []
        self.refreshed = False

        # Override repository methods
        async def _override_unclustered():
            return list(self._unclustered)

        async def _override_centroids():
            return list(self._existing_entries)

        async def _override_reps():
            return self._representatives

        async def _override_count_reps(cluster_id, media_id):
            return 0

        self.repository.get_unclustered_identities = _override_unclustered
        self.repository.get_clusters_with_centroids = _override_centroids
        self.repository.get_clusters_with_representatives = _override_reps
        self.repository.count_representatives_for_media = _override_count_reps

        # Override factory to track created clusters
        original_create = self.factory.create_cluster_with_centroid

        async def _override_create(identities, add_representative_callback=None):
            cluster, entry = await original_create(identities, add_representative_callback)
            self.created_clusters.append(cluster)
            self._existing_entries.append(entry)
            return cluster, entry

        self.factory.create_cluster_with_centroid = _override_create

        # Override assigner to track assignments
        original_assign = self.assigner.assign_to_cluster

        async def _override_assign(identity, identity_vector, entry, similarity):
            await original_assign(identity, identity_vector, entry, similarity)
            self.assigned_identities.append(identity.id)

        async def _override_assign_by_id(identity, identity_vector, cluster_id, similarity):
            # Find or create entry for this cluster
            entry = next((e for e in self._existing_entries if e.cluster.id == cluster_id), None)
            if not entry:
                entry = ClusterSearchEntry(
                    cluster=IdentityCluster(
                        id=cluster_id,
                        tenant_id=self.tenant_id,
                        label="rep-only",
                        identity_count=0,
                        clustering_algorithm="test",
                    ),
                    centroid=identity_vector,
                    member_count=0,
                )
                self._existing_entries.append(entry)
            await _override_assign(identity, identity_vector, entry, similarity)

        self.assigner.assign_to_cluster = _override_assign
        self.assigner.assign_to_cluster_by_id = _override_assign_by_id

    async def _refresh_centroid_view(self):
        self.refreshed = True


async def refresh_centroid_view(session):
    """Refresh the materialized view. Always uses RLS bypass for the refresh operation."""
    # REFRESH MATERIALIZED VIEW needs to read from source tables without RLS
    await enable_rls_bypass(session)
    await session.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
    await disable_rls_bypass(session)


def test_cluster_identities_returns_empty_when_no_candidates():
    service = ClusterServiceHarness(unclustered=[])

    clusters = asyncio.run(service.cluster_identities_incremental())

    assert clusters == []


def test_cluster_identities_creates_cluster_for_unclustered_identity():
    identity = make_stub_identity([1.0, 0.0, 0.0])
    service = ClusterServiceHarness(unclustered=[identity])

    clusters = asyncio.run(service.cluster_identities_incremental())

    assert len(clusters) == 1
    assert len(service.created_clusters) == 1
    assert service.assigned_identities == []


def test_cluster_identities_assigns_to_existing_cluster():
    tenant_id = uuid4()
    cluster = IdentityCluster(
        tenant_id=tenant_id,
        label="cluster-existing",
        representative_identity_id=None,
        identity_count=2,
        similarity_threshold=0.6,
        clustering_algorithm="test",
    )
    cluster.id = uuid4()
    entry = ClusterSearchEntry(
        cluster=cluster,
        centroid=np.array([1.0, 0.0, 0.0], dtype=np.float32),
        member_count=2,
    )
    identity = make_stub_identity([0.99, 0.01, 0.0])
    service = ClusterServiceHarness(unclustered=[identity], existing_entries=[entry])

    clusters = asyncio.run(service.cluster_identities_incremental())

    assert clusters == []
    assert service.assigned_identities == [identity.id]


def test_cluster_identities_creates_new_cluster_when_similarity_low():
    tenant_id = uuid4()
    cluster = IdentityCluster(
        tenant_id=tenant_id,
        label="cluster-low-sim",
        representative_identity_id=None,
        identity_count=2,
        similarity_threshold=0.6,
        clustering_algorithm="test",
    )
    cluster.id = uuid4()
    entry = ClusterSearchEntry(
        cluster=cluster,
        centroid=np.array([0.0, 1.0, 0.0], dtype=np.float32),
        member_count=2,
    )
    identity = make_stub_identity([1.0, 0.0, 0.0])
    service = ClusterServiceHarness(unclustered=[identity], existing_entries=[entry])

    clusters = asyncio.run(service.cluster_identities_incremental())

    assert len(clusters) == 1
    assert service.assigned_identities == []


def test_cluster_identities_assigns_via_representatives():
    tenant_id = uuid4()
    cluster = IdentityCluster(
        tenant_id=tenant_id,
        label="cluster-with-rep",
        representative_identity_id=None,
        identity_count=1,
        similarity_threshold=0.6,
        clustering_algorithm="test",
    )
    cluster.id = uuid4()
    rep_vector = np.array([0.99, 0.01, 0.0], dtype=np.float32)
    identity = make_stub_identity([0.99, 0.0, 0.01])
    service = ClusterServiceHarness(
        unclustered=[identity],
        existing_entries=[ClusterSearchEntry(cluster=cluster, centroid=rep_vector, member_count=1)],
        representatives={cluster.id: [rep_vector]},
    )

    clusters = asyncio.run(service.cluster_identities_incremental())

    assert clusters == []
    assert service.assigned_identities == [identity.id]
    assert service.created_clusters == []


def test_create_cluster_adds_representatives(monkeypatch):
    tenant_id = uuid4()
    session = DummySession()
    service = IdentityClusteringService(session=session, tenant_id=tenant_id)

    identity1 = make_media_identity(tenant_id, media_id=1, confidence=0.9, embedding=[1.0, 0.0, 0.0, 0.0])
    identity2 = make_media_identity(tenant_id, media_id=2, confidence=0.8, embedding=[0.0, 1.0, 0.0, 0.0])

    mock_add_rep = AsyncMock()
    service._add_representative_embedding = mock_add_rep

    cluster, _ = asyncio.run(
        service.factory.create_cluster_with_centroid(
            [identity1, identity2],
            add_representative_callback=mock_add_rep,
        )
    )

    assert mock_add_rep.await_count == 2
    called_ids = {call.args[1].id for call in mock_add_rep.await_args_list}
    assert called_ids == {identity1.id, identity2.id}


def test_cluster_identities_respects_threshold_for_borderline_similarity():
    tenant_id = uuid4()
    cluster = IdentityCluster(
        tenant_id=tenant_id,
        label="cluster-threshold",
        representative_identity_id=None,
        identity_count=2,
        similarity_threshold=0.6,
        clustering_algorithm="test",
    )
    cluster.id = uuid4()
    entry = ClusterSearchEntry(
        cluster=cluster,
        centroid=np.array([1.0, 0.0], dtype=np.float32),
        member_count=2,
    )
    identity = make_stub_identity([0.55, 0.835])
    service = ClusterServiceHarness(unclustered=[identity], existing_entries=[entry])

    clusters = asyncio.run(service.cluster_identities_incremental())

    assert len(clusters) == 1  # new cluster created instead of assignment
    assert service.assigned_identities == []


@pytest.mark.asyncio
async def test_assign_to_cluster_logs_borderline_and_validates(caplog):
    tenant_id = uuid4()
    cluster = IdentityCluster(
        tenant_id=tenant_id,
        label="cluster-borderline",
        representative_identity_id=None,
        identity_count=1,
        similarity_threshold=0.6,
        clustering_algorithm="test",
    )
    cluster.id = uuid4()
    entry = ClusterSearchEntry(
        cluster=cluster,
        centroid=np.array([1.0, 0.0, 0.0], dtype=np.float32),
        member_count=1,
    )
    identity = make_stub_identity([0.6, 0.8, 0.0])
    identity_vector = np.array(identity.embedding, dtype=np.float32)
    similarity = compute_similarity(identity_vector, entry.centroid)

    service = IdentityClusteringService(
        session=DummySession(),
        tenant_id=tenant_id,
        similarity_threshold=0.6,
        strict_validation=True,
    )
    # Track original method for assertion
    original_validate = service.assigner._validate_assignment
    service.assigner._validate_assignment = AsyncMock(wraps=original_validate)

    with caplog.at_level(logging.WARNING):
        await service.assigner.assign_to_cluster(identity, identity_vector, entry, similarity)

    service.assigner._validate_assignment.assert_awaited_once()
    assert any("Borderline assignment" in record.message for record in caplog.records)


def test_create_cluster_persists_members_and_flushes():
    tenant_id = uuid4()
    session = DummySession()
    service = IdentityClusteringService(session=session, tenant_id=tenant_id)

    identity1 = make_media_identity(tenant_id, media_id=1, confidence=0.95)
    identity2 = make_media_identity(tenant_id, media_id=2, confidence=0.75)
    cluster, entry = asyncio.run(
        service.factory.create_cluster_with_centroid(
            [identity1, identity2],
            add_representative_callback=service._add_representative_embedding,
        )
    )

    assert cluster.identity_count == 2
    assert entry.member_count == 2
    assert any(obj for obj in session.added if isinstance(obj, IdentityMember))
    assert session.flush_calls >= 1
    assert session.commit_calls == 0


def test_get_cluster_summary_returns_serializable_payload():
    tenant_id = uuid4()
    cluster_id = uuid4()
    representative = SimpleNamespace(
        media_id=99,
        bbox_x=1,
        bbox_y=2,
        bbox_width=10,
        bbox_height=12,
        thumbnail_url="https://example.com/thumb.jpg",
    )
    cluster = SimpleNamespace(
        id=cluster_id,
        label="cluster-1234",
        identity_count=4,
        representative_identity=representative,
    )

    session = SimpleNamespace()
    session.get = AsyncMock(return_value=cluster)

    sample_member = SimpleNamespace(similarity=0.93)
    sample_identity = SimpleNamespace(
        id=uuid4(),
        media_id=42,
        bbox_x=3,
        bbox_y=4,
        bbox_width=5,
        bbox_height=6,
        confidence=0.88,
        thumbnail_url="https://example.com/sample.jpg",
    )
    member_rows = [(uuid4(),), (uuid4(),)]
    session.execute = AsyncMock(side_effect=[FakeResult([(sample_member, sample_identity)]), FakeResult(member_rows)])

    service = IdentityClusteringService(session=session, tenant_id=tenant_id)
    summary = asyncio.run(service.get_cluster_summary(cluster_id))

    assert summary["id"] == str(cluster_id)
    assert summary["representative_identity"]["media_id"] == 99
    assert summary["sample_identities"][0]["media_id"] == 42
    assert summary["member_ids"]


def test_get_cluster_summary_missing_cluster():
    session = SimpleNamespace()
    session.get = AsyncMock(return_value=None)
    service = IdentityClusteringService(session=session, tenant_id=uuid4())

    with pytest.raises(ValueError):
        asyncio.run(service.get_cluster_summary(uuid4()))


@pytest.mark.asyncio
async def test_merge_similar_clusters_merges_expected(require_database):
    tenant_id = uuid4()
    async with async_session_factory() as session:
        session.add(Tenant(id=tenant_id, site_url=f"https://{tenant_id}.example.com"))
        await session.commit()

        await set_tenant_context(session, tenant_id)
        identity_a = make_media_identity(tenant_id, media_id=11, embedding=[1.0] * 1024)
        identity_b = make_media_identity(
            tenant_id,
            media_id=22,
            embedding=[0.99] * 512 + [1.01] * 512,
        )
        identity_c = make_media_identity(tenant_id, media_id=33, embedding=[0.0] * 1024)
        session.add_all([identity_a, identity_b, identity_c])
        await session.flush()

        cluster_a = IdentityCluster(
            tenant_id=tenant_id,
            label="cluster-a",
            representative_identity_id=identity_a.id,
            identity_count=1,
        )
        cluster_b = IdentityCluster(
            tenant_id=tenant_id,
            label="cluster-b",
            representative_identity_id=identity_b.id,
            identity_count=1,
        )
        cluster_c = IdentityCluster(
            tenant_id=tenant_id,
            label="cluster-c",
            representative_identity_id=identity_c.id,
            identity_count=1,
        )
        session.add_all([cluster_a, cluster_b, cluster_c])
        await session.flush()

        session.add_all(
            [
                IdentityMember(
                    tenant_id=tenant_id,
                    cluster_id=cluster_a.id,
                    identity_id=identity_a.id,
                    similarity=0.9,
                ),
                IdentityMember(
                    tenant_id=tenant_id,
                    cluster_id=cluster_b.id,
                    identity_id=identity_b.id,
                    similarity=0.9,
                ),
                IdentityMember(
                    tenant_id=tenant_id,
                    cluster_id=cluster_c.id,
                    identity_id=identity_c.id,
                    similarity=0.4,
                ),
            ]
        )
        await session.commit()
        await refresh_centroid_view(session)
        await session.commit()

        await set_tenant_context(session, tenant_id)
        service = IdentityClusteringService(session=session, tenant_id=tenant_id)
        merges = await service.merge_similar_clusters(threshold=0.95)
        assert merges == 1

        await set_tenant_context(session, tenant_id)
        remaining_clusters = await session.execute(
            select(IdentityCluster).where(IdentityCluster.tenant_id == tenant_id)
        )
        labels = {cluster.label for cluster in remaining_clusters.scalars().all()}
        assert "cluster-c" in labels
        assert len(labels) == 2
        await clear_tenant_context(session)


@pytest.mark.asyncio
async def test_materialized_view_stores_normalized_centroid(require_database):
    tenant_id = uuid4()
    async with async_session_factory() as session:
        session.add(Tenant(id=tenant_id, site_url=f"https://{tenant_id}.example.com"))
        await session.commit()
        await set_tenant_context(session, tenant_id)

        vec_a = [1.0] + [0.0] * 1023
        vec_b = [0.0] + [1.0] + [0.0] * 1022
        identity_a = make_media_identity(tenant_id, media_id=101, embedding=vec_a)
        identity_b = make_media_identity(tenant_id, media_id=202, embedding=vec_b)
        session.add_all([identity_a, identity_b])
        await session.flush()

        cluster = IdentityCluster(
            tenant_id=tenant_id,
            label="cluster-norm",
            representative_identity_id=identity_a.id,
            identity_count=2,
            similarity_threshold=0.6,
        )
        session.add(cluster)
        await session.flush()
        session.add_all(
            [
                IdentityMember(
                    tenant_id=tenant_id,
                    cluster_id=cluster.id,
                    identity_id=identity_a.id,
                    similarity=1.0,
                ),
                IdentityMember(
                    tenant_id=tenant_id,
                    cluster_id=cluster.id,
                    identity_id=identity_b.id,
                    similarity=1.0,
                ),
            ]
        )
        await session.commit()

        await refresh_centroid_view(session)
        await set_tenant_context(session, tenant_id)
        result = await session.execute(
            select(ClusterCentroid.centroid)
            .where(ClusterCentroid.cluster_id == cluster.id)
            .where(ClusterCentroid.tenant_id == tenant_id)
        )
        centroid = result.scalar_one()
        norm = float(np.linalg.norm(np.array(centroid, dtype=np.float32)))

        assert norm == pytest.approx(1.0, abs=1e-3)
        await clear_tenant_context(session)


@pytest.mark.asyncio
async def test_representative_matching_blocks_centroid_drift(require_database):
    settings = get_database_settings()
    tenant_id = uuid4()
    async with async_session_factory() as session:
        session.add(Tenant(id=tenant_id, site_url=f"https://{tenant_id}.example.com"))
        await session.commit()

        try:
            await set_tenant_context(session, tenant_id)
            base_embeddings = []
            for idx in range(3):
                vec = np.zeros(settings.pgvector_dimension, dtype=np.float32)
                vec[idx] = 1.0
                base_embeddings.append(vec.tolist())

            identities = [
                make_media_identity(tenant_id, media_id=media_id, embedding=embedding)
                for media_id, embedding in enumerate(base_embeddings, start=1)
            ]
            session.add_all(identities)
            await session.commit()
            await set_tenant_context(session, tenant_id)

            service = IdentityClusteringService(
                session=session,
                tenant_id=tenant_id,
                settings=ClusteringSettings(similarity_threshold=0.6, auto_merge_enabled=False),
            )
            cluster, _ = await service.factory.create_cluster_with_centroid(
                identities,
                add_representative_callback=service._add_representative_embedding,
            )
            await session.commit()
            base_cluster_id = cluster.id

            await set_tenant_context(session, tenant_id)
            await refresh_centroid_view(session)
            await set_tenant_context(session, tenant_id)

            candidate_vec = np.zeros(settings.pgvector_dimension, dtype=np.float32)
            candidate_vec[:3] = 1.0
            candidate_identity = make_media_identity(
                tenant_id,
                media_id=99,
                embedding=candidate_vec.tolist(),
            )
            session.add(candidate_identity)
            await session.commit()
            await set_tenant_context(session, tenant_id)

            await refresh_centroid_view(session)
            await set_tenant_context(session, tenant_id)
            centroid_row = await session.execute(
                select(ClusterCentroid.centroid)
                .where(ClusterCentroid.cluster_id == base_cluster_id)
                .where(ClusterCentroid.tenant_id == tenant_id)
            )
            centroid_vector = np.array(centroid_row.scalar_one(), dtype=np.float32)
            candidate_vector = np.array(candidate_identity.embedding, dtype=np.float32)
            centroid_similarity = compute_similarity(candidate_vector, centroid_vector)
            assert centroid_similarity > service.threshold

            new_clusters = await service.cluster_identities_incremental()
            await set_tenant_context(session, tenant_id)
            member_result = await session.execute(
                select(IdentityMember.cluster_id).where(IdentityMember.identity_id == candidate_identity.id)
            )
            assigned_cluster_id = member_result.scalar_one()

            assert assigned_cluster_id != base_cluster_id
            assert len(new_clusters) == 1
        finally:
            await clear_tenant_context(session)


@pytest.mark.asyncio
async def test_representatives_table_populated_after_clustering(require_database):
    settings = get_database_settings()
    tenant_id = uuid4()
    async with async_session_factory() as session:
        session.add(Tenant(id=tenant_id, site_url=f"https://{tenant_id}.example.com"))
        await session.commit()

        try:
            await set_tenant_context(session, tenant_id)
            embeddings = []
            for idx in range(3):
                vec = np.zeros(settings.pgvector_dimension, dtype=np.float32)
                vec[idx] = 1.0
                embeddings.append(vec.tolist())

            identities = [
                make_media_identity(tenant_id, media_id=idx + 10, embedding=embedding)
                for idx, embedding in enumerate(embeddings)
            ]
            session.add_all(identities)
            await session.commit()
            await set_tenant_context(session, tenant_id)

            service = IdentityClusteringService(session=session, tenant_id=tenant_id, similarity_threshold=0.6)
            cluster, _ = await service.factory.create_cluster_with_centroid(
                identities,
                add_representative_callback=service._add_representative_embedding,
            )
            await session.commit()
            cluster_id = cluster.id
            await set_tenant_context(session, tenant_id)

            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                select(IdentityClusterRepresentative).where(IdentityClusterRepresentative.cluster_id == cluster_id)
            )
            reps = result.scalars().all()

            assert len(reps) == len(identities)
            assert {rep.identity_id for rep in reps} == {identity.id for identity in identities}
            assert all(rep.tenant_id == tenant_id for rep in reps)
            expected_confidence = {identity.id: identity.confidence for identity in identities}
            for rep in reps:
                norm = float(np.linalg.norm(np.array(rep.embedding, dtype=np.float32)))
                assert norm == pytest.approx(1.0, abs=1e-6)
                assert rep.quality_score == expected_confidence[rep.identity_id]
        finally:
            await clear_tenant_context(session)
