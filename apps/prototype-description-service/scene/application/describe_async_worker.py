"""DB-backed async supersede worker for single-image describe jobs (VLM-5).

Ports ``description_worker.run_describe_job`` onto ``DescribeRunRepository``:
CPU provisional → GPU final, degraded-on-GPU-failure, timeout, CancelledError
re-raise [CON-03], and FINAL-tier cache write-through on the same commit as
``set_item_final`` [DATA-14].
"""

from __future__ import annotations

import asyncio
import contextlib
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
from scene.application.visual_facts_service import build_visual_facts_envelope
from scene.domain.describe_run import DescribeItemStatus
from scene.domain.description import DescriptionResultTier, RetentionClass


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
    """Build the 17-field envelope — byte-compatible with description_worker._result_payload."""
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


def _envelope_to_cache_row(envelope: dict[str, Any]) -> ImageDescription:
    """Map a FINAL-tier wire envelope into an ``image_descriptions`` cache row."""
    return ImageDescription(
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
    [DATA-14]. CancelledError marks failed then re-raises [CON-03].
    """

    async def _mark_failed(error: str) -> None:
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            repo = DescribeRunRepository(session)
            item = await repo.get_single_run_item(tenant_id=tenant_id, run_id=run_id)
            if item is None:
                return
            if DescribeItemStatus(item.status) is DescribeItemStatus.FAILED:
                return
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
                image_bytes = item.image_bytes or b""
                await repo.mark_item(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=media_id,
                    status=DescribeItemStatus.RUNNING,
                )
                await session.commit()

            if media_id is None:
                return

            # CPU provisional (no open DB session during adapter work).
            cpu_result, cpu_duration_ms = await _describe_adapter(
                cpu_adapter, image_bytes=image_bytes, context=context
            )
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
            gpu_result, gpu_duration_ms = await _describe_adapter(
                gpu_adapter, image_bytes=image_bytes, context=context
            )
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
                await cache_repo.insert_or_get_existing(_envelope_to_cache_row(final_envelope))
                await repo.set_item_final(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=media_id,
                    visual_facts=final_envelope,
                )
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
            # Mark failed for pollers, then re-raise so cooperative cancellation
            # and wait_for timeout semantics still work [CON-03].
            await _mark_failed("CancelledError: job cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - persist terminal job failure
            error = f"{type(exc).__name__}: {exc}"
            if media_id is None:
                return
            async with session_factory() as session:
                await set_tenant_context(session, tenant_id)
                repo = DescribeRunRepository(session)
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
            # wait_for cancels the inner task; CancelledError may already have
            # marked FAILED. Avoid a second set_failed that overwrites the error.
            async with session_factory() as session:
                await set_tenant_context(session, tenant_id)
                repo = DescribeRunRepository(session)
                item = await repo.get_single_run_item(tenant_id=tenant_id, run_id=run_id)
                if item is not None and DescribeItemStatus(item.status) is DescribeItemStatus.FAILED:
                    return
                media_id = item.media_id if item is not None else None
                if media_id is None:
                    return
                await repo.set_item_failed(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    media_id=media_id,
                    error=f"TimeoutError: job exceeded {job_timeout_seconds}s",
                )
                await session.commit()
        return
    await _run()
