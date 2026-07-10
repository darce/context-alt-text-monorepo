"""Async describe worker primitives."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Mapping
from typing import Any, Protocol

from scene.application.describe_jobs import DescribeJob, DescribeJobStatus, InMemoryDescribeJobStore
from scene.application.description_adapter import AdapterResult, DescriptionAdapter
from scene.application.visual_facts_service import build_visual_facts_envelope
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
    job: DescribeJob,
    image_bytes: bytes,
    tier: DescriptionResultTier,
    result_generation: int,
    duration_ms: int,
) -> dict[str, Any]:
    return build_visual_facts_envelope(
        result=result,
        adapter=adapter,
        tenant_id=job.tenant_id,
        media_id=job.media_id,
        image_bytes=image_bytes,
        context=job.context,
        tier=tier,
        result_generation=result_generation,
        duration_ms=duration_ms,
        retention_class=RetentionClass.RETAIN_ALL,
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


async def run_describe_job(
    *,
    store: InMemoryDescribeJobStore,
    job_id: str,
    cpu_adapter: DescriptionAdapter,
    gpu_adapter: DescriptionAdapter,
    job_timeout_seconds: float | None = None,
    audit_sink: AuditSink | None = None,
    metrics: DescriptionMetrics | None = None,
) -> DescribeJob:
    """Run one job: CPU provisional first, then GPU final supersede."""

    async def _run() -> DescribeJob:
        job = store.mark_running(job_id)
        provisional_set = False
        provisional: DescribeJob | None = None
        try:
            cpu_result, cpu_duration_ms = await _describe_adapter(
                cpu_adapter, image_bytes=job.image_bytes, context=job.context
            )
            if metrics is not None:
                metrics.record_request(adapter=cpu_adapter.kind.value, result="generated")
                metrics.observe_adapter_duration(
                    adapter=cpu_adapter.kind.value, duration_seconds=cpu_duration_ms / 1000
                )
            provisional = store.set_provisional(
                job_id,
                visual_facts=_result_payload(
                    cpu_result,
                    adapter=cpu_adapter,
                    job=job,
                    image_bytes=job.image_bytes,
                    tier=DescriptionResultTier.PROVISIONAL_CPU,
                    result_generation=1,
                    duration_ms=cpu_duration_ms,
                ),
            )
            provisional_set = True
            if audit_sink is not None:
                with contextlib.suppress(Exception):
                    await audit_sink.record(
                        tenant_id=job.tenant_id,
                        event_type="description.generated",
                        payload={
                            "media_id": job.media_id,
                            "adapter": cpu_adapter.kind.value,
                            "tier": DescriptionResultTier.PROVISIONAL_CPU.value,
                            "job_id": job_id,
                        },
                    )

            gpu_result, gpu_duration_ms = await _describe_adapter(
                gpu_adapter, image_bytes=job.image_bytes, context=job.context
            )
            if metrics is not None:
                metrics.record_request(adapter=gpu_adapter.kind.value, result="generated")
                metrics.observe_adapter_duration(
                    adapter=gpu_adapter.kind.value, duration_seconds=gpu_duration_ms / 1000
                )
            final = store.set_final(
                job_id,
                visual_facts=_result_payload(
                    gpu_result,
                    adapter=gpu_adapter,
                    job=job,
                    image_bytes=job.image_bytes,
                    tier=DescriptionResultTier.FINAL_GPU,
                    result_generation=2,
                    duration_ms=gpu_duration_ms,
                ),
            )
            if audit_sink is not None:
                with contextlib.suppress(Exception):
                    await audit_sink.record(
                        tenant_id=job.tenant_id,
                        event_type="description.generated",
                        payload={
                            "media_id": job.media_id,
                            "adapter": gpu_adapter.kind.value,
                            "tier": DescriptionResultTier.FINAL_GPU.value,
                            "job_id": job_id,
                        },
                    )
            return final
        except asyncio.CancelledError:
            # Mark failed for pollers, then re-raise so cooperative cancellation
            # and wait_for timeout semantics still work (CON-03 / VLMFIX-S1-04).
            store.set_failed(job_id, error="CancelledError: job cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - persist terminal job failure
            error = f"{type(exc).__name__}: {exc}"
            if provisional_set and provisional is not None and provisional.visual_facts is not None:
                return store.set_degraded(job_id, error=error)
            return store.set_failed(job_id, error=error)

    if job_timeout_seconds is not None:
        try:
            return await asyncio.wait_for(_run(), job_timeout_seconds)
        except TimeoutError:
            # wait_for cancels the inner task; CancelledError may already have
            # marked FAILED. Avoid a second set_failed that overwrites the error.
            existing = store.get(job_id)
            if existing is not None and existing.status is DescribeJobStatus.FAILED:
                return existing
            return store.set_failed(job_id, error=f"TimeoutError: job exceeded {job_timeout_seconds}s")
    return await _run()
