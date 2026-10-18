"""Bulk-worker completion must use the cancellation-safe snapshot publisher."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import contextmanager

import pytest

import scene.application.describe_load as load
import scene.application.describe_run_worker as worker


def _producer(monkeypatch, target, payload):
    import db.tenant_context as tenant_context

    transactions = []
    observations = []

    class Session:
        async def __aenter__(self):
            transactions.append("opened")
            return self

        async def __aexit__(self, *_args):
            transactions.append("closed")

        async def commit(self):
            transactions.append("committed")

    async def bypass(_session):
        pass

    async def snapshot(_session, **kwargs):
        observations.append(kwargs)
        return payload

    monkeypatch.setattr(tenant_context, "enable_rls_bypass", bypass)
    monkeypatch.setattr(load, "load_snapshot", snapshot)
    monkeypatch.setattr(load, "resolve_load_path", lambda: target)
    # Also exercise the old direct-import caller in cause-removal mutations.
    monkeypatch.setattr(worker, "load_snapshot", snapshot, raising=False)
    monkeypatch.setattr(worker, "resolve_load_path", lambda: target, raising=False)
    return Session, transactions, observations


@contextmanager
def _held_fence(target, kind):
    from infra.oci.gpu_lifecycle.load_source import AggregateJobLoadSource

    entered = threading.Event()
    release = threading.Event()
    failures = []

    def bounded_stop():
        entered.set()
        release.wait(timeout=0.4)  # Bound teardown even for a synchronous mutant.

    def hold():
        try:
            if kind == "process":
                source = AggregateJobLoadSource(
                    target.parent.parent, stale_seconds=120, expected_environments=(target.parent.name,)
                )
                assert source.actuate_if_generation(source.fence_token(), bounded_stop)
            else:
                with load._LOAD_SNAPSHOT_WRITE_LOCK:
                    bounded_stop()
        except BaseException as error:
            failures.append(error)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    try:
        assert entered.wait(timeout=1), "publication fence holder did not start"
        yield release, holder
    finally:
        release.set()
        holder.join(timeout=1)
        assert not holder.is_alive(), "publication fence holder did not finish"
        if failures:
            raise failures[0]


async def _event(event, budget_seconds=1):
    # Poll without spending another executor thread on the test's barrier.
    async with asyncio.timeout(budget_seconds):
        while not event.is_set():  # noqa: ASYNC110 - signalled by a writer thread, not an asyncio task
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("kind", ["process", "thread"])
@pytest.mark.timeout(10)
def test_worker_snapshot_contended_fence_keeps_heartbeat_and_commits(tmp_path, monkeypatch, kind):
    target = tmp_path / "prod" / "describe-load.json"
    idle = {
        "revision": 1,
        "queue_depth": 0,
        "in_flight": 0,
        "batch_in_progress": False,
        "lease_demand": 0,
        "written_at": time.time(),
    }
    load.write_load_snapshot(idle, target)
    original = target.read_bytes()
    busy = {**idle, "revision": 2, "in_flight": 1, "lease_demand": 1}
    factory, transactions, observations = _producer(monkeypatch, target, busy)
    monkeypatch.setattr(load, "LOAD_SNAPSHOT_ACQUIRE_TIMEOUT_SECONDS", 0.25)

    async def exercise():
        with _held_fence(target, kind):
            started = time.monotonic()
            publication = asyncio.create_task(worker.publish_demand_snapshot(factory))
            try:
                await asyncio.sleep(0.01)
                assert time.monotonic() - started < 0.1, "worker snapshot fence blocked the event loop"
                assert not publication.done(), "publication must wait for the STOP fence"
                assert target.read_bytes() == original
                await asyncio.wait_for(publication, 1)  # Best-effort acquisition timeout.
                assert target.read_bytes() == original
            finally:
                publication.cancel()
                async with asyncio.timeout(1):
                    await asyncio.gather(publication, return_exceptions=True)
        assert transactions == ["opened", "committed", "closed"]
        assert observations[0]["minimum_revision"] == 1
        assert observations[0]["stop_requested"] is None
        assert observations[0]["max_lease_reached"] is None
        await worker.publish_demand_snapshot(factory)
        assert json.loads(target.read_text()) == busy
        # An equal revision cannot refresh the reaper's timestamp.
        busy["written_at"] += 100
        await worker.publish_demand_snapshot(factory)
        assert json.loads(target.read_text())["written_at"] == idle["written_at"]
        assert not list(target.parent.glob("*.tmp"))

    asyncio.run(exercise())


@pytest.mark.parametrize("kind", ["process", "thread"])
@pytest.mark.parametrize("cancel_mode", ["cancel", "timeout"])
@pytest.mark.timeout(10)
def test_worker_snapshot_cancel_stops_publication_before_fence_release(tmp_path, monkeypatch, kind, cancel_mode):
    target = tmp_path / "prod" / "describe-load.json"
    load.write_load_snapshot({"revision": 1}, target)
    original = target.read_bytes()
    factory, transactions, _ = _producer(monkeypatch, target, {"revision": 2})
    monkeypatch.setattr(load, "LOAD_SNAPSHOT_ACQUIRE_TIMEOUT_SECONDS", 0.3)
    entered = threading.Event()
    finished = threading.Event()
    real_write = load.write_load_snapshot

    def observed_write(*args, **kwargs):
        entered.set()
        try:
            return real_write(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(load, "write_load_snapshot", observed_write)
    monkeypatch.setattr(worker, "write_load_snapshot", observed_write, raising=False)

    async def exercise():
        with _held_fence(target, kind) as (release, holder):
            publication = asyncio.create_task(worker.publish_demand_snapshot(factory))
            try:
                await _event(entered)
                assert not publication.done(), "publisher returned before cancellation could overlap the fence"
                if cancel_mode == "cancel":
                    publication.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        async with asyncio.timeout(0.15):
                            await publication
                else:
                    with pytest.raises(TimeoutError):
                        async with asyncio.timeout(0.01):
                            await publication
                await _event(finished, budget_seconds=0.15)
                assert holder.is_alive(), "cancellation must complete while STOP still holds its fence"
                assert transactions == ["opened", "committed", "closed"]
                assert target.read_bytes() == original
                assert not list(target.parent.glob("*.tmp"))
            finally:
                release.set()
                publication.cancel()
                async with asyncio.timeout(1):
                    await asyncio.gather(publication, return_exceptions=True)
        assert target.read_bytes() == original
        await worker.publish_demand_snapshot(factory)
        assert json.loads(target.read_text()) == {"revision": 2}

    asyncio.run(exercise())
