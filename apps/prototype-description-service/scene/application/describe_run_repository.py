"""Tenant-scoped persistence for async scene describe runs."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.scene import DescribeRun, DescribeRunItem
from recognition.shared.db.dialect import is_sqlite
from scene.domain.describe_run import (
    TERMINAL_ITEM_STATUSES,
    TERMINAL_RUN_STATUSES,
    DescribeItemStatus,
    DescribeRunPhase,
    DescribeRunRequest,
    DescribeRunStatus,
    RunKind,
    async_job_retention_hours,
    describe_run_max_items,
    phase_for_status,
    terminal_run_status,
)
from scene.domain.description import DescriptionResultTier

_TRUTHY_PG_SETTINGS = {"true", "on", "1", "yes"}
_RECLAIM_INTERRUPT_ERROR = "interrupted by service restart"


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
        # PHP-04: dedup while preserving first-seen order so a caller cannot
        # trigger redundant VLM inference by repeating a media_id.
        media_ids = list(dict.fromkeys(media_ids))
        request = DescribeRunRequest(tenant_id=tenant_id, media_ids=media_ids, max_items=self._max_items)
        request.validate()
        images = images or {}
        run = DescribeRun(
            tenant_id=tenant_id,
            run_kind=RunKind.BULK,
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

    async def create_single_run(
        self,
        *,
        tenant_id: uuid.UUID,
        media_id: int,
        image_bytes: bytes,
        image_content_type: str | None = None,
        created_by_user_id: int | None = None,
    ) -> uuid.UUID:
        """Create a one-item ``run_kind=single`` job for the async supersede path (VLM-5)."""
        run = DescribeRun(
            tenant_id=tenant_id,
            run_kind=RunKind.SINGLE,
            status=DescribeRunStatus.PENDING,
            phase=DescribeRunPhase.QUEUED,
            media_ids=[media_id],
            total_items=1,
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
                image_bytes=image_bytes,
                image_content_type=image_content_type,
                result_generation=0,
            )
        ]
        self._session.add(run)
        await self._session.flush()
        return run.id

    async def get_single_run_item(self, *, tenant_id: uuid.UUID, run_id: uuid.UUID) -> DescribeRunItem | None:
        """Return the sole item for a single-run job (None if missing or empty)."""
        items = await self.list_run_items(tenant_id=tenant_id, run_id=run_id)
        if not items:
            return None
        return items[0]

    async def set_item_provisional(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        media_id: int,
        visual_facts: dict[str, Any],
        now: datetime | None = None,
    ) -> bool:
        """Persist CPU provisional envelope; keep image_bytes for GPU supersede."""
        now = now or datetime.now(tz=UTC)
        item = await self._get_item(tenant_id=tenant_id, run_id=run_id, media_id=media_id)
        if item is None:
            return False
        if DescribeItemStatus(item.status) in TERMINAL_ITEM_STATUSES:
            return False
        if item.status != DescribeItemStatus.RUNNING:
            item.status = DescribeItemStatus.RUNNING
            item.started_at = item.started_at or now
            item.attempts = max(item.attempts, 1)
        item.visual_facts = visual_facts
        item.tier = DescriptionResultTier.PROVISIONAL_CPU
        item.result_generation = 1
        item.last_error = None
        await self._recompute_run_totals(tenant_id=tenant_id, run_id=run_id, now=now)
        await self._session.flush()
        return True

    async def set_item_final(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        media_id: int,
        visual_facts: dict[str, Any],
        now: datetime | None = None,
    ) -> bool:
        """Persist GPU-final envelope and mark the item terminal completed.

        Returns True only when the FINAL envelope is persisted on the item —
        either by this call or by a prior FINAL_GPU write (idempotent re-run).
        A terminal item in any other state (degraded/failed/cancelled) returns
        False WITHOUT writing: the envelope is dropped, and callers must gate
        the image_descriptions cache write on this return (VLM5-S1A-BR-02).
        """
        now = now or datetime.now(tz=UTC)
        item = await self._get_item(tenant_id=tenant_id, run_id=run_id, media_id=media_id)
        if item is None:
            return False
        if DescribeItemStatus(item.status) in TERMINAL_ITEM_STATUSES:
            return (
                DescribeItemStatus(item.status) is DescribeItemStatus.COMPLETED
                and item.tier is not None
                and DescriptionResultTier(item.tier) is DescriptionResultTier.FINAL_GPU
            )
        item.status = DescribeItemStatus.COMPLETED
        item.completed_at = now
        item.visual_facts = visual_facts
        item.tier = DescriptionResultTier.FINAL_GPU
        item.result_generation = 2
        item.last_error = None
        item.image_bytes = None
        await self._recompute_run_totals(tenant_id=tenant_id, run_id=run_id, now=now)
        await self._session.flush()
        return True

    async def set_item_degraded(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        media_id: int,
        error: str,
        now: datetime | None = None,
    ) -> bool:
        """Keep provisional visual_facts; mark completed with last_error (projects degraded).

        Degraded requires a persisted provisional envelope (plan Terminology:
        degraded = GPU failure AFTER a provisional). Without ``visual_facts``
        this delegates to the FAILED path — mirroring the reclaim branch — so a
        facts-less item can never project DEGRADED with a null result payload
        (VLM5-S1A-BR-03).
        """
        now = now or datetime.now(tz=UTC)
        item = await self._get_item(tenant_id=tenant_id, run_id=run_id, media_id=media_id)
        if item is None:
            return False
        if DescribeItemStatus(item.status) in TERMINAL_ITEM_STATUSES:
            return DescribeItemStatus(item.status) is DescribeItemStatus.COMPLETED and item.last_error is not None
        if item.visual_facts is None:
            return await self.mark_item(
                tenant_id=tenant_id,
                run_id=run_id,
                media_id=media_id,
                status=DescribeItemStatus.FAILED,
                error_message=error,
                now=now,
            )
        item.status = DescribeItemStatus.COMPLETED
        item.completed_at = now
        item.tier = item.tier or DescriptionResultTier.PROVISIONAL_CPU
        if not item.result_generation:
            item.result_generation = 1
        item.last_error = error
        item.image_bytes = None
        await self._recompute_run_totals(tenant_id=tenant_id, run_id=run_id, now=now)
        await self._session.flush()
        return True

    async def set_item_failed(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        media_id: int,
        error: str,
        now: datetime | None = None,
    ) -> bool:
        """Mark the single-run item failed and reclaim image bytes."""
        return await self.mark_item(
            tenant_id=tenant_id,
            run_id=run_id,
            media_id=media_id,
            status=DescribeItemStatus.FAILED,
            error_message=error,
            now=now,
        )

    async def purge_expired_single_runs(
        self,
        *,
        now: datetime | None = None,
        retention_hours: int | None = None,
    ) -> int:
        """Delete terminal ``run_kind=single`` runs older than retention (cross-tenant).

        MUST run on an RLS-bypassed system session (design (c)/(d)) — same gate as
        :meth:`reclaim_interrupted_runs` [SEC-01], [RES-07].
        """
        await self._require_rls_bypass()
        now = now or datetime.now(tz=UTC)
        hours = retention_hours if retention_hours is not None else async_job_retention_hours()
        cutoff = now - timedelta(hours=hours)
        result = await self._session.execute(
            select(DescribeRun).where(
                DescribeRun.run_kind == RunKind.SINGLE,
                DescribeRun.status.in_(list(TERMINAL_RUN_STATUSES)),
                DescribeRun.completed_at.is_not(None),
                DescribeRun.completed_at < cutoff,
            )
        )
        runs = list(result.scalars().all())
        if not runs:
            return 0
        run_ids = [run.id for run in runs]
        await self._session.execute(delete(DescribeRunItem).where(DescribeRunItem.run_id.in_(run_ids)))
        await self._session.execute(delete(DescribeRun).where(DescribeRun.id.in_(run_ids)))
        await self._session.flush()
        return len(runs)

    async def record_item_result(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        media_id: int,
        alt_text_draft: str | None,
        caption: str | None,
        provenance: dict | None,
        tier: DescriptionResultTier | str | None = None,
    ) -> bool:
        """Persist the describe output for one item and clear its image bytes."""
        item = await self._get_item(tenant_id=tenant_id, run_id=run_id, media_id=media_id)
        if item is None:
            return False
        item.alt_text_draft = alt_text_draft
        item.caption = caption
        item.provenance = provenance
        item.tier = DescriptionResultTier(tier) if tier is not None else None
        if any(value is not None for value in (alt_text_draft, caption, provenance, tier)):
            item.result_generation = int(item.result_generation or 0) + 1
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
        """Force a run terminal-FAILED on an unexpected fatal worker error.

        A run that is already terminal is left untouched: a cancel that landed
        while the worker was failing must keep CANCELLED (HARM-01). Remaining
        non-terminal items are driven terminal-FAILED so their stored image
        bytes are reclaimed rather than stranded QUEUED under a FAILED run.
        """
        run = await self.get_run(tenant_id=tenant_id, run_id=run_id)
        if run is None:
            return False
        if DescribeRunStatus(run.status) in TERMINAL_RUN_STATUSES:
            return False
        now = now or datetime.now(tz=UTC)
        for item in await self.list_run_items(tenant_id=tenant_id, run_id=run_id):
            if DescribeItemStatus(item.status) in TERMINAL_ITEM_STATUSES:
                continue
            try:
                await self.mark_item(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=item.media_id,
                    status=DescribeItemStatus.FAILED,
                    error_message=error_message or "run failed before this item was processed",
                    now=now,
                )
            except Exception:  # noqa: BLE001 - byte reclamation is best-effort,
                # but a failed flush poisons the session (pending rollback) and
                # would abort the terminal run write below. Roll back and keep
                # going; the run-status write is the part that must land.
                await self._session.rollback()
                continue
        # The rollback above expires ORM state; re-fetch so the status check and
        # terminal write below never touch expired attributes in async context.
        run = await self.get_run(tenant_id=tenant_id, run_id=run_id)
        if run is None:
            return False
        # The per-item recompute may already have derived a terminal status. A
        # fatal-path write preserves only CANCELLED (cancel wins, untouched);
        # anything else -- including a derived COMPLETED_WITH_ERRORS -- becomes
        # FAILED, because this path only runs when the worker died fatally.
        if DescribeRunStatus(run.status) is DescribeRunStatus.CANCELLED:
            return False
        run.status = DescribeRunStatus.FAILED
        run.phase = DescribeRunPhase.FAILED
        if run.completed_at is None:
            run.completed_at = now
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
            # BE-04: reclaim stored image bytes on ANY terminal state (including
            # SKIPPED on cancel), not only the worker's success/failure path.
            item.image_bytes = None
        else:
            item.status = status

        await self._recompute_run_totals(tenant_id=tenant_id, run_id=run_id, now=now)
        await self._session.flush()
        return True

    async def _require_rls_bypass(self) -> None:
        """Fail closed unless this session has RLS bypass active (S5-02).

        Cross-tenant ops (``reclaim_interrupted_runs``, ``purge_expired_single_runs``)
        take no tenant filter, so they MUST run on a system-scoped, RLS-bypassed
        session — otherwise RLS would silently hide most rows and the sweep would
        be a partial, wrong no-op. On SQLite (tests) there is no RLS, so this is
        a graceful no-op.
        """
        if is_sqlite(self._session):
            return
        result = await self._session.execute(text("SELECT current_setting('app.bypass_rls', true)"))
        value = result.scalar()
        if value is None or str(value).strip().lower() not in _TRUTHY_PG_SETTINGS:
            raise RuntimeError(
                "cross-tenant describe-run op requires an RLS-bypassed system session "
                "(current_setting('app.bypass_rls') is not truthy); call it via "
                "run_startup_reclaim / enable_rls_bypass(session) first"
            )

    async def reclaim_interrupted_runs(self, *, now: datetime | None = None) -> int:
        """WBUX-4 INT-02: drive orphaned non-terminal runs to an honest terminal state.

        The worker runs in-process, so a run still PENDING/RUNNING at startup is
        orphaned by a restart — nothing will finish it. Fail its still-non-terminal
        items, clear stranded image bytes, then derive the run's terminal status
        the same way the live recompute path does (S5-01/S5-04): a cancel that was
        requested wins (CANCELLED), any failure -> COMPLETED_WITH_ERRORS, else
        COMPLETED. The caller MUST provide a system-scoped / RLS-bypassed session:
        this sweeps ALL tenants and takes no tenant filter.

        VLM-5 design (e): for ``run_kind=single`` items that already hold
        provisional ``visual_facts``, mark ``completed`` with
        ``last_error='interrupted by service restart'`` so the poll projection
        yields ``degraded`` and the provisional result stays pollable; without
        provisional, mark ``failed`` as bulk does.

        S5-05 (single-process assumption): this sweep is only safe because the
        bulk worker runs in a single in-process FastAPI task (no ``--workers`` /
        no horizontal replicas). It unconditionally fails every non-terminal run
        it sees, so under multiple replicas a booting replica would kill runs that
        another replica is actively processing. Horizontal scaling MUST first add
        a boot-time/heartbeat ownership guard (rg-007) before removing this
        assumption.
        """
        await self._require_rls_bypass()
        now = now or datetime.now(tz=UTC)
        result = await self._session.execute(
            select(DescribeRun).where(DescribeRun.status.in_([DescribeRunStatus.PENDING, DescribeRunStatus.RUNNING]))
        )
        runs = list(result.scalars().all())
        for run in runs:
            items_res = await self._session.execute(select(DescribeRunItem).where(DescribeRunItem.run_id == run.id))
            items = list(items_res.scalars().all())
            is_single = run.run_kind == RunKind.SINGLE
            for item in items:
                if item.status not in TERMINAL_ITEM_STATUSES:
                    if is_single and item.visual_facts is not None:
                        # Preserve provisional result; projects to degraded (design e).
                        item.status = DescribeItemStatus.COMPLETED
                        item.completed_at = now
                        item.last_error = item.last_error or _RECLAIM_INTERRUPT_ERROR
                        item.tier = item.tier or DescriptionResultTier.PROVISIONAL_CPU
                        if not item.result_generation:
                            item.result_generation = 1
                    else:
                        item.status = DescribeItemStatus.FAILED
                        item.completed_at = now
                        item.last_error = item.last_error or _RECLAIM_INTERRUPT_ERROR
                item.image_bytes = None
            statuses = Counter(item.status for item in items)
            completed = statuses[DescribeItemStatus.COMPLETED]
            failed = statuses[DescribeItemStatus.FAILED]
            skipped = statuses[DescribeItemStatus.SKIPPED]
            run.completed_items = completed
            run.failed_items = failed
            run.skipped_items = skipped
            # D2-01: gate terminal-status derivation on all items being terminal,
            # matching _recompute_run_totals. Under the atomic item-creation
            # invariant (persisted items == total_items) every item is terminal
            # here — this always holds and behavior is unchanged. Kept as a
            # defensive alignment: a genuinely-incomplete run (fewer persisted
            # items than total_items) falls back to FAILED rather than deriving
            # a falsely-successful terminal status from a partial item set.
            terminal = completed + failed + skipped
            if terminal >= run.total_items:
                status = terminal_run_status(
                    completed=completed,
                    failed=failed,
                    skipped=skipped,
                    cancel_requested=run.cancel_requested,
                )
            else:
                status = DescribeRunStatus.FAILED
            run.status = status
            run.phase = phase_for_status(status)
            run.completed_at = now
            if status in {DescribeRunStatus.FAILED, DescribeRunStatus.COMPLETED_WITH_ERRORS}:
                run.error_message = run.error_message or _RECLAIM_INTERRUPT_ERROR
        await self._session.flush()
        return len(runs)

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
            status = terminal_run_status(
                completed=completed,
                failed=failed,
                skipped=skipped,
                cancel_requested=run.cancel_requested,
            )
            run.status = status
            run.phase = phase_for_status(status)
            run.completed_at = now
        elif running:
            run.status = DescribeRunStatus.RUNNING
            run.phase = DescribeRunPhase.DESCRIBING
        else:
            run.status = DescribeRunStatus.PENDING
            run.phase = DescribeRunPhase.QUEUED


async def run_startup_reclaim(session_factory) -> int:
    """WBUX-4 INT-02: reclaim interrupted describe runs once at service startup.

    Opens a system-scoped session with RLS bypassed so the sweep spans all
    tenants, marks orphaned non-terminal runs terminal, and commits. Best-effort
    and idempotent — safe to call on every boot. Returns the number reclaimed.
    """
    from db.tenant_context import enable_rls_bypass

    async with session_factory() as session:
        await enable_rls_bypass(session)
        count = await DescribeRunRepository(session).reclaim_interrupted_runs()
        await session.commit()
    return count


async def run_startup_retention_purge(session_factory) -> int:
    """VLM-5 design (d): purge expired terminal single runs once at service startup.

    Dedicated short-lived RLS-bypassed session (design (c) session discipline) —
    never a tenant-scoped session. Best-effort and idempotent. Returns deleted run count.
    """
    from db.tenant_context import enable_rls_bypass

    async with session_factory() as session:
        await enable_rls_bypass(session)
        count = await DescribeRunRepository(session).purge_expired_single_runs()
        await session.commit()
    return count
