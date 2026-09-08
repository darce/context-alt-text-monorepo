"""API tests for tenant whoami endpoint (E15-24 slice 2 / MAINT key-only auth)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from db.models import Tenant
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth_key_only
from recognition.interface_adapters.http.routers import tenant as tenant_router
from recognition.tests.api.conftest import FakeSession


def _build_client(
    *,
    auth: AuthContext,
    tenant: Tenant | None,
) -> TestClient:
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    fake_session = FakeSession()
    if tenant is not None:
        for _ in range(8):
            fake_session.queue_execute_result(scalar_one_or_none=tenant)

    async def _session_override():
        yield fake_session

    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[require_auth_key_only] = lambda: auth
    return TestClient(app)


def _whoami_client_with_real_auth(
    *,
    tenant: Tenant | None,
    monkeypatch: pytest.MonkeyPatch,
    lookup_side_effect=None,  # noqa: ANN001
    lookup_result: tuple[str | None, str | None, str | None, bool] | None = None,
) -> TestClient:
    """Client that exercises require_auth_key_only (no auth override)."""
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    fake_session = FakeSession()
    if tenant is not None:
        # Auth path + whoami tenant lookup may each execute queries.
        for _ in range(16):
            fake_session.queue_execute_result(scalar_one_or_none=tenant)

    async def _session_override():
        yield fake_session

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        if lookup_side_effect is not None:
            raise lookup_side_effect
        assert lookup_result is not None
        return lookup_result

    from recognition.interface_adapters.http.deps import auth as auth_module

    monkeypatch.setattr(auth_module, "_lookup_api_key", _fake_lookup)
    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    return TestClient(app)


def test_whoami_returns_key_tenant_claim_and_site_url() -> None:
    tenant_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, site_url="https://prod.example")
    auth = AuthContext(
        token="key",
        tenant_claim=str(tenant_id),
        api_key_id="key-1",
        rate_limit_tier="default",
        is_admin=False,
        enabled=True,
    )
    client = _build_client(auth=auth, tenant=tenant)

    resp = client.get("/recognition/tenant/whoami", headers={"X-Tenant-ID": str(tenant_id)})

    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == str(tenant_id)
    assert body["site_url"] == "https://prod.example"


def test_whoami_missing_tenant_row_returns_404() -> None:
    tenant_id = uuid.uuid4()
    auth = AuthContext(
        token="key",
        tenant_claim=str(tenant_id),
        api_key_id="key-1",
        rate_limit_tier="default",
        is_admin=False,
        enabled=True,
    )
    client = _build_client(auth=auth, tenant=None)

    resp = client.get("/recognition/tenant/whoami", headers={"X-Tenant-ID": str(tenant_id)})

    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["code"] == "tenant_not_found"
    assert detail["tenant_id"] == str(tenant_id)


@pytest.mark.asyncio
async def test_whoami_malformed_tenant_claim_returns_403() -> None:
    auth = AuthContext(
        token="key",
        tenant_claim="not-a-uuid",
        api_key_id="key-1",
        rate_limit_tier="default",
        is_admin=False,
        enabled=True,
    )
    with pytest.raises(HTTPException) as caught:
        await tenant_router.tenant_whoami(auth=auth, session=FakeSession())

    assert caught.value.status_code == 403
    assert caught.value.detail == "invalid tenant claim"


def test_whoami_admin_without_claim_returns_404() -> None:
    auth = AuthContext(
        token="admin-key",
        tenant_claim=None,
        api_key_id="admin-1",
        rate_limit_tier="admin",
        is_admin=True,
        enabled=True,
    )
    client = _build_client(auth=auth, tenant=None)

    resp = client.get("/recognition/tenant/whoami")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "no tenant claim"


def test_whoami_mismatched_x_tenant_id_returns_key_canonical_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid key + mismatched X-Tenant-ID must 200 with the key-bound tenant."""
    key_tenant_id = uuid.uuid4()
    header_tenant_id = uuid.uuid4()
    tenant = Tenant(id=key_tenant_id, site_url="https://canonical.example")
    client = _whoami_client_with_real_auth(
        tenant=tenant,
        monkeypatch=monkeypatch,
        lookup_result=(str(key_tenant_id), "key-1", "STANDARD", False),
    )

    resp = client.get(
        "/recognition/tenant/whoami",
        headers={
            "Authorization": "Bearer good-key",
            "X-Tenant-ID": str(header_tenant_id),
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == str(key_tenant_id)
    assert body["site_url"] == "https://canonical.example"


def test_whoami_revoked_key_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _whoami_client_with_real_auth(
        tenant=None,
        monkeypatch=monkeypatch,
        lookup_side_effect=HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="api key revoked",
        ),
    )

    resp = client.get(
        "/recognition/tenant/whoami",
        headers={
            "Authorization": "Bearer revoked-key",
            "X-Tenant-ID": str(uuid.uuid4()),
        },
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "api key revoked"


def test_whoami_expired_key_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _whoami_client_with_real_auth(
        tenant=None,
        monkeypatch=monkeypatch,
        lookup_side_effect=HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="api key expired",
        ),
    )

    resp = client.get(
        "/recognition/tenant/whoami",
        headers={
            "Authorization": "Bearer expired-key",
            "X-Tenant-ID": str(uuid.uuid4()),
        },
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "api key expired"
