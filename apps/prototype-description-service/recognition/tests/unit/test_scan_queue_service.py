"""Unit tests for scan queue persistence + progress logic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from db.models import IdentityScanJob, IdentityScanJobItem
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository


@pytest.mark.asyncio
async def test_refresh_job_progress_completes_when_all_items_done(db_session, tenant) -> None:
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

    claimed = await repo.claim_pending_items(tenant_id=tenant.id, job_id=job_id, limit=2, now=datetime.now(tz=UTC))
    assert len(claimed) == 2
    await repo.mark_job_running(job_id=job_id, started_at=datetime.now(tz=UTC))

    await repo.mark_item_completed(item_id=claimed[0].id, completed_at=datetime.now(tz=UTC), identities_detected=1)
    completed = await queue.refresh_job_progress(job_id=job_id)
    assert completed is False  # Not all items done yet
    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.processed_media == 1
    assert job.identities_detected == 1
    assert job.status in {"pending", "running", "completed"}

    await repo.mark_item_completed(item_id=claimed[1].id, completed_at=datetime.now(tz=UTC), identities_detected=2)
    completed = await queue.refresh_job_progress(job_id=job_id)
    assert completed is True  # All items done, job completed successfully
    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.processed_media == 2
    assert job.identities_detected == 3
    assert job.status == "completed"
    assert job.completed_at is not None


@pytest.mark.asyncio
async def test_refresh_job_progress_fails_when_any_item_failed(db_session, tenant) -> None:
    repo = SqlAlchemyScanQueueRepository(db_session)
    queue = ScanQueueService(repo)

    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1])
    await repo.enqueue_items(job_id=job_id, tenant_id=tenant.id, items=[(1, "http://example.test/1.jpg")])

    claimed = await repo.claim_pending_items(tenant_id=tenant.id, job_id=job_id, limit=1, now=datetime.now(tz=UTC))
    assert len(claimed) == 1
    await repo.mark_item_failed(item_id=claimed[0].id, completed_at=datetime.now(tz=UTC), error_message="boom")
    completed = await queue.refresh_job_progress(job_id=job_id)
    assert completed is False  # Job failed, not successfully completed

    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.status == "completed_with_errors"
    assert job.completed_at is not None
    assert job.error_message == "one or more items failed"


@pytest.mark.asyncio
async def test_reclaim_stale_items_resets_processing_to_pending(db_session, tenant) -> None:
    repo = SqlAlchemyScanQueueRepository(db_session)
    now = datetime.now(tz=UTC)
    stale_started_at = now - timedelta(minutes=20)

    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1])
    item_id = uuid.uuid4()
    db_session.add(
        IdentityScanJobItem(
            id=item_id,
            job_id=job_id,
            tenant_id=tenant.id,
            media_id=1,
            media_url="http://example.test/1.jpg",
            status="processing",
            attempts=1,
            identities_detected=0,
            started_at=stale_started_at,
            created_at=stale_started_at,
        )
    )
    await db_session.flush()

    reclaimed = await repo.reclaim_stale_items(stale_after_seconds=600, max_attempts=3, now=now)
    assert reclaimed == 1

    item = (await db_session.execute(select(IdentityScanJobItem).where(IdentityScanJobItem.id == item_id))).scalar_one()
    assert item.status == "pending"
    assert item.started_at is None


@pytest.mark.asyncio
async def test_cancel_scan_job_cancels_pending_items_and_fails_job(db_session, tenant) -> None:
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

    cancelled = await queue.cancel_scan_job(job_id=job_id)
    assert cancelled == 2

    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.status == "failed"
    assert job.error_message == "canceled"
    assert job.processed_media == 2

    statuses = (
        (
            await db_session.execute(
                select(IdentityScanJobItem.status)
                .where(IdentityScanJobItem.job_id == job_id)
                .order_by(IdentityScanJobItem.media_id)
            )
        )
        .scalars()
        .all()
    )
    assert statuses == ["cancelled", "cancelled"]


@pytest.mark.asyncio
async def test_reclaim_stale_items_skips_exhausted_attempts(db_session, tenant) -> None:
    repo = SqlAlchemyScanQueueRepository(db_session)
    now = datetime.now(tz=UTC)
    stale_started_at = now - timedelta(minutes=20)

    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1])
    item_id = uuid.uuid4()
    db_session.add(
        IdentityScanJobItem(
            id=item_id,
            job_id=job_id,
            tenant_id=tenant.id,
            media_id=1,
            media_url="http://example.test/1.jpg",
            status="processing",
            attempts=3,
            identities_detected=0,
            started_at=stale_started_at,
            created_at=stale_started_at,
        )
    )
    await db_session.flush()

    reclaimed = await repo.reclaim_stale_items(stale_after_seconds=600, max_attempts=3, now=now)
    assert reclaimed == 0


@pytest.mark.asyncio
async def test_create_scan_job_record_sets_message(db_session, tenant) -> None:
    repo = SqlAlchemyScanQueueRepository(db_session)
    queue = ScanQueueService(repo)

    job_id = await queue.create_scan_job_record(tenant_id=tenant.id, total=3)

    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.total_media == 3
    assert job.message == "Queueing 0/3 items"


@pytest.mark.asyncio
async def test_populate_scan_job_items_updates_message(db_session, tenant) -> None:
    repo = SqlAlchemyScanQueueRepository(db_session)
    queue = ScanQueueService(repo)

    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1, 2, 3])
    enqueued = await queue.populate_scan_job_items(
        job_id=job_id,
        tenant_id=tenant.id,
        media_items=[
            (1, "http://example.test/1.jpg"),
            (2, "http://example.test/2.jpg"),
            (3, "http://example.test/3.jpg"),
        ],
        chunk_size=2,
    )

    assert enqueued == 3
    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.message == "Queued 3 items"
    items = (
        (await db_session.execute(select(IdentityScanJobItem).where(IdentityScanJobItem.job_id == job_id)))
        .scalars()
        .all()
    )
    assert len(items) == 3
