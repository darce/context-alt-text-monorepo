"""Public demo slug resolution (DS-2 / launch-plan §5).

Mounted at the **app root** (not under ``/recognition``) so the public URL is
``GET /x/{slug}`` — matching ``demo_url_for`` / provisioned demo URLs.

Unauthenticated. Per-IP rate limited (DS-5). Never returns raw API key or
``api_key_ref`` (hash) — response fields are sourced only from the demo row.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.demo_provisioning_service import (
    DemoEndedError,
    DemoInstanceNotFoundError,
    resolve_demo,
)
from recognition.interface_adapters.http.deps.ip_rate_limit import enforce_ip_rate_limit
from recognition.interface_adapters.http.deps.session import get_session

router = APIRouter(tags=["demo"], dependencies=[Depends(enforce_ip_rate_limit)])


class DemoResolveResponse(BaseModel):
    """Public-safe demo context. Every field from the demo_instances row."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    seed_bundle: str
    branding_json: dict | None
    expires_at: datetime
    quota_remaining: int


@router.get(
    "/x/{slug}",
    response_model=DemoResolveResponse,
    summary="Resolve a public demo slug (DS-2)",
)
async def resolve_demo_slug(
    slug: str,
    session: AsyncSession = Depends(get_session),
) -> DemoResolveResponse:
    """Resolve ``slug`` to demo context for the demo WP (server-side only)."""
    try:
        ctx = await resolve_demo(session, slug=slug)
    except DemoInstanceNotFoundError as exc:
        # Uniform not-found body — no existence oracle.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not found",
        ) from exc
    except DemoEndedError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "demo_ended",
                "message": "this demo has ended",
            },
        ) from exc

    return DemoResolveResponse(
        tenant_id=ctx.tenant_id,
        seed_bundle=ctx.seed_bundle,
        branding_json=ctx.branding_json,
        expires_at=ctx.expires_at,
        quota_remaining=ctx.quota_remaining,
    )


__all__ = ["DemoResolveResponse", "router"]
