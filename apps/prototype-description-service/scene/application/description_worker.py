"""Async describe worker primitives."""

from __future__ import annotations

import asyncio
from typing import Any

from scene.application.describe_jobs import DescribeJob, InMemoryDescribeJobStore
from scene.application.description_adapter import AdapterResult, DescriptionAdapter


def _result_payload(result: AdapterResult, *, adapter: DescriptionAdapter) -> dict[str, Any]:
    return {
        "adapter": adapter.kind.value,
        "model_id": adapter.model_id,
        "model_version": adapter.model_version,
        "caption": result.caption,
        "objects": list(result.objects),
        "ocr_text": result.ocr_text,
        "alt_text_draft": result.alt_text_draft,
        "context_sources": list(result.context_sources),
        "context_applied": result.context_applied,
    }


async def run_describe_job(
    *,
    store: InMemoryDescribeJobStore,
    job_id: str,
    cpu_adapter: DescriptionAdapter,
    gpu_adapter: DescriptionAdapter,
) -> DescribeJob:
    """Run one job: CPU provisional first, then GPU final supersede."""

    job = store.mark_running(job_id)
    try:
        cpu_result = await asyncio.to_thread(cpu_adapter.describe, image_bytes=job.image_bytes, context=job.context)
        store.set_provisional(job_id, visual_facts=_result_payload(cpu_result, adapter=cpu_adapter))
        gpu_result = await asyncio.to_thread(gpu_adapter.describe, image_bytes=job.image_bytes, context=job.context)
        return store.set_final(job_id, visual_facts=_result_payload(gpu_result, adapter=gpu_adapter))
    except Exception as exc:  # noqa: BLE001 - persist terminal job failure
        return store.set_failed(job_id, error=f"{type(exc).__name__}: {exc}")
