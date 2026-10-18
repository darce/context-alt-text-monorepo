"""VLM5-S3A-BR-04: terminal publication belongs to the async finalizer.

TEST-15 — Prove the green can go red (The Pragmatic Programmer, ch. 9;
heuristics-canon v0.25.6 SOURCES.md#src-pragmatic-programmer): the unchanged
source loses a seeded busy snapshot's terminal refresh when cancelled here.
The shared publisher's direct-cancellation contract remains independently
covered by test_describe_load.py; only the router await is intercepted below.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import (
    DescribeDemandLease,
    DescribeOperation,
    DescribeRun,
    DescribeRunItem,
    DescribeStartup,
)
from scene.application.describe_load import dump_load_snapshot
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import TERMINAL_RUN_STATUSES, DescribeItemStatus
from scene.interface_adapters.http.routers import describe as route

WAIT_SECONDS = 5
IMAGE = b"finalizer-regression"


class CountingGate(route.AsyncAdmissionGate):
    def __init__(self):
        super().__init__(max_jobs=1, max_retained_image_bytes=len(IMAGE))
        self.released = []

    def release(self, image_len):
        self.released.append(image_len)
        super().release(image_len)


@pytest_asyncio.fixture
async def finalizer(tmp_path, monkeypatch):
    # Real persistence and publication, isolated from serving state and GPU.
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(tmp_path / "gpu-state.json"))
    monkeypatch.setenv("ACX_GPU_INTENT_PATH", str(tmp_path / "gpu-intent.json"))
    target = tmp_path / "describe-load.json"
    monkeypatch.setenv("ACX_DESCRIBE_LOAD_PATH", str(target))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'finalizer.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[
                    DescribeStartup.__table__,
                    DescribeOperation.__table__,
                    DescribeDemandLease.__table__,
                    DescribeRun.__table__,
                    DescribeRunItem.__table__,
                ],
            )
            await conn.execute(text(
                "CREATE TABLE describe_load_snapshot_revisions ("
                "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
                "revision INTEGER NOT NULL)"
            ))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        tenant = uuid.uuid4()
        async with factory() as session:
            repo = DescribeRunRepository(session)
            run_id = await repo.create_single_run(tenant_id=tenant, media_id=42, image_bytes=IMAGE)
            await session.commit()
        await dump_load_snapshot(factory, raise_on_error=True)
        busy = json.loads(target.read_text())
        assert (busy["queue_depth"], busy["in_flight"]) == (1, 0)
        assert busy["revision"] > 0
        gate = CountingGate()
        assert gate.try_acquire(len(IMAGE)) is None
        yield SimpleNamespace(factory=factory, tenant=tenant, run_id=run_id, target=target, busy=busy, gate=gate)
    finally:
        await engine.dispose()


async def _commit_terminal(case):
    async with case.factory() as session:
        repo = DescribeRunRepository(session)
        assert await repo.set_item_failed(
            tenant_id=case.tenant, run_id=case.run_id, media_id=42, error="test worker terminal result"
        )
        await session.commit()


async def _assert_terminal_and_released(case):
    async with case.factory() as session:
        repo = DescribeRunRepository(session)
        item = await repo.get_single_run_item(tenant_id=case.tenant, run_id=case.run_id)
        run = await session.get(DescribeRun, case.run_id)
        assert item.status == DescribeItemStatus.FAILED
        assert item.image_bytes is None
        assert run.status in TERMINAL_RUN_STATUSES
    assert case.gate.released == [len(IMAGE)], "admission must be released exactly once"
    assert (case.gate._job_count, case.gate._retained_image_bytes) == (0, 0)


def _assert_new_terminal_snapshot(case):
    snapshot = json.loads(case.target.read_text())
    assert snapshot["revision"] > case.busy["revision"], (
        "terminal refresh was abandoned after cancellation: "
        f"seeded busy revision={case.busy['revision']}, observed snapshot={snapshot}"
    )
    assert (snapshot["queue_depth"], snapshot["in_flight"]) == (0, 0)
    assert snapshot["batch_in_progress"] is False
    assert snapshot["lease_demand"] == 0


def _start(case):
    return asyncio.create_task(route._run_async_describe_job_and_release(
        image_len=len(IMAGE), session_factory=case.factory, admission_gate=case.gate,
        tenant_id=case.tenant, run_id=case.run_id,
    ))


async def _checkpoint():
    # Yield after cancel() without a wall-clock ordering assumption.
    reached = asyncio.Event()
    asyncio.get_running_loop().call_soon(reached.set)
    await reached.wait()


@pytest.mark.asyncio
async def test_healthy_finalizer_publishes_new_terminal_revision(finalizer, monkeypatch):
    async def worker(**kwargs):
        assert kwargs["session_factory"] is finalizer.factory
        await _commit_terminal(finalizer)

    monkeypatch.setattr(route, "run_async_describe_job", worker)
    await asyncio.wait_for(_start(finalizer), WAIT_SECONDS)
    await _assert_terminal_and_released(finalizer)
    _assert_new_terminal_snapshot(finalizer)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_worker", [False, True], ids=["final-refresh", "repeated-worker-cleanup"])
async def test_cancelled_finalizer_still_publishes_committed_terminal_revision(
    finalizer, monkeypatch, cancel_worker,
):
    committed = asyncio.Event()
    worker_continue = asyncio.Event()
    cleanup_entered = asyncio.Event()
    cleanup_continue = asyncio.Event()
    publication_entered = asyncio.Event()
    publication_continue = asyncio.Event()
    publication_tasks = set()
    real_cleanup = route._reconcile_aborted_describe_worker

    async def worker(**kwargs):
        await _commit_terminal(finalizer)
        committed.set()
        if cancel_worker:
            await worker_continue.wait()

    async def cleanup(**kwargs):
        cleanup_entered.set()
        await cleanup_continue.wait()
        await real_cleanup(**kwargs)

    async def paused_publication(factory, *args, **kwargs):
        publication_tasks.add(asyncio.current_task())
        publication_entered.set()
        await publication_continue.wait()
        # Use the real producer, revision allocator, commit and atomic writer.
        await dump_load_snapshot(factory, *args, **kwargs)

    monkeypatch.setattr(route, "run_async_describe_job", worker)
    monkeypatch.setattr(route, "_reconcile_aborted_describe_worker", cleanup)
    monkeypatch.setattr(route, "dump_load_snapshot", paused_publication)
    pending = _start(finalizer)
    try:
        await asyncio.wait_for(committed.wait(), WAIT_SECONDS)
        if cancel_worker:
            assert pending.cancel()
            await asyncio.wait_for(cleanup_entered.wait(), WAIT_SECONDS)
            assert pending.cancel(), "second cancellation must arrive during worker cleanup"
            await _checkpoint()
            assert not pending.done(), "second cancellation abandoned worker reconciliation"
            cleanup_continue.set()
        await asyncio.wait_for(publication_entered.wait(), WAIT_SECONDS)
        # Establish committed terminal state and stale publication before the
        # decisive cancellation; enqueue and admission are separate concerns.
        await _assert_terminal_and_released(finalizer)
        assert json.loads(finalizer.target.read_text()) == finalizer.busy
        assert pending.cancel(), "cancellation must arrive at the final publication barrier"
        await _checkpoint()
        if not cancel_worker and not pending.done():
            assert pending.cancel()  # Also interrupt a protected final refresh twice.
            await _checkpoint()
        publication_continue.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(pending), WAIT_SECONDS)
        await _assert_terminal_and_released(finalizer)
        _assert_new_terminal_snapshot(finalizer)
    finally:
        worker_continue.set()
        cleanup_continue.set()
        publication_continue.set()
        # Drain tasks started by this test even when a barrier/oracle fails.
        if not pending.done():
            pending.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(pending), WAIT_SECONDS)
        children = publication_tasks - {pending}
        if children:
            await asyncio.wait_for(asyncio.gather(*children, return_exceptions=True), WAIT_SECONDS)
