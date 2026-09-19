"""Composed contracts for describe-run GPU warm-start behavior (GPUSMOKE-1)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import scene.application.describe_run_worker as wmod
from scene.application.describe_run_repository import DescribeRunRepository
from scene.config.settings import DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS, DescriptionSettings
from scene.domain.describe_run import (
    DescribeItemStatus,
    DescribeJobStatus,
    DescribeRunStatus,
    describe_job_error,
    describe_job_status,
)
from scene.domain.description import DescriptionAdapterKind, DescriptionResultTier
from scene.infrastructure.vlm.unavailable_adapter import UnavailableDescriptionAdapter
from scene.interface_adapters.http.routers.describe_run import _run_response
from scene.interface_adapters.http.schemas.responses import DescribeRunItemResponse
from scene.tests.test_describe_run_worker import TENANT_ID, _make_db_async

HealthHandler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


@pytest.fixture(autouse=True)
def _gpu_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://localhost:8000")
    monkeypatch.setenv("ACX_DESCRIBE_LOAD_PATH", str(tmp_path / "describe-load.json"))
    monkeypatch.setattr(wmod, "_GPU_HEALTH_POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(wmod, "_GPU_ITEM_RETRY_BASE_DELAY_SECONDS", 0)


@asynccontextmanager
async def _database() -> AsyncIterator[tuple[async_sessionmaker, object]]:
    path, url = await _make_db_async()
    engine = create_async_engine(url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False), engine
    finally:
        await engine.dispose()
        os.unlink(path)


async def _create_run(session_factory: async_sessionmaker, media_ids: list[int]):
    async with session_factory() as session:
        run_id = await DescribeRunRepository(session).create_run(
            tenant_id=TENANT_ID,
            media_ids=media_ids,
            images=dict.fromkeys(media_ids, (b"rawbytes", "image/png")),
        )
        await session.commit()
    return run_id


async def _read_run(session_factory: async_sessionmaker, run_id):
    async with session_factory() as session:
        repo = DescribeRunRepository(session)
        run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
        items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)
    return run, items


def _gpu_policy():
    policy = wmod.gpu_run_policy(
        adapter_kind=DescriptionAdapterKind.GPU,
        settings=DescriptionSettings(),
    )
    assert policy is not None
    return policy


def _install_mock_transport(monkeypatch: pytest.MonkeyPatch, handler: HealthHandler) -> None:
    real_async_client = httpx.AsyncClient

    def client_factory(*, timeout):
        return real_async_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(wmod.httpx, "AsyncClient", client_factory)


def _final_outcome(media_id: int) -> wmod.DescribeItemOutcome:
    return wmod.DescribeItemOutcome(
        alt_text_draft=f"alt {media_id}",
        caption=f"caption {media_id}",
        provenance={"adapter": "gpu_qwen30b"},
        tier=DescriptionResultTier.FINAL_GPU,
    )


def _cpu_outcome(media_id: int) -> wmod.DescribeItemOutcome:
    return wmod.DescribeItemOutcome(
        alt_text_draft=f"cpu alt {media_id}",
        caption=f"cpu caption {media_id}",
        provenance={"adapter": "florence_small"},
        tier=DescriptionResultTier.PROVISIONAL_CPU,
    )


def _refusing_health_handler() -> HealthHandler:
    async def health_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("GPU endpoint refused connection", request=request)

    return health_handler


def _warmup_timeout_detail(error_message: str | None) -> dict:
    assert error_message is not None
    return json.loads(error_message)


def test_composed_gpu_warm_start_reaches_final_without_degrading(monkeypatch: pytest.MonkeyPatch) -> None:
    health_events: list[str] = []
    describe_health_counts: list[int] = []

    async def health_handler(request: httpx.Request) -> httpx.Response:
        call = len(health_events) + 1
        health_events.append(str(call))
        if call <= 2:
            raise httpx.ConnectError("GPU is still booting", request=request)
        if call == 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, request=request)

    _install_mock_transport(monkeypatch, health_handler)

    async def body() -> None:
        async with _database() as (session_factory, _engine):
            run_id = await _create_run(session_factory, [1])

            async def describe_one(
                media_id: int,
                image_bytes: bytes | None,
                content_type: str | None,
                *,
                naming_inputs=None,
            ):
                describe_health_counts.append(len(health_events))
                assert image_bytes == b"rawbytes"
                assert content_type == "image/png"
                return _final_outcome(media_id)

            await wmod.run_describe_job(
                tenant_id=TENANT_ID,
                run_id=run_id,
                session_factory=session_factory,
                describe_one=describe_one,
                timeout_seconds=0.5,
                gpu_policy=_gpu_policy(),
            )
            run, items = await _read_run(session_factory, run_id)

        assert len(health_events) >= 4
        assert describe_health_counts == [4]
        assert run is not None
        assert run.status == DescribeRunStatus.COMPLETED
        assert items[0].status == DescribeItemStatus.COMPLETED
        assert items[0].tier == DescriptionResultTier.FINAL_GPU
        projected = describe_job_status(items[0])
        assert projected is DescribeJobStatus.FINAL
        assert projected not in {DescribeJobStatus.DEGRADED, DescribeJobStatus.PROVISIONAL}

    asyncio.run(body())


def test_default_warmup_budget_covers_start_detection_boot_and_read_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep at least one start-timer interval of headroom above measured p95 composition."""
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    try:
        from infra.oci.gpu_lifecycle.reaper import JsonFileJobLoadSource

        from scene.application.describe_load import DEFAULT_LOAD_REFRESH_SECONDS
    finally:
        sys.path.remove(str(repo_root))

    installer = (repo_root / "scripts/deploy/gpu-lifecycle-install.sh").read_text(encoding="utf-8")
    # The installer deliberately uses the unset-only form ${START_INTERVAL-30s}
    # rather than ${START_INTERVAL:-30s}: an explicitly empty START_INTERVAL must
    # reach the timespan validator and fail loudly instead of being silently
    # replaced by the default. Accept either form so this budget coupling keeps
    # measuring the default value, not the substitution operator.
    start_interval_match = re.search(r'^START_INTERVAL="\$\{START_INTERVAL:?-(\d+)s\}"$', installer, re.MULTILINE)
    assert start_interval_match is not None, "installer START_INTERVAL default is missing"
    start_interval = int(start_interval_match.group(1))
    load_max_age = JsonFileJobLoadSource.__dataclass_fields__["max_age_seconds"].default
    evidence_path = repo_root / "docs/tasks/vlm/VLM-3-gpu-spike-2026-07-14-750gb-balanced.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    warm_start_measurement = evidence["measurements"]["warm_start_p95_seconds"]
    assert len(warm_start_measurement["samples"]) >= 3, "warm-start p95 evidence needs at least three samples"
    measured_warm_start_p95 = warm_start_measurement["value"]
    monkeypatch.delenv("ACX_GPU_READ_TIMEOUT_SECONDS", raising=False)
    read_timeout_field = DescriptionSettings.model_fields["gpu_read_timeout_seconds"]
    assert read_timeout_field.default_factory is not None
    configured_read_timeout = read_timeout_field.default_factory()
    composed = (
        start_interval + DEFAULT_LOAD_REFRESH_SECONDS + load_max_age + measured_warm_start_p95 + configured_read_timeout
    )
    headroom = DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS - composed
    budget_terms = (
        f"START_INTERVAL={start_interval} + load_refresh={DEFAULT_LOAD_REFRESH_SECONDS} + "
        f"load_max_age={load_max_age} + "
        f"measured_warm_start_p95={measured_warm_start_p95} from {evidence_path.relative_to(repo_root)} + "
        f"configured_read_timeout={configured_read_timeout} "
        f"= composed={composed}; DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS={DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS}; "
        f"headroom={headroom} must cover START_INTERVAL={start_interval}"
    )
    assert headroom >= start_interval, budget_terms


def test_run_enqueued_during_warmup_completes_without_retries_or_orphans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_health_entered = asyncio.Event()
    both_health_entered = asyncio.Event()
    release_health = asyncio.Event()
    health_calls = 0

    async def health_handler(request: httpx.Request) -> httpx.Response:
        nonlocal health_calls
        health_calls += 1
        first_health_entered.set()
        if health_calls >= 2:
            both_health_entered.set()
        await release_health.wait()
        return httpx.Response(200, request=request)

    _install_mock_transport(monkeypatch, health_handler)

    async def body() -> None:
        async with _database() as (session_factory, _engine):
            first_run_id = await _create_run(session_factory, [11])
            attempts = {11: 0, 22: 0}

            async def describe_one(
                media_id: int,
                _image_bytes: bytes | None,
                _content_type: str | None,
                *,
                naming_inputs=None,
            ):
                attempts[media_id] += 1
                return _final_outcome(media_id)

            baseline_tasks = set(asyncio.all_tasks())
            tracked_tasks: set[asyncio.Task] = set()
            first_task = asyncio.create_task(
                wmod.run_describe_job(
                    tenant_id=TENANT_ID,
                    run_id=first_run_id,
                    session_factory=session_factory,
                    describe_one=describe_one,
                    timeout_seconds=0.5,
                    gpu_policy=_gpu_policy(),
                ),
                name="gpusmoke-first-run",
            )
            tracked_tasks.add(first_task)
            await asyncio.wait_for(first_health_entered.wait(), timeout=0.5)

            second_run_id = await _create_run(session_factory, [22])
            second_task = asyncio.create_task(
                wmod.run_describe_job(
                    tenant_id=TENANT_ID,
                    run_id=second_run_id,
                    session_factory=session_factory,
                    describe_one=describe_one,
                    timeout_seconds=0.5,
                    gpu_policy=_gpu_policy(),
                ),
                name="gpusmoke-second-run",
            )
            tracked_tasks.add(second_task)
            try:
                await asyncio.wait_for(both_health_entered.wait(), timeout=0.5)
                release_health.set()
                await asyncio.gather(*tracked_tasks)
            finally:
                release_health.set()
                for task in tracked_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tracked_tasks, return_exceptions=True)

            first_run, first_items = await _read_run(session_factory, first_run_id)
            second_run, second_items = await _read_run(session_factory, second_run_id)
            await asyncio.sleep(0)
            orphan_tasks = [task for task in asyncio.all_tasks() - baseline_tasks if not task.done()]

        assert first_run is not None and first_run.status == DescribeRunStatus.COMPLETED
        assert second_run is not None and second_run.status == DescribeRunStatus.COMPLETED
        assert [describe_job_status(first_items[0]), describe_job_status(second_items[0])] == [
            DescribeJobStatus.FINAL,
            DescribeJobStatus.FINAL,
        ]
        assert [first_items[0].tier, second_items[0].tier] == [
            DescriptionResultTier.FINAL_GPU,
            DescriptionResultTier.FINAL_GPU,
        ]
        assert attempts == {11: 1, 22: 1}
        assert all(task.done() for task in tracked_tasks)
        assert orphan_tasks == []

    asyncio.run(body())


def test_warmup_deadline_fails_run_without_hanging(monkeypatch: pytest.MonkeyPatch) -> None:
    health_calls = 0

    async def health_handler(request: httpx.Request) -> httpx.Response:
        nonlocal health_calls
        health_calls += 1
        raise httpx.ConnectError("GPU endpoint refused connection", request=request)

    _install_mock_transport(monkeypatch, health_handler)
    monkeypatch.setenv("ACX_GPU_WARMUP_TIMEOUT_SECONDS", "0.1")

    async def body() -> None:
        async with _database() as (session_factory, _engine):
            run_id = await _create_run(session_factory, [99])
            describe_calls = 0

            async def describe_one(
                _media_id: int,
                _image_bytes: bytes | None,
                _content_type: str | None,
                *,
                naming_inputs=None,
            ):
                nonlocal describe_calls
                describe_calls += 1
                return _final_outcome(99)

            started = time.monotonic()
            await asyncio.wait_for(
                wmod.run_describe_job(
                    tenant_id=TENANT_ID,
                    run_id=run_id,
                    session_factory=session_factory,
                    describe_one=describe_one,
                    timeout_seconds=0.5,
                    gpu_policy=_gpu_policy(),
                ),
                timeout=1.0,
            )
            elapsed = time.monotonic() - started
            run, items = await _read_run(session_factory, run_id)

        assert elapsed < 2.0
        assert health_calls > 0
        assert describe_calls == 0
        assert run is not None
        assert run.status == DescribeRunStatus.FAILED
        detail = _warmup_timeout_detail(run.error_message)
        assert detail["code"] == wmod.DescribeRunTerminalCode.GPU_WARMUP_TIMEOUT
        assert detail["retryable"] is True
        assert detail["startup_budget_seconds"] == max(1, round(_gpu_policy().warmup_timeout_seconds))
        envelope = _run_response(run)
        assert envelope.status is DescribeRunStatus.FAILED
        assert envelope.terminal is not None
        assert envelope.terminal.code == wmod.DescribeRunTerminalCode.GPU_WARMUP_TIMEOUT
        assert envelope.terminal.retryable is True
        assert envelope.fallback_reason is None
        assert items[0].status == DescribeItemStatus.FAILED
        assert items[0].image_bytes is None

    asyncio.run(body())


def test_gpu_warmup_timeout_startup_budget_rounds_positive_timeout() -> None:
    detail = _warmup_timeout_detail(
        wmod._gpu_warmup_timeout_detail(timeout_seconds=17.5, error=TimeoutError("still starting"))
    )
    assert detail["startup_budget_seconds"] == 18
    assert wmod._startup_budget_seconds(0.1) == 1
    assert wmod._startup_budget_seconds(1.0) == 1
    assert wmod._startup_budget_seconds(0.0) is None
    assert wmod._startup_budget_seconds(-2.0) is None


def test_warmup_timeout_degrades_to_cpu_adapter_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_transport(monkeypatch, _refusing_health_handler())
    monkeypatch.setenv("ACX_GPU_WARMUP_TIMEOUT_SECONDS", "0.1")

    async def body() -> None:
        async with _database() as (session_factory, _engine):
            run_id = await _create_run(session_factory, [7, 8])
            gpu_calls: list[int] = []
            cpu_calls: list[int] = []

            async def gpu_describe_one(
                media_id: int,
                _image_bytes: bytes | None,
                _content_type: str | None,
                *,
                naming_inputs=None,
            ):
                gpu_calls.append(media_id)
                return _final_outcome(media_id)

            async def cpu_describe_one(
                media_id: int,
                image_bytes: bytes | None,
                content_type: str | None,
                *,
                naming_inputs=None,
            ):
                cpu_calls.append(media_id)
                assert image_bytes == b"rawbytes"
                assert content_type == "image/png"
                return _cpu_outcome(media_id)

            await asyncio.wait_for(
                wmod.run_describe_job(
                    tenant_id=TENANT_ID,
                    run_id=run_id,
                    session_factory=session_factory,
                    describe_one=gpu_describe_one,
                    timeout_seconds=0.5,
                    gpu_policy=_gpu_policy(),
                    cpu_describe_one=cpu_describe_one,
                ),
                timeout=2.0,
            )
            run, items = await _read_run(session_factory, run_id)

        assert gpu_calls == []
        assert cpu_calls == [7, 8]
        assert run is not None
        assert run.status == DescribeRunStatus.COMPLETED
        persisted = _warmup_timeout_detail(run.error_message)
        assert persisted["fallback_reason"] == wmod.DescribeRunTerminalReason.GPU_WARMUP_TIMEOUT
        assert "code" not in persisted
        envelope = _run_response(run)
        assert envelope.fallback_reason == wmod.DescribeRunTerminalReason.GPU_WARMUP_TIMEOUT
        assert envelope.terminal is None
        assert run.first_ready_at is None
        assert run.ramp_up_ms is None
        assert [item.status for item in items] == [DescribeItemStatus.COMPLETED, DescribeItemStatus.COMPLETED]
        for item in items:
            assert item.tier == DescriptionResultTier.PROVISIONAL_CPU
            assert item.provenance is not None
            assert item.provenance["fallback_reason"] == wmod.DescribeRunTerminalReason.GPU_WARMUP_TIMEOUT
            assert item.alt_text_draft == f"cpu alt {item.media_id}"
            projected = describe_job_status(item)
            assert projected is DescribeJobStatus.DEGRADED
            assert projected is not DescribeJobStatus.FINAL
            validated = DescribeRunItemResponse.model_validate(
                {
                    "media_id": item.media_id,
                    "status": item.status,
                    "alt_text_draft": item.alt_text_draft,
                    "caption": item.caption,
                    "provenance": item.provenance,
                    "error": describe_job_error(item),
                    "tier": item.tier,
                    "result_generation": item.result_generation,
                    "processing_ms": item.processing_ms,
                }
            )
            assert validated.tier is DescriptionResultTier.PROVISIONAL_CPU

    asyncio.run(body())


def test_warmup_timeout_unavailable_cpu_ends_with_typed_retryable_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mock_transport(monkeypatch, _refusing_health_handler())
    monkeypatch.setenv("ACX_GPU_WARMUP_TIMEOUT_SECONDS", "0.1")

    async def body() -> None:
        async with _database() as (session_factory, _engine):
            run_id = await _create_run(session_factory, [5])
            describe_calls = 0

            async def describe_one(
                _media_id: int,
                _image_bytes: bytes | None,
                _content_type: str | None,
                *,
                naming_inputs=None,
            ):
                nonlocal describe_calls
                describe_calls += 1
                return _final_outcome(5)

            await asyncio.wait_for(
                wmod.run_describe_job(
                    tenant_id=TENANT_ID,
                    run_id=run_id,
                    session_factory=session_factory,
                    describe_one=describe_one,
                    timeout_seconds=0.5,
                    gpu_policy=_gpu_policy(),
                    cpu_describe_one=UnavailableDescriptionAdapter("florence_small extra missing"),
                ),
                timeout=2.0,
            )
            run, items = await _read_run(session_factory, run_id)

        assert describe_calls == 0
        assert run is not None
        assert run.status == DescribeRunStatus.FAILED
        detail = _warmup_timeout_detail(run.error_message)
        assert detail["code"] == wmod.DescribeRunTerminalCode.GPU_WARMUP_TIMEOUT
        assert detail["retryable"] is True
        assert detail["startup_budget_seconds"] == max(1, round(_gpu_policy().warmup_timeout_seconds))
        envelope = _run_response(run)
        assert envelope.status is DescribeRunStatus.FAILED
        assert envelope.terminal is not None
        assert envelope.terminal.code == wmod.DescribeRunTerminalCode.GPU_WARMUP_TIMEOUT
        assert envelope.terminal.retryable is True
        assert envelope.fallback_reason is None
        assert items[0].status == DescribeItemStatus.FAILED
        assert items[0].image_bytes is None

    asyncio.run(body())


def test_warmup_cpu_fallback_forces_provisional_cpu_when_adapter_returns_final_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mock_transport(monkeypatch, _refusing_health_handler())
    monkeypatch.setenv("ACX_GPU_WARMUP_TIMEOUT_SECONDS", "0.1")

    async def body() -> None:
        async with _database() as (session_factory, _engine):
            run_id = await _create_run(session_factory, [3])

            async def gpu_describe_one(
                media_id: int,
                _image_bytes: bytes | None,
                _content_type: str | None,
                *,
                naming_inputs=None,
            ):
                return _final_outcome(media_id)

            async def cpu_describe_one(
                media_id: int,
                _image_bytes: bytes | None,
                _content_type: str | None,
                *,
                naming_inputs=None,
            ):
                return _final_outcome(media_id)

            await asyncio.wait_for(
                wmod.run_describe_job(
                    tenant_id=TENANT_ID,
                    run_id=run_id,
                    session_factory=session_factory,
                    describe_one=gpu_describe_one,
                    timeout_seconds=0.5,
                    gpu_policy=_gpu_policy(),
                    cpu_describe_one=cpu_describe_one,
                ),
                timeout=2.0,
            )
            run, items = await _read_run(session_factory, run_id)

        assert run is not None
        assert run.status == DescribeRunStatus.COMPLETED
        envelope = _run_response(run)
        assert envelope.fallback_reason == wmod.DescribeRunTerminalReason.GPU_WARMUP_TIMEOUT
        assert envelope.terminal is None
        assert items[0].tier == DescriptionResultTier.PROVISIONAL_CPU
        assert items[0].tier != DescriptionResultTier.FINAL_GPU
        assert items[0].provenance["fallback_reason"] == wmod.DescribeRunTerminalReason.GPU_WARMUP_TIMEOUT
        assert describe_job_status(items[0]) is DescribeJobStatus.DEGRADED

    asyncio.run(body())


def test_describe_run_item_response_accepts_warmup_cpu_fallback_row() -> None:
    item = DescribeRunItemResponse.model_validate(
        {
            "media_id": 7,
            "status": "completed",
            "alt_text_draft": "cpu alt 7",
            "caption": "cpu caption 7",
            "provenance": {"adapter": "florence_small", "fallback_reason": "gpu_warmup_timeout"},
            "tier": "provisional_cpu",
            "result_generation": 0,
        }
    )
    assert item.tier is DescriptionResultTier.PROVISIONAL_CPU
    assert item.provenance is not None
    assert item.provenance["fallback_reason"] == wmod.DescribeRunTerminalReason.GPU_WARMUP_TIMEOUT


def test_naming_preview_timeout_stamps_skipped_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    async def hang(**_kwargs):
        raise TimeoutError("preview timed out")

    monkeypatch.setattr(wmod, "naming_preview", hang)

    async def body():
        return await wmod._apply_naming_preview(
            enabled=True,
            session=object(),
            tenant=object(),
            tenant_id=TENANT_ID,
            media_id=1,
            image_bytes=b"raw",
            outcome=wmod.DescribeItemOutcome(alt_text_draft="generic"),
            naming_inputs=wmod.FusionNamingInputs(confirmed_faces=[], naming_policy=object()),
            item_started=time.monotonic(),
            item_envelope=30.0,
        )

    naming = asyncio.run(body()).provenance["naming"]
    assert naming["status"] == wmod.NamingStatus.SKIPPED_BUDGET


def test_naming_preview_unexpected_exception_stamps_merge_error_not_no_faces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(**_kwargs):
        raise RuntimeError("preview exploded")

    monkeypatch.setattr(wmod, "naming_preview", boom)

    async def body():
        return await wmod._apply_naming_preview(
            enabled=True,
            session=object(),
            tenant=object(),
            tenant_id=TENANT_ID,
            media_id=1,
            image_bytes=b"raw",
            outcome=wmod.DescribeItemOutcome(alt_text_draft="generic"),
            naming_inputs=wmod.FusionNamingInputs(confirmed_faces=[], naming_policy=object()),
            item_started=time.monotonic(),
            item_envelope=30.0,
        )

    naming = asyncio.run(body()).provenance["naming"]
    assert naming["reason"] == wmod.NamingSkipReason.MERGE_ERROR
    assert naming["status"] != wmod.NamingStatus.NO_FACES
    assert naming["status"] != wmod.NamingStatus.SKIPPED_BUDGET
