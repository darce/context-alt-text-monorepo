"""Regression tests for DEFWAVE-2 cluster merge space validation."""

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


def _representative(cluster_id: str, model: str) -> ClusterRepresentative:
    return ClusterRepresentative(
        id=f"r-{model}-{cluster_id}",
        cluster_id=cluster_id,
        identity_id=f"i-{model}",
        embedding=np.array([1.0, 0.0], dtype=np.float32),
        created_at=datetime.now(tz=UTC),
        embedding_model=model,
    )


@pytest.mark.asyncio
async def test_merge_rejects_cluster_with_representative_outside_majority_space() -> None:
    tenant_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    source_cluster = IdentityCluster(
        id=source_id,
        tenant_id=tenant_id,
        is_labeled=False,
        identity_count=3,
        label="Source",
    )
    target_cluster = IdentityCluster(
        id=target_id,
        tenant_id=tenant_id,
        is_labeled=True,
        identity_count=1,
        label="Target",
    )

    cluster_repo = AsyncMock(spec=ClusterRepository)
    cluster_repo.get_by_id.side_effect = [source_cluster, target_cluster]

    async def representatives(cluster_id: str) -> list[ClusterRepresentative]:
        if cluster_id == source_id:
            return [
                _representative(source_id, "space-a"),
                _representative(source_id, "space-a"),
                _representative(source_id, "space-b"),
            ]
        return [_representative(target_id, "space-a")]

    cluster_repo.get_all_representatives.side_effect = representatives
    member_repo = AsyncMock(spec=MemberRepository)
    writer = Mock(spec=AssignmentWriter)
    writer.cluster_repository = cluster_repo
    writer.member_repository = member_repo

    service = ClusterService(
        gate=Mock(),
        representative_discovery=Mock(),
        centroid_discovery=Mock(),
        graph_discovery=Mock(),
        assignment_writer=writer,
        suggestion_service=Mock(),
    )

    with pytest.raises(CrossSpaceMergeError):
        await service.merge_cluster(
            source_cluster_id=source_id,
            tenant_id=tenant_id,
            target_cluster_id=target_id,
        )

    member_repo.move_members.assert_not_awaited()
    cluster_repo.delete.assert_not_awaited()
