"""WBUX-4 INT-02: startup reclaim of interrupted runs.

The bulk worker runs in-process (FastAPI background task) and does not survive
a service restart. Any run left PENDING/RUNNING at startup is orphaned — no
worker will ever finish it, so `_recompute_run_totals` never reaches terminal
and the frontend would poll it indefinitely. Startup reclaim marks such runs
terminal (FAILED) so they stop being polled and are reported honestly.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

import scene.application.describe_run_repository as repo_mod
from scene.application.describe_run_repository import (
    DescribeRunRepository,
    run_startup_reclaim,
)
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus
from scene.tests.test_describe_run_repository import _sessionmaker


def _install_healthy_observability_session(app) -> None:
    """Pin startup health assertions to the pool-aware liveness contract."""
    from unittest.mock import AsyncMock, MagicMock

    from db.settings import get_database_settings
    from recognition.interface_adapters.http import deps as dependencies

    dim = int(get_database_settings().pgvector_dimension)
    rows = [
        ("media_identities", "embedding", dim),
        ("identity_cluster_representatives", "embedding", dim),
        ("mv_identity_cluster_centroids", "centroid", dim),
    ]
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    class _NestedTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    session.begin_nested = MagicMock(return_value=_NestedTransaction())

    async def _session_yielder():
        yield session

    app.dependency_overrides[dependencies.get_observability_session] = _session_yielder


def test_reclaim_derives_terminal_status_and_preserves_completed_items():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=3)
            # 102 carries real stranded image bytes to prove the clearing path runs.
            run_id = await repo.create_run(
                tenant_id=tenant,
                media_ids=[101, 102],
                images={102: (b"strandedbytes", "image/png")},
            )
            # 101 finished before the crash; 102 was still queued.
            await repo.record_item_result(
                tenant_id=tenant,
                run_id=run_id,
                media_id=101,
                alt_text_draft="done",
                caption="c",
                provenance={"adapter": "florence"},
            )
            await repo.mark_item(tenant_id=tenant, run_id=run_id, media_id=101, status=DescribeItemStatus.COMPLETED)
            # Sanity: the stranded bytes are actually present before reclaim.
            queued = {i.media_id: i for i in await repo.list_run_items(tenant_id=tenant, run_id=run_id)}
            assert queued[102].image_bytes == b"strandedbytes"
            # Run left non-terminal (RUNNING) as if the process died mid-run.
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            run.status = DescribeRunStatus.RUNNING
            await s.commit()

        reclaimed = await run_startup_reclaim(sf)
        assert reclaimed == 1

        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=3)
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            items = {i.media_id: i for i in await repo.list_run_items(tenant_id=tenant, run_id=run_id)}

        # One completed + one force-failed item -> honest COMPLETED_WITH_ERRORS,
        # not a blanket FAILED (S5-01).
        assert run.status == DescribeRunStatus.COMPLETED_WITH_ERRORS
        assert run.completed_at is not None
        assert run.error_message
        # completed item kept its draft; queued item failed; bytes cleared.
        assert items[101].status == DescribeItemStatus.COMPLETED
        assert items[101].alt_text_draft == "done"
        assert items[102].status == DescribeItemStatus.FAILED
        assert items[101].image_bytes is None and items[102].image_bytes is None
        # counters honest after reclaim.
        assert run.completed_items == 1
        assert run.failed_items == 1

        await engine.dispose()

    asyncio.run(body())


def test_reclaim_derives_completed_when_all_items_completed_before_crash():
    """D2-02: all items COMPLETED before the crash, no failures -> the run
    derives to COMPLETED (not a blanket FAILED). This is the headline new
    outcome of the parity gate: a fully-successful run whose row was left
    non-terminal by the restart reclaims honestly to COMPLETED."""

    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=2)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[401, 402])
            for media_id in (401, 402):
                await repo.record_item_result(
                    tenant_id=tenant,
                    run_id=run_id,
                    media_id=media_id,
                    alt_text_draft="done",
                    caption="c",
                    provenance={"adapter": "florence"},
                )
                await repo.mark_item(
                    tenant_id=tenant, run_id=run_id, media_id=media_id, status=DescribeItemStatus.COMPLETED
                )
            # Simulate a crash that left the run row non-terminal despite every
            # item already being COMPLETED.
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            run.status = DescribeRunStatus.RUNNING
            await s.commit()

        reclaimed = await run_startup_reclaim(sf)
        assert reclaimed == 1

        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=2)
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            items = {i.media_id: i for i in await repo.list_run_items(tenant_id=tenant, run_id=run_id)}

        assert run.status == DescribeRunStatus.COMPLETED
        assert run.completed_at is not None
        assert run.completed_items == 2
        assert run.failed_items == 0
        assert all(i.status == DescribeItemStatus.COMPLETED for i in items.values())
        await engine.dispose()

    asyncio.run(body())


def test_reclaim_derives_cancelled_when_all_items_skipped_before_crash():
    """D2-02: all items SKIPPED, nothing completed or failed -> per
    terminal_run_status this maps to CANCELLED (cancel-before-run), a distinct
    terminal status from FAILED/COMPLETED."""

    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=2)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[501, 502])
            for media_id in (501, 502):
                await repo.mark_item(
                    tenant_id=tenant, run_id=run_id, media_id=media_id, status=DescribeItemStatus.SKIPPED
                )
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            run.status = DescribeRunStatus.RUNNING
            await s.commit()

        reclaimed = await run_startup_reclaim(sf)
        assert reclaimed == 1

        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=2)
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            items = {i.media_id: i for i in await repo.list_run_items(tenant_id=tenant, run_id=run_id)}

        assert run.status == DescribeRunStatus.CANCELLED
        assert run.skipped_items == 2
        assert all(i.status == DescribeItemStatus.SKIPPED for i in items.values())
        await engine.dispose()

    asyncio.run(body())


def test_reclaim_honors_cancel_requested_as_cancelled():
    """S5-04: a run with cancel_requested reclaims to CANCELLED, not FAILED."""

    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=2)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[301])
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            run.status = DescribeRunStatus.RUNNING
            run.cancel_requested = True
            await s.commit()

        reclaimed = await run_startup_reclaim(sf)
        assert reclaimed == 1

        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=tenant, run_id=run_id)
        assert run.status == DescribeRunStatus.CANCELLED
        await engine.dispose()

    asyncio.run(body())


class _NotBypassedResult:
    def scalar(self):
        return None  # current_setting('app.bypass_rls', true) unset -> NULL


class _NotBypassedSession:
    """Minimal async session whose bypass probe reports RLS bypass is NOT active."""

    async def execute(self, *_args, **_kwargs):
        return _NotBypassedResult()


def test_reclaim_fails_closed_when_rls_bypass_not_active(monkeypatch):
    """S5-02/S5-03b: on a non-SQLite session without RLS bypass, reclaim raises
    rather than running an under-scoped partial sweep. SQLite no-ops the real
    guard, so force the Postgres branch via is_sqlite=False."""
    monkeypatch.setattr(repo_mod, "is_sqlite", lambda _session: False)
    repo = DescribeRunRepository(_NotBypassedSession(), max_items=1)
    with pytest.raises(RuntimeError, match="RLS-bypassed system session"):
        asyncio.run(repo.reclaim_interrupted_runs())


def test_startup_reclaim_failure_does_not_block_boot_and_is_wired(monkeypatch):
    """S5-03a / VLM5-S4A-BR-02: reclaim exception must not block boot, and purge
    + snapshot still run independently afterward (each independently best-effort)."""
    from fastapi.testclient import TestClient

    from api.main import create_app
    from scene.application import describe_load as load_mod

    called = {"n": 0}
    order: list[str] = []

    async def boom(*_args, **_kwargs):
        called["n"] += 1
        raise RuntimeError("reclaim boom")

    async def track_purge(*_args, **_kwargs):
        order.append("purge")
        return 0

    async def track_snapshot(*_args, **_kwargs):
        order.append("snapshot")
        return None

    monkeypatch.setattr(repo_mod, "run_startup_reclaim", boom)
    monkeypatch.setattr(repo_mod, "run_startup_retention_purge", track_purge)
    monkeypatch.setattr(load_mod, "run_startup_load_snapshot", track_snapshot)

    app = create_app()
    _install_healthy_observability_session(app)
    with TestClient(app) as client:  # __enter__ runs the lifespan startup
        resp = client.get("/health")
        assert resp.status_code == 200, resp.text
    # The lifespan invoked reclaim exactly once (wired) and swallowed the error (boot survived).
    assert called["n"] == 1
    # VLM5-S4A-BR-02: purge and snapshot still execute after reclaim raises.
    assert order == ["purge", "snapshot"]


def test_startup_boot_order_reclaim_then_purge_then_snapshot(monkeypatch):
    """VLM-5 Slice 4: lifespan order is reclaim → purge → snapshot, all wired."""
    from fastapi.testclient import TestClient

    from api.main import create_app
    from scene.application import describe_load as load_mod

    order: list[str] = []

    async def reclaim_ok(*_args, **_kwargs):
        order.append("reclaim")
        return 0

    async def purge_ok(*_args, **_kwargs):
        order.append("purge")
        return 0

    async def snapshot_ok(*_args, **_kwargs):
        order.append("snapshot")
        return None

    monkeypatch.setattr(repo_mod, "run_startup_reclaim", reclaim_ok)
    monkeypatch.setattr(repo_mod, "run_startup_retention_purge", purge_ok)
    monkeypatch.setattr(load_mod, "run_startup_load_snapshot", snapshot_ok)

    app = create_app()
    _install_healthy_observability_session(app)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert order == ["reclaim", "purge", "snapshot"]


def test_startup_purge_or_snapshot_failure_does_not_block_boot(monkeypatch):
    """VLM-5 Slice 4: purge/snapshot exceptions are best-effort and never block boot."""
    from fastapi.testclient import TestClient

    from api.main import create_app
    from scene.application import describe_load as load_mod

    order: list[str] = []

    async def reclaim_ok(*_args, **_kwargs):
        order.append("reclaim")
        return 0

    async def purge_boom(*_args, **_kwargs):
        order.append("purge")
        raise RuntimeError("purge boom")

    async def snapshot_boom(*_args, **_kwargs):
        order.append("snapshot")
        raise RuntimeError("snapshot boom")

    monkeypatch.setattr(repo_mod, "run_startup_reclaim", reclaim_ok)
    monkeypatch.setattr(repo_mod, "run_startup_retention_purge", purge_boom)
    monkeypatch.setattr(load_mod, "run_startup_load_snapshot", snapshot_boom)

    app = create_app()
    _install_healthy_observability_session(app)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    # Snapshot still runs after purge failure; both failures are swallowed.
    assert order == ["reclaim", "purge", "snapshot"]


def test_reclaim_leaves_terminal_runs_untouched():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=1)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[201])
            await repo.mark_item(tenant_id=tenant, run_id=run_id, media_id=201, status=DescribeItemStatus.COMPLETED)
            await s.commit()

        reclaimed = await run_startup_reclaim(sf)
        assert reclaimed == 0

        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=tenant, run_id=run_id)
        assert run.status != DescribeRunStatus.FAILED
        await engine.dispose()

    asyncio.run(body())
