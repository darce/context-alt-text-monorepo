"""FIR23-01: assign_outlier_to_cluster refuses mixed embedding spaces."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import numpy as np
import pytest

from recognition.application.orchestration.curation.cluster_mutations import assign_outlier_to_cluster
from recognition.application.orchestration.curation.similarity import compute_curation_similarity
from recognition.domain.cluster import CrossSpaceMergeError, IdentityCluster
from recognition.domain.representative import ClusterRepresentative


def _rep(cluster_id: str, model: str | None) -> ClusterRepresentative:
    return ClusterRepresentative(
        id=str(uuid4()),
        cluster_id=cluster_id,
        identity_id=str(uuid4()),
        embedding=np.array([1.0, 0.0], dtype=np.float32),
        created_at=datetime.now(tz=UTC),
        embedding_model=model,
    )


def _identity_model(*, tenant_id: str, identity_id: str, embedding_model: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(identity_id),
        tenant_id=UUID(tenant_id),
        media_id=7,
        embedding=np.array([1.0, 0.0], dtype=np.float32),
        embedding_model=embedding_model,
        confidence=0.9,
        bbox_width=10,
        bbox_height=10,
        bbox_x=0,
        bbox_y=0,
        pose_pitch=None,
        pose_yaw=None,
        pose_roll=None,
        image_phash=None,
        sharpness=None,
        embedding_norm=None,
        occlusion_severity=None,
        moved_by_merge_id=None,
    )


@pytest.mark.asyncio
async def test_assign_outlier_refuses_cross_space_and_does_not_add_member() -> None:
    tenant_id = str(uuid4())
    target_id = str(uuid4())
    identity_id = str(uuid4())
    cluster = IdentityCluster(
        id=target_id,
        tenant_id=tenant_id,
        is_labeled=True,
        identity_count=3,
        label="Target",
    )
    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.return_value = cluster
    cluster_repo.get_all_representatives.return_value = [_rep(target_id, "space-a")]
    member_repo = AsyncMock()
    writer = Mock()
    writer.cluster_repository = cluster_repo
    writer.member_repository = member_repo
    session = AsyncMock()
    session.get = AsyncMock(
        return_value=_identity_model(tenant_id=tenant_id, identity_id=identity_id, embedding_model="space-b")
    )

    with pytest.raises(CrossSpaceMergeError) as exc_info:
        await assign_outlier_to_cluster(
            identity_id=identity_id,
            target_cluster_id=target_id,
            tenant_id=tenant_id,
            similarity=0.0,
            session=session,
            assignment_writer=writer,
        )

    err = exc_info.value
    assert err.source_model == "space-b"
    assert err.target_model == "space-a"
    member_repo.add_member_if_not_exists.assert_not_awaited()
    member_repo.remove_by_identity_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_assign_outlier_same_space_adds_member(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = str(uuid4())
    target_id = str(uuid4())
    identity_id = str(uuid4())
    cluster = IdentityCluster(
        id=target_id,
        tenant_id=tenant_id,
        is_labeled=True,
        identity_count=3,
        label="Target",
    )
    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.return_value = cluster
    cluster_repo.get_all_representatives.return_value = [_rep(target_id, "space-a")]
    cluster_repo.update = AsyncMock(side_effect=lambda value: value)
    cluster_repo.get_curriculum_t = AsyncMock(return_value=0.0)
    cluster_repo.set_curriculum_t = AsyncMock()
    member_repo = AsyncMock()
    member_repo.get_by_identity_id.return_value = []
    member_repo.add_member_if_not_exists.return_value = SimpleNamespace(id="m1")
    writer = Mock()
    writer.cluster_repository = cluster_repo
    writer.member_repository = member_repo
    writer.recompute_representatives = AsyncMock()
    writer.recompute_centroid = AsyncMock()
    session = AsyncMock()
    session.get = AsyncMock(
        return_value=_identity_model(tenant_id=tenant_id, identity_id=identity_id, embedding_model="space-a")
    )
    broadcaster = SimpleNamespace(broadcast=AsyncMock())
    monkeypatch.setattr(
        "recognition.application.orchestration.curation.cluster_mutations.get_event_broadcaster",
        lambda: broadcaster,
    )

    result = await assign_outlier_to_cluster(
        identity_id=identity_id,
        target_cluster_id=target_id,
        tenant_id=tenant_id,
        similarity=0.8,
        session=session,
        assignment_writer=writer,
    )

    assert result is cluster
    member_repo.add_member_if_not_exists.assert_awaited_once()
    writer.recompute_representatives.assert_awaited_once_with(target_id)


@pytest.mark.asyncio
async def test_compute_curation_similarity_skips_cross_space_reps() -> None:
    session = AsyncMock()
    foreign = SimpleNamespace(embedding=np.array([1.0, 0.0], dtype=np.float32))
    session.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: [(foreign, "space-b")]))

    similarity = await compute_curation_similarity(
        identity_embedding=np.array([1.0, 0.0], dtype=np.float32),
        target_cluster_id=str(uuid4()),
        session=session,
        identity_embedding_model="space-a",
    )

    assert similarity == 0.0


@pytest.mark.asyncio
async def test_compute_curation_similarity_same_space_cosines() -> None:
    session = AsyncMock()
    same = SimpleNamespace(embedding=np.array([1.0, 0.0], dtype=np.float32))
    session.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: [(same, "space-a")]))

    similarity = await compute_curation_similarity(
        identity_embedding=np.array([1.0, 0.0], dtype=np.float32),
        target_cluster_id=str(uuid4()),
        session=session,
        identity_embedding_model="space-a",
    )

    assert similarity > 0.9
