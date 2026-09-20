"""FastAPI authentication dependency for portal browser sessions."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import inspect
import json
import logging
import math
import os
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlparse

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.portal_identity_service import SqlAlchemyPortalIdentityService
from recognition.domain.portal_contracts import PortalIdentityService, PortalPrincipal
from recognition.interface_adapters.http.deps.session import get_optional_session
from recognition.interface_adapters.http.deps.tenant_common import normalize_tenant_id
from recognition.observability.auth_audit import emit_auth_event

logger = logging.getLogger(__name__)

PORTAL_CLOCK_SKEW_SECONDS = 30.0
PORTAL_CLOCK_SKEW = timedelta(seconds=PORTAL_CLOCK_SKEW_SECONDS)
JWKS_FETCH_TIMEOUT_SECONDS = 2.0
JWKS_CACHE_TTL_SECONDS = 300.0
JWKS_CACHE_TTL = timedelta(seconds=JWKS_CACHE_TTL_SECONDS)
JWKS_MAX_RESPONSE_BYTES = 256 * 1024
JWKS_MAX_KEYS = 64

CLOCK_SKEW = PORTAL_CLOCK_SKEW
JWKS_FETCH_TIMEOUT_S = JWKS_FETCH_TIMEOUT_SECONDS
JWKS_CACHE_TTL_S = JWKS_CACHE_TTL_SECONDS
MAX_JWKS_RESPONSE_BYTES = JWKS_MAX_RESPONSE_BYTES

_RSA_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
_AuthAuditOutcome = Literal["success", "invalid_key", "tenant_mismatch"]
_Clock = Callable[[], datetime | float | int]


@dataclass(frozen=True, slots=True)
class PortalTokenClaims:
    """Claims trusted only after a complete signature and claim validation."""

    issuer: str
    subject: str
    email: str | None
    email_verified: bool
    expires_at: datetime


class PortalTokenVerifier(Protocol):
    """Verify one bearer token and return only trusted portal claims."""

    async def verify(self, token: str) -> PortalTokenClaims:
        """Verify a token before any local identity lookup is attempted."""
        ...


class AsyncHttpClient(Protocol):
    """Small injected HTTP-client surface used by the JWKS verifier."""

    def get(self, url: str, *, timeout: float) -> Awaitable[Any]:
        """Issue one bounded GET request."""
        ...


class PortalTokenVerificationError(ValueError):
    """The supplied token is not a valid portal token."""


class PortalJwksUnavailableError(RuntimeError):
    """The configured JWKS endpoint could not be read within its bounds."""


PortalJwksUnavailable = PortalJwksUnavailableError


def _as_timedelta(value: timedelta | float | int, *, name: str) -> timedelta:
    if isinstance(value, timedelta):
        result = value
    elif isinstance(value, (float, int)) and not isinstance(value, bool):
        result = timedelta(seconds=float(value))
    else:
        raise ValueError(f"{name} must be a timedelta or seconds")
    if result <= timedelta(0):
        raise ValueError(f"{name} must be positive")
    return result


def _normalize_values(value: str | Collection[str], *, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value.strip(),)
    else:
        values = tuple(item.strip() for item in value if isinstance(item, str))
    normalized = tuple(item for item in values if item)
    if not normalized:
        raise ValueError(f"{name} must contain at least one value")
    return normalized


def _coerce_datetime(value: datetime | float | int) -> datetime:
    if isinstance(value, datetime):
        current = value
        if current.tzinfo is None:
            return current.replace(tzinfo=UTC)
        return current.astimezone(UTC)
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise ValueError("clock value must be finite")
        return datetime.fromtimestamp(float(value), tz=UTC)
    raise ValueError("clock must return a datetime or timestamp")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PortalAuthSettings:
    """Explicit portal verifier settings, following the service env pattern."""

    issuer: str
    jwks_url: str
    audience: str | Collection[str]
    authorized_parties: Collection[str] | None = None
    allowed_algorithms: Collection[str] = ("RS256",)
    clock_skew: timedelta | float = PORTAL_CLOCK_SKEW
    jwks_cache_ttl: timedelta | float = JWKS_CACHE_TTL
    jwks_timeout_seconds: float = JWKS_FETCH_TIMEOUT_SECONDS
    jwks_max_response_bytes: int = JWKS_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        issuer = self.issuer.strip() if isinstance(self.issuer, str) else ""
        jwks_url = self.jwks_url.strip() if isinstance(self.jwks_url, str) else ""
        if not issuer or not jwks_url:
            raise ValueError("portal issuer and JWKS URL are required")
        parsed_url = urlparse(jwks_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("portal JWKS URL must be an absolute HTTP URL")
        object.__setattr__(self, "issuer", issuer)
        object.__setattr__(self, "jwks_url", jwks_url)
        object.__setattr__(self, "audience", _normalize_values(self.audience, name="audience"))
        if self.authorized_parties is not None:
            object.__setattr__(
                self,
                "authorized_parties",
                _normalize_values(self.authorized_parties, name="authorized_parties"),
            )
        object.__setattr__(
            self, "allowed_algorithms", _normalize_values(self.allowed_algorithms, name="allowed_algorithms")
        )
        object.__setattr__(self, "clock_skew", _as_timedelta(self.clock_skew, name="clock_skew"))
        object.__setattr__(self, "jwks_cache_ttl", _as_timedelta(self.jwks_cache_ttl, name="jwks_cache_ttl"))
        if not isinstance(self.jwks_timeout_seconds, (float, int)) or isinstance(self.jwks_timeout_seconds, bool):
            raise ValueError("jwks_timeout_seconds must be positive")
        if self.jwks_timeout_seconds <= 0:
            raise ValueError("jwks_timeout_seconds must be positive")
        if not isinstance(self.jwks_max_response_bytes, int) or self.jwks_max_response_bytes <= 0:
            raise ValueError("jwks_max_response_bytes must be positive")

    @classmethod
    def from_env(cls) -> PortalAuthSettings:
        """Load operator-supplied settings without inventing a provider domain."""
        issuer = os.getenv("ACX_CLERK_ISSUER", "").strip()
        jwks_url = os.getenv("ACX_CLERK_JWKS_URL", "").strip()
        audience_raw = os.getenv("ACX_CLERK_AUTHORIZED_PARTIES", "")
        audience = tuple(part.strip() for part in audience_raw.split(",") if part.strip())
        if not issuer or not jwks_url or not audience:
            raise ValueError("portal authentication settings are incomplete")
        return cls(issuer=issuer, jwks_url=jwks_url, audience=audience)


@dataclass(frozen=True, slots=True)
class _RsaJwk:
    kid: str
    modulus: int
    exponent: int
    algorithm: str | None


def _decode_base64url(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid base64url value")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid base64url value") from exc


def _decode_base64url_int(value: str) -> int:
    decoded = _decode_base64url(value)
    if not decoded:
        raise ValueError("invalid integer value")
    result = int.from_bytes(decoded, byteorder="big", signed=False)
    if result <= 0:
        raise ValueError("invalid integer value")
    return result


def _decode_json_segment(segment: str) -> Mapping[str, Any]:
    try:
        decoded = _decode_base64url(segment)
        parsed = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PortalTokenVerificationError("invalid portal token") from exc
    if not isinstance(parsed, dict):
        raise PortalTokenVerificationError("invalid portal token")
    return cast(Mapping[str, Any], parsed)


def _timestamp_datetime(value: Any, *, name: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise PortalTokenVerificationError("invalid portal token")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise PortalTokenVerificationError("invalid portal token")
    try:
        return datetime.fromtimestamp(numeric, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise PortalTokenVerificationError("invalid portal token") from exc


class JwksPortalTokenVerifier:
    """Verify RS256 JWTs against a bounded, refreshable injected JWKS client."""

    def __init__(
        self,
        http_client: AsyncHttpClient,
        issuer: str,
        audience: str | Collection[str],
        jwks_url: str,
        *,
        clock: _Clock = _utcnow,
        allowed_algorithms: Collection[str] = ("RS256",),
        authorized_parties: Collection[str] | None = None,
        clock_skew: timedelta | float = PORTAL_CLOCK_SKEW,
        cache_ttl: timedelta | float = JWKS_CACHE_TTL,
        jwks_cache_ttl: timedelta | float | None = None,
        timeout_s: float = JWKS_FETCH_TIMEOUT_SECONDS,
        jwks_timeout_seconds: float | None = None,
        max_response_bytes: int = JWKS_MAX_RESPONSE_BYTES,
    ) -> None:
        if not isinstance(issuer, str) or not issuer.strip():
            raise ValueError("issuer is required")
        if not isinstance(jwks_url, str) or not jwks_url.strip():
            raise ValueError("JWKS URL is required")
        parsed_url = urlparse(jwks_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("JWKS URL must be an absolute HTTP URL")
        if not callable(clock):
            raise ValueError("clock must be callable")
        selected_ttl = cache_ttl if jwks_cache_ttl is None else jwks_cache_ttl
        selected_timeout = timeout_s if jwks_timeout_seconds is None else jwks_timeout_seconds
        if (
            not isinstance(selected_timeout, (float, int))
            or isinstance(selected_timeout, bool)
            or selected_timeout <= 0
        ):
            raise ValueError("JWKS timeout must be positive")
        if not isinstance(max_response_bytes, int) or max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._http_client = http_client
        self._issuer = issuer.strip()
        self._audience = _normalize_values(audience, name="audience")
        self._jwks_url = jwks_url.strip()
        self._clock = clock
        self._allowed_algorithms = frozenset(_normalize_values(allowed_algorithms, name="allowed_algorithms"))
        self._authorized_parties = (
            frozenset(_normalize_values(authorized_parties, name="authorized_parties"))
            if authorized_parties is not None
            else None
        )
        self._clock_skew = _as_timedelta(clock_skew, name="clock_skew")
        self._cache_ttl = _as_timedelta(selected_ttl, name="cache_ttl")
        self._timeout_s = float(selected_timeout)
        self._max_response_bytes = max_response_bytes
        self._jwks: dict[str, _RsaJwk] = {}
        self._missing_kids: set[str] = set()
        self._cache_expires_at: datetime | None = None
        self._refresh_lock = asyncio.Lock()

    async def verify(self, token: str) -> PortalTokenClaims:
        """Verify token bytes and trusted claims without exposing token material."""
        if not isinstance(token, str) or not token.strip():
            raise PortalTokenVerificationError("invalid portal token")
        try:
            parts = token.split(".")
            if len(parts) != 3 or any(not part for part in parts):
                raise PortalTokenVerificationError("invalid portal token")
            header_segment, payload_segment, signature_segment = parts
            header = _decode_json_segment(header_segment)
            algorithm = header.get("alg")
            kid = header.get("kid")
            if not isinstance(algorithm, str) or algorithm not in self._allowed_algorithms or algorithm == "none":
                raise PortalTokenVerificationError("invalid portal token")
            if not isinstance(kid, str) or not kid:
                raise PortalTokenVerificationError("invalid portal token")
            signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
            signature = _decode_base64url(signature_segment)
            key = await self._key_for(kid)
            if key.algorithm is not None and key.algorithm != algorithm:
                raise PortalTokenVerificationError("invalid portal token")
            if not self._verify_signature(algorithm, key, signing_input, signature):
                raise PortalTokenVerificationError("invalid portal token")
            payload = _decode_json_segment(payload_segment)
            return self._claims_from_verified_payload(payload)
        except PortalTokenVerificationError:
            raise
        except PortalJwksUnavailable:
            raise
        except (UnicodeEncodeError, TypeError, ValueError, OverflowError) as exc:
            raise PortalTokenVerificationError("invalid portal token") from exc

    async def _key_for(self, kid: str) -> _RsaJwk:
        now = _coerce_datetime(self._clock())
        cached = self._jwks.get(kid)
        cache_is_fresh = self._cache_expires_at is not None and now < self._cache_expires_at
        if cache_is_fresh:
            if cached is not None:
                return cached
            if kid in self._missing_kids:
                raise PortalTokenVerificationError("invalid portal token")
        async with self._refresh_lock:
            now = _coerce_datetime(self._clock())
            cached = self._jwks.get(kid)
            cache_is_fresh = self._cache_expires_at is not None and now < self._cache_expires_at
            if cache_is_fresh:
                if cached is not None:
                    return cached
                if kid in self._missing_kids:
                    raise PortalTokenVerificationError("invalid portal token")
            try:
                refreshed = await asyncio.wait_for(self._fetch_jwks(), timeout=self._timeout_s)
            except TimeoutError as exc:
                if cached is not None:
                    return cached
                raise PortalJwksUnavailable("portal JWKS unavailable") from exc
            except PortalJwksUnavailable:
                if cached is not None:
                    return cached
                raise
            self._jwks = refreshed
            self._missing_kids.clear()
            self._cache_expires_at = _coerce_datetime(self._clock()) + self._cache_ttl
            key = self._jwks.get(kid)
            if key is None:
                self._missing_kids.add(kid)
                raise PortalTokenVerificationError("invalid portal token")
            return key

    async def _fetch_jwks(self) -> dict[str, _RsaJwk]:
        try:
            stream = getattr(self._http_client, "stream", None)
            if callable(stream):
                candidate = stream("GET", self._jwks_url, timeout=self._timeout_s)
                if inspect.isawaitable(candidate):
                    candidate = await candidate
                if hasattr(candidate, "__aenter__"):
                    async with candidate as response:
                        payload = await self._read_response(response)
                    return self._parse_jwks(payload)
            response = await self._http_client.get(self._jwks_url, timeout=self._timeout_s)
            payload = await self._read_response(response)
            return self._parse_jwks(payload)
        except PortalJwksUnavailable:
            raise
        except (TimeoutError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PortalJwksUnavailable("portal JWKS unavailable") from exc
        except Exception as exc:
            raise PortalJwksUnavailable("portal JWKS unavailable") from exc

    async def _read_response(self, response: Any) -> Mapping[str, Any]:
        status_code = getattr(response, "status_code", 200)
        if not isinstance(status_code, int) or not 200 <= status_code < 300:
            raise PortalJwksUnavailable("portal JWKS unavailable")
        raise_for_status = getattr(response, "raise_for_status", None)
        if callable(raise_for_status):
            result = raise_for_status()
            if inspect.isawaitable(result):
                await result

        aiter_bytes = getattr(response, "aiter_bytes", None)
        if callable(aiter_bytes):
            body = bytearray()
            async for chunk in aiter_bytes():
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise PortalJwksUnavailable("portal JWKS unavailable")
                body.extend(chunk)
                if len(body) > self._max_response_bytes:
                    raise PortalJwksUnavailable("portal JWKS unavailable")
            return self._parse_json_bytes(bytes(body))

        content = getattr(response, "content", None)
        if content is not None:
            if isinstance(content, str):
                content = content.encode("utf-8")
            if isinstance(content, (bytes, bytearray, memoryview)):
                if len(content) > self._max_response_bytes:
                    raise PortalJwksUnavailable("portal JWKS unavailable")
                return self._parse_json_bytes(bytes(content))

        headers = getattr(response, "headers", {})
        content_length = headers.get("content-length") if hasattr(headers, "get") else None
        if content_length is not None:
            try:
                if int(content_length) > self._max_response_bytes:
                    raise PortalJwksUnavailable("portal JWKS unavailable")
            except (TypeError, ValueError) as exc:
                raise PortalJwksUnavailable("portal JWKS unavailable") from exc
        response_json = getattr(response, "json", None)
        if not callable(response_json):
            raise PortalJwksUnavailable("portal JWKS unavailable")
        parsed = response_json()
        if inspect.isawaitable(parsed):
            parsed = await parsed
        if not isinstance(parsed, Mapping):
            raise PortalJwksUnavailable("portal JWKS unavailable")
        try:
            if len(json.dumps(parsed, separators=(",", ":")).encode("utf-8")) > self._max_response_bytes:
                raise PortalJwksUnavailable("portal JWKS unavailable")
        except (TypeError, ValueError, OverflowError) as exc:
            raise PortalJwksUnavailable("portal JWKS unavailable") from exc
        return cast(Mapping[str, Any], parsed)

    @staticmethod
    def _parse_json_bytes(body: bytes) -> Mapping[str, Any]:
        try:
            parsed = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise PortalJwksUnavailable("portal JWKS unavailable") from exc
        if not isinstance(parsed, Mapping):
            raise PortalJwksUnavailable("portal JWKS unavailable")
        return cast(Mapping[str, Any], parsed)

    def _parse_jwks(self, payload: Mapping[str, Any]) -> dict[str, _RsaJwk]:
        raw_keys = payload.get("keys")
        if not isinstance(raw_keys, list) or len(raw_keys) > JWKS_MAX_KEYS:
            raise PortalJwksUnavailable("portal JWKS unavailable")
        parsed: dict[str, _RsaJwk] = {}
        for raw_key in raw_keys:
            if not isinstance(raw_key, Mapping):
                raise PortalJwksUnavailable("portal JWKS unavailable")
            if raw_key.get("kty") != "RSA":
                continue
            kid = raw_key.get("kid")
            if not isinstance(kid, str) or not kid:
                raise PortalJwksUnavailable("portal JWKS unavailable")
            if raw_key.get("use") not in (None, "sig"):
                continue
            key_ops = raw_key.get("key_ops")
            if key_ops is not None and (not isinstance(key_ops, list) or "verify" not in key_ops):
                continue
            algorithm = raw_key.get("alg")
            if algorithm is not None and not isinstance(algorithm, str):
                raise PortalJwksUnavailable("portal JWKS unavailable")
            if algorithm is not None and algorithm not in self._allowed_algorithms:
                continue
            try:
                key = _RsaJwk(
                    kid=kid,
                    modulus=_decode_base64url_int(cast(str, raw_key.get("n"))),
                    exponent=_decode_base64url_int(cast(str, raw_key.get("e"))),
                    algorithm=algorithm,
                )
            except (TypeError, ValueError) as exc:
                raise PortalJwksUnavailable("portal JWKS unavailable") from exc
            if kid in parsed:
                raise PortalJwksUnavailable("portal JWKS unavailable")
            parsed[kid] = key
        return parsed

    @staticmethod
    def _verify_signature(algorithm: str, key: _RsaJwk, signing_input: bytes, signature: bytes) -> bool:
        if algorithm != "RS256":
            return False
        key_size = (key.modulus.bit_length() + 7) // 8
        if len(signature) != key_size:
            return False
        signature_value = int.from_bytes(signature, byteorder="big")
        if signature_value >= key.modulus:
            return False
        encoded_message = pow(signature_value, key.exponent, key.modulus).to_bytes(
            key_size,
            byteorder="big",
        )
        digest_info = _RSA_SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(signing_input).digest()
        padding_length = key_size - len(digest_info) - 3
        if padding_length < 8:
            return False
        expected = b"\x00\x01" + b"\xff" * padding_length + b"\x00" + digest_info
        return hmac.compare_digest(encoded_message, expected)

    def _claims_from_verified_payload(self, payload: Mapping[str, Any]) -> PortalTokenClaims:
        now = _coerce_datetime(self._clock())
        issuer = payload.get("iss")
        subject = payload.get("sub")
        if not isinstance(issuer, str) or issuer != self._issuer:
            raise PortalTokenVerificationError("invalid portal token")
        if not isinstance(subject, str) or not subject.strip():
            raise PortalTokenVerificationError("invalid portal token")
        expires_at = _timestamp_datetime(payload.get("exp"), name="exp")
        if now > expires_at + self._clock_skew:
            raise PortalTokenVerificationError("invalid portal token")
        not_before = payload.get("nbf")
        if not_before is not None and now + self._clock_skew < _timestamp_datetime(not_before, name="nbf"):
            raise PortalTokenVerificationError("invalid portal token")
        audience = payload.get("aud")
        if isinstance(audience, str):
            token_audience = {audience}
        elif isinstance(audience, list) and all(isinstance(item, str) for item in audience):
            token_audience = set(audience)
        else:
            raise PortalTokenVerificationError("invalid portal token")
        if not token_audience.intersection(self._audience):
            raise PortalTokenVerificationError("invalid portal token")
        if self._authorized_parties is not None:
            authorized_party = payload.get("azp")
            if not isinstance(authorized_party, str) or authorized_party not in self._authorized_parties:
                raise PortalTokenVerificationError("invalid portal token")
        email = payload.get("email")
        if email is not None and (not isinstance(email, str) or not email.strip()):
            email = None
        email_verified = payload.get("email_verified")
        if not isinstance(email_verified, bool):
            email_verified = False
        return PortalTokenClaims(
            issuer=issuer,
            subject=subject,
            email=email,
            email_verified=email_verified,
            expires_at=expires_at,
        )


JWKSBackedPortalTokenVerifier = JwksPortalTokenVerifier
JWKSPortalTokenVerifier = JwksPortalTokenVerifier
ClerkPortalTokenVerifier = JwksPortalTokenVerifier


def build_portal_token_verifier(
    http_client: AsyncHttpClient,
    settings: PortalAuthSettings | None = None,
    *,
    clock: _Clock = _utcnow,
) -> JwksPortalTokenVerifier:
    """Construct a verifier from injected transport and explicit settings."""
    resolved = settings or PortalAuthSettings.from_env()
    return JwksPortalTokenVerifier(
        http_client,
        resolved.issuer,
        resolved.audience,
        resolved.jwks_url,
        clock=clock,
        allowed_algorithms=resolved.allowed_algorithms,
        authorized_parties=resolved.authorized_parties,
        clock_skew=resolved.clock_skew,
        cache_ttl=resolved.jwks_cache_ttl,
        timeout_s=resolved.jwks_timeout_seconds,
        max_response_bytes=resolved.jwks_max_response_bytes,
    )


def get_portal_token_verifier(request: Request) -> PortalTokenVerifier:
    """Resolve the app-owned verifier without constructing a client at import time."""
    state = getattr(getattr(request, "app", None), "state", None)
    verifier = getattr(state, "portal_token_verifier", None)
    if verifier is None or not callable(getattr(verifier, "verify", None)):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="portal authentication unavailable",
        )
    return cast(PortalTokenVerifier, verifier)


def get_portal_identity_service(
    session: AsyncSession | None = Depends(get_optional_session),
) -> PortalIdentityService:
    """Build the identity service on the request-scoped session dependency."""
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="portal identity unavailable",
        )
    return SqlAlchemyPortalIdentityService(session=session)


def _emit_portal_auth_event(outcome: _AuthAuditOutcome) -> None:
    try:
        emit_auth_event(
            outcome,
            api_key_id=None,
            key_hash=None,
            tenant_claim=None,
            trace_id=None,
        )
    except Exception:
        logger.error("portal auth audit emission failed", extra={"outcome": outcome})


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization or not isinstance(authorization, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="portal authorization required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    pieces = authorization.split()
    if len(pieces) != 2 or pieces[0].lower() != "bearer" or not pieces[1]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid portal authorization",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return pieces[1]


async def _require_portal_principal_impl(
    *,
    token: str,
    x_tenant_id: str | None,
    verifier: PortalTokenVerifier,
    identity_service: PortalIdentityService,
) -> PortalPrincipal:
    try:
        claims = await verifier.verify(token)
    except PortalJwksUnavailable:
        _emit_portal_auth_event("invalid_key")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="portal authentication temporarily unavailable",
        ) from None
    except Exception:
        _emit_portal_auth_event("invalid_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid portal authorization",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    if not claims.email_verified or not claims.email:
        _emit_portal_auth_event("invalid_key")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="portal access denied")

    try:
        principal = await identity_service.resolve_principal(claims.issuer, claims.subject)
    except Exception:
        _emit_portal_auth_event("invalid_key")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="portal identity unavailable",
        ) from None
    if principal is None:
        _emit_portal_auth_event("invalid_key")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="portal access denied")

    if x_tenant_id is not None:
        try:
            requested_tenant_id = normalize_tenant_id(x_tenant_id)
        except HTTPException:
            _emit_portal_auth_event("tenant_mismatch")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="portal access denied") from None
        if requested_tenant_id != str(principal.tenant_id):
            _emit_portal_auth_event("tenant_mismatch")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="portal access denied")

    _emit_portal_auth_event("success")
    return principal


async def require_portal_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    verifier: PortalTokenVerifier = Depends(get_portal_token_verifier),
    identity_service: PortalIdentityService = Depends(get_portal_identity_service),
) -> PortalPrincipal:
    """Authenticate a portal bearer token and bind it to its local tenant identity."""
    try:
        token = _extract_bearer_token(authorization)
    except HTTPException:
        _emit_portal_auth_event("invalid_key")
        raise
    if not callable(getattr(verifier, "verify", None)):
        _emit_portal_auth_event("invalid_key")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="portal authentication unavailable",
        )
    return await _require_portal_principal_impl(
        token=token,
        x_tenant_id=x_tenant_id if isinstance(x_tenant_id, str) else None,
        verifier=verifier,
        identity_service=identity_service,
    )


__all__ = [
    "AsyncHttpClient",
    "CLOCK_SKEW",
    "ClerkPortalTokenVerifier",
    "JWKSPortalTokenVerifier",
    "JWKSBackedPortalTokenVerifier",
    "JWKS_CACHE_TTL",
    "JWKS_CACHE_TTL_SECONDS",
    "JWKS_FETCH_TIMEOUT_S",
    "JWKS_FETCH_TIMEOUT_SECONDS",
    "JWKS_MAX_KEYS",
    "JWKS_MAX_RESPONSE_BYTES",
    "JwksPortalTokenVerifier",
    "MAX_JWKS_RESPONSE_BYTES",
    "PORTAL_CLOCK_SKEW",
    "PORTAL_CLOCK_SKEW_SECONDS",
    "PortalAuthSettings",
    "PortalJwksUnavailable",
    "PortalJwksUnavailableError",
    "PortalTokenClaims",
    "PortalTokenVerificationError",
    "PortalTokenVerifier",
    "build_portal_token_verifier",
    "get_portal_identity_service",
    "get_portal_token_verifier",
    "require_portal_principal",
]
