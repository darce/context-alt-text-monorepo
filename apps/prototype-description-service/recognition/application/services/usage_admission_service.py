"""Application service for tenant-bound usage admission."""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.domain.portal_contracts import UsageTicket
from recognition.infrastructure.repositories.usage_repository import (
    AllowanceExceededError,
    InvalidUsageRequestError,
    ReservationNotFoundError,
    SqlAlchemyUsageRepository,
    UsageAdmissionError,
    UsageAdmissionTimeoutError,
    UsageRepository,
)

_DEFAULT_OPERATION_TIMEOUT_S = 5.0


def _validate_request(
    tenant_id: UUID,
    *,
    idempotency_key: str,
    job_id: str | None,
    cost_units: int,
) -> None:
    if not isinstance(tenant_id, UUID):
        raise InvalidUsageRequestError("tenant_id must be a UUID")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise InvalidUsageRequestError("idempotency_key must be a non-empty string")
    if job_id is not None and (not isinstance(job_id, str) or not job_id.strip()):
        raise InvalidUsageRequestError("job_id must be a non-empty string when provided")
    if isinstance(cost_units, bool) or not isinstance(cost_units, int) or cost_units < 1:
        raise InvalidUsageRequestError("cost_units must be a positive integer")


def _validate_ticket(ticket: UsageTicket) -> None:
    if not isinstance(ticket, UsageTicket):
        raise InvalidUsageRequestError("ticket must be a UsageTicket")
    if not isinstance(ticket.reservation_id, UUID) or not isinstance(ticket.tenant_id, UUID):
        raise InvalidUsageRequestError("ticket identifiers must be UUIDs")
    if not isinstance(ticket.idempotency_key, str) or not ticket.idempotency_key.strip():
        raise InvalidUsageRequestError("ticket idempotency_key must be a non-empty string")
    if isinstance(ticket.cost_units, bool) or not isinstance(ticket.cost_units, int) or ticket.cost_units < 1:
        raise InvalidUsageRequestError("ticket cost_units must be a positive integer")


class UsageAdmissionService:
    """Implement the published ``UsageAdmissionService`` protocol.

    The service accepts either an async SQLAlchemy session or a repository
    implementing the same three persistence methods.  The surrounding caller
    owns transaction commit, matching the other SQLAlchemy application seams.
    """

    def __init__(
        self,
        session_or_repository: AsyncSession | UsageRepository | None = None,
        *,
        session: AsyncSession | None = None,
        repository: UsageRepository | None = None,
        timeout_s: float = _DEFAULT_OPERATION_TIMEOUT_S,
    ) -> None:
        if session_or_repository is not None and (session is not None or repository is not None):
            raise ValueError("provide one session or repository")
        if session is not None and repository is not None:
            raise ValueError("provide a session or repository, not both")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
            raise ValueError("timeout_s must be a finite positive number")
        if not math.isfinite(float(timeout_s)) or float(timeout_s) <= 0:
            raise ValueError("timeout_s must be a finite positive number")

        candidate: Any = repository if repository is not None else session
        if candidate is None:
            candidate = session_or_repository
        if candidate is None:
            raise ValueError("a database session or usage repository is required")

        if all(callable(getattr(candidate, name, None)) for name in ("reserve", "commit", "release")):
            self._repository = candidate
        else:
            self._repository = SqlAlchemyUsageRepository(candidate, timeout_s=timeout_s)

    async def reserve(
        self,
        tenant_id: UUID,
        *,
        idempotency_key: str,
        job_id: str | None,
        cost_units: int,
    ) -> UsageTicket:
        """Atomically reserve allowance and return a retry-stable ticket."""
        _validate_request(
            tenant_id,
            idempotency_key=idempotency_key,
            job_id=job_id,
            cost_units=cost_units,
        )
        reservation = await self._repository.reserve(
            tenant_id,
            idempotency_key=idempotency_key,
            job_id=job_id,
            cost_units=cost_units,
        )
        if isinstance(reservation, UsageTicket):
            return reservation
        return UsageTicket(
            reservation_id=reservation.id,
            tenant_id=reservation.tenant_id,
            idempotency_key=reservation.idempotency_key,
            cost_units=reservation.cost_units,
        )

    async def commit(self, ticket: UsageTicket) -> None:
        """Commit one reservation; duplicate completion is a no-op."""
        _validate_ticket(ticket)
        await self._repository.commit(ticket)

    async def release(self, ticket: UsageTicket) -> None:
        """Release one reservation; duplicate or late release is a no-op."""
        _validate_ticket(ticket)
        await self._repository.release(ticket)


# Explicit implementation aliases are useful to dependency-wiring code while
# keeping ``UsageAdmissionService`` aligned with the published protocol name.
SqlAlchemyUsageAdmissionService = UsageAdmissionService
UsageAdmissionServiceImpl = UsageAdmissionService


__all__ = [
    "AllowanceExceededError",
    "InvalidUsageRequestError",
    "ReservationNotFoundError",
    "SqlAlchemyUsageAdmissionService",
    "UsageAdmissionError",
    "UsageAdmissionService",
    "UsageAdmissionServiceImpl",
    "UsageAdmissionTimeoutError",
]
