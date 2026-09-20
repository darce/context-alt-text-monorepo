"""Application service for tenant-bound beta and billing entitlements."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.audit_service import AuditService
from recognition.config.settings import RecognitionSettings
from recognition.domain.portal_contracts import (
    DEFAULT_ALLOWANCE_JOBS,
    DEFAULT_ENTITLEMENT_STATUS,
    BillingState,
    BillingSubscriptionStatus,
    EntitlementSnapshot,
    EntitlementStatus,
)
from recognition.infrastructure.repositories.tenant_entitlement_repository import (
    SqlAlchemyTenantEntitlementRepository,
    TenantEntitlementTimeoutError,
)

_DEFAULT_OPERATION_TIMEOUT_S = 5.0
_BETA_PLAN_CODE = "beta"
_PAID_PLAN_CODE = "paid"
_BETA_AUDIT_EVENT = "tenant.entitlement.grant_beta"
_AUDIT_ACTOR = "tenant-entitlement-service"
_AUDIT_SCOPE = "tenant.entitlement"
_ACTIVE_ENTITLEMENT_STATUSES = (EntitlementStatus.BETA_ACTIVE, EntitlementStatus.PAID_ACTIVE)

_BILLING_TO_ENTITLEMENT_STATUS: dict[BillingSubscriptionStatus, EntitlementStatus] = {
    BillingSubscriptionStatus.NONE: EntitlementStatus.EXPIRED,
    BillingSubscriptionStatus.ACTIVE: EntitlementStatus.PAID_ACTIVE,
    BillingSubscriptionStatus.PAST_DUE: EntitlementStatus.PAST_DUE,
    BillingSubscriptionStatus.CANCELED: EntitlementStatus.EXPIRED,
    BillingSubscriptionStatus.REFUND_HOLD: EntitlementStatus.REVOKED,
}


class InvalidEntitlementRequestError(ValueError):
    """The caller supplied invalid or cross-tenant entitlement data."""


def _utc_now() -> datetime:
    """Default wall clock; application methods always call the injected clock."""
    return datetime.now(tz=UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validate_timeout(timeout_s: float) -> float:
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        raise ValueError("timeout_s must be a finite positive number")
    value = float(timeout_s)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout_s must be a finite positive number")
    return value


def _validate_tenant_id(tenant_id: UUID) -> UUID:
    if not isinstance(tenant_id, UUID):
        raise InvalidEntitlementRequestError("tenant_id must be a UUID")
    return tenant_id


def _validate_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidEntitlementRequestError(f"{field_name} must be a non-empty string")
    return value.strip()


def _validate_period(period_start: datetime, period_end: datetime) -> tuple[datetime, datetime]:
    if not isinstance(period_start, datetime) or not isinstance(period_end, datetime):
        raise InvalidEntitlementRequestError("period_start and period_end must be datetimes")
    normalized_start = _as_utc(period_start)
    normalized_end = _as_utc(period_end)
    if normalized_start >= normalized_end:
        raise InvalidEntitlementRequestError("period_end must be after period_start")
    return normalized_start, normalized_end


def _clock_read(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime):
        raise InvalidEntitlementRequestError("clock must return a datetime")
    return _as_utc(value)


def _settings_plan_allowances(settings: object) -> Mapping[str, int] | None:
    """Read the billable plan table without coupling to settings internals."""
    for field_name in ("plan_allowances", "allowance_by_plan", "entitlement_plan_allowances"):
        configured = getattr(settings, field_name, None)
        if configured is not None:
            return configured
    return None


def _settings_past_due_grace_s(settings: object) -> float | None:
    """Read the past-due grace window without coupling to settings internals."""
    for field_name in ("past_due_grace_seconds", "past_due_grace_s"):
        configured = getattr(settings, field_name, None)
        if configured is not None:
            return float(configured)
    return None


class TenantEntitlementService:
    """Implement the published tenant entitlement protocol.

    The surrounding request owns transaction commit.  A beta grant flushes the
    entitlement and its audit row before returning; a caller rollback therefore
    removes both writes when either operation fails.
    """

    def __init__(
        self,
        session_or_repository: AsyncSession | Any | None = None,
        *,
        session: AsyncSession | None = None,
        repository: Any | None = None,
        audit_service: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout_s: float = _DEFAULT_OPERATION_TIMEOUT_S,
        settings: object | None = None,
        plan_allowances: Mapping[str, int] | None = None,
    ) -> None:
        if session_or_repository is not None and (session is not None or repository is not None):
            raise ValueError("provide one session or repository")
        if session is not None and repository is not None:
            raise ValueError("provide a session or repository, not both")
        if clock is not None and not callable(clock):
            raise ValueError("clock must be callable")
        if settings is not None and plan_allowances is not None:
            raise ValueError("provide settings or plan_allowances, not both")

        self._timeout_s = _validate_timeout(timeout_s)
        candidate: Any = repository if repository is not None else session
        if candidate is None:
            candidate = session_or_repository
        if candidate is None:
            raise ValueError("a database session or tenant entitlement repository is required")

        repository_methods = {
            name: callable(getattr(candidate, name, None))
            for name in ("get", "upsert_beta", "upsert", "apply_billing_state", "used_jobs", "get_used_jobs")
        }
        if (
            repository_methods["get"]
            and (repository_methods["upsert_beta"] or repository_methods["upsert"])
            and repository_methods["apply_billing_state"]
            and (repository_methods["used_jobs"] or repository_methods["get_used_jobs"])
        ):
            self._repository = candidate
            self._session = getattr(candidate, "session", None)
        else:
            self._session = candidate
            configured_settings = settings
            if plan_allowances is None:
                if configured_settings is None:
                    configured_settings = RecognitionSettings()
                plan_allowances = _settings_plan_allowances(configured_settings)
            if plan_allowances is None:
                raise ValueError("RecognitionSettings must configure plan_allowances for paid entitlements")
            self._repository = SqlAlchemyTenantEntitlementRepository(
                candidate,
                timeout_s=self._timeout_s,
                plan_allowances=plan_allowances,
                past_due_grace_s=_settings_past_due_grace_s(configured_settings),
            )

        self._clock = clock or _utc_now
        self._audit_service = audit_service
        if self._audit_service is None and self._session is not None:
            self._audit_service = AuditService()

    async def _call[T](self, awaitable: Awaitable[T], *, operation: str) -> T:
        try:
            return await asyncio.wait_for(awaitable, timeout=self._timeout_s)
        except TimeoutError as exc:
            raise TenantEntitlementTimeoutError(f"tenant entitlement operation timed out: {operation}") from exc

    def _now(self) -> datetime:
        return _clock_read(self._clock)

    async def snapshot(self, tenant_id: UUID) -> EntitlementSnapshot:
        """Return a closed snapshot unless current, active evidence exists."""
        tenant_uuid = _validate_tenant_id(tenant_id)
        now = self._now()
        row = await self._call(
            self._repository.get(tenant_uuid),
            operation="load entitlement snapshot",
        )
        if row is None:
            return self._default_snapshot(tenant_uuid, now)

        try:
            period_start = _as_utc(row.period_start)
            period_end = _as_utc(row.period_end)
        except (AttributeError, TypeError, ValueError) as exc:
            raise InvalidEntitlementRequestError("persisted entitlement period is invalid") from exc
        grace_until = _as_utc(row.grace_until) if row.grace_until is not None else None

        try:
            status = EntitlementStatus(row.status)
        except (TypeError, ValueError):
            return self._default_snapshot(tenant_uuid, now, period_start=period_start, period_end=period_end)

        period_current = period_start <= now < period_end
        grace_current = period_end <= now and grace_until is not None and now <= grace_until
        if not (period_current or grace_current):
            return self._default_snapshot(tenant_uuid, now, period_start=period_start, period_end=period_end)

        allowance_jobs = max(0, int(row.allowance_jobs))
        # Plan 0001 promises a past-due customer a fixed grace window to fix their card;
        # cutting the allowance to zero the moment the first payment fails defeats it.
        within_past_due_grace = status is EntitlementStatus.PAST_DUE and grace_until is not None and now <= grace_until
        if status not in _ACTIVE_ENTITLEMENT_STATUSES and not within_past_due_grace:
            return EntitlementSnapshot(
                tenant_id=tenant_uuid,
                status=status,
                allowance_jobs=DEFAULT_ALLOWANCE_JOBS,
                used_jobs=0,
                period_start=period_start,
                period_end=period_end,
                grace_until=grace_until,
            )

        usage_getter = getattr(self._repository, "used_jobs", None) or self._repository.get_used_jobs
        used_jobs = await self._call(
            usage_getter(tenant_uuid, period_start),
            operation="load entitlement usage",
        )
        return EntitlementSnapshot(
            tenant_id=tenant_uuid,
            status=status,
            allowance_jobs=allowance_jobs,
            used_jobs=max(0, int(used_jobs)),
            period_start=period_start,
            period_end=period_end,
            grace_until=grace_until,
        )

    async def grant_beta(
        self,
        tenant_id: UUID,
        *,
        allowance_jobs: int,
        allowance_version: str,
        period_start: datetime,
        period_end: datetime,
        source: str,
    ) -> EntitlementSnapshot:
        """Audited, tenant-bound beta grant with one-row upsert semantics."""
        tenant_uuid = _validate_tenant_id(tenant_id)
        if isinstance(allowance_jobs, bool) or not isinstance(allowance_jobs, int) or allowance_jobs < 0:
            raise InvalidEntitlementRequestError("allowance_jobs must be a non-negative integer")
        version = _validate_text(allowance_version, "allowance_version")
        grant_source = _validate_text(source, "source")
        normalized_start, normalized_end = _validate_period(period_start, period_end)

        upsert = getattr(self._repository, "upsert_beta", None) or self._repository.upsert
        await self._call(
            upsert(
                tenant_uuid,
                allowance_jobs=allowance_jobs,
                allowance_version=version,
                period_start=normalized_start,
                period_end=normalized_end,
                source=grant_source,
            ),
            operation="upsert beta entitlement",
        )
        await self._record_grant_audit(
            tenant_uuid,
            allowance_jobs=allowance_jobs,
            allowance_version=version,
            period_start=normalized_start,
            period_end=normalized_end,
            source=grant_source,
        )
        return await self.snapshot(tenant_uuid)

    async def _record_grant_audit(
        self,
        tenant_id: UUID,
        *,
        allowance_jobs: int,
        allowance_version: str,
        period_start: datetime,
        period_end: datetime,
        source: str,
    ) -> None:
        if self._audit_service is None or self._session is None:
            raise RuntimeError("audited beta grants require a transactional audit service")
        await self._call(
            self._audit_service.record_event(
                self._session,
                tenant_id=str(tenant_id),
                event_type=_BETA_AUDIT_EVENT,
                actor=_AUDIT_ACTOR,
                scope=_AUDIT_SCOPE,
                payload={
                    "allowance_jobs": allowance_jobs,
                    "allowance_version": allowance_version,
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "source": source,
                    "plan_code": _BETA_PLAN_CODE,
                },
            ),
            operation="write beta entitlement audit",
        )

    async def apply_billing_state(self, tenant_id: UUID, state: BillingState) -> EntitlementSnapshot:
        """Map authoritative billing state without billing prior beta usage."""
        tenant_uuid = _validate_tenant_id(tenant_id)
        if not isinstance(state, BillingState):
            raise InvalidEntitlementRequestError("state must be a BillingState")
        if state.tenant_id != tenant_uuid:
            raise InvalidEntitlementRequestError("state tenant_id must match tenant_id")
        try:
            billing_status = BillingSubscriptionStatus(state.status)
        except (TypeError, ValueError) as exc:
            raise InvalidEntitlementRequestError("state status is not a known billing status") from exc

        now = self._now()
        period_end = _as_utc(state.current_period_end) if state.current_period_end is not None else None
        entitlement_status = _BILLING_TO_ENTITLEMENT_STATUS[billing_status]
        await self._call(
            self._repository.apply_billing_state(
                tenant_uuid,
                status=entitlement_status,
                now=now,
                period_end=period_end,
                plan_code=_PAID_PLAN_CODE,
                source="billing",
                grace_until=None,
            ),
            operation="apply billing entitlement",
        )
        return await self.snapshot(tenant_uuid)

    def _default_snapshot(
        self,
        tenant_id: UUID,
        now: datetime,
        *,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> EntitlementSnapshot:
        return EntitlementSnapshot(
            tenant_id=tenant_id,
            status=DEFAULT_ENTITLEMENT_STATUS,
            allowance_jobs=DEFAULT_ALLOWANCE_JOBS,
            used_jobs=0,
            period_start=period_start or now,
            period_end=period_end or now,
            grace_until=None,
        )


# Keep the concrete class discoverable under names commonly used by wiring code
# while retaining the published protocol name on this module.
SqlAlchemyTenantEntitlementService = TenantEntitlementService
TenantEntitlementServiceImpl = TenantEntitlementService


__all__ = [
    "InvalidEntitlementRequestError",
    "SqlAlchemyTenantEntitlementService",
    "TenantEntitlementService",
    "TenantEntitlementServiceImpl",
]
