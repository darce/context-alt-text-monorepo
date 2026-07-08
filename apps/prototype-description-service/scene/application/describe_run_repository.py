"""Tenant-scoped persistence for async scene describe runs."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.scene import DescribeRun, DescribeRunItem
from scene.domain.describe_run import (
    TERMINAL_ITEM_STATUSES,
    DescribeItemStatus,
    DescribeRunPhase,
    DescribeRunRequest,
    DescribeRunStatus,
    describe_run_max_items,
    phase_for_status,
)


class DescribeRunRepository:
    def __init__(self, session: AsyncSession, *, max_items: int | None = None) -> None:
        self._session = session
        self._max_items = max_items or describe_run_max_items()

    async def create_run(
        self,
        *,
        tenant_id: uuid.UUID,
        media_ids: Sequence[int],
        created_by_user_id: int | None = None,
        images: Mapping[int, tuple[bytes, str | None]] | None = None,
    ) -> uuid.UUID:
        request = DescribeRunRequest(tenant_id=tenant_id, media_ids=media_ids, max_items=self._max_items)
        request.validate()
        images = images or {}
        run = DescribeRun(
            tenant_id=tenant_id,
            status=DescribeRunStatus.PENDING,
            phase=DescribeRunPhase.QUEUED,
            media_ids=list(media_ids),
            total_items=len(media_ids),
            completed_items=0,
            failed_items=0,
            skipped_items=0,
            created_by_user_id=created_by_user_id,
        )
        run.items = [
            DescribeRunItem(
                tenant_id=tenant_id,
                media_id=media_id,
                status=DescribeItemStatus.QUEUED,
                attempts=0,
                image_bytes=images.get(media_id, (None, None))[0],
                image_content_type=images.get(media_id, (None, None))[1],
            )
            for media_id in media_ids
        ]
        self._session.add(run)
        await self._session.flush()
        return run.id

    async def record_item_result(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        media_id: int,
        alt_text_draft: str | None,
        caption: str | None,
        provenance: dict | None,
    ) -> bool:
        """Persist the describe output for one item and clear its image bytes."""
        item = await self._get_item(tenant_id=tenant_id, run_id=run_id, media_id=media_id)
        if item is None:
            return False
        item.alt_text_draft = alt_text_draft
        item.caption = caption
        item.provenance = provenance
        item.image_bytes = None
        await self._session.flush()
        return True

    async def mark_run_failed(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        error_message: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Force a run terminal-FAILED on an unexpected fatal worker error."""
        run = await self.get_run(tenant_id=tenant_id, run_id=run_id)
        if run is None:
            return False
        run.status = DescribeRunStatus.FAILED
        run.phase = DescribeRunPhase.FAILED
        run.completed_at = now or datetime.now(tz=UTC)
        if error_message:
            run.error_message = error_message
        await self._session.flush()
        return True

    async def get_run(self, *, tenant_id: uuid.UUID, run_id: uuid.UUID) -> DescribeRun | None:
        result = await self._session.execute(
            select(DescribeRun).where(DescribeRun.tenant_id == tenant_id, DescribeRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_run_items(self, *, tenant_id: uuid.UUID, run_id: uuid.UUID) -> list[DescribeRunItem]:
        result = await self._session.execute(
            select(DescribeRunItem)
            .where(DescribeRunItem.tenant_id == tenant_id, DescribeRunItem.run_id == run_id)
            .order_by(DescribeRunItem.media_id.asc())
        )
        return list(result.scalars().all())

    async def request_cancel(self, *, tenant_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        run = await self.get_run(tenant_id=tenant_id, run_id=run_id)
        if run is None:
            return False
        run.cancel_requested = True
        if run.status == DescribeRunStatus.PENDING:
            run.status = DescribeRunStatus.CANCELLED
            run.phase = DescribeRunPhase.CANCELLED
            run.completed_at = datetime.now(tz=UTC)
        await self._session.flush()
        return True

    async def mark_item(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        media_id: int,
        status: DescribeItemStatus,
        error_message: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        now = now or datetime.now(tz=UTC)
        item = await self._get_item(tenant_id=tenant_id, run_id=run_id, media_id=media_id)
        if item is None:
            return False
        current = DescribeItemStatus(item.status)
        if current in TERMINAL_ITEM_STATUSES:
            await self._recompute_run_totals(tenant_id=tenant_id, run_id=run_id, now=now)
            return current == status

        if status == DescribeItemStatus.RUNNING:
            item.status = status
            item.started_at = now
            item.attempts += 1
        elif status in TERMINAL_ITEM_STATUSES:
            item.status = status
            item.completed_at = now
            if error_message:
                item.last_error = error_message
        else:
            item.status = status

        await self._recompute_run_totals(tenant_id=tenant_id, run_id=run_id, now=now)
        await self._session.flush()
        return True

    async def reclaim_interrupted_runs(self, *, tenant_id: uuid.UUID, cutoff: datetime) -> int:
        result = await self._session.execute(
            update(DescribeRunItem)
            .where(
                DescribeRunItem.tenant_id == tenant_id,
                DescribeRunItem.status == DescribeItemStatus.RUNNING,
                DescribeRunItem.started_at.is_not(None),
                DescribeRunItem.started_at < cutoff,
            )
            .values(status=DescribeItemStatus.QUEUED, started_at=None)
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def _get_item(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        media_id: int,
    ) -> DescribeRunItem | None:
        result = await self._session.execute(
            select(DescribeRunItem).where(
                DescribeRunItem.tenant_id == tenant_id,
                DescribeRunItem.run_id == run_id,
                DescribeRunItem.media_id == media_id,
            )
        )
        return result.scalar_one_or_none()

    async def _recompute_run_totals(self, *, tenant_id: uuid.UUID, run_id: uuid.UUID, now: datetime) -> None:
        run = await self.get_run(tenant_id=tenant_id, run_id=run_id)
        if run is None:
            return

        statuses = Counter(item.status for item in await self.list_run_items(tenant_id=tenant_id, run_id=run_id))
        completed = statuses[DescribeItemStatus.COMPLETED]
        failed = statuses[DescribeItemStatus.FAILED]
        skipped = statuses[DescribeItemStatus.SKIPPED]
        terminal = completed + failed + skipped
        running = statuses[DescribeItemStatus.RUNNING]

        run.completed_items = completed
        run.failed_items = failed
        run.skipped_items = skipped
        if running and run.started_at is None:
            run.started_at = now

        if terminal >= run.total_items:
            if run.cancel_requested:
                # A cancel that lands mid-run ends CANCELLED even if some items
                # completed before the cancel took effect. (S1-01)
                status = DescribeRunStatus.CANCELLED
            elif skipped and not failed and completed == 0:
                status = DescribeRunStatus.CANCELLED
            elif failed:
                status = DescribeRunStatus.COMPLETED_WITH_ERRORS
            else:
                status = DescribeRunStatus.COMPLETED
            run.status = status
            run.phase = phase_for_status(status)
            run.completed_at = now
        elif running:
            run.status = DescribeRunStatus.RUNNING
            run.phase = DescribeRunPhase.DESCRIBING
        else:
            run.status = DescribeRunStatus.PENDING
            run.phase = DescribeRunPhase.QUEUED
