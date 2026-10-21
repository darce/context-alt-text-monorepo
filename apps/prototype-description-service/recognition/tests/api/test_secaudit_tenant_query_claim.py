"""Tenant query selectors must pass the shared API-key authorization boundary."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from recognition.config.security import SecuritySettings
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps import auth
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.tests.api.conftest import FakeSession

TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CLUSTER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
ROUTES = [
    ("GET", "/media/identities"),
    ("GET", "/suggestions"),
    ("GET", f"/clusters/{CLUSTER}/merge-candidates"),
    ("GET", "/clusters/events"),
    ("POST", f"/clusters/{CLUSTER}/dismiss"),
]


@pytest.fixture
def client_and_audit(monkeypatch):
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def session_dep():
        yield FakeSession()

    async def lookup(api_key, settings, session):
        # Synthetic keys only; no auth store or external services are used.
        return (None if api_key == "admin-test" else TENANT_A, None, None, api_key == "admin-test")

    def downstream():
        # A distinct response proves auth permitted dependency resolution while
        # preventing database/service work in these boundary tests.
        raise HTTPException(status_code=409, detail="downstream reached")

    async def finite_events(request, tenant_id):
        yield ": test complete\n\n"

    from recognition.interface_adapters.http.routers import events, tenant

    monkeypatch.setattr(auth, "get_security_settings", lambda: SecuritySettings(auth_enabled=True))
    monkeypatch.setattr(auth, "_lookup_api_key", lookup)
    audit = Mock()
    monkeypatch.setattr(auth, "emit_auth_event", audit)
    async def tenant_record(session, tenant_id):
        return SimpleNamespace(id=tenant_id, site_url="https://example.invalid", display_name="Test tenant")

    monkeypatch.setattr(events, "_event_generator", finite_events)
    monkeypatch.setattr(tenant, "get_tenant_record", tenant_record)
    app.dependency_overrides[dependencies.get_session] = session_dep
    app.dependency_overrides[dependencies.get_optional_session] = session_dep
    app.dependency_overrides[enforce_rate_limit] = lambda: None
    for dependency in (
        dependencies.get_media_identity_service,
        dependencies.get_suggestion_service,
        dependencies.get_cluster_repository,
    ):
        app.dependency_overrides[dependency] = downstream
    with TestClient(app) as client:
        yield client, audit


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize("header_tenant", [None, TENANT_A])
def test_cross_tenant_query_denied(client_and_audit, method, path, header_tenant):
    client, audit = client_and_audit
    headers = {"Authorization": "Bearer tenant-test"}
    if header_tenant:
        headers["X-Tenant-ID"] = header_tenant
    response = client.request(method, "/recognition" + path, headers=headers, params={"tenant_id": TENANT_B})
    assert response.status_code == 403
    assert response.json() == {"detail": "tenant mismatch"}
    assert audit.call_count == 1
    assert audit.call_args.args == ("tenant_mismatch",)
    assert audit.call_args.kwargs["tenant_claim"] == TENANT_B


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize("admin", [False, True])
def test_matching_query_and_admin_reach_downstream(client_and_audit, method, path, admin):
    client, audit = client_and_audit
    response = client.request(
        method,
        "/recognition" + path,
        headers={"Authorization": "Bearer admin-test" if admin else "Bearer tenant-test"},
        params={"tenant_id": TENANT_B if admin else TENANT_A.upper()},
    )
    assert response.status_code == (200 if path == "/clusters/events" else 409)
    assert audit.call_count == 1
    assert audit.call_args.args == ("success",)


@pytest.mark.parametrize("values", [(TENANT_B, TENANT_A), (TENANT_A, TENANT_B)])
def test_duplicate_query_cannot_hide_mismatch(client_and_audit, values):
    client, audit = client_and_audit
    response = client.get(
        "/recognition/media/identities",
        headers={"Authorization": "Bearer tenant-test"},
        params=[("tenant_id", value) for value in values],
    )
    assert response.status_code == 403
    assert audit.call_count == 1
    assert audit.call_args.args == ("tenant_mismatch",)


def test_whoami_query_remains_key_only(client_and_audit):
    client, audit = client_and_audit
    response = client.get(
        "/recognition/tenant/whoami",
        headers={"Authorization": "Bearer tenant-test", "X-Tenant-ID": TENANT_B},
        params={"tenant_id": TENANT_B},
    )
    assert response.status_code == 200
    assert response.json()["tenant_id"] == TENANT_A
    assert audit.call_args.args == ("success",)
