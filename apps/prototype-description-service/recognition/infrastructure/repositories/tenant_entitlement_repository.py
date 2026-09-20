"""Tenant-scoped persistence for portal entitlements."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TenantEntitlement, UsageReservation
from recognition.domain.portal_contracts import EntitlementStatus, UsageReservationStatus

_DEFAULT_OPERATION_TIMEOUT_S = 5.0


class TenantEntitlementTimeoutError(TimeoutError):
    """A tenant entitlement database operation exceeded its deadline."""


async def _with_timeout[T](awaitable: Awaitable[T], *, timeout_s: float, operation: str) -> T:
    """Bound every blocking database await in this repository."""
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_s)
    except TimeoutError as exc:
        raise TenantEntitlementTimeoutError(f"tenant entitlement operation timed out: {operation}") from exc


def _validate_timeout(timeout_s: float) -> float:
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        raise ValueError("timeout_s must be a finite positive number")
    value = float(timeout_s)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout_s must be a finite positive number")
    return value


def _validate_tenant_id(tenant_id: UUID) -> UUID:
    if not isinstance(tenant_id, UUID):
        raise ValueError("tenant_id must be a UUID")
    return tenant_id


def _as_utc(value: datetime) -> datetime:
    """Normalize timestamps returned by SQLite, which drops timezone metadata."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dialect_name(session: object) -> str | None:
    bind = getattr(session, "bind", None)
    if bind is None:
        sync_session = getattr(session, "sync_session", None)
        bind = getattr(sync_session, "bind", None)
    dialect = getattr(bind, "dialect", None)
    name = getattr(dialect, "name", None)
    return str(name) if name is not None else None


class SqlAlchemyTenantEntitlementRepository:
    """Persist one entitlement projection per tenant.

    The caller owns the surrounding transaction.  Mutations flush before they
    return so the application service can perform a read-after-write snapshot
    and write an audit event in that same transaction.
    """

    def __init__(self, session: AsyncSession, *, timeout_s: float = _DEFAULT_OPERATION_TIMEOUT_S) -> None:
        self._session = session
        self._timeout_s = _validate_timeout(timeout_s)

    @property
    def session(self) -> AsyncSession:
        """Expose the request-scoped session to the transactional audit seam."""
        return self._session

    async def get(self, tenant_id: UUID, *, for_update: bool = False) -> TenantEntitlement | None:
        """Return the singleton entitlement row for exactly one tenant."""
        tenant_uuid = _validate_tenant_id(tenant_id)
        stmt = select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_uuid).limit(1)
        if for_update:
            stmt = stmt.with_for_update()
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation="load tenant entitlement",
        )
        return result.scalar_one_or_none()

    async def used_jobs(self, tenant_id: UUID, period_start: datetime) -> int:
        """Return chargeable usage for one tenant and one entitlement period."""
        tenant_uuid = _validate_tenant_id(tenant_id)
        normalized_period_start = _as_utc(period_start)
        stmt = (
            select(func.coalesce(func.sum(UsageReservation.cost_units), 0))
            .where(
                UsageReservation.tenant_id == tenant_uuid,
                UsageReservation.period_start == normalized_period_start,
                UsageReservation.status.in_((UsageReservationStatus.RESERVED, UsageReservationStatus.COMMITTED)),
            )
            .limit(1)
        )
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation="calculate tenant entitlement usage",
        )
        return int(result.scalar_one() or 0)

    async def get_used_jobs(self, tenant_id: UUID, period_start: datetime) -> int:
        """Compatibility spelling for callers that name the aggregate explicitly."""
        return await self.used_jobs(tenant_id, period_start)

    async def upsert_beta(
        self,
        tenant_id: UUID,
        *,
        allowance_jobs: int,
        allowance_version: str,
        period_start: datetime,
        period_end: datetime,
        source: str,
    ) -> TenantEntitlement:
        """Atomically insert or replace the entitlement for one tenant."""
        tenant_uuid = _validate_tenant_id(tenant_id)
        values: dict[str, Any] = {
            "id": uuid4(),
            "tenant_id": tenant_uuid,
            "plan_code": "beta",
            "allowance_version": allowance_version,
            "allowance_jobs": allowance_jobs,
            "period_start": _as_utc(period_start),
            "period_end": _as_utc(period_end),
            "status": EntitlementStatus.BETA_ACTIVE,
            "source": source,
            "grace_until": None,
        }

        dialect_name = _dialect_name(self._session)
        insert_statement: Any = None
        if dialect_name == "postgresql":
            insert_statement = postgres_insert(TenantEntitlement).values(**values)
        elif dialect_name == "sqlite":
            insert_statement = sqlite_insert(TenantEntitlement).values(**values)

        if insert_statement is not None:
            excluded = insert_statement.excluded
            statement = insert_statement.on_conflict_do_update(
                index_elements=[TenantEntitlement.tenant_id],
                set_={
                    "plan_code": excluded.plan_code,
                    "allowance_version": excluded.allowance_version,
                    "allowance_jobs": excluded.allowance_jobs,
                    "period_start": excluded.period_start,
                    "period_end": excluded.period_end,
                    "status": excluded.status,
                    "source": excluded.source,
                    "grace_until": excluded.grace_until,
                },
            )
            await _with_timeout(
                self._session.execute(statement),
                timeout_s=self._timeout_s,
                operation="upsert beta entitlement",
            )
        else:
            # Test doubles and uncommon SQLAlchemy dialects do not expose a
            # dialect-specific ON CONFLICT builder.  Keep their behavior
            # tenant-bound while production PostgreSQL/SQLite use the atomic
            # database upsert above.
            row = await self.get(tenant_uuid, for_update=True)
            if row is None:
                row = TenantEntitlement(**values)
                self._session.add(row)
            else:
                self._set_beta_values(row, values)

        await _with_timeout(
            self._session.flush(),
            timeout_s=self._timeout_s,
            operation="flush beta entitlement",
        )
        row = await self.get(tenant_uuid)
        if row is None:
            raise RuntimeError("beta entitlement upsert returned no tenant row")
        return row

    async def upsert(self, tenant_id: UUID, **values: Any) -> TenantEntitlement:
        """Compatibility spelling for the beta entitlement upsert."""
        return await self.upsert_beta(tenant_id, **values)

    async def apply_billing_state(
        self,
        tenant_id: UUID,
        *,
        status: EntitlementStatus,
        now: datetime,
        period_end: datetime | None,
        plan_code: str = "paid",
        source: str = "billing",
        grace_until: datetime | None = None,
    ) -> TenantEntitlement:
        """Map billing state without resetting usage from a current period."""
        tenant_uuid = _validate_tenant_id(tenant_id)
        normalized_now = _as_utc(now)
        normalized_period_end = _as_utc(period_end) if period_end is not None else None
        normalized_grace_until = _as_utc(grace_until) if grace_until is not None else None
        row = await self.get(tenant_uuid, for_update=True)

        if row is None:
            row = TenantEntitlement(
                id=uuid4(),
                tenant_id=tenant_uuid,
                plan_code=plan_code,
                allowance_version="billing",
                allowance_jobs=0,
                period_start=normalized_now,
                period_end=normalized_period_end or normalized_now,
                status=status,
                source=source,
                grace_until=normalized_grace_until,
            )
            self._session.add(row)
        else:
            existing_period_start = _as_utc(row.period_start)
            existing_period_end = _as_utc(row.period_end)
            existing_grace_until = _as_utc(row.grace_until) if row.grace_until is not None else None
            current_period = existing_period_start <= normalized_now and (
                normalized_now < existing_period_end
                or (existing_grace_until is not None and normalized_now <= existing_grace_until)
            )
            if not current_period:
                row.period_start = normalized_now
            row.period_end = normalized_period_end or row.period_end
            row.plan_code = plan_code
            row.status = status
            row.source = source
            row.grace_until = normalized_grace_until

        await _with_timeout(
            self._session.flush(),
            timeout_s=self._timeout_s,
            operation="flush billing entitlement",
        )
        row = await self.get(tenant_uuid)
        if row is None:
            raise RuntimeError("billing state update returned no tenant row")
        return row

    @staticmethod
    def _set_beta_values(row: TenantEntitlement, values: dict[str, Any]) -> None:
        row.plan_code = values["plan_code"]
        row.allowance_version = values["allowance_version"]
        row.allowance_jobs = values["allowance_jobs"]
        row.period_start = values["period_start"]
        row.period_end = values["period_end"]
        row.status = values["status"]
        row.source = values["source"]
        row.grace_until = values["grace_until"]


TenantEntitlementRepository = SqlAlchemyTenantEntitlementRepository
TenantEntitlementRepositoryImpl = SqlAlchemyTenantEntitlementRepository


__all__ = [
    "SqlAlchemyTenantEntitlementRepository",
    "TenantEntitlementRepository",
    "TenantEntitlementRepositoryImpl",
    "TenantEntitlementTimeoutError",
]
