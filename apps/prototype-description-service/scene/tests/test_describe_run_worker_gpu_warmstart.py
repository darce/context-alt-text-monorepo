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
    describe_job_status,
)
from scene.domain.description import DescriptionAdapterKind, DescriptionResultTier
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
    start_interval_match = re.search(r'^START_INTERVAL="\$\{START_INTERVAL:-(\d+)s\}"$', installer, re.MULTILINE)
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
        assert run.error_message is not None and "did not become ready" in run.error_message
        assert items[0].status == DescribeItemStatus.FAILED

    asyncio.run(body())
