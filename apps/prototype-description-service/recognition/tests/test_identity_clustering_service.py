"""Tests for the recognition clustering service."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock

from sqlalchemy import select

from recognition.application.identity_clustering_service import IdentityClusteringService
from recognition.tests.fakes import DummySession, FakeResult, make_media_identity, make_simple_identity
from db.session import async_session_factory
from db.models import Tenant, MediaIdentity, IdentityCluster, IdentityMember
from db.tenant_context import set_tenant_context, clear_tenant_context


class ClusterServiceHarness(IdentityClusteringService):
    """Overrides data access to exercise coordinator logic deterministically."""

    def __init__(self, identity_map):
        super().__init__(session=DummySession(), tenant_id=uuid4())
        self.identity_map = identity_map
        self.created_clusters = []

    async def _get_unclustered_identities(self):
        return list(self.identity_map.keys())

    async def _find_similar_identities(self, seed_identity):
        return self.identity_map.get(seed_identity, [])

    async def _create_cluster(self, identities_with_scores):
        cluster = SimpleNamespace(id=uuid4(), identity_count=len(identities_with_scores))
        self.created_clusters.append(identities_with_scores)
        return cluster


def test_cluster_identities_returns_empty_when_no_candidates():
    service = ClusterServiceHarness(identity_map={})

    clusters = asyncio.run(service.cluster_identities())

    assert clusters == []


def test_cluster_identities_creates_cluster_for_candidates():
    identity_a = make_simple_identity()
    identity_b = make_simple_identity()
    identity_map = {
        identity_a: [(identity_a, 0.98), (identity_b, 0.91)],
        identity_b: [(identity_b, 0.91)],
    }
    service = ClusterServiceHarness(identity_map)

    clusters = asyncio.run(service.cluster_identities())

    assert len(clusters) == 1
    assert len(service.created_clusters) == 1
    assert service.created_clusters[0][0][0] is identity_a


def test_cluster_identities_creates_cluster_for_solitary_identities():
    lonely_identity = make_simple_identity()
    identity_map = {lonely_identity: [(lonely_identity, 1.0)]}
    service = ClusterServiceHarness(identity_map)

    clusters = asyncio.run(service.cluster_identities())

    assert len(clusters) == 1
    assert len(service.created_clusters) == 1


def test_create_cluster_persists_members_and_commits():
    tenant_id = uuid4()
    session = DummySession()
    service = IdentityClusteringService(session=session, tenant_id=tenant_id)

    identity1 = make_media_identity(tenant_id, media_id=1, confidence=0.95)
    identity2 = make_media_identity(tenant_id, media_id=2, confidence=0.75)
    cluster = asyncio.run(service._create_cluster([(identity1, 0.94), (identity2, 0.72)]))

    assert cluster.identity_count == 2
    assert any(obj for obj in session.added if obj is cluster)
    member_count = len(
        [
            obj
            for obj in session.added
            if getattr(obj, "identity_id", None) in {identity1.id, identity2.id}
        ]
    )
    assert member_count == 2
    assert session.commit_calls == 1


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


@pytest.mark.xfail(reason="Pending enforcement of min_cluster_size from ClusteringSettings")
def test_cluster_identities_respects_min_cluster_size():
    identity_a = make_simple_identity()
    identity_b = make_simple_identity()
    identity_map = {identity_a: [(identity_a, 0.99), (identity_b, 0.95)]}
    service = ClusterServiceHarness(identity_map)
    service.min_cluster_size = 3  # Future configuration hook

    clusters = asyncio.run(service.cluster_identities())

    assert clusters == []


@pytest.mark.xfail(reason="Pending enforcement of max_cluster_size from ClusteringSettings")
def test_cluster_identities_caps_members_at_configured_limit():
    identities = [make_simple_identity() for _ in range(4)]
    identity_map = {identities[0]: [(identity, 0.9) for identity in identities]}
    service = ClusterServiceHarness(identity_map)
    service.max_cluster_size = 2  # Future configuration hook

    clusters = asyncio.run(service.cluster_identities())

    assert clusters
    assert len(service.created_clusters[0]) == 2


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

        await set_tenant_context(session, tenant_id)
        service = IdentityClusteringService(session=session, tenant_id=tenant_id)
        merges = await service.merge_similar_clusters(threshold=0.95)
        assert merges == 1

        remaining_clusters = await session.execute(select(IdentityCluster))
        labels = {cluster.label for cluster in remaining_clusters.scalars().all()}
        assert "cluster-c" in labels
        assert len(labels) == 2
        await clear_tenant_context(session)
