"""Tests for ClusterService merge logic (Task 75.6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from recognition.application.orchestration import ClusterService
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import CrossSpaceMergeError, IdentityCluster
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.domain.representative import ClusterRepresentative


@pytest.fixture
def mock_cluster_repo() -> AsyncMock:
    repo = AsyncMock(spec=ClusterRepository)
    repo.get_all_representatives.return_value = []
    return repo


@pytest.fixture
def mock_member_repo() -> AsyncMock:
    repo = AsyncMock(spec=MemberRepository)
    repo.move_members.return_value = 5  # moved 5 members
    repo.get_by_cluster.return_value = ["fake_member"] * 15  # new count
    return repo


@pytest.fixture
def mock_writer(mock_cluster_repo: AsyncMock, mock_member_repo: AsyncMock) -> Mock:
    writer = Mock(spec=AssignmentWriter)
    writer.cluster_repository = mock_cluster_repo
    writer.member_repository = mock_member_repo
    # Mock the recompute methods
    writer.recompute_centroid = AsyncMock()
    writer.recompute_representatives = AsyncMock()
    writer.refresh_centroids_view = AsyncMock()
    return writer


@pytest.fixture
def service(mock_writer: Mock) -> ClusterService:
    # We only need assignment_writer for merge testing
    return ClusterService(
        gate=Mock(),
        representative_discovery=Mock(),
        centroid_discovery=Mock(),
        graph_discovery=Mock(),
        assignment_writer=mock_writer,
        suggestion_service=Mock(),
        logger=None,
    )


@pytest.mark.asyncio
async def test_merge_cluster_moves_members_and_recomputes(
    service: ClusterService,
    mock_cluster_repo: AsyncMock,
    mock_member_repo: AsyncMock,
    mock_writer: Mock,
) -> None:
    """Test that merging clusters moves members, deletes source, and triggers recomputation."""
    tenant_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())

    source_cluster = IdentityCluster(
        id=source_id,
        tenant_id=tenant_id,
        is_labeled=False,
        identity_count=5,
        label="Source",
    )
    target_cluster = IdentityCluster(
        id=target_id,
        tenant_id=tenant_id,
        is_labeled=True,
        identity_count=10,
        label="Target",
    )

    mock_cluster_repo.get_by_id.side_effect = [source_cluster, target_cluster]
    mock_cluster_repo.update.return_value = target_cluster  # Return target as updated

    # Action
    merged = await service.merge_cluster(
        source_cluster_id=source_id,
        tenant_id=tenant_id,
        target_cluster_id=target_id,
    )

    # Assertions
    assert merged is target_cluster

    # 1. Members moved
    mock_member_repo.move_members.assert_awaited_once_with(source_id, target_id)

    # 2. Source deleted
    mock_cluster_repo.delete.assert_awaited_once_with(source_id)

    # 3. Target updated (count matches get_by_cluster mock)
    assert target_cluster.identity_count == 15
    mock_cluster_repo.update.assert_awaited_once()

    # 4. HOOKS TRIGGERED
    mock_writer.recompute_centroid.assert_awaited_once_with(target_id)
    mock_writer.recompute_representatives.assert_awaited_once_with(target_id)
    mock_writer.refresh_centroids_view.assert_awaited_once()


@pytest.mark.asyncio
async def test_merge_cluster_tolerates_refresh_centroids_failure(
    service: ClusterService,
    mock_cluster_repo: AsyncMock,
    mock_member_repo: AsyncMock,
    mock_writer: Mock,
    caplog,
) -> None:
    """INFRA-5: a transient post-merge MV-refresh failure must not roll back the
    already-applied merge (bulk-accept would otherwise discard the whole batch)."""
    import logging

    tenant_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())

    source_cluster = IdentityCluster(
        id=source_id, tenant_id=tenant_id, is_labeled=False, identity_count=5, label="Source"
    )
    target_cluster = IdentityCluster(
        id=target_id, tenant_id=tenant_id, is_labeled=True, identity_count=10, label="Target"
    )
    mock_cluster_repo.get_by_id.side_effect = [source_cluster, target_cluster]
    mock_cluster_repo.update.return_value = target_cluster
    mock_writer.refresh_centroids_view = AsyncMock(side_effect=RuntimeError("transient MV refresh failure"))

    with caplog.at_level(logging.WARNING, logger="recognition.application.orchestration.cluster_merge"):
        merged = await service.merge_cluster(
            source_cluster_id=source_id,
            tenant_id=tenant_id,
            target_cluster_id=target_id,
        )

    # Merge still completes: members moved, source deleted, target updated.
    assert merged is target_cluster
    mock_member_repo.move_members.assert_awaited_once_with(source_id, target_id)
    mock_cluster_repo.delete.assert_awaited_once_with(source_id)
    mock_writer.refresh_centroids_view.assert_awaited_once()
    assert any("centroid" in record.message.lower() for record in caplog.records), (
        "a failed post-merge MV refresh must be logged"
    )


@pytest.mark.asyncio
async def test_merge_cluster_defers_recompute_and_deletion(
    service: ClusterService,
    mock_cluster_repo: AsyncMock,
    mock_member_repo: AsyncMock,
    mock_writer: Mock,
) -> None:
    """Should support a fast merge path that defers heavyweight work."""
    tenant_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())

    source_cluster = IdentityCluster(
        id=source_id,
        tenant_id=tenant_id,
        is_labeled=False,
        identity_count=5,
        label="Source",
    )
    target_cluster = IdentityCluster(
        id=target_id,
        tenant_id=tenant_id,
        is_labeled=True,
        identity_count=10,
        label="Target",
    )

    mock_cluster_repo.get_by_id.side_effect = [source_cluster, target_cluster]
    mock_cluster_repo.update.return_value = target_cluster

    merged = await service.merge_cluster(
        source_cluster_id=source_id,
        tenant_id=tenant_id,
        target_cluster_id=target_id,
        defer_recompute=True,
    )

    assert merged is target_cluster
    mock_member_repo.move_members.assert_awaited_once_with(source_id, target_id)
    mock_cluster_repo.delete.assert_not_called()
    assert source_cluster.identity_count == 0
    assert mock_cluster_repo.update.await_count == 2
    mock_member_repo.get_by_cluster.assert_not_awaited()
    mock_writer.recompute_centroid.assert_not_awaited()
    mock_writer.recompute_representatives.assert_not_awaited()
    mock_writer.refresh_centroids_view.assert_not_awaited()


@pytest.mark.asyncio
async def test_merge_cluster_missing_validation(
    service: ClusterService,
    mock_cluster_repo: AsyncMock,
) -> None:
    """Should return None if clusters don't exist or tenant mismatch."""
    mock_cluster_repo.get_by_id.return_value = None
    result = await service.merge_cluster("s", "t", "d")
    assert result is None


def _space_rep(cluster_id: str, model: str) -> ClusterRepresentative:
    return ClusterRepresentative(
        id=f"r-{model}-{cluster_id}",
        cluster_id=cluster_id,
        identity_id=f"i-{model}",
        embedding=np.array([1.0, 0.0], dtype=np.float32),
        created_at=datetime.now(tz=UTC),
        embedding_model=model,
    )


@pytest.mark.asyncio
async def test_merge_cluster_refuses_cross_space_and_moves_no_members(
    service: ClusterService,
    mock_cluster_repo: AsyncMock,
    mock_member_repo: AsyncMock,
) -> None:
    """FIR23-01: space-a into space-b must not reassign members."""
    tenant_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    source_cluster = IdentityCluster(
        id=source_id,
        tenant_id=tenant_id,
        is_labeled=False,
        identity_count=5,
        label="Source",
    )
    target_cluster = IdentityCluster(
        id=target_id,
        tenant_id=tenant_id,
        is_labeled=True,
        identity_count=10,
        label="Target",
    )
    mock_cluster_repo.get_by_id.side_effect = [source_cluster, target_cluster]

    async def reps_for(cluster_id: str) -> list[ClusterRepresentative]:
        model = "space-a" if cluster_id == source_id else "space-b"
        return [_space_rep(cluster_id, model)]

    mock_cluster_repo.get_all_representatives.side_effect = reps_for

    with pytest.raises(CrossSpaceMergeError) as exc_info:
        await service.merge_cluster(
            source_cluster_id=source_id,
            tenant_id=tenant_id,
            target_cluster_id=target_id,
        )

    err = exc_info.value
    assert err.source_cluster_id == source_id
    assert err.target_cluster_id == target_id
    assert err.source_model == "space-a"
    assert err.target_model == "space-b"
    assert "space-a" in str(err)
    assert "space-b" in str(err)
    mock_member_repo.move_members.assert_not_awaited()
    mock_cluster_repo.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_merge_cluster_allows_same_space_stamped_clusters(
    service: ClusterService,
    mock_cluster_repo: AsyncMock,
    mock_member_repo: AsyncMock,
    mock_writer: Mock,
) -> None:
    """Matching embedding spaces still merge members and recompute."""
    tenant_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    source_cluster = IdentityCluster(
        id=source_id,
        tenant_id=tenant_id,
        is_labeled=False,
        identity_count=5,
        label="Source",
    )
    target_cluster = IdentityCluster(
        id=target_id,
        tenant_id=tenant_id,
        is_labeled=True,
        identity_count=10,
        label="Target",
    )
    mock_cluster_repo.get_by_id.side_effect = [source_cluster, target_cluster]
    mock_cluster_repo.update.return_value = target_cluster
    mock_cluster_repo.get_all_representatives.side_effect = lambda cluster_id: [
        _space_rep(cluster_id, "space-a")
    ]

    merged = await service.merge_cluster(
        source_cluster_id=source_id,
        tenant_id=tenant_id,
        target_cluster_id=target_id,
    )

    assert merged is target_cluster
    mock_member_repo.move_members.assert_awaited_once_with(source_id, target_id)
    mock_cluster_repo.delete.assert_awaited_once_with(source_id)
    mock_writer.recompute_centroid.assert_awaited_once_with(target_id)
    mock_writer.recompute_representatives.assert_awaited_once_with(target_id)
