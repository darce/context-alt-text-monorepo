from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from db.models import IdentityCluster as IdentityClusterModel
from db.models.identity import ClusterMergeReceipt
from recognition.application.orchestration import cluster_merge as cluster_merge_module
from recognition.application.orchestration.cluster_merge import merge_cluster
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.domain.suggestion import MergeSuggestion, SuggestionStatus
from recognition.infrastructure.repositories import SqlAlchemyMergeSuggestionRepository
from recognition.interface_adapters.http.routers.suggestions import (
    AcceptMergeSuggestionRequest,
    accept_merge_suggestion,
)


class _EmptyResult:
    def scalar_one_or_none(self) -> None:
        return None

    def scalars(self) -> _EmptyResult:
        return self

    def all(self) -> list[ClusterMergeReceipt]:
        return []


def _cluster(cluster_id: uuid.UUID, tenant_id: uuid.UUID, label: str) -> IdentityCluster:
    return IdentityCluster(
        id=str(cluster_id),
        tenant_id=str(tenant_id),
        label=label,
        is_labeled=True,
        identity_count=1,
    )


@pytest.mark.asyncio
async def test_receipted_merge_locks_both_clusters_and_skips_receipt_when_nothing_moved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, source_id, target_id, merge_id, identity_id = (uuid.uuid4() for _ in range(5))
    source = _cluster(source_id, tenant_id, "Source")
    target = _cluster(target_id, tenant_id, "Target")
    source_member = SimpleNamespace(identity_id=identity_id)
    statements: list[object] = []

    async def execute(statement: object) -> _EmptyResult:
        statements.append(statement)
        return _EmptyResult()

    cluster_repo = AsyncMock(spec=ClusterRepository)

    async def get_cluster(cluster_id: str) -> IdentityCluster | None:
        if cluster_id == str(source_id):
            return source
        if cluster_id == str(target_id):
            return target
        return None

    cluster_repo.get_by_id.side_effect = get_cluster
    cluster_repo.get_all_representatives.return_value = []
    cluster_repo.update.return_value = target
    member_repo = AsyncMock(spec=MemberRepository)
    member_repo.get_by_cluster.side_effect = lambda cluster_id: [source_member] if cluster_id == str(source_id) else []
    member_repo.move_members.return_value = 0
    writer = Mock(spec=AssignmentWriter)
    writer.cluster_repository = cluster_repo
    writer.member_repository = member_repo
    writer.recompute_representatives = AsyncMock()
    writer.recompute_centroid = AsyncMock()
    writer.refresh_centroids_view = AsyncMock()
    session = SimpleNamespace(execute=AsyncMock(side_effect=execute), flush=AsyncMock(), add=Mock())
    broadcaster = SimpleNamespace(broadcast=AsyncMock())
    monkeypatch.setattr(cluster_merge_module, "get_event_broadcaster", lambda: broadcaster)

    result = await merge_cluster(
        source_cluster_id=str(source_id),
        tenant_id=str(tenant_id),
        target_cluster_id=str(target_id),
        target_label=None,
        assignment_writer=writer,
        suggestion_service=SimpleNamespace(resolve_for_identity_exclusive=AsyncMock()),
        gate=Mock(),
        session=session,
        moved_by_merge_id=str(merge_id),
    )

    lock_statement = next(
        statement
        for statement in statements
        if "identity_clusters" in str(statement).lower() and "FOR UPDATE" in str(statement).upper()
    )
    compiled = lock_statement.compile()
    lock_sql = str(compiled).lower()
    assert "order by identity_clusters.id" in lock_sql
    assert "identity_clusters.id in" in lock_sql
    locked_ids = next(value for value in compiled.params.values() if isinstance(value, list))
    assert locked_ids == sorted([source_id, target_id])
    assert result is None
    session.add.assert_not_called()
    assert not any("update media_identities" in str(statement).lower() for statement in statements)


@pytest.mark.asyncio
async def test_receipted_merge_replay_returns_survivor_when_source_was_already_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, source_id, target_id, merge_id = (uuid.uuid4() for _ in range(4))
    target = _cluster(target_id, tenant_id, "Target")
    receipt = SimpleNamespace(source_cluster_id=source_id, survivor_cluster_id=target_id)
    calls: list[str] = []

    async def lock_clusters(*_args: object, **_kwargs: object) -> None:
        calls.append("lock")

    async def load_receipt(*_args: object, **_kwargs: object) -> SimpleNamespace:
        calls.append("receipt")
        return receipt

    lock_mock = AsyncMock(side_effect=lock_clusters)
    receipt_mock = AsyncMock(side_effect=load_receipt)
    monkeypatch.setattr(cluster_merge_module, "_lock_merge_clusters", lock_mock, raising=False)
    monkeypatch.setattr(cluster_merge_module, "_load_receipt", receipt_mock)
    cluster_repo = AsyncMock(spec=ClusterRepository)

    async def get_cluster(cluster_id: str) -> IdentityCluster | None:
        return target if cluster_id == str(target_id) else None

    cluster_repo.get_by_id.side_effect = get_cluster
    member_repo = AsyncMock(spec=MemberRepository)
    writer = Mock(spec=AssignmentWriter)
    writer.cluster_repository = cluster_repo
    writer.member_repository = member_repo
    session = SimpleNamespace(execute=AsyncMock(return_value=_EmptyResult()), add=Mock())

    result = await merge_cluster(
        source_cluster_id=str(source_id),
        tenant_id=str(tenant_id),
        target_cluster_id=str(target_id),
        target_label=None,
        assignment_writer=writer,
        suggestion_service=Mock(),
        gate=Mock(),
        session=session,
        moved_by_merge_id=str(merge_id),
    )

    lock_mock.assert_awaited_once()
    receipt_mock.assert_awaited_once()
    assert calls == ["lock", "receipt"]
    assert result is target
    member_repo.move_members.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_accept_merge_persists_accepted_status_before_pending_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    cluster_a = _cluster(uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), uuid.UUID(tenant_id), "A")
    cluster_b = _cluster(uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"), uuid.UUID(tenant_id), "B")
    suggestion = MergeSuggestion(
        id=str(uuid.uuid4()),
        cluster_a_id=str(cluster_a.id),
        cluster_b_id=str(cluster_b.id),
        similarity=0.91,
        status=SuggestionStatus.PENDING,
    )
    order: list[tuple[str, object]] = []
    get_by_id = AsyncMock(return_value=suggestion)

    async def delete_by_cluster(
        _repo: SqlAlchemyMergeSuggestionRepository,
        _tenant_id: str,
        cluster_id: str,
    ) -> int:
        order.append(("delete", cluster_id))
        return 1

    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "__init__", lambda self, _session: None)
    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "get_by_id", get_by_id)
    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "delete_by_cluster", delete_by_cluster)
    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.side_effect = [cluster_a, cluster_b]
    cluster_repo.list_identity_ids_moved_by_merge = AsyncMock(return_value=[])
    cluster_service = AsyncMock()
    cluster_service.assignment_writer = SimpleNamespace(cluster_repository=cluster_repo)
    cluster_service.merge_cluster = AsyncMock(return_value=cluster_b)
    session = AsyncMock()

    async def execute(statement: object) -> SimpleNamespace:
        order.append(("status", statement))
        return SimpleNamespace(rowcount=1)

    session.execute.side_effect = execute

    response = await accept_merge_suggestion(
        suggestion_id=suggestion.id,
        request=AcceptMergeSuggestionRequest(tenant_id=tenant_id),
        auth=SimpleNamespace(tenant_claim=tenant_id),
        session=session,
        cluster_service_builder=AsyncMock(return_value=cluster_service),
    )

    assert response.status == SuggestionStatus.ACCEPTED.value
    status_statement = order[0][1]
    assert "update cluster_merge_suggestions" in str(status_statement).lower()
    assert status_statement.compile().params["resolution"] == SuggestionStatus.ACCEPTED.value
    assert [event[0] for event in order] == ["status", "delete", "delete"]
    assert order[1:] == [
        ("delete", response.source_cluster_id),
        ("delete", response.target_cluster_id),
    ]
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_accept_merge_returns_conflict_when_acceptance_cas_updates_no_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    cluster_a = _cluster(uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), uuid.UUID(tenant_id), "A")
    cluster_b = _cluster(uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"), uuid.UUID(tenant_id), "B")
    suggestion = MergeSuggestion(
        id=str(uuid.uuid4()),
        cluster_a_id=str(cluster_a.id),
        cluster_b_id=str(cluster_b.id),
        similarity=0.91,
        status=SuggestionStatus.PENDING,
    )
    order: list[tuple[str, object]] = []
    get_by_id = AsyncMock(return_value=suggestion)

    async def delete_by_cluster(
        _repo: SqlAlchemyMergeSuggestionRepository,
        _tenant_id: str,
        cluster_id: str,
    ) -> int:
        order.append(("delete", cluster_id))
        return 1

    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "__init__", lambda self, _session: None)
    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "get_by_id", get_by_id)
    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "delete_by_cluster", delete_by_cluster)
    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.side_effect = [cluster_a, cluster_b]
    cluster_service = AsyncMock()
    cluster_service.assignment_writer = SimpleNamespace(cluster_repository=cluster_repo)
    cluster_service.merge_cluster = AsyncMock(return_value=cluster_b)
    session = AsyncMock()

    async def execute(statement: object) -> SimpleNamespace:
        order.append(("status", statement))
        return SimpleNamespace(rowcount=0)

    session.execute.side_effect = execute

    with pytest.raises(HTTPException) as excinfo:
        await accept_merge_suggestion(
            suggestion_id=suggestion.id,
            request=AcceptMergeSuggestionRequest(tenant_id=tenant_id),
            auth=SimpleNamespace(tenant_claim=tenant_id),
            session=session,
            cluster_service_builder=AsyncMock(return_value=cluster_service),
        )

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "Merge suggestion is no longer pending"
    assert [event[0] for event in order] == ["status"]
    session.commit.assert_not_awaited()
