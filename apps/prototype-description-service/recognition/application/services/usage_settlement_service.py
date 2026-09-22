"""G3 usage settlement: reconstruct tickets from persisted jobs and settle once.

Workers capture the opaque reservation fence at claim and pass it unchanged to
``commit_fenced`` / ``release_fenced``. This module never synthesizes a fence or
replaces a captured token with the current row. Sweeper/reclaim may use the
persisted token only after proving the bound job is inactive or terminal under
DB locks; elapsed reservation age alone is not authorization to release.

[RES-01][RES-02][RES-05][DATA-03][GRPH-09]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from db.models import IdentityScanJob, UsageReservation
from db.models.scene import DescribeDemandLease, DescribeOperation, DescribeRun
from recognition.application.services.usage_admission_service import (
    UsageAdmissionService,
    UsageFenceMismatchError,
)
from recognition.domain.job import TERMINAL_JOB_STATUSES, JobStatus
from recognition.domain.portal_contracts import UsageReservationStatus, UsageTicket
from recognition.infrastructure.repositories.usage_repository import SqlAlchemyUsageRepository
from scene.domain.describe_run import TERMINAL_RUN_STATUSES, DescribeRunStatus

_logger = logging.getLogger(__name__)

_ACTIVE_DESCRIBE_STATUSES = {DescribeRunStatus.PENDING, DescribeRunStatus.RUNNING}
_ACTIVE_SCAN_STATUSES = {JobStatus.PENDING, JobStatus.RUNNING}
_SUCCESS_DESCRIBE_STATUSES = {
    DescribeRunStatus.COMPLETED,
    DescribeRunStatus.COMPLETED_WITH_ERRORS,
}
_SUCCESS_SCAN_STATUSES = {JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS}
_MISSING_RELATION_MARKERS = ("no such table", "does not exist", "undefinedtable")

# G1 does not expose a settle-time API that binds reservation.fence_token to
# usage_admission_global_state.fence_epoch. Workers therefore treat the token as
# opaque and refuse to refresh it on a callback. [GRPH-09]
MISSING_GENERATION_FENCE_CONTRACT = (
    "G1 settle identity is reservation_id+tenant+idempotency+cost+opaque fence_token; "
    "there is no shared-repo API to re-fence a captured worker callback against "
    "usage_admission_global_state.fence_epoch. Stale callbacks must keep the claim-time "
    "token and must not substitute the current reservation.fence_token."
)


class SettlementOutcome(StrEnum):
    COMMITTED = "committed"
    RELEASED = "released"
    SKIPPED_ACTIVE = "skipped_active"
    REJECTED = "rejected"
    MISSING = "missing"
    FAIL_CLOSED = "fail_closed"
    ALREADY_SETTLED = "already_settled"


@dataclass(frozen=True, slots=True)
class UsageClaim:
    """Fence captured from the persisted reservation at work claim."""

    ticket: UsageTicket
    fence_token: str


@dataclass(frozen=True, slots=True)
class SettlementResult:
    outcome: SettlementOutcome
    reservation_id: UUID | None = None
    detail: str = ""


@dataclass
class SweepReport:
    released: int = 0
    committed: int = 0
    skipped_active: int = 0
    rejected: int = 0
    fail_closed: int = 0
    already_settled: int = 0
    missing: int = 0
    stale_seen: int = 0
    batches: int = 0
    no_progress_cycles: int = 0
    stalled: bool = False
    exit_code: int = 0
    notes: list[str] = field(default_factory=list)


def ticket_from_reservation(reservation: UsageReservation) -> UsageTicket:
    """Rebuild a G1 ticket from the persisted reservation row. Token stays opaque."""
    return UsageTicket(
        reservation_id=reservation.id,
        tenant_id=reservation.tenant_id,
        idempotency_key=reservation.idempotency_key,
        cost_units=int(reservation.cost_units),
        operation_id=reservation.operation_id or reservation.idempotency_key,
        request_fingerprint=reservation.request_fingerprint or reservation.idempotency_key,
        job_id=reservation.job_id,
        fence_token=reservation.fence_token or "",
    )


def _missing_relation(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _MISSING_RELATION_MARKERS)


def _as_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _has_started(job: Any) -> bool:
    return (
        getattr(job, "started_at", None) is not None
        or getattr(job, "queue_ms", None) is not None
        or getattr(job, "processing_ms", None) is not None
    )


class UsageSettlementService:
    """Look up reservation+job evidence and settle through G1 only."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        admission: UsageAdmissionService | None = None,
    ) -> None:
        self._session = session
        self._admission = admission or UsageAdmissionService(session)

    async def _lookup(self, statement):
        try:
            async with self._session.begin_nested():
                result = await self._session.execute(statement)
                return result.scalar_one_or_none()
        except (OperationalError, ProgrammingError) as exc:
            if _missing_relation(exc):
                return None
            raise

    async def _get_reservation(self, *, tenant_id: UUID, job_id: str) -> UsageReservation | None:
        return await self._lookup(
            select(UsageReservation)
            .where(
                UsageReservation.tenant_id == tenant_id,
                UsageReservation.job_id == job_id,
            )
            .limit(1)
        )

    async def load_claim(self, *, tenant_id: UUID, job_id: str) -> UsageClaim | None:
        """Read the persisted fence at claim. Never invent a token."""
        reservation = await self._get_reservation(tenant_id=tenant_id, job_id=job_id)
        if reservation is None or not (reservation.fence_token or "").strip():
            return None
        return UsageClaim(ticket=ticket_from_reservation(reservation), fence_token=reservation.fence_token)

    def _identity_ok(
        self,
        reservation: UsageReservation,
        *,
        fence_token: str,
        operation_id: str | None,
        request_fingerprint: str | None,
        job_id: str | None,
        tenant_id: UUID,
    ) -> str | None:
        if reservation.tenant_id != tenant_id:
            return "tenant mismatch"
        if job_id is not None and reservation.job_id and reservation.job_id != job_id:
            return "job mismatch"
        if operation_id and reservation.operation_id and reservation.operation_id != operation_id:
            return "operation mismatch"
        if (
            request_fingerprint
            and reservation.request_fingerprint
            and reservation.request_fingerprint != request_fingerprint
        ):
            return "fingerprint mismatch"
        if not fence_token or fence_token != (reservation.fence_token or ""):
            return "fence mismatch"
        return None

    async def _describe_evidence(self, *, tenant_id: UUID, job_uuid: UUID | None) -> SettlementOutcome | None:
        if job_uuid is None:
            return None
        run = await self._lookup(
            select(DescribeRun)
            .options(noload(DescribeRun.items))
            .where(DescribeRun.tenant_id == tenant_id, DescribeRun.id == job_uuid)
            .limit(1)
        )
        if run is None:
            return None
        try:
            status = DescribeRunStatus(run.status)
        except (TypeError, ValueError):
            return SettlementOutcome.FAIL_CLOSED
        if status in _ACTIVE_DESCRIBE_STATUSES:
            return SettlementOutcome.SKIPPED_ACTIVE
        if status not in TERMINAL_RUN_STATUSES:
            return SettlementOutcome.FAIL_CLOSED
        if status in _SUCCESS_DESCRIBE_STATUSES:
            return SettlementOutcome.COMMITTED
        if status is DescribeRunStatus.CANCELLED and not _has_started(run):
            return SettlementOutcome.RELEASED
        if status is DescribeRunStatus.FAILED and not _has_started(run):
            return SettlementOutcome.RELEASED
        return SettlementOutcome.COMMITTED

    async def _scan_evidence(self, *, tenant_id: UUID, job_uuid: UUID | None) -> SettlementOutcome | None:
        if job_uuid is None:
            return None
        job = await self._lookup(
            select(IdentityScanJob)
            .options(noload(IdentityScanJob.items))
            .where(IdentityScanJob.tenant_id == tenant_id, IdentityScanJob.id == job_uuid)
            .limit(1)
        )
        if job is None:
            return None
        try:
            status = JobStatus(job.status)
        except (TypeError, ValueError):
            return SettlementOutcome.FAIL_CLOSED
        if status in _ACTIVE_SCAN_STATUSES:
            return SettlementOutcome.SKIPPED_ACTIVE
        if status not in TERMINAL_JOB_STATUSES:
            return SettlementOutcome.FAIL_CLOSED
        if status in _SUCCESS_SCAN_STATUSES:
            return SettlementOutcome.COMMITTED
        if status is JobStatus.FAILED and not _has_started(job):
            error = (job.error_message or "").lower()
            if "cancel" in error:
                return SettlementOutcome.RELEASED
            return SettlementOutcome.RELEASED
        if status is JobStatus.REJECTED and not _has_started(job):
            return SettlementOutcome.RELEASED
        return SettlementOutcome.COMMITTED

    async def _operation_evidence(self, *, tenant_id: UUID, operation_id: str | None) -> SettlementOutcome | None:
        if not operation_id:
            return None
        operation = await self._lookup(
            select(DescribeOperation)
            .where(
                DescribeOperation.tenant_id == tenant_id,
                DescribeOperation.operation_id == operation_id,
            )
            .limit(1)
        )
        if operation is None:
            return None
        lease = await self._lookup(
            select(DescribeDemandLease)
            .where(
                DescribeDemandLease.tenant_id == tenant_id,
                DescribeDemandLease.operation_id == operation_id,
            )
            .limit(1)
        )
        if lease is not None and str(lease.state) == "active":
            return SettlementOutcome.SKIPPED_ACTIVE
        if operation.completed_at is None:
            return SettlementOutcome.SKIPPED_ACTIVE
        if operation.processing_ms is not None:
            return SettlementOutcome.COMMITTED
        return SettlementOutcome.RELEASED

    async def _decide(
        self,
        reservation: UsageReservation,
        *,
        allow_missing_job_release: bool,
    ) -> SettlementOutcome:
        job_uuid = _as_uuid(reservation.job_id)
        for reader in (
            lambda: self._describe_evidence(tenant_id=reservation.tenant_id, job_uuid=job_uuid),
            lambda: self._scan_evidence(tenant_id=reservation.tenant_id, job_uuid=job_uuid),
            lambda: self._operation_evidence(tenant_id=reservation.tenant_id, operation_id=reservation.operation_id),
        ):
            outcome = await reader()
            if outcome is not None:
                return outcome
        if allow_missing_job_release:
            return SettlementOutcome.RELEASED
        return SettlementOutcome.FAIL_CLOSED

    async def settle_job(
        self,
        *,
        tenant_id: UUID,
        job_id: str,
        fence_token: str | None = None,
        operation_id: str | None = None,
        request_fingerprint: str | None = None,
        allow_missing_job_release: bool = False,
    ) -> SettlementResult:
        """Settle one job through G1 using captured fence when provided.

        A captured ``fence_token`` is retained even if the row later shows a
        different token. Missing/unknown job evidence fail-closes unless the
        caller is the stale sweeper proving no job row exists.
        """
        reservation = await self._get_reservation(tenant_id=tenant_id, job_id=job_id)
        if reservation is None:
            return SettlementResult(SettlementOutcome.MISSING, detail="reservation not found")
        try:
            status = UsageReservationStatus(reservation.status)
        except (TypeError, ValueError):
            return SettlementResult(
                SettlementOutcome.FAIL_CLOSED,
                reservation_id=reservation.id,
                detail="unknown reservation status",
            )
        if status is not UsageReservationStatus.RESERVED:
            return SettlementResult(SettlementOutcome.ALREADY_SETTLED, reservation_id=reservation.id)

        if fence_token is None:
            if not allow_missing_job_release:
                # Worker callback without a captured fence: reconstruct from the
                # row only after job evidence is proven. Token stays the persisted
                # opaque value, never a newly generated one.
                token = reservation.fence_token or ""
            else:
                token = reservation.fence_token or ""
        else:
            token = fence_token

        mismatch = self._identity_ok(
            reservation,
            fence_token=token,
            operation_id=operation_id,
            request_fingerprint=request_fingerprint,
            job_id=job_id,
            tenant_id=tenant_id,
        )
        if mismatch:
            return SettlementResult(
                SettlementOutcome.REJECTED,
                reservation_id=reservation.id,
                detail=mismatch,
            )

        decision = await self._decide(reservation, allow_missing_job_release=allow_missing_job_release)
        if decision is SettlementOutcome.SKIPPED_ACTIVE:
            return SettlementResult(decision, reservation_id=reservation.id, detail="job still active")
        if decision is SettlementOutcome.FAIL_CLOSED:
            return SettlementResult(
                decision,
                reservation_id=reservation.id,
                detail="unsafe unknown job state; not releasing",
            )
        if decision not in {SettlementOutcome.COMMITTED, SettlementOutcome.RELEASED}:
            return SettlementResult(SettlementOutcome.FAIL_CLOSED, reservation_id=reservation.id)

        ticket = ticket_from_reservation(reservation)
        try:
            if decision is SettlementOutcome.COMMITTED:
                await self._admission.commit_fenced(ticket, fence_token=token)
            else:
                await self._admission.release_fenced(ticket, fence_token=token)
        except UsageFenceMismatchError:
            return SettlementResult(
                SettlementOutcome.REJECTED,
                reservation_id=reservation.id,
                detail="stale fence rejected by G1",
            )
        return SettlementResult(decision, reservation_id=reservation.id)

    async def settle_ticket(
        self,
        ticket: UsageTicket,
        *,
        action: SettlementOutcome,
        fence_token: str | None = None,
    ) -> SettlementResult:
        """Direct terminal callback with a captured ticket+fence (worker path)."""
        token = fence_token if fence_token is not None else ticket.fence_token
        if not token:
            return SettlementResult(SettlementOutcome.FAIL_CLOSED, detail="missing captured fence")
        if action is SettlementOutcome.COMMITTED:
            job_decision = SettlementOutcome.COMMITTED
        elif action is SettlementOutcome.RELEASED:
            job_decision = SettlementOutcome.RELEASED
        else:
            return SettlementResult(SettlementOutcome.FAIL_CLOSED, detail="invalid terminal action")
        reservation = await self._lookup(
            select(UsageReservation)
            .where(
                UsageReservation.id == ticket.reservation_id,
                UsageReservation.tenant_id == ticket.tenant_id,
            )
            .limit(1)
        )
        if reservation is None:
            return SettlementResult(SettlementOutcome.MISSING, detail="reservation not found")
        mismatch = self._identity_ok(
            reservation,
            fence_token=token,
            operation_id=ticket.operation_id,
            request_fingerprint=ticket.request_fingerprint,
            job_id=ticket.job_id,
            tenant_id=ticket.tenant_id,
        )
        if mismatch:
            return SettlementResult(
                SettlementOutcome.REJECTED,
                reservation_id=reservation.id,
                detail=mismatch,
            )
        try:
            status = UsageReservationStatus(reservation.status)
        except (TypeError, ValueError):
            return SettlementResult(SettlementOutcome.FAIL_CLOSED, reservation_id=reservation.id)
        if status is not UsageReservationStatus.RESERVED:
            return SettlementResult(SettlementOutcome.ALREADY_SETTLED, reservation_id=reservation.id)
        reconstructed = ticket_from_reservation(reservation)
        try:
            if job_decision is SettlementOutcome.COMMITTED:
                await self._admission.commit_fenced(reconstructed, fence_token=token)
            else:
                await self._admission.release_fenced(reconstructed, fence_token=token)
        except UsageFenceMismatchError:
            return SettlementResult(
                SettlementOutcome.REJECTED,
                reservation_id=reservation.id,
                detail="stale fence rejected by G1",
            )
        return SettlementResult(job_decision, reservation_id=reservation.id)

    async def sweep_stale_reservations(
        self,
        *,
        stale_after_seconds: float,
        max_batches: int = 10,
        batch_size: int = 100,
        no_progress_limit: int = 3,
    ) -> SweepReport:
        """Bounded stale scan. Active jobs are never released. [rg-007]"""
        report = SweepReport()
        report.notes.append(MISSING_GENERATION_FENCE_CONTRACT)
        repo = SqlAlchemyUsageRepository(self._session)
        no_progress = 0
        for _ in range(max(1, max_batches)):
            report.batches += 1
            try:
                rows = await repo.list_stale_reservations(stale_after_seconds, limit=batch_size)
            except (OperationalError, ProgrammingError) as exc:
                if _missing_relation(exc):
                    report.exit_code = 0
                    return report
                raise
            if not rows:
                report.exit_code = 0
                return report
            report.stale_seen += len(rows)
            progressed = 0
            for row in rows:
                result = await self.settle_job(
                    tenant_id=row.tenant_id,
                    job_id=str(row.job_id or ""),
                    fence_token=None,
                    allow_missing_job_release=True,
                )
                if result.outcome is SettlementOutcome.RELEASED:
                    report.released += 1
                    progressed += 1
                elif result.outcome is SettlementOutcome.COMMITTED:
                    report.committed += 1
                    progressed += 1
                elif result.outcome is SettlementOutcome.SKIPPED_ACTIVE:
                    report.skipped_active += 1
                elif result.outcome is SettlementOutcome.REJECTED:
                    report.rejected += 1
                    progressed += 1
                elif result.outcome is SettlementOutcome.ALREADY_SETTLED:
                    report.already_settled += 1
                    progressed += 1
                elif result.outcome is SettlementOutcome.MISSING:
                    report.missing += 1
                else:
                    report.fail_closed += 1
            if report.skipped_active and progressed == 0 and report.fail_closed == 0:
                # Active work remains reserved on purpose; that is a successful sweep.
                report.exit_code = 0
                return report
            if progressed == 0:
                no_progress += 1
                report.no_progress_cycles = no_progress
                if no_progress >= max(1, no_progress_limit):
                    report.stalled = True
                    report.exit_code = 1
                    return report
            else:
                no_progress = 0
        report.exit_code = 0
        return report


async def capture_usage_fence(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    job_id: str,
) -> str | None:
    """Best-effort claim-time fence capture; missing ledger is not an error."""
    try:
        claim = await UsageSettlementService(session).load_claim(tenant_id=tenant_id, job_id=job_id)
    except Exception:
        _logger.debug("usage fence capture failed job_id=%s", job_id, exc_info=True)
        return None
    return None if claim is None else claim.fence_token


async def settle_usage_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    job_id: str,
    fence_token: str | None = None,
    allow_missing_job_release: bool = False,
) -> SettlementResult:
    try:
        return await UsageSettlementService(session).settle_job(
            tenant_id=tenant_id,
            job_id=job_id,
            fence_token=fence_token,
            allow_missing_job_release=allow_missing_job_release,
        )
    except Exception as exc:
        _logger.exception("usage settlement failed job_id=%s", job_id)
        return SettlementResult(SettlementOutcome.FAIL_CLOSED, detail=str(exc))


async def sweep_stale_reservations(
    session: AsyncSession,
    *,
    stale_after_seconds: float,
    max_batches: int = 10,
    batch_size: int = 100,
    no_progress_limit: int = 3,
) -> SweepReport:
    """Module-level sweeper used by unit tests and worker maintenance."""
    return await UsageSettlementService(session).sweep_stale_reservations(
        stale_after_seconds=stale_after_seconds,
        max_batches=max_batches,
        batch_size=batch_size,
        no_progress_limit=no_progress_limit,
    )


__all__ = [
    "MISSING_GENERATION_FENCE_CONTRACT",
    "SettlementOutcome",
    "SettlementResult",
    "SweepReport",
    "UsageClaim",
    "UsageSettlementService",
    "capture_usage_fence",
    "settle_usage_job",
    "sweep_stale_reservations",
    "ticket_from_reservation",
]
