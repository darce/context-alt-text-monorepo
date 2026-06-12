"""E15-27 Slice 3: bounded stall terminality for scan jobs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from db.models import IdentityScanJob
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.domain.job import JobStatus
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository


@pytest.mark.asyncio
async def test_terminate_stalled_jobs_fails_running_job_with_no_progress(db_session, tenant) -> None:
    repo = SqlAlchemyScanQueueRepository(db_session)
    queue = ScanQueueService(repo)

    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1, 2])
    await repo.enqueue_items(
        job_id=job_id,
        tenant_id=tenant.id,
        items=[
            (1, "http://example.test/1.jpg"),
            (2, "http://example.test/2.jpg"),
        ],
    )
    stale_started_at = datetime.now(tz=UTC) - timedelta(seconds=900)
    await repo.mark_job_running(job_id=job_id, started_at=stale_started_at)

    terminated = await queue.terminate_stalled_jobs(
        stale_after_seconds=600,
        now=datetime.now(tz=UTC),
    )

    assert terminated == 1
    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.status == JobStatus.FAILED.value
    assert job.error_message == "stalled"