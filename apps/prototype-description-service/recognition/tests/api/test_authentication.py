"""Authentication and tenant scope tests (TDD - expected to fail until auth is enforced)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.config.security import SecuritySettings
from recognition.interface_adapters.http.deps import auth
from recognition.tests.api.conftest import FakeSession
from recognition.tests.fakes import FakeClusterService


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

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return token_tenant, "api-key-id", "free", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    headers = {"X-Tenant-ID": request_tenant, "Authorization": "Bearer good-key"}

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


def test_valid_x_api_key_header_allows_request_with_default_settings(monkeypatch) -> None:
    """WordPress-style X-Api-Key headers should authenticate without an env override."""
    client = _auth_client(FakeClusterService(), monkeypatch)
    tenant_id = str(uuid.uuid4())

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "free", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    headers = {
        "X-Tenant-ID": tenant_id,
        "X-Api-Key": "good-key",
    }

    response = client.get("/recognition/clusters", headers=headers)

    assert response.status_code == 200


def test_valid_x_api_key_header_allows_request_when_configured(monkeypatch) -> None:
    """Explicit X-Api-Key configuration should accept the raw header value the WP proxy sends."""
    monkeypatch.setenv("RECOGNITION_API_KEY_HEADER", "X-Api-Key")
    client = _auth_client(FakeClusterService(), monkeypatch)
    tenant_id = str(uuid.uuid4())

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "free", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    headers = {
        "X-Tenant-ID": tenant_id,
        "X-Api-Key": "good-key",
    }

    response = client.get("/recognition/clusters", headers=headers)

    assert response.status_code == 200


def test_dev_key_returns_503_when_optional_session_is_unavailable(monkeypatch) -> None:
    """Breaker-open/session-unavailable requests must fail before dev-key fallback."""
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    monkeypatch.setenv("RECOGNITION_ALLOWED_API_KEYS", "good-key")
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_dep():
        yield None

    def cluster_builder():
        async def _build(_tenant_id: str):
            return FakeClusterService()

        return _build

    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_cluster_service_builder] = cluster_builder
    client = TestClient(app)

    response = client.get(
        "/recognition/clusters",
        headers={"Authorization": "Bearer good-key", "X-Tenant-ID": str(uuid.uuid4())},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Database unavailable"


class _FakeLookupError(Exception):
    """Small DB-ish exception carrying SQLSTATE for auth lookup tests."""

    def __init__(self, message: str, *, sqlstate: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def test_classify_auth_lookup_failure_25p02_returns_transaction_aborted() -> None:
    """Aborted-transaction SQLSTATE should translate to a retryable auth failure."""
    failure = auth._classify_auth_lookup_failure(_FakeLookupError("aborted transaction", sqlstate="25P02"))

    assert failure.kind == "transaction_aborted"
    assert failure.sqlstate == "25P02"
    assert auth._translate_auth_lookup_failure(failure).status_code == 503


@pytest.mark.asyncio
async def test_lookup_api_key_is_pure_query_and_uses_nested_transaction() -> None:
    """Successful auth lookup should not flush telemetry writes on the request session."""
    session = FakeSession()
    tenant_id = uuid.uuid4()
    api_key_id = uuid.uuid4()
    session.queue_execute_result(
        scalar_one_or_none=SimpleNamespace(id=api_key_id, tenant_id=tenant_id, rate_limit_tier="free")
    )

    result = await auth._lookup_api_key(
        "good-key",
        SecuritySettings(auth_enabled=True, dev_api_keys=[]),
        session,
    )

    assert result == (str(tenant_id), str(api_key_id), "free", False)
    assert session.begin_nested_calls == 1
    assert session.nested_rollback_calls == 0
    assert session.flush_calls == 0


@pytest.mark.asyncio
async def test_lookup_api_key_translates_missing_table_to_500_and_rolls_back_savepoint() -> None:
    """Permanent auth-store faults should fail fast at the auth boundary."""
    session = FakeSession()
    session.queue_execute_exception(_FakeLookupError('relation "api_keys" does not exist', sqlstate="42P01"))

    with pytest.raises(HTTPException) as exc_info:
        await auth._lookup_api_key(
            "good-key",
            SecuritySettings(auth_enabled=True, dev_api_keys=[]),
            session,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "api key store unavailable"
    assert session.begin_nested_calls == 1
    assert session.nested_rollback_calls == 1
