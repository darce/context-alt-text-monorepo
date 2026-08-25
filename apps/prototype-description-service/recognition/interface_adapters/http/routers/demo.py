"""Public demo slug resolution (DS-2 / launch-plan §5).

Mounted at the **app root** (not under ``/recognition``) so the public URL is
``GET /x/{slug}`` — matching ``demo_url_for`` / provisioned demo URLs.

First exchange is ``POST /x/{slug}/session`` which mints a short-lived session
(cookie + token). Subsequent ``GET /x/{slug}`` requires that session; missing,
invalid, or expired sessions return 401 with no tenant data. Per-IP rate
limited (DS-5). Never returns raw API key or ``api_key_ref`` (hash).
"""

from __future__ import annotations

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
    mint_demo_session,
    resolve_demo,
    resolve_demo_session,
)
from recognition.interface_adapters.http.deps.ip_rate_limit import enforce_ip_rate_limit
from recognition.interface_adapters.http.deps.session import get_session

router = APIRouter(tags=["demo"], dependencies=[Depends(enforce_ip_rate_limit)])


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
    if isinstance(exc, DemoEndedError):
        return HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "demo_ended",
                "message": "this demo has ended",
            },
        )
    raise exc


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
    except (DemoInstanceNotFoundError, DemoEndedError) as exc:
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
    except (DemoInstanceNotFoundError, DemoEndedError) as exc:
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


__all__ = ["DemoPreScanResponse", "DemoResolveResponse", "DemoSessionResponse", "router"]
