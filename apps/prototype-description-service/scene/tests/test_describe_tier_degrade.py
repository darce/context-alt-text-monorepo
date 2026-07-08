from __future__ import annotations

import asyncio
import uuid

from scene.application.describe_jobs import DescribeJobStatus, InMemoryDescribeJobStore
from scene.application.description_adapter import AdapterResult
from scene.application.description_worker import run_describe_job
from scene.domain.description import DescriptionAdapterKind


class _Adapter:
    prompt_or_task_version = "1"

    def __init__(self, *, kind: DescriptionAdapterKind, caption: str) -> None:
        self.kind = kind
        self.model_id = f"{kind.value}-model"
        self.model_version = "1"
        self.caption = caption

    def describe(self, *, image_bytes, context):
        return AdapterResult(
            caption=self.caption,
            objects=(),
            ocr_text=None,
            alt_text_draft=self.caption,
            context_sources=(),
            context_applied=False,
        )


def test_worker_records_cpu_provisional_then_gpu_final() -> None:
    async def body() -> None:
        store = InMemoryDescribeJobStore()
        job = store.enqueue(tenant_id=uuid.uuid4(), media_id=7, image_bytes=b"image", context={"title": "Launch"})

        final = await run_describe_job(
            store=store,
            job_id=job.job_id,
            cpu_adapter=_Adapter(kind=DescriptionAdapterKind.LOCAL_CPU, caption="CPU provisional."),
            gpu_adapter=_Adapter(kind=DescriptionAdapterKind.GPU, caption="GPU final."),
        )

        assert final.status is DescribeJobStatus.FINAL
        assert final.tier == "final_gpu"
        assert final.result_generation == 2
        assert final.visual_facts["alt_text_draft"] == "GPU final."

    asyncio.run(body())
