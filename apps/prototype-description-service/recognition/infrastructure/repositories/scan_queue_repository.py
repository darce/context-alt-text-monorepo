"""SQLAlchemy implementation of the scan queue repository."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, exists, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityScanJob, IdentityScanJobItem
from recognition.application.scan.queue_repository import ScanQueueItem, ScanQueueRepository
from recognition.domain.job import TERMINAL_JOB_STATUSES, JobStatus, ScanItemStatus
from recognition.shared.db.dialect import is_postgres, timestamp_as_epoch
from recognition.shared.db.helpers import execute_dml, get_rowcount

logger = logging.getLogger(__name__)

# Stored job.status values that are terminal; finalizers must never overwrite them.
_TERMINAL_JOB_STATUS_VALUES = tuple(status.value for status in TERMINAL_JOB_STATUSES)


class SqlAlchemyScanQueueRepository(ScanQueueRepository):
    """Persist scan jobs and scan queue items using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_job(
        self,
        *,
        tenant_id: uuid.UUID,
        media_ids: Sequence[int],
        created_by_user_id: int | None = None,
    ) -> uuid.UUID:
        logger.debug("create_job: creating job for tenant %s with %d media items", tenant_id, len(media_ids))
        job = IdentityScanJob(
            tenant_id=tenant_id,
            status=JobStatus.PENDING,
            media_ids=list(media_ids),
            total_media=len(media_ids),
            processed_media=0,
            identities_detected=0,
            created_by_user_id=created_by_user_id,
        )
        self._session.add(job)
        await self._session.flush()
        logger.debug("create_job: created job id=%s", job.id)
        return job.id

    async def create_job_with_message(
        self,
        *,
        tenant_id: uuid.UUID,
        media_ids: Sequence[int],
        total: int,
        message: str | None,
        created_by_user_id: int | None = None,
        job_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        logger.debug("create_job_with_message: creating job for tenant %s with total %d", tenant_id, total)
        job_kwargs: dict = {
            "tenant_id": tenant_id,
            "status": JobStatus.PENDING,
            "media_ids": list(media_ids),
            "total_media": total,
            "processed_media": 0,
            "identities_detected": 0,
            "message": message,
            "created_by_user_id": created_by_user_id,
        }
        if job_id is not None:
            # E15-11: the multipart route pre-generates the UUID so it can
            # write blobs under <tenant>/<job_id>/<media_id>.bin BEFORE the
            # scan job record exists. Persist the caller-supplied UUID so
            # the on-disk path matches the DB row.
            job_kwargs["id"] = job_id
        job = IdentityScanJob(**job_kwargs)
        self._session.add(job)
        await self._session.flush()
        logger.debug("create_job_with_message: created job id=%s", job.id)
        return job.id

    async def enqueue_items(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        items: Iterable[tuple[int, str]],
        correlation_id: str | None = None,
    ) -> int:
        from recognition.interface_adapters.http.middleware.correlation import CorrelationSource

        now = datetime.now(tz=UTC)
        correlation_source = CorrelationSource.API.value if correlation_id else None
        created = [
            IdentityScanJobItem(
                id=uuid.uuid4(),
                job_id=job_id,
                tenant_id=tenant_id,
                media_id=media_id,
                media_url=media_url,
                status=JobStatus.PENDING,
                attempts=0,
                identities_detected=0,
                created_at=now,
                correlation_id=correlation_id,
                correlation_source=correlation_source,
            )
            for media_id, media_url in items
        ]
        if not created:
            return 0
        self._session.add_all(created)
        await self._session.flush()
        return len(created)

    async def mark_job_running(self, *, job_id: uuid.UUID, started_at: datetime) -> None:
        await self._session.execute(
            update(IdentityScanJob)
            .where(IdentityScanJob.id == job_id)
            .values(status=JobStatus.RUNNING, started_at=started_at, error_message=None)
        )

    async def update_job_progress(
        self,
        *,
        job_id: uuid.UUID,
        processed_media: int,
        identities_detected: int,
    ) -> None:
        await self._session.execute(
            update(IdentityScanJob)
            .where(IdentityScanJob.id == job_id)
            .values(processed_media=processed_media, identities_detected=identities_detected)
        )

    async def update_job_message(self, *, job_id: uuid.UUID, message: str | None) -> None:
        """Update a scan job's status message."""
        await self._session.execute(update(IdentityScanJob).where(IdentityScanJob.id == job_id).values(message=message))

    async def finalize_job_queue(
        self,
        *,
        job_id: uuid.UUID,
        media_ids: Sequence[int],
        message: str | None,
    ) -> None:
        """Persist media_ids and final queue message after enqueueing completes."""
        await self._session.execute(
            update(IdentityScanJob)
            .where(IdentityScanJob.id == job_id)
            .values(media_ids=list(media_ids), message=message)
        )

    async def complete_job(self, *, job_id: uuid.UUID, completed_at: datetime) -> bool:
        result = await execute_dml(
            self._session,
            update(IdentityScanJob)
            .where(
                IdentityScanJob.id == job_id,
                IdentityScanJob.status.not_in(_TERMINAL_JOB_STATUS_VALUES),
            )
            .values(status=JobStatus.COMPLETED, completed_at=completed_at),
        )
        return get_rowcount(result) > 0

    async def complete_job_with_errors(
        self,
        *,
        job_id: uuid.UUID,
        completed_at: datetime,
        error_message: str,
    ) -> bool:
        result = await execute_dml(
            self._session,
            update(IdentityScanJob)
            .where(
                IdentityScanJob.id == job_id,
                IdentityScanJob.status.not_in(_TERMINAL_JOB_STATUS_VALUES),
            )
            .values(
                status=JobStatus.COMPLETED_WITH_ERRORS,
                completed_at=completed_at,
                error_message=error_message,
            ),
        )
        return get_rowcount(result) > 0

    async def fail_job(self, *, job_id: uuid.UUID, completed_at: datetime, error_message: str) -> None:
        await self._session.execute(
            update(IdentityScanJob)
            .where(IdentityScanJob.id == job_id)
            .values(status=JobStatus.FAILED, completed_at=completed_at, error_message=error_message)
        )

    async def claim_pending_items(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        limit: int,
        now: datetime,
    ) -> list[ScanQueueItem]:
        if limit <= 0:
            return []

        if is_postgres(self._session):
            return await self._claim_pending_items_postgres(tenant_id=tenant_id, job_id=job_id, limit=limit, now=now)
        return await self._claim_pending_items_generic(tenant_id=tenant_id, job_id=job_id, limit=limit, now=now)

    async def claim_pending_items_any(self, *, limit: int, now: datetime) -> list[ScanQueueItem]:
        if limit <= 0:
            return []
        if is_postgres(self._session):
            return await self._claim_pending_items_any_postgres(limit=limit, now=now)
        return await self._claim_pending_items_any_generic(limit=limit, now=now)

    async def reclaim_stale_items(
        self,
        *,
        stale_after_seconds: int,
        max_attempts: int,
        now: datetime,
    ) -> int:
        if stale_after_seconds <= 0:
            return 0

        if is_postgres(self._session):
            stale_before = now - timedelta(seconds=stale_after_seconds)
            reclaim_sql = text(
                """
                UPDATE identity_scan_job_items
                SET status = 'pending',
                    started_at = NULL
                WHERE status = 'processing'
                  AND started_at IS NOT NULL
                  AND started_at < :stale_before
                  AND attempts < :max_attempts
                """
            )
            result = await execute_dml(
                self._session,
                reclaim_sql,
                {"stale_before": stale_before, "max_attempts": max_attempts},
            )
            return get_rowcount(result)

        stale_before_ts = now.timestamp() - stale_after_seconds
        reclaim_stmt = (
            update(IdentityScanJobItem)
            .where(
                IdentityScanJobItem.status == ScanItemStatus.PROCESSING.value,
                IdentityScanJobItem.started_at.is_not(None),
                timestamp_as_epoch(IdentityScanJobItem.started_at, self._session) < int(stale_before_ts),
                IdentityScanJobItem.attempts < max_attempts,
            )
            .values(status=JobStatus.PENDING, started_at=None)
        )
        result = await execute_dml(self._session, reclaim_stmt)
        return get_rowcount(result)

    async def _claim_pending_items_generic(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        limit: int,
        now: datetime,
    ) -> list[ScanQueueItem]:
        stmt: Select[tuple[IdentityScanJobItem]] = (
            select(IdentityScanJobItem)
            .where(
                IdentityScanJobItem.tenant_id == tenant_id,
                IdentityScanJobItem.job_id == job_id,
                IdentityScanJobItem.status == JobStatus.PENDING.value,
            )
            .order_by(IdentityScanJobItem.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        if not rows:
            return []
        ids = [row.id for row in rows]
        await self._session.execute(
            update(IdentityScanJobItem)
            .where(IdentityScanJobItem.id.in_(ids))
            .values(
                status=ScanItemStatus.PROCESSING.value,
                started_at=now,
                attempts=IdentityScanJobItem.attempts + 1,
                last_error=None,
            )
        )
        return [_to_item(row) for row in rows]

    async def _claim_pending_items_any_generic(self, *, limit: int, now: datetime) -> list[ScanQueueItem]:
        stmt: Select[tuple[IdentityScanJobItem]] = (
            select(IdentityScanJobItem)
            .where(IdentityScanJobItem.status == JobStatus.PENDING.value)
            .order_by(IdentityScanJobItem.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        if not rows:
            return []
        ids = [row.id for row in rows]
        await self._session.execute(
            update(IdentityScanJobItem)
            .where(IdentityScanJobItem.id.in_(ids))
            .values(
                status=ScanItemStatus.PROCESSING.value,
                started_at=now,
                attempts=IdentityScanJobItem.attempts + 1,
                last_error=None,
            )
        )
        return [_to_item(row) for row in rows]

    async def _claim_pending_items_postgres(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        limit: int,
        now: datetime,
    ) -> list[ScanQueueItem]:
        # CTE claim pattern: select ids FOR UPDATE SKIP LOCKED then update returning.
        claim_sql = text(
            """
            WITH claimed AS (
              SELECT id
              FROM identity_scan_job_items
              WHERE tenant_id = :tenant_id
                AND job_id = :job_id
                AND status = 'pending'
              ORDER BY created_at ASC
              FOR UPDATE SKIP LOCKED
              LIMIT :limit
            )
            UPDATE identity_scan_job_items
            SET status = 'processing',
                started_at = :now,
                attempts = attempts + 1,
                last_error = NULL
            WHERE id IN (SELECT id FROM claimed)
            RETURNING id, job_id, tenant_id, media_id, media_url, status, attempts, identities_detected, last_error, created_at, started_at, completed_at, correlation_id, correlation_source
            """
        )
        result = await self._session.execute(
            claim_sql,
            {"tenant_id": tenant_id, "job_id": job_id, "limit": limit, "now": now},
        )
        rows = result.mappings().all()
        return [
            ScanQueueItem(
                id=row["id"],
                job_id=row["job_id"],
                tenant_id=row["tenant_id"],
                media_id=row["media_id"],
                media_url=row["media_url"],
                status=row["status"],
                attempts=row["attempts"],
                identities_detected=row.get("identities_detected", 0) or 0,
                last_error=row["last_error"],
                created_at=row["created_at"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                correlation_id=row.get("correlation_id"),
                correlation_source=row.get("correlation_source"),
            )
            for row in rows
        ]

    async def _claim_pending_items_any_postgres(self, *, limit: int, now: datetime) -> list[ScanQueueItem]:
        claim_sql = text(
            """
            WITH claimed AS (
              SELECT id
              FROM identity_scan_job_items
              WHERE status = 'pending'
              ORDER BY created_at ASC
              FOR UPDATE SKIP LOCKED
              LIMIT :limit
            )
            UPDATE identity_scan_job_items
            SET status = 'processing',
                started_at = :now,
                attempts = attempts + 1,
                last_error = NULL
            WHERE id IN (SELECT id FROM claimed)
            RETURNING id, job_id, tenant_id, media_id, media_url, status, attempts, identities_detected, last_error, created_at, started_at, completed_at, correlation_id, correlation_source
            """
        )
        result = await self._session.execute(claim_sql, {"limit": limit, "now": now})
        rows = result.mappings().all()
        return [
            ScanQueueItem(
                id=row["id"],
                job_id=row["job_id"],
                tenant_id=row["tenant_id"],
                media_id=row["media_id"],
                media_url=row["media_url"],
                status=row["status"],
                attempts=row["attempts"],
                identities_detected=row.get("identities_detected", 0) or 0,
                last_error=row["last_error"],
                created_at=row["created_at"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                correlation_id=row.get("correlation_id"),
                correlation_source=row.get("correlation_source"),
            )
            for row in rows
        ]

    async def mark_item_completed(
        self, *, item_id: uuid.UUID, completed_at: datetime, identities_detected: int
    ) -> None:
        await self._session.execute(
            update(IdentityScanJobItem)
            .where(IdentityScanJobItem.id == item_id)
            .values(status=JobStatus.COMPLETED, completed_at=completed_at, identities_detected=identities_detected)
        )

    async def mark_item_failed(self, *, item_id: uuid.UUID, completed_at: datetime, error_message: str) -> None:
        await self._session.execute(
            update(IdentityScanJobItem)
            .where(IdentityScanJobItem.id == item_id)
            .values(status=JobStatus.FAILED, completed_at=completed_at, last_error=error_message)
        )

    async def release_item_for_retry(self, *, item_id: uuid.UUID, error_message: str) -> None:
        await self._session.execute(
            update(IdentityScanJobItem)
            .where(IdentityScanJobItem.id == item_id)
            .values(status=JobStatus.PENDING, started_at=None, last_error=error_message)
        )

    async def cancel_pending_items(self, *, job_id: uuid.UUID, cancelled_at: datetime) -> int:
        result = await execute_dml(
            self._session,
            update(IdentityScanJobItem)
            .where(IdentityScanJobItem.job_id == job_id, IdentityScanJobItem.status == JobStatus.PENDING.value)
            .values(status=ScanItemStatus.CANCELLED.value, completed_at=cancelled_at),
        )
        return get_rowcount(result)

    async def get_job_item_status_counts(self, *, job_id: uuid.UUID) -> dict[str, int]:
        stmt = (
            select(IdentityScanJobItem.status, func.count(IdentityScanJobItem.id))
            .where(IdentityScanJobItem.job_id == job_id)
            .group_by(IdentityScanJobItem.status)
        )
        result = await self._session.execute(stmt)
        rows = result.all()
        return {status: int(count) for status, count in rows}

    async def get_job_item_identities_detected(self, *, job_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.sum(IdentityScanJobItem.identities_detected), 0)).where(
            IdentityScanJobItem.job_id == job_id, IdentityScanJobItem.status == JobStatus.COMPLETED.value
        )
        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)

    async def get_job_tenant_id(self, *, job_id: uuid.UUID) -> uuid.UUID | None:
        stmt = select(IdentityScanJob.tenant_id).where(IdentityScanJob.id == job_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def fail_stalled_running_jobs(
        self,
        *,
        stale_after_seconds: int,
        now: datetime,
    ) -> int:
        if stale_after_seconds <= 0:
            return 0

        stale_before = now - timedelta(seconds=stale_after_seconds)
        incomplete_items = exists(
            select(IdentityScanJobItem.id).where(
                IdentityScanJobItem.job_id == IdentityScanJob.id,
                IdentityScanJobItem.status.in_(
                    (
                        ScanItemStatus.PENDING.value,
                        ScanItemStatus.PROCESSING.value,
                    )
                ),
            )
        )
        stmt = select(IdentityScanJob.id).where(
            IdentityScanJob.status == JobStatus.RUNNING.value,
            IdentityScanJob.started_at.is_not(None),
            IdentityScanJob.started_at < stale_before,
            incomplete_items,
        )
        result = await self._session.execute(stmt)
        stalled_job_ids = list(result.scalars().all())
        if not stalled_job_ids:
            return 0

        for job_id in stalled_job_ids:
            await self.fail_job(job_id=job_id, completed_at=now, error_message="stalled")
            await execute_dml(
                self._session,
                update(IdentityScanJobItem)
                .where(
                    IdentityScanJobItem.job_id == job_id,
                    IdentityScanJobItem.status == ScanItemStatus.PENDING.value,
                )
                .values(status=ScanItemStatus.CANCELLED.value, completed_at=now),
            )
            await execute_dml(
                self._session,
                update(IdentityScanJobItem)
                .where(
                    IdentityScanJobItem.job_id == job_id,
                    IdentityScanJobItem.status == ScanItemStatus.PROCESSING.value,
                )
                .values(status=ScanItemStatus.FAILED.value, completed_at=now, last_error="stalled"),
            )
        return len(stalled_job_ids)


def _to_item(row: IdentityScanJobItem) -> ScanQueueItem:
    return ScanQueueItem(
        id=row.id,
        job_id=row.job_id,
        tenant_id=row.tenant_id,
        media_id=row.media_id,
        media_url=row.media_url,
        status=row.status,
        attempts=row.attempts,
        identities_detected=row.identities_detected,
        last_error=row.last_error,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        correlation_id=row.correlation_id,
        correlation_source=row.correlation_source,
    )


__all__ = ["SqlAlchemyScanQueueRepository"]
