"""Public demo slug resolution (DS-2 / launch-plan §5).

Mounted at the **app root** (not under ``/recognition``) so the public URL is
``GET /x/{slug}`` — matching ``demo_url_for`` / provisioned demo URLs.

First exchange is ``POST /x/{slug}/session`` which mints a short-lived session
(cookie + token). Subsequent ``GET /x/{slug}`` requires that session; missing,
invalid, or expired sessions return 401 with no tenant data. Per-IP rate
limited (DS-5). Never returns raw API key or ``api_key_ref`` (hash).
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.demo_provisioning_service import (
    DEFAULT_SESSION_TTL_SECONDS,
    DEMO_SESSION_COOKIE,
    DEMO_SESSION_HEADER,
    DemoEndedError,
    DemoInstanceNotFoundError,
    DemoSessionError,
    PreScanStateError,
    UnknownSeedBundleError,
    mint_demo_session,
    provision_demo,
    resolve_demo,
    resolve_demo_session,
)
from recognition.interface_adapters.http.deps.ip_rate_limit import _client_ip, enforce_ip_rate_limit
from recognition.interface_adapters.http.deps.session import get_session

router = APIRouter(tags=["demo"], dependencies=[Depends(enforce_ip_rate_limit)])

_PROVISION_WINDOW_SECONDS = 60
_provision_state: dict[str, deque[float]] = {}
_provision_lock = asyncio.Lock()


def _reset_provision_limiter_for_tests() -> None:
    """Testing seam: clear the per-source provision counter between tests."""
    _provision_state.clear()


_DEFAULT_PROVISION_RPM = 3


def _provision_rpm() -> int:
    raw = os.getenv("RECOGNITION_DEMO_PROVISION_RPM", str(_DEFAULT_PROVISION_RPM))
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_PROVISION_RPM
    if parsed <= 0:
        return _DEFAULT_PROVISION_RPM
    return parsed


async def enforce_provision_rate_limit(request: Request) -> None:
    """Per-source (client IP) cap on POST /x/provision (WEB-17 / SEC-08)."""
    limit = _provision_rpm()
    key = _client_ip(request)
    now = time.monotonic()
    async with _provision_lock:
        window = _provision_state.setdefault(key, deque())
        cutoff = now - _PROVISION_WINDOW_SECONDS
        while window and window[0] <= cutoff:
            window.popleft()
        if len(window) >= limit:
            oldest = window[0]
            retry_after = max(0, int(oldest + _PROVISION_WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
        window.append(now)


class DemoPreScanResponse(BaseModel):
    """Pre-scan contract encoded in the seed bundle (AUTH-04)."""

    model_config = ConfigDict(extra="forbid")

    seeded_media_present: bool
    scanned_faces: int
    people_count: int


class DemoResolveResponse(BaseModel):
    """Public-safe demo context. Every field from the demo_instances row."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    seed_bundle: str
    branding_json: dict | None
    expires_at: datetime
    quota_remaining: int
    pre_scan: DemoPreScanResponse


class DemoSessionResponse(BaseModel):
    """Session minted by exchanging a slug. No tenant data."""

    model_config = ConfigDict(extra="forbid")

    session_token: str
    expires_at: datetime


class DemoProvisionRequest(BaseModel):
    """Public demo provision body. No key material."""

    model_config = ConfigDict(extra="forbid")

    label: str
    seed: str = "default"


class DemoProvisionResponse(BaseModel):
    """Public-safe provision result. Raw API key is never returned."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    demo_url: str
    seed_bundle: str
    expires_at: datetime
    pre_scan: DemoPreScanResponse


def _session_token_from_request(request: Request) -> str | None:
    header = request.headers.get(DEMO_SESSION_HEADER)
    if header and header.strip():
        return header.strip()
    cookie = request.cookies.get(DEMO_SESSION_COOKIE)
    if cookie and cookie.strip():
        return cookie.strip()
    return None


def _http_from_lookup(exc: Exception) -> HTTPException:
    if isinstance(exc, DemoInstanceNotFoundError):
        # Uniform 404 body for every unknown slug (no existence oracle among
        # unknowns). Expired/revoked deliberately return 410 demo_ended below —
        # an intentional lifecycle signal for the sign-up CTA (launch-plan §5),
        # bounded against enumeration by the per-IP limiter.
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not found",
        )
    if isinstance(exc, (DemoEndedError, UnknownSeedBundleError)):
        return HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "demo_ended",
                "message": "this demo has ended",
            },
        )
    raise exc


@router.post(
    "/x/provision",
    response_model=DemoProvisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision a demo instance (WEB-17 rate-limited)",
    dependencies=[Depends(enforce_provision_rate_limit)],
)
async def provision_demo_instance(
    body: DemoProvisionRequest,
    session: AsyncSession = Depends(get_session),
) -> DemoProvisionResponse:
    """Mint a demo tenant. Per-source 429 when the provision budget is spent."""
    try:
        result = await provision_demo(session, label=body.label, seed=body.seed)
    except UnknownSeedBundleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except PreScanStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    instance = result.instance
    return DemoProvisionResponse(
        slug=instance.slug,
        demo_url=result.demo_url,
        seed_bundle=instance.seed_bundle,
        expires_at=instance.expires_at,
        pre_scan=DemoPreScanResponse(
            seeded_media_present=result.pre_scan.seeded_media_present,
            scanned_faces=result.pre_scan.scanned_faces,
            people_count=result.pre_scan.people_count,
        ),
    )


@router.post(
    "/x/{slug}/session",
    response_model=DemoSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Exchange a demo slug for a short-lived session (AUTH-02)",
)
async def mint_demo_slug_session(
    slug: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> DemoSessionResponse:
    """Validate ``slug`` then mint a session. Does not return tenant data."""
    try:
        await resolve_demo(session, slug=slug)
    except (DemoInstanceNotFoundError, DemoEndedError, UnknownSeedBundleError) as exc:
        raise _http_from_lookup(exc) from exc

    minted = mint_demo_session(slug)
    response.set_cookie(
        key=DEMO_SESSION_COOKIE,
        value=minted.token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/x",
        max_age=DEFAULT_SESSION_TTL_SECONDS,
    )
    return DemoSessionResponse(session_token=minted.token, expires_at=minted.expires_at)


@router.get(
    "/x/{slug}",
    response_model=DemoResolveResponse,
    summary="Resolve a public demo slug (DS-2)",
)
async def resolve_demo_slug(
    slug: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> DemoResolveResponse:
    """Resolve ``slug`` to demo context. Requires a session from POST /session."""
    try:
        ctx = await resolve_demo(session, slug=slug)
    except (DemoInstanceNotFoundError, DemoEndedError, UnknownSeedBundleError) as exc:
        raise _http_from_lookup(exc) from exc

    try:
        resolve_demo_session(_session_token_from_request(request), slug=slug)
    except DemoSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.code.value,
        ) from exc

    return DemoResolveResponse(
        tenant_id=ctx.tenant_id,
        seed_bundle=ctx.seed_bundle,
        branding_json=ctx.branding_json,
        expires_at=ctx.expires_at,
        quota_remaining=ctx.quota_remaining,
        pre_scan=DemoPreScanResponse(
            seeded_media_present=ctx.pre_scan.seeded_media_present,
            scanned_faces=ctx.pre_scan.scanned_faces,
            people_count=ctx.pre_scan.people_count,
        ),
    )


__all__ = [
    "DemoPreScanResponse",
    "DemoProvisionRequest",
    "DemoProvisionResponse",
    "DemoResolveResponse",
    "DemoSessionResponse",
    "enforce_provision_rate_limit",
    "router",
]
