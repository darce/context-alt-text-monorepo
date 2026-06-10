"""API tests for tenant provisioning discipline (E15-24 slice 2)."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
from recognition.tests.api.conftest import FakeSession


def _postgres_session_with_missing_tenant() -> FakeSession:
    fake_session = FakeSession()
    fake_session.bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "postgresql"})()})()
    fake_session.queue_execute_result(scalar_one_or_none=None)
    return fake_session


def _admin_auth() -> AuthContext:
    # Admin keys carry no tenant_claim; they must NOT bypass the provisioning gate.
    return AuthContext(
        token="key",
        tenant_claim=None,
        api_key_id="admin-1",
        rate_limit_tier="default",
        is_admin=True,
        enabled=True,
    )


def test_analyze_unknown_tenant_returns_structured_403_without_provisioning(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    fake_session = FakeSession()
    fake_session.bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "postgresql"})()})()
    fake_session.queue_execute_result(scalar_one_or_none=None)

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_override():
        yield fake_session

    auth = AuthContext(
        token="key",
        tenant_claim=tenant_id,
        api_key_id="key-1",
        rate_limit_tier="default",
        is_admin=False,
        enabled=True,
    )

    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[require_auth] = lambda: auth

    client = TestClient(app)
    resp = client.post(
        "/recognition/analyze",
        json={"media_ids": [str(uuid.uuid4())], "tenant_id": tenant_id},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["code"] == "tenant_not_provisioned"
    assert detail["tenant_id"] == tenant_id
    assert detail["provisioning_path"] == "manage_api_keys"
    assert fake_session.added == []


def test_analyze_admin_key_unknown_tenant_still_403(monkeypatch) -> None:
    """An admin key (no tenant_claim) must not bypass the gate on a live postgres session."""
    tenant_id = str(uuid.uuid4())
    fake_session = _postgres_session_with_missing_tenant()

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_override():
        yield fake_session

    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[require_auth] = _admin_auth

    client = TestClient(app)
    resp = client.post(
        "/recognition/analyze",
        json={"media_ids": [str(uuid.uuid4())], "tenant_id": tenant_id},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "tenant_not_provisioned"
    assert fake_session.added == []


def test_multipart_analyze_admin_key_unknown_tenant_still_403(monkeypatch) -> None:
    """An admin key must not bypass the gate on /analyze/multipart either."""
    tenant_id = str(uuid.uuid4())
    fake_session = _postgres_session_with_missing_tenant()

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_override():
        yield fake_session

    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[require_auth] = _admin_auth

    client = TestClient(app)
    resp = client.post(
        "/recognition/analyze/multipart",
        files=[
            ("request", ("request.json", json.dumps({"tenant_id": tenant_id}), "application/json")),
            ("image_42", ("a.png", b"\x89PNG\r\n\x1a\nfake", "image/png")),
        ],
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "tenant_not_provisioned"
    assert fake_session.added == []


@pytest.mark.asyncio
async def test_build_cluster_service_unknown_tenant_raises_403() -> None:
    """The clustering builder leg of the gate (deps.services.build_cluster_service) must fail fast."""
    from recognition.interface_adapters.http.deps.services import build_cluster_service

    tenant_id = str(uuid.uuid4())
    fake_session = FakeSession()
    # sqlite dialect short-circuits set_tenant_context; require_tenant_record still runs unconditionally.
    fake_session.bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "sqlite"})()})()
    fake_session.queue_execute_result(scalar_one_or_none=None)

    with pytest.raises(HTTPException) as exc_info:
        await build_cluster_service(fake_session, tenant_id)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "tenant_not_provisioned"


def test_multipart_analyze_unknown_tenant_returns_structured_403_without_provisioning(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    fake_session = FakeSession()
    fake_session.bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "postgresql"})()})()
    fake_session.queue_execute_result(scalar_one_or_none=None)

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_override():
        yield fake_session

    auth = AuthContext(
        token="key",
        tenant_claim=tenant_id,
        api_key_id="key-1",
        rate_limit_tier="default",
        is_admin=False,
        enabled=True,
    )

    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[require_auth] = lambda: auth

    client = TestClient(app)
    resp = client.post(
        "/recognition/analyze/multipart",
        files=[
            (
                "request",
                ("request.json", json.dumps({"tenant_id": tenant_id}), "application/json"),
            ),
            ("image_42", ("a.png", b"\x89PNG\r\n\x1a\nfake", "image/png")),
        ],
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["code"] == "tenant_not_provisioned"
    assert detail["tenant_id"] == tenant_id
    assert detail["provisioning_path"] == "manage_api_keys"
    assert fake_session.added == []
