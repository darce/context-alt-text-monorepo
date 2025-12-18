"""Scan queue service.

This service owns enqueueing scan jobs and processing queued items. It is used by:
- the HTTP API (`POST /recognition/analyze`) to enqueue work
- the scan worker process to claim and execute work
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from recognition.application.scan.queue_repository import ScanQueueItem, ScanQueueRepository


@dataclass(frozen=True, slots=True)
class EnqueueScanResult:
    """Result returned after enqueueing a scan job."""

    job_id: uuid.UUID
    total: int


class ScanQueueService:
    """Coordinates scan queue persistence and processing."""

    def __init__(self, repository: ScanQueueRepository) -> None:
        self._repository = repository

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
        media_ids = [media_id for media_id, _ in media_items]
        job_id = await self._repository.create_job(
            tenant_id=tenant_id,
            media_ids=media_ids,
            created_by_user_id=created_by_user_id,
        )
        await self._repository.enqueue_items(job_id=job_id, tenant_id=tenant_id, items=media_items)
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

    async def refresh_job_progress(self, *, job_id: uuid.UUID) -> None:
        """Recompute job progress and finalize job status when appropriate.

        Rules:
        - processed_media counts terminal item states: completed/failed/skipped/cancelled
        - identities_detected sums completed item identities_detected
        - when no pending/processing remain:
          - fail if any failed items exist
          - otherwise complete
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
            else:
                await self._repository.complete_job(job_id=job_id, completed_at=now)

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
