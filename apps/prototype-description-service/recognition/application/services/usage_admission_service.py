"""Application service for tenant-bound usage admission."""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.domain.portal_contracts import UsageReservationStatus, UsageTicket
from recognition.infrastructure.repositories.usage_repository import (
    AllowanceExceededError,
    GlobalUsageLimitExceededError,
    InvalidUsageRequestError,
    ReservationNotFoundError,
    SqlAlchemyUsageRepository,
    UsageAdmissionError,
    UsageAdmissionStoppedError,
    UsageAdmissionTimeoutError,
    UsageAdmissionUnavailableError,
    UsageFenceMismatchError,
    UsageFingerprintConflictError,
    UsageRepository,
)

_DEFAULT_OPERATION_TIMEOUT_S = 5.0


def _validate_request(
    tenant_id: UUID,
    *,
    idempotency_key: str,
    job_id: str | None,
    cost_units: int,
    operation_id: str | None,
    request_fingerprint: str | None,
    queue_bytes: int,
) -> None:
    if not isinstance(tenant_id, UUID):
        raise InvalidUsageRequestError("tenant_id must be a UUID")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise InvalidUsageRequestError("idempotency_key must be a non-empty string")
    if job_id is not None and (not isinstance(job_id, str) or not job_id.strip()):
        raise InvalidUsageRequestError("job_id must be a non-empty string when provided")
    if isinstance(cost_units, bool) or not isinstance(cost_units, int) or cost_units < 1:
        raise InvalidUsageRequestError("cost_units must be a positive integer")
    if operation_id is not None and (not isinstance(operation_id, str) or not operation_id.strip()):
        raise InvalidUsageRequestError("operation_id must be a non-empty string when provided")
    if request_fingerprint is not None and (
        not isinstance(request_fingerprint, str) or not request_fingerprint.strip()
    ):
        raise InvalidUsageRequestError("request_fingerprint must be a non-empty string when provided")
    if isinstance(queue_bytes, bool) or not isinstance(queue_bytes, int) or queue_bytes < 0:
        raise InvalidUsageRequestError("queue_bytes must be a non-negative integer")


def _validate_ticket(ticket: UsageTicket) -> None:
    if not isinstance(ticket, UsageTicket):
        raise InvalidUsageRequestError("ticket must be a UsageTicket")
    if not isinstance(ticket.reservation_id, UUID) or not isinstance(ticket.tenant_id, UUID):
        raise InvalidUsageRequestError("ticket identifiers must be UUIDs")
    if not isinstance(ticket.idempotency_key, str) or not ticket.idempotency_key.strip():
        raise InvalidUsageRequestError("ticket idempotency_key must be a non-empty string")
    if isinstance(ticket.cost_units, bool) or not isinstance(ticket.cost_units, int) or ticket.cost_units < 1:
        raise InvalidUsageRequestError("ticket cost_units must be a positive integer")


def _ticket_from_reservation(reservation: Any) -> UsageTicket:
    return UsageTicket(
        reservation_id=reservation.id,
        tenant_id=reservation.tenant_id,
        idempotency_key=reservation.idempotency_key,
        cost_units=int(reservation.cost_units),
        operation_id=getattr(reservation, "operation_id", None) or reservation.idempotency_key,
        request_fingerprint=getattr(reservation, "request_fingerprint", None) or reservation.idempotency_key,
        job_id=getattr(reservation, "job_id", None),
        fence_token=getattr(reservation, "fence_token", None) or "",
    )


class UsageAdmissionService:
    """Implement the published ``UsageAdmissionService`` protocol.

    The service accepts either an async SQLAlchemy session or a repository
    implementing the same persistence methods.  The surrounding caller
    owns transaction commit, matching the other SQLAlchemy application seams.

    G1 public ledger methods beyond the published protocol::

        async def reserve(
            tenant_id: UUID,
            *,
            idempotency_key: str,
            job_id: str | None,
            cost_units: int,
            operation_id: str | None = None,
            request_fingerprint: str | None = None,
            queue_bytes: int = 0,
        ) -> UsageTicket

        async def commit_fenced(ticket: UsageTicket, *, fence_token: str) -> None
        async def release_fenced(ticket: UsageTicket, *, fence_token: str) -> None
        async def begin_recovery(ticket: UsageTicket) -> Any
        async def complete_recovery(reservation: Any, *, target_status: UsageReservationStatus) -> None
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
        operation_id: str | None = None,
        request_fingerprint: str | None = None,
        queue_bytes: int = 0,
    ) -> UsageTicket:
        """Atomically reserve allowance and return a retry-stable ticket."""
        _validate_request(
            tenant_id,
            idempotency_key=idempotency_key,
            job_id=job_id,
            cost_units=cost_units,
            operation_id=operation_id,
            request_fingerprint=request_fingerprint,
            queue_bytes=queue_bytes,
        )
        try:
            reservation = await self._repository.reserve(
                tenant_id,
                idempotency_key=idempotency_key,
                job_id=job_id,
                cost_units=cost_units,
                operation_id=operation_id,
                request_fingerprint=request_fingerprint,
                queue_bytes=queue_bytes,
            )
        except TypeError:
            reservation = await self._repository.reserve(
                tenant_id,
                idempotency_key=idempotency_key,
                job_id=job_id,
                cost_units=cost_units,
            )
        if isinstance(reservation, UsageTicket):
            return reservation
        return _ticket_from_reservation(reservation)

    async def _settle(self, method_name: str, ticket: UsageTicket, *, fence_token: str | None) -> None:
        method = getattr(self._repository, method_name)
        try:
            await method(ticket, fence_token=fence_token)
        except TypeError:
            await method(ticket)

    async def commit(self, ticket: UsageTicket) -> None:
        """Commit one reservation; duplicate completion is a no-op."""
        _validate_ticket(ticket)
        await self._settle("commit", ticket, fence_token=ticket.fence_token or None)

    async def release(self, ticket: UsageTicket) -> None:
        """Release one reservation; duplicate or late release is a no-op."""
        _validate_ticket(ticket)
        await self._settle("release", ticket, fence_token=ticket.fence_token or None)

    async def commit_fenced(self, ticket: UsageTicket, *, fence_token: str) -> None:
        """Idempotent terminal commit guarded by reservation id plus fence."""
        _validate_ticket(ticket)
        if not isinstance(fence_token, str) or not fence_token.strip():
            raise InvalidUsageRequestError("fence_token must be a non-empty string")
        commit_fenced = getattr(self._repository, "commit_fenced", None)
        if callable(commit_fenced):
            await commit_fenced(ticket, fence_token=fence_token.strip())
            return
        await self._repository.commit(ticket, fence_token=fence_token.strip())

    async def release_fenced(self, ticket: UsageTicket, *, fence_token: str) -> None:
        """Idempotent terminal release guarded by reservation id plus fence."""
        _validate_ticket(ticket)
        if not isinstance(fence_token, str) or not fence_token.strip():
            raise InvalidUsageRequestError("fence_token must be a non-empty string")
        release_fenced = getattr(self._repository, "release_fenced", None)
        if callable(release_fenced):
            await release_fenced(ticket, fence_token=fence_token.strip())
            return
        await self._repository.release(ticket, fence_token=fence_token.strip())

    async def assert_fence_current(self, ticket: UsageTicket, *, fence_token: str) -> None:
        """Reject a captured worker token whose generation is no longer current."""
        _validate_ticket(ticket)
        if not isinstance(fence_token, str) or not fence_token.strip():
            raise InvalidUsageRequestError("fence_token must be a non-empty string")
        assert_fence_current = getattr(self._repository, "assert_fence_current", None)
        if not callable(assert_fence_current):
            raise UsageAdmissionUnavailableError("usage repository does not expose fence assertion")
        await assert_fence_current(ticket, fence_token=fence_token.strip())

    async def begin_recovery(self, ticket: UsageTicket) -> Any:
        """Lock ledger identity for trusted terminal recovery. No new work is minted."""
        _validate_ticket(ticket)
        begin_recovery = getattr(self._repository, "begin_recovery", None)
        if not callable(begin_recovery):
            raise UsageAdmissionUnavailableError("usage repository does not support trusted recovery")
        return await begin_recovery(ticket)

    async def complete_recovery(self, reservation: Any, *, target_status: UsageReservationStatus) -> bool:
        """Re-fence to the current epoch and settle one already-locked reservation."""
        if target_status not in (UsageReservationStatus.COMMITTED, UsageReservationStatus.RELEASED):
            raise InvalidUsageRequestError("recovery target must be committed or released")
        complete_recovery = getattr(self._repository, "complete_recovery", None)
        if not callable(complete_recovery):
            raise UsageAdmissionUnavailableError("usage repository does not support trusted recovery")
        return bool(await complete_recovery(reservation, target_status=target_status))


# Explicit implementation aliases are useful to dependency-wiring code while
# keeping ``UsageAdmissionService`` aligned with the published protocol name.
SqlAlchemyUsageAdmissionService = UsageAdmissionService
UsageAdmissionServiceImpl = UsageAdmissionService


__all__ = [
    "AllowanceExceededError",
    "GlobalUsageLimitExceededError",
    "InvalidUsageRequestError",
    "ReservationNotFoundError",
    "SqlAlchemyUsageAdmissionService",
    "UsageAdmissionError",
    "UsageAdmissionService",
    "UsageAdmissionServiceImpl",
    "UsageAdmissionStoppedError",
    "UsageAdmissionTimeoutError",
    "UsageAdmissionUnavailableError",
    "UsageFenceMismatchError",
    "UsageFingerprintConflictError",
]
