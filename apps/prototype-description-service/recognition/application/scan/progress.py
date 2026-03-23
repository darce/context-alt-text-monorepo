"""Phase-aware scan job progress helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from recognition.application.scan.queue_repository import ScanQueueRepository
from recognition.domain.job import JobPhase, JobStatus


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

    if status is JobStatus.PENDING:
        phase = JobPhase.QUEUED
    elif status is JobStatus.RUNNING:
        phase = JobPhase.DETECTING
    elif status is JobStatus.FAILED:
        phase = JobPhase.FAILED
    else:
        phase = JobPhase.COMPLETE

    return ScanJobProgressSnapshot(
        phase=phase,
        images_total=images_total,
        images_processed=images_processed,
        faces_found=faces_found,
    )


__all__ = ["ScanJobProgressSnapshot", "build_scan_progress_snapshot"]
