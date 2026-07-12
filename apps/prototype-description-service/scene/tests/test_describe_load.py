"""VLM-5 Slice 3: DB-derived load snapshot for the GPU idle reaper.

Key set, atomic write, single-run-only counts, and RLS-bypass discipline
[DIAG-02], [SEC-01], [DATA-16].
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import scene.application.describe_load as load_mod
from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from scene.application.describe_load import load_snapshot, write_load_snapshot
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import DescribeItemStatus


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
            assert set(snap) == {"queue_depth", "in_flight", "written_at"}
            assert snap["queue_depth"] == 2
            assert snap["in_flight"] == 1
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
