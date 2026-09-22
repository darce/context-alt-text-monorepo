"""Authenticated tenant self-service portal routes."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Final, NoReturn, cast
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.routing import APIRoute
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StrictBool, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.portal_billing import CheckoutAttemptStatus
from db.session import async_session_factory
from db.tenant_context import set_tenant_context
from recognition.application.services.checkout_service import (
    CheckoutActiveConflictError,
    CheckoutAmbiguousError,
    CheckoutFingerprintConflictError,
    CheckoutPaymentsDisabledError,
    CheckoutService,
    InvalidCheckoutRequestError,
)
from recognition.application.services.portal_identity_service import (
    PortalClaimOutcome,
    PortalIdentityClaimError,
    PortalIdentityClaimRefused,
    SqlAlchemyPortalIdentityService,
)
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
from recognition.domain.portal_contracts import BillingSubscriptionStatus, EntitlementStatus, PortalPrincipal
from recognition.infrastructure.repositories.billing_repository import BillingRepository
from recognition.interface_adapters.http.deps.portal_auth import (
    PortalTokenClaims,
    require_portal_principal,
    require_verified_portal_identity,
)
from recognition.interface_adapters.http.deps.portal_composition import (
    BillingRepositoryFactory,
    CheckoutServiceFactory,
)
from recognition.shared.db.dialect import is_postgres

logger = logging.getLogger(__name__)

DEFAULT_KEY_PAGE_LIMIT = 25
MAX_KEY_PAGE_LIMIT = 100
MAX_KEY_LOOKUP_PAGES: Final[int] = 100
NO_STORE_HEADERS = {"Cache-Control": "no-store"}
_SAFE_RETURN_PATH = re.compile(r"^/[A-Za-z0-9/_-]*$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{64,128}$")
_DEFAULT_SUCCESS_PATH = "/billing/return"
_DEFAULT_CANCEL_PATH = "/billing/cancel"
_DEFAULT_MANAGE_PATH = "/billing"
_CLAIM_ERROR_STATUS = {
    "invalid_claim_request": 422,
    "not_admitted": status.HTTP_403_FORBIDDEN,
    "tenant_header_forbidden": status.HTTP_403_FORBIDDEN,
    "csrf_origin_denied": status.HTTP_403_FORBIDDEN,
    "email_unverified": status.HTTP_403_FORBIDDEN,
    "invitation_consumed": status.HTTP_409_CONFLICT,
    "identity_already_bound": status.HTTP_409_CONFLICT,
    "portal_identity_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _http_exception_with_no_store(exc: HTTPException) -> HTTPException:
    headers = dict(exc.headers or {})
    headers.update(NO_STORE_HEADERS)
    return HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers)


class _NoStoreAPIRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                response = await original(request)
            except HTTPException as exc:
                raise _http_exception_with_no_store(exc) from None
            response.headers.update(NO_STORE_HEADERS)
            return response

        return handler


router = APIRouter(prefix="/portal", tags=["portal"])
_me_router = APIRouter(route_class=_NoStoreAPIRoute)


class PortalMeResponse(BaseModel):
    """The identity and tenant binding established by portal authentication."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    issuer: str
    subject: str
    email: str | None


class PortalClaimResponse(BaseModel):
    """Durable onboarding claim result; replay is decided in the claim transaction."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    issuer: str
    subject: str
    email: str | None
    replayed: bool


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
    as_of: datetime | None
    status: EntitlementStatus | None
    data_source: str


class PortalCheckoutRequest(BaseModel):
    """Client checkout intent; catalog and return URLs are server-selected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    plan_code: str = Field(min_length=1)
    return_path: str | None = None


class PortalCheckoutResponse(BaseModel):
    """Durable checkout attempt result; redirects never grant entitlement."""

    model_config = ConfigDict(extra="forbid")

    attempt_id: UUID
    checkout_url: str | None
    status: str
    replayed: bool


class PortalManageRequest(BaseModel):
    """Optional relative return path for the hosted customer portal."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    return_path: str | None = None


class PortalManageResponse(BaseModel):
    """Hosted portal URL for an already-mapped billing customer."""

    model_config = ConfigDict(extra="forbid")

    portal_url: str


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


async def get_claim_session() -> AsyncIterator[AsyncSession]:
    """Provide a request-scoped session that does not take tenant from the client."""
    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_portal_claim_service(
    request: Request,
    session: AsyncSession = Depends(get_claim_session),
) -> SqlAlchemyPortalIdentityService:
    """Resolve the identity service used by invitation claim, without Polar."""
    configured = getattr(request.app.state, "portal_identity_service", None)
    if configured is not None:
        return cast(SqlAlchemyPortalIdentityService, configured)
    entitlement = getattr(request.app.state, "tenant_entitlement_service", None)
    return SqlAlchemyPortalIdentityService(
        session=session,
        beta_grant=getattr(entitlement, "grant_beta", None) if entitlement is not None else None,
        audit_service=getattr(request.app.state, "audit_service", None),
        entitlement_service=entitlement,
    )


def _claim_http_error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code}, headers=dict(NO_STORE_HEADERS))


def _allowed_claim_origins(request: Request) -> frozenset[str]:
    configured = getattr(getattr(request, "app", None), "state", None)
    origins = getattr(configured, "app_allowed_origins", None) if configured is not None else None
    if origins is not None:
        return frozenset(str(item).strip() for item in origins if str(item).strip())
    raw = os.getenv("APP_ALLOWED_ORIGINS", "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _require_claim_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not isinstance(origin, str) or not origin or origin not in _allowed_claim_origins(request):
        raise _claim_http_error(status.HTTP_403_FORBIDDEN, "csrf_origin_denied")


def _reject_claim_tenant_selection(request: Request, payload: Mapping[str, object]) -> None:
    if request.headers.get("x-tenant-id") is not None:
        raise _claim_http_error(status.HTTP_403_FORBIDDEN, "tenant_header_forbidden")
    if "tenant_id" in request.query_params:
        raise _claim_http_error(status.HTTP_403_FORBIDDEN, "tenant_header_forbidden")
    if "tenant_id" in payload or "tenantId" in payload:
        raise _claim_http_error(status.HTTP_403_FORBIDDEN, "tenant_header_forbidden")


def _reject_client_tenant_selection(request: Request, payload: Mapping[str, object]) -> None:
    if "tenant_id" in request.query_params:
        raise _claim_http_error(status.HTTP_403_FORBIDDEN, "tenant_header_forbidden")
    if "tenant_id" in payload or "tenantId" in payload:
        raise _claim_http_error(status.HTTP_403_FORBIDDEN, "tenant_header_forbidden")


def _billing_http_error(
    status_code: int,
    code: str,
    *,
    attempt_id: UUID | None = None,
    retry_after: int | None = None,
) -> HTTPException:
    detail: dict[str, object] = {"code": code}
    if attempt_id is not None:
        detail["attempt_id"] = str(attempt_id)
    headers = dict(NO_STORE_HEADERS)
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return HTTPException(status_code=status_code, detail=detail, headers=headers)


def _payments_enabled(request: Request) -> bool:
    config = getattr(getattr(request, "app", None), "state", None)
    return bool(
        getattr(config, "portal_composition_config", None)
        and getattr(
            getattr(config, "portal_composition_config", None),
            "billing_payments_enabled",
            False,
        )
    )


def _require_payments_enabled(request: Request) -> None:
    if not _payments_enabled(request):
        raise _billing_http_error(status.HTTP_403_FORBIDDEN, "payments_disabled")


def _billing_config(request: Request) -> object:
    config = getattr(getattr(request, "app", None), "state", None)
    return getattr(config, "portal_composition_config", None)


def _validate_return_path(path: str) -> str:
    if not isinstance(path, str) or not _SAFE_RETURN_PATH.fullmatch(path) or "//" in path:
        raise _billing_http_error(422, "invalid_return_path")
    return path


def _absolute_return_url(request: Request, path: str) -> str:
    normalized = _validate_return_path(path)
    config = _billing_config(request)
    origin = str(getattr(config, "app_public_origin", "") or os.getenv("APP_PUBLIC_ORIGIN", "")).rstrip("/")
    if not origin:
        raise _billing_http_error(422, "invalid_return_path")
    url = f"{origin}{normalized}"
    parsed = urlparse(url)
    result_origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed = tuple(getattr(config, "billing_allowed_return_origins", ()) or ())
    if allowed and result_origin not in allowed:
        raise _billing_http_error(422, "invalid_return_path")
    return url


def _client_idempotency_key(request: Request) -> str:
    value = request.headers.get("idempotency-key")
    if not isinstance(value, str) or _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise _billing_http_error(422, "invalid_idempotency_key")
    return value


def _validate_checkout_request(payload: Mapping[str, object]) -> PortalCheckoutRequest:
    try:
        return PortalCheckoutRequest.model_validate(payload)
    except ValidationError:
        raise _billing_http_error(422, "invalid_checkout_request") from None


def _validate_manage_request(payload: Mapping[str, object]) -> PortalManageRequest:
    try:
        return PortalManageRequest.model_validate(payload)
    except ValidationError:
        raise _billing_http_error(422, "invalid_return_path") from None


def _plan_catalog(request: Request) -> Mapping[str, str]:
    catalog = getattr(_billing_config(request), "billing_product_ids", None)
    if isinstance(catalog, Mapping):
        return catalog
    return {}


async def get_checkout_service(
    request: Request,
    session: AsyncSession = Depends(get_portal_session),
) -> CheckoutService:
    """Build a tenant-scoped checkout service from the request session."""
    factory = getattr(request.app.state, "checkout_service", None)
    if isinstance(factory, CheckoutService) or not isinstance(factory, CheckoutServiceFactory):
        raise _billing_http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "checkout_unavailable")
    return factory(session)


async def get_portal_billing_repository(
    request: Request,
    session: AsyncSession = Depends(get_portal_session),
) -> BillingRepository:
    """Build a tenant-scoped billing repository from the request session."""
    factory = getattr(request.app.state, "billing_repository", None)
    if isinstance(factory, BillingRepositoryFactory):
        return factory(session)
    return BillingRepository(session)


async def _claim_payload(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except Exception:
        raise _claim_http_error(422, "invalid_claim_request") from None
    if not isinstance(payload, dict):
        raise _claim_http_error(422, "invalid_claim_request")
    return cast(dict[str, object], payload)


async def _rollback_claim_session(session: AsyncSession) -> None:
    rollback = getattr(session, "rollback", None)
    if callable(rollback):
        await rollback()


def _no_store_error(code: int, detail: object) -> HTTPException:
    return HTTPException(status_code=code, detail=detail, headers=dict(NO_STORE_HEADERS))


def _key_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyNotFoundError):
        return _no_store_error(status.HTTP_404_NOT_FOUND, "portal key not found")
    if isinstance(exc, IdempotencyKeyReuseError):
        return _no_store_error(
            422,
            "idempotency key was reused with a different request",
        )
    if isinstance(exc, InvalidKeyRequestError):
        return _no_store_error(422, "invalid portal key request")
    if isinstance(exc, KeyAlreadyRevokedError):
        return _no_store_error(status.HTTP_409_CONFLICT, "portal key is already revoked")
    if isinstance(exc, KeyAlreadyRotatedError):
        return _no_store_error(status.HTTP_409_CONFLICT, "portal key was already rotated")
    if isinstance(exc, KeyLimitExceededError):
        return _no_store_error(status.HTTP_409_CONFLICT, "tenant key limit reached")
    if isinstance(exc, KeyConflictError):
        return _no_store_error(status.HTTP_409_CONFLICT, "portal key state conflict")
    if isinstance(exc, KeyLifecycleCorruptionError):
        return _no_store_error(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc) or "portal key service unavailable")
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
    async for page in _iter_key_pages(service, tenant_id):
        for result in _page_data(page):
            result_tenant_id = _uuid_value(_attribute(result, "tenant_id"), field_name="tenant_id")
            if result_tenant_id != tenant_id:
                continue
            result_id = _uuid_value(_attribute(result, "api_key_id", "key_id", "id"), field_name="api_key_id")
            if result_id == api_key_id:
                return result
    return None


async def _iter_key_pages(service: TenantKeyService, tenant_id: UUID) -> AsyncIterator[object]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(MAX_KEY_LOOKUP_PAGES):
        page = await service.list_keys(
            tenant_id,
            cursor=cursor,
            limit=MAX_KEY_PAGE_LIMIT,
            include_revoked=True,
        )
        yield page
        next_cursor = _attribute(page, "next_cursor")
        if next_cursor is None:
            return
        if not isinstance(next_cursor, str) or not next_cursor:
            raise KeyLifecycleCorruptionError("portal key page cursor is invalid")
        if next_cursor == cursor or next_cursor in seen_cursors:
            raise KeyLifecycleCorruptionError("portal key page cursor repeated")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise KeyLifecycleCorruptionError("portal key lookup page bound reached")


async def _last_usable_key(
    service: TenantKeyService,
    tenant_id: UUID,
    api_key_id: UUID,
) -> bool:
    target_seen = False
    usable_count = 0
    now = _utc_now()
    async for page in _iter_key_pages(service, tenant_id):
        for row in _page_data(page):
            row_tenant_id = _uuid_value(_attribute(row, "tenant_id"), field_name="tenant_id")
            if row_tenant_id != tenant_id:
                continue
            row_id = _uuid_value(_attribute(row, "api_key_id", "key_id", "id"), field_name="api_key_id")
            if row_id == api_key_id:
                target_seen = True
            if _is_usable(row, now=now):
                usable_count += 1
    return target_seen and usable_count == 1


@_me_router.get("/me", response_model=PortalMeResponse)
async def portal_me(
    response: Response,
    principal: PortalPrincipal = Depends(require_portal_principal),
) -> PortalMeResponse:
    """Return the authenticated principal's authoritative tenant binding."""
    response.headers.update(NO_STORE_HEADERS)
    return PortalMeResponse(
        tenant_id=principal.tenant_id,
        issuer=principal.issuer,
        subject=principal.subject,
        email=principal.email,
    )


router.include_router(_me_router)


@router.post("/onboarding/claim", response_model=PortalClaimResponse)
async def portal_onboarding_claim(
    request: Request,
    response: Response,
    claims: PortalTokenClaims = Depends(require_verified_portal_identity),
    service: SqlAlchemyPortalIdentityService = Depends(get_portal_claim_service),
    session: AsyncSession = Depends(get_claim_session),
) -> PortalClaimResponse:
    """Redeem one invitation into a local tenant without billing-provider calls or client tenant selection."""
    response.headers.update(NO_STORE_HEADERS)
    _require_claim_origin(request)
    payload = await _claim_payload(request)
    _reject_claim_tenant_selection(request, payload)
    if getattr(claims, "email_verified", False) is not True:
        raise _claim_http_error(status.HTTP_403_FORBIDDEN, "email_unverified")
    token = payload.get("invitation_token")
    if not isinstance(token, str) or not token.strip():
        raise _claim_http_error(422, "invalid_claim_request")
    try:
        outcome = await service.claim_onboarding(
            issuer=claims.issuer,
            subject=claims.subject,
            email=claims.email,
            invitation_token=token,
        )
    except HTTPException:
        raise
    except PortalIdentityClaimError as exc:
        await _rollback_claim_session(session)
        raise _claim_http_error(
            _CLAIM_ERROR_STATUS.get(exc.code, status.HTTP_503_SERVICE_UNAVAILABLE),
            exc.code if exc.code in _CLAIM_ERROR_STATUS else "portal_identity_unavailable",
        ) from None
    except PortalIdentityClaimRefused:
        await _rollback_claim_session(session)
        raise _claim_http_error(status.HTTP_403_FORBIDDEN, "not_admitted") from None
    except TimeoutError:
        await _rollback_claim_session(session)
        raise _claim_http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "portal_identity_unavailable") from None
    except Exception:
        await _rollback_claim_session(session)
        logger.exception("Portal onboarding claim failed")
        raise _claim_http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "portal_identity_unavailable") from None
    if not isinstance(outcome, PortalClaimOutcome):
        await _rollback_claim_session(session)
        raise _claim_http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "portal_identity_unavailable")
    commit = getattr(session, "commit", None)
    if callable(commit):
        await commit()
    response.status_code = status.HTTP_200_OK if outcome.replayed else status.HTTP_201_CREATED
    return PortalClaimResponse(
        tenant_id=outcome.principal.tenant_id,
        issuer=outcome.principal.issuer,
        subject=outcome.principal.subject,
        email=outcome.principal.email,
        replayed=outcome.replayed,
    )


def _checkout_status(result: object) -> str:
    value = getattr(result, "status", None)
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _map_checkout_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CheckoutPaymentsDisabledError):
        return _billing_http_error(status.HTTP_403_FORBIDDEN, "payments_disabled")
    if isinstance(exc, CheckoutFingerprintConflictError):
        return _billing_http_error(422, "idempotency_key_reuse")
    if isinstance(exc, CheckoutAmbiguousError):
        if exc.__cause__ is not None:
            return _billing_http_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "checkout_ambiguous",
                attempt_id=exc.attempt_id,
                retry_after=1,
            )
        return _billing_http_error(status.HTTP_409_CONFLICT, "checkout_ambiguous", attempt_id=exc.attempt_id)
    if isinstance(exc, CheckoutActiveConflictError):
        return _billing_http_error(status.HTTP_409_CONFLICT, "checkout_ambiguous")
    if isinstance(exc, InvalidCheckoutRequestError):
        return _billing_http_error(422, "invalid_checkout_request")
    return _billing_http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "checkout_unavailable")


@router.post("/billing/checkout", response_model=PortalCheckoutResponse)
async def portal_billing_checkout(
    request: Request,
    response: Response,
    principal: PortalPrincipal = Depends(require_portal_principal),
    session: AsyncSession = Depends(get_portal_session),
    billing_repository: BillingRepository = Depends(get_portal_billing_repository),
) -> PortalCheckoutResponse:
    """Create or replay a durable hosted checkout without granting entitlement from the redirect."""
    response.headers.update(NO_STORE_HEADERS)
    _require_claim_origin(request)
    payload = await _claim_payload(request)
    _reject_client_tenant_selection(request, payload)
    _require_payments_enabled(request)
    body = _validate_checkout_request(payload)
    if body.plan_code not in _plan_catalog(request):
        raise _billing_http_error(422, "unknown_plan_code")
    success_url = _absolute_return_url(request, body.return_path or _DEFAULT_SUCCESS_PATH)
    cancel_url = _absolute_return_url(request, _DEFAULT_CANCEL_PATH)
    service = await get_checkout_service(request, session)
    client_key = _client_idempotency_key(request)
    try:
        result = await service.replay_existing_checkout(
            tenant_id=principal.tenant_id,
            plan_code=body.plan_code,
            success_url=success_url,
            cancel_url=cancel_url,
            client_idempotency_key=client_key,
        )
        if result is None:
            projection = await billing_repository.get_projection(principal.tenant_id)
            if projection is not None and projection.status == BillingSubscriptionStatus.ACTIVE.value:
                raise _billing_http_error(status.HTTP_409_CONFLICT, "already_subscribed")
            result = await service.create_checkout(
                tenant_id=principal.tenant_id,
                plan_code=body.plan_code,
                success_url=success_url,
                cancel_url=cancel_url,
                client_idempotency_key=client_key,
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_checkout_error(exc) from None
    status_value = _checkout_status(result)
    checkout_url = None if status_value == CheckoutAttemptStatus.SUCCEEDED.value else result.checkout_url
    return PortalCheckoutResponse(
        attempt_id=result.attempt_id,
        checkout_url=checkout_url,
        status=status_value,
        replayed=bool(result.replayed),
    )


@router.post("/billing/manage", response_model=PortalManageResponse)
async def portal_billing_manage(
    request: Request,
    response: Response,
    principal: PortalPrincipal = Depends(require_portal_principal),
    billing_repository: BillingRepository = Depends(get_portal_billing_repository),
) -> PortalManageResponse:
    """Open the hosted customer portal only after a tenant billing mapping exists."""
    response.headers.update(NO_STORE_HEADERS)
    _require_claim_origin(request)
    payload = await _claim_payload(request)
    _reject_client_tenant_selection(request, payload)
    _require_payments_enabled(request)
    body = _validate_manage_request(payload)
    return_url = _absolute_return_url(request, body.return_path or _DEFAULT_MANAGE_PATH)
    projection = await billing_repository.get_projection(principal.tenant_id)
    if projection is None or not projection.provider_customer_id:
        raise _billing_http_error(status.HTTP_409_CONFLICT, "billing_customer_missing")
    provider = getattr(request.app.state, "billing_provider", None)
    create_portal_session = getattr(provider, "create_portal_session", None)
    if not callable(create_portal_session):
        raise _billing_http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "billing_portal_unavailable")
    try:
        portal_url = await create_portal_session(tenant_id=principal.tenant_id, return_url=return_url)
    except Exception:
        raise _billing_http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "billing_portal_unavailable") from None
    if not isinstance(portal_url, str) or not portal_url:
        raise _billing_http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "billing_portal_unavailable")
    return PortalManageResponse(portal_url=portal_url)


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
    session: AsyncSession = Depends(get_portal_session),
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
        await session.commit()
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
    session: AsyncSession = Depends(get_portal_session),
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
        await session.commit()
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
    session: AsyncSession = Depends(get_portal_session),
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
        await session.commit()
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
        stale = _attribute(source, "stale", "pending", default=False) is True
        missing_split = reserved is None
        if source is entitlement:
            data_source = "authoritative"
        elif not isinstance(data_source, str) or not data_source:
            data_source = "pending" if stale or missing_split else "authoritative"
        source_status = _attribute(source, "status", default=None)
        status_value = source_status.value if hasattr(source_status, "value") else source_status
        try:
            usage_status = EntitlementStatus(status_value) if isinstance(status_value, str) else None
        except ValueError:
            usage_status = None
        as_of = _datetime_value(source, "as_of", "observed_at", "updated_at")

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
            status=usage_status,
            data_source=cast(str, data_source),
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
    "MAX_KEY_LOOKUP_PAGES",
    "NO_STORE_HEADERS",
    "PortalClaimResponse",
    "PortalKeyIssueResponse",
    "PortalKeyMetadataResponse",
    "PortalKeyPageResponse",
    "PortalMeResponse",
    "PortalUsageResponse",
    "RevokeKeyRequest",
    "RevokeKeyResponse",
    "RotateKeyRequest",
    "get_checkout_service",
    "get_claim_session",
    "get_portal_billing_repository",
    "get_portal_claim_service",
    "get_portal_session",
    "get_portal_usage_service",
    "get_tenant_entitlement_service",
    "get_tenant_key_service",
    "portal_billing_checkout",
    "portal_billing_manage",
    "portal_onboarding_claim",
    "router",
]
