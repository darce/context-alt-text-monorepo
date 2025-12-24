"""
Shared job utilities for recognition HTTP API.

This module provides common job-related functions used across routers.
"""

from __future__ import annotations

from datetime import UTC, datetime

from recognition.domain.job import Job
from recognition.interface_adapters.http.schemas.responses import (
    ClusteringJobStatusResponse,
    JobProgressResponse,
    JobStatusResponse,
)


def job_to_response(job: Job) -> JobStatusResponse:
    """Convert Job domain object to API response.

    Args:
        job: Domain Job object with status and progress.

    Returns:
        JobStatusResponse suitable for API serialization.
    """
    progress = JobProgressResponse(completed=job.progress_completed, total=job.progress_total)
    started_at = job.started_at or datetime.now(tz=UTC)
    return JobStatusResponse(
        id=job.id,
        type=job.type.value,
        status=job.status.value,
        progress=progress,
        started_at=started_at,
        finished_at=job.finished_at,
        message=job.message,
    )


def job_to_clustering_response(job: Job) -> ClusteringJobStatusResponse:
    """Convert Job domain object to clustering API response.

    Args:
        job: Domain Job object with status and progress.

    Returns:
        ClusteringJobStatusResponse with clustering-specific fields.
    """
    progress = JobProgressResponse(completed=job.progress_completed, total=job.progress_total)
    started_at = job.started_at or datetime.now(tz=UTC)
    return ClusteringJobStatusResponse(
        id=job.id,
        type=job.type.value,
        status=job.status.value,
        progress=progress,
        started_at=started_at,
        finished_at=job.finished_at,
        message=job.message,
        clusters_created=0,  # Not known until job completes
        total_identities_clustered=job.progress_completed,
    )


__all__ = ["job_to_response", "job_to_clustering_response"]
