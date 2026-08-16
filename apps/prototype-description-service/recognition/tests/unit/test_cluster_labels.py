"""Tests for cluster-label domain rules and write boundaries."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from recognition.application.orchestration.cluster_merge import merge_cluster
from recognition.application.orchestration.curation.cluster_mutations import (
    create_cluster_for_identity,
    update_cluster,
)
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster, ReservedClusterLabelError, is_reserved_label_shape


@pytest.mark.parametrize("label", ["cluster-abcdef01", "cluster_7", " cluster-x ", "CLUSTER-9"])
def test_reserved_label_shape_is_detected(label: str) -> None:
    assert is_reserved_label_shape(label) is True


@pytest.mark.parametrize(
    "label",
    ["Cluster Nine", "Alice", "Person 2", None, "", "The cluster-9 team", "my cluster_x"],
)
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


async def _merge_into(
    *,
    target: IdentityCluster,
    source: IdentityCluster,
    target_label: str | None,
) -> IdentityCluster:
    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.side_effect = [source, target]
    cluster_repo.update.side_effect = lambda cluster: cluster
    member_repo = AsyncMock()
    member_repo.move_members.return_value = 1
    writer = Mock()
    writer.cluster_repository = cluster_repo
    writer.member_repository = member_repo
    writer.recompute_representatives = AsyncMock()
    writer.recompute_centroid = AsyncMock()
    writer.refresh_centroids_view = AsyncMock()

    merged = await merge_cluster(
        source_cluster_id=source.id or "source",
        target_cluster_id=target.id or "target",
        tenant_id="tenant",
        target_label=target_label,
        assignment_writer=writer,
        suggestion_service=Mock(),
        gate=Mock(),
    )
    assert merged is target
    return target


@pytest.mark.asyncio
async def test_merge_none_target_label_preserves_unconfirmed_reserved_survivor() -> None:
    """E21-17-R2-PY-N1: placeholder merge must not stamp user_confirmed=True."""
    source = IdentityCluster(
        tenant_id="tenant", is_labeled=True, identity_count=1, label="cluster-b", id="source", user_confirmed=False
    )
    target = IdentityCluster(
        tenant_id="tenant", is_labeled=True, identity_count=2, label="cluster-a", id="target", user_confirmed=False
    )

    merged = await _merge_into(target=target, source=source, target_label=None)

    assert merged.label == "cluster-a"
    assert merged.is_labeled is True
    assert merged.user_confirmed is False


@pytest.mark.asyncio
async def test_merge_none_target_label_preserves_confirmed_reserved_survivor() -> None:
    """E21-17-R2-PY-N1: reserved survivor that was already confirmed stays confirmed."""
    source = IdentityCluster(
        tenant_id="tenant", is_labeled=True, identity_count=1, label="cluster-b", id="source", user_confirmed=False
    )
    target = IdentityCluster(
        tenant_id="tenant", is_labeled=True, identity_count=2, label="cluster-a", id="target", user_confirmed=True
    )

    merged = await _merge_into(target=target, source=source, target_label=None)

    assert merged.label == "cluster-a"
    assert merged.user_confirmed is True


@pytest.mark.asyncio
async def test_merge_meaningful_target_label_stamps_user_confirmed() -> None:
    """E21-17-R2-PY-N1: explicit meaningful label keeps prior operator-confirm behavior."""
    source = IdentityCluster(
        tenant_id="tenant", is_labeled=True, identity_count=1, label="cluster-b", id="source", user_confirmed=False
    )
    target = IdentityCluster(
        tenant_id="tenant", is_labeled=True, identity_count=2, label="cluster-a", id="target", user_confirmed=False
    )

    merged = await _merge_into(target=target, source=source, target_label="Alice")

    assert merged.label == "Alice"
    assert merged.is_labeled is True
    assert merged.user_confirmed is True


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


@pytest.mark.asyncio
async def test_create_cluster_for_identity_rejects_reserved_label_before_persist() -> None:
    """E21-17-R1-PY47-2: reserved label must raise before any repository write."""
    writer = Mock()
    writer.persist_new_cluster = AsyncMock()
    writer.update_cluster_metadata = AsyncMock()
    writer.cluster_repository = AsyncMock()
    writer.member_repository = AsyncMock()
    session = AsyncMock()

    with pytest.raises(ReservedClusterLabelError):
        await create_cluster_for_identity(
            identity_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            label="cluster-x",
            tenant_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            desired_cluster_id=None,
            session=session,
            assignment_writer=writer,
        )

    writer.persist_new_cluster.assert_not_awaited()
    session.get.assert_not_awaited()
