"""API tests for the tenant naming-agreement authority routes."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db.models import Tenant
from recognition.infrastructure.repositories.tenant_repository import SqlAlchemyTenantRepository
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.auth import AuthContext
from recognition.interface_adapters.http.routers import tenant as tenant_router
from recognition.tests.api.conftest import FakeSession


def _client(*, auth: AuthContext, tenant: Tenant | None) -> tuple[TestClient, FakeSession]:
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    session = FakeSession()
    if tenant is not None:
        session.set_get_result(model_class=Tenant, pk=tenant.id, value=tenant)

    async def _session_override():
        yield session

    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[dependencies.require_auth] = lambda: auth
    app.dependency_overrides[dependencies.require_auth_key_only] = lambda: auth
    app.dependency_overrides[dependencies.require_write_access] = lambda: auth
    return TestClient(app), session


def _auth(tenant_id: uuid.UUID, *, tier: str = "STANDARD") -> AuthContext:
    return AuthContext(
        token="tenant-key",
        tenant_claim=str(tenant_id),
        api_key_id="key-1",
        rate_limit_tier=tier,
        enabled=True,
    )


def test_get_naming_agreement_is_scoped_to_the_calling_key_tenant() -> None:
    tenant_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, site_url="https://tenant.example", naming_agreement_enabled=True)
    client, _ = _client(auth=_auth(tenant_id), tenant=tenant)

    response = client.get("/recognition/tenant/naming-agreement")

    assert response.status_code == 200
    assert response.json() == {"enabled": True}


def test_put_naming_agreement_requires_write_access_and_updates_the_tenant() -> None:
    tenant_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, site_url="https://tenant.example", naming_agreement_enabled=True)
    client, session = _client(auth=_auth(tenant_id), tenant=tenant)

    response = client.put("/recognition/tenant/naming-agreement", json={"enabled": False})

    assert response.status_code == 200
    assert response.json() == {"enabled": False}
    assert tenant.naming_agreement_enabled is False
    assert session.flush_calls == 1


def test_naming_agreement_rejects_demo_tier() -> None:
    tenant_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, site_url="https://demo.example")
    client, _ = _client(auth=_auth(tenant_id, tier="DEMO"), tenant=tenant)

    response = client.get("/recognition/tenant/naming-agreement")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tenant_repository_updates_naming_agreement() -> None:
    tenant_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, site_url="https://tenant.example", naming_agreement_enabled=True)
    session = FakeSession()
    session.set_get_result(model_class=Tenant, pk=tenant_id, value=tenant)

    updated = await SqlAlchemyTenantRepository(session).update_naming_agreement_enabled(tenant_id, False)

    assert updated is tenant
    assert tenant.naming_agreement_enabled is False
    assert session.flush_calls == 1

