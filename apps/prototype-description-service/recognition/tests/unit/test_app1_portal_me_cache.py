"""GET /portal/me must not be stored by shared caches."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.domain.portal_contracts import PortalPrincipal
from recognition.interface_adapters.http.deps.portal_auth import (
    PortalTokenVerificationError,
    get_portal_identity_service,
    require_portal_principal,
)
from recognition.interface_adapters.http.routers import portal

ISSUER = "https://issuer.example.test"
SUBJECT = "subject-1"
EMAIL = "owner@example.test"


class _RejectingVerifier:
    async def verify(self, token: str) -> object:
        raise PortalTokenVerificationError("invalid portal authorization")


class _IdentityStub:
    async def resolve_principal(self, issuer: str, subject: str) -> None:
        return None


def test_portal_me_success_sets_no_store_and_keeps_json_contract() -> None:
    application = FastAPI()
    application.include_router(portal.router)
    principal = PortalPrincipal(tenant_id=uuid4(), issuer=ISSUER, subject=SUBJECT, email=EMAIL)

    async def override_principal() -> PortalPrincipal:
        return principal

    application.dependency_overrides[require_portal_principal] = override_principal

    with TestClient(application) as client:
        response = client.get("/portal/me", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "tenant_id": str(principal.tenant_id),
        "issuer": ISSUER,
        "subject": SUBJECT,
        "email": EMAIL,
    }


def test_portal_me_identity_errors_set_no_store_without_changing_status() -> None:
    application = FastAPI()
    application.include_router(portal.router)
    application.state.portal_token_verifier = _RejectingVerifier()
    application.dependency_overrides[get_portal_identity_service] = lambda: _IdentityStub()

    with TestClient(application) as client:
        missing = client.get("/portal/me")
        invalid = client.get("/portal/me", headers={"Authorization": "NotBearer"})
        rejected = client.get("/portal/me", headers={"Authorization": "Bearer token"})

    assert missing.status_code == 401
    assert missing.headers["cache-control"] == "no-store"
    assert missing.headers.get("www-authenticate") == "Bearer"
    assert missing.json() == {"detail": "portal authorization required"}

    assert invalid.status_code == 401
    assert invalid.headers["cache-control"] == "no-store"
    assert invalid.json() == {"detail": "invalid portal authorization"}

    assert rejected.status_code == 401
    assert rejected.headers["cache-control"] == "no-store"
    assert rejected.json() == {"detail": "invalid portal authorization"}


def test_portal_me_unavailable_identity_is_no_store() -> None:
    application = FastAPI()
    application.include_router(portal.router)

    with TestClient(application) as client:
        unavailable = client.get("/portal/me", headers={"Authorization": "Bearer token"})

    assert unavailable.status_code == 503
    assert unavailable.headers["cache-control"] == "no-store"
    assert unavailable.json() == {"detail": "portal authentication unavailable"}
