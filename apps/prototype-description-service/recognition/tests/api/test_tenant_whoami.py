"""API tests for tenant whoami endpoint (E15-24 slice 2)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db.models import Tenant
from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
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
    app.dependency_overrides[require_auth] = lambda: auth
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
