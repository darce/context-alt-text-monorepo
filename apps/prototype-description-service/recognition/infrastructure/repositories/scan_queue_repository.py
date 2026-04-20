"""SQLAlchemy implementation of the scan queue repository."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityScanJob, IdentityScanJobItem
from recognition.application.scan.queue_repository import ScanQueueItem, ScanQueueRepository
from recognition.shared.db.dialect import is_postgres, timestamp_as_epoch
from recognition.shared.db.helpers import execute_dml, get_rowcount

logger = logging.getLogger(__name__)


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
            status="pending",
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
    ) -> uuid.UUID:
        logger.debug("create_job_with_message: creating job for tenant %s with total %d", tenant_id, total)
        job = IdentityScanJob(
            tenant_id=tenant_id,
            status="pending",
            media_ids=list(media_ids),
            total_media=total,
            processed_media=0,
            identities_detected=0,
            message=message,
            created_by_user_id=created_by_user_id,
        )
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
                status="pending",
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
            .values(status="running", started_at=started_at, error_message=None)
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

    async def complete_job(self, *, job_id: uuid.UUID, completed_at: datetime) -> None:
        await self._session.execute(
            update(IdentityScanJob)
            .where(IdentityScanJob.id == job_id)
            .values(status="completed", completed_at=completed_at)
        )

    async def fail_job(self, *, job_id: uuid.UUID, completed_at: datetime, error_message: str) -> None:
        await self._session.execute(
            update(IdentityScanJob)
            .where(IdentityScanJob.id == job_id)
            .values(status="failed", completed_at=completed_at, error_message=error_message)
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
                IdentityScanJobItem.status == "processing",
                IdentityScanJobItem.started_at.is_not(None),
                timestamp_as_epoch(IdentityScanJobItem.started_at, self._session) < int(stale_before_ts),
                IdentityScanJobItem.attempts < max_attempts,
            )
            .values(status="pending", started_at=None)
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
                IdentityScanJobItem.status == "pending",
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
                status="processing",
                started_at=now,
                attempts=IdentityScanJobItem.attempts + 1,
                last_error=None,
            )
        )
        return [_to_item(row) for row in rows]

    async def _claim_pending_items_any_generic(self, *, limit: int, now: datetime) -> list[ScanQueueItem]:
        stmt: Select[tuple[IdentityScanJobItem]] = (
            select(IdentityScanJobItem)
            .where(IdentityScanJobItem.status == "pending")
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
                status="processing",
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
            .values(status="completed", completed_at=completed_at, identities_detected=identities_detected)
        )

    async def mark_item_failed(self, *, item_id: uuid.UUID, completed_at: datetime, error_message: str) -> None:
        await self._session.execute(
            update(IdentityScanJobItem)
            .where(IdentityScanJobItem.id == item_id)
            .values(status="failed", completed_at=completed_at, last_error=error_message)
        )

    async def release_item_for_retry(self, *, item_id: uuid.UUID, error_message: str) -> None:
        await self._session.execute(
            update(IdentityScanJobItem)
            .where(IdentityScanJobItem.id == item_id)
            .values(status="pending", started_at=None, last_error=error_message)
        )

    async def cancel_pending_items(self, *, job_id: uuid.UUID, cancelled_at: datetime) -> int:
        result = await execute_dml(
            self._session,
            update(IdentityScanJobItem)
            .where(IdentityScanJobItem.job_id == job_id, IdentityScanJobItem.status == "pending")
            .values(status="cancelled", completed_at=cancelled_at),
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
            IdentityScanJobItem.job_id == job_id, IdentityScanJobItem.status == "completed"
        )
        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)

    async def get_job_tenant_id(self, *, job_id: uuid.UUID) -> uuid.UUID | None:
        stmt = select(IdentityScanJob.tenant_id).where(IdentityScanJob.id == job_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


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
