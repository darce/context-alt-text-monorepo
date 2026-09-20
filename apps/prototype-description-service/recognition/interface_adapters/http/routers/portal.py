"""Authenticated tenant self-service portal routes."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import async_session_factory
from db.tenant_context import set_tenant_context
from recognition.application.services.tenant_entitlement_service import TenantEntitlementService
from recognition.application.services.tenant_key_service import (
    IdempotencyKeyReuseError,
    InvalidKeyRequestError,
    KeyAlreadyRevokedError,
    KeyAlreadyRotatedError,
    KeyConflictError,
    KeyIssueResult,
    KeyLifecycleCorruptionError,
    KeyLimitExceededError,
    KeyNotFoundError,
    KeyPage,
    TenantKeyService,
)
from recognition.domain.portal_contracts import PortalPrincipal
from recognition.interface_adapters.http.deps.portal_auth import require_portal_principal
from recognition.shared.db.dialect import is_postgres

logger = logging.getLogger(__name__)

DEFAULT_KEY_PAGE_LIMIT = 25
MAX_KEY_PAGE_LIMIT = 100
NO_STORE_HEADERS = {"Cache-Control": "no-store"}

router = APIRouter(prefix="/portal", tags=["portal"])


class PortalMeResponse(BaseModel):
    """The identity and tenant binding established by portal authentication."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    issuer: str
    subject: str
    email: str | None


class PortalKeyMetadataResponse(BaseModel):
    """Key metadata that can safely be returned from reads."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    rate_limit_tier: str | None
    lifetime_seconds: int | None


class PortalKeyIssueResponse(PortalKeyMetadataResponse):
    """Create/rotate response whose raw secret is present only on first success."""

    raw_key: str | None
    replayed: bool


class PortalKeyPageResponse(BaseModel):
    """Cursor page envelope copied from the bounded service result."""

    model_config = ConfigDict(extra="forbid")

    data: list[PortalKeyMetadataResponse]
    next_cursor: str | None
    cursor: str | None
    limit: int
    total: int


class CreateKeyRequest(BaseModel):
    """Normalized create request used by the service fingerprint."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    lifetime_seconds: int | None = Field(default=None, gt=0)
    rate_limit_tier: str | None = Field(default=None, min_length=1)


class RotateKeyRequest(BaseModel):
    """Normalized rotation request used by the service fingerprint."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(default="routine", min_length=1)


class RevokeKeyRequest(BaseModel):
    """Revoke request with an explicit last-key confirmation switch."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(default="portal revoke", min_length=1)
    confirm_last_usable: StrictBool = Field(
        default=False,
        validation_alias=AliasChoices("confirm_last_usable", "confirm_last_key", "confirm", "confirmation"),
    )
    emergency: StrictBool = False


class RevokeKeyResponse(BaseModel):
    """Safe acknowledgement for an immediate revocation."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    revoked: bool


class PortalUsagePeriodResponse(BaseModel):
    """The entitlement period represented by a usage read."""

    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime


class PortalUsageResponse(BaseModel):
    """Tenant usage with explicit freshness and observation timestamp."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    used: int | None
    reserved: int | None
    remaining: int | None
    allowance: int | None
    period_start: datetime
    period_end: datetime
    period: PortalUsagePeriodResponse
    as_of: datetime
    status: str
    data_source: str


async def get_portal_session(
    principal: PortalPrincipal = Depends(require_portal_principal),
) -> AsyncIterator[AsyncSession]:
    """Provide a session whose tenant context is sourced only from the principal."""
    session = async_session_factory()
    try:
        if is_postgres(session):
            await set_tenant_context(session, principal.tenant_id)
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_tenant_key_service(
    request: Request,
    session: AsyncSession = Depends(get_portal_session),
) -> TenantKeyService:
    """Resolve the injected key service, or construct its tenant-bound implementation."""
    configured = getattr(request.app.state, "tenant_key_service", None)
    if configured is not None:
        return cast(TenantKeyService, configured)
    return TenantKeyService(session)


async def get_tenant_entitlement_service(
    request: Request,
    session: AsyncSession = Depends(get_portal_session),
) -> TenantEntitlementService:
    """Resolve the injected entitlement service, or construct its implementation."""
    configured = getattr(request.app.state, "tenant_entitlement_service", None)
    if configured is not None:
        return cast(TenantEntitlementService, configured)
    return TenantEntitlementService(session)


async def get_portal_usage_service(request: Request) -> object | None:
    """Resolve an optional read-side usage projection installed by composition."""
    configured = getattr(request.app.state, "portal_usage_service", None)
    if configured is not None:
        return configured
    return getattr(request.app.state, "usage_admission_service", None)


def _no_store_error(code: int, detail: object) -> HTTPException:
    return HTTPException(status_code=code, detail=detail, headers=dict(NO_STORE_HEADERS))


def _key_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyNotFoundError):
        return _no_store_error(status.HTTP_404_NOT_FOUND, "portal key not found")
    if isinstance(exc, IdempotencyKeyReuseError):
        return _no_store_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "idempotency key was reused with a different request",
        )
    if isinstance(exc, InvalidKeyRequestError):
        return _no_store_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid portal key request")
    if isinstance(exc, KeyAlreadyRevokedError):
        return _no_store_error(status.HTTP_409_CONFLICT, "portal key is already revoked")
    if isinstance(exc, KeyAlreadyRotatedError):
        return _no_store_error(status.HTTP_409_CONFLICT, "portal key was already rotated")
    if isinstance(exc, KeyLimitExceededError):
        return _no_store_error(status.HTTP_409_CONFLICT, "tenant key limit reached")
    if isinstance(exc, KeyConflictError):
        return _no_store_error(status.HTTP_409_CONFLICT, "portal key state conflict")
    if isinstance(exc, KeyLifecycleCorruptionError):
        return _no_store_error(status.HTTP_503_SERVICE_UNAVAILABLE, "portal key service unavailable")
    return _no_store_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "portal key service unavailable")


def _raise_key_error(exc: Exception, *, operation: str) -> NoReturn:
    if not isinstance(
        exc,
        (
            KeyNotFoundError,
            IdempotencyKeyReuseError,
            InvalidKeyRequestError,
            KeyConflictError,
            KeyLifecycleCorruptionError,
        ),
    ):
        logger.error("Portal key operation failed: %s", operation)
    raise _key_error(exc) from None


def _attribute(source: object, *names: str, default: object = None) -> object:
    if isinstance(source, Mapping):
        for name in names:
            if name in source:
                return source[name]
        return default
    for name in names:
        value = getattr(source, name, None)
        if value is not None:
            return value
    return default


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _uuid_value(value: object, *, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} is invalid") from exc


def _metadata(result: object, *, tenant_id: UUID) -> PortalKeyMetadataResponse:
    result_tenant_id = _uuid_value(_attribute(result, "tenant_id"), field_name="tenant_id")
    if result_tenant_id != tenant_id:
        raise KeyNotFoundError("portal key not found")
    created_at = _attribute(result, "created_at")
    if not isinstance(created_at, datetime):
        raise KeyLifecycleCorruptionError("persisted key metadata is invalid")
    return PortalKeyMetadataResponse(
        id=_uuid_value(_attribute(result, "api_key_id", "key_id", "id"), field_name="api_key_id"),
        tenant_id=tenant_id,
        created_at=_as_utc(created_at),
        expires_at=(
            _as_utc(expires_at) if isinstance(expires_at := _attribute(result, "expires_at"), datetime) else None
        ),
        revoked_at=(
            _as_utc(revoked_at) if isinstance(revoked_at := _attribute(result, "revoked_at"), datetime) else None
        ),
        rate_limit_tier=cast(str | None, _attribute(result, "rate_limit_tier")),
        lifetime_seconds=cast(int | None, _attribute(result, "lifetime_seconds")),
    )


def _issue_response(result: KeyIssueResult, *, tenant_id: UUID) -> PortalKeyIssueResponse:
    metadata = _metadata(result, tenant_id=tenant_id)
    return PortalKeyIssueResponse(
        **metadata.model_dump(),
        raw_key=None if result.replayed else result.raw_key,
        replayed=bool(result.replayed),
    )


def _page_data(page: object) -> tuple[object, ...]:
    rows = _attribute(page, "data", "items", "keys", "rows")
    if rows is None:
        raise KeyLifecycleCorruptionError("portal key page is invalid")
    try:
        return tuple(rows)  # type: ignore[arg-type]
    except TypeError as exc:
        raise KeyLifecycleCorruptionError("portal key page is invalid") from exc


def _page_response(page: KeyPage, *, tenant_id: UUID, requested_cursor: str | None) -> PortalKeyPageResponse:
    rows = _page_data(page)
    metadata: list[PortalKeyMetadataResponse] = []
    for row in rows:
        try:
            metadata.append(_metadata(row, tenant_id=tenant_id))
        except KeyNotFoundError:
            continue
    limit = _attribute(page, "limit")
    total = _attribute(page, "total")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise KeyLifecycleCorruptionError("portal key page limit is invalid")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise KeyLifecycleCorruptionError("portal key page total is invalid")
    return PortalKeyPageResponse(
        data=metadata,
        next_cursor=cast(str | None, _attribute(page, "next_cursor")),
        cursor=cast(str | None, _attribute(page, "cursor", default=requested_cursor)),
        limit=limit,
        total=total,
    )


def _is_usable(result: object, *, now: datetime) -> bool:
    if _attribute(result, "revoked_at") is not None:
        return False
    expires_at = _attribute(result, "expires_at")
    return not isinstance(expires_at, datetime) or _as_utc(expires_at) > now


async def _find_key(
    service: TenantKeyService,
    tenant_id: UUID,
    api_key_id: UUID,
) -> object | None:
    getter = getattr(service, "get_key", None)
    if callable(getter):
        result = await getter(tenant_id, api_key_id)
        if result is None:
            return None
        result_tenant_id = _uuid_value(_attribute(result, "tenant_id"), field_name="tenant_id")
        if result_tenant_id != tenant_id:
            return None
        result_id = _uuid_value(_attribute(result, "api_key_id", "key_id", "id"), field_name="api_key_id")
        return result if result_id == api_key_id else None
    page = await service.list_keys(tenant_id, cursor=None, limit=MAX_KEY_PAGE_LIMIT, include_revoked=True)
    for result in _page_data(page):
        result_tenant_id = _uuid_value(_attribute(result, "tenant_id"), field_name="tenant_id")
        if result_tenant_id != tenant_id:
            continue
        result_id = _uuid_value(_attribute(result, "api_key_id", "key_id", "id"), field_name="api_key_id")
        if result_id == api_key_id:
            return result
    return None


async def _last_usable_key(
    service: TenantKeyService,
    tenant_id: UUID,
    api_key_id: UUID,
) -> bool:
    page = await service.list_keys(tenant_id, cursor=None, limit=MAX_KEY_PAGE_LIMIT, include_revoked=True)
    rows = _page_data(page)
    target_seen = False
    usable_count = 0
    now = _utc_now()
    for row in rows:
        row_tenant_id = _uuid_value(_attribute(row, "tenant_id"), field_name="tenant_id")
        if row_tenant_id != tenant_id:
            continue
        row_id = _uuid_value(_attribute(row, "api_key_id", "key_id", "id"), field_name="api_key_id")
        if row_id == api_key_id:
            target_seen = True
        if _is_usable(row, now=now):
            usable_count += 1
    return target_seen and usable_count == 1


@router.get("/me", response_model=PortalMeResponse)
async def portal_me(principal: PortalPrincipal = Depends(require_portal_principal)) -> PortalMeResponse:
    """Return the authenticated principal's authoritative tenant binding."""
    return PortalMeResponse(
        tenant_id=principal.tenant_id,
        issuer=principal.issuer,
        subject=principal.subject,
        email=principal.email,
    )


@router.get("/keys", response_model=PortalKeyPageResponse)
async def list_portal_keys(
    response: Response,
    limit: int = Query(default=DEFAULT_KEY_PAGE_LIMIT, ge=1),
    cursor: str | None = Query(default=None),
    principal: PortalPrincipal = Depends(require_portal_principal),
    service: TenantKeyService = Depends(get_tenant_key_service),
) -> PortalKeyPageResponse:
    """List tenant key history, including revoked metadata but never secrets."""
    response.headers.update(NO_STORE_HEADERS)
    effective_limit = min(limit, MAX_KEY_PAGE_LIMIT)
    try:
        page = await service.list_keys(
            principal.tenant_id,
            cursor=cursor,
            limit=effective_limit,
            include_revoked=True,
        )
        return _page_response(page, tenant_id=principal.tenant_id, requested_cursor=cursor)
    except Exception as exc:
        _raise_key_error(exc, operation="list")


@router.get("/keys/{api_key_id}", response_model=PortalKeyMetadataResponse)
async def get_portal_key(
    api_key_id: UUID,
    response: Response,
    principal: PortalPrincipal = Depends(require_portal_principal),
    service: TenantKeyService = Depends(get_tenant_key_service),
) -> PortalKeyMetadataResponse:
    """Return one tenant key or the same 404 for a foreign key id."""
    response.headers.update(NO_STORE_HEADERS)
    try:
        result = await _find_key(service, principal.tenant_id, api_key_id)
        if result is None:
            raise KeyNotFoundError("portal key not found")
        return _metadata(result, tenant_id=principal.tenant_id)
    except Exception as exc:
        _raise_key_error(exc, operation="get")


@router.post("/keys", response_model=PortalKeyIssueResponse)
async def create_portal_key(
    body: CreateKeyRequest,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: PortalPrincipal = Depends(require_portal_principal),
    service: TenantKeyService = Depends(get_tenant_key_service),
) -> PortalKeyIssueResponse:
    """Create one tenant key and expose its raw secret only in this response."""
    response.headers.update(NO_STORE_HEADERS)
    try:
        result = await service.create_key(
            principal.tenant_id,
            idempotency_key=idempotency_key,
            lifetime_seconds=body.lifetime_seconds,
            rate_limit_tier=body.rate_limit_tier,
        )
        return _issue_response(result, tenant_id=principal.tenant_id)
    except Exception as exc:
        _raise_key_error(exc, operation="create")


@router.post("/keys/{api_key_id}/rotate", response_model=PortalKeyIssueResponse)
async def rotate_portal_key(
    api_key_id: UUID,
    body: RotateKeyRequest,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: PortalPrincipal = Depends(require_portal_principal),
    service: TenantKeyService = Depends(get_tenant_key_service),
) -> PortalKeyIssueResponse:
    """Rotate one tenant key through the durable service idempotency boundary."""
    response.headers.update(NO_STORE_HEADERS)
    try:
        if await _find_key(service, principal.tenant_id, api_key_id) is None:
            raise KeyNotFoundError("portal key not found")
        result = await service.rotate_key(
            principal.tenant_id,
            api_key_id,
            idempotency_key=idempotency_key,
            reason=body.reason,
        )
        return _issue_response(result, tenant_id=principal.tenant_id)
    except Exception as exc:
        _raise_key_error(exc, operation="rotate")


@router.post("/keys/{api_key_id}/revoke", response_model=RevokeKeyResponse)
async def revoke_portal_key(
    api_key_id: UUID,
    body: RevokeKeyRequest,
    response: Response,
    principal: PortalPrincipal = Depends(require_portal_principal),
    service: TenantKeyService = Depends(get_tenant_key_service),
) -> RevokeKeyResponse:
    """Immediately revoke a key, warning before the tenant loses its last usable key."""
    response.headers.update(NO_STORE_HEADERS)
    try:
        if await _find_key(service, principal.tenant_id, api_key_id) is None:
            raise KeyNotFoundError("portal key not found")
        if (
            not body.confirm_last_usable
            and not body.emergency
            and await _last_usable_key(service, principal.tenant_id, api_key_id)
        ):
            raise _no_store_error(
                status.HTTP_409_CONFLICT,
                {
                    "code": "last_usable_key_confirmation_required",
                    "detail": "Revoking the last usable key would break API access until a new key is created.",
                    "confirmation_field": "confirm_last_usable",
                },
            )
        await service.revoke_key(principal.tenant_id, api_key_id, reason=body.reason)
        return RevokeKeyResponse(id=api_key_id, tenant_id=principal.tenant_id, revoked=True)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_key_error(exc, operation="revoke")


def _mapping_or_object_value(source: object, *names: str) -> object | None:
    value = _attribute(source, *names)
    if isinstance(value, Mapping):
        return value
    return value


def _count_value(source: object, *names: str) -> int | None:
    value = _mapping_or_object_value(source, *names)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _datetime_value(source: object, *names: str) -> datetime | None:
    value = _mapping_or_object_value(source, *names)
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, str) and value.strip():
        try:
            return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _usage_period(source: object) -> tuple[datetime | None, datetime | None]:
    period = _attribute(source, "period")
    period_start = _datetime_value(source, "period_start", "starts_at")
    period_end = _datetime_value(source, "period_end", "ends_at")
    if isinstance(period, Mapping):
        period_start = period_start or _datetime_value(period, "start", "period_start", "starts_at")
        period_end = period_end or _datetime_value(period, "end", "period_end", "ends_at")
    return period_start, period_end


async def _read_usage_projection(service: object | None, tenant_id: UUID) -> object | None:
    if service is None:
        return None
    for method_name in ("usage", "get_usage", "read_usage", "snapshot"):
        method = getattr(service, method_name, None)
        if not callable(method):
            continue
        try:
            return await method(tenant_id)
        except TypeError:
            return await method(tenant_id=tenant_id)
    return None


@router.get("/usage", response_model=PortalUsageResponse)
async def get_portal_usage(
    principal: PortalPrincipal = Depends(require_portal_principal),
    entitlement_service: TenantEntitlementService = Depends(get_tenant_entitlement_service),
    usage_service: object | None = Depends(get_portal_usage_service),
) -> PortalUsageResponse:
    """Read tenant entitlement usage without substituting fabricated counts."""
    try:
        entitlement = await entitlement_service.snapshot(principal.tenant_id)
        projection = await _read_usage_projection(usage_service, principal.tenant_id)
        source = projection if projection is not None else entitlement

        period_start, period_end = _usage_period(source)
        if period_start is None or period_end is None:
            period_start, period_end = _usage_period(entitlement)
        if period_start is None or period_end is None:
            raise RuntimeError("usage period unavailable")

        used = _count_value(source, "used", "used_jobs", "committed", "committed_jobs")
        reserved = _count_value(source, "reserved", "reserved_jobs")
        allowance = _count_value(source, "allowance", "allowance_jobs", "limit", "quota")
        remaining = _count_value(source, "remaining", "remaining_jobs")
        if used is None and source is not entitlement:
            used = _count_value(entitlement, "used", "used_jobs", "committed", "committed_jobs")
        if allowance is None:
            allowance = _count_value(entitlement, "allowance", "allowance_jobs", "limit", "quota")
        if remaining is None and allowance is not None and used is not None:
            remaining = max(0, allowance - used - (reserved or 0))

        data_source = _attribute(source, "data_source", "freshness")
        stale = bool(_attribute(source, "stale", "pending", default=False))
        missing_split = reserved is None
        if not isinstance(data_source, str) or not data_source:
            data_source = "pending" if stale or missing_split else "authoritative"
        source_status = _attribute(source, "status", default=None)
        status_value = source_status.value if hasattr(source_status, "value") else source_status
        if not isinstance(status_value, str) or not status_value:
            status_value = "pending" if stale or (used is None and allowance is None) else "current"
        as_of = _datetime_value(source, "as_of", "observed_at", "updated_at") or _utc_now()

        return PortalUsageResponse(
            tenant_id=principal.tenant_id,
            used=used,
            reserved=reserved,
            remaining=remaining,
            allowance=allowance,
            period_start=period_start,
            period_end=period_end,
            period=PortalUsagePeriodResponse(start=period_start, end=period_end),
            as_of=as_of,
            status=status_value,
            data_source=data_source,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Portal usage read failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="portal usage unavailable",
        ) from None


__all__ = [
    "CreateKeyRequest",
    "MAX_KEY_PAGE_LIMIT",
    "NO_STORE_HEADERS",
    "PortalKeyIssueResponse",
    "PortalKeyMetadataResponse",
    "PortalKeyPageResponse",
    "PortalMeResponse",
    "PortalUsageResponse",
    "RevokeKeyRequest",
    "RevokeKeyResponse",
    "RotateKeyRequest",
    "get_portal_session",
    "get_portal_usage_service",
    "get_tenant_entitlement_service",
    "get_tenant_key_service",
    "router",
]
