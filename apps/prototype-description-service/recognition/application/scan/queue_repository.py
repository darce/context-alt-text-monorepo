"""Scan queue persistence primitives.

This module defines the repository interface for enqueueing scan jobs and claiming queued work.
It is intentionally small so it can be unit-tested with in-memory fakes and implemented with SQLAlchemy.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ScanQueueItem:
    """A single media scan unit of work."""

    id: uuid.UUID
    job_id: uuid.UUID
    tenant_id: uuid.UUID
    media_id: int
    media_url: str
    status: str
    attempts: int
    identities_detected: int
    last_error: str | None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    correlation_id: str | None = None
    correlation_source: str | None = None


class ScanQueueRepository(Protocol):
    """Repository used by API endpoints and workers to manage scan jobs."""

    async def create_job(
        self,
        *,
        tenant_id: uuid.UUID,
        media_ids: Sequence[int],
        created_by_user_id: int | None = None,
    ) -> uuid.UUID:
        """Create a parent scan job and return its job id."""

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
        """Create a parent scan job with an initial status message."""

    async def enqueue_items(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        items: Iterable[tuple[int, str]],
        correlation_id: str | None = None,
    ) -> int:
        """Enqueue media items for a scan job.

        Args:
            job_id: Parent scan job id.
            tenant_id: Tenant id (RLS scope).
            items: Iterable of (media_id, media_url).
            correlation_id: Optional request-scope correlation id to persist on
                every row. When non-null, ``correlation_source`` is persisted as
                ``CorrelationSource.API``; when null, both columns stay NULL and
                the worker-fallback path owns generation.

        Returns:
            Number of enqueued items.
        """

    async def mark_job_running(self, *, job_id: uuid.UUID, started_at: datetime) -> None:
        """Mark a scan job as running."""

    async def update_job_progress(
        self,
        *,
        job_id: uuid.UUID,
        processed_media: int,
        identities_detected: int,
    ) -> None:
        """Update job-level counters."""

    async def update_job_message(self, *, job_id: uuid.UUID, message: str | None) -> None:
        """Update job-level status message."""

    async def finalize_job_queue(
        self,
        *,
        job_id: uuid.UUID,
        media_ids: Sequence[int],
        message: str | None,
    ) -> None:
        """Persist media_ids and final queue message after enqueueing completes."""

    async def complete_job(self, *, job_id: uuid.UUID, completed_at: datetime) -> bool:
        """Mark a non-terminal scan job as completed.

        Returns True only if this call transitioned the job; a job already in a
        terminal state (e.g. failed/stalled by another worker) is left untouched.
        """

    async def complete_job_with_errors(
        self,
        *,
        job_id: uuid.UUID,
        completed_at: datetime,
        error_message: str,
    ) -> bool:
        """Mark a non-terminal scan job as completed-with-errors.

        Returns True only if this call transitioned the job; an already-terminal
        job is left untouched so a stall/failure reason is never overwritten.
        """

    async def fail_job(self, *, job_id: uuid.UUID, completed_at: datetime, error_message: str) -> None:
        """Mark a scan job as failed (unconditional; used by explicit cancel)."""

    async def fail_job_if_active(self, *, job_id: uuid.UUID, completed_at: datetime, error_message: str) -> bool:
        """Mark a non-terminal scan job as failed.

        Returns True only if this call transitioned the job; an already-terminal
        job is left untouched so a prior stall/completion reason is never
        overwritten. Used by the all-items-failed finalize path.
        """

    async def claim_pending_items(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        limit: int,
        now: datetime,
    ) -> list[ScanQueueItem]:
        """Atomically claim up to `limit` pending items.

        Implementations should prefer `FOR UPDATE SKIP LOCKED` on PostgreSQL.
        """

    async def claim_pending_items_any(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> list[ScanQueueItem]:
        """Atomically claim up to `limit` pending items across all jobs."""

    async def reclaim_stale_items(
        self,
        *,
        stale_after_seconds: int,
        max_attempts: int,
        now: datetime,
    ) -> int:
        """Reclaim stale processing items and return how many were updated."""

    async def mark_item_completed(
        self,
        *,
        item_id: uuid.UUID,
        completed_at: datetime,
        identities_detected: int,
    ) -> None:
        """Mark a queue item as completed."""

    async def mark_item_failed(
        self,
        *,
        item_id: uuid.UUID,
        completed_at: datetime,
        error_message: str,
    ) -> None:
        """Mark a queue item as failed and record its error."""

    async def release_item_for_retry(
        self,
        *,
        item_id: uuid.UUID,
        error_message: str,
        attempts: int,
        now: datetime | None = None,
    ) -> None:
        """Return an item to pending with attempt-based not-before backoff.

        ``attempts`` is the post-claim attempt count. Implementations must delay
        re-claim until ``now + compute_retry_backoff(attempts)`` (typically by
        storing that instant in ``started_at`` while status is pending).
        """

    async def cancel_pending_items(self, *, job_id: uuid.UUID, cancelled_at: datetime) -> int:
        """Cancel all pending items for a job and return how many were canceled."""

    async def get_job_item_status_counts(self, *, job_id: uuid.UUID) -> dict[str, int]:
        """Return counts of items by status for a job."""

    async def get_job_item_identities_detected(self, *, job_id: uuid.UUID) -> int:
        """Return total identities_detected sum for completed items in a job."""

    async def get_job_tenant_id(self, *, job_id: uuid.UUID) -> uuid.UUID | None:
        """Return the tenant_id for a scan job, or None if not found."""

    async def fail_stalled_running_jobs(
        self,
        *,
        stale_after_seconds: int,
        now: datetime,
    ) -> int:
        """Fail running jobs with incomplete work older than the stall threshold."""
