"""Tests for cluster-label domain rules and write boundaries."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from recognition.application.orchestration.cluster_merge import merge_cluster
from recognition.application.orchestration.curation.cluster_mutations import update_cluster
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster, ReservedClusterLabelError, is_reserved_label_shape


@pytest.mark.parametrize("label", ["cluster-abcdef01", "cluster_7", " cluster-x ", "CLUSTER-9"])
def test_reserved_label_shape_is_detected(label: str) -> None:
    assert is_reserved_label_shape(label) is True


@pytest.mark.parametrize("label", ["Cluster Nine", "Alice", "Person 2", None, ""])
def test_non_reserved_label_shape_is_allowed(label: str | None) -> None:
    assert is_reserved_label_shape(label) is False


@pytest.mark.asyncio
async def test_merge_rejects_reserved_target_label_without_mutation() -> None:
    source = IdentityCluster(tenant_id="tenant", is_labeled=True, identity_count=1, label="Source", id="source")
    target = IdentityCluster(
        tenant_id="tenant", is_labeled=True, identity_count=2, label="Target", id="target", user_confirmed=False
    )
    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.side_effect = [source, target]
    member_repo = AsyncMock()
    writer = Mock()
    writer.cluster_repository = cluster_repo
    writer.member_repository = member_repo

    with pytest.raises(ReservedClusterLabelError):
        await merge_cluster(
            source_cluster_id="source",
            target_cluster_id="target",
            tenant_id="tenant",
            target_label=" cluster-forbidden ",
            assignment_writer=writer,
            suggestion_service=Mock(),
            gate=Mock(),
        )

    assert target.label == "Target"
    assert target.user_confirmed is False
    member_repo.move_members.assert_not_awaited()
    cluster_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_cluster_rejects_reserved_label_without_mutation() -> None:
    cluster = IdentityCluster(
        tenant_id="tenant", is_labeled=True, identity_count=2, label="Alice", id="target", user_confirmed=True
    )
    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.return_value = cluster
    writer = Mock()
    writer.cluster_repository = cluster_repo

    with pytest.raises(ReservedClusterLabelError):
        await update_cluster(cluster_id="target", tenant_id="tenant", label="CLUSTER_9", assignment_writer=writer)

    assert cluster.label == "Alice"
    assert cluster.user_confirmed is True
    cluster_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_cluster_accepts_person_auto_label_shape() -> None:
    cluster = IdentityCluster(tenant_id="tenant", is_labeled=False, identity_count=2, id="target")
    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.return_value = cluster
    cluster_repo.update.return_value = cluster
    writer = Mock()
    writer.cluster_repository = cluster_repo

    updated = await update_cluster(cluster_id="target", tenant_id="tenant", label="Person 2", assignment_writer=writer)

    assert updated is cluster
    assert cluster.label == "Person 2"
    assert cluster.user_confirmed is True


@pytest.mark.asyncio
async def test_assignment_writer_rejects_reserved_label_without_mutation() -> None:
    cluster = IdentityCluster(tenant_id="tenant", is_labeled=False, identity_count=0, id="target")
    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.return_value = cluster
    writer = AssignmentWriter(ClusteringSettings(), cluster_repo, AsyncMock())

    with pytest.raises(ReservedClusterLabelError):
        await writer.update_cluster_metadata("target", label="cluster-7")

    assert cluster.label is None
    cluster_repo.update.assert_not_awaited()
