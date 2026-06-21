"""Operator ``/admin`` router: tenant + API-key lifecycle over JSON.

Every route is gated by :func:`require_admin` (a dedicated admin-token header,
never the tenant auth path). Every mutation writes an ``audit_events`` row on the
**same** request-scoped session as the DB change and commits exactly once, so a
failed audit write rolls back the whole request — no un-audited state can land.

Session note: admin is cross-tenant, so this router uses a dedicated
``get_admin_session`` dependency built directly on the unscoped
``async_session_factory``. It deliberately does NOT reuse the tenant
``get_session`` dependency: ``get_session`` chains ``get_tenant_id_optional``,
which declares a ``tenant_id`` *query* parameter that collides with the
``{tenant_id}`` *path* parameter on these routes (FastAPI rejects the mix), and
its only RLS-setting branch is gated on a tenant header admin never sends. The
admin session therefore never sets the RLS ``app.current_tenant`` GUC — exactly
what a cross-tenant operator surface needs.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from enum import StrEnum

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, Tenant
from db.session import async_session_factory
from db.settings import get_database_settings
from recognition.application.services.api_key_admin_service import mint_api_key
from recognition.application.services.audit_service import AuditService
from recognition.config.security import RateLimitTier
from recognition.infrastructure.repositories.api_key_repository import (
    ClassifyResult,
    SqlAlchemyApiKeyRepository,
    _as_utc,
)
from recognition.interface_adapters.http.deps.admin_auth import require_admin

_ADMIN_ACTOR = "admin"
_ADMIN_SCOPE = "admin_router"


async def get_admin_session() -> AsyncIterator[AsyncSession]:
    """Yield an unscoped session for cross-tenant admin work (no RLS GUC).

    Handlers own commits explicitly; this dependency rolls back and re-raises on
    any unhandled error so a failed audit write cannot leave un-audited state.
    """
    session = async_session_factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


class AdminAuditEvent(StrEnum):
    """Canonical ``audit_events.event_type`` values for admin mutations (sr-007)."""

    TENANT_CREATE = "tenant.create"
    API_KEY_MINT = "api_key.mint"
    API_KEY_REVOKE = "api_key.revoke"


# --- Request / response models -------------------------------------------------


class CreateTenantRequest(BaseModel):
    tenant_id: uuid.UUID
    site_url: str = Field(min_length=1, max_length=255)


class TenantResponse(BaseModel):
    tenant_id: uuid.UUID
    site_url: str
    created_at: datetime | None = None


class MintKeyRequest(BaseModel):
    tier: RateLimitTier = RateLimitTier.STANDARD
    expires_in_days: int | None = Field(default=None, ge=1)


class MintKeyResponse(BaseModel):
    """Raw key is surfaced exactly once here and is unrecoverable thereafter."""

    key_id: uuid.UUID
    tenant_id: uuid.UUID
    api_key: str
    rate_limit_tier: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    key_id: uuid.UUID
    tenant_id: uuid.UUID
    status: ClassifyResult
    rate_limit_tier: str | None = None
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class RevokeKeyResponse(BaseModel):
    key_id: uuid.UUID
    tenant_id: uuid.UUID
    revoked_at: datetime | None = None
    already_revoked: bool = False


admin_router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin)])


# --- Helpers -------------------------------------------------------------------


def _derive_status(record: ApiKey) -> ClassifyResult:
    """Status from stored timestamps (no DB round-trip)."""
    if record.revoked_at is not None:
        return "revoked"
    if record.expires_at is not None and _as_utc(record.expires_at) <= datetime.now(tz=UTC):
        return "expired"
    return "active"


def _api_key_response(record: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        key_id=record.id,
        tenant_id=record.tenant_id,
        status=_derive_status(record),
        rate_limit_tier=record.rate_limit_tier,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
    )


# --- Routes --------------------------------------------------------------------


@admin_router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: CreateTenantRequest,
    session: AsyncSession = Depends(get_admin_session),
) -> TenantResponse:
    """Upsert a tenant by id. A duplicate ``site_url`` on a different tenant → 409."""
    existing = await session.get(Tenant, body.tenant_id)
    if existing is None:
        tenant = Tenant(id=body.tenant_id, site_url=body.site_url)
        session.add(tenant)
    else:
        existing.site_url = body.site_url
        tenant = existing

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="site_url already in use by another tenant",
        ) from exc

    await AuditService().record_event(
        session,
        tenant_id=str(body.tenant_id),
        event_type=AdminAuditEvent.TENANT_CREATE,
        actor=_ADMIN_ACTOR,
        scope=_ADMIN_SCOPE,
        payload={"site_url": body.site_url},
    )
    await session.commit()
    await session.refresh(tenant)
    return TenantResponse(tenant_id=tenant.id, site_url=tenant.site_url, created_at=tenant.created_at)


@admin_router.get("/tenants", response_model=list[TenantResponse])
async def list_tenants(session: AsyncSession = Depends(get_admin_session)) -> list[TenantResponse]:
    """List tenants ordered by creation time."""
    stmt = select(Tenant).order_by(Tenant.created_at, Tenant.id)
    rows = (await session.execute(stmt)).scalars().all()
    return [TenantResponse(tenant_id=t.id, site_url=t.site_url, created_at=t.created_at) for t in rows]


@admin_router.post(
    "/tenants/{tenant_id}/keys",
    response_model=MintKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def mint_key(
    tenant_id: uuid.UUID,
    body: MintKeyRequest | None = None,
    session: AsyncSession = Depends(get_admin_session),
) -> MintKeyResponse:
    """Mint an API key for a tenant; the raw key is returned exactly once.

    Unknown tenant (FK violation on ``api_keys.tenant_id``) → 404.
    """
    request = body or MintKeyRequest()
    try:
        record, raw = await mint_api_key(
            session,
            tenant_id=tenant_id,
            tier=request.tier,
            expires_in_days=request.expires_in_days,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant not found",
        ) from exc

    await AuditService().record_event(
        session,
        tenant_id=str(tenant_id),
        event_type=AdminAuditEvent.API_KEY_MINT,
        actor=_ADMIN_ACTOR,
        scope=_ADMIN_SCOPE,
        payload={"key_id": str(record.id), "rate_limit_tier": record.rate_limit_tier},
    )
    await session.commit()
    return MintKeyResponse(
        key_id=record.id,
        tenant_id=record.tenant_id,
        api_key=raw,
        rate_limit_tier=record.rate_limit_tier,
        created_at=record.created_at,
        expires_at=record.expires_at,
    )


@admin_router.get("/tenants/{tenant_id}/keys", response_model=list[ApiKeyResponse])
async def list_keys(
    tenant_id: uuid.UUID,
    session: AsyncSession = Depends(get_admin_session),
) -> list[ApiKeyResponse]:
    """List a tenant's keys with derived status; never returns the hash or raw key."""
    repo = SqlAlchemyApiKeyRepository(session)
    rows = await repo.list_for_tenant(tenant_id, include_revoked=True)
    return [_api_key_response(record) for record in rows]


@admin_router.post("/keys/{key_id}/revoke", response_model=RevokeKeyResponse)
async def revoke_key(
    key_id: uuid.UUID,
    session: AsyncSession = Depends(get_admin_session),
) -> RevokeKeyResponse:
    """Revoke a key. Unknown key → 404; already-revoked → 200 idempotent.

    An already-revoked key returns the original ``revoked_at`` unchanged and
    writes NO second audit row (no re-stamp). A fresh revoke resolves the owning
    ``tenant_id`` first, then audits atomically with the soft-revoke.
    """
    record = await session.get(ApiKey, key_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="api key not found")

    if record.revoked_at is not None:
        return RevokeKeyResponse(
            key_id=record.id,
            tenant_id=record.tenant_id,
            revoked_at=record.revoked_at,
            already_revoked=True,
        )

    tenant_id = record.tenant_id
    repo = SqlAlchemyApiKeyRepository(session)
    revoked = await repo.revoke(key_id)

    await AuditService().record_event(
        session,
        tenant_id=str(tenant_id),
        event_type=AdminAuditEvent.API_KEY_REVOKE,
        actor=_ADMIN_ACTOR,
        scope=_ADMIN_SCOPE,
        payload={"key_id": str(key_id)},
    )
    await session.commit()
    return RevokeKeyResponse(
        key_id=revoked.id,
        tenant_id=revoked.tenant_id,
        revoked_at=revoked.revoked_at,
        already_revoked=False,
    )


# --- Env/DSN safety guard (BR-02 mirror) ---------------------------------------


def assert_admin_env_dsn(*, runtime_mode: str | None = None, dsn: str | None = None) -> None:
    """Fail closed when the runtime mode and the configured DSN host disagree.

    Mirrors the CLI BR-02 guard (``scripts.manage_api_keys._validate_env_vs_dsn``)
    in-process so mounting the admin surface cannot silently write a "production"
    key to a local DB. ``runtime_mode`` maps to the CLI env token explicitly:
    ``"production" -> "prod"`` (anything else, incl. None default of
    ``RECOGNITION_RUNTIME_MODE`` or ``"production"``) ``-> "local"``. Raises
    ``RuntimeError`` on any non-None mismatch result; not a silent no-op.
    """
    import os

    from scripts.manage_api_keys import _validate_env_vs_dsn

    resolved_mode = runtime_mode if runtime_mode is not None else os.environ.get("RECOGNITION_RUNTIME_MODE", "production")
    env_token = "prod" if resolved_mode == "production" else "local"
    resolved_dsn = dsn if dsn is not None else get_database_settings().postgres_dsn

    mismatch = _validate_env_vs_dsn(env_token, resolved_dsn)
    if mismatch is not None:
        raise RuntimeError(f"admin env/DSN guard: {mismatch}")


__all__ = ["AdminAuditEvent", "admin_router", "assert_admin_env_dsn"]
