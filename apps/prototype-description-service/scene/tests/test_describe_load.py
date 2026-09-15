"""VLM-5 Slice 3: DB-derived load snapshot for the GPU idle reaper.

Key set, atomic write, single-run-only counts, and RLS-bypass discipline
[DIAG-02], [SEC-01], [DATA-16].
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import math
import os
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import scene.application.describe_load as load_mod
from db.models.base_imports import Base
from db.models.scene import (
    DescribeDemandLease,
    DescribeOperation,
    DescribeRun,
    DescribeRunItem,
    DescribeStartup,
)
from scene.application.describe_load import (
    DemandLeaseBounds,
    batch_in_progress,
    dump_load_snapshot,
    load_snapshot,
    refresh_load_snapshot_loop,
    resolve_load_path,
    resolve_load_refresh_seconds,
    run_startup_load_snapshot,
    validate_demand_lease_bounds,
    write_load_snapshot,
)
from scene.application.describe_operation_repository import DescribeOperationRepository
from scene.application.describe_run_repository import (
    DescribeRunRepository,
    run_startup_retention_purge,
)
from scene.domain.describe_run import (
    DemandLeaseState,
    DescribeItemStatus,
    DescribeRunStatus,
    OperationExpiredError,
)

_LOAD_SNAPSHOT_KEYS = {
    "queue_depth",
    "in_flight",
    "batch_in_progress",
    "written_at",
    "lease_demand",
    "revision",
}
_PUBLIC_RETRY_AFTER_CEILING = 120
_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64


async def _sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=cast(
                list[Table],
                [
                    DescribeStartup.__table__,
                    DescribeOperation.__table__,
                    DescribeDemandLease.__table__,
                    DescribeRun.__table__,
                    DescribeRunItem.__table__,
                ],
            ),
        )
        await conn.execute(
            text(
                "CREATE TABLE describe_load_snapshot_revisions ("
                "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
                "revision INTEGER NOT NULL)"
            )
        )
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _has_work(snapshot: dict) -> bool:
    return ((snapshot["queue_depth"] + snapshot["in_flight"]) > 0) or bool(snapshot["batch_in_progress"])


def _publish_gpu_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    now: datetime,
    state: str = "stopped",
    last_transition_reason: str | None = None,
    written_at: float | None = None,
    raw: str | bytes | None = None,
    reason: str | None = None,
) -> Path:
    path = tmp_path / "gpu-state.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))
    if raw is not None:
        if isinstance(raw, bytes):
            path.write_bytes(raw)
        else:
            path.write_text(raw, encoding="utf-8")
        return path
    payload: dict[str, object] = {
        "state": state,
        "instance_id": "ocid1.gpu",
        "written_at": now.timestamp() if written_at is None else written_at,
        "reason": "readiness_timeout" if state == "degraded" and reason is None else reason,
    }
    if last_transition_reason is not None:
        payload["last_transition_reason"] = last_transition_reason
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _legal_bounds(**overrides: float) -> DemandLeaseBounds:
    return replace(load_mod.deployed_demand_lease_bounds(), **overrides)


def test_write_load_snapshot_keys_and_atomic_replace(tmp_path: Path):
    target = tmp_path / "describe-load.json"
    payload = {"queue_depth": 2, "in_flight": 1, "written_at": 1_700_000_000.0}
    write_load_snapshot(payload, target)
    assert target.exists()
    assert not target.with_suffix(target.suffix + ".tmp").exists()
    loaded = json.loads(target.read_text())
    assert set(loaded) == {"queue_depth", "in_flight", "written_at"}
    assert loaded["queue_depth"] == 2
    assert loaded["in_flight"] == 1
    assert loaded["written_at"] == 1_700_000_000.0


def test_load_snapshot_counts_single_runs_only_across_tenants():
    async def body():
        engine, sf = await _sessionmaker()
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()

        async with sf() as s:
            repo = DescribeRunRepository(s)
            # Two queued singles (different tenants) + one running single.
            await repo.create_single_run(tenant_id=tenant_a, media_id=1, image_bytes=b"a")
            await repo.create_single_run(tenant_id=tenant_b, media_id=2, image_bytes=b"b")
            run_c = await repo.create_single_run(tenant_id=tenant_a, media_id=3, image_bytes=b"c")
            await repo.mark_item(
                tenant_id=tenant_a,
                run_id=run_c,
                media_id=3,
                status=DescribeItemStatus.RUNNING,
            )
            # Bulk run items must not contribute.
            bulk_id = await repo.create_run(tenant_id=tenant_a, media_ids=[10, 11])
            await repo.mark_item(
                tenant_id=tenant_a,
                run_id=bulk_id,
                media_id=10,
                status=DescribeItemStatus.RUNNING,
            )
            # Terminal single must not contribute.
            term_id = await repo.create_single_run(tenant_id=tenant_b, media_id=99, image_bytes=b"done")
            await repo.set_item_failed(tenant_id=tenant_b, run_id=term_id, media_id=99, error="done")
            await s.commit()

        async with sf() as s:
            snap = await load_snapshot(s)
            assert set(snap) == _LOAD_SNAPSHOT_KEYS
            assert snap["queue_depth"] == 2
            assert snap["in_flight"] == 1
            assert snap["lease_demand"] == 0
            assert snap["revision"] == 1
            # The bulk run above is still non-terminal: excluded from the item
            # counts, but it must surface on its own key (GPUW-1).
            assert snap["batch_in_progress"] is True
            assert isinstance(snap["written_at"], float)
            assert snap["written_at"] > 0
            assert _has_work(snap) is True

        await engine.dispose()

    asyncio.run(body())


def test_load_snapshot_requires_rls_bypass_on_non_sqlite(monkeypatch):
    """Tenant-scoped / non-bypass sessions fail closed [DIAG-02], [SEC-01]."""

    class _NotBypassedResult:
        def scalar(self):
            return None

    class _NotBypassedSession:
        async def execute(self, *_args, **_kwargs):
            return _NotBypassedResult()

    monkeypatch.setattr(load_mod, "is_sqlite", lambda _session: False)
    with pytest.raises(RuntimeError, match="RLS-bypassed"):
        asyncio.run(load_snapshot(_NotBypassedSession()))  # type: ignore[arg-type]


def test_require_rls_bypass_fails_closed_unless_pg_setting_is_truthy(monkeypatch):
    """Fail closed on tenant-scoped aggregation; sqlite skip is not the proof."""

    class _Result:
        def __init__(self, value: object):
            self._value = value

        def scalar(self):
            return self._value

    class _Session:
        def __init__(self, value: object):
            self._value = value

        async def execute(self, *_args, **_kwargs):
            return _Result(self._value)

    monkeypatch.setattr(load_mod, "is_sqlite", lambda _session: False)
    for value in (None, "", "off", "false", "0", "no"):
        with pytest.raises(RuntimeError, match="RLS-bypassed"):
            asyncio.run(load_mod._require_rls_bypass(_Session(value)))  # type: ignore[arg-type]
    for value in ("true", "on", "1", "yes", "TRUE", "On"):
        asyncio.run(load_mod._require_rls_bypass(_Session(value)))  # type: ignore[arg-type]


def test_dump_load_snapshot_enables_rls_bypass_before_counting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def body():
        engine, sf = await _sessionmaker()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        _publish_gpu_state(tmp_path, monkeypatch, now=start, state="stopped")
        bypass_sessions: list[object] = []
        import db.tenant_context as tenant_context

        real_bypass = tenant_context.enable_rls_bypass

        async def spy_bypass(session):
            bypass_sessions.append(session)
            return await real_bypass(session)

        monkeypatch.setattr(tenant_context, "enable_rls_bypass", spy_bypass)
        await dump_load_snapshot(sf, path=tmp_path / "describe-load.json", now=start, raise_on_error=True)
        assert bypass_sessions
        await engine.dispose()

    asyncio.run(body())


def test_write_load_snapshot_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "nested" / "run" / "describe-load.json"
        write_load_snapshot({"queue_depth": 0, "in_flight": 0, "written_at": 1.0}, target)
        assert target.is_file()
        assert json.loads(target.read_text())["queue_depth"] == 0
        # No leftover tmp after atomic replace.
        assert not any(p.suffix == ".tmp" or p.name.endswith(".json.tmp") for p in target.parent.iterdir())
        # Clean env leftover if any
        assert "describe-load.json.tmp" not in os.listdir(target.parent)


def test_write_load_snapshot_serializes_concurrent_unique_temp_files(tmp_path: Path, monkeypatch):
    target = tmp_path / "describe-load.json"
    real_replace = os.replace
    first_replace_started = threading.Event()
    second_writer_started = threading.Event()
    release_first_replace = threading.Event()
    temp_paths: list[Path] = []

    def observed_replace(src, dst):
        temp_paths.append(Path(src))
        if len(temp_paths) == 1:
            first_replace_started.set()
            assert release_first_replace.wait(timeout=1)
        real_replace(src, dst)

    def second_write():
        second_writer_started.set()
        write_load_snapshot({"writer": 2}, target)

    monkeypatch.setattr(load_mod.os, "replace", observed_replace)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(write_load_snapshot, {"writer": 1}, target)
        assert first_replace_started.wait(timeout=1)
        second = executor.submit(second_write)
        assert second_writer_started.wait(timeout=1)
        # The first writer still holds the replace lock, so the second cannot
        # enter the critical section or reuse/clobber its temporary file.
        assert len(temp_paths) == 1
        release_first_replace.set()
        first.result(timeout=1)
        second.result(timeout=1)

    assert len(temp_paths) == 2
    assert temp_paths[0] != temp_paths[1]
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads(target.read_text()) == {"writer": 2}


def test_write_load_snapshot_holds_process_fence_during_publish(tmp_path: Path, monkeypatch):
    target = tmp_path / "describe-load.json"
    real_replace = os.replace

    def assert_fenced_replace(src, dst):
        lock_fd = os.open(tmp_path / "describe-load.json.lock", os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(lock_fd)
        real_replace(src, dst)

    monkeypatch.setattr(load_mod.os, "replace", assert_fenced_replace)

    write_load_snapshot({"writer": 1}, target)

    assert json.loads(target.read_text()) == {"writer": 1}


def test_run_startup_load_snapshot_writes_file_with_counts(tmp_path: Path):
    """VLM5-S4A-BR-01: run_startup_load_snapshot end-to-end against sqlite session factory."""

    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        target = tmp_path / "describe-load.json"

        async with sf() as s:
            repo = DescribeRunRepository(s)
            await repo.create_single_run(tenant_id=tenant, media_id=1, image_bytes=b"q")
            run_r = await repo.create_single_run(tenant_id=tenant, media_id=2, image_bytes=b"r")
            await repo.mark_item(
                tenant_id=tenant,
                run_id=run_r,
                media_id=2,
                status=DescribeItemStatus.RUNNING,
            )
            await s.commit()

        await run_startup_load_snapshot(sf, path=target)

        assert target.is_file()
        loaded = json.loads(target.read_text())
        assert set(loaded) == _LOAD_SNAPSHOT_KEYS
        assert loaded["queue_depth"] == 1
        assert loaded["in_flight"] == 1
        assert loaded["lease_demand"] == 0
        assert loaded["revision"] == 1
        # Only single runs above, so the batch flag must read False (GPUW-1).
        assert loaded["batch_in_progress"] is False
        assert isinstance(loaded["written_at"], (int, float))
        assert loaded["written_at"] > 0
        await engine.dispose()

    asyncio.run(body())


def test_run_startup_load_snapshot_resolves_env_path_when_path_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """VLM5-S4A-BR-01: path=None uses resolve_load_path() / ACX_DESCRIBE_LOAD_PATH."""

    async def body():
        engine, sf = await _sessionmaker()
        target = tmp_path / "from-env" / "load.json"
        monkeypatch.setenv("ACX_DESCRIBE_LOAD_PATH", str(target))
        assert resolve_load_path() == str(target)

        await run_startup_load_snapshot(sf, path=None)

        assert target.is_file()
        loaded = json.loads(target.read_text())
        assert set(loaded) == _LOAD_SNAPSHOT_KEYS
        assert loaded["queue_depth"] == 0
        assert loaded["in_flight"] == 0
        assert loaded["lease_demand"] == 0
        assert loaded["revision"] == 1
        assert loaded["batch_in_progress"] is False
        await engine.dispose()

    asyncio.run(body())


def test_run_startup_retention_purge_deletes_expired_terminal_singles():
    """VLM5-S4A-BR-01: run_startup_retention_purge wrapper deletes expired terminal singles."""
    from datetime import UTC, datetime, timedelta

    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        # Wrapper uses datetime.now() + default retention; age rows relative to wall clock.
        very_old = datetime.now(tz=UTC) - timedelta(hours=48)
        recent = datetime.now(tz=UTC) - timedelta(hours=1)

        async with sf() as s:
            repo = DescribeRunRepository(s)
            expired_id = await repo.create_single_run(tenant_id=tenant, media_id=1, image_bytes=b"old")
            await repo.set_item_failed(tenant_id=tenant, run_id=expired_id, media_id=1, error="done")
            expired = await repo.get_run(tenant_id=tenant, run_id=expired_id)
            assert expired is not None
            expired.completed_at = very_old
            expired.created_at = very_old

            keep_id = await repo.create_single_run(tenant_id=tenant, media_id=2, image_bytes=b"new")
            await repo.set_item_failed(tenant_id=tenant, run_id=keep_id, media_id=2, error="fresh")
            keep = await repo.get_run(tenant_id=tenant, run_id=keep_id)
            assert keep is not None
            keep.completed_at = recent
            keep.created_at = recent
            await s.commit()

        deleted = await run_startup_retention_purge(sf)
        assert deleted == 1

        async with sf() as s:
            repo = DescribeRunRepository(s)
            assert await repo.get_run(tenant_id=tenant, run_id=expired_id) is None
            assert await repo.get_run(tenant_id=tenant, run_id=keep_id) is not None

        await engine.dispose()

    asyncio.run(body())


# --- GPUW-1: bulk runs must be visible to the GPU lifecycle controller --------
#
# "Describe selected" creates a run_kind=bulk run. queue_depth/in_flight count
# single runs only, so before this key existed a batch was invisible to both
# cycles: run_start_cycle never started the burst GPU, and run_reap_cycle STOPped
# a running one mid-batch. These pin the flag that closes that hole.


def test_batch_in_progress_true_while_a_bulk_run_is_pending():
    async def body():
        engine, sf = await _sessionmaker()
        async with sf() as s:
            repo = DescribeRunRepository(s)
            await repo.create_run(tenant_id=uuid.uuid4(), media_ids=[1, 2, 3])
            await s.commit()
        async with sf() as s:
            assert await batch_in_progress(s) is True
            snap = await load_snapshot(s)
            # The whole point: the batch is invisible to the item counts, so the
            # flag is the only thing keeping the GPU alive for it.
            assert snap["queue_depth"] == 0
            assert snap["in_flight"] == 0
            assert snap["batch_in_progress"] is True
        await engine.dispose()

    asyncio.run(body())


def test_batch_in_progress_false_when_no_bulk_run_exists():
    """TEST-15: the flag must be able to read False, or it pins an A10 forever."""

    async def body():
        engine, sf = await _sessionmaker()
        async with sf() as s:
            repo = DescribeRunRepository(s)
            # A queued *single* run is real work, but it is not a batch.
            await repo.create_single_run(tenant_id=uuid.uuid4(), media_id=1, image_bytes=b"a")
            await s.commit()
        async with sf() as s:
            assert await batch_in_progress(s) is False
            snap = await load_snapshot(s)
            assert snap["queue_depth"] == 1
            assert snap["batch_in_progress"] is False
        await engine.dispose()

    asyncio.run(body())


def test_batch_in_progress_false_once_the_bulk_run_reaches_a_terminal_status():
    """ "Stop after batch complete": a finished run must release the GPU."""

    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[1])
            await s.commit()
        async with sf() as s:
            assert await batch_in_progress(s) is True
        async with sf() as s:
            run = await s.get(DescribeRun, run_id)
            run.status = DescribeRunStatus.COMPLETED
            await s.commit()
        async with sf() as s:
            assert await batch_in_progress(s) is False
        await engine.dispose()

    asyncio.run(body())


def test_batch_in_progress_is_cross_tenant():
    """The GPU is a single shared resource: any tenant's batch holds it open."""

    async def body():
        engine, sf = await _sessionmaker()
        async with sf() as s:
            repo = DescribeRunRepository(s)
            await repo.create_run(tenant_id=uuid.uuid4(), media_ids=[1])
            await repo.create_run(tenant_id=uuid.uuid4(), media_ids=[2])
            await s.commit()
        async with sf() as s:
            assert await batch_in_progress(s) is True
        await engine.dispose()

    asyncio.run(body())


def test_describe_load_refresh_seconds_defaults_and_stays_inside_stale_guard(monkeypatch):
    env_name = "ACX_DESCRIBE_LOAD_REFRESH_SECONDS"
    monkeypatch.delenv(env_name, raising=False)
    assert resolve_load_refresh_seconds() == 45.0

    monkeypatch.setenv(env_name, "15.5")
    assert resolve_load_refresh_seconds() == 15.5

    monkeypatch.setenv(env_name, "59.9")
    assert resolve_load_refresh_seconds() == 59.9

    for invalid in ("invalid", "0", "-1", "60", "90", "119", "120", "nan", "inf"):
        monkeypatch.setenv(env_name, invalid)
        assert resolve_load_refresh_seconds() == 45.0


def test_dump_load_snapshot_can_make_failures_visible_to_supervisor(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    class BrokenSessionFactory:
        def __call__(self):
            raise RuntimeError("database unavailable")

    async def body():
        factory = BrokenSessionFactory()
        target = tmp_path / "describe-load.json"
        with caplog.at_level(logging.WARNING, logger="scene.application.describe_load"):
            await dump_load_snapshot(factory, path=target)
        assert not target.exists()
        assert any(record.levelno == logging.WARNING for record in caplog.records)
        assert "describe load snapshot write failed" in caplog.text
        assert str(target) in caplog.text
        with pytest.raises(RuntimeError, match="database unavailable"):
            await dump_load_snapshot(factory, path=target, raise_on_error=True)

    asyncio.run(body())


def test_describe_load_refresher_keeps_running_after_one_failed_dump(monkeypatch):
    async def body():
        calls: list[object] = []
        second_call_started = asyncio.Event()
        hold_second_call = asyncio.Event()
        session_factory = object()

        async def fake_dump(factory, *, raise_on_error=False):
            assert factory is session_factory
            assert raise_on_error is True
            calls.append(factory)
            if len(calls) == 1:
                raise RuntimeError("transient snapshot failure")
            second_call_started.set()
            await hold_second_call.wait()

        monkeypatch.setattr(load_mod, "dump_load_snapshot", fake_dump)
        task = asyncio.create_task(refresh_load_snapshot_loop(session_factory, refresh_seconds=0))
        await asyncio.wait_for(second_call_started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # A failure in one cycle did not terminate the refresher, and shutdown
        # cancellation was propagated rather than swallowed by the failure guard.
        assert calls == [session_factory, session_factory]

    asyncio.run(body())


def test_describe_load_refresher_times_out_one_cycle_and_retries(monkeypatch):
    async def body():
        calls = 0
        second_call_started = asyncio.Event()

        async def stuck_dump(_factory, *, raise_on_error=False):
            nonlocal calls
            assert raise_on_error is True
            calls += 1
            if calls == 2:
                second_call_started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(load_mod, "dump_load_snapshot", stuck_dump)
        task = asyncio.create_task(refresh_load_snapshot_loop(object(), refresh_seconds=0, timeout_seconds=0.01))
        await asyncio.wait_for(second_call_started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert calls == 2

    asyncio.run(body())


def test_refresh_loop_binds_resolver_when_interval_not_passed(monkeypatch):
    """S2A-04: with refresh_seconds omitted, the loop's cadence must come from
    resolve_load_refresh_seconds(); a hardcoded interval would leave this red."""

    async def body():
        resolver_calls = 0
        dump_calls = 0
        second_dump = asyncio.Event()

        def fake_resolver():
            nonlocal resolver_calls
            resolver_calls += 1
            return 0.01

        async def fake_dump(_factory, *, raise_on_error=False):
            nonlocal dump_calls
            assert raise_on_error is True
            dump_calls += 1
            if dump_calls == 2:
                second_dump.set()

        monkeypatch.setattr(load_mod, "resolve_load_refresh_seconds", fake_resolver)
        monkeypatch.setattr(load_mod, "dump_load_snapshot", fake_dump)
        task = asyncio.create_task(refresh_load_snapshot_loop(object()))
        await asyncio.wait_for(second_dump.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert resolver_calls == 1
        assert dump_calls >= 2

    asyncio.run(body())


def test_lifespan_supervisor_rearms_refresher_and_propagates_cancel(monkeypatch):
    """S2B-05: the lifespan-owned supervisor must restart the refresher after a
    crash and after an unexpected clean return, and must let shutdown
    cancellation terminate it."""
    # api.main enforces production config at import; scene/tests has no
    # runtime-mode conftest, so scope the test mode to this import.
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    import api.main as main_mod

    async def body():
        starts = 0
        third_start = asyncio.Event()
        session_factory = object()

        async def fake_refresher(factory):
            nonlocal starts
            assert factory is session_factory
            starts += 1
            if starts == 1:
                raise RuntimeError("refresher crash")
            if starts == 2:
                return  # unexpected clean stop
            third_start.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(main_mod, "_LOAD_SNAPSHOT_REFRESH_REARM_SECONDS", 0.01)
        monkeypatch.setattr(load_mod, "refresh_load_snapshot_loop", fake_refresher)
        task = asyncio.create_task(main_mod._supervise_load_snapshot_refresher(session_factory))
        await asyncio.wait_for(third_start.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert starts == 3

    asyncio.run(body())


def test_load_snapshot_counts_cross_tenant_leases_as_in_flight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def body():
        engine, sf = await _sessionmaker()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        _publish_gpu_state(tmp_path, monkeypatch, now=start, state="stopped")
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        async with sf() as session:
            repo = DescribeOperationRepository(session, lease_seconds=180)
            await repo.accept(tenant_id=tenant_a, request_digest=_DIGEST_A, now=start)
            await repo.accept(tenant_id=tenant_b, request_digest=_DIGEST_B, now=start)
            await session.commit()
        async with sf() as session:
            snap = await load_snapshot(session, now=start)
            assert set(snap) == _LOAD_SNAPSHOT_KEYS
            assert snap["queue_depth"] == 0
            assert snap["in_flight"] == 2
            assert snap["lease_demand"] == 2
            assert snap["batch_in_progress"] is False
            assert snap["revision"] == 1
            assert _has_work(snap) is True
        await engine.dispose()

    asyncio.run(body())


def test_load_snapshot_stop_and_max_lease_exclude_demand_without_deleting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def body():
        engine, sf = await _sessionmaker()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        _publish_gpu_state(tmp_path, monkeypatch, now=start, state="stopped")
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        async with sf() as session:
            repo = DescribeOperationRepository(session, lease_seconds=180)
            first = await repo.accept(tenant_id=tenant_a, request_digest=_DIGEST_A, now=start)
            second = await repo.accept(tenant_id=tenant_b, request_digest=_DIGEST_B, now=start)
            await session.commit()
            first_id, second_id = first.operation_id, second.operation_id
        async with sf() as session:
            counted = await load_snapshot(session, now=start)
            assert counted["in_flight"] == 2
            assert counted["lease_demand"] == 2
            assert _has_work(counted) is True
            global_stop = await load_snapshot(session, now=start, stop_requested=True)
            assert global_stop["in_flight"] == 0
            assert global_stop["lease_demand"] == 0
            assert _has_work(global_stop) is False
            both_blocked = await load_snapshot(session, now=start, max_lease_reached=True)
            assert both_blocked["in_flight"] == 0
            assert both_blocked["lease_demand"] == 0
            first_lease = await session.get(DescribeDemandLease, (tenant_a, first_id))
            second_lease = await session.get(DescribeDemandLease, (tenant_b, second_id))
            assert first_lease is not None and first_lease.state == DemandLeaseState.ACTIVE
            assert second_lease is not None and second_lease.state == DemandLeaseState.ACTIVE
        await engine.dispose()

    asyncio.run(body())


def test_load_snapshot_drops_expired_lease_and_keeps_the_other(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def body():
        engine, sf = await _sessionmaker()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        later = start + timedelta(seconds=60)
        _publish_gpu_state(tmp_path, monkeypatch, now=later, state="stopped")
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        async with sf() as session:
            short = DescribeOperationRepository(session, lease_seconds=30)
            long = DescribeOperationRepository(session, lease_seconds=180)
            await short.accept(tenant_id=tenant_a, request_digest=_DIGEST_A, now=start)
            await long.accept(tenant_id=tenant_b, request_digest=_DIGEST_B, now=start)
            await session.commit()
        async with sf() as session:
            snap = await load_snapshot(session, now=later)
            assert snap["queue_depth"] == 0
            assert snap["in_flight"] == 1
            assert snap["lease_demand"] == 1
            assert _has_work(snap) is True
        await engine.dispose()

    asyncio.run(body())


def test_load_snapshot_does_not_double_count_lease_and_async_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def body():
        engine, sf = await _sessionmaker()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        _publish_gpu_state(tmp_path, monkeypatch, now=start, state="ready")
        tenant = uuid.uuid4()
        async with sf() as session:
            await DescribeOperationRepository(session, lease_seconds=180).accept(
                tenant_id=tenant, request_digest=_DIGEST_A, now=start
            )
            runs = DescribeRunRepository(session)
            await runs.create_single_run(tenant_id=tenant, media_id=1, image_bytes=b"q")
            running = await runs.create_single_run(tenant_id=tenant, media_id=2, image_bytes=b"r")
            await runs.mark_item(
                tenant_id=tenant,
                run_id=running,
                media_id=2,
                status=DescribeItemStatus.RUNNING,
            )
            await session.commit()
        async with sf() as session:
            snap = await load_snapshot(session, now=start)
            assert snap["queue_depth"] == 1
            assert snap["lease_demand"] == 1
            assert snap["in_flight"] == 2
            assert _has_work(snap) is True
        await engine.dispose()

    asyncio.run(body())


def test_fake_clock_retry_after_ceiling_retains_warming_demand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def body():
        engine, sf = await _sessionmaker()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        retry_at = start + timedelta(seconds=_PUBLIC_RETRY_AFTER_CEILING)
        _publish_gpu_state(tmp_path, monkeypatch, now=retry_at, state="warming")
        tenant = uuid.uuid4()
        async with sf() as session:
            await DescribeOperationRepository(session, lease_seconds=_PUBLIC_RETRY_AFTER_CEILING + 1).accept(
                tenant_id=tenant, request_digest=_DIGEST_A, now=start
            )
            await session.commit()
        async with sf() as session:
            snap = await load_snapshot(session, now=retry_at)
            assert snap["lease_demand"] == 1
            assert snap["in_flight"] == 1
            assert _has_work(snap) is True
        await engine.dispose()

    asyncio.run(body())


def test_write_load_snapshot_drops_older_and_equal_revisions(tmp_path: Path):
    target = tmp_path / "describe-load.json"
    newer = {
        "queue_depth": 0,
        "in_flight": 2,
        "lease_demand": 2,
        "revision": 11,
        "written_at": 100.0,
    }
    write_load_snapshot(newer, target)
    assert json.loads(target.read_text())["written_at"] == 100.0
    write_load_snapshot({**newer, "revision": 10, "written_at": 200.0, "in_flight": 0}, target)
    loaded = json.loads(target.read_text())
    assert loaded["revision"] == 11
    assert loaded["in_flight"] == 2
    assert loaded["written_at"] == 100.0
    write_load_snapshot({**newer, "revision": 11, "written_at": 300.0}, target)
    assert json.loads(target.read_text())["written_at"] == 100.0
    write_load_snapshot({**newer, "revision": 12, "written_at": 400.0, "in_flight": 3}, target)
    updated = json.loads(target.read_text())
    assert updated["revision"] == 12
    assert updated["in_flight"] == 3
    assert updated["written_at"] == 400.0


def test_write_load_snapshot_fails_closed_on_malformed_published_revision(tmp_path: Path):
    target = tmp_path / "describe-load.json"
    target.write_text("{not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreadable published load snapshot"):
        write_load_snapshot({"revision": 1, "written_at": 1.0}, target)
    for malformed in ("11", None, True, False, [11], {"nested": 1}, -1, 0):
        target.write_text(json.dumps({"revision": malformed}), encoding="utf-8")
        with pytest.raises(RuntimeError, match="malformed published load snapshot revision"):
            write_load_snapshot({"revision": 12, "written_at": 2.0}, target)
        assert json.loads(target.read_text()) == {"revision": malformed}


def test_write_load_snapshot_treats_missing_revision_key_as_initial_file(tmp_path: Path):
    target = tmp_path / "describe-load.json"
    target.write_text(json.dumps({"queue_depth": 1, "written_at": 1.0}), encoding="utf-8")
    write_load_snapshot({"revision": 1, "written_at": 2.0, "queue_depth": 0}, target)
    loaded = json.loads(target.read_text())
    assert loaded["revision"] == 1
    assert loaded["written_at"] == 2.0


def test_dump_load_snapshot_commits_before_stale_publication_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def body():
        engine, sf = await _sessionmaker()
        target = tmp_path / "describe-load.json"
        start = datetime(2026, 1, 1, tzinfo=UTC)
        _publish_gpu_state(tmp_path, monkeypatch, now=start, state="stopped")
        tenant = uuid.uuid4()
        async with sf() as session:
            repo = DescribeOperationRepository(session, lease_seconds=180)
            await repo.accept(tenant_id=tenant, request_digest=_DIGEST_A, now=start)
            await repo.accept(tenant_id=uuid.uuid4(), request_digest=_DIGEST_B, now=start)
            await session.commit()
        await dump_load_snapshot(sf, path=target, now=start, raise_on_error=True)
        first = json.loads(target.read_text())
        assert first["revision"] == 1
        assert first["lease_demand"] == 2
        await dump_load_snapshot(sf, path=target, now=start, raise_on_error=True)
        published = json.loads(target.read_text())
        assert published["revision"] == 2
        write_load_snapshot({**first, "written_at": 9_999.0, "lease_demand": 0, "in_flight": 0}, target)
        dropped = json.loads(target.read_text())
        assert dropped["revision"] == 2
        assert dropped["lease_demand"] == 2
        assert dropped["written_at"] == published["written_at"]
        await engine.dispose()

    asyncio.run(body())


def test_dump_load_snapshot_observes_stop_intent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scene.application.gpu_intent import IntentAction, write_gpu_intent

    intent_path = tmp_path / "gpu-intent.json"
    monkeypatch.setenv("ACX_GPU_INTENT_PATH", str(intent_path))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    write_gpu_intent(
        intent_path,
        action=IntentAction.STOP,
        ttl_seconds=1800,
        requested_by="operator",
        now=start,
    )

    async def body():
        engine, sf = await _sessionmaker()
        target = tmp_path / "describe-load.json"
        async with sf() as session:
            await DescribeOperationRepository(session, lease_seconds=180).accept(
                tenant_id=uuid.uuid4(), request_digest=_DIGEST_A, now=start
            )
            await session.commit()
        await dump_load_snapshot(sf, path=target, now=start, raise_on_error=True)
        loaded = json.loads(target.read_text())
        assert loaded["lease_demand"] == 0
        assert loaded["in_flight"] == 0
        assert _has_work(loaded) is False
        await engine.dispose()

    asyncio.run(body())


def test_periodic_pass_persists_first_ready_while_gpu_is_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    ready_at = start + timedelta(seconds=8)
    _publish_gpu_state(tmp_path, monkeypatch, now=ready_at, state="ready")

    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as session:
            repo = DescribeOperationRepository(session, lease_seconds=180)
            op = await repo.accept(tenant_id=tenant, request_digest=_DIGEST_A, now=start)
            await repo.associate_startup(
                tenant_id=tenant,
                operation_id=op.operation_id,
                startup_id="boot",
                started_at=start,
                now=start,
            )
            token = op.operation_id
            await session.commit()
        async with sf() as session:
            snap = await load_snapshot(session, now=ready_at)
            assert snap["lease_demand"] == 1
            stored = await session.get(DescribeOperation, (tenant, token))
            startup = await session.get(DescribeStartup, "boot")
            assert stored is not None and stored.first_ready_at is not None
            assert startup is not None and startup.first_ready_at is not None
        await engine.dispose()

    asyncio.run(body())


def test_sync_style_caller_stop_excludes_demand_without_deleting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scene.application.gpu_intent import IntentAction, write_gpu_intent

    intent_path = tmp_path / "gpu-intent.json"
    monkeypatch.setenv("ACX_GPU_INTENT_PATH", str(intent_path))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    write_gpu_intent(
        intent_path,
        action=IntentAction.STOP,
        ttl_seconds=1800,
        requested_by="operator",
        now=start,
    )

    async def body():
        engine, sf = await _sessionmaker()
        target = tmp_path / "describe-load.json"
        tenant = uuid.uuid4()
        async with sf() as session:
            op = await DescribeOperationRepository(session, lease_seconds=180).accept(
                tenant_id=tenant, request_digest=_DIGEST_A, now=start
            )
            token = op.operation_id
            await session.commit()
        async with sf() as session:
            snap = await load_snapshot(session, now=start)
            write_load_snapshot(snap, target)
            await session.commit()
        loaded = json.loads(target.read_text())
        assert loaded["lease_demand"] == 0
        assert loaded["in_flight"] == 0
        assert _has_work(loaded) is False
        async with sf() as session:
            lease = await session.get(DescribeDemandLease, (tenant, token))
            assert lease is not None and lease.state == DemandLeaseState.ACTIVE
        await engine.dispose()

    asyncio.run(body())


def test_sync_style_caller_lease_cap_excludes_demand_without_deleting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state_path = tmp_path / "gpu-state.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(state_path))
    state_path.write_text(json.dumps({"last_transition_reason": "lease_cap"}), encoding="utf-8")
    start = datetime(2026, 1, 1, tzinfo=UTC)

    async def body():
        engine, sf = await _sessionmaker()
        target = tmp_path / "describe-load.json"
        tenant = uuid.uuid4()
        async with sf() as session:
            op = await DescribeOperationRepository(session, lease_seconds=180).accept(
                tenant_id=tenant, request_digest=_DIGEST_A, now=start
            )
            token = op.operation_id
            await session.commit()
        async with sf() as session:
            snap = await load_snapshot(session, now=start)
            write_load_snapshot(snap, target)
            await session.commit()
        loaded = json.loads(target.read_text())
        assert loaded["lease_demand"] == 0
        assert loaded["in_flight"] == 0
        assert _has_work(loaded) is False
        async with sf() as session:
            lease = await session.get(DescribeDemandLease, (tenant, token))
            assert lease is not None and lease.state == DemandLeaseState.ACTIVE
        await engine.dispose()

    asyncio.run(body())


def test_load_snapshot_commit_failure_leaves_file_untouched_and_next_revision_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    async def body():
        engine, sf = await _sessionmaker()
        target = tmp_path / "describe-load.json"
        seed = {"queue_depth": 9, "in_flight": 0, "written_at": 1.0}
        target.write_text(json.dumps(seed), encoding="utf-8")
        start = datetime(2026, 1, 1, tzinfo=UTC)
        _publish_gpu_state(tmp_path, monkeypatch, now=start, state="stopped")
        async with sf() as session:
            await DescribeOperationRepository(session, lease_seconds=180).accept(
                tenant_id=uuid.uuid4(), request_digest=_DIGEST_A, now=start
            )
            await session.commit()
        async with sf() as session:

            async def boom() -> None:
                raise RuntimeError("injected commit failure")

            session.commit = boom  # type: ignore[method-assign]
            with pytest.raises(RuntimeError, match="injected commit failure"):
                await load_snapshot(session, now=start)
        assert json.loads(target.read_text()) == seed
        await dump_load_snapshot(sf, path=target, now=start, raise_on_error=True)
        loaded = json.loads(target.read_text())
        assert loaded["revision"] == 1
        assert loaded["lease_demand"] == 1
        assert loaded["in_flight"] == 1
        await engine.dispose()

    asyncio.run(body())


def test_older_publisher_write_is_dropped_after_newer_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def body():
        engine, sf = await _sessionmaker()
        target = tmp_path / "describe-load.json"
        start = datetime(2026, 1, 1, tzinfo=UTC)
        _publish_gpu_state(tmp_path, monkeypatch, now=start, state="stopped")
        async with sf() as session:
            await DescribeOperationRepository(session, lease_seconds=180).accept(
                tenant_id=uuid.uuid4(), request_digest=_DIGEST_A, now=start
            )
            await session.commit()
        a_read = asyncio.Event()
        b_published = asyncio.Event()

        async def publisher_a() -> None:
            async with sf() as session:
                snap = await load_snapshot(session, now=start)
            a_read.set()
            await b_published.wait()
            write_load_snapshot(snap, target)

        async def publisher_b() -> None:
            await a_read.wait()
            async with sf() as session:
                snap = await load_snapshot(session, now=start)
            write_load_snapshot(snap, target)
            b_published.set()

        await asyncio.gather(publisher_a(), publisher_b())
        loaded = json.loads(target.read_text())
        assert loaded["revision"] == 2
        assert loaded["lease_demand"] == 1
        assert loaded["in_flight"] == 1
        await engine.dispose()

    asyncio.run(body())


def test_maybe_dump_describe_load_drops_older_publish_after_demand_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Sync publisher path: older read is dropped after newer demand publishes."""
    from scene.interface_adapters.http.routers import describe as describe_router

    async def body():
        engine, sf = await _sessionmaker()
        target = tmp_path / "describe-load.json"
        monkeypatch.setenv("ACX_DESCRIBE_LOAD_PATH", str(target))
        start = datetime(2026, 1, 1, tzinfo=UTC)
        _publish_gpu_state(tmp_path, monkeypatch, now=start, state="stopped")
        async with sf() as session:
            await DescribeOperationRepository(session, lease_seconds=180).accept(
                tenant_id=uuid.uuid4(), request_digest=_DIGEST_A, now=start
            )
            await session.commit()
        a_read = asyncio.Event()
        b_published = asyncio.Event()
        real_load = describe_router.load_snapshot
        calls = 0

        async def gated_load(session, **kwargs):
            nonlocal calls
            kwargs.setdefault("now", start)
            snap = await real_load(session, **kwargs)
            calls += 1
            if calls == 1:
                a_read.set()
                await b_published.wait()
            return snap

        monkeypatch.setattr(describe_router, "load_snapshot", gated_load)

        async def publisher_a() -> None:
            await describe_router._maybe_dump_describe_load(sf)

        async def publisher_b() -> None:
            await a_read.wait()
            async with sf() as session:
                await DescribeOperationRepository(session, lease_seconds=180).accept(
                    tenant_id=uuid.uuid4(), request_digest=_DIGEST_B, now=start
                )
                await session.commit()
            await describe_router._maybe_dump_describe_load(sf)
            b_published.set()

        await asyncio.wait_for(asyncio.gather(publisher_a(), publisher_b()), timeout=5)
        loaded = json.loads(target.read_text())
        assert loaded["revision"] == 2
        assert loaded["lease_demand"] == 2
        assert loaded["in_flight"] == 2
        await engine.dispose()

    asyncio.run(body())


def test_load_snapshot_live_stop_cannot_be_disabled_by_false_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scene.application.gpu_intent import IntentAction, write_gpu_intent

    intent_path = tmp_path / "gpu-intent.json"
    monkeypatch.setenv("ACX_GPU_INTENT_PATH", str(intent_path))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    _publish_gpu_state(tmp_path, monkeypatch, now=start, state="stopped")
    write_gpu_intent(
        intent_path,
        action=IntentAction.STOP,
        ttl_seconds=1800,
        requested_by="operator",
        now=start,
    )

    async def body():
        engine, sf, tenant, token = await _one_active_lease(start)
        async with sf() as session:
            snap = await load_snapshot(session, now=start, stop_requested=False)
            assert snap["lease_demand"] == 0
            assert snap["in_flight"] == 0
            assert _has_work(snap) is False
            lease = await session.get(DescribeDemandLease, (tenant, token))
            assert lease is not None and lease.state == DemandLeaseState.ACTIVE
        await engine.dispose()

    asyncio.run(body())


def test_load_snapshot_live_lease_cap_cannot_be_disabled_by_false_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    _publish_gpu_state(
        tmp_path,
        monkeypatch,
        now=start,
        state="stopped",
        last_transition_reason="lease_cap",
    )

    async def body():
        engine, sf, tenant, token = await _one_active_lease(start)
        async with sf() as session:
            snap = await load_snapshot(session, now=start, max_lease_reached=False)
            assert snap["lease_demand"] == 0
            assert snap["in_flight"] == 0
            assert _has_work(snap) is False
            lease = await session.get(DescribeDemandLease, (tenant, token))
            assert lease is not None and lease.state == DemandLeaseState.ACTIVE
        await engine.dispose()

    asyncio.run(body())


def test_completed_and_rejected_leases_do_not_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def body():
        engine, sf = await _sessionmaker()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        observed = start + timedelta(seconds=2)
        _publish_gpu_state(tmp_path, monkeypatch, now=observed, state="stopped")
        tenant = uuid.uuid4()
        async with sf() as session:
            repo = DescribeOperationRepository(session, lease_seconds=60)
            completed = await repo.accept(tenant_id=tenant, request_digest=_DIGEST_A, now=start)
            await repo.observe_ready(
                tenant_id=tenant, operation_id=completed.operation_id, now=start + timedelta(seconds=1)
            )
            await repo.complete(
                tenant_id=tenant,
                operation_id=completed.operation_id,
                processing_ms=1,
                server_elapsed_ms=2,
                now=start + timedelta(seconds=2),
            )
            expired = await repo.accept(tenant_id=tenant, request_digest=_DIGEST_B, now=start)
            await repo.active_demand_count(now=start + timedelta(seconds=60))
            with pytest.raises(OperationExpiredError):
                await repo.accept(
                    tenant_id=tenant,
                    request_digest=_DIGEST_B,
                    operation_id=expired.operation_id,
                    now=start + timedelta(seconds=61),
                )
            await repo.accept(tenant_id=uuid.uuid4(), request_digest=_DIGEST_C, now=start + timedelta(seconds=2))
            await session.commit()
        async with sf() as session:
            snap = await load_snapshot(session, now=start + timedelta(seconds=2))
            assert snap["lease_demand"] == 1
            assert snap["in_flight"] == 1
        await engine.dispose()

    asyncio.run(body())


async def _one_active_lease(now: datetime):
    engine, sf = await _sessionmaker()
    tenant = uuid.uuid4()
    async with sf() as session:
        op = await DescribeOperationRepository(session, lease_seconds=180).accept(
            tenant_id=tenant, request_digest=_DIGEST_A, now=now
        )
        token = op.operation_id
        await session.commit()
    return engine, sf, tenant, token


def test_load_snapshot_unknown_gpu_state_excludes_demand_without_deleting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def body():
        start = datetime(2026, 1, 1, tzinfo=UTC)
        monkeypatch.setenv("ACX_GPU_STATE_PATH", str(tmp_path / "missing-gpu-state.json"))
        engine, sf, tenant, token = await _one_active_lease(start)
        async with sf() as session:
            snap = await load_snapshot(session, now=start)
            assert snap["lease_demand"] == 0
            assert snap["in_flight"] == 0
            assert _has_work(snap) is False
            lease = await session.get(DescribeDemandLease, (tenant, token))
            assert lease is not None and lease.state == DemandLeaseState.ACTIVE
        await engine.dispose()

    asyncio.run(body())


def test_load_snapshot_stale_gpu_state_excludes_demand_without_deleting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def body():
        start = datetime(2026, 1, 1, tzinfo=UTC)
        _publish_gpu_state(
            tmp_path,
            monkeypatch,
            now=start,
            state="stopped",
            written_at=start.timestamp() - 181.0,
        )
        engine, sf, tenant, token = await _one_active_lease(start)
        async with sf() as session:
            snap = await load_snapshot(session, now=start)
            assert snap["lease_demand"] == 0
            assert snap["in_flight"] == 0
            assert _has_work(snap) is False
            lease = await session.get(DescribeDemandLease, (tenant, token))
            assert lease is not None and lease.state == DemandLeaseState.ACTIVE
        await engine.dispose()

    asyncio.run(body())


def test_load_snapshot_unreadable_gpu_state_excludes_demand_without_deleting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def body():
        start = datetime(2026, 1, 1, tzinfo=UTC)
        _publish_gpu_state(tmp_path, monkeypatch, now=start, raw="{not-json")
        engine, sf, tenant, token = await _one_active_lease(start)
        async with sf() as session:
            snap = await load_snapshot(session, now=start)
            assert snap["lease_demand"] == 0
            assert snap["in_flight"] == 0
            assert _has_work(snap) is False
            lease = await session.get(DescribeDemandLease, (tenant, token))
            assert lease is not None and lease.state == DemandLeaseState.ACTIVE
        await engine.dispose()

    asyncio.run(body())


def test_load_snapshot_lease_cap_then_unknown_still_excludes_demand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def body():
        start = datetime(2026, 1, 1, tzinfo=UTC)
        path = _publish_gpu_state(
            tmp_path,
            monkeypatch,
            now=start,
            state="stopped",
            last_transition_reason="lease_cap",
        )
        engine, sf, tenant, token = await _one_active_lease(start)
        async with sf() as session:
            capped = await load_snapshot(session, now=start)
            assert capped["lease_demand"] == 0
            assert _has_work(capped) is False
        path.write_text(json.dumps({"written_at": start.timestamp()}), encoding="utf-8")
        async with sf() as session:
            unknown = await load_snapshot(session, now=start)
            assert unknown["lease_demand"] == 0
            assert unknown["in_flight"] == 0
            assert _has_work(unknown) is False
            lease = await session.get(DescribeDemandLease, (tenant, token))
            assert lease is not None and lease.state == DemandLeaseState.ACTIVE
        await engine.dispose()

    asyncio.run(body())


def test_load_snapshot_stopped_auto_counts_active_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def body():
        start = datetime(2026, 1, 1, tzinfo=UTC)
        _publish_gpu_state(tmp_path, monkeypatch, now=start, state="stopped", last_transition_reason="work")
        engine, sf, tenant, token = await _one_active_lease(start)
        async with sf() as session:
            snap = await load_snapshot(session, now=start)
            assert snap["lease_demand"] == 1
            assert snap["in_flight"] == 1
            assert _has_work(snap) is True
            lease = await session.get(DescribeDemandLease, (tenant, token))
            assert lease is not None and lease.state == DemandLeaseState.ACTIVE
        await engine.dispose()

    asyncio.run(body())


def test_demand_lease_bounds_accept_legal_deployed_defaults():
    bounds = validate_demand_lease_bounds()
    assert bounds.lease_seconds == 180.0
    assert bounds.refresh_seconds + bounds.publication_delay_seconds < bounds.freshness_seconds


def test_demand_lease_bounds_reject_lease_not_exceeding_poll_budget():
    with pytest.raises(ValueError, match=r"P\+J\+D"):
        _legal_bounds(lease_seconds=75.0).validate()


def test_demand_lease_bounds_reject_non_finite_values():
    with pytest.raises(ValueError, match="finite"):
        _legal_bounds(lease_seconds=math.nan).validate()
    with pytest.raises(ValueError, match="finite"):
        _legal_bounds(refresh_seconds=math.inf).validate()


def test_run_startup_load_snapshot_rejects_illegal_bounds_before_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(load_mod, "DEMAND_LEASE_SECONDS", 1.0)

    async def body():
        engine, sf = await _sessionmaker()
        target = tmp_path / "describe-load.json"
        with pytest.raises(ValueError, match=r"P\+J\+D"):
            await run_startup_load_snapshot(sf, path=target)
        assert not target.exists()
        await engine.dispose()

    asyncio.run(body())
