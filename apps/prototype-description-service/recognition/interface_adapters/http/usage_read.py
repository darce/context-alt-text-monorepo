"""Single tenant usage read shared by the portal and site-key tenant routes.

``GET /portal/usage`` (Clerk session) and ``GET /recognition/tenant/usage``
(tenant API key) differ only in how they resolve the tenant. Both call
:func:`build_tenant_usage`, so ``remaining`` and the provenance fields have one
reading. The wire contract is
``packages/shared-contracts/schemas/tenant-usage-response.schema.json``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel, ConfigDict, NonNegativeInt
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.tenant_entitlement_service import TenantEntitlementService
from recognition.domain.portal_contracts import EntitlementStatus


class PortalUsagePeriodResponse(BaseModel):
    """The entitlement period represented by a usage read."""

    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime


class PortalUsageResponse(BaseModel):
    """Tenant usage with explicit freshness and observation timestamp."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    used: NonNegativeInt | None
    reserved: NonNegativeInt | None
    remaining: NonNegativeInt | None
    allowance: NonNegativeInt | None
    period_start: datetime
    period_end: datetime
    period: PortalUsagePeriodResponse
    as_of: datetime | None
    status: EntitlementStatus | None
    data_source: str


def resolve_tenant_entitlement_service(request: Request, session: AsyncSession) -> TenantEntitlementService:
    """Return the injected entitlement service, or one bound to the tenant-scoped session."""
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


def _count_value(source: object, *names: str) -> int | None:
    value = _attribute(source, *names)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _datetime_value(source: object, *names: str) -> datetime | None:
    value = _attribute(source, *names)
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


async def build_tenant_usage(
    tenant_id: UUID,
    entitlement_service: TenantEntitlementService,
    usage_service: object | None,
) -> PortalUsageResponse:
    """Read tenant entitlement usage without substituting fabricated counts.

    Raises when the entitlement or its period cannot be read; each route maps
    that to its own 503 so no partial body is ever returned.
    """
    entitlement = await entitlement_service.snapshot(tenant_id)
    projection = await _read_usage_projection(usage_service, tenant_id)
    source = projection if projection is not None else entitlement

    period_start, period_end = _usage_period(source)
    if period_start is None or period_end is None:
        period_start, period_end = _usage_period(entitlement)
    if period_start is None or period_end is None:
        raise RuntimeError("usage period unavailable")

    # A count the reader does not supply stays null; remaining is never derived
    # from used/reserved/allowance (tenant-usage-response.schema.json).
    used = _count_value(source, "used", "used_jobs", "committed", "committed_jobs")
    reserved = _count_value(source, "reserved", "reserved_jobs")
    allowance = _count_value(source, "allowance", "allowance_jobs", "limit", "quota")
    remaining = _count_value(source, "remaining", "remaining_jobs")
    if allowance is None:
        allowance = _count_value(entitlement, "allowance", "allowance_jobs", "limit", "quota")

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
        tenant_id=tenant_id,
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


__all__ = [
    "PortalUsagePeriodResponse",
    "PortalUsageResponse",
    "build_tenant_usage",
    "get_portal_usage_service",
    "resolve_tenant_entitlement_service",
]
