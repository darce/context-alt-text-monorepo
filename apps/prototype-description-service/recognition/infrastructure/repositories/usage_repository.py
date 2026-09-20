"""Persistence primitives for tenant usage reservations.

The entitlement row is the serialization point for admission.  A reservation
transaction locks that row before reading the period total, so concurrent
callers cannot all observe the same remaining allowance and then insert.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TenantEntitlement, UsageReservation
from recognition.domain.portal_contracts import (
    EntitlementStatus,
    UsageReservationStatus,
    UsageTicket,
)

_DEFAULT_OPERATION_TIMEOUT_S = 5.0
_ACTIVE_ENTITLEMENT_STATUSES = (
    EntitlementStatus.BETA_ACTIVE,
    EntitlementStatus.PAID_ACTIVE,
)
_CHARGEABLE_RESERVATION_STATUSES = (
    UsageReservationStatus.RESERVED,
    UsageReservationStatus.COMMITTED,
)
_TERMINAL_RESERVATION_STATUSES = (
    UsageReservationStatus.COMMITTED,
    UsageReservationStatus.RELEASED,
    UsageReservationStatus.EXPIRED,
)


class UsageAdmissionError(RuntimeError):
    """Base class for usage admission failures."""


class InvalidUsageRequestError(ValueError):
    """The caller supplied an invalid usage request or ticket."""


class AllowanceExceededError(UsageAdmissionError):
    """No active entitlement has enough remaining allowance."""


class ReservationNotFoundError(LookupError):
    """A completion ticket does not identify a reservation for its tenant."""


class UsageAdmissionTimeoutError(TimeoutError):
    """A database operation exceeded the admission operation deadline."""


async def _with_timeout[T](awaitable: Awaitable[T], *, timeout_s: float, operation: str) -> T:
    """Bound every database await used by this repository."""
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_s)
    except TimeoutError as exc:
        raise UsageAdmissionTimeoutError(f"usage admission database operation timed out: {operation}") from exc


def _validate_timeout(timeout_s: float) -> float:
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        raise ValueError("timeout_s must be a finite positive number")
    value = float(timeout_s)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout_s must be a finite positive number")
    return value


class SqlAlchemyUsageRepository:
    """Persist usage reservations through a request-scoped async session.

    The caller owns the surrounding transaction and commit.  ``reserve``
    flushes its insert before returning so the returned ticket is usable by
    subsequent work in the same transaction.
    """

    def __init__(self, session: AsyncSession, *, timeout_s: float = _DEFAULT_OPERATION_TIMEOUT_S) -> None:
        self._session = session
        self._timeout_s = _validate_timeout(timeout_s)

    async def _get_by_idempotency_key(self, tenant_id: UUID, idempotency_key: str) -> UsageReservation | None:
        stmt = (
            select(UsageReservation)
            .where(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.idempotency_key == idempotency_key,
            )
            .limit(1)
        )
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation="find reservation by idempotency key",
        )
        return result.scalar_one_or_none()

    async def _get_by_ticket(self, ticket: UsageTicket) -> UsageReservation | None:
        stmt = (
            select(UsageReservation)
            .where(
                UsageReservation.id == ticket.reservation_id,
                UsageReservation.tenant_id == ticket.tenant_id,
                UsageReservation.idempotency_key == ticket.idempotency_key,
                UsageReservation.cost_units == ticket.cost_units,
            )
            .limit(1)
        )
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation="find reservation by ticket",
        )
        return result.scalar_one_or_none()

    async def reserve(
        self,
        tenant_id: UUID,
        *,
        idempotency_key: str,
        job_id: str | None,
        cost_units: int,
    ) -> UsageReservation:
        """Atomically admit one reservation against the current entitlement.

        ``SELECT ... FOR UPDATE`` on the singleton entitlement serializes the
        allowance read with the reservation insert for one tenant.  The second
        idempotency lookup happens after that lock so a retry waiting behind an
        in-flight request returns its original row rather than inserting again.
        """
        if not isinstance(tenant_id, UUID):
            raise InvalidUsageRequestError("tenant_id must be a UUID")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise InvalidUsageRequestError("idempotency_key must be a non-empty string")
        if job_id is not None and (not isinstance(job_id, str) or not job_id.strip()):
            raise InvalidUsageRequestError("job_id must be a non-empty string when provided")
        if isinstance(cost_units, bool) or not isinstance(cost_units, int) or cost_units < 1:
            raise InvalidUsageRequestError("cost_units must be a positive integer")

        existing = await self._get_by_idempotency_key(tenant_id, idempotency_key)
        if existing is not None:
            return existing

        now = datetime.now(tz=UTC)
        entitlement_stmt = (
            select(TenantEntitlement)
            .where(
                TenantEntitlement.tenant_id == tenant_id,
                TenantEntitlement.status.in_(_ACTIVE_ENTITLEMENT_STATUSES),
                TenantEntitlement.period_start <= now,
                TenantEntitlement.period_end > now,
            )
            .with_for_update()
            .limit(1)
        )
        entitlement_result = await _with_timeout(
            self._session.execute(entitlement_stmt),
            timeout_s=self._timeout_s,
            operation="lock tenant entitlement for usage admission",
        )
        entitlement = entitlement_result.scalar_one_or_none()
        if entitlement is None:
            raise AllowanceExceededError("tenant has no active usage entitlement")

        # A concurrent request with the same key can become visible after the
        # first lookup while this request waits for the entitlement lock.
        existing = await self._get_by_idempotency_key(tenant_id, idempotency_key)
        if existing is not None:
            return existing

        used_stmt = (
            select(func.coalesce(func.sum(UsageReservation.cost_units), 0))
            .where(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.period_start == entitlement.period_start,
                UsageReservation.status.in_(_CHARGEABLE_RESERVATION_STATUSES),
            )
            .limit(1)
        )
        used_result = await _with_timeout(
            self._session.execute(used_stmt),
            timeout_s=self._timeout_s,
            operation="calculate committed and reserved usage",
        )
        used_units = int(used_result.scalar_one() or 0)
        allowance = int(entitlement.allowance_jobs)
        if used_units + cost_units > allowance:
            raise AllowanceExceededError("tenant usage allowance exhausted")

        reservation = UsageReservation(
            id=uuid4(),
            tenant_id=tenant_id,
            period_start=entitlement.period_start,
            idempotency_key=idempotency_key,
            job_id=job_id,
            status=UsageReservationStatus.RESERVED,
            cost_units=cost_units,
        )
        self._session.add(reservation)
        await _with_timeout(
            self._session.flush(),
            timeout_s=self._timeout_s,
            operation="insert usage reservation",
        )
        return reservation

    async def _settle(self, ticket: UsageTicket, target_status: UsageReservationStatus) -> None:
        reservation = await self._get_by_ticket(ticket)
        if reservation is None:
            raise ReservationNotFoundError("usage ticket does not identify a reservation")

        try:
            current_status = UsageReservationStatus(reservation.status)
        except (TypeError, ValueError):
            # Unknown persisted status is fail-safe: do not mutate a row whose
            # state this service cannot prove is the reservable state.
            return
        if current_status in _TERMINAL_RESERVATION_STATUSES:
            return
        if current_status is not UsageReservationStatus.RESERVED:
            return

        stmt = (
            update(UsageReservation)
            .where(
                UsageReservation.id == ticket.reservation_id,
                UsageReservation.tenant_id == ticket.tenant_id,
                UsageReservation.idempotency_key == ticket.idempotency_key,
                UsageReservation.cost_units == ticket.cost_units,
                UsageReservation.status == UsageReservationStatus.RESERVED,
            )
            .values(status=target_status, settled_at=func.now())
            .returning(UsageReservation.id)
        )
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation=f"mark usage reservation {target_status.value}",
        )
        changed_id = result.scalar_one_or_none()
        if changed_id is not None:
            return

        # A concurrent completion won the guarded update.  Re-read one row to
        # distinguish that terminal no-op from a ticket that disappeared or was
        # tampered with; the bounded query never materializes a reservation set.
        current = await self._get_by_ticket(ticket)
        if current is None:
            raise ReservationNotFoundError("usage ticket does not identify a reservation")

    async def commit(self, ticket: UsageTicket) -> None:
        """Commit a reserved ticket exactly once."""
        await self._settle(ticket, UsageReservationStatus.COMMITTED)

    async def release(self, ticket: UsageTicket) -> None:
        """Release a reserved ticket exactly once."""
        await self._settle(ticket, UsageReservationStatus.RELEASED)


# Short aliases keep the infrastructure seam convenient for callers that do
# not need to spell out the SQLAlchemy implementation detail.
UsageRepository = SqlAlchemyUsageRepository
UsageReservationRepository = SqlAlchemyUsageRepository
UsageAdmissionRepository = SqlAlchemyUsageRepository
SqlAlchemyUsageReservationRepository = SqlAlchemyUsageRepository
SqlAlchemyUsageAdmissionRepository = SqlAlchemyUsageRepository


__all__ = [
    "AllowanceExceededError",
    "InvalidUsageRequestError",
    "ReservationNotFoundError",
    "SqlAlchemyUsageRepository",
    "SqlAlchemyUsageAdmissionRepository",
    "SqlAlchemyUsageReservationRepository",
    "UsageAdmissionError",
    "UsageAdmissionRepository",
    "UsageAdmissionTimeoutError",
    "UsageRepository",
    "UsageReservationRepository",
]
