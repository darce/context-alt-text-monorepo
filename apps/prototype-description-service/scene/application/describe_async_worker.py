"""DB-backed async supersede worker for single-image describe jobs (VLM-5).

CPU provisional → GPU final, degraded-on-GPU-failure, timeout, CancelledError
re-raise [CON-03], and FINAL-tier cache write-through on the same commit as
``set_item_final`` [DATA-14].
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models.scene import ImageDescription
from db.tenant_context import set_tenant_context
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.description_adapter import AdapterResult, DescriptionAdapter
from scene.application.description_repository import ImageDescriptionRepository
from scene.application.visual_facts_service import build_visual_facts_envelope, phrase_boxes_to_json
from scene.domain.describe_run import TERMINAL_ITEM_STATUSES, DescribeItemStatus
from scene.domain.description import DescriptionResultTier, RetentionClass

_logger = logging.getLogger(__name__)

# Strong refs for shielded cancellation-cleanup tasks: asyncio holds only weak
# task refs, so a second cancel abandoning the shield must not let the cleanup
# be GC'd mid-write (VLM5-F1A-BR-01).
_cleanup_tasks: set[asyncio.Task] = set()


def _log_cleanup_failure(task: asyncio.Task) -> None:
    """Retrieve the cleanup task result so a DB failure is logged, never silent."""
    _cleanup_tasks.discard(task)
    if task.cancelled():
        _logger.error("cancellation cleanup was cancelled before persisting terminal state")
        return
    exc = task.exception()
    if exc is not None:
        _logger.error("cancellation cleanup failed to persist terminal job state", exc_info=exc)


class AuditSink(Protocol):
    async def record(self, *, tenant_id: uuid.UUID, event_type: str, payload: dict[str, Any]) -> None: ...


class DescriptionMetrics(Protocol):
    def record_request(self, *, adapter: str, result: str) -> None: ...

    def observe_adapter_duration(self, *, adapter: str, duration_seconds: float) -> None: ...


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _result_payload(
    result: AdapterResult,
    *,
    adapter: DescriptionAdapter,
    tenant_id: uuid.UUID,
    media_id: int,
    image_bytes: bytes,
    context: Mapping[str, Any] | None,
    tier: DescriptionResultTier,
    result_generation: int,
    duration_ms: int,
) -> dict[str, Any]:
    """Build the 17-field visual-facts envelope for provisional/final tiers."""
    return build_visual_facts_envelope(
        result=result,
        adapter=adapter,
        tenant_id=tenant_id,
        media_id=media_id,
        image_bytes=image_bytes,
        context=context,
        tier=tier,
        result_generation=result_generation,
        duration_ms=duration_ms,
        retention_class=RetentionClass.RETAIN_ALL,
    )


def _envelope_to_cache_row(envelope: dict[str, Any], *, result: AdapterResult) -> ImageDescription:
    """Map a FINAL-tier wire envelope into an ``image_descriptions`` cache row.

    ``phrase_boxes`` are not part of the wire envelope, so they come from the
    adapter result — the sync path persists them the same way so cache hits
    keep grounded-naming parity (VLM5-S2A-BR-01, E19-4a).
    """
    return ImageDescription(
        phrase_boxes=phrase_boxes_to_json(result.phrase_boxes),
        tenant_id=uuid.UUID(str(envelope["tenant_id"])),
        media_id=int(envelope["media_id"]),
        image_hash=str(envelope["image_hash"]),
        context_hash=str(envelope["context_hash"]),
        adapter=str(envelope["adapter"]),
        model_id=str(envelope["model_id"]),
        model_version=str(envelope["model_version"]),
        prompt_or_task_version=str(envelope["prompt_or_task_version"]),
        visual_facts=dict(envelope["visual_facts"]),
        alt_text_draft=str(envelope["alt_text_draft"]),
        context_used=dict(envelope["context_used"]),
        provider_disclosure=dict(envelope["provider_disclosure"]),
        retention_class=str(envelope["retention_class"]),
        duration_ms=int(envelope["duration_ms"]),
    )


async def _describe_adapter(
    adapter: DescriptionAdapter,
    *,
    image_bytes: bytes,
    context: Mapping[str, Any] | None,
) -> tuple[AdapterResult, int]:
    start = time.perf_counter()
    result = await asyncio.to_thread(adapter.describe, image_bytes=image_bytes, context=context)
    return result, _elapsed_ms(start)


async def run_async_describe_job(
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    cpu_adapter: DescriptionAdapter,
    gpu_adapter: DescriptionAdapter,
    job_timeout_seconds: float | None = None,
    audit_sink: AuditSink | None = None,
    metrics: DescriptionMetrics | None = None,
    context: Mapping[str, Any] | None = None,
) -> None:
    """Run one single-run job: CPU provisional first, then GPU final supersede.

    Phase commits use short-lived sessions so long adapter calls do not hold a DB
    connection open. FINAL cache write-through shares the ``set_item_final`` commit
    [DATA-14]. CancelledError marks the job terminal (degraded when a provisional
    exists, else failed) then re-raises [CON-03].
    """

    async def _mark_terminal(error: str) -> None:
        """Drive a non-terminal item to an honest terminal state for pollers.

        Degraded when a provisional envelope was already persisted (contract:
        degraded = GPU failure after a provisional — same as the GPU-exception
        and restart-reclaim paths), else failed (VLM5-F1A-BR-02). No-op when
        the item is already terminal, so cancel + timeout cannot double-write.
        """
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            repo = DescribeRunRepository(session)
            item = await repo.get_single_run_item(tenant_id=tenant_id, run_id=run_id)
            if item is None:
                return
            if DescribeItemStatus(item.status) in TERMINAL_ITEM_STATUSES:
                return
            if item.visual_facts is not None:
                await repo.set_item_degraded(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=item.media_id,
                    error=error,
                )
            else:
                await repo.set_item_failed(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=item.media_id,
                    error=error,
                )
            await session.commit()

    async def _run() -> None:
        provisional_set = False
        media_id: int | None = None
        image_bytes = b""

        try:
            # Phase: mark running + load image bytes (short session).
            async with session_factory() as session:
                await set_tenant_context(session, tenant_id)
                repo = DescribeRunRepository(session)
                item = await repo.get_single_run_item(tenant_id=tenant_id, run_id=run_id)
                if item is None:
                    return
                media_id = item.media_id
                marked = await repo.mark_item(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=media_id,
                    status=DescribeItemStatus.RUNNING,
                )
                if not marked:
                    # Already terminal (duplicate dispatch / retry after cancel):
                    # bytes were reclaimed — never run adapters or cache-write
                    # for this invocation (VLM5-S2A-BR-02).
                    return
                if item.image_bytes is None:
                    await repo.set_item_failed(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        media_id=media_id,
                        error="ValueError: queued item has no image bytes",
                    )
                    await session.commit()
                    return
                image_bytes = item.image_bytes
                await session.commit()

            if media_id is None:
                return

            # CPU provisional (no open DB session during adapter work).
            cpu_result, cpu_duration_ms = await _describe_adapter(cpu_adapter, image_bytes=image_bytes, context=context)
            if metrics is not None:
                metrics.record_request(adapter=cpu_adapter.kind.value, result="generated")
                metrics.observe_adapter_duration(
                    adapter=cpu_adapter.kind.value, duration_seconds=cpu_duration_ms / 1000
                )
            provisional_envelope = _result_payload(
                cpu_result,
                adapter=cpu_adapter,
                tenant_id=tenant_id,
                media_id=media_id,
                image_bytes=image_bytes,
                context=context,
                tier=DescriptionResultTier.PROVISIONAL_CPU,
                result_generation=1,
                duration_ms=cpu_duration_ms,
            )
            async with session_factory() as session:
                await set_tenant_context(session, tenant_id)
                repo = DescribeRunRepository(session)
                await repo.set_item_provisional(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=media_id,
                    visual_facts=provisional_envelope,
                )
                await session.commit()
            provisional_set = True
            if audit_sink is not None:
                with contextlib.suppress(Exception):
                    await audit_sink.record(
                        tenant_id=tenant_id,
                        event_type="description.generated",
                        payload={
                            "media_id": media_id,
                            "adapter": cpu_adapter.kind.value,
                            "tier": DescriptionResultTier.PROVISIONAL_CPU.value,
                            "job_id": str(run_id),
                        },
                    )

            # GPU final (no open DB session during adapter work).
            gpu_result, gpu_duration_ms = await _describe_adapter(gpu_adapter, image_bytes=image_bytes, context=context)
            if metrics is not None:
                metrics.record_request(adapter=gpu_adapter.kind.value, result="generated")
                metrics.observe_adapter_duration(
                    adapter=gpu_adapter.kind.value, duration_seconds=gpu_duration_ms / 1000
                )
            final_envelope = _result_payload(
                gpu_result,
                adapter=gpu_adapter,
                tenant_id=tenant_id,
                media_id=media_id,
                image_bytes=image_bytes,
                context=context,
                tier=DescriptionResultTier.FINAL_GPU,
                result_generation=2,
                duration_ms=gpu_duration_ms,
            )
            # FINAL cache write-through + set_item_final on the same session/commit [DATA-14].
            async with session_factory() as session:
                await set_tenant_context(session, tenant_id)
                repo = DescribeRunRepository(session)
                cache_repo = ImageDescriptionRepository(session)
                final_persisted = await repo.set_item_final(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=media_id,
                    visual_facts=final_envelope,
                )
                if final_persisted:
                    # Gate the cache row on an actually-persisted item-final so
                    # the cache and the durable item row cannot diverge
                    # (VLM5-S2A-BR-02, VLM5-S1A-BR-02) [DATA-14].
                    await cache_repo.insert_or_get_existing(_envelope_to_cache_row(final_envelope, result=gpu_result))
                await session.commit()
            if audit_sink is not None:
                with contextlib.suppress(Exception):
                    await audit_sink.record(
                        tenant_id=tenant_id,
                        event_type="description.generated",
                        payload={
                            "media_id": media_id,
                            "adapter": gpu_adapter.kind.value,
                            "tier": DescriptionResultTier.FINAL_GPU.value,
                            "job_id": str(run_id),
                        },
                    )
        except asyncio.CancelledError:
            # Mark terminal for pollers, then re-raise so cooperative cancellation
            # and wait_for timeout semantics still work [CON-03]. The cleanup write
            # is shielded so a second cancel cannot abort the persist, suppressed so
            # a DB error during shutdown cannot replace the CancelledError
            # (VLM5-S2A-BR-04) [RES-04], strongly referenced + done-callback-logged
            # so an abandoned or failed cleanup is never silent (VLM5-F1A-BR-01).
            cleanup = asyncio.ensure_future(_mark_terminal("CancelledError: job cancelled"))
            _cleanup_tasks.add(cleanup)
            cleanup.add_done_callback(_log_cleanup_failure)
            with contextlib.suppress(Exception):
                await asyncio.shield(cleanup)
            raise
        except Exception as exc:  # noqa: BLE001 - persist terminal job failure
            error = f"{type(exc).__name__}: {exc}"
            _logger.exception("async describe job failed run_id=%s media_id=%s", run_id, media_id)
            async with session_factory() as session:
                await set_tenant_context(session, tenant_id)
                repo = DescribeRunRepository(session)
                if media_id is None:
                    # First session phase failed before media_id was assigned
                    # (e.g. transient DB error in set_tenant_context or the
                    # item fetch). Re-fetch so the job still lands terminal
                    # FAILED instead of sticking QUEUED forever
                    # (VLM5-S2A-BR-03) [RES-04].
                    item = await repo.get_single_run_item(tenant_id=tenant_id, run_id=run_id)
                    if item is None:
                        return
                    media_id = item.media_id
                if provisional_set:
                    await repo.set_item_degraded(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        media_id=media_id,
                        error=error,
                    )
                else:
                    await repo.set_item_failed(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        media_id=media_id,
                        error=error,
                    )
                await session.commit()

    if job_timeout_seconds is not None:
        try:
            await asyncio.wait_for(_run(), job_timeout_seconds)
        except TimeoutError:
            # wait_for cancels the inner task; the CancelledError cleanup usually
            # persisted a terminal state already. _mark_terminal's terminal guard
            # prevents a second write from overwriting that error, and its
            # degraded-vs-failed split keeps the timeout path consistent with the
            # GPU-exception and reclaim contracts (VLM5-F1A-BR-02).
            await _mark_terminal(f"TimeoutError: job exceeded {job_timeout_seconds}s")
        return
    await _run()
