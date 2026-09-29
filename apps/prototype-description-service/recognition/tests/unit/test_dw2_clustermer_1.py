from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from db.models.identity import ClusterMergeKind, ClusterMergeReceipt
from recognition.application.orchestration.cluster_merge import merge_cluster
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import ClusterRepository, MemberRepository


class _EmptyScalarResult:
    def scalars(self) -> _EmptyScalarResult:
        return self

    def all(self) -> list[ClusterMergeReceipt]:
        return []


@pytest.mark.asyncio
async def test_normal_merge_persists_receipt_for_revert(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    merge_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    source = IdentityCluster(
        id=str(source_id),
        tenant_id=str(tenant_id),
        label="Source",
        is_labeled=True,
        identity_count=1,
    )
    target = IdentityCluster(
        id=str(target_id),
        tenant_id=str(tenant_id),
        label="Target",
        is_labeled=True,
        identity_count=1,
    )

    cluster_repo = AsyncMock(spec=ClusterRepository)
    cluster_repo.get_by_id.side_effect = [source, target]
    cluster_repo.get_all_representatives.return_value = []
    cluster_repo.update.return_value = target
    member_repo = AsyncMock(spec=MemberRepository)
    member = SimpleNamespace(identity_id=identity_id)
    member_repo.get_by_cluster.side_effect = [[member], [member], [member]]
    member_repo.move_members.return_value = 1
    writer = Mock(spec=AssignmentWriter)
    writer.cluster_repository = cluster_repo
    writer.member_repository = member_repo
    writer._settings = ClusteringSettings(merge_undo_window_days=3)
    writer.recompute_representatives = AsyncMock()
    writer.recompute_centroid = AsyncMock()
    writer.refresh_centroids_view = AsyncMock()
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_EmptyScalarResult()),
        flush=AsyncMock(),
        add=Mock(),
    )
    suggestion_service = Mock()
    suggestion_service.resolve_for_identity_exclusive = AsyncMock()
    broadcaster = SimpleNamespace(broadcast=AsyncMock())
    monkeypatch.setattr(
        "recognition.application.orchestration.cluster_merge.get_event_broadcaster",
        lambda: broadcaster,
    )

    await merge_cluster(
        source_cluster_id=str(source_id),
        tenant_id=str(tenant_id),
        target_cluster_id=str(target_id),
        target_label=None,
        assignment_writer=writer,
        suggestion_service=suggestion_service,
        gate=Mock(),
        session=session,
        moved_by_merge_id=str(merge_id),
    )

    session.add.assert_called_once()
    receipt = session.add.call_args.args[0]
    assert isinstance(receipt, ClusterMergeReceipt)
    assert receipt.receipt_id == merge_id
    assert receipt.tenant_id == tenant_id
    assert receipt.survivor_cluster_id == target_id
    assert receipt.source_cluster_id == source_id
    assert receipt.source_label == "Source"
    assert receipt.moved_identity_ids == [identity_id]
    assert receipt.kind == ClusterMergeKind.OPERATOR.value
    assert receipt.sequence_no == 1
    assert receipt.expires_at - receipt.created_at == timedelta(days=3)
