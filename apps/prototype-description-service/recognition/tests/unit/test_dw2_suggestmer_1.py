from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from recognition.domain.cluster import IdentityCluster
from recognition.domain.suggestion import MergeSuggestion, SuggestionStatus
from recognition.infrastructure.repositories import SqlAlchemyMergeSuggestionRepository
from recognition.interface_adapters.http.routers.suggestions import (
    AcceptMergeSuggestionRequest,
    accept_merge_suggestion,
)


def _cluster(cluster_id: str, tenant_id: str) -> IdentityCluster:
    return IdentityCluster(
        tenant_id=tenant_id,
        is_labeled=False,
        identity_count=1,
        id=cluster_id,
        user_confirmed=False,
    )


@pytest.mark.asyncio
async def test_accept_merge_rejects_cluster_owned_by_another_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = str(uuid4())
    other_tenant_id = str(uuid4())
    cluster_a = _cluster("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", tenant_id)
    cluster_b = _cluster("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", other_tenant_id)
    suggestion = MergeSuggestion(
        id=str(uuid4()),
        cluster_a_id=cluster_a.id or "",
        cluster_b_id=cluster_b.id or "",
        similarity=0.91,
        status=SuggestionStatus.PENDING,
    )

    suggestion_repo = Mock()
    suggestion_repo.get_by_id = AsyncMock(return_value=suggestion)
    suggestion_repo.delete_by_cluster = AsyncMock(return_value=0)
    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "__init__", lambda self, _session: None)
    monkeypatch.setattr(SqlAlchemyMergeSuggestionRepository, "get_by_id", suggestion_repo.get_by_id)
    monkeypatch.setattr(
        SqlAlchemyMergeSuggestionRepository,
        "delete_by_cluster",
        suggestion_repo.delete_by_cluster,
    )

    cluster_repo = AsyncMock()
    cluster_repo.get_by_id.side_effect = [cluster_a, cluster_b]
    cluster_service = AsyncMock()
    cluster_service.assignment_writer = SimpleNamespace(cluster_repository=cluster_repo)
    cluster_service.merge_cluster = AsyncMock(return_value=cluster_b)
    service_builder = AsyncMock(return_value=cluster_service)
    session = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await accept_merge_suggestion(
            suggestion_id=suggestion.id,
            request=AcceptMergeSuggestionRequest(tenant_id=tenant_id),
            auth=SimpleNamespace(tenant_claim=tenant_id),
            session=session,
            cluster_service_builder=service_builder,
        )

    assert exc.value.status_code == 404
    service_builder.assert_awaited_once_with(tenant_id)
    cluster_service.merge_cluster.assert_not_awaited()
    session.commit.assert_not_awaited()
