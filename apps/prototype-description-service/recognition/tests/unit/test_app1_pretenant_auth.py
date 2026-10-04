"""Pre-tenant verified portal identity: JWT checks without a local tenant."""

from __future__ import annotations

import asyncio
import base64
from contextlib import AsyncExitStack
import inspect
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.dependencies.utils import get_dependant, solve_dependencies
from fastapi.testclient import TestClient

from recognition.domain.portal_contracts import PortalPrincipal
from recognition.interface_adapters.http.deps import portal_auth

ISSUER = "https://issuer.example.test"
JWKS_URL = "https://jwks.example.test/keys"
AUDIENCE = "clerk-instance-aud"
AUTHORIZED_PARTY = "https://app.altcontext.io"
EMAIL = "owner@example.test"
SUBJECT = "user_123"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _claims(
    *,
    now: datetime,
    expires_at: datetime | None = None,
    email: str | None = EMAIL,
    email_verified: bool = True,
    aud: str = AUDIENCE,
    azp: str | None = AUTHORIZED_PARTY,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "sub": SUBJECT,
        "aud": aud,
        "email_verified": email_verified,
        "exp": (expires_at or now + timedelta(minutes=5)).timestamp(),
    }
    if email is not None:
        payload["email"] = email
    if azp is not None:
        payload["azp"] = azp
    if extra:
        payload.update(extra)
    return payload


def _token(private_key: rsa.RSAPrivateKey, *, header: dict[str, Any], claims: dict[str, Any]) -> str:
    encoded_header = _b64(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_claims = _b64(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{encoded_header}.{encoded_claims}.{_b64(signature)}"


class _Clock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


class _Response:
    status_code = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class _HttpClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, float]] = []

    async def get(self, url: str, **kwargs: Any) -> _Response:
        timeout = kwargs["timeout"]
        self.calls.append((url, timeout))
        return _Response(self.payload)


class _DownHttpClient:
    async def get(self, url: str, **kwargs: Any) -> _Response:
        raise OSError("jwks unavailable")


class _IdentityService:
    def __init__(self, principal: PortalPrincipal | None) -> None:
        self.principal = principal
        self.calls: list[tuple[str, str]] = []

    async def resolve_principal(self, issuer: str, subject: str) -> PortalPrincipal | None:
        self.calls.append((issuer, subject))
        return self.principal


async def _pretenant_claims(
    token: str,
    verifier: portal_auth.PortalTokenVerifier,
    identity_service: _IdentityService,
) -> portal_auth.PortalTokenClaims:
    app = FastAPI()

    @app.get("/pretenant")
    async def pretenant(
        claims: portal_auth.PortalTokenClaims = Depends(portal_auth.require_verified_portal_identity),
    ) -> portal_auth.PortalTokenClaims:
        return claims

    async def provide_verifier() -> portal_auth.PortalTokenVerifier:
        return verifier

    async def provide_identity_service() -> _IdentityService:
        return identity_service

    app.dependency_overrides[portal_auth.get_portal_token_verifier] = provide_verifier
    app.dependency_overrides[portal_auth.get_portal_identity_service] = provide_identity_service
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/pretenant",
            "raw_path": b"/pretenant",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"authorization", f"Bearer {token}".encode("ascii"))],
            "client": ("test", 1234),
            "server": ("test", 80),
            "path_params": {},
            "app": app,
            "state": {},
        }
    )
    dependant = get_dependant(path="/pretenant", call=pretenant)
    async with AsyncExitStack() as stack:
        request.scope["fastapi_inner_astack"] = stack
        request.scope["fastapi_function_astack"] = stack
        solved = await solve_dependencies(
            request=request,
            dependant=dependant,
            body=None,
            background_tasks=None,
            response=Response(),
            dependency_overrides_provider=app,
            async_exit_stack=stack,
            embed_body_fields=False,
        )
        if solved.errors:
            raise AssertionError(f"pretenant dependency validation failed: {solved.errors}")
        return await pretenant(**solved.values)


@pytest.fixture
def key_material() -> tuple[rsa.RSAPrivateKey, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": "key-1",
        "alg": "RS256",
        "use": "sig",
        "n": _b64(public_key.n.to_bytes((public_key.n.bit_length() + 7) // 8, "big")),
        "e": _b64(public_key.e.to_bytes((public_key.e.bit_length() + 7) // 8, "big")),
    }
    return private_key, jwk


def _make_verifier(
    private_key: rsa.RSAPrivateKey,
    jwk: dict[str, Any],
    clock: _Clock,
    http_client: _HttpClient | _DownHttpClient | None = None,
) -> tuple[portal_auth.JwksPortalTokenVerifier, _HttpClient | _DownHttpClient]:
    client: _HttpClient | _DownHttpClient = http_client or _HttpClient({"keys": [jwk]})
    verifier = portal_auth.JwksPortalTokenVerifier(
        client,
        ISSUER,
        AUDIENCE,
        JWKS_URL,
        clock=clock,
        authorized_parties=(AUTHORIZED_PARTY,),
    )
    return verifier, client


def _header() -> dict[str, Any]:
    return {"alg": "RS256", "kid": "key-1", "typ": "JWT"}


def _principal() -> PortalPrincipal:
    return PortalPrincipal(
        tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
        issuer=ISSUER,
        subject=SUBJECT,
        email=EMAIL,
    )


def _code(exc: HTTPException) -> str | None:
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code")
        return str(code) if code is not None else None
    return None


def test_pretenant_dependency_does_not_take_an_identity_service() -> None:
    parameters = inspect.signature(portal_auth.require_verified_portal_identity).parameters
    assert "identity_service" not in parameters


def test_unbound_verified_identity_succeeds_pretenant_but_is_forbidden_on_tenant_route(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    verifier, _ = _make_verifier(private_key, jwk, _Clock(now))
    token = _token(private_key, header=_header(), claims=_claims(now=now))
    identity_service = _IdentityService(None)
    events: list[str] = []
    monkeypatch.setattr(portal_auth, "emit_auth_event", lambda outcome, **kwargs: events.append(outcome))

    claims = asyncio.run(_pretenant_claims(token, verifier, identity_service))

    assert isinstance(claims, portal_auth.PortalTokenClaims)
    assert claims.subject == SUBJECT
    assert claims.email == EMAIL
    assert claims.email_verified is True
    assert identity_service.calls == []
    assert "success" not in events

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            portal_auth.require_portal_principal(
                authorization=f"Bearer {token}",
                verifier=verifier,
                identity_service=identity_service,
            )
        )

    assert raised.value.status_code == 403
    assert raised.value.detail == "portal access denied"
    assert identity_service.calls == [(ISSUER, SUBJECT)]


@pytest.mark.asyncio
async def test_forged_signature_is_401(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    verifier, client = _make_verifier(private_key, jwk, _Clock(now))
    token = _token(private_key, header=_header(), claims=_claims(now=now))
    header, payload, signature = token.split(".")
    forged = f"{header}.{payload}.{signature[:-2]}AA"

    with pytest.raises(HTTPException) as raised:
        await portal_auth.require_verified_portal_identity(
            authorization=f"Bearer {forged}",
            verifier=verifier,
        )

    assert raised.value.status_code == 401
    assert _code(raised.value) == "invalid_portal_authorization"
    assert client.calls  # signature check still used the JWKS producer


@pytest.mark.asyncio
async def test_audience_mismatch_is_401(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    verifier, _ = _make_verifier(private_key, jwk, _Clock(now))
    token = _token(private_key, header=_header(), claims=_claims(now=now, aud="other-api"))

    with pytest.raises(HTTPException) as raised:
        await portal_auth.require_verified_portal_identity(
            authorization=f"Bearer {token}",
            verifier=verifier,
        )

    assert raised.value.status_code == 401
    assert _code(raised.value) == "invalid_portal_authorization"


@pytest.mark.asyncio
async def test_azp_mismatch_is_401(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    verifier, _ = _make_verifier(private_key, jwk, _Clock(now))
    token = _token(
        private_key,
        header=_header(),
        claims=_claims(now=now, azp="https://evil.example.test"),
    )

    with pytest.raises(HTTPException) as raised:
        await portal_auth.require_verified_portal_identity(
            authorization=f"Bearer {token}",
            verifier=verifier,
        )

    assert raised.value.status_code == 401
    assert _code(raised.value) == "invalid_portal_authorization"


@pytest.mark.asyncio
async def test_expired_token_is_401(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    verifier, _ = _make_verifier(private_key, jwk, _Clock(now))
    token = _token(
        private_key,
        header=_header(),
        claims=_claims(
            now=now,
            expires_at=now - portal_auth.PORTAL_CLOCK_SKEW - timedelta(seconds=1),
        ),
    )

    with pytest.raises(HTTPException) as raised:
        await portal_auth.require_verified_portal_identity(
            authorization=f"Bearer {token}",
            verifier=verifier,
        )

    assert raised.value.status_code == 401
    assert _code(raised.value) == "invalid_portal_authorization"


@pytest.mark.asyncio
async def test_whitespace_email_is_403(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    verifier, _ = _make_verifier(private_key, jwk, _Clock(now))
    token = _token(
        private_key,
        header=_header(),
        claims=_claims(now=now, email="   \t  ", email_verified=True),
    )

    with pytest.raises(HTTPException) as raised:
        await portal_auth.require_verified_portal_identity(
            authorization=f"Bearer {token}",
            verifier=verifier,
        )

    assert raised.value.status_code == 403
    assert _code(raised.value) == "email_unverified"


def test_unverified_email_is_403_without_identity_lookup(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    verifier, _ = _make_verifier(private_key, jwk, _Clock(now))
    token = _token(
        private_key,
        header=_header(),
        claims=_claims(now=now, email_verified=False),
    )
    identity_service = _IdentityService(_principal())

    with pytest.raises(HTTPException) as raised:
        asyncio.run(_pretenant_claims(token, verifier, identity_service))

    assert raised.value.status_code == 403
    assert _code(raised.value) == "email_unverified"
    assert identity_service.calls == []


@pytest.mark.asyncio
async def test_any_tenant_header_is_403(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    verifier, client = _make_verifier(private_key, jwk, _Clock(now))
    token = _token(private_key, header=_header(), claims=_claims(now=now))
    events: list[str] = []
    monkeypatch.setattr(portal_auth, "emit_auth_event", lambda outcome, **kwargs: events.append(outcome))

    with pytest.raises(HTTPException) as raised:
        await portal_auth.require_verified_portal_identity(
            authorization=f"Bearer {token}",
            x_tenant_id=str(uuid4()),
            verifier=verifier,
        )

    assert raised.value.status_code == 403
    assert _code(raised.value) == "tenant_header_forbidden"
    assert client.calls == []
    assert events == ["tenant_mismatch"]


@pytest.mark.asyncio
async def test_missing_and_malformed_bearer_are_401(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(portal_auth, "emit_auth_event", lambda outcome, **kwargs: events.append(outcome))
    verifier = object()

    with pytest.raises(HTTPException) as missing:
        await portal_auth.require_verified_portal_identity(authorization=None, verifier=verifier)
    with pytest.raises(HTTPException) as malformed:
        await portal_auth.require_verified_portal_identity(authorization="Basic abc", verifier=verifier)

    assert missing.value.status_code == 401
    assert malformed.value.status_code == 401
    assert _code(missing.value) == "invalid_portal_authorization"
    assert _code(malformed.value) == "invalid_portal_authorization"
    assert events == ["invalid_key", "invalid_key"]


@pytest.mark.asyncio
async def test_jwks_unavailable_is_503(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    verifier, _ = _make_verifier(private_key, jwk, _Clock(now), _DownHttpClient())
    token = _token(private_key, header=_header(), claims=_claims(now=now))

    with pytest.raises(HTTPException) as raised:
        await portal_auth.require_verified_portal_identity(
            authorization=f"Bearer {token}",
            verifier=verifier,
        )

    assert raised.value.status_code == 503
    assert _code(raised.value) == "portal_authentication_unavailable"


@pytest.mark.asyncio
async def test_missing_verifier_is_503() -> None:
    with pytest.raises(HTTPException) as raised:
        await portal_auth.require_verified_portal_identity(
            authorization="Bearer browser-token",
            verifier=object(),
        )

    assert raised.value.status_code == 503
    assert _code(raised.value) == "portal_authentication_unavailable"


def test_endpoint_dependency_smoke_accepts_unbound_verified_identity(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    verifier, _ = _make_verifier(private_key, jwk, _Clock(now))
    token = _token(private_key, header=_header(), claims=_claims(now=now))
    app = FastAPI()

    @app.get("/pretenant-smoke")
    async def pretenant_smoke(
        claims: portal_auth.PortalTokenClaims = Depends(portal_auth.require_verified_portal_identity),
    ) -> dict[str, str | None]:
        return {"subject": claims.subject, "email": claims.email}

    app.state.portal_token_verifier = verifier
    client = TestClient(app)

    ok = client.get("/pretenant-smoke", headers={"Authorization": f"Bearer {token}"})
    denied = client.get(
        "/pretenant-smoke",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": str(uuid4())},
    )
    missing_verifier_app = FastAPI()

    @missing_verifier_app.get("/pretenant-smoke")
    async def missing_verifier_smoke(
        claims: portal_auth.PortalTokenClaims = Depends(portal_auth.require_verified_portal_identity),
    ) -> dict[str, str]:
        return {"subject": claims.subject}

    missing = TestClient(missing_verifier_app).get(
        "/pretenant-smoke",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert ok.status_code == 200
    assert ok.json() == {"subject": SUBJECT, "email": EMAIL}
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "tenant_header_forbidden"
    assert missing.status_code == 503
