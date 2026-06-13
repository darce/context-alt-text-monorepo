"""Unit tests for phase-aware job progress helpers."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from recognition.application.scan.progress import build_scan_progress_snapshot
from recognition.domain.job import Job, JobPhase, JobStatus, JobType
from recognition.interface_adapters.http.job_utils import build_job_progress_response, derive_job_phase


@pytest.mark.parametrize(
    ("job_type", "status", "expected"),
    [
        (JobType.ANALYZE, JobStatus.PENDING, JobPhase.QUEUED),
        (JobType.ANALYZE, JobStatus.RUNNING, JobPhase.DETECTING),
        (JobType.ANALYZE, JobStatus.COMPLETED, JobPhase.COMPLETE),
        (JobType.ANALYZE, JobStatus.COMPLETED_WITH_ERRORS, JobPhase.COMPLETE),
        (JobType.ANALYZE, JobStatus.REJECTED, JobPhase.COMPLETE),
        (JobType.ANALYZE, JobStatus.FAILED, JobPhase.FAILED),
        (JobType.CLUSTERING, JobStatus.PENDING, JobPhase.QUEUED),
        (JobType.CLUSTERING, JobStatus.RUNNING, JobPhase.CLUSTERING),
        (JobType.CLUSTERING, JobStatus.COMPLETED, JobPhase.COMPLETE),
        (JobType.CLUSTERING, JobStatus.FAILED, JobPhase.FAILED),
    ],
)
@pytest.mark.asyncio
async def test_derive_job_phase(job_type: JobType, status: JobStatus, expected: JobPhase) -> None:
    assert derive_job_phase(job_type=job_type, status=status) is expected


@pytest.mark.parametrize(
    ("job_type", "status", "payload", "expected"),
    [
        # Clustering job re-queued after transient failure: RETRYING while pending
        (JobType.CLUSTERING, JobStatus.PENDING, {"retry_count": 1}, JobPhase.RETRYING),
        (JobType.CLUSTERING, JobStatus.PENDING, {"retry_count": 2}, JobPhase.RETRYING),
        # Clustering job running its retry attempt: RETRYING while running
        (JobType.CLUSTERING, JobStatus.RUNNING, {"retry_count": 1}, JobPhase.RETRYING),
        # retry_count=0 is not a retry: still QUEUED / CLUSTERING
        (JobType.CLUSTERING, JobStatus.PENDING, {"retry_count": 0}, JobPhase.QUEUED),
        (JobType.CLUSTERING, JobStatus.RUNNING, {"retry_count": 0}, JobPhase.CLUSTERING),
        # No payload: QUEUED / CLUSTERING as before
        (JobType.CLUSTERING, JobStatus.PENDING, None, JobPhase.QUEUED),
        (JobType.CLUSTERING, JobStatus.RUNNING, None, JobPhase.CLUSTERING),
        # RETRYING only applies to clustering jobs; analyze with retry_count stays QUEUED
        (JobType.ANALYZE, JobStatus.PENDING, {"retry_count": 1}, JobPhase.QUEUED),
    ],
)
def test_derive_job_phase_with_payload(
    job_type: JobType,
    status: JobStatus,
    payload: dict[str, object] | None,
    expected: JobPhase,
) -> None:
    assert derive_job_phase(job_type=job_type, status=status, payload=payload) is expected


@pytest.mark.asyncio
async def test_build_scan_progress_snapshot_uses_counts_and_faces() -> None:
    scan_repo = AsyncMock()
    scan_repo.get_job_item_status_counts.return_value = {
        "pending": 1,
        "processing": 1,
        "completed": 2,
    }
    scan_repo.get_job_item_identities_detected.return_value = 7

    snapshot = await build_scan_progress_snapshot(
        job_id=uuid.uuid4(),
        status=JobStatus.RUNNING,
        total_images=5,
        scan_repo=scan_repo,
    )

    assert snapshot.phase is JobPhase.DETECTING
    assert snapshot.images_total == 5
    assert snapshot.images_processed == 2
    assert snapshot.faces_found == 7


@pytest.mark.asyncio
async def test_build_job_progress_response_includes_scan_metrics() -> None:
    scan_repo = AsyncMock()
    scan_repo.get_job_item_status_counts.return_value = {
        "completed": 3,
        "failed": 1,
    }
    scan_repo.get_job_item_identities_detected.return_value = 11

    job = Job(
        id=str(uuid.uuid4()),
        type=JobType.ANALYZE,
        tenant_id="tenant",
        status=JobStatus.RUNNING,
        progress_completed=4,
        progress_total=6,
    )

    progress = await build_job_progress_response(job=job, scan_repo=scan_repo)
    assert progress is not None
    assert progress.completed == 3
    assert progress.total == 6
    assert progress.phase == JobPhase.DETECTING.value
    assert progress.images_processed == 3
    assert progress.faces_found == 11


@pytest.mark.asyncio
async def test_build_job_progress_response_includes_clusters_created_for_clustering() -> None:
    job = Job(
        id=str(uuid.uuid4()),
        type=JobType.CLUSTERING,
        tenant_id="tenant",
        status=JobStatus.RUNNING,
        progress_completed=2,
        progress_total=5,
        payload={"clusters_created": 3},
    )

    progress = await build_job_progress_response(job=job, scan_repo=None)
    assert progress is not None
    assert progress.phase == JobPhase.CLUSTERING.value
    assert progress.clusters_created == 3


@pytest.mark.asyncio
async def test_build_job_progress_response_marks_failed_jobs_failed() -> None:
    job = Job(
        id=str(uuid.uuid4()),
        type=JobType.CLUSTERING,
        tenant_id="tenant",
        status=JobStatus.FAILED,
        progress_completed=50,
        progress_total=194,
    )

    progress = await build_job_progress_response(job=job, scan_repo=None)
    assert progress is not None
    assert progress.phase == JobPhase.FAILED.value


@pytest.mark.asyncio
async def test_build_job_progress_response_includes_current_chunk_size() -> None:
    job = Job(
        id=str(uuid.uuid4()),
        type=JobType.CLUSTERING,
        tenant_id="tenant",
        status=JobStatus.RUNNING,
        progress_completed=5,
        progress_total=12,
        payload={"current_chunk_size": 5, "clusters_created": 2},
    )

    progress = await build_job_progress_response(job=job, scan_repo=None)
    assert progress is not None
    assert progress.current_chunk_size == 5
