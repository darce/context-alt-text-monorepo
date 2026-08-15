"""VLM-5 Slice 2: DB-backed supersede worker (run_async_describe_job).

Provisional→final, degraded-on-GPU-failure, timeout once, cancellation re-raise,
FINAL cache write-through only [TEST-13], [DATA-14], [CON-03].
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import uuid
import weakref
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import jsonschema
import pytest
from sqlalchemy import Table, event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

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
    # File-backed + StaticPool: the file keeps the schema when a cancelled
    # aiosqlite query invalidates the connection (s1). StaticPool is one
    # live checkout so the UDF and sequential sessions share a connection
    # (GATEFLAKE-R1-03). It does NOT close the R1-01 lock window: cancel
    # mid-write invalidates that connection, the dying aiosqlite worker
    # still holds the file lock, and the replacement cannot persist
    # FAILED (measured; busy_timeout self-deadlocks). See the timeout
    # and cancel tests (REF-25).
    tmpdir = tempfile.TemporaryDirectory(prefix="acx-describe-async-")
    path = os.path.join(tmpdir.name, "test.db")
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        poolclass=StaticPool,
    )

    def _cleanup(_eng: object = None) -> None:
        tmpdir.cleanup()

    event.listen(engine.sync_engine, "engine_disposed", _cleanup)
    weakref.finalize(engine, _cleanup)
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


def test_sessionmaker_survives_cancelled_in_flight_query():
    """Discrimination guard [TEST-08][TEST-07][DBG-01]: cancel mid-query must not drop schema.

    StaticPool + :memory: is one connection === the database. Cancelling an
    in-flight aiosqlite await invalidates that connection, StaticPool closes
    it, and the schema is gone. File-backed SQLite keeps the file. StaticPool
    on that file URL is still one connection, so the UDF registered below is
    the same checkout ``sf()`` uses (GATEFLAKE-R1-03). This test does not
    depend on worker timing.
    """

    async def body() -> None:
        engine, sf = await _sessionmaker()
        try:
            tenant = uuid.uuid4()
            run_id = await _create_run(sf, tenant_id=tenant, media_id=7, image_bytes=b"image")

            started = asyncio.Event()
            loop = asyncio.get_running_loop()

            def _sleep_and_signal(ms: object) -> int:
                loop.call_soon_threadsafe(started.set)
                time.sleep(float(ms) / 1000.0)
                return 1

            async with engine.connect() as conn:
                adapt = conn.sync_connection.connection.dbapi_connection
                aiosqlite_conn = adapt._connection
                await aiosqlite_conn.create_function("sleep_ms", 1, _sleep_and_signal)

            async def _in_flight() -> None:
                async with sf() as session:
                    await session.execute(text("SELECT sleep_ms(800)"))

            task = asyncio.create_task(_in_flight())
            try:
                await asyncio.wait_for(started.wait(), timeout=3.0)
            except TimeoutError as exc:
                raise TimeoutError(
                    "sleep_ms UDF never started; UDF is registered on one "
                    "aiosqlite connection and this session may have checked "
                    "out a different one"
                ) from exc
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
            assert item is not None
            assert item.media_id == 7
        finally:
            await engine.dispose()

    asyncio.run(body())


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


def test_worker_timeout_marks_failed_exactly_once(monkeypatch: pytest.MonkeyPatch):
    """wait_for cancel may mark FAILED via CancelledError; outer guard must not double-write.

    VLM5-F2B-BR-03: a spy on mark_item counts actual non-terminal→FAILED
    transitions, so a second write that REPLACES the error string (instead of
    concatenating) is detected directly — not inferred from string shape.
    """

    async def body() -> None:
        from scene.application.describe_async_worker import run_async_describe_job
        from scene.domain.describe_run import TERMINAL_ITEM_STATUSES

        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        run_id = await _create_run(sf, tenant_id=tenant, media_id=7, image_bytes=b"image")

        failed_writes: list[str | None] = []
        orig_mark_item = DescribeRunRepository.mark_item

        async def spy_mark_item(self, *, tenant_id, run_id, media_id, status, error_message=None, now=None):
            item = await self._get_item(tenant_id=tenant_id, run_id=run_id, media_id=media_id)
            was_terminal = item is not None and DescribeItemStatus(item.status) in TERMINAL_ITEM_STATUSES
            result = await orig_mark_item(
                self,
                tenant_id=tenant_id,
                run_id=run_id,
                media_id=media_id,
                status=status,
                error_message=error_message,
                now=now,
            )
            if status is DescribeItemStatus.FAILED and result and not was_terminal:
                failed_writes.append(error_message)
            return result

        monkeypatch.setattr(DescribeRunRepository, "mark_item", spy_mark_item)

        await run_async_describe_job(
            tenant_id=tenant,
            run_id=run_id,
            session_factory=sf,
            cpu_adapter=_Adapter(kind=DescriptionAdapterKind.LOCAL_CPU, caption="slow", delay_s=2.0),
            gpu_adapter=_Adapter(kind=DescriptionAdapterKind.GPU, caption="never"),
            # FALLBACK (REF-25 / GATEFLAKE-R1-01): 0.05 fires inside
            # phase-1 mark_item(RUNNING). The cancelled aiosqlite
            # connection still holds the SQLite write lock; StaticPool
            # replacement then fails _mark_terminal with database is
            # locked (23/25 and 8/10 under 6 CPU burners; busy_timeout
            # self-deadlocks because the holder is the dying checkout).
            # 0.5 lets phase-1 commit before wait_for cancels, so
            # cleanup is not fighting a live writer. Production is
            # Postgres. Do not silently retune this.
            job_timeout_seconds=0.5,
            audit_sink=None,
            metrics=None,
        )

        item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
        assert item is not None
        assert item.status == DescribeItemStatus.FAILED
        assert describe_job_status(item) is DescribeJobStatus.FAILED
        # Exactly one persisted FAILED transition — a replace-style double write
        # would append a second entry here regardless of the final string shape.
        assert len(failed_writes) == 1
        assert item.last_error == failed_writes[0]
        assert item.last_error is not None
        assert item.last_error.startswith("TimeoutError: job exceeded") or item.last_error == (
            "CancelledError: job cancelled"
        )
        assert await _count_cache_rows(sf, tenant_id=tenant) == 0

        await engine.dispose()

    asyncio.run(body())


def test_worker_timeout_after_provisional_projects_degraded():
    """VLM5-F1A-BR-02: cancel/timeout AFTER a committed provisional projects degraded.

    Same contract as the GPU-exception and restart-reclaim paths: the provisional
    envelope stays pollable, status COMPLETED + last_error (degraded), not FAILED.
    """

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
            gpu_adapter=_Adapter(kind=DescriptionAdapterKind.GPU, caption="never", delay_s=2.0),
            job_timeout_seconds=0.3,
            audit_sink=None,
            metrics=None,
        )

        item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
        assert item is not None
        assert item.status == DescribeItemStatus.COMPLETED
        assert describe_job_status(item) is DescribeJobStatus.DEGRADED
        assert item.tier == DescriptionResultTier.PROVISIONAL_CPU
        assert item.visual_facts is not None
        assert item.visual_facts["alt_text_draft"] == "CPU provisional."
        assert item.last_error is not None
        assert item.last_error.startswith(("TimeoutError: job exceeded", "CancelledError:"))
        assert await _count_cache_rows(sf, tenant_id=tenant) == 0

        await engine.dispose()

    asyncio.run(body())


def test_final_phase_item_final_and_cache_insert_share_one_session(monkeypatch: pytest.MonkeyPatch):
    """VLM5-F2B-BR-01 [DATA-14]: structural proof of same-session (same-commit) coupling.

    Session-identity spies fail if the final item write and the cache insert are
    ever split into separate sessions/commits — the decoupling the fault-injection
    test alone cannot observe.
    """

    async def body() -> None:
        from scene.application.describe_async_worker import run_async_describe_job
        from scene.application.description_repository import ImageDescriptionRepository

        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        run_id = await _create_run(sf, tenant_id=tenant, media_id=7, image_bytes=b"image")

        seen: dict[str, object] = {}
        orig_final = DescribeRunRepository.set_item_final
        orig_insert = ImageDescriptionRepository.insert_or_get_existing

        async def spy_final(self, **kwargs):
            seen["final_session"] = self._session
            return await orig_final(self, **kwargs)

        async def spy_insert(self, record):
            seen["cache_session"] = self._session
            return await orig_insert(self, record)

        monkeypatch.setattr(DescribeRunRepository, "set_item_final", spy_final)
        monkeypatch.setattr(ImageDescriptionRepository, "insert_or_get_existing", spy_insert)

        await run_async_describe_job(
            tenant_id=tenant,
            run_id=run_id,
            session_factory=sf,
            cpu_adapter=_Adapter(kind=DescriptionAdapterKind.LOCAL_CPU, caption="CPU provisional."),
            gpu_adapter=_Adapter(kind=DescriptionAdapterKind.GPU, caption="GPU final."),
            job_timeout_seconds=None,
            audit_sink=None,
            metrics=None,
        )

        assert "final_session" in seen and "cache_session" in seen
        assert seen["final_session"] is seen["cache_session"], (
            "item-final and cache insert must share one session/commit [DATA-14]"
        )
        item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
        assert item is not None
        assert item.tier == DescriptionResultTier.FINAL_GPU
        assert await _count_cache_rows(sf, tenant_id=tenant) == 1

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
        # FALLBACK (REF-25 / GATEFLAKE-R1-02): sleep(0.05) lands inside
        # phase-1's RUNNING write under load. Same lock race as the
        # timeout test — dying aiosqlite holds the file lock, cleanup
        # cannot persist FAILED. Wait for the committed RUNNING row
        # so cancel is after that write, not a magic longer sleep.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            started_item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
            if started_item is not None and started_item.status == DescribeItemStatus.RUNNING:
                break
            await asyncio.sleep(0.01)
        else:
            raise TimeoutError(
                "phase-1 RUNNING never committed before cancel; "
                "refusing to cancel mid-write (GATEFLAKE-R1-01 lock race)"
            )
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


def test_final_phase_commit_failure_rolls_back_cache_and_item_final():
    """VLM5-S2A-BR-05 [DATA-14]: commit fail after set_item_final+cache insert rolls both back.

    Same-session coupling must mean a crash pre-commit loses the FINAL item write
    and the image_descriptions row together — zero cache rows, item not FINAL.
    """

    async def body() -> None:
        from scene.application.describe_async_worker import run_async_describe_job

        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        run_id = await _create_run(sf, tenant_id=tenant, media_id=7, image_bytes=b"image")

        # Commits: (1) mark RUNNING (2) provisional (3) final+cache — fail only #3.
        commit_n = {"n": 0}
        real_factory = sf

        def counting_factory():
            session_cm = real_factory()

            class _Wrapped:
                async def __aenter__(self):
                    self._session = await session_cm.__aenter__()
                    original_commit = self._session.commit

                    async def counted_commit():
                        commit_n["n"] += 1
                        # Fail only the final-phase commit (3rd); allow degraded cleanup after.
                        if commit_n["n"] == 3:
                            raise RuntimeError("final commit boom")
                        return await original_commit()

                    self._session.commit = counted_commit  # type: ignore[method-assign]
                    return self._session

                async def __aexit__(self, *exc):
                    return await session_cm.__aexit__(*exc)

            return _Wrapped()

        await run_async_describe_job(
            tenant_id=tenant,
            run_id=run_id,
            session_factory=counting_factory,
            cpu_adapter=_Adapter(kind=DescriptionAdapterKind.LOCAL_CPU, caption="CPU provisional."),
            gpu_adapter=_Adapter(kind=DescriptionAdapterKind.GPU, caption="GPU final."),
            job_timeout_seconds=None,
            audit_sink=None,
            metrics=None,
        )

        item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
        assert item is not None
        # Outer exception handler marks degraded (provisional was committed).
        assert describe_job_status(item) is not DescribeJobStatus.FINAL
        assert item.tier != DescriptionResultTier.FINAL_GPU
        assert await _count_cache_rows(sf, tenant_id=tenant) == 0
        assert commit_n["n"] >= 3

        await engine.dispose()

    asyncio.run(body())


def test_worker_bails_on_already_terminal_failed_and_completed():
    """VLM5-S2A-BR-05: re-entry on terminal items never runs adapters or cache writes.

    mark_item(...RUNNING) returns False for FAILED and COMPLETED; worker must bail
    before adapters (F1 terminal guard) with zero new image_descriptions rows.
    """

    async def body() -> None:
        from scene.application.describe_async_worker import run_async_describe_job

        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()

        # --- FAILED terminal re-entry ---
        fail_id = await _create_run(sf, tenant_id=tenant, media_id=8, image_bytes=b"fail-img")
        async with sf() as s:
            repo = DescribeRunRepository(s)
            await repo.set_item_failed(tenant_id=tenant, run_id=fail_id, media_id=8, error="already failed")
            await s.commit()

        cpu_fail = _Adapter(kind=DescriptionAdapterKind.LOCAL_CPU, caption="should-not-run")
        gpu_fail = _Adapter(kind=DescriptionAdapterKind.GPU, caption="should-not-run")
        await run_async_describe_job(
            tenant_id=tenant,
            run_id=fail_id,
            session_factory=sf,
            cpu_adapter=cpu_fail,
            gpu_adapter=gpu_fail,
            job_timeout_seconds=None,
            audit_sink=None,
            metrics=None,
        )
        item = await _load_item(sf, tenant_id=tenant, run_id=fail_id)
        assert item is not None
        assert item.status == DescribeItemStatus.FAILED
        assert item.last_error == "already failed"
        assert cpu_fail.calls == 0 and gpu_fail.calls == 0
        assert await _count_cache_rows(sf, tenant_id=tenant) == 0

        # --- COMPLETED (FINAL) terminal re-entry ---
        done_id = await _create_run(sf, tenant_id=tenant, media_id=9, image_bytes=b"done-img")
        async with sf() as s:
            repo = DescribeRunRepository(s)
            await repo.mark_item(
                tenant_id=tenant,
                run_id=done_id,
                media_id=9,
                status=DescribeItemStatus.RUNNING,
            )
            await repo.set_item_final(
                tenant_id=tenant,
                run_id=done_id,
                media_id=9,
                visual_facts={
                    "tier": "final_gpu",
                    "alt_text_draft": "already final",
                    "caption": "c",
                },
            )
            await s.commit()

        cpu_done = _Adapter(kind=DescriptionAdapterKind.LOCAL_CPU, caption="should-not-run")
        gpu_done = _Adapter(kind=DescriptionAdapterKind.GPU, caption="should-not-run")
        await run_async_describe_job(
            tenant_id=tenant,
            run_id=done_id,
            session_factory=sf,
            cpu_adapter=cpu_done,
            gpu_adapter=gpu_done,
            job_timeout_seconds=None,
            audit_sink=None,
            metrics=None,
        )
        item = await _load_item(sf, tenant_id=tenant, run_id=done_id)
        assert item is not None
        assert item.status == DescribeItemStatus.COMPLETED
        assert item.tier == DescriptionResultTier.FINAL_GPU
        assert item.visual_facts is not None
        assert item.visual_facts["alt_text_draft"] == "already final"
        assert cpu_done.calls == 0 and gpu_done.calls == 0
        # No cache row was present and re-entry must not invent one.
        assert await _count_cache_rows(sf, tenant_id=tenant) == 0

        await engine.dispose()

    asyncio.run(body())
