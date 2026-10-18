from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from recognition.application.orchestration import cluster_merge as cluster_merge_module
from recognition.application.orchestration.cluster_merge import merge_cluster
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import IdentityMember


class _ClusterRepository:
    def __init__(self, clusters: list[IdentityCluster]) -> None:
        self.clusters = {str(cluster.id): cluster for cluster in clusters}
        self.target_id = next(cluster_id for cluster_id, cluster in self.clusters.items() if cluster.label == "Ada")

    async def get_by_id(self, cluster_id: str) -> IdentityCluster | None:
        cluster = self.clusters.get(str(cluster_id))
        if cluster is None:
            return None
        return replace(cluster)

    async def get_all_representatives(self, _cluster_id: str) -> list[object]:
        return []

    async def update(self, cluster: IdentityCluster) -> IdentityCluster:
        self.clusters[str(cluster.id)] = replace(cluster)
        return replace(cluster)


class _MemberRepository:
    def __init__(self, members: list[IdentityMember]) -> None:
        self.members = members

    async def get_by_cluster(self, cluster_id: str) -> list[IdentityMember]:
        return [member for member in self.members if member.cluster_id == cluster_id]

    async def move_members(self, source_id: str, target_id: str) -> int:
        moved = 0
        for index, member in enumerate(self.members):
            if member.cluster_id == source_id:
                self.members[index] = replace(member, cluster_id=target_id)
                moved += 1
        return moved


class _LockSession:
    def __init__(self, cluster_repo: _ClusterRepository, target_id: str) -> None:
        self.cluster_repo = cluster_repo
        self.target_id = target_id
        self.statements: list[object] = []

    async def execute(self, statement: object) -> object:
        self.statements.append(statement)
        rendered = str(statement).lower()
        if "identity_clusters" in rendered and "for update" in rendered:
            current = self.cluster_repo.clusters[self.target_id]
            current.label = "Ada (first merge)"
            current.identity_count = 8
        return SimpleNamespace(
            scalar_one_or_none=lambda: None,
            scalars=lambda: SimpleNamespace(all=lambda: []),
        )

    async def flush(self) -> None:
        return None

    def add(self, _record: object) -> None:
        return None


@pytest.mark.asyncio
async def test_merge_uses_survivor_state_read_after_waiting_for_row_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = str(uuid4())
    source_id = str(uuid4())
    target_id = str(uuid4())
    identity_id = str(uuid4())
    cluster_repo = _ClusterRepository(
        [
            IdentityCluster(id=source_id, tenant_id=tenant_id, is_labeled=False, identity_count=1, label="Source"),
            IdentityCluster(id=target_id, tenant_id=tenant_id, is_labeled=True, identity_count=3, label="Ada"),
        ]
    )
    member_repo = _MemberRepository(
        [
            IdentityMember(
                id=str(uuid4()),
                cluster_id=source_id,
                identity_id=identity_id,
                similarity=0.9,
            )
        ]
    )
    writer = SimpleNamespace(
        cluster_repository=cluster_repo,
        member_repository=member_repo,
        _settings=SimpleNamespace(merge_undo_window_days=7),
    )
    session = _LockSession(cluster_repo, target_id)
    broadcaster = SimpleNamespace(broadcast=AsyncMock())
    monkeypatch.setattr(cluster_merge_module, "get_event_broadcaster", lambda: broadcaster)

    updated = await merge_cluster(
        source_cluster_id=source_id,
        tenant_id=tenant_id,
        target_cluster_id=target_id,
        target_label=None,
        assignment_writer=writer,
        suggestion_service=SimpleNamespace(),
        gate=SimpleNamespace(),
        session=session,
        moved_by_merge_id=str(uuid4()),
        defer_recompute=True,
    )

    assert updated is not None
    assert updated.label == "Ada (first merge)"
    assert updated.identity_count == 9
    lock_statement = next(
        statement
        for statement in session.statements
        if "identity_clusters" in str(statement).lower() and "for update" in str(statement).lower()
    )
    assert lock_statement.get_execution_options().get("populate_existing") is True
