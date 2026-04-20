"""Scan queue service.

This service owns enqueueing scan jobs and processing queued items. It is used by:
- the HTTP API (`POST /recognition/analyze`) to enqueue work
- the scan worker process to claim and execute work
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from recognition.application.scan.queue_repository import ScanQueueItem, ScanQueueRepository
from recognition.application.settings.scan import ScanSettings
from recognition.config import get_settings


@dataclass(frozen=True, slots=True)
class EnqueueScanResult:
    """Result returned after enqueueing a scan job."""

    job_id: uuid.UUID
    total: int


def _format_queue_message(enqueued: int, total: int) -> str:
    return f"Queueing {enqueued}/{total} items"


def _chunk_items(items: Sequence[tuple[int, str]], chunk_size: int) -> Iterable[Sequence[tuple[int, str]]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    for start in range(0, len(items), chunk_size):
        yield items[start : start + chunk_size]


class ScanQueueService:
    """Coordinates scan queue persistence and processing."""

    def __init__(self, repository: ScanQueueRepository, settings: ScanSettings | None = None) -> None:
        self._repository = repository
        self._settings = settings or get_settings().scan

    async def create_scan_job_record(
        self,
        *,
        tenant_id: uuid.UUID,
        total: int,
        created_by_user_id: int | None = None,
    ) -> uuid.UUID:
        """Create a scan job record without enqueueing items.

        Args:
            tenant_id: Tenant UUID.
            total: Total number of items expected for the job.
            created_by_user_id: Optional WP user id for audit.

        Returns:
            Newly created job UUID.
        """
        if total <= 0:
            raise ValueError("total must be positive")
        message = _format_queue_message(0, total)
        job_id = await self._repository.create_job_with_message(
            tenant_id=tenant_id,
            media_ids=[],
            total=total,
            message=message,
            created_by_user_id=created_by_user_id,
        )
        return job_id

    async def populate_scan_job_items(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        media_items: Sequence[tuple[int, str]],
        chunk_size: int | None = None,
        commit_hook: Callable[[], Awaitable[None]] | None = None,
        correlation_id: str | None = None,
    ) -> int:
        """Populate scan job items in batches.

        Args:
            job_id: Parent scan job id.
            tenant_id: Tenant UUID.
            media_items: Sequence of (media_id, media_url).
            chunk_size: Max items to enqueue per batch.
            commit_hook: Optional async callback to persist each chunk.

        Returns:
            Total number of enqueued items.
        """
        if not media_items:
            return 0
        total = len(media_items)
        enqueued_total = 0
        media_ids: list[int] = []
        chunk_size = chunk_size or self._settings.enqueue_chunk_size
        for chunk in _chunk_items(media_items, chunk_size):
            created = await self._repository.enqueue_items(
                job_id=job_id, tenant_id=tenant_id, items=chunk, correlation_id=correlation_id
            )
            enqueued_total += created
            media_ids.extend(media_id for media_id, _ in chunk)
            await self._repository.update_job_message(
                job_id=job_id,
                message=_format_queue_message(enqueued_total, total),
            )
            if commit_hook:
                await commit_hook()
        await self._repository.finalize_job_queue(
            job_id=job_id,
            media_ids=media_ids,
            message=f"Queued {total} items",
        )
        if commit_hook:
            await commit_hook()
        return enqueued_total

    async def enqueue_scan_job(
        self,
        *,
        tenant_id: uuid.UUID,
        media_items: Sequence[tuple[int, str]],
        created_by_user_id: int | None = None,
    ) -> EnqueueScanResult:
        """Create a scan job and enqueue all items.

        Args:
            tenant_id: Tenant UUID.
            media_items: Sequence of (media_id, media_url).
            created_by_user_id: Optional WP user id for audit.

        Returns:
            EnqueueScanResult containing job id and total count.

        Raises:
            ValueError: When no media items are provided.
        """
        if not media_items:
            raise ValueError("media_items required")
        job_id = await self.create_scan_job_record(
            tenant_id=tenant_id,
            total=len(media_items),
            created_by_user_id=created_by_user_id,
        )
        await self.populate_scan_job_items(job_id=job_id, tenant_id=tenant_id, media_items=media_items)
        return EnqueueScanResult(job_id=job_id, total=len(media_items))

    async def process_next_batch(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        limit: int,
    ) -> list[ScanQueueItem]:
        """Claim and return the next batch of pending items.

        This method only claims work. A worker should process returned items and then
        mark each item completed/failed, updating job progress accordingly.
        """
        now = datetime.now(tz=UTC)
        items = await self._repository.claim_pending_items(tenant_id=tenant_id, job_id=job_id, limit=limit, now=now)
        if items:
            await self._repository.mark_job_running(job_id=job_id, started_at=now)
        return items

    async def refresh_job_progress(self, *, job_id: uuid.UUID) -> bool:
        """Recompute job progress and finalize job status when appropriate.

        Rules:
        - processed_media counts terminal item states: completed/failed/skipped/cancelled
        - identities_detected sums completed item identities_detected
        - when no pending/processing remain:
          - fail if any failed items exist
          - otherwise complete

        Returns:
            True if the job was just completed successfully, False otherwise.
        """
        counts = await self._repository.get_job_item_status_counts(job_id=job_id)
        terminal = ("completed", "failed", "skipped", "cancelled")
        processed_media = sum(counts.get(status, 0) for status in terminal)
        identities_detected = await self._repository.get_job_item_identities_detected(job_id=job_id)
        await self._repository.update_job_progress(
            job_id=job_id,
            processed_media=processed_media,
            identities_detected=identities_detected,
        )

        pending = counts.get("pending", 0)
        processing = counts.get("processing", 0)
        failed = counts.get("failed", 0)

        if pending == 0 and processing == 0 and processed_media > 0:
            now = datetime.now(tz=UTC)
            if failed > 0:
                await self._repository.fail_job(
                    job_id=job_id, completed_at=now, error_message="one or more items failed"
                )
                return False
            else:
                await self._repository.complete_job(job_id=job_id, completed_at=now)
                return True
        return False

    async def cancel_scan_job(self, *, job_id: uuid.UUID) -> int:
        """Cancel any pending items for a scan job.

        Returns:
            Number of items cancelled.
        """
        now = datetime.now(tz=UTC)
        cancelled = await self._repository.cancel_pending_items(job_id=job_id, cancelled_at=now)

        await self.refresh_job_progress(job_id=job_id)

        await self._repository.fail_job(job_id=job_id, completed_at=now, error_message="canceled")
        return cancelled
