from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import HTTPException

from recognition.domain.portal_contracts import PortalPrincipal
from recognition.interface_adapters.http.deps import portal_auth


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _claims(*, now: datetime, expires_at: datetime | None = None, email_verified: bool = True) -> dict[str, Any]:
    return {
        "iss": "https://issuer.example.test",
        "sub": "user_123",
        "aud": "portal-api",
        "email": "owner@example.test",
        "email_verified": email_verified,
        "exp": (expires_at or now + timedelta(minutes=5)).timestamp(),
    }


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
    def __init__(self, payload: dict[str, Any], *, delay: float = 0) -> None:
        self.payload = payload
        self.delay = delay
        self.calls: list[tuple[str, float]] = []

    async def get(self, url: str, **kwargs: Any) -> _Response:
        timeout = kwargs["timeout"]
        self.calls.append((url, timeout))
        if self.delay:
            await asyncio.sleep(self.delay)
        return _Response(self.payload)


class _IdentityService:
    def __init__(self, principal: PortalPrincipal | None) -> None:
        self.principal = principal
        self.calls: list[tuple[str, str]] = []

    async def resolve_principal(self, issuer: str, subject: str) -> PortalPrincipal | None:
        self.calls.append((issuer, subject))
        return self.principal


class _Verifier:
    def __init__(self, claims: portal_auth.PortalTokenClaims) -> None:
        self.claims = claims
        self.calls: list[str] = []

    async def verify(self, token: str) -> portal_auth.PortalTokenClaims:
        self.calls.append(token)
        return self.claims


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
    http_client: _HttpClient | None = None,
) -> tuple[portal_auth.JwksPortalTokenVerifier, _HttpClient]:
    client = http_client or _HttpClient({"keys": [jwk]})
    verifier = portal_auth.JwksPortalTokenVerifier(
        client,
        "https://issuer.example.test",
        "portal-api",
        "https://jwks.example.test/keys",
        clock=clock,
    )
    return verifier, client


def _principal() -> PortalPrincipal:
    return PortalPrincipal(
        tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
        issuer="https://issuer.example.test",
        subject="user_123",
        email="owner@example.test",
    )


@pytest.mark.asyncio
async def test_valid_token_returns_identity_tenant_and_emits_success(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 9, 20, tzinfo=UTC)
    principal = _principal()
    verifier = _Verifier(
        portal_auth.PortalTokenClaims(
            issuer=principal.issuer,
            subject=principal.subject,
            email=principal.email,
            email_verified=True,
            expires_at=now + timedelta(minutes=5),
        )
    )
    identity_service = _IdentityService(principal)
    events: list[str] = []
    monkeypatch.setattr(
        portal_auth,
        "emit_auth_event",
        lambda outcome, **kwargs: events.append(outcome),
    )

    resolved = await portal_auth.require_portal_principal(
        authorization="Bearer browser-token",
        verifier=verifier,
        identity_service=identity_service,
    )

    assert resolved == principal
    assert resolved.tenant_id == principal.tenant_id
    assert identity_service.calls == [(principal.issuer, principal.subject)]
    assert events == ["success"]


@pytest.mark.asyncio
async def test_alg_none_is_rejected_before_identity_lookup(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    clock = _Clock(now)
    verifier, client = _make_verifier(private_key, jwk, clock)
    token = _token(private_key, header={"alg": "none", "kid": "key-1", "typ": "JWT"}, claims=_claims(now=now))

    with pytest.raises(portal_auth.PortalTokenVerificationError):
        await verifier.verify(token)

    assert client.calls == []


@pytest.mark.asyncio
async def test_unexpected_algorithm_is_rejected(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    verifier, client = _make_verifier(private_key, jwk, _Clock(now))
    token = _token(private_key, header={"alg": "HS256", "kid": "key-1", "typ": "JWT"}, claims=_claims(now=now))

    with pytest.raises(portal_auth.PortalTokenVerificationError):
        await verifier.verify(token)

    assert client.calls == []


@pytest.mark.asyncio
async def test_expiry_is_rejected_but_documented_clock_skew_is_accepted(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    clock = _Clock(now)
    verifier, _ = _make_verifier(private_key, jwk, clock)
    expired = _token(
        private_key,
        header={"alg": "RS256", "kid": "key-1", "typ": "JWT"},
        claims=_claims(now=now, expires_at=now - portal_auth.PORTAL_CLOCK_SKEW - timedelta(seconds=1)),
    )
    within_skew = _token(
        private_key,
        header={"alg": "RS256", "kid": "key-1", "typ": "JWT"},
        claims=_claims(now=now, expires_at=now - portal_auth.PORTAL_CLOCK_SKEW + timedelta(seconds=1)),
    )

    with pytest.raises(portal_auth.PortalTokenVerificationError):
        await verifier.verify(expired)
    claims = await verifier.verify(within_skew)

    assert claims.subject == "user_123"


@pytest.mark.asyncio
async def test_unverified_email_is_forbidden_without_identity_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 9, 20, tzinfo=UTC)
    verifier = _Verifier(
        portal_auth.PortalTokenClaims(
            issuer="https://issuer.example.test",
            subject="user_123",
            email="owner@example.test",
            email_verified=False,
            expires_at=now + timedelta(minutes=5),
        )
    )
    identity_service = _IdentityService(_principal())
    events: list[str] = []
    monkeypatch.setattr(portal_auth, "emit_auth_event", lambda outcome, **kwargs: events.append(outcome))

    with pytest.raises(HTTPException) as raised:
        await portal_auth.require_portal_principal(
            authorization="Bearer browser-token",
            verifier=verifier,
            identity_service=identity_service,
        )

    assert raised.value.status_code == 403
    assert raised.value.detail == "portal access denied"
    assert identity_service.calls == []
    assert events == ["invalid_key"]


@pytest.mark.asyncio
async def test_no_active_identity_returns_opaque_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 9, 20, tzinfo=UTC)
    claims = portal_auth.PortalTokenClaims(
        issuer="https://issuer.example.test",
        subject="user_123",
        email="owner@example.test",
        email_verified=True,
        expires_at=now + timedelta(minutes=5),
    )
    identity_service = _IdentityService(None)
    events: list[str] = []
    monkeypatch.setattr(portal_auth, "emit_auth_event", lambda outcome, **kwargs: events.append(outcome))

    with pytest.raises(HTTPException) as raised:
        await portal_auth.require_portal_principal(
            authorization="Bearer browser-token",
            verifier=_Verifier(claims),
            identity_service=identity_service,
        )

    assert raised.value.status_code == 403
    assert raised.value.detail == "portal access denied"
    assert "suspended" not in str(raised.value.detail)
    assert "never" not in str(raised.value.detail)
    assert events == ["invalid_key"]


@pytest.mark.asyncio
async def test_contradictory_tenant_header_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 9, 20, tzinfo=UTC)
    identity_service = _IdentityService(_principal())
    events: list[str] = []
    monkeypatch.setattr(portal_auth, "emit_auth_event", lambda outcome, **kwargs: events.append(outcome))
    verifier = _Verifier(
        portal_auth.PortalTokenClaims(
            issuer="https://issuer.example.test",
            subject="user_123",
            email="owner@example.test",
            email_verified=True,
            expires_at=now + timedelta(minutes=5),
        )
    )

    with pytest.raises(HTTPException) as raised:
        await portal_auth.require_portal_principal(
            authorization="Bearer browser-token",
            x_tenant_id=str(uuid4()),
            verifier=verifier,
            identity_service=identity_service,
        )

    assert raised.value.status_code == 403
    assert raised.value.detail == "portal access denied"
    assert identity_service.calls == [("https://issuer.example.test", "user_123")]
    assert events == ["tenant_mismatch"]


@pytest.mark.asyncio
async def test_jwks_fetch_uses_timeout_caches_and_refreshes_after_ttl(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    clock = _Clock(now)
    client = _HttpClient({"keys": [jwk]})
    verifier, _ = _make_verifier(private_key, jwk, clock, client)
    token = _token(
        private_key,
        header={"alg": "RS256", "kid": "key-1", "typ": "JWT"},
        claims=_claims(now=now),
    )

    await verifier.verify(token)
    await verifier.verify(token)
    assert len(client.calls) == 1
    assert client.calls[0][1] == portal_auth.JWKS_FETCH_TIMEOUT_SECONDS

    clock.current = now + portal_auth.JWKS_CACHE_TTL + timedelta(seconds=1)
    await verifier.verify(token)

    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_concurrent_cache_misses_share_one_jwks_fetch(
    key_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwk = key_material
    now = datetime(2026, 9, 20, tzinfo=UTC)
    client = _HttpClient({"keys": [jwk]}, delay=0.01)
    verifier, _ = _make_verifier(private_key, jwk, _Clock(now), client)
    tokens = [
        _token(
            private_key,
            header={"alg": "RS256", "kid": "key-1", "typ": "JWT"},
            claims=_claims(now=now),
        )
        for _ in range(8)
    ]

    claims = await asyncio.gather(*(verifier.verify(token) for token in tokens))

    assert len(claims) == 8
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_missing_credential_is_401_and_audited(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(portal_auth, "emit_auth_event", lambda outcome, **kwargs: events.append(outcome))

    with pytest.raises(HTTPException) as raised:
        await portal_auth.require_portal_principal(
            authorization=None,
            verifier=_Verifier(
                portal_auth.PortalTokenClaims(
                    issuer="issuer",
                    subject="subject",
                    email="owner@example.test",
                    email_verified=True,
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            ),
            identity_service=_IdentityService(None),
        )

    assert raised.value.status_code == 401
    assert events == ["invalid_key"]
