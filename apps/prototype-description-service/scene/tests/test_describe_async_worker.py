"""VLM-5 Slice 2: DB-backed supersede worker (run_async_describe_job).

Provisional→final, degraded-on-GPU-failure, timeout once, cancellation re-raise,
FINAL cache write-through only [TEST-13], [DATA-14], [CON-03].
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import jsonschema
import pytest
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem, ImageDescription
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.description_adapter import AdapterResult
from scene.domain.describe_run import DescribeItemStatus, DescribeJobStatus, describe_job_status
from scene.domain.description import DescriptionAdapterKind, DescriptionResultTier

SCHEMA_PATH = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "shared-contracts"
    / "schemas"
    / "image-description-response.schema.json"
)


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


async def _sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=cast(
                list[Table],
                [DescribeRun.__table__, DescribeRunItem.__table__, ImageDescription.__table__],
            ),
        )
    return engine, async_sessionmaker(engine, expire_on_commit=False)


class _Adapter:
    """Spec'd fake DescriptionAdapter [TEST-13]."""

    prompt_or_task_version = "1"

    def __init__(self, *, kind: DescriptionAdapterKind, caption: str, delay_s: float = 0.0) -> None:
        self.kind = kind
        self.model_id = f"{kind.value}-model"
        self.model_version = "1"
        self.caption = caption
        self.delay_s = delay_s
        self.calls = 0

    def describe(self, *, image_bytes: bytes, context: dict[str, Any] | None) -> AdapterResult:
        self.calls += 1
        if self.delay_s > 0:
            time.sleep(self.delay_s)
        return AdapterResult(
            caption=self.caption,
            objects=(),
            ocr_text=None,
            alt_text_draft=self.caption,
            context_sources=(),
            context_applied=False,
        )


class _FailingGpu(_Adapter):
    def describe(self, *, image_bytes: bytes, context: dict[str, Any] | None) -> AdapterResult:
        self.calls += 1
        raise RuntimeError("gpu cold")


async def _create_run(sf, *, tenant_id: uuid.UUID, media_id: int = 7, image_bytes: bytes = b"image") -> uuid.UUID:
    async with sf() as s:
        repo = DescribeRunRepository(s)
        run_id = await repo.create_single_run(
            tenant_id=tenant_id,
            media_id=media_id,
            image_bytes=image_bytes,
            image_content_type="image/jpeg",
        )
        await s.commit()
    return run_id


async def _load_item(sf, *, tenant_id: uuid.UUID, run_id: uuid.UUID):
    async with sf() as s:
        return await DescribeRunRepository(s).get_single_run_item(tenant_id=tenant_id, run_id=run_id)


async def _count_cache_rows(sf, *, tenant_id: uuid.UUID) -> int:
    async with sf() as s:
        result = await s.execute(select(ImageDescription).where(ImageDescription.tenant_id == tenant_id))
        return len(list(result.scalars().all()))


def test_worker_module_importable():
    """RED baseline: module must exist for Slice 2."""
    from scene.application.describe_async_worker import run_async_describe_job  # noqa: F401


def test_worker_records_cpu_provisional_then_gpu_final():
    """Supersede ordering: tier + result_generation 1→2; envelope keys; FINAL cached."""

    async def body() -> None:
        from scene.application.describe_async_worker import run_async_describe_job

        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        run_id = await _create_run(sf, tenant_id=tenant, media_id=7, image_bytes=b"image")

        audit = MagicMock(spec=["record"])
        audit.record = AsyncMock()
        metrics = MagicMock(spec=["record_request", "observe_adapter_duration"])

        await run_async_describe_job(
            tenant_id=tenant,
            run_id=run_id,
            session_factory=sf,
            cpu_adapter=_Adapter(kind=DescriptionAdapterKind.LOCAL_CPU, caption="CPU provisional."),
            gpu_adapter=_Adapter(kind=DescriptionAdapterKind.GPU, caption="GPU final."),
            job_timeout_seconds=None,
            audit_sink=audit,
            metrics=metrics,
        )

        item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
        assert item is not None
        assert item.status == DescribeItemStatus.COMPLETED
        assert describe_job_status(item) is DescribeJobStatus.FINAL
        assert item.tier == DescriptionResultTier.FINAL_GPU
        assert item.result_generation == 2
        assert item.visual_facts is not None
        assert item.visual_facts["alt_text_draft"] == "GPU final."
        assert item.visual_facts["tier"] == "final_gpu"
        assert "image_hash" in item.visual_facts
        assert "provider_disclosure" in item.visual_facts
        jsonschema.validate(item.visual_facts, _schema())
        assert item.image_bytes is None

        assert await _count_cache_rows(sf, tenant_id=tenant) == 1

        assert audit.record.await_count == 2
        assert metrics.record_request.call_count == 2
        assert metrics.observe_adapter_duration.call_count == 2

        await engine.dispose()

    asyncio.run(body())


def test_worker_keeps_cpu_provisional_when_gpu_fails():
    """Degraded preserves provisional visual_facts; provisional/degraded never cached."""

    async def body() -> None:
        from scene.application.describe_async_worker import run_async_describe_job

        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        run_id = await _create_run(sf, tenant_id=tenant, media_id=7, image_bytes=b"image")

        await run_async_describe_job(
            tenant_id=tenant,
            run_id=run_id,
            session_factory=sf,
            cpu_adapter=_Adapter(kind=DescriptionAdapterKind.LOCAL_CPU, caption="CPU provisional."),
            gpu_adapter=_FailingGpu(kind=DescriptionAdapterKind.GPU, caption="never"),
            job_timeout_seconds=None,
            audit_sink=None,
            metrics=None,
        )

        item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
        assert item is not None
        assert describe_job_status(item) is DescribeJobStatus.DEGRADED
        assert item.tier == DescriptionResultTier.PROVISIONAL_CPU
        assert item.result_generation == 1
        assert item.visual_facts is not None
        assert item.visual_facts["alt_text_draft"] == "CPU provisional."
        assert item.visual_facts["tier"] == "provisional_cpu"
        assert item.last_error is not None
        assert "RuntimeError" in item.last_error
        assert item.image_bytes is None
        jsonschema.validate(item.visual_facts, _schema())

        assert await _count_cache_rows(sf, tenant_id=tenant) == 0

        await engine.dispose()

    asyncio.run(body())


def test_worker_timeout_marks_failed_exactly_once():
    """wait_for cancel may mark FAILED via CancelledError; outer guard must not double-write."""

    async def body() -> None:
        from scene.application.describe_async_worker import run_async_describe_job

        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        run_id = await _create_run(sf, tenant_id=tenant, media_id=7, image_bytes=b"image")

        await run_async_describe_job(
            tenant_id=tenant,
            run_id=run_id,
            session_factory=sf,
            cpu_adapter=_Adapter(kind=DescriptionAdapterKind.LOCAL_CPU, caption="slow", delay_s=2.0),
            gpu_adapter=_Adapter(kind=DescriptionAdapterKind.GPU, caption="never"),
            job_timeout_seconds=0.05,
            audit_sink=None,
            metrics=None,
        )

        item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
        assert item is not None
        assert item.status == DescribeItemStatus.FAILED
        assert describe_job_status(item) is DescribeJobStatus.FAILED
        assert item.last_error is not None
        # Either CancelledError (inner) or TimeoutError (outer guard) — not both stacked.
        assert "CancelledError" in item.last_error or "TimeoutError" in item.last_error
        assert item.last_error.count("\n") == 0  # single error string, not concatenated
        assert await _count_cache_rows(sf, tenant_id=tenant) == 0

        await engine.dispose()

    asyncio.run(body())


def test_worker_cancellation_marks_failed_then_re_raises():
    """CancelledError persists FAILED then re-raises for cooperative cancel [CON-03]."""

    async def body() -> None:
        from scene.application.describe_async_worker import run_async_describe_job

        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        run_id = await _create_run(sf, tenant_id=tenant, media_id=7, image_bytes=b"image")

        task = asyncio.create_task(
            run_async_describe_job(
                tenant_id=tenant,
                run_id=run_id,
                session_factory=sf,
                cpu_adapter=_Adapter(kind=DescriptionAdapterKind.LOCAL_CPU, caption="slow", delay_s=5.0),
                gpu_adapter=_Adapter(kind=DescriptionAdapterKind.GPU, caption="never"),
                job_timeout_seconds=None,
                audit_sink=None,
                metrics=None,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
        assert item is not None
        assert item.status == DescribeItemStatus.FAILED
        assert item.last_error is not None
        assert "CancelledError" in item.last_error
        assert await _count_cache_rows(sf, tenant_id=tenant) == 0

        await engine.dispose()

    asyncio.run(body())


def test_cpu_failure_before_provisional_marks_failed_not_cached():
    """Exception before provisional → failed; no image_descriptions row."""

    class _FailingCpu(_Adapter):
        def describe(self, *, image_bytes: bytes, context: dict[str, Any] | None) -> AdapterResult:
            raise RuntimeError("cpu boom")

    async def body() -> None:
        from scene.application.describe_async_worker import run_async_describe_job

        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        run_id = await _create_run(sf, tenant_id=tenant, media_id=8, image_bytes=b"y")

        await run_async_describe_job(
            tenant_id=tenant,
            run_id=run_id,
            session_factory=sf,
            cpu_adapter=_FailingCpu(kind=DescriptionAdapterKind.LOCAL_CPU, caption="x"),
            gpu_adapter=_Adapter(kind=DescriptionAdapterKind.GPU, caption="never"),
            job_timeout_seconds=None,
            audit_sink=None,
            metrics=None,
        )

        item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
        assert item is not None
        assert item.status == DescribeItemStatus.FAILED
        assert "cpu boom" in (item.last_error or "")
        assert item.visual_facts is None
        assert await _count_cache_rows(sf, tenant_id=tenant) == 0

        await engine.dispose()

    asyncio.run(body())
