"""Persistence primitives for tenant usage reservations.

Lock order is fixed and short: the global admission singleton first, then the
tenant entitlement row.  That serializes tenant allowance, global daily cost,
in-flight units, queue bounds, and stop/fence checks with the reservation
insert.  Missing global state is fail-closed, never unmetered.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Iterable
from datetime import UTC, datetime, timedelta
from typing import NamedTuple
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TenantEntitlement, UsageReservation
from db.models.portal_billing import GlobalUsageAdmissionState
from recognition.domain.portal_contracts import (
    GLOBAL_USAGE_ADMISSION_STATE_ID,
    EntitlementStatus,
    UsageReservationStatus,
    UsageTicket,
)

_DEFAULT_OPERATION_TIMEOUT_S = 5.0
# Recognition work can span multiple bounded inference and database calls; this
# gives a synchronous request room to finish while reclaiming abandoned rows promptly.
USAGE_RESERVATION_LEASE = timedelta(minutes=30)
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


class ExpiredUsageReservationError(InvalidUsageRequestError):
    """The operation or idempotency key identifies an expired reservation."""


class AllowanceExceededError(UsageAdmissionError):
    """No active entitlement has enough remaining allowance."""

    def __init__(
        self, message: str = "tenant usage allowance exhausted", *, period_end: datetime | None = None
    ) -> None:
        super().__init__(message)
        self.period_end = period_end


class ReservationNotFoundError(LookupError):
    """A completion ticket does not identify a reservation for its tenant."""


class UsageAdmissionTimeoutError(TimeoutError):
    """A database operation exceeded the admission operation deadline."""


class UsageFingerprintConflictError(UsageAdmissionError):
    """Same tenant operation was reused with a different request fingerprint."""


class UsageAdmissionUnavailableError(UsageAdmissionError):
    """Required global admission state or configuration is missing or invalid."""


class GlobalUsageLimitExceededError(UsageAdmissionError):
    """Global daily, in-flight, or queue bounds refused the reservation."""


class UsageAdmissionStoppedError(UsageAdmissionError):
    """Operator stop/fence is set; new reservations are refused."""


class UsageFenceMismatchError(UsageAdmissionError):
    """A stale fence token cannot settle this reservation."""


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


def _require_non_empty(name: str, value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidUsageRequestError(f"{name} must be a non-empty string")
    return value.strip()


def _utc_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


_FENCE_LEGACY_MARKER = "legacy"


class _ParsedFence(NamedTuple):
    epoch: int | None
    legacy: bool
    token_uuid: UUID


def _parse_uuid_text(value: str) -> UUID:
    try:
        return UUID(value)
    except (TypeError, ValueError) as exc:
        raise UsageFenceMismatchError("usage ticket fence is malformed") from exc


def _parse_positive_epoch(value: str) -> int:
    if not value.isdigit() or value.startswith("0"):
        raise UsageFenceMismatchError("usage ticket fence epoch is malformed")
    epoch = int(value)
    if epoch < 1:
        raise UsageFenceMismatchError("usage ticket fence epoch is malformed")
    return epoch


def _parse_fence_token(raw: str | None) -> _ParsedFence:
    value = (raw or "").strip()
    if not value:
        raise UsageFenceMismatchError("usage ticket fence is missing")
    parts = value.split(":")
    if len(parts) == 1:
        return _ParsedFence(epoch=None, legacy=False, token_uuid=_parse_uuid_text(parts[0]))
    if len(parts) == 2:
        return _ParsedFence(
            epoch=_parse_positive_epoch(parts[0]),
            legacy=False,
            token_uuid=_parse_uuid_text(parts[1]),
        )
    if len(parts) == 3:
        if parts[1] != _FENCE_LEGACY_MARKER:
            raise UsageFenceMismatchError("usage ticket fence marker is malformed")
        return _ParsedFence(
            epoch=_parse_positive_epoch(parts[0]),
            legacy=True,
            token_uuid=_parse_uuid_text(parts[2]),
        )
    raise UsageFenceMismatchError("usage ticket fence is malformed")


def _mint_modern_fence_token(epoch: int) -> str:
    return f"{int(epoch)}:{uuid4()}"


def _has_explicit_legacy_marker(raw: str | None, reservation_id: UUID) -> bool:
    parts = (raw or "").strip().split(":")
    if len(parts) != 3 or parts[1] != _FENCE_LEGACY_MARKER:
        return False
    try:
        epoch = int(parts[0], 10)
        marker_uuid = UUID(parts[2])
    except (TypeError, ValueError):
        return False
    return epoch >= 1 and marker_uuid == reservation_id


def _legacy_row_tuple(reservation: UsageReservation) -> bool:
    return (reservation.operation_id or "") == reservation.idempotency_key and (
        reservation.request_fingerprint or ""
    ) == reservation.idempotency_key


class SqlAlchemyUsageRepository:
    """Persist usage reservations through a request-scoped async session.

    The caller owns the surrounding transaction and commit.  ``reserve``
    flushes its insert before returning so the returned ticket is usable by
    subsequent work in the same transaction.
    """

    def __init__(self, session: AsyncSession, *, timeout_s: float = _DEFAULT_OPERATION_TIMEOUT_S) -> None:
        self._session = session
        self._timeout_s = _validate_timeout(timeout_s)

    async def _get_by_operation_id(self, tenant_id: UUID, operation_id: str) -> UsageReservation | None:
        stmt = (
            select(UsageReservation)
            .where(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.operation_id == operation_id,
            )
            .limit(1)
        )
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation="find reservation by operation id",
        )
        return result.scalar_one_or_none()

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

    def _ticket_identity_matches(self, reservation: UsageReservation, ticket: UsageTicket) -> bool:
        if reservation.job_id != ticket.job_id:
            return False
        ticket_operation = (ticket.operation_id or "").strip()
        ticket_fingerprint = (ticket.request_fingerprint or "").strip()
        explicit_legacy = _has_explicit_legacy_marker(reservation.fence_token, reservation.id) and _legacy_row_tuple(
            reservation
        )
        if explicit_legacy:
            operation_ok = not ticket_operation or ticket_operation == reservation.operation_id
            fingerprint_ok = not ticket_fingerprint or ticket_fingerprint == reservation.request_fingerprint
            return operation_ok and fingerprint_ok
        if not ticket_operation or not ticket_fingerprint:
            return False
        return ticket_operation == reservation.operation_id and ticket_fingerprint == reservation.request_fingerprint

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
            .execution_options(populate_existing=True)
        )
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation="find reservation by ticket",
        )
        reservation = result.scalar_one_or_none()
        if reservation is None or not self._ticket_identity_matches(reservation, ticket):
            return None
        return reservation

    def _replay_or_conflict(self, existing: UsageReservation, request_fingerprint: str) -> UsageReservation:
        self._reject_expired_reservation(existing)
        stored = existing.request_fingerprint or existing.idempotency_key
        if stored != request_fingerprint:
            raise UsageFingerprintConflictError("usage operation reused with a different request fingerprint")
        return existing

    @staticmethod
    def _reject_expired_reservation(existing: UsageReservation) -> None:
        if existing.status == UsageReservationStatus.EXPIRED:
            raise ExpiredUsageReservationError("operation or idempotency key belongs to an expired reservation")

    async def _lock_global_state(self) -> GlobalUsageAdmissionState:
        stmt = (
            select(GlobalUsageAdmissionState)
            .where(GlobalUsageAdmissionState.id == GLOBAL_USAGE_ADMISSION_STATE_ID)
            .with_for_update()
            .limit(1)
        )
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation="lock global usage admission state",
        )
        global_state = result.scalar_one_or_none()
        if global_state is None:
            raise UsageAdmissionUnavailableError("global usage admission state is missing")
        self._validate_global_config(global_state)
        return global_state

    def _validate_global_config(self, global_state: GlobalUsageAdmissionState) -> None:
        required = (
            global_state.daily_cost_limit,
            global_state.daily_cost_units,
            global_state.inflight_limit,
            global_state.inflight_units,
            global_state.queue_limit,
            global_state.queue_depth,
            global_state.queue_byte_limit,
            global_state.queue_bytes,
            global_state.fence_epoch,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in required):
            raise UsageAdmissionUnavailableError("global usage admission configuration is invalid")
        if int(global_state.fence_epoch) < 1:
            raise UsageAdmissionUnavailableError("global usage admission fence epoch is missing")
        if not isinstance(global_state.config_version, str) or not global_state.config_version.strip():
            raise UsageAdmissionUnavailableError("global usage admission config version is missing")
        if global_state.period_start is None or global_state.period_end is None:
            raise UsageAdmissionUnavailableError("global usage admission period is missing")
        if global_state.stop_requested is None:
            raise UsageAdmissionUnavailableError("global usage admission stop state is missing")

    def _roll_global_period_if_needed(self, global_state: GlobalUsageAdmissionState, now: datetime) -> None:
        period_end = global_state.period_end
        if period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=UTC)
        if now < period_end:
            return
        start, end = _utc_day_bounds(now)
        global_state.period_start = start
        global_state.period_end = end
        global_state.daily_cost_units = 0
        global_state.updated_at = now

    def _assert_global_capacity(
        self,
        global_state: GlobalUsageAdmissionState,
        *,
        cost_units: int,
        queue_bytes: int,
    ) -> None:
        if bool(global_state.stop_requested):
            raise UsageAdmissionStoppedError("usage admission stop is requested")
        if int(global_state.daily_cost_units) + cost_units > int(global_state.daily_cost_limit):
            raise GlobalUsageLimitExceededError("global daily usage cost limit exceeded")
        if int(global_state.inflight_units) + cost_units > int(global_state.inflight_limit):
            raise GlobalUsageLimitExceededError("global in-flight usage limit exceeded")
        if int(global_state.queue_depth) + 1 > int(global_state.queue_limit):
            raise GlobalUsageLimitExceededError("global usage queue is full")
        if int(global_state.queue_bytes) + queue_bytes > int(global_state.queue_byte_limit):
            raise GlobalUsageLimitExceededError("global usage queue byte budget exceeded")

    def _apply_reserve_counters(
        self,
        global_state: GlobalUsageAdmissionState,
        *,
        cost_units: int,
        queue_bytes: int,
        now: datetime,
    ) -> None:
        global_state.daily_cost_units = int(global_state.daily_cost_units) + cost_units
        global_state.inflight_units = int(global_state.inflight_units) + cost_units
        global_state.queue_depth = int(global_state.queue_depth) + 1
        global_state.queue_bytes = int(global_state.queue_bytes) + queue_bytes
        global_state.updated_at = now

    def _apply_settle_counters(
        self,
        global_state: GlobalUsageAdmissionState,
        reservation: UsageReservation,
        *,
        target_status: UsageReservationStatus,
        now: datetime,
    ) -> None:
        cost_units = int(reservation.cost_units)
        queue_bytes = int(reservation.queue_bytes or 0)
        global_state.inflight_units = max(0, int(global_state.inflight_units) - cost_units)
        global_state.queue_depth = max(0, int(global_state.queue_depth) - 1)
        global_state.queue_bytes = max(0, int(global_state.queue_bytes) - queue_bytes)
        if target_status is UsageReservationStatus.RELEASED or target_status is UsageReservationStatus.EXPIRED:
            # A rollover already discarded prior-day costs. Only refund work
            # admitted within the daily period this counter currently tracks.
            reserved_at = reservation.reserved_at
            period_start = global_state.period_start
            period_end = global_state.period_end
            if reserved_at.tzinfo is None:
                reserved_at = reserved_at.replace(tzinfo=UTC)
            if period_start.tzinfo is None:
                period_start = period_start.replace(tzinfo=UTC)
            if period_end.tzinfo is None:
                period_end = period_end.replace(tzinfo=UTC)
            if period_start <= reserved_at < period_end:
                global_state.daily_cost_units = max(0, int(global_state.daily_cost_units) - cost_units)
        global_state.updated_at = now

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
    ) -> UsageReservation:
        """Atomically admit one reservation against tenant and global bounds.

        Lock order is global state, then tenant entitlement.  A unique collision
        re-reads the winner and compares the fingerprint; a changed fingerprint
        is never accepted as a replay.
        """
        if not isinstance(tenant_id, UUID):
            raise InvalidUsageRequestError("tenant_id must be a UUID")
        normalized_key = _require_non_empty("idempotency_key", idempotency_key)
        normalized_operation = _require_non_empty("operation_id", operation_id or normalized_key)
        normalized_fingerprint = _require_non_empty("request_fingerprint", request_fingerprint or normalized_key)
        if job_id is not None:
            job_id = _require_non_empty("job_id", job_id)
        if isinstance(cost_units, bool) or not isinstance(cost_units, int) or cost_units < 1:
            raise InvalidUsageRequestError("cost_units must be a positive integer")
        if isinstance(queue_bytes, bool) or not isinstance(queue_bytes, int) or queue_bytes < 0:
            raise InvalidUsageRequestError("queue_bytes must be a non-negative integer")

        bound_job_id = job_id or uuid4().hex
        existing = await self._get_by_idempotency_key(tenant_id, normalized_key)
        if existing is not None:
            # A stale RESERVED retry can be returned here, but _settle applies
            # this same lease before charging it, so replay cannot extend it.
            return self._replay_or_conflict(existing, normalized_fingerprint)
        global_state = await self._lock_global_state()
        now = datetime.now(tz=UTC)
        self._roll_global_period_if_needed(global_state, now)

        existing = await self._get_by_operation_id(tenant_id, normalized_operation)
        if existing is None:
            existing = await self._get_by_idempotency_key(tenant_id, normalized_key)
        if existing is not None:
            return self._replay_or_conflict(existing, normalized_fingerprint)

        entitlement_stmt = (
            select(TenantEntitlement)
            .where(
                TenantEntitlement.tenant_id == tenant_id,
                TenantEntitlement.period_start <= now,
                # Mirrors TenantEntitlementService.snapshot: a past-due tenant stays
                # admissible until its grace window closes, even past period_end.
                or_(
                    and_(
                        TenantEntitlement.status.in_(_ACTIVE_ENTITLEMENT_STATUSES),
                        TenantEntitlement.period_end > now,
                    ),
                    and_(
                        TenantEntitlement.status == EntitlementStatus.PAST_DUE,
                        TenantEntitlement.grace_until.is_not(None),
                        TenantEntitlement.grace_until >= now,
                    ),
                ),
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

        existing = await self._get_by_operation_id(tenant_id, normalized_operation)
        if existing is None:
            existing = await self._get_by_idempotency_key(tenant_id, normalized_key)
        if existing is not None:
            return self._replay_or_conflict(existing, normalized_fingerprint)

        lease_cutoff = datetime.now(tz=UTC) - USAGE_RESERVATION_LEASE
        expire_stmt = (
            update(UsageReservation)
            .where(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.period_start == entitlement.period_start,
                UsageReservation.status == UsageReservationStatus.RESERVED,
                UsageReservation.reserved_at < lease_cutoff,
            )
            .values(status=UsageReservationStatus.EXPIRED, settled_at=func.now())
        )
        await _with_timeout(
            self._session.execute(expire_stmt),
            timeout_s=self._timeout_s,
            operation="expire stale usage reservations",
        )

        used_stmt = (
            select(func.coalesce(func.sum(UsageReservation.cost_units), 0))
            .where(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.period_start == entitlement.period_start,
                UsageReservation.status.in_(_CHARGEABLE_RESERVATION_STATUSES),
                or_(
                    UsageReservation.status == UsageReservationStatus.COMMITTED,
                    UsageReservation.reserved_at >= lease_cutoff,
                ),
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
            raise AllowanceExceededError(
                "tenant usage allowance exhausted",
                period_end=entitlement.period_end,
            )

        self._assert_global_capacity(global_state, cost_units=cost_units, queue_bytes=queue_bytes)

        reservation = UsageReservation(
            id=uuid4(),
            tenant_id=tenant_id,
            period_start=entitlement.period_start,
            idempotency_key=normalized_key,
            operation_id=normalized_operation,
            request_fingerprint=normalized_fingerprint,
            job_id=bound_job_id,
            fence_token=_mint_modern_fence_token(int(global_state.fence_epoch)),
            queue_bytes=queue_bytes,
            status=UsageReservationStatus.RESERVED,
            cost_units=cost_units,
            reserved_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(reservation)
                await _with_timeout(
                    self._session.flush(),
                    timeout_s=self._timeout_s,
                    operation="insert usage reservation",
                )
        except IntegrityError:
            raced = await self._get_by_operation_id(tenant_id, normalized_operation)
            if raced is None:
                raced = await self._get_by_idempotency_key(tenant_id, normalized_key)
            if raced is not None:
                return self._replay_or_conflict(raced, normalized_fingerprint)
            raise
        self._apply_reserve_counters(global_state, cost_units=cost_units, queue_bytes=queue_bytes, now=now)
        return reservation

    def _assert_fence_current(
        self,
        global_state: GlobalUsageAdmissionState,
        reservation: UsageReservation,
        fence_token: str | None,
    ) -> None:
        parsed = _parse_fence_token(reservation.fence_token)
        if parsed.legacy and parsed.token_uuid != reservation.id:
            raise UsageFenceMismatchError("usage ticket fence does not match the reservation")
        if parsed.epoch is not None and parsed.epoch != int(global_state.fence_epoch):
            raise UsageFenceMismatchError("usage ticket fence epoch is stale")
        provided = (fence_token or "").strip()
        stored = (reservation.fence_token or "").strip()
        if not provided or provided != stored:
            raise UsageFenceMismatchError("usage ticket fence does not match the reservation")

    async def _settle(
        self,
        ticket: UsageTicket,
        target_status: UsageReservationStatus,
        *,
        fence_token: str | None = None,
    ) -> None:
        now = datetime.now(tz=UTC)
        global_state = await self._lock_global_state()
        reservation = await self._get_by_ticket(ticket)
        if reservation is None:
            raise ReservationNotFoundError("usage ticket does not identify a reservation")
        self._assert_fence_current(
            global_state,
            reservation,
            fence_token if fence_token is not None else ticket.fence_token,
        )

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

        lease_cutoff = datetime.now(tz=UTC) - USAGE_RESERVATION_LEASE
        reserved_at = reservation.reserved_at
        if reserved_at.tzinfo is None:
            reserved_at = reserved_at.replace(tzinfo=UTC)
        stale_reservation = reserved_at < lease_cutoff
        settled_status = UsageReservationStatus.EXPIRED if stale_reservation else target_status
        lease_guard = (
            UsageReservation.reserved_at < lease_cutoff
            if stale_reservation
            else UsageReservation.reserved_at >= lease_cutoff
        )
        stmt = (
            update(UsageReservation)
            .where(
                UsageReservation.id == ticket.reservation_id,
                UsageReservation.tenant_id == ticket.tenant_id,
                UsageReservation.idempotency_key == ticket.idempotency_key,
                UsageReservation.cost_units == ticket.cost_units,
                UsageReservation.job_id == reservation.job_id,
                UsageReservation.operation_id == reservation.operation_id,
                UsageReservation.request_fingerprint == reservation.request_fingerprint,
                UsageReservation.status == UsageReservationStatus.RESERVED,
                UsageReservation.fence_token == reservation.fence_token,
                lease_guard,
            )
            .values(status=settled_status, settled_at=func.now())
            .returning(UsageReservation.id)
            .execution_options(synchronize_session=False)
        )
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation=f"mark usage reservation {target_status.value}",
        )
        changed_id = result.scalar_one_or_none()
        if changed_id is not None:
            self._apply_settle_counters(global_state, reservation, target_status=settled_status, now=now)
            return

        # A concurrent completion won the guarded update.  Re-read one row to
        # distinguish that terminal no-op from a ticket that disappeared or was
        # tampered with; the bounded query never materializes a reservation set.
        current = await self._get_by_ticket(ticket)
        if current is None:
            raise ReservationNotFoundError("usage ticket does not identify a reservation")

    async def commit(self, ticket: UsageTicket, *, fence_token: str | None = None) -> None:
        """Commit a reserved ticket exactly once."""
        await self._settle(ticket, UsageReservationStatus.COMMITTED, fence_token=fence_token)

    async def release(self, ticket: UsageTicket, *, fence_token: str | None = None) -> None:
        """Release a reserved ticket exactly once."""
        await self._settle(ticket, UsageReservationStatus.RELEASED, fence_token=fence_token)

    async def commit_fenced(self, ticket: UsageTicket, *, fence_token: str) -> None:
        """Worker terminal commit guarded by reservation id plus fence."""
        await self._settle(
            ticket,
            UsageReservationStatus.COMMITTED,
            fence_token=_require_non_empty("fence_token", fence_token),
        )

    async def release_fenced(self, ticket: UsageTicket, *, fence_token: str) -> None:
        """Worker/pre-pickup release guarded by reservation id plus fence."""
        await self._settle(
            ticket,
            UsageReservationStatus.RELEASED,
            fence_token=_require_non_empty("fence_token", fence_token),
        )

    async def _lock_entitlement_row(self, tenant_id: UUID) -> TenantEntitlement | None:
        stmt = select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id).with_for_update().limit(1)
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation="lock tenant entitlement for usage recovery",
        )
        return result.scalar_one_or_none()

    async def _lock_reservation(self, ticket: UsageTicket) -> UsageReservation | None:
        stmt = (
            select(UsageReservation)
            .where(
                UsageReservation.id == ticket.reservation_id,
                UsageReservation.tenant_id == ticket.tenant_id,
                UsageReservation.idempotency_key == ticket.idempotency_key,
                UsageReservation.cost_units == ticket.cost_units,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
            .limit(1)
        )
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation="lock usage reservation for recovery",
        )
        return result.scalar_one_or_none()

    async def assert_fence_current(self, ticket: UsageTicket, *, fence_token: str) -> None:
        """Reject a captured token whose epoch no longer matches global state."""
        global_state = await self._lock_global_state()
        reservation = await self._get_by_ticket(ticket)
        if reservation is None:
            raise ReservationNotFoundError("usage ticket does not identify a reservation")
        self._assert_fence_current(global_state, reservation, fence_token)

    async def begin_recovery(self, ticket: UsageTicket) -> UsageReservation:
        """Lock global state, entitlement, then reservation for trusted recovery.

        Recovery uses the reservation's recorded entitlement period, because
        the singleton entitlement may have advanced since admission. A daily
        rollover resets only daily accounting; inflight and queue holds remain
        available for recovery to release. [RES-19][DATA-03]
        """
        now = datetime.now(tz=UTC)
        global_state = await self._lock_global_state()
        self._roll_global_period_if_needed(global_state, now)
        entitlement = await self._lock_entitlement_row(ticket.tenant_id)
        if entitlement is None:
            raise UsageAdmissionUnavailableError("tenant entitlement is missing; recovery is unsafe")
        reservation = await self._lock_reservation(ticket)
        if reservation is None or not self._ticket_identity_matches(reservation, ticket):
            raise ReservationNotFoundError("usage ticket does not identify a reservation")
        return reservation

    async def complete_recovery(
        self,
        reservation: UsageReservation,
        *,
        target_status: UsageReservationStatus,
    ) -> bool:
        """Atomically re-fence to the current epoch and settle without new work."""
        if target_status not in (UsageReservationStatus.COMMITTED, UsageReservationStatus.RELEASED):
            raise InvalidUsageRequestError("recovery target must be committed or released")
        now = datetime.now(tz=UTC)
        global_state = await self._lock_global_state()
        self._roll_global_period_if_needed(global_state, now)
        try:
            current_status = UsageReservationStatus(reservation.status)
        except (TypeError, ValueError):
            return False
        if current_status in _TERMINAL_RESERVATION_STATUSES:
            return False
        if current_status is not UsageReservationStatus.RESERVED:
            return False

        new_fence = _mint_modern_fence_token(int(global_state.fence_epoch))
        stmt = (
            update(UsageReservation)
            .where(
                UsageReservation.id == reservation.id,
                UsageReservation.tenant_id == reservation.tenant_id,
                UsageReservation.idempotency_key == reservation.idempotency_key,
                UsageReservation.cost_units == reservation.cost_units,
                UsageReservation.job_id == reservation.job_id,
                UsageReservation.operation_id == reservation.operation_id,
                UsageReservation.request_fingerprint == reservation.request_fingerprint,
                UsageReservation.period_start == reservation.period_start,
                UsageReservation.status == UsageReservationStatus.RESERVED,
                UsageReservation.fence_token == reservation.fence_token,
            )
            .values(status=target_status, settled_at=func.now(), fence_token=new_fence)
            .returning(UsageReservation.id)
        )
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation=f"recover usage reservation {target_status.value}",
        )
        changed_id = result.scalar_one_or_none()
        if changed_id is not None:
            self._apply_settle_counters(global_state, reservation, target_status=target_status, now=now)
            reservation.status = target_status.value
            reservation.fence_token = new_fence
            return True
        current = await self._lock_reservation(
            UsageTicket(
                reservation_id=reservation.id,
                tenant_id=reservation.tenant_id,
                idempotency_key=reservation.idempotency_key,
                cost_units=int(reservation.cost_units),
                operation_id=reservation.operation_id or "",
                request_fingerprint=reservation.request_fingerprint or "",
                job_id=reservation.job_id,
                fence_token=reservation.fence_token or "",
            )
        )
        if current is None:
            raise ReservationNotFoundError("usage ticket does not identify a reservation")
        return False

    async def list_stale_reservations(
        self,
        stale_after_seconds: float,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[UsageReservation]:
        """Return a bounded, oldest-first batch of reservations still held open."""
        if isinstance(stale_after_seconds, bool) or not isinstance(stale_after_seconds, (int, float)):
            raise ValueError("stale_after_seconds must be a finite non-negative number")
        stale_after = float(stale_after_seconds)
        if not math.isfinite(stale_after) or stale_after < 0:
            raise ValueError("stale_after_seconds must be a finite non-negative number")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")

        reference_time = now or datetime.now(tz=UTC)
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=UTC)
        cutoff = reference_time - timedelta(seconds=stale_after)
        stmt = (
            select(UsageReservation)
            .where(
                UsageReservation.status == UsageReservationStatus.RESERVED,
                UsageReservation.reserved_at <= cutoff,
            )
            .order_by(UsageReservation.reserved_at.asc(), UsageReservation.id.asc())
            .limit(limit)
        )
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation="list stale usage reservations",
        )
        return list(result.scalars().all())

    async def release_batch(self, reservations: Iterable[UsageReservation | UsageTicket]) -> int:
        """Release a bounded batch without reviving rows settled by a racer."""
        reservation_ids: list[UUID] = []
        for reservation in reservations:
            reservation_id = getattr(reservation, "reservation_id", None) or getattr(reservation, "id", None)
            if isinstance(reservation_id, UUID):
                reservation_ids.append(reservation_id)
        if not reservation_ids:
            return 0

        now = datetime.now(tz=UTC)
        global_state = await self._lock_global_state()
        held_stmt = select(UsageReservation).where(
            UsageReservation.id.in_(reservation_ids),
            UsageReservation.status == UsageReservationStatus.RESERVED,
        )
        held_result = await _with_timeout(
            self._session.execute(held_stmt),
            timeout_s=self._timeout_s,
            operation="load reserved usage rows for batch release",
        )
        held_rows = list(held_result.scalars().all())
        if not held_rows:
            return 0

        stmt = (
            update(UsageReservation)
            .where(
                UsageReservation.id.in_([row.id for row in held_rows]),
                UsageReservation.status == UsageReservationStatus.RESERVED,
            )
            .values(status=UsageReservationStatus.RELEASED, settled_at=func.now())
        )
        result = await _with_timeout(
            self._session.execute(stmt),
            timeout_s=self._timeout_s,
            operation="release stale usage reservations",
        )
        released = int(getattr(result, "rowcount", 0) or 0)
        if released:
            for row in held_rows:
                self._apply_settle_counters(global_state, row, target_status=UsageReservationStatus.RELEASED, now=now)
        return released

    async def release_stale_reservations(self, reservations: Iterable[UsageReservation | UsageTicket]) -> int:
        """Compatibility name for sweepers that describe the reclaimed rows explicitly."""
        return await self.release_batch(reservations)

    async def release_reservations(self, reservations: Iterable[UsageReservation | UsageTicket]) -> int:
        """Release a batch under the generic repository naming used by maintenance jobs."""
        return await self.release_batch(reservations)


# Short aliases keep the infrastructure seam convenient for callers that do
# not need to spell out the SQLAlchemy implementation detail.
UsageRepository = SqlAlchemyUsageRepository
UsageReservationRepository = SqlAlchemyUsageRepository
UsageAdmissionRepository = SqlAlchemyUsageRepository
SqlAlchemyUsageReservationRepository = SqlAlchemyUsageRepository
SqlAlchemyUsageAdmissionRepository = SqlAlchemyUsageRepository


__all__ = [
    "AllowanceExceededError",
    "GlobalUsageLimitExceededError",
    "ExpiredUsageReservationError",
    "InvalidUsageRequestError",
    "ReservationNotFoundError",
    "SqlAlchemyUsageRepository",
    "SqlAlchemyUsageAdmissionRepository",
    "SqlAlchemyUsageReservationRepository",
    "UsageAdmissionError",
    "UsageAdmissionRepository",
    "UsageAdmissionStoppedError",
    "UsageAdmissionTimeoutError",
    "UsageAdmissionUnavailableError",
    "UsageFenceMismatchError",
    "UsageFingerprintConflictError",
    "USAGE_RESERVATION_LEASE",
    "UsageRepository",
    "UsageReservationRepository",
]
