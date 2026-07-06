"""Operator ``/admin`` router: tenant + API-key lifecycle over JSON.

Every route is gated by :func:`require_admin` (dedicated admin-token header, or
HTTP Basic for the browser console — never the tenant auth path). JSON mutation
routes are ADDITIONALLY gated by :func:`require_admin_header`: Basic auth is
console-only, so browser credential replay cannot authorize a cross-site JSON
mutation. Any new mutating JSON route MUST attach
``dependencies=[Depends(require_admin_header)]``; ``/ui`` form routes use
``require_same_origin`` instead. Every mutation writes an ``audit_events`` row on the
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

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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
from recognition.interface_adapters.http.admin_console import render_console
from recognition.interface_adapters.http.deps.admin_auth import (
    require_admin,
    require_admin_header,
    require_same_origin,
)

_CONSOLE_KEYS_PER_TENANT = 100

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
    expires_in_days: int | None = Field(default=None, ge=1, le=36500)


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


class TenantSiteUrlConflictError(Exception):
    """Raised when an upsert would collide with another tenant's ``site_url``."""


class UnknownTenantError(Exception):
    """Raised when a mint targets a tenant id that does not exist (FK violation)."""


class UnknownKeyError(Exception):
    """Raised when a revoke targets a key id that does not exist."""


class RevokeOutcome:
    """Result of :func:`revoke_key_atomic`: the key plus whether it was already revoked."""

    __slots__ = ("record", "already_revoked")

    def __init__(self, record: ApiKey, *, already_revoked: bool) -> None:
        self.record = record
        self.already_revoked = already_revoked


# --- Shared mutation helpers (single audit/atomicity implementation) -----------
#
# Both the JSON handlers and the browser-form handlers call these so the
# audit-row-per-mutation + single-commit contract has exactly one implementation.
# Each helper flushes/audits and commits on the supplied session; callers map the
# domain exceptions above onto their transport's error shape (HTTP status vs.
# console message).


async def upsert_tenant_atomic(session: AsyncSession, *, tenant_id: uuid.UUID, site_url: str) -> Tenant:
    """Upsert a tenant by id + audit + commit. Duplicate site_url → TenantSiteUrlConflictError."""
    existing = await session.get(Tenant, tenant_id)
    if existing is None:
        tenant = Tenant(id=tenant_id, site_url=site_url)
        session.add(tenant)
    else:
        existing.site_url = site_url
        tenant = existing

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise TenantSiteUrlConflictError from exc

    await AuditService().record_event(
        session,
        tenant_id=str(tenant_id),
        event_type=AdminAuditEvent.TENANT_CREATE,
        actor=_ADMIN_ACTOR,
        scope=_ADMIN_SCOPE,
        payload={"site_url": site_url},
    )
    await session.commit()
    await session.refresh(tenant)
    return tenant


async def mint_key_atomic(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    tier: RateLimitTier,
    expires_in_days: int | None,
) -> tuple[ApiKey, str]:
    """Mint a key + audit + commit. Unknown tenant (FK) → UnknownTenantError."""
    try:
        record, raw = await mint_api_key(
            session,
            tenant_id=tenant_id,
            tier=tier,
            expires_in_days=expires_in_days,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise UnknownTenantError from exc

    await AuditService().record_event(
        session,
        tenant_id=str(tenant_id),
        event_type=AdminAuditEvent.API_KEY_MINT,
        actor=_ADMIN_ACTOR,
        scope=_ADMIN_SCOPE,
        payload={"key_id": str(record.id), "rate_limit_tier": record.rate_limit_tier},
    )
    await session.commit()
    return record, raw


async def revoke_key_atomic(session: AsyncSession, *, key_id: uuid.UUID) -> RevokeOutcome:
    """Revoke a key + audit + commit. Unknown key → UnknownKeyError; already-revoked is idempotent.

    An already-revoked key returns the original ``revoked_at`` unchanged and writes
    NO second audit row. A fresh revoke resolves the owning ``tenant_id`` first, then
    audits atomically with the soft-revoke.
    """
    record = await session.get(ApiKey, key_id)
    if record is None:
        raise UnknownKeyError

    if record.revoked_at is not None:
        return RevokeOutcome(record, already_revoked=True)

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
    return RevokeOutcome(revoked, already_revoked=False)


# --- Routes --------------------------------------------------------------------


@admin_router.post(
    "/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_header)],
)
async def create_tenant(
    body: CreateTenantRequest,
    session: AsyncSession = Depends(get_admin_session),
) -> TenantResponse:
    """Upsert a tenant by id. A duplicate ``site_url`` on a different tenant → 409."""
    try:
        tenant = await upsert_tenant_atomic(session, tenant_id=body.tenant_id, site_url=body.site_url)
    except TenantSiteUrlConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="site_url already in use by another tenant",
        ) from exc
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
    dependencies=[Depends(require_admin_header)],
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
        record, raw = await mint_key_atomic(
            session,
            tenant_id=tenant_id,
            tier=request.tier,
            expires_in_days=request.expires_in_days,
        )
    except UnknownTenantError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant not found",
        ) from exc
    except ValueError as exc:
        # Defence-in-depth: Field(le=36500) already 422s out-of-range JSON, but a
        # direct/default caller could still trip the helper's bound — map it to 400
        # so it never surfaces as a 500.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

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


@admin_router.post(
    "/keys/{key_id}/revoke",
    response_model=RevokeKeyResponse,
    dependencies=[Depends(require_admin_header)],
)
async def revoke_key(
    key_id: uuid.UUID,
    session: AsyncSession = Depends(get_admin_session),
) -> RevokeKeyResponse:
    """Revoke a key. Unknown key → 404; already-revoked → 200 idempotent.

    An already-revoked key returns the original ``revoked_at`` unchanged and
    writes NO second audit row (no re-stamp). A fresh revoke resolves the owning
    ``tenant_id`` first, then audits atomically with the soft-revoke.
    """
    try:
        outcome = await revoke_key_atomic(session, key_id=key_id)
    except UnknownKeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="api key not found") from exc
    return RevokeKeyResponse(
        key_id=outcome.record.id,
        tenant_id=outcome.record.tenant_id,
        revoked_at=outcome.record.revoked_at,
        already_revoked=outcome.already_revoked,
    )


# --- Browser console (HTML) ----------------------------------------------------
#
# These routes live on ``admin_router`` so they inherit the router-level
# ``Depends(require_admin)``. They reuse the SAME atomic mutation helpers as the
# JSON routes above, so the audit/atomicity contract has one implementation.
# Forms POST (not JSON) and 303-redirect back to ``/admin/`` — except mint, which
# renders inline so the raw key is shown once and never lands in a redirect URL.


async def _load_console_model(
    session: AsyncSession,
) -> tuple[list[Tenant], dict[uuid.UUID, list[ApiKey]], dict[uuid.UUID, int]]:
    """Load every tenant + its keys (incl. revoked) for the console in ONE key query.

    Replaces the prior per-tenant ``list_for_tenant`` loop (N+1) with a single
    ``WHERE tenant_id IN (...)`` query, then groups in-memory. Every tenant gets a
    list (empty if it has no keys). The cap is applied in SQL (row_number over a
    per-tenant window, newest first) so a tenant with many keys keeps the key
    the operator just minted visible and over-cap rows are not materialized;
    ``totals_by_tenant`` carries the pre-cap count so the view can show a
    "showing N of M" note. Recency ordering is exact up to ``created_at``
    resolution: rows sharing a timestamp (e.g. bulk mints in one transaction
    where ``now()`` is transaction-fixed) tie-break on ``id DESC``, which is
    deterministic but not recency-meaningful for uuid4 ids. Ordering here is
    deliberately newest-first (operational console view); the JSON
    ``GET /admin/tenants/{id}/keys`` route and the CLI keep the repository's
    chronological ``created_at ASC`` order (audit view) — an intentional
    divergence, not drift.
    """
    stmt = select(Tenant).order_by(Tenant.created_at, Tenant.id)
    tenants = list((await session.execute(stmt)).scalars().all())

    keys_by_tenant: dict[uuid.UUID, list[ApiKey]] = {tenant.id: [] for tenant in tenants}
    totals_by_tenant: dict[uuid.UUID, int] = {tenant.id: 0 for tenant in tenants}
    if tenants:
        tenant_ids = [tenant.id for tenant in tenants]
        ranked_keys = (
            select(
                ApiKey,
                func.row_number()
                .over(
                    partition_by=ApiKey.tenant_id,
                    order_by=(ApiKey.created_at.desc(), ApiKey.id.desc()),
                )
                .label("key_rank"),
                func.count().over(partition_by=ApiKey.tenant_id).label("tenant_key_count"),
            )
            .where(ApiKey.tenant_id.in_(tenant_ids))
            .subquery()
        )
        ranked_key = aliased(ApiKey, ranked_keys)
        keys_stmt = (
            select(ranked_key, ranked_keys.c.tenant_key_count)
            .where(ranked_keys.c.key_rank <= _CONSOLE_KEYS_PER_TENANT)
            .order_by(
                ranked_key.tenant_id,
                ranked_key.created_at.desc(),
                ranked_key.id.desc(),
            )
        )
        for key, tenant_key_count in (await session.execute(keys_stmt)).all():
            totals_by_tenant[key.tenant_id] = int(tenant_key_count)
            keys_by_tenant[key.tenant_id].append(key)
    return tenants, keys_by_tenant, totals_by_tenant


async def _render_console_response(
    session: AsyncSession,
    *,
    minted_key: str | None = None,
    message: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    tenants, keys_by_tenant, totals_by_tenant = await _load_console_model(session)
    html_doc = render_console(
        tenants=tenants,
        keys_by_tenant=keys_by_tenant,
        totals_by_tenant=totals_by_tenant,
        minted_key=minted_key,
        message=message,
    )
    return HTMLResponse(content=html_doc, status_code=status_code)


@admin_router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def console_index(session: AsyncSession = Depends(get_admin_session)) -> HTMLResponse:
    """Render the operator console listing every tenant and its keys."""
    return await _render_console_response(session)


@admin_router.post("/ui/tenants", include_in_schema=False, dependencies=[Depends(require_same_origin)])
async def console_create_tenant(
    tenant_id: str = Form(...),
    site_url: str = Form(...),
    session: AsyncSession = Depends(get_admin_session),
) -> RedirectResponse:
    """Upsert a tenant from the console form, then 303-redirect to the console."""
    try:
        parsed_id = uuid.UUID(tenant_id.strip())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant_id must be a UUID") from exc
    try:
        await upsert_tenant_atomic(session, tenant_id=parsed_id, site_url=site_url.strip())
    except TenantSiteUrlConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="site_url already in use by another tenant",
        ) from exc
    return RedirectResponse(url="/admin/", status_code=status.HTTP_303_SEE_OTHER)


@admin_router.post(
    "/ui/keys",
    response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(require_same_origin)],
)
async def console_mint_key(
    tenant_id: str = Form(...),
    tier: RateLimitTier = Form(RateLimitTier.STANDARD),
    expires_in_days: str | None = Form(None),
    session: AsyncSession = Depends(get_admin_session),
) -> HTMLResponse:
    """Mint a key from the console form and render the raw key inline exactly once.

    The raw key is NOT placed in a redirect URL; it is surfaced once in the
    re-rendered console and is unrecoverable thereafter.
    """
    try:
        parsed_id = uuid.UUID(tenant_id.strip())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant_id must be a UUID") from exc

    days: int | None = None
    if expires_in_days is not None and expires_in_days.strip():
        try:
            days = int(expires_in_days)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="expires_in_days must be an integer"
            ) from exc
        if days < 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="expires_in_days must be >= 1")
        if days > 36500:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="expires_in_days must be <= 36500")

    try:
        _record, raw = await mint_key_atomic(session, tenant_id=parsed_id, tier=tier, expires_in_days=days)
    except UnknownTenantError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return await _render_console_response(session, minted_key=raw, message="API key minted.")


@admin_router.post("/ui/keys/{key_id}/revoke", include_in_schema=False, dependencies=[Depends(require_same_origin)])
async def console_revoke_key(
    key_id: uuid.UUID,
    session: AsyncSession = Depends(get_admin_session),
) -> RedirectResponse:
    """Revoke a key from the console form (idempotent), then 303-redirect."""
    try:
        await revoke_key_atomic(session, key_id=key_id)
    except UnknownKeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="api key not found") from exc
    return RedirectResponse(url="/admin/", status_code=status.HTTP_303_SEE_OTHER)


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

    resolved_mode = (
        runtime_mode if runtime_mode is not None else os.environ.get("RECOGNITION_RUNTIME_MODE", "production")
    )
    env_token = "prod" if resolved_mode == "production" else "local"
    resolved_dsn = dsn if dsn is not None else get_database_settings().postgres_dsn

    mismatch = _validate_env_vs_dsn(env_token, resolved_dsn)
    if mismatch is not None:
        raise RuntimeError(f"admin env/DSN guard: {mismatch}")


__all__ = ["AdminAuditEvent", "admin_router", "assert_admin_env_dsn"]
