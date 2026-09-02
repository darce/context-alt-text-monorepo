"""WBUX-6 D2: warming is a stored sub-phase of RUNNING around the GPU gate."""

from __future__ import annotations

import asyncio
import os
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import DescribeItemOutcome, run_describe_job
from scene.domain.describe_run import DescribeRunPhase, DescribeRunStatus
from scene.interface_adapters.http.schemas.responses import DescribeRunResponse
from scene.tests.test_describe_run_worker import TENANT_ID, _make_db_async


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
        gpu_state=None,
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

        async def describe_one(media_id, image_bytes, content_type):
            async with sf() as s:
                run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
            assert run is not None
            phases_during_describe.append(str(run.phase))
            return DescribeItemOutcome(alt_text_draft="ok")

        policy = wmod.GpuRunPolicy(
            endpoint_url="http://gpu.internal:8000", api_key=None, warmup_timeout_seconds=10
        )
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

        async def describe_one(media_id, image_bytes, content_type):
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

    async def gated_ready(**kwargs):
        entered.set()
        await release.wait()
        raise wmod._RunCancelledError("describe run cancelled while waiting for GPU readiness")

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

        policy = wmod.GpuRunPolicy(
            endpoint_url="http://gpu.internal:8000", api_key=None, warmup_timeout_seconds=10
        )
        job = asyncio.create_task(
            run_describe_job(
                tenant_id=TENANT_ID,
                run_id=run_id,
                session_factory=sf,
                describe_one=lambda *_: (_ for _ in ()).throw(AssertionError("describe must not run")),
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
