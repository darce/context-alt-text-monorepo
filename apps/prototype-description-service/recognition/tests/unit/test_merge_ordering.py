from unittest.mock import AsyncMock, Mock, call

import pytest

from recognition.application.orchestration.cluster_merge import merge_cluster
from recognition.domain.cluster import IdentityCluster


@pytest.mark.asyncio
async def test_merge_cluster_deletes_source_last():
    """
    Regression test: Ensure source cluster is deleted ONLY after all recomputations are done.
    Early deletion caused 404 errors during transaction commit in some environments.
    """
    # Mocks
    mock_assignment_writer = Mock()
    mock_assignment_writer.cluster_repository = AsyncMock()
    mock_assignment_writer.member_repository = AsyncMock()
    mock_assignment_writer.recompute_representatives = AsyncMock()
    mock_assignment_writer.recompute_centroid = AsyncMock()
    mock_assignment_writer.refresh_centroids_view = AsyncMock()

    mock_cluster_repo = mock_assignment_writer.cluster_repository
    mock_member_repo = mock_assignment_writer.member_repository

    # Setup data
    source_cluster = IdentityCluster(
        id="source-1", tenant_id="tenant-1", label="Source", identity_count=1, is_labeled=True
    )
    target_cluster = IdentityCluster(
        id="target-1", tenant_id="tenant-1", label="Target", identity_count=1, is_labeled=True
    )

    mock_cluster_repo.get_by_id.side_effect = lambda eid: source_cluster if eid == "source-1" else target_cluster
    mock_cluster_repo.get_all_representatives = AsyncMock(return_value=[])
    mock_cluster_repo.update.return_value = target_cluster
    mock_member_repo.move_members.return_value = 5  # moved 5 members

    # Execute
    await merge_cluster(
        source_cluster_id="source-1",
        tenant_id="tenant-1",
        target_cluster_id="target-1",
        target_label="Merged",
        assignment_writer=mock_assignment_writer,
        suggestion_service=Mock(),
        gate=Mock(),
    )

    # Verification: Check Call Order
    # We want to ensure delete("source-1") was called...
    mock_cluster_repo.delete.assert_called_with("source-1")

    # ...AND that it was called AFTER recompute_representatives
    # Get all calls to the relevant mocks
    manager = Mock()
    manager.attach_mock(mock_cluster_repo.delete, "delete")
    manager.attach_mock(mock_assignment_writer.recompute_representatives, "recompute")

    # We reconstruct the sequence. Since we attached them to a manager, we can check reference order.
    # Note: unittest.mock doesn't track relative order of DIFFERENT mock objects easily unless they are children of a parent.
    # Strategy: Check timestamps or manual call list?
    # Simple approach: Check that recompute was called, and it was NOT called after delete (which ends the function basically).
    # But since it's async, we just want to ensure the await happened.

    # Better approach using call_args_list if attached to same parent mock?
    # Let's use specific assertion:

    # Check that recompute happened
    mock_assignment_writer.recompute_representatives.assert_called_once()

    # To strictly verify order without a parent mock for everything (which is hard here),
    # we can use side_effect assertions.

    # Define a tracking list
    call_order = []

    mock_assignment_writer.recompute_representatives.side_effect = lambda *a: call_order.append("recompute")
    mock_cluster_repo.delete.side_effect = lambda *a: call_order.append("delete")

    # Re-run logic
    # Reset mocks
    mock_assignment_writer.recompute_representatives = AsyncMock(side_effect=lambda *a: call_order.append("recompute"))
    mock_cluster_repo.delete = AsyncMock(side_effect=lambda *a: call_order.append("delete"))

    await merge_cluster(
        source_cluster_id="source-1",
        tenant_id="tenant-1",
        target_cluster_id="target-1",
        target_label="Merged",
        assignment_writer=mock_assignment_writer,
        suggestion_service=Mock(),
        gate=Mock(),
    )

    assert call_order == ["recompute", "delete"], (
        f"Deletion call order incorrect! Expected ['recompute', 'delete'], got {call_order}"
    )
