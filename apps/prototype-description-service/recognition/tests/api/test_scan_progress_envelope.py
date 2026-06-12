"""E15-27 Slice 2: scan progress envelope on GET /recognition/jobs/{job_id}."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from recognition.application.scan.progress import build_scan_progress_envelope
from recognition.domain.job import Job, JobPhase, JobStatus, JobType
from recognition.interface_adapters.http.job_utils import job_to_response


@pytest.mark.asyncio
async def test_build_scan_progress_envelope_shape() -> None:
    job_id = uuid.uuid4()
    scan_repo = AsyncMock()
    scan_repo.get_job_item_status_counts.return_value = {
        "pending": 1,
        "completed": 2,
        "failed": 1,
    }

    job = Job(
        id=str(job_id),
        type=JobType.ANALYZE,
        tenant_id=str(uuid.uuid4()),
        status=JobStatus.RUNNING,
        progress_completed=3,
        progress_total=4,
        started_at=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    )

    envelope = await build_scan_progress_envelope(job=job, scan_repo=scan_repo)

    assert envelope.job_id == str(job_id)
    assert envelope.status is JobStatus.RUNNING
    assert envelope.phase is JobPhase.DETECTING
    assert envelope.items_total == 4
    assert envelope.items_done == 2
    assert envelope.items_failed == 1
    assert envelope.failure_reason is None
    assert envelope.updated_at == job.started_at


@pytest.mark.asyncio
async def test_job_to_response_includes_progress_envelope_for_analyze_jobs() -> None:
    job_id = uuid.uuid4()
    scan_repo = AsyncMock()
    scan_repo.get_job_item_status_counts.return_value = {"completed": 2, "pending": 1}
    scan_repo.get_job_item_identities_detected.return_value = 5

    job = Job(
        id=str(job_id),
        type=JobType.ANALYZE,
        tenant_id=str(uuid.uuid4()),
        status=JobStatus.RUNNING,
        progress_completed=2,
        progress_total=3,
        started_at=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    )

    response = await job_to_response(job, scan_repo=scan_repo)

    assert response.progress_envelope is not None
    assert response.progress_envelope.job_id == str(job_id)
    assert response.progress_envelope.items_total == 3
    assert response.progress_envelope.items_done == 2
    assert response.progress_envelope.phase == JobPhase.DETECTING


@pytest.mark.asyncio
async def test_progress_envelope_counts_monotonic_across_batches(db_session, tenant) -> None:
    from recognition.application.scan.scan_queue_service import ScanQueueService
    from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository

    repo = SqlAlchemyScanQueueRepository(db_session)
    queue = ScanQueueService(repo)

    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1, 2, 3])
    await repo.enqueue_items(
        job_id=job_id,
        tenant_id=tenant.id,
        items=[
            (1, "http://example.test/1.jpg"),
            (2, "http://example.test/2.jpg"),
            (3, "http://example.test/3.jpg"),
        ],
    )
    await repo.mark_job_running(job_id=job_id, started_at=datetime.now(tz=UTC))

    job = Job(
        id=str(job_id),
        type=JobType.ANALYZE,
        tenant_id=str(tenant.id),
        status=JobStatus.RUNNING,
        progress_completed=0,
        progress_total=3,
        started_at=datetime.now(tz=UTC),
    )

    first_batch = await repo.claim_pending_items(
        tenant_id=tenant.id,
        job_id=job_id,
        limit=2,
        now=datetime.now(tz=UTC),
    )
    for item in first_batch:
        await repo.mark_item_completed(
            item_id=item.id,
            completed_at=datetime.now(tz=UTC),
            identities_detected=1,
        )
    await queue.refresh_job_progress(job_id=job_id)

    first = await build_scan_progress_envelope(job=job, scan_repo=repo)
    assert first.items_done == 2
    assert first.items_failed == 0

    second_batch = await repo.claim_pending_items(
        tenant_id=tenant.id,
        job_id=job_id,
        limit=2,
        now=datetime.now(tz=UTC),
    )
    assert len(second_batch) == 1
    await repo.mark_item_failed(
        item_id=second_batch[0].id,
        completed_at=datetime.now(tz=UTC),
        error_message="decode error",
    )
    await queue.refresh_job_progress(job_id=job_id)

    job.status = JobStatus.COMPLETED_WITH_ERRORS
    job.error_message = "one or more items failed"
    second = await build_scan_progress_envelope(job=job, scan_repo=repo)

    assert second.items_done >= first.items_done
    assert second.items_done + second.items_failed >= first.items_done
    assert second.items_failed == 1
    assert second.failure_reason == "one or more items failed"