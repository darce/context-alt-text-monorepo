"""Regression tests for deferred cluster merge findings."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.orchestration.cluster_merge import merge_cluster
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import CrossSpaceMergeError, IdentityCluster
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.domain.representative import ClusterRepresentative


class _EmbeddingModelSession:
    def __init__(self, model_rows: list[list[str | None]]) -> None:
        self.model_rows = list(model_rows)
        self.statements: list[object] = []

    async def execute(self, statement: object) -> SimpleNamespace:
        self.statements.append(statement)
        models = self.model_rows.pop(0)
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: models))


def _representative(cluster_id: str) -> ClusterRepresentative:
    return ClusterRepresentative(
        id=f"rep:{cluster_id}",
        cluster_id=cluster_id,
        identity_id=f"identity:{cluster_id}",
        embedding=np.array([1.0, 0.0], dtype=np.float32),
        created_at=datetime.now(tz=UTC),
        embedding_model="space-a",
    )


@pytest.mark.asyncio
async def test_merge_rejects_minority_model_in_full_member_and_representative_sets() -> None:
    tenant_id = str(uuid4())
    source_id = str(uuid4())
    target_id = str(uuid4())
    source = IdentityCluster(
        id=source_id,
        tenant_id=tenant_id,
        is_labeled=False,
        identity_count=5,
        label="Source",
    )
    target = IdentityCluster(
        id=target_id,
        tenant_id=tenant_id,
        is_labeled=True,
        identity_count=2,
        label="Target",
    )
    cluster_repo = AsyncMock(spec=ClusterRepository)
    cluster_repo.get_by_id.side_effect = [source, target]
    cluster_repo.get_all_representatives.side_effect = lambda cluster_id: [_representative(cluster_id)]
    cluster_repo.update.return_value = target
    member_repo = AsyncMock(spec=MemberRepository)
    member_repo.move_members.return_value = 1
    writer = Mock(spec=AssignmentWriter)
    writer.cluster_repository = cluster_repo
    writer.member_repository = member_repo
    session = _EmbeddingModelSession(
        [
            ["space-a", "space-a", "space-a", "space-a", "space-b"],
            ["space-a", "space-a"],
        ]
    )

    with pytest.raises(CrossSpaceMergeError):
        await merge_cluster(
            source_cluster_id=source_id,
            tenant_id=tenant_id,
            target_cluster_id=target_id,
            target_label="Target",
            assignment_writer=writer,
            suggestion_service=Mock(),
            gate=Mock(),
            session=session,
            defer_recompute=True,
        )

    member_repo.move_members.assert_not_awaited()
    rendered_statements = " ".join(str(statement).lower() for statement in session.statements)
    assert "identity_members" in rendered_statements
    assert "identity_cluster_representatives" in rendered_statements
