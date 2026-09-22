"""HTTP contract tests for POST /portal/onboarding/claim."""

from __future__ import annotations

import inspect
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from recognition.application.services.portal_identity_service import (
    PortalClaimOutcome,
    PortalIdentityClaimError,
    SqlAlchemyPortalIdentityService,
)
from recognition.domain.portal_contracts import PortalPrincipal
from recognition.interface_adapters.http.deps.portal_auth import require_verified_portal_identity
from recognition.interface_adapters.http.routers import portal

ALLOWED_ORIGIN = "https://app.altcontext.com"
ISSUER = "https://issuer.example.test"
SUBJECT = "subject-1"
EMAIL = "owner@example.test"
TENANT_ID = uuid4()


class _Claims:
    issuer = ISSUER
    subject = SUBJECT
    email = EMAIL
    email_verified = True


class _SessionStub:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")

    async def close(self) -> None:
        self.events.append("close")


class _ClaimService:
    def __init__(self, outcome: PortalClaimOutcome | BaseException) -> None:
        self.outcome = outcome
        self.claim_calls: list[dict[str, str | None]] = []
        self.resolve_calls: list[tuple[str, str]] = []
        self.claim_tenant_calls = 0
        self.polar_calls = 0

    async def claim_onboarding(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        invitation_token: str,
    ) -> PortalClaimOutcome:
        self.claim_calls.append(
            {
                "issuer": issuer,
                "subject": subject,
                "email": email,
                "invitation_token": invitation_token,
            }
        )
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    async def claim_tenant(self, **kwargs: object) -> PortalPrincipal:
        self.claim_tenant_calls += 1
        raise AssertionError("claim route must not use claim_tenant to infer replay")

    async def resolve_principal(self, issuer: str, subject: str) -> PortalPrincipal | None:
        self.resolve_calls.append((issuer, subject))
        raise AssertionError("claim route must not infer replay from an unlocked pre-read")


class _PolarSpy:
    def __init__(self) -> None:
        self.calls: list[object] = []

    async def create_checkout_session(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        raise AssertionError("claim must never call Polar")

    async def create_portal_session(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        raise AssertionError("claim must never call Polar")


async def _verified_identity() -> _Claims:
    return _Claims()


async def _missing_auth() -> _Claims:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "invalid_portal_authorization"},
    )


async def _unverified_email() -> _Claims:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "email_unverified"},
    )


async def _tenant_header_denied() -> _Claims:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "tenant_header_forbidden"},
    )


def _outcome(*, replayed: bool) -> PortalClaimOutcome:
    return PortalClaimOutcome(
        principal=PortalPrincipal(
            tenant_id=TENANT_ID,
            issuer=ISSUER,
            subject=SUBJECT,
            email=EMAIL,
        ),
        replayed=replayed,
    )


def _app(
    service: _ClaimService,
    *,
    authenticate: object = _verified_identity,
    session: _SessionStub | None = None,
    allowed_origins: tuple[str, ...] = (ALLOWED_ORIGIN,),
) -> tuple[FastAPI, _SessionStub]:
    application = FastAPI()
    application.include_router(portal.router)
    application.state.app_allowed_origins = allowed_origins
    application.state.billing_provider = _PolarSpy()
    portal_session = session or _SessionStub()
    application.dependency_overrides[require_verified_portal_identity] = authenticate

    async def override_service() -> _ClaimService:
        return service

    async def override_session() -> _SessionStub:
        return portal_session

    application.dependency_overrides[portal.get_portal_claim_service] = override_service
    application.dependency_overrides[portal.get_claim_session] = override_session
    return application, portal_session


def _post(
    client: TestClient,
    *,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> object:
    request_headers = {"Origin": ALLOWED_ORIGIN, "Authorization": "Bearer token"}
    if headers:
        request_headers.update(headers)
    return client.post(
        "/portal/onboarding/claim",
        json={"invitation_token": "inv_secret"} if body is None else body,
        headers=request_headers,
        params=params,
    )


def _code(response: object) -> str | None:
    payload = response.json().get("detail")
    if isinstance(payload, dict):
        code = payload.get("code")
        return str(code) if code is not None else None
    return None


def test_claim_onboarding_is_a_compatible_extension_of_claim_tenant() -> None:
    tenant_signature = inspect.signature(SqlAlchemyPortalIdentityService.claim_tenant)
    onboarding_signature = inspect.signature(SqlAlchemyPortalIdentityService.claim_onboarding)
    assert "tenant_id" not in tenant_signature.parameters
    assert tenant_signature.return_annotation in {PortalPrincipal, "PortalPrincipal"}
    assert onboarding_signature.return_annotation in {PortalClaimOutcome, "PortalClaimOutcome"}
    for name in ("issuer", "subject", "email", "invitation_token"):
        assert name in tenant_signature.parameters
        assert name in onboarding_signature.parameters


def test_first_successful_claim_is_201_and_replay_is_200() -> None:
    first_service = _ClaimService(_outcome(replayed=False))
    replay_service = _ClaimService(_outcome(replayed=True))
    first_app, first_session = _app(first_service)
    replay_app, replay_session = _app(replay_service)

    with TestClient(first_app) as first_client:
        created = _post(first_client)
    with TestClient(replay_app) as replay_client:
        replayed = _post(replay_client)

    assert created.status_code == 201
    assert created.json() == {
        "tenant_id": str(TENANT_ID),
        "issuer": ISSUER,
        "subject": SUBJECT,
        "email": EMAIL,
        "replayed": False,
    }
    assert replayed.status_code == 200
    assert replayed.json()["replayed"] is True
    assert replayed.json()["tenant_id"] == str(TENANT_ID)
    assert created.headers["cache-control"] == "no-store"
    assert replayed.headers["cache-control"] == "no-store"
    assert first_service.resolve_calls == []
    assert replay_service.resolve_calls == []
    assert first_service.claim_tenant_calls == 0
    assert replay_service.claim_tenant_calls == 0
    assert first_session.events == ["commit"]
    assert replay_session.events == ["commit"]


@pytest.mark.parametrize(
    ("exc", "status_code", "code"),
    [
        (PortalIdentityClaimError("not_admitted"), 403, "not_admitted"),
        (PortalIdentityClaimError("invitation_consumed"), 409, "invitation_consumed"),
        (PortalIdentityClaimError("identity_already_bound"), 409, "identity_already_bound"),
        (PortalIdentityClaimError("invalid_claim_request"), 422, "invalid_claim_request"),
        (PortalIdentityClaimError("portal_identity_unavailable"), 503, "portal_identity_unavailable"),
        (TimeoutError("db timed out"), 503, "portal_identity_unavailable"),
    ],
)
def test_claim_errors_map_exactly_to_spec(
    exc: BaseException,
    status_code: int,
    code: str,
) -> None:
    application, session = _app(_ClaimService(exc))

    with TestClient(application, raise_server_exceptions=False) as client:
        response = _post(client)

    assert response.status_code == status_code
    assert _code(response) == code
    assert response.headers["cache-control"] == "no-store"
    assert "rollback" in session.events
    assert "commit" not in session.events


def test_missing_and_mismatched_origin_are_csrf_denied() -> None:
    application, session = _app(_ClaimService(_outcome(replayed=False)))

    with TestClient(application) as client:
        missing = _post(client, headers={"Origin": ""})
        missing_header = client.post(
            "/portal/onboarding/claim",
            json={"invitation_token": "inv_secret"},
            headers={"Authorization": "Bearer token", "Referer": ALLOWED_ORIGIN},
        )
        mismatched = _post(client, headers={"Origin": "https://evil.example"})

    assert missing.status_code == 403
    assert _code(missing) == "csrf_origin_denied"
    assert missing_header.status_code == 403
    assert _code(missing_header) == "csrf_origin_denied"
    assert mismatched.status_code == 403
    assert _code(mismatched) == "csrf_origin_denied"
    assert "commit" not in session.events


def test_body_and_query_tenant_selection_are_forbidden() -> None:
    application, session = _app(_ClaimService(_outcome(replayed=False)))

    with TestClient(application) as client:
        body = _post(
            client,
            body={"invitation_token": "inv_secret", "tenant_id": str(uuid4())},
        )
        query = _post(client, params={"tenant_id": str(uuid4())})

    assert body.status_code == 403
    assert _code(body) == "tenant_header_forbidden"
    assert query.status_code == 403
    assert _code(query) == "tenant_header_forbidden"
    assert "commit" not in session.events


def test_tenant_header_is_rejected_by_verified_identity_dependency() -> None:
    application, _session = _app(
        _ClaimService(_outcome(replayed=False)),
        authenticate=_tenant_header_denied,
    )

    with TestClient(application) as client:
        response = _post(client, headers={"X-Tenant-ID": str(uuid4())})

    assert response.status_code == 403
    assert _code(response) == "tenant_header_forbidden"


def test_empty_token_is_invalid_claim_request() -> None:
    service = _ClaimService(_outcome(replayed=False))
    application, session = _app(service)

    with TestClient(application) as client:
        response = _post(client, body={"invitation_token": "   "})

    assert response.status_code == 422
    assert _code(response) == "invalid_claim_request"
    assert service.claim_calls == []
    assert "commit" not in session.events


def test_unverified_email_and_missing_bearer_use_pretenant_codes() -> None:
    unverified_app, _ = _app(_ClaimService(_outcome(replayed=False)), authenticate=_unverified_email)
    missing_app, _ = _app(_ClaimService(_outcome(replayed=False)), authenticate=_missing_auth)

    with TestClient(unverified_app) as client:
        unverified = _post(client)
    with TestClient(missing_app) as client:
        missing = _post(client)

    assert unverified.status_code == 403
    assert _code(unverified) == "email_unverified"
    assert missing.status_code == 401
    assert _code(missing) == "invalid_portal_authorization"


def test_claim_never_calls_polar_and_does_not_add_checkout_routes() -> None:
    service = _ClaimService(_outcome(replayed=False))
    application, _session = _app(service)
    polar = application.state.billing_provider
    route_paths = {getattr(route, "path", "") for route in portal.router.routes}

    with TestClient(application) as client:
        created = _post(client)
        checkout = client.post("/portal/billing/checkout", json={})
        manage = client.post("/portal/billing/manage", json={})

    assert created.status_code == 201
    assert polar.calls == []
    assert checkout.status_code == 404
    assert manage.status_code == 404
    assert "/portal/onboarding/claim" in route_paths
    assert "/portal/billing/checkout" not in route_paths
    source = inspect.getsource(portal.portal_onboarding_claim)
    assert "polar_provider" not in source
    assert "create_checkout_session" not in source
    assert "create_portal_session" not in source
