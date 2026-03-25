"""
Shared job utilities for recognition HTTP API.

This module provides common job-related functions used across routers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from recognition.application.scan.progress import build_scan_progress_snapshot
from recognition.application.scan.queue_repository import ScanQueueRepository
from recognition.domain.job import Job, JobPhase, JobStatus, JobType
from recognition.interface_adapters.http.schemas.responses import (
    ClusteringJobStatusResponse,
    JobProgressResponse,
    JobStatusResponse,
)


async def job_to_response(job: Job, *, scan_repo: ScanQueueRepository | None = None) -> JobStatusResponse:
    """Convert Job domain object to API response.

    Args:
        job: Domain Job object with status and progress.
        scan_repo: Optional scan queue repository for scan job metrics.

    Returns:
        JobStatusResponse suitable for API serialization.
    """
    progress = await build_job_progress_response(job=job, scan_repo=scan_repo)
    started_at = job.started_at or datetime.now(tz=UTC)
    return JobStatusResponse(
        id=job.id,
        type=job.type.value,
        status=job.status.value,
        progress=progress,
        started_at=started_at,
        finished_at=job.finished_at,
        message=job.message,
        snapshot_version=None,
        source_job_id=None,
        projection_acknowledged_at=None,
    )


def derive_job_phase(
    *,
    job_type: JobType,
    status: JobStatus,
    payload: dict[str, object] | None = None,
) -> JobPhase:
    """Map a job type + status to a progress phase.

    For clustering jobs, ``RETRYING`` is returned when ``payload`` carries a
    non-zero ``retry_count``, signalling the job was re-queued after a transient
    failure (Phase 4: pipeline-truth enrichment).
    """
    if status is JobStatus.PENDING:
        if (
            job_type is JobType.CLUSTERING
            and isinstance(payload, dict)
            and isinstance(payload.get("retry_count"), int)
            and payload["retry_count"] > 0
        ):
            return JobPhase.RETRYING
        return JobPhase.QUEUED
    if status is JobStatus.RUNNING:
        if job_type is JobType.ANALYZE:
            return JobPhase.DETECTING
        if isinstance(payload, dict) and isinstance(payload.get("retry_count"), int) and payload["retry_count"] > 0:
            return JobPhase.RETRYING
        return JobPhase.CLUSTERING
    if status is JobStatus.FAILED:
        return JobPhase.FAILED
    return JobPhase.COMPLETE


async def build_job_progress_response(
    *,
    job: Job,
    scan_repo: ScanQueueRepository | None = None,
) -> JobProgressResponse | None:
    """Build a phase-aware JobProgressResponse for a job.

    Args:
        job: Domain Job object with status and progress.
        scan_repo: Optional scan queue repository for scan job metrics.

    Returns:
        JobProgressResponse with phase and optional metrics, or None if progress unavailable.
    """
    if job.progress_total is None:
        return None

    phase = derive_job_phase(job_type=job.type, status=job.status, payload=job.payload)
    if job.type is JobType.ANALYZE and scan_repo is not None:
        try:
            job_uuid = _coerce_uuid(job.id)
        except ValueError:
            job_uuid = None
        if job_uuid is not None:
            snapshot = await build_scan_progress_snapshot(
                job_id=job_uuid,
                status=job.status,
                total_images=job.progress_total,
                scan_repo=scan_repo,
            )
            return JobProgressResponse(
                completed=snapshot.images_processed,
                total=snapshot.images_total,
                phase=snapshot.phase.value,
                images_processed=snapshot.images_processed,
                faces_found=snapshot.faces_found,
            )

    clusters_created = None
    if isinstance(job.payload, dict) and "clusters_created" in job.payload:
        try:
            clusters_created = int(job.payload.get("clusters_created", 0) or 0)
        except (TypeError, ValueError):
            clusters_created = None

    # Extract Phase-2 checkpoint/retry metadata from job payload so clients
    # can display truthful pipeline UX (finding 1165).
    (
        retry_count,
        current_stage,
        last_successful_processed_identities,
        last_error_code,
        current_chunk_size,
    ) = _extract_checkpoint_fields(job.payload)

    return JobProgressResponse(
        completed=job.progress_completed,
        total=job.progress_total,
        phase=phase.value,
        clusters_created=clusters_created,
        retry_count=retry_count,
        current_stage=current_stage,
        last_successful_processed_identities=last_successful_processed_identities,
        last_error_code=last_error_code,
        current_chunk_size=current_chunk_size,
    )


def _coerce_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid job id for progress lookup")


def _extract_checkpoint_fields(
    payload: dict[str, object] | None,
) -> tuple[int | None, str | None, int | None, str | None, int | None]:
    """Extract Phase-2 checkpoint/retry fields from a job payload dict.

    Returns:
        (retry_count, current_stage, last_successful_processed_identities, last_error_code, current_chunk_size)
    """
    if not isinstance(payload, dict):
        return None, None, None, None, None

    retry_count: int | None = None
    try:
        _rc = payload.get("retry_count")
        if _rc is not None:
            retry_count = int(_rc)
    except (TypeError, ValueError):
        pass

    current_stage: str | None = payload.get("current_stage") or None  # type: ignore[assignment]
    last_error_code: str | None = payload.get("last_error_code") or None  # type: ignore[assignment]

    last_successful_processed_identities: int | None = None
    try:
        _lsp = payload.get("last_successful_processed_identities")
        if _lsp is not None:
            last_successful_processed_identities = int(_lsp)
    except (TypeError, ValueError):
        pass

    current_chunk_size: int | None = None
    try:
        _ccs = payload.get("current_chunk_size")
        if _ccs is not None:
            current_chunk_size = int(_ccs)
    except (TypeError, ValueError):
        pass

    return retry_count, current_stage, last_successful_processed_identities, last_error_code, current_chunk_size


def job_to_clustering_response(job: Job) -> ClusteringJobStatusResponse:
    """Convert Job domain object to clustering API response.

    Args:
        job: Domain Job object with status and progress.

    Returns:
        ClusteringJobStatusResponse with clustering-specific fields.
    """
    phase = derive_job_phase(job_type=job.type, status=job.status, payload=job.payload)
    clusters_created = None
    if isinstance(job.payload, dict) and "clusters_created" in job.payload:
        try:
            clusters_created = int(job.payload.get("clusters_created", 0) or 0)
        except (TypeError, ValueError):
            clusters_created = None

    (
        retry_count,
        current_stage,
        last_successful_processed_identities,
        last_error_code,
        current_chunk_size,
    ) = _extract_checkpoint_fields(job.payload)

    progress = JobProgressResponse(
        completed=job.progress_completed,
        total=job.progress_total,
        phase=phase.value,
        clusters_created=clusters_created,
        retry_count=retry_count,
        current_stage=current_stage,
        last_successful_processed_identities=last_successful_processed_identities,
        last_error_code=last_error_code,
        current_chunk_size=current_chunk_size,
    )
    started_at = job.started_at or datetime.now(tz=UTC)
    return ClusteringJobStatusResponse(
        id=job.id,
        type=job.type.value,
        status=job.status.value,
        progress=progress,
        started_at=started_at,
        finished_at=job.finished_at,
        message=job.message,
        snapshot_version=None,
        source_job_id=None,
        projection_acknowledged_at=None,
        clusters_created=0,  # Not known until job completes
        total_identities_clustered=job.progress_completed,
    )


__all__ = ["job_to_response", "job_to_clustering_response"]
