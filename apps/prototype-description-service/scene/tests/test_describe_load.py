"""VLM-5 Slice 3: DB-derived load snapshot for the GPU idle reaper.

Key set, atomic write, single-run-only counts, and RLS-bypass discipline
[DIAG-02], [SEC-01], [DATA-16].
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import scene.application.describe_load as load_mod
from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from scene.application.describe_load import (
    batch_in_progress,
    dump_load_snapshot,
    load_snapshot,
    refresh_load_snapshot_loop,
    resolve_load_path,
    resolve_load_refresh_seconds,
    run_startup_load_snapshot,
    write_load_snapshot,
)
from scene.application.describe_run_repository import (
    DescribeRunRepository,
    run_startup_retention_purge,
)
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus


async def _sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=cast(list[Table], [DescribeRun.__table__, DescribeRunItem.__table__]),
        )
    return engine, async_sessionmaker(engine, expire_on_commit=False)


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
            assert set(snap) == {
                "queue_depth",
                "in_flight",
                "batch_in_progress",
                "written_at",
            }
            assert snap["queue_depth"] == 2
            assert snap["in_flight"] == 1
            # The bulk run above is still non-terminal: excluded from the item
            # counts, but it must surface on its own key (GPUW-1).
            assert snap["batch_in_progress"] is True
            assert isinstance(snap["written_at"], float)
            assert snap["written_at"] > 0

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
        assert set(loaded) == {
            "queue_depth",
            "in_flight",
            "batch_in_progress",
            "written_at",
        }
        assert loaded["queue_depth"] == 1
        assert loaded["in_flight"] == 1
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
        assert set(loaded) == {
            "queue_depth",
            "in_flight",
            "batch_in_progress",
            "written_at",
        }
        assert loaded["queue_depth"] == 0
        assert loaded["in_flight"] == 0
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


def test_dump_load_snapshot_can_make_failures_visible_to_supervisor():
    class BrokenSessionFactory:
        def __call__(self):
            raise RuntimeError("database unavailable")

    async def body():
        factory = BrokenSessionFactory()
        # Describe request/worker call sites remain failure-isolated.
        await dump_load_snapshot(factory)
        # The refresher's strict mode must be able to see and report the same
        # failure; otherwise its cycle-level warning is dead code.
        with pytest.raises(RuntimeError, match="database unavailable"):
            await dump_load_snapshot(factory, raise_on_error=True)

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
