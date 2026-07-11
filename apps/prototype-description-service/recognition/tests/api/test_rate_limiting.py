"""Rate limiting dependency tests (Slice 1 of E15-1).

Covers:
- under-limit requests return 200
- at-limit (N+1) returns 429 with Retry-After + X-RateLimit-* headers
- per-key counter isolation
- tier override (PRO = 3x STANDARD)
- auth-disabled bypass (RECOGNITION_AUTH_ENABLED=false)
- burst handling (window-based, not per-second)
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps import auth as auth_module
from recognition.tests.api.conftest import FakeSession
from recognition.tests.fakes import FakeClusterService


def _reset_limiter_state() -> None:
    """Clear the in-memory rate-limiter counter dict between tests."""
    from recognition.interface_adapters.http.deps import rate_limit

    rate_limit._reset_state_for_tests()


def _build_client(
    monkeypatch,
    *,
    auth_enabled: str = "1",
    rpm: str = "5",
) -> TestClient:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", auth_enabled)
    monkeypatch.setenv("RECOGNITION_RATE_LIMIT_RPM", rpm)
    _reset_limiter_state()

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_dep():
        yield FakeSession()

    def cluster_builder():
        async def _build(_tenant_id: str):
            return FakeClusterService()

        return _build

    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_cluster_service_builder] = cluster_builder
    return TestClient(app)


def _install_lookup(monkeypatch, *, tenant_id: str, api_key_id: str, tier: str | None = None) -> None:
    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, api_key_id, tier, False

    monkeypatch.setattr(auth_module, "_lookup_api_key", _fake_lookup)


def test_under_limit_returns_200(monkeypatch) -> None:
    client = _build_client(monkeypatch, rpm="5")
    tenant_id = str(uuid.uuid4())
    _install_lookup(monkeypatch, tenant_id=tenant_id, api_key_id="key-1")
    headers = {"X-Tenant-ID": tenant_id, "Authorization": "Bearer good-key"}

    for _ in range(5):
        response = client.get("/recognition/clusters", headers=headers)
        assert response.status_code == 200


def test_at_limit_returns_429_with_headers(monkeypatch) -> None:
    client = _build_client(monkeypatch, rpm="3")
    tenant_id = str(uuid.uuid4())
    _install_lookup(monkeypatch, tenant_id=tenant_id, api_key_id="key-A")
    headers = {"X-Tenant-ID": tenant_id, "Authorization": "Bearer good-key"}

    for _ in range(3):
        assert client.get("/recognition/clusters", headers=headers).status_code == 200

    response = client.get("/recognition/clusters", headers=headers)
    assert response.status_code == 429
    assert response.json()["detail"] == "rate limit exceeded"
    assert "Retry-After" in response.headers
    assert int(response.headers["Retry-After"]) >= 0
    assert response.headers["X-RateLimit-Limit"] == "3"
    assert response.headers["X-RateLimit-Remaining"] == "0"


def test_per_key_isolation(monkeypatch) -> None:
    client = _build_client(monkeypatch, rpm="2")
    tenant_id = str(uuid.uuid4())
    # Alternating keys via dynamic lookup
    state = {"key": "key-A"}

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, state["key"], None, False

    monkeypatch.setattr(auth_module, "_lookup_api_key", _fake_lookup)
    headers = {"X-Tenant-ID": tenant_id, "Authorization": "Bearer good-key"}

    state["key"] = "key-A"
    assert client.get("/recognition/clusters", headers=headers).status_code == 200
    assert client.get("/recognition/clusters", headers=headers).status_code == 200
    assert client.get("/recognition/clusters", headers=headers).status_code == 429

    state["key"] = "key-B"
    assert client.get("/recognition/clusters", headers=headers).status_code == 200
    assert client.get("/recognition/clusters", headers=headers).status_code == 200
    assert client.get("/recognition/clusters", headers=headers).status_code == 429


def test_pro_tier_gets_triple_budget(monkeypatch) -> None:
    client = _build_client(monkeypatch, rpm="2")
    tenant_id = str(uuid.uuid4())
    _install_lookup(monkeypatch, tenant_id=tenant_id, api_key_id="key-pro", tier="PRO")
    headers = {"X-Tenant-ID": tenant_id, "Authorization": "Bearer good-key"}

    # STANDARD would cap at 2; PRO should allow 6.
    for _ in range(6):
        assert client.get("/recognition/clusters", headers=headers).status_code == 200

    response = client.get("/recognition/clusters", headers=headers)
    assert response.status_code == 429
    assert response.headers["X-RateLimit-Limit"] == "6"


def test_auth_disabled_bypass(monkeypatch) -> None:
    client = _build_client(monkeypatch, auth_enabled="0", rpm="2")
    tenant_id = str(uuid.uuid4())
    headers = {"X-Tenant-ID": tenant_id}

    for _ in range(20):
        assert client.get("/recognition/clusters", headers=headers).status_code == 200


def test_burst_within_window(monkeypatch) -> None:
    """A short burst of requests below the per-window limit all succeed."""
    client = _build_client(monkeypatch, rpm="10")
    tenant_id = str(uuid.uuid4())
    _install_lookup(monkeypatch, tenant_id=tenant_id, api_key_id="key-burst")
    headers = {"X-Tenant-ID": tenant_id, "Authorization": "Bearer good-key"}

    # 10 requests in rapid succession — all fit in window.
    for _ in range(10):
        assert client.get("/recognition/clusters", headers=headers).status_code == 200

    # The 11th crosses the cap.
    assert client.get("/recognition/clusters", headers=headers).status_code == 429


def test_rate_limit_tier_enum_values() -> None:
    """The RateLimitTier enum defines exactly STANDARD/PRO/ENTERPRISE string values."""
    from recognition.config.security import RateLimitTier, SecuritySettings, tier_rpm

    assert RateLimitTier.STANDARD.value == "STANDARD"
    assert RateLimitTier.PRO.value == "PRO"
    assert RateLimitTier.ENTERPRISE.value == "ENTERPRISE"

    settings = SecuritySettings(rate_limit_requests_per_minute=60)
    assert tier_rpm(RateLimitTier.STANDARD, settings) == 60
    assert tier_rpm(RateLimitTier.PRO, settings) == 180
    assert tier_rpm(RateLimitTier.ENTERPRISE, settings) == 600
