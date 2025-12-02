"""Integration-style test for suggestion acceptance flow."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

suggestion_router_module = importlib.import_module("recognition.interface_adapters.http.suggestion_router")


class FakeSession:
    """Minimal AsyncSession stub for suggestion acceptance."""

    def __init__(self, suggestion: Any) -> None:
        self._suggestion = suggestion
        self.commit_calls = 0

    async def get(self, _model: Any, _id: Any) -> Any:
        return self._suggestion

    async def execute(self, _stmt: Any) -> SimpleNamespace:  # expire_suggestions_for_identity uses execute().rowcount
        return SimpleNamespace(rowcount=0)

    async def commit(self) -> None:
        self.commit_calls += 1

    async def flush(self) -> None:
        return None


class FakeClusteringService:
    """Stub IdentityClusteringService that tracks assignments."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.calls: list[tuple] = []

    async def assign_identity_to_cluster(self, identity_id: Any, cluster_id: Any) -> None:
        self.calls.append((identity_id, cluster_id))


class FakeSuggestionService:
    """Stub SuggestionService used in router acceptance."""

    def __init__(self, session: FakeSession, tenant_id: Any):
        self.session = session
        self.tenant_id = tenant_id
        self.expire_calls: list = []

    async def accept_suggestion(self, suggestion_id: Any):
        suggestion = await self.session.get(None, suggestion_id)
        # Simulate what the real service does: mark as accepted
        suggestion.resolution = "accepted"
        return suggestion

    async def expire_suggestions_for_identity(self, identity_id: Any) -> int:
        self.expire_calls.append(identity_id)
        return 0


@pytest.mark.asyncio
async def test_accept_suggestion_assigns_identity(monkeypatch) -> None:
    """Accepting a suggestion assigns the identity to the suggested cluster and commits."""
    tenant_id = uuid4()
    identity_id = uuid4()
    cluster_id = uuid4()
    suggestion_id = uuid4()

    suggestion = SimpleNamespace(
        id=suggestion_id,
        tenant_id=tenant_id,
        resolution="pending",
        representative_similarity=0.91,
        avg_member_similarity=0.90,
        suggested_cluster_id=cluster_id,
        identity_id=identity_id,
        resolved_at=None,
    )

    fake_session = FakeSession(suggestion)
    fake_clustering = FakeClusteringService()

    async def noop_set_tenant_context(_session, _tenant_id):
        return None

    def fake_clustering_factory(_session, _tenant_id):
        return fake_clustering

    # Patch out dependencies inside the router module
    monkeypatch.setattr(suggestion_router_module, "set_tenant_context", noop_set_tenant_context)
    # Patch the class in the router module where it's imported and used
    monkeypatch.setattr(suggestion_router_module, "IdentityClusteringService", fake_clustering_factory)
    monkeypatch.setattr(
        suggestion_router_module,
        "SuggestionService",
        lambda session, tenant_id: FakeSuggestionService(session, tenant_id),
    )

    response = await suggestion_router_module.accept_suggestion(
        suggestion_id=suggestion_id,
        tenant_id=tenant_id,
        session=fake_session,
    )

    # Identity should be assigned to cluster
    assert fake_clustering.calls == [(identity_id, cluster_id)]
    # Suggestion should be marked accepted
    assert response.resolution == "accepted"
    assert response.id == str(suggestion_id)
    assert fake_session.commit_calls >= 1
