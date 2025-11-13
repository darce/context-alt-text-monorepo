from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock

from recognition.application.face_clustering_service import FaceClusteringService
from recognition.tests.fakes import DummySession, FakeResult, make_media_face, make_simple_face


class ClusterServiceHarness(FaceClusteringService):
    """Overrides data access to exercise coordinator logic deterministically."""

    def __init__(self, face_map):
        super().__init__(session=DummySession(), tenant_id=uuid4())
        self.face_map = face_map
        self.created_clusters = []

    async def _get_unclustered_faces(self):
        return list(self.face_map.keys())

    async def _find_similar_faces(self, seed_face):
        return self.face_map.get(seed_face, [])

    async def _create_cluster(self, faces_with_scores):
        cluster = SimpleNamespace(id=uuid4(), face_count=len(faces_with_scores))
        self.created_clusters.append(faces_with_scores)
        return cluster


def test_cluster_faces_returns_empty_when_no_candidates():
    service = ClusterServiceHarness(face_map={})

    clusters = asyncio.run(service.cluster_faces())

    assert clusters == []


def test_cluster_faces_creates_cluster_for_candidates():
    face_a = make_simple_face()
    face_b = make_simple_face()
    face_map = {
        face_a: [(face_a, 0.98), (face_b, 0.91)],
        face_b: [(face_b, 0.91)],
    }
    service = ClusterServiceHarness(face_map)

    clusters = asyncio.run(service.cluster_faces())

    assert len(clusters) == 1
    assert len(service.created_clusters) == 1
    assert service.created_clusters[0][0][0] is face_a


def test_cluster_faces_skips_solitary_faces():
    face_lonely = make_simple_face()
    face_map = {face_lonely: [(face_lonely, 1.0)]}
    service = ClusterServiceHarness(face_map)

    clusters = asyncio.run(service.cluster_faces())

    assert clusters == []
    assert service.created_clusters == []


def test_create_cluster_persists_members_and_commits():
    tenant_id = uuid4()
    session = DummySession()
    service = FaceClusteringService(session=session, tenant_id=tenant_id)

    face1 = make_media_face(tenant_id, media_id=1, confidence=0.95)
    face2 = make_media_face(tenant_id, media_id=2, confidence=0.75)
    cluster = asyncio.run(service._create_cluster([(face1, 0.94), (face2, 0.72)]))

    assert cluster.face_count == 2
    assert any(obj for obj in session.added if obj is cluster)
    member_count = len([obj for obj in session.added if getattr(obj, "face_id", None) in {face1.id, face2.id}])
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
    )
    cluster = SimpleNamespace(
        id=cluster_id,
        label="cluster-1234",
        face_count=4,
        representative_face=representative,
    )

    session = SimpleNamespace()
    session.get = AsyncMock(return_value=cluster)

    sample_member = SimpleNamespace(similarity=0.93)
    sample_face = SimpleNamespace(
        id=uuid4(),
        media_id=42,
        bbox_x=3,
        bbox_y=4,
        bbox_width=5,
        bbox_height=6,
        confidence=0.88,
    )
    member_rows = [(uuid4(),), (uuid4(),)]
    session.execute = AsyncMock(side_effect=[FakeResult([(sample_member, sample_face)]), FakeResult(member_rows)])

    service = FaceClusteringService(session=session, tenant_id=tenant_id)
    summary = asyncio.run(service.get_cluster_summary(cluster_id))

    assert summary["id"] == str(cluster_id)
    assert summary["representative_face"]["media_id"] == 99
    assert summary["sample_faces"][0]["media_id"] == 42
    assert summary["member_ids"]


def test_get_cluster_summary_missing_cluster():
    session = SimpleNamespace()
    session.get = AsyncMock(return_value=None)
    service = FaceClusteringService(session=session, tenant_id=uuid4())

    with pytest.raises(ValueError):
        asyncio.run(service.get_cluster_summary(uuid4()))


@pytest.mark.xfail(reason="Pending enforcement of min_cluster_size from ClusteringSettings")
def test_cluster_faces_respects_min_cluster_size():
    face_a = make_simple_face()
    face_b = make_simple_face()
    face_map = {face_a: [(face_a, 0.99), (face_b, 0.95)]}
    service = ClusterServiceHarness(face_map)
    service.min_cluster_size = 3  # Future configuration hook

    clusters = asyncio.run(service.cluster_faces())

    assert clusters == []


@pytest.mark.xfail(reason="Pending enforcement of max_cluster_size from ClusteringSettings")
def test_cluster_faces_caps_members_at_configured_limit():
    faces = [make_simple_face() for _ in range(4)]
    face_map = {faces[0]: [(face, 0.9) for face in faces]}
    service = ClusterServiceHarness(face_map)
    service.max_cluster_size = 2  # Future configuration hook

    clusters = asyncio.run(service.cluster_faces())

    assert clusters
    assert len(service.created_clusters[0]) == 2
