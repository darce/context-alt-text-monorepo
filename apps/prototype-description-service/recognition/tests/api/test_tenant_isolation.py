"""Tenant validation tests for API routes (faked services)."""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.shared.ids import generate_id
from recognition.tests.api.conftest import FakeSession


class StubClusterService:
    """Shared minimal cluster service stub for tenant-isolation tests."""

    def __init__(self, on_list=None):  # noqa: ANN001
        self._on_list = on_list

    async def list_clusters(
        self,
        tenant_id: str,
        limit: int,
        offset: int,
        include_outliers: bool = False,
        labeled_only: bool = False,
        search: str | None = None,
    ):
        if self._on_list is not None:
            self._on_list(
                tenant_id=tenant_id,
                limit=limit,
                offset=offset,
                include_outliers=include_outliers,
                labeled_only=labeled_only,
                search=search,
            )
        return []


def _tenant_validation_client() -> TestClient:
    """Build a TestClient that preserves real tenant validation."""
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_dep():
        yield FakeSession()

    def cluster_builder():
        async def _build(_tenant_id: str):
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


def test_query_param_tenant_rejected_on_authenticated_route(monkeypatch) -> None:
    """Sensitive routes that depend on ``get_authenticated_tenant_id`` must not
    honour a ``tenant_id`` query param — it is intentionally ignored so the
    tenant claim comes from the authenticated context or an ``X-Tenant-ID``
    admin override. Hardened in commit e79e19b7 (E15-3a-BR-15).
    """
    collected: dict[str, str] = {}

    def builder():
        async def _build(tenant_id: str):
            collected["tenant_id"] = tenant_id

            return StubClusterService(on_list=lambda **_: collected.__setitem__("service_tenant", tenant_id))

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

    assert resp.status_code == 400
    assert collected == {}


def test_session_context_is_reset_by_next_request_setup(monkeypatch) -> None:
    """Each request should establish its tenant context without dependency-local cleanup."""
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

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

        async def close(self) -> None:
            return None

    session = StubSession()

    async def fake_set(session_obj, tenant_id):
        events.append(("set", str(tenant_id)))
        session_obj.current_tenant = str(tenant_id)

    async def fake_commit():
        events.append(("commit", session.current_tenant))

    async def fake_rollback():
        events.append(("rollback", session.current_tenant))

    async def fake_close():
        events.append(("session_exit", session.current_tenant))

    session.commit = fake_commit
    session.rollback = fake_rollback
    session.close = fake_close

    from recognition.interface_adapters.http.deps import session as session_module

    monkeypatch.setattr(session_module, "async_session_factory", lambda: session)
    monkeypatch.setattr(session_module, "set_tenant_context", fake_set)

    def builder(session_dep=Depends(dependencies.get_session)):
        async def _build(_: str):
            return StubClusterService(
                on_list=lambda **kwargs: events.append(("list", kwargs["tenant_id"], session_dep.current_tenant))
            )

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
    assert ("set", tenant_a) in events
    assert ("set", tenant_b) in events
    assert not any(evt[0] == "clear" for evt in events)
    assert session.current_tenant == tenant_b
