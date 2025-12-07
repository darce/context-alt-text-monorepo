"""Tenant validation tests for API routes (faked services)."""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.shared.ids import generate_id
from recognition.tests.api.conftest import FakeSession


def _tenant_validation_client() -> TestClient:
    """Build a TestClient that preserves real tenant validation."""
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_dep():
        yield FakeSession()

    def cluster_builder():
        async def _build(_tenant_id: str):
            class StubClusterService:
                async def list_clusters(self, tenant_id: str, limit: int, offset: int, include_outliers: bool = False):
                    return []

            return StubClusterService()

        return _build

    class StubSuggestionService:
        async def list_for_identity(self, identity_id: str):
            return []

        async def accept(self, suggestion_id: str):
            return None

        async def reject(self, suggestion_id: str):
            return None

        async def list_pending(self, limit: int = 50, offset: int = 0):  # noqa: ARG002
            return []

    async def suggestion_service_dep(session=None, tenant_id=None):  # noqa: ANN001
        return StubSuggestionService()

    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_cluster_service_builder] = cluster_builder
    app.dependency_overrides[dependencies.get_suggestion_service] = suggestion_service_dep
    from recognition.interface_adapters.http.routers import suggestions as suggestions_router

    app.dependency_overrides[suggestions_router.get_suggestion_service] = suggestion_service_dep
    return TestClient(app)


def test_missing_tenant_returns_400() -> None:
    client = _tenant_validation_client()
    resp = client.get("/recognition/clusters")

    assert resp.status_code == 400


def test_invalid_tenant_format_returns_400() -> None:
    client = _tenant_validation_client()
    resp = client.get("/recognition/clusters", headers={"X-Tenant-ID": "invalid-id"})

    assert resp.status_code == 400


def test_suggestions_require_tenant_header() -> None:
    client = _tenant_validation_client()
    resp = client.get("/recognition/identities/abc/suggestions")
    assert resp.status_code == 400

    resp_accept = client.post("/recognition/suggestions/abc/accept", json={"tenant_id": "abc"})
    assert resp_accept.status_code in {400, 422}


def test_query_param_tenant_fallback(monkeypatch) -> None:
    """Query param may be used when header is absent."""
    collected: dict[str, str] = {}

    def builder():
        async def _build(tenant_id: str):
            collected["tenant_id"] = tenant_id

            class StubClusterService:
                async def list_clusters(self, tenant_id: str, limit: int, offset: int, include_outliers: bool = False):
                    collected["service_tenant"] = tenant_id
                    return []

            return StubClusterService()

        return _build

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_dep():
        yield FakeSession()

    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_cluster_service_builder] = builder
    client = TestClient(app)
    tenant_value = str(uuid.uuid4())

    resp = client.get("/recognition/clusters", params={"tenant_id": tenant_value})

    assert resp.status_code == 200
    assert collected["tenant_id"] == tenant_value
    assert collected["service_tenant"] == tenant_value


def test_session_context_cleared_after_request(monkeypatch) -> None:
    """Tenant context should be set and cleared so sessions do not leak between requests."""
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    events: list[tuple[str, str | None]] = []

    class StubSession:
        def __init__(self) -> None:
            self.current_tenant: str | None = None
            self.executed = False

        async def execute(self, *_args, **_kwargs):
            self.executed = True
            return None

    session = StubSession()

    async def fake_set(session_obj, tenant_id):
        events.append(("set", str(tenant_id)))
        session_obj.current_tenant = str(tenant_id)

    async def fake_clear(session_obj):
        events.append(("clear", session_obj.current_tenant))
        session_obj.current_tenant = None

    async def fake_session_source():
        events.append(("open", session.current_tenant))
        try:
            yield session
        finally:
            events.append(("session_exit", session.current_tenant))

    monkeypatch.setattr("db.tenant_context.set_tenant_context", fake_set)
    monkeypatch.setattr("db.tenant_context.clear_tenant_context", fake_clear)
    monkeypatch.setattr(dependencies, "_get_session", fake_session_source)

    def builder(session_dep=Depends(dependencies.get_session)):
        async def _build(_: str):
            class StubClusterService:
                async def list_clusters(self, tenant_id: str, limit: int, offset: int, include_outliers: bool = False):
                    events.append(("list", tenant_id, session_dep.current_tenant))
                    return []

            return StubClusterService()

        return _build

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    app.dependency_overrides[dependencies.get_cluster_service_builder] = builder
    client = TestClient(app)

    first = client.get(
        "/recognition/clusters",
        headers={"X-Tenant-ID": tenant_a},
        params={"tenant_id": tenant_a},
    )
    second = client.get(
        "/recognition/clusters",
        headers={"X-Tenant-ID": tenant_b},
        params={"tenant_id": tenant_b},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert any(evt[0] == "list" and evt[1] == tenant_a for evt in events)
    assert any(evt[0] == "list" and evt[1] == tenant_b for evt in events)
    assert session.current_tenant is None
