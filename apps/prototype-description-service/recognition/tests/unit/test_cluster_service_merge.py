"""Tests for ClusterService merge logic (Task 75.6)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from recognition.application.orchestration import ClusterService
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import ClusterRepository, MemberRepository


@pytest.fixture
def mock_cluster_repo() -> AsyncMock:
    repo = AsyncMock(spec=ClusterRepository)
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
    writer._clusters = mock_cluster_repo
    writer._members = mock_member_repo
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
