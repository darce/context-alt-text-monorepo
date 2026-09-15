"""WBUX-6 D2: warming is a stored sub-phase of RUNNING around the GPU gate."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from jsonschema import Draft7Validator, FormatChecker
from referencing import Registry, Resource
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import DescribeOperation, DescribeStartup
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import DescribeItemOutcome, run_describe_job
from scene.application.gpu_state import GpuState
from scene.domain.describe_run import (
    DescribeItemStatus,
    DescribeRunPhase,
    DescribeRunStatus,
    elapsed_ms,
)
from scene.interface_adapters.http.schemas.responses import DescribeRunResponse
from scene.tests.test_describe_run_worker import TENANT_ID, _make_db_async

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gpuflow-run-items.json"
_SCHEMA = (
    Path(__file__).resolve().parents[4] / "packages" / "shared-contracts" / "schemas" / "scene-describe-run.schema.json"
)


def _phase_enum_from_response_schema() -> set[str]:
    schema = DescribeRunResponse.model_json_schema()
    phase = schema["properties"]["phase"]
    if "enum" in phase:
        return set(phase["enum"])
    ref = str(phase.get("$ref", ""))
    name = ref.rsplit("/", 1)[-1]
    defs = schema.get("$defs") or schema.get("definitions") or {}
    return set(defs[name]["enum"])


def test_describe_run_phase_enum_and_response_schema_include_warming():
    assert DescribeRunPhase.WARMING == "warming"
    assert "warming" in {member.value for member in DescribeRunPhase}
    assert "warming" in _phase_enum_from_response_schema()
    payload = DescribeRunResponse(
        tenant_id=str(TENANT_ID),
        run_id=str(uuid.uuid4()),
        status=DescribeRunStatus.RUNNING,
        phase=DescribeRunPhase.WARMING,
        completed=0,
        failed=0,
        skipped=0,
        total=1,
        cancel_requested=False,
        eta_seconds=None,
        gpu_state=GpuState.UNKNOWN,
    )
    assert payload.phase == "warming"


def test_gpu_policy_run_reports_warming_while_health_poll_pending_then_describing(monkeypatch):
    import scene.application.describe_run_worker as wmod

    entered = asyncio.Event()
    release = asyncio.Event()

    async def gated_ready(**kwargs):
        entered.set()
        await release.wait()

    monkeypatch.setattr(wmod, "_wait_for_gpu_ready", gated_ready)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            await s.commit()

        phases_during_describe: list[str] = []

        async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
            async with sf() as s:
                run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
            assert run is not None
            phases_during_describe.append(str(run.phase))
            return DescribeItemOutcome(alt_text_draft="ok")

        policy = wmod.GpuRunPolicy(endpoint_url="http://gpu.internal:8000", api_key=None, warmup_timeout_seconds=10)
        job = asyncio.create_task(
            run_describe_job(
                tenant_id=TENANT_ID,
                run_id=run_id,
                session_factory=sf,
                describe_one=describe_one,
                timeout_seconds=1.0,
                gpu_policy=policy,
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=5)
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.phase == DescribeRunPhase.WARMING
        assert run.status == DescribeRunStatus.RUNNING
        release.set()
        await asyncio.wait_for(job, timeout=5)
        assert phases_during_describe == [DescribeRunPhase.DESCRIBING]
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.phase == DescribeRunPhase.COMPLETE
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_seeded_run_without_gpu_policy_never_reports_warming(monkeypatch):
    import scene.application.describe_run_worker as wmod

    async def forbidden(**kwargs):
        raise AssertionError("gpu wait must not run without gpu_policy")

    monkeypatch.setattr(wmod, "_wait_for_gpu_ready", forbidden)

    persisted: list[str] = []
    original_persist = wmod._persist_run_phase

    async def spy_persist(**kwargs):
        persisted.append(str(kwargs["phase"]))
        return await original_persist(**kwargs)

    monkeypatch.setattr(wmod, "_persist_run_phase", spy_persist)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            await s.commit()

        seen: list[str] = []

        async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
            async with sf() as s:
                run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
            assert run is not None
            seen.append(str(run.phase))
            return DescribeItemOutcome(alt_text_draft="ok")

        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=1.0,
        )
        assert DescribeRunPhase.WARMING not in persisted
        assert "warming" not in persisted
        assert "warming" not in seen
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert str(run.phase) != "warming"
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_cancel_during_warming_still_marks_run_cancelled(monkeypatch):
    import scene.application.describe_run_worker as wmod

    entered = asyncio.Event()
    release = asyncio.Event()

    class _FakeHealthResponse:
        status_code = 503

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return _FakeHealthResponse()

    async def gated_sleep(_seconds):
        entered.set()
        await release.wait()

    monkeypatch.setattr(wmod.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(wmod.asyncio, "sleep", gated_sleep)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            await s.commit()

        policy = wmod.GpuRunPolicy(endpoint_url="http://gpu.internal:8000", api_key=None, warmup_timeout_seconds=10)
        job = asyncio.create_task(
            run_describe_job(
                tenant_id=TENANT_ID,
                run_id=run_id,
                session_factory=sf,
                describe_one=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("describe must not run")),
                timeout_seconds=1.0,
                gpu_policy=policy,
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=5)
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
            assert run is not None
            run.cancel_requested = True
            await s.commit()
        release.set()
        await asyncio.wait_for(job, timeout=5)
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.status == DescribeRunStatus.CANCELLED
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_gpuflow_run_items_fixture_matches_shared_schema():
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    registry = Registry().with_resources([(schema["$id"], Resource.from_contents(schema))])
    Draft7Validator(schema, format_checker=FormatChecker(), registry=registry).validate(fixture["run"])
    Draft7Validator(
        {"$ref": schema["$id"] + "#/definitions/items"},
        format_checker=FormatChecker(),
        registry=registry,
    ).validate(fixture["items"])
    assert fixture["run"]["timing"]["ramp_up_ms"] == 0
    assert fixture["run"]["startup_id"] is None
    assert fixture["items"]["items"][2]["processing_ms"] is None


def test_seeded_run_records_queue_once_and_zero_warm_ramp_up(monkeypatch):
    import scene.application.describe_run_worker as wmod

    monkeypatch.setattr(wmod, "_wait_for_gpu_ready", lambda **kwargs: (_ for _ in ()).throw(AssertionError("warm")))

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1, 2], images={1: (b"x", "image/png"), 2: (b"y", "image/png")}
            )
            await s.commit()

        async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
            if media_id == 1:
                return DescribeItemOutcome(alt_text_draft="ok", processing_ms=12.5)
            exc = RuntimeError("adapter boom")
            exc.processing_ms = 30
            raise exc

        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=1.0,
        )
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.queue_ms is not None and run.queue_ms >= 0
        assert run.ramp_up_ms == 0
        assert run.startup_id is None
        assert run.startup_ms is None
        assert run.operation_id
        assert run.items_timed == 2
        assert run.processing_ms_p50 == 21.25
        assert run.processing_ms_max == 30
        by_media = {item.media_id: item for item in items}
        assert by_media[1].processing_ms == 12.5
        assert by_media[1].status == DescribeItemStatus.COMPLETED
        assert by_media[2].processing_ms == 30
        assert by_media[2].status == DescribeItemStatus.FAILED
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


async def _ensure_startup_table(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=cast(list[Table], [DescribeStartup.__table__, DescribeOperation.__table__]),
        )


def _operation(
    *,
    operation_id: str,
    startup_id: str,
    accepted_at: datetime,
    retain_until: datetime,
) -> DescribeOperation:
    return DescribeOperation(
        tenant_id=TENANT_ID,
        operation_id=operation_id,
        request_digest="ab" * 32,
        accepted_at=accepted_at,
        expires_at=accepted_at + timedelta(minutes=30),
        retain_until=retain_until,
        startup_id=startup_id,
    )


def test_gpu_wait_records_cold_ramp_up_after_pickup(monkeypatch):
    import scene.application.describe_run_worker as wmod

    async def delayed_ready(**kwargs):
        await asyncio.sleep(0.01)
        return False

    monkeypatch.setattr(wmod, "_wait_for_gpu_ready", delayed_ready)
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    first_ready_at = started_at + timedelta(seconds=12)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        await _ensure_startup_table(engine)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        retain_until = datetime.now(UTC) + timedelta(hours=1)
        newer_started = started_at + timedelta(seconds=60)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            s.add(
                DescribeStartup(
                    startup_id="older-boot",
                    started_at=started_at,
                    first_ready_at=first_ready_at,
                    retain_until=retain_until,
                )
            )
            s.add(
                DescribeStartup(
                    startup_id="newer-boot",
                    started_at=newer_started,
                    first_ready_at=newer_started + timedelta(seconds=3),
                    retain_until=retain_until,
                )
            )
            s.add(
                _operation(
                    operation_id="op-older",
                    startup_id="older-boot",
                    accepted_at=started_at,
                    retain_until=retain_until,
                )
            )
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
            assert run is not None
            run.operation_id = "op-older"
            await s.commit()

        async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
            return DescribeItemOutcome(alt_text_draft="ok", processing_ms=8)

        policy = wmod.GpuRunPolicy(endpoint_url="http://gpu.internal:8000", api_key=None, warmup_timeout_seconds=10)
        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=1.0,
            gpu_policy=policy,
        )
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.queue_ms is not None
        assert run.ramp_up_ms is not None and run.ramp_up_ms >= 0
        assert run.startup_id == "older-boot"
        assert run.startup_ms == elapsed_ms(started_at, first_ready_at)
        assert run.startup_ms != run.ramp_up_ms
        assert run.items_timed == 1
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_cold_gpu_wait_without_startup_observation_leaves_ids_null(monkeypatch):
    import scene.application.describe_run_worker as wmod

    async def delayed_ready(**kwargs):
        await asyncio.sleep(0.01)
        return False

    monkeypatch.setattr(wmod, "_wait_for_gpu_ready", delayed_ready)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            await s.commit()

        policy = wmod.GpuRunPolicy(endpoint_url="http://gpu.internal:8000", api_key=None, warmup_timeout_seconds=10)
        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=lambda *_a, **_k: DescribeItemOutcome(alt_text_draft="ok", processing_ms=8),
            timeout_seconds=1.0,
            gpu_policy=policy,
        )
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.startup_id is None
        assert run.startup_ms is None
        assert run.ramp_up_ms is not None and run.ramp_up_ms > 0
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_immediate_gpu_ready_is_warm_and_has_no_startup(monkeypatch):
    import scene.application.describe_run_worker as wmod

    async def already_ready(**kwargs):
        return True

    monkeypatch.setattr(wmod, "_wait_for_gpu_ready", already_ready)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            await s.commit()

        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=lambda *_a, **_k: DescribeItemOutcome(alt_text_draft="ok", processing_ms=0),
            timeout_seconds=1.0,
            gpu_policy=wmod.GpuRunPolicy(
                endpoint_url="http://gpu.internal:8000", api_key=None, warmup_timeout_seconds=10
            ),
        )
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.ramp_up_ms == 0
        assert run.startup_id is None
        assert run.startup_ms is None
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_worker_publishes_demand_snapshot_without_stop_flags(monkeypatch):
    import scene.application.describe_run_worker as wmod

    calls: list[dict] = []

    async def fake_load(session, **kwargs):
        calls.append(kwargs)
        return {"queue_depth": 0, "in_flight": 0, "written_at": 1.0, "revision": 1}

    written: list[tuple] = []

    def fake_write(payload, path):
        written.append((payload, str(path)))

    monkeypatch.setattr(wmod, "load_snapshot", fake_load)
    monkeypatch.setattr(wmod, "write_load_snapshot", fake_write)
    monkeypatch.setattr(wmod, "resolve_load_path", lambda: "/tmp/describe-load.json")

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            await s.commit()
        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=lambda *_a, **_k: DescribeItemOutcome(alt_text_draft="ok"),
            timeout_seconds=1.0,
        )
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())
    assert calls == [{}]
    assert written[0][0]["revision"] == 1


def test_cancel_during_retry_backoff_keeps_measured_attempt_ms(monkeypatch):
    import scene.application.describe_run_worker as wmod

    clock = {"t": 100.0}
    attempt_s = 0.042

    def fake_monotonic() -> float:
        return clock["t"]

    monkeypatch.setattr(wmod.time, "monotonic", fake_monotonic)

    attempts = {"n": 0}

    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
        from scene.application.visual_facts_service import AdapterAttemptTiming

        attempts["n"] += 1
        if attempts["n"] == 1:
            clock["t"] += attempt_s
            exc = httpx.ConnectError("transient")
            exc.attempt_timing = AdapterAttemptTiming(entered_adapter=True)
            raise exc
        raise AssertionError("retry must not dispatch after cancel")

    async def already_ready(**kwargs):
        return True

    monkeypatch.setattr(wmod, "_wait_for_gpu_ready", already_ready)
    state = {"cancel": False}
    original_get_run = DescribeRunRepository.get_run

    async def patched_get_run(self, *, tenant_id, run_id):
        run = await original_get_run(self, tenant_id=tenant_id, run_id=run_id)
        if run is not None and state["cancel"] and not run.cancel_requested:
            run.cancel_requested = True
        return run

    monkeypatch.setattr(DescribeRunRepository, "get_run", patched_get_run)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            await s.commit()

        real_sleep = asyncio.sleep

        async def cancel_during_backoff(_delay):
            state["cancel"] = True
            await real_sleep(0)

        monkeypatch.setattr(wmod.asyncio, "sleep", cancel_during_backoff)
        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=1.0,
            gpu_policy=wmod.GpuRunPolicy(
                endpoint_url="http://gpu.internal:8000", api_key=None, warmup_timeout_seconds=10
            ),
        )
        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        assert attempts["n"] == 1
        assert items[0].status == DescribeItemStatus.SKIPPED
        assert items[0].processing_ms == pytest.approx(attempt_s * 1000)
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_three_noop_terminal_transitions_abort_run():
    described: list[int] = []

    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
        described.append(media_id)
        return DescribeItemOutcome(alt_text_draft="ok", processing_ms=1)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_run(
                tenant_id=TENANT_ID,
                media_ids=[1, 2, 3, 4],
                images={1: (b"a", "image/png"), 2: (b"b", "image/png"), 3: (b"c", "image/png"), 4: (b"d", "image/png")},
            )
            for media_id in (1, 2, 3):
                await repo.mark_item(
                    tenant_id=TENANT_ID,
                    run_id=run_id,
                    media_id=media_id,
                    status=DescribeItemStatus.COMPLETED,
                )
            await s.commit()
        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=1.0,
        )
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert described == [1, 2, 3]
        assert run is not None
        assert run.status == DescribeRunStatus.FAILED
        assert run.error_message == "describe run stalled: no item progress"
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_async_adapter_timing_excludes_thread_queue_delay(monkeypatch):
    import scene.application.describe_async_worker as amod
    from scene.application.description_adapter import AdapterResult
    from scene.domain.description import DescriptionAdapterKind

    class InstantAdapter:
        kind = DescriptionAdapterKind.SEEDED
        model_id = "seeded"
        model_version = "1"
        prompt_or_task_version = "1"

        def describe(self, *, image_bytes, context):
            return AdapterResult(
                caption="c",
                objects=(),
                ocr_text=None,
                alt_text_draft="c",
                context_sources=(),
                context_applied=False,
            )

    real_to_thread = asyncio.to_thread

    async def queued_to_thread(func, /, *args, **kwargs):
        await asyncio.sleep(0.05)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(amod.asyncio, "to_thread", queued_to_thread)

    async def body():
        _result, ms = await amod._describe_adapter(InstantAdapter(), image_bytes=b"x", context=None)
        assert ms < 25

    asyncio.run(body())


def test_async_adapter_failure_persists_dispatch_ms_excluding_queue(monkeypatch):
    import scene.application.describe_async_worker as amod
    from scene.domain.description import DescriptionAdapterKind

    class SlowFailAdapter:
        kind = DescriptionAdapterKind.SEEDED
        model_id = "seeded"
        model_version = "1"
        prompt_or_task_version = "1"

        def describe(self, *, image_bytes, context):
            time.sleep(0.03)
            raise RuntimeError("adapter boom")

    class UnusedGpu:
        kind = DescriptionAdapterKind.GPU
        model_id = "gpu"
        model_version = "1"
        prompt_or_task_version = "1"

        def describe(self, *, image_bytes, context):
            raise AssertionError("gpu must not run after cpu failure")

    real_to_thread = asyncio.to_thread

    async def queued_to_thread(func, /, *args, **kwargs):
        await asyncio.sleep(0.05)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(amod.asyncio, "to_thread", queued_to_thread)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_single_run(
                tenant_id=TENANT_ID, media_id=7, image_bytes=b"image"
            )
            await s.commit()
        await amod.run_async_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            cpu_adapter=SlowFailAdapter(),
            gpu_adapter=UnusedGpu(),
        )
        async with sf() as s:
            item = await DescribeRunRepository(s).get_single_run_item(tenant_id=TENANT_ID, run_id=run_id)
        assert item is not None
        assert item.status == DescribeItemStatus.FAILED
        assert item.processing_ms is not None
        assert 20 <= item.processing_ms < 70
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_warm_retry_keeps_retained_first_ramp_up():
    import scene.application.describe_run_worker as wmod

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            await s.commit()
        await wmod._record_run_pickup(session_factory=sf, tenant_id=TENANT_ID, run_id=run_id)
        await asyncio.sleep(0.02)
        await wmod._record_run_readiness(session_factory=sf, tenant_id=TENANT_ID, run_id=run_id, cold=True)
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        first_ramp = run.ramp_up_ms
        assert first_ramp is not None and first_ramp > 0
        await asyncio.sleep(0.02)
        await wmod._record_run_readiness(session_factory=sf, tenant_id=TENANT_ID, run_id=run_id, cold=False)
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.ramp_up_ms == first_ramp
        assert run.startup_id is None
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_pre_dispatch_failure_leaves_processing_ms_null():
    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
        raise RuntimeError("quota exceeded")

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            await s.commit()
        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=1.0,
        )
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert items[0].status == DescribeItemStatus.FAILED
        assert items[0].processing_ms is None
        assert run.items_timed == 0
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_readiness_uses_startup_associated_between_lookup_and_write(monkeypatch):
    import scene.application.describe_run_worker as wmod

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        await _ensure_startup_table(engine)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        started_at = datetime(2026, 1, 1, tzinfo=UTC)
        first_ready_at = started_at + timedelta(seconds=5)
        retain_until = datetime.now(UTC) + timedelta(hours=1)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            s.add(
                DescribeStartup(
                    startup_id="raced-boot",
                    started_at=started_at,
                    first_ready_at=first_ready_at,
                    retain_until=retain_until,
                )
            )
            s.add(
                DescribeOperation(
                    tenant_id=TENANT_ID,
                    operation_id="op-race",
                    request_digest="ab" * 32,
                    accepted_at=started_at,
                    expires_at=started_at + timedelta(minutes=30),
                    retain_until=retain_until,
                    startup_id=None,
                )
            )
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
            assert run is not None
            run.operation_id = "op-race"
            await s.commit()

        calls = {"n": 0}
        original = wmod._observed_startup

        async def spy(session, *, tenant_id, operation_id, for_update=False):
            calls["n"] += 1
            if calls["n"] == 1:
                op = await session.scalar(
                    select(DescribeOperation).where(
                        DescribeOperation.tenant_id == TENANT_ID,
                        DescribeOperation.operation_id == operation_id,
                    )
                )
                assert op is not None
                op.startup_id = "raced-boot"
                return None, None
            return await original(session, tenant_id=tenant_id, operation_id=operation_id, for_update=for_update)

        monkeypatch.setattr(wmod, "_observed_startup", spy)
        await wmod._record_run_pickup(session_factory=sf, tenant_id=TENANT_ID, run_id=run_id)
        await wmod._record_run_readiness(session_factory=sf, tenant_id=TENANT_ID, run_id=run_id, cold=True)
        assert calls["n"] >= 2
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.startup_id == "raced-boot"
        assert run.startup_ms == elapsed_ms(started_at, first_ready_at)
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_later_readiness_repairs_null_startup_id():
    import scene.application.describe_run_worker as wmod

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        await _ensure_startup_table(engine)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            await s.commit()
        await wmod._record_run_pickup(session_factory=sf, tenant_id=TENANT_ID, run_id=run_id)
        await asyncio.sleep(0.02)
        await wmod._record_run_readiness(session_factory=sf, tenant_id=TENANT_ID, run_id=run_id, cold=True)
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.startup_id is None
        first_ramp = run.ramp_up_ms
        assert first_ramp is not None and first_ramp > 0

        started_at = datetime(2026, 1, 1, tzinfo=UTC)
        first_ready_at = started_at + timedelta(seconds=9)
        retain_until = datetime.now(UTC) + timedelta(hours=1)
        async with sf() as s:
            s.add(
                DescribeStartup(
                    startup_id="late-boot",
                    started_at=started_at,
                    first_ready_at=first_ready_at,
                    retain_until=retain_until,
                )
            )
            s.add(
                _operation(
                    operation_id="op-late",
                    startup_id="late-boot",
                    accepted_at=started_at,
                    retain_until=retain_until,
                )
            )
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
            assert run is not None
            run.operation_id = "op-late"
            await s.commit()

        await wmod._record_run_readiness(session_factory=sf, tenant_id=TENANT_ID, run_id=run_id, cold=False)
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.startup_id == "late-boot"
        assert run.startup_ms == elapsed_ms(started_at, first_ready_at)
        assert run.ramp_up_ms == first_ramp
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())
