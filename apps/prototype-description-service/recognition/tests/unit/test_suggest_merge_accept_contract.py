"""FEBT1-LD-01: atomic merge-accept returns revert ids and honours operator target."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from recognition.domain.cluster import CrossSpaceMergeError, IdentityCluster
from recognition.domain.suggestion import MergeSuggestion, SuggestionStatus
from recognition.infrastructure.repositories import SqlAlchemyMergeSuggestionRepository
from recognition.interface_adapters.http.routers.suggestions import (
    AcceptMergeSuggestionRequest,
    AcceptMergeSuggestionResponse,
    _resolve_merge_pair,
    _to_accept_merge_response,
    accept_merge_suggestion,
)
from recognition.interface_adapters.http.schemas.responses import MergeSuggestionResponse


def _cluster(cluster_id: str, *, identity_count: int = 1) -> IdentityCluster:
    return IdentityCluster(
        tenant_id=str(uuid4()),
        is_labeled=False,
        identity_count=identity_count,
        id=cluster_id,
        user_confirmed=False,
    )


def test_accept_merge_response_includes_moved_identity_ids() -> None:
    assert "moved_identity_ids" in AcceptMergeSuggestionResponse.model_fields
    assert "target_cluster_id" in AcceptMergeSuggestionRequest.model_fields
    payload = _to_accept_merge_response(
        MergeSuggestionResponse(
            id=str(uuid4()),
            cluster_a_id=str(uuid4()),
            cluster_b_id=str(uuid4()),
            similarity=0.7,
            status="accepted",
        ),
        moved_identity_ids=["id-1", "id-2"],
    )
    assert payload.moved_identity_ids == ["id-1", "id-2"]


def test_resolve_merge_pair_honours_operator_target() -> None:
    smaller = _cluster("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", identity_count=1)
    larger = _cluster("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", identity_count=9)

    source_id, target_id, _label = _resolve_merge_pair(
        smaller,
        larger,
        requested_target_cluster_id=smaller.id,
    )

    assert target_id == smaller.id
    assert source_id == larger.id


def test_resolve_merge_pair_rejects_unrelated_target() -> None:
    cluster_a = _cluster("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    cluster_b = _cluster("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    with pytest.raises(HTTPException) as exc:
        _resolve_merge_pair(
            cluster_a,
            cluster_b,
            requested_target_cluster_id=str(uuid4()),
        )

    assert exc.value.status_code == 422


def _pending_suggestion(cluster_a_id: str, cluster_b_id: str) -> MergeSuggestion:
    return MergeSuggestion(
        id=str(uuid4()),
        cluster_a_id=cluster_a_id,
        cluster_b_id=cluster_b_id,
        similarity=0.91,
        status=SuggestionStatus.PENDING,
    )


def _bind_merge_repo(monkeypatch: pytest.MonkeyPatch, suggestion: MergeSuggestion) -> Mock:
    repo = Mock()
    repo.get_by_id = AsyncMock(return_value=suggestion)
    repo.delete_by_cluster = AsyncMock(return_value=0)
    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "__init__", lambda self, _session: None)
    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "get_by_id", repo.get_by_id)
    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "delete_by_cluster", repo.delete_by_cluster)
    return repo


@pytest.mark.asyncio
async def test_accept_merge_cross_space_returns_409_and_moves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid4())
    cluster_a = _cluster("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", identity_count=2)
    cluster_b = _cluster("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", identity_count=4)
    suggestion = _pending_suggestion(cluster_a.id or "", cluster_b.id or "")
    _bind_merge_repo(monkeypatch, suggestion)

    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.side_effect = [cluster_a, cluster_b]
    cluster_repo.list_identity_ids_moved_by_merge = AsyncMock(return_value=["should-not-run"])
    cluster_service = AsyncMock()
    cluster_service.assignment_writer = SimpleNamespace(cluster_repository=cluster_repo)
    cluster_service.merge_cluster = AsyncMock(
        side_effect=CrossSpaceMergeError(
            source_cluster_id=cluster_a.id or "",
            target_cluster_id=cluster_b.id or "",
            source_model="space-a",
            target_model="space-b",
        )
    )
    session = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await accept_merge_suggestion(
            suggestion_id=suggestion.id,
            request=AcceptMergeSuggestionRequest(tenant_id=tenant_id),
            auth=SimpleNamespace(tenant_claim=tenant_id),
            session=session,
            cluster_service_builder=AsyncMock(return_value=cluster_service),
        )

    assert exc.value.status_code == 409
    assert "space-a" in str(exc.value.detail)
    cluster_repo.list_identity_ids_moved_by_merge.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_accept_merge_moved_identity_ids_match_session_stamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid4())
    cluster_a = _cluster("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", identity_count=2)
    cluster_b = _cluster("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", identity_count=4)
    suggestion = _pending_suggestion(cluster_a.id or "", cluster_b.id or "")
    _bind_merge_repo(monkeypatch, suggestion)

    moved = [str(uuid4()), str(uuid4())]
    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.side_effect = [cluster_a, cluster_b]
    cluster_repo.list_identity_ids_moved_by_merge = AsyncMock(return_value=moved)
    cluster_service = AsyncMock()
    cluster_service.assignment_writer = SimpleNamespace(cluster_repository=cluster_repo)
    cluster_service.merge_cluster = AsyncMock(return_value=cluster_b)
    session = AsyncMock()

    response = await accept_merge_suggestion(
        suggestion_id=suggestion.id,
        request=AcceptMergeSuggestionRequest(tenant_id=tenant_id),
        auth=SimpleNamespace(tenant_claim=tenant_id),
        session=session,
        cluster_service_builder=AsyncMock(return_value=cluster_service),
    )

    assert response.moved_identity_ids == moved
    cluster_repo.list_identity_ids_moved_by_merge.assert_awaited_once_with(tenant_id, suggestion.id)
    session.commit.assert_awaited_once()
    cluster_service.merge_cluster.assert_awaited_once()


@pytest.mark.asyncio
async def test_accept_merge_accepted_replay_returns_empty_moved_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid4())
    cluster_a = _cluster("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", identity_count=2)
    cluster_b = _cluster("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", identity_count=4)
    suggestion = _pending_suggestion(cluster_a.id or "", cluster_b.id or "")
    suggestion.status = SuggestionStatus.ACCEPTED
    _bind_merge_repo(monkeypatch, suggestion)

    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.side_effect = [None, cluster_b]
    cluster_repo.list_identity_ids_moved_by_merge = AsyncMock(return_value=["stale"])
    cluster_service = AsyncMock()
    cluster_service.assignment_writer = SimpleNamespace(cluster_repository=cluster_repo)
    session = AsyncMock()

    response = await accept_merge_suggestion(
        suggestion_id=suggestion.id,
        request=AcceptMergeSuggestionRequest(tenant_id=tenant_id),
        auth=SimpleNamespace(tenant_claim=tenant_id),
        session=session,
        cluster_service_builder=AsyncMock(return_value=cluster_service),
    )

    assert response.moved_identity_ids == []
    cluster_service.merge_cluster.assert_not_awaited()
    cluster_repo.list_identity_ids_moved_by_merge.assert_not_awaited()
    session.commit.assert_not_awaited()
