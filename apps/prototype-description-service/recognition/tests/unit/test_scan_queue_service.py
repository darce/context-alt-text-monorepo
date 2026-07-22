"""Unit tests for scan queue persistence + progress logic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from db.models import IdentityScanJob, IdentityScanJobItem
from recognition.application.scan.scan_queue_service import JobProgressResult, ScanQueueService
from recognition.domain.job import JobStatus
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
    result = await queue.refresh_job_progress(job_id=job_id)
    assert result.transitioned is False  # Not all items done yet
    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.processed_media == 1
    assert job.identities_detected == 1
    assert job.status in {"pending", "running", "completed"}

    await repo.mark_item_completed(item_id=claimed[1].id, completed_at=datetime.now(tz=UTC), identities_detected=2)
    result = await queue.refresh_job_progress(job_id=job_id)
    assert result.transitioned is True  # All items done, job completed successfully
    assert result.status is JobStatus.COMPLETED
    assert result.triggers_followups is True
    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.processed_media == 2
    assert job.identities_detected == 3
    assert job.status == "completed"
    assert job.completed_at is not None


@pytest.mark.asyncio
async def test_refresh_job_progress_partial_failure_completes_with_errors(db_session, tenant) -> None:
    """E15-27-BR-24/BR-25: a batch with at least one success AND at least one
    failure finalizes completed_with_errors and must still trigger the
    downstream follow-ups (clustering + ObjectStore cleanup)."""
    repo = SqlAlchemyScanQueueRepository(db_session)
    queue = ScanQueueService(repo)

    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1, 2])
    await repo.enqueue_items(
        job_id=job_id,
        tenant_id=tenant.id,
        items=[(1, "http://example.test/1.jpg"), (2, "http://example.test/2.jpg")],
    )
    claimed = await repo.claim_pending_items(tenant_id=tenant.id, job_id=job_id, limit=2, now=datetime.now(tz=UTC))
    await repo.mark_item_completed(item_id=claimed[0].id, completed_at=datetime.now(tz=UTC), identities_detected=2)
    await repo.mark_item_failed(item_id=claimed[1].id, completed_at=datetime.now(tz=UTC), error_message="boom")

    result = await queue.refresh_job_progress(job_id=job_id)
    assert result.transitioned is True
    assert result.status is JobStatus.COMPLETED_WITH_ERRORS
    assert result.triggers_followups is True  # successes present -> cluster + cleanup

    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.status == "completed_with_errors"
    assert job.completed_at is not None
    assert job.error_message == "one or more items failed"


@pytest.mark.asyncio
async def test_refresh_job_progress_all_items_failed_finalizes_failed(db_session, tenant) -> None:
    """E15-27-BR-25: a batch where every processed item failed (zero successes)
    must finalize as terminal FAILED, not completed_with_errors. The latter
    reads as a partial success and lets envelope phase=complete look healthy.
    With no successful item there is also nothing to cluster or clean up."""
    repo = SqlAlchemyScanQueueRepository(db_session)
    queue = ScanQueueService(repo)

    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1, 2])
    await repo.enqueue_items(
        job_id=job_id,
        tenant_id=tenant.id,
        items=[(1, "http://example.test/1.jpg"), (2, "http://example.test/2.jpg")],
    )
    claimed = await repo.claim_pending_items(tenant_id=tenant.id, job_id=job_id, limit=2, now=datetime.now(tz=UTC))
    for item in claimed:
        await repo.mark_item_failed(item_id=item.id, completed_at=datetime.now(tz=UTC), error_message="boom")

    result = await queue.refresh_job_progress(job_id=job_id)
    assert result.transitioned is True
    assert result.status is JobStatus.FAILED
    assert result.triggers_followups is False  # nothing succeeded

    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.status == "failed"
    assert job.completed_at is not None
    assert job.error_message == "no items completed successfully"


@pytest.mark.asyncio
async def test_fail_job_if_active_is_terminal_guarded(db_session, tenant) -> None:
    """The all-items-failed -> FAILED finalize is terminal-guarded just like the
    complete paths (E15-27-RF-A-01): a job already terminal is never
    overwritten, so a stall/completion reason is preserved."""
    repo = SqlAlchemyScanQueueRepository(db_session)

    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1])
    assert await repo.complete_job(job_id=job_id, completed_at=datetime.now(tz=UTC)) is True

    transitioned = await repo.fail_job_if_active(
        job_id=job_id, completed_at=datetime.now(tz=UTC), error_message="all items failed"
    )
    assert transitioned is False
    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.status == "completed"


@pytest.mark.asyncio
async def test_refresh_job_progress_does_not_overwrite_terminal_stalled_job(db_session, tenant) -> None:
    """Regression (E15-27-RF-A-01): once a job is terminal as failed(stalled), a
    late refresh_job_progress — e.g. a concurrent worker replica finishing an
    in-flight item after the stall — must not flip it to completed_with_errors
    and must preserve the stall reason."""
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
    # Started long enough ago to be eligible for stall termination.
    await repo.mark_job_running(job_id=job_id, started_at=datetime.now(tz=UTC) - timedelta(seconds=3600))

    terminated = await queue.terminate_stalled_jobs(stale_after_seconds=600)
    assert terminated == 1
    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.status == "failed"
    assert job.error_message == "stalled"

    # A late refresh after every item has reached a terminal state must not
    # re-finalize the already-terminal job.
    result = await queue.refresh_job_progress(job_id=job_id)
    assert result.transitioned is False
    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.status == "failed"
    assert job.error_message == "stalled"


def _as_utc(dt: datetime) -> datetime:
    """Normalize SQLite naive timestamps for comparison with aware datetimes."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@pytest.mark.asyncio
async def test_release_item_for_retry_applies_attempt_based_not_before(db_session, tenant) -> None:
    """Released items must not be re-claimable until compute_retry_backoff elapses."""
    from recognition.application.scan.retry_backoff import compute_retry_backoff

    repo = SqlAlchemyScanQueueRepository(db_session)
    now = datetime.now(tz=UTC)
    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1])
    await repo.enqueue_items(
        job_id=job_id,
        tenant_id=tenant.id,
        items=[(1, "http://example.test/1.jpg")],
    )
    claimed = await repo.claim_pending_items(tenant_id=tenant.id, job_id=job_id, limit=1, now=now)
    assert len(claimed) == 1
    item = claimed[0]
    assert item.attempts == 1

    await repo.release_item_for_retry(
        item_id=item.id,
        error_message="transient",
        attempts=item.attempts,
        now=now,
    )
    await db_session.flush()

    row = (
        await db_session.execute(select(IdentityScanJobItem).where(IdentityScanJobItem.id == item.id))
    ).scalar_one()
    assert row.status == "pending"
    assert row.last_error == "transient"
    expected_available = now + compute_retry_backoff(item.attempts)
    assert row.started_at is not None
    assert abs((_as_utc(row.started_at) - expected_available).total_seconds()) < 0.001

    # Still inside backoff window — must not claim.
    during_backoff = await repo.claim_pending_items(
        tenant_id=tenant.id, job_id=job_id, limit=1, now=now + timedelta(seconds=0.5)
    )
    assert during_backoff == []

    # After not-before — claimable again.
    after = now + compute_retry_backoff(item.attempts) + timedelta(milliseconds=1)
    reclaimed = await repo.claim_pending_items(tenant_id=tenant.id, job_id=job_id, limit=1, now=after)
    assert len(reclaimed) == 1
    assert reclaimed[0].id == item.id
    assert reclaimed[0].attempts == 2


@pytest.mark.asyncio
async def test_release_item_for_retry_longer_backoff_for_higher_attempts(db_session, tenant) -> None:
    """Higher attempt counts must yield a strictly later not-before than attempt=1."""
    from recognition.application.scan.retry_backoff import compute_retry_backoff

    repo = SqlAlchemyScanQueueRepository(db_session)
    now = datetime.now(tz=UTC)
    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1, 2])
    await repo.enqueue_items(
        job_id=job_id,
        tenant_id=tenant.id,
        items=[
            (1, "http://example.test/1.jpg"),
            (2, "http://example.test/2.jpg"),
        ],
    )
    claimed = await repo.claim_pending_items(tenant_id=tenant.id, job_id=job_id, limit=2, now=now)
    assert len(claimed) == 2
    low, high = claimed[0], claimed[1]

    await repo.release_item_for_retry(
        item_id=low.id, error_message="e1", attempts=1, now=now
    )
    await repo.release_item_for_retry(
        item_id=high.id, error_message="e2", attempts=3, now=now
    )
    await db_session.flush()

    low_row = (
        await db_session.execute(select(IdentityScanJobItem).where(IdentityScanJobItem.id == low.id))
    ).scalar_one()
    high_row = (
        await db_session.execute(select(IdentityScanJobItem).where(IdentityScanJobItem.id == high.id))
    ).scalar_one()
    assert _as_utc(low_row.started_at) == now + compute_retry_backoff(1)
    assert _as_utc(high_row.started_at) == now + compute_retry_backoff(3)
    assert _as_utc(high_row.started_at) > _as_utc(low_row.started_at)

    # Mid window: only the lower-attempt item is claimable.
    mid = now + compute_retry_backoff(1) + timedelta(milliseconds=1)
    mid_claimed = await repo.claim_pending_items(tenant_id=tenant.id, job_id=job_id, limit=2, now=mid)
    assert [c.id for c in mid_claimed] == [low.id]


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
