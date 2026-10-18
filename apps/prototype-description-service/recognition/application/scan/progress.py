"""Phase-aware scan job progress helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from recognition.application.scan.queue_repository import ScanQueueRepository
from recognition.domain.job import Job, JobPhase, JobStatus


def scan_phase_for_status(status: JobStatus) -> JobPhase:
    """Map a job status to its scan progress phase.

    Explicit per-status mapping so terminal statuses (``COMPLETED_WITH_ERRORS``,
    ``REJECTED``) cannot silently fall through to ``COMPLETE`` and a newly added
    :class:`JobStatus` fails loudly instead of defaulting (E15-27-BR-21).
    """
    match status:
        case JobStatus.PENDING:
            return JobPhase.QUEUED
        case JobStatus.RUNNING:
            return JobPhase.DETECTING
        case JobStatus.FAILED:
            return JobPhase.FAILED
        case JobStatus.COMPLETED | JobStatus.COMPLETED_WITH_ERRORS | JobStatus.REJECTED:
            return JobPhase.COMPLETE
    raise ValueError(f"Unhandled JobStatus for scan phase mapping: {status!r}")


@dataclass(frozen=True, slots=True)
class ScanJobProgressSnapshot:
    """Progress snapshot for scan/analyze jobs.

    Attributes:
        phase: High-level phase marker (queued, detecting, complete).
        images_total: Total images expected for the job.
        images_processed: Number of images completed (status=completed).
        faces_found: Running count of detected faces/identities.
    """

    phase: JobPhase
    images_total: int
    images_processed: int
    faces_found: int


async def build_scan_progress_snapshot(
    *,
    job_id: uuid.UUID,
    status: JobStatus,
    total_images: int,
    scan_repo: ScanQueueRepository,
) -> ScanJobProgressSnapshot:
    """Build a phase-aware scan job progress snapshot.

    Args:
        job_id: Scan job UUID.
        status: Current job status.
        total_images: Total images expected for the job.
        scan_repo: Repository for scan queue items.

    Returns:
        ScanJobProgressSnapshot with phase + progress counters.
    """
    status_counts = await scan_repo.get_job_item_status_counts(job_id=job_id)
    faces_found = await scan_repo.get_job_item_identities_detected(job_id=job_id)
    images_total = max(total_images, sum(status_counts.values()))
    images_processed = min(status_counts.get("completed", 0), images_total)

    phase = scan_phase_for_status(status)

    return ScanJobProgressSnapshot(
        phase=phase,
        images_total=images_total,
        images_processed=images_processed,
        faces_found=faces_found,
    )


@dataclass(frozen=True, slots=True)
class ScanProgressEnvelope:
    """Poll-cheap scan progress contract for plugin/E15-22 consumers."""

    job_id: str
    status: JobStatus
    phase: JobPhase
    items_total: int
    items_done: int
    items_failed: int
    failure_reason: str | None
    updated_at: datetime


async def build_scan_progress_envelope(
    *,
    job: Job,
    scan_repo: ScanQueueRepository,
) -> ScanProgressEnvelope:
    """Build the scan progress envelope from live item aggregates."""
    job_uuid = uuid.UUID(str(job.id))
    status_counts = await scan_repo.get_job_item_status_counts(job_id=job_uuid)
    items_total = max(job.progress_total or 0, sum(status_counts.values()))
    items_done = status_counts.get("completed", 0)
    items_failed = status_counts.get("failed", 0)

    phase = scan_phase_for_status(job.status)

    updated_at = job.finished_at or job.started_at or datetime.now(tz=UTC)
    failure_reason = job.error_message if job.status in {JobStatus.FAILED, JobStatus.COMPLETED_WITH_ERRORS} else None

    return ScanProgressEnvelope(
        job_id=job.id,
        status=job.status,
        phase=phase,
        items_total=items_total,
        items_done=items_done,
        items_failed=items_failed,
        failure_reason=failure_reason,
        updated_at=updated_at,
    )


__all__ = [
    "ScanJobProgressSnapshot",
    "ScanProgressEnvelope",
    "build_scan_progress_envelope",
    "build_scan_progress_snapshot",
    "scan_phase_for_status",
]
