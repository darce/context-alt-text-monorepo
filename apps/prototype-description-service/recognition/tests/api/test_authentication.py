"""Authentication and tenant scope tests (TDD - expected to fail until auth is enforced)."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.tests.api.conftest import FakeSession
from recognition.tests.conftest import FakeClusterService


def _auth_client(fake_cluster_service: FakeClusterService, monkeypatch) -> TestClient:
    """Build a client with faked dependencies to avoid real DB connections."""
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_dep():
        yield FakeSession()

    def cluster_builder():
        async def _build(_tenant_id: str):
            return fake_cluster_service

        return _build

    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_cluster_service_builder] = cluster_builder
    return TestClient(app)


def test_missing_authorization_header_returns_401(monkeypatch) -> None:
    """Requests without Authorization should be rejected."""
    client = _auth_client(FakeClusterService(), monkeypatch)
    tenant_id = str(uuid.uuid4())

    response = client.get("/recognition/clusters", headers={"X-Tenant-ID": tenant_id})

    assert response.status_code == 401


def test_invalid_bearer_token_returns_403(monkeypatch) -> None:
    """Malformed or unknown tokens should return 403."""
    client = _auth_client(FakeClusterService(), monkeypatch)
    tenant_id = str(uuid.uuid4())
    headers = {"X-Tenant-ID": tenant_id, "Authorization": "Bearer invalid-token"}

    response = client.get("/recognition/clusters", headers=headers)

    assert response.status_code == 403


def test_token_tenant_mismatch_returns_403(monkeypatch) -> None:
    """Token tenant claim must align with request tenant to protect isolation."""
    client = _auth_client(FakeClusterService(), monkeypatch)
    token_tenant = str(uuid.uuid4())
    request_tenant = str(uuid.uuid4())
    headers = {
        "X-Tenant-ID": request_tenant,
        "Authorization": f"Bearer tenant:{token_tenant}",
    }

    response = client.get("/recognition/clusters", headers=headers)

    assert response.status_code == 403


def test_valid_api_key_allows_request(monkeypatch) -> None:
    """A valid API key should authenticate and pass the request through."""
    client = _auth_client(FakeClusterService(), monkeypatch)
    tenant_id = str(uuid.uuid4())

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "free", False

    # Patch in the auth module where it's actually used
    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    headers = {
        "X-Tenant-ID": tenant_id,
        "Authorization": "Bearer good-key",
    }

    response = client.get("/recognition/clusters", headers=headers)

    assert response.status_code == 200
