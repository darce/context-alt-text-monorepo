"""API tests for tenant provisioning discipline (E15-24 slice 2)."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
from recognition.tests.api.conftest import FakeSession


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
