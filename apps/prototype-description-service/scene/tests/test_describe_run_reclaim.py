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
from recognition.tests.support.health_session import install_healthy_observability_session
from scene.application.describe_run_repository import (
    DescribeRunRepository,
    run_startup_reclaim,
)
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus
from scene.tests.test_describe_run_repository import _sessionmaker


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
    install_healthy_observability_session(app)
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
    install_healthy_observability_session(app)
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
    install_healthy_observability_session(app)
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


async def _usage_sessionmaker():
    import os
    import tempfile
    from typing import cast

    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from db.models import UsageReservation
    from db.models.base_imports import Base
    from db.models.jobs import IdentityScanJob, IdentityScanJobItem
    from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
    from db.models.scene import DescribeRun, DescribeRunItem
    from db.models.tenant import Tenant

    path = os.path.join(tempfile.gettempdir(), f"app1_reclaim_usage_{uuid.uuid4().hex}.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=cast(
                list[Table],
                [
                    Tenant.__table__,
                    TenantEntitlement.__table__,
                    UsageReservation.__table__,
                    GlobalUsageAdmissionState.__table__,
                    DescribeRun.__table__,
                    DescribeRunItem.__table__,
                    IdentityScanJob.__table__,
                    IdentityScanJobItem.__table__,
                ],
            ),
        )
    return engine, async_sessionmaker(engine, expire_on_commit=False), path


async def _seed_usage_tenant(session):
    from datetime import UTC, datetime, timedelta

    from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
    from db.models.tenant import Tenant
    from recognition.domain.portal_contracts import (
        DEFAULT_GLOBAL_CONFIG_VERSION,
        DEFAULT_GLOBAL_DAILY_COST_LIMIT,
        DEFAULT_GLOBAL_FENCE_EPOCH,
        DEFAULT_GLOBAL_INFLIGHT_LIMIT,
        DEFAULT_GLOBAL_QUEUE_BYTE_LIMIT,
        DEFAULT_GLOBAL_QUEUE_LIMIT,
        GLOBAL_USAGE_ADMISSION_STATE_ID,
        EntitlementStatus,
    )

    tenant = Tenant(id=uuid.uuid4(), site_url=f"https://{uuid.uuid4().hex}.example.test")
    session.add(tenant)
    await session.flush()
    now = datetime.now(tz=UTC)
    session.add(
        TenantEntitlement(
            tenant_id=tenant.id,
            plan_code="beta",
            allowance_version="reclaim-v1",
            allowance_jobs=20,
            period_start=now - timedelta(minutes=1),
            period_end=now + timedelta(hours=1),
            status=EntitlementStatus.BETA_ACTIVE,
            source="unit-test",
        )
    )
    session.add(
        GlobalUsageAdmissionState(
            id=GLOBAL_USAGE_ADMISSION_STATE_ID,
            period_start=datetime(now.year, now.month, now.day, tzinfo=UTC),
            period_end=datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1),
            daily_cost_limit=DEFAULT_GLOBAL_DAILY_COST_LIMIT,
            daily_cost_units=0,
            inflight_limit=DEFAULT_GLOBAL_INFLIGHT_LIMIT,
            inflight_units=0,
            queue_limit=DEFAULT_GLOBAL_QUEUE_LIMIT,
            queue_depth=0,
            queue_byte_limit=DEFAULT_GLOBAL_QUEUE_BYTE_LIMIT,
            queue_bytes=0,
            stop_requested=False,
            fence_epoch=DEFAULT_GLOBAL_FENCE_EPOCH,
            config_version=DEFAULT_GLOBAL_CONFIG_VERSION,
            updated_at=now,
        )
    )
    await session.flush()
    return tenant


def test_startup_reclaim_releases_queued_and_charges_started_run():
    async def body():
        from datetime import UTC, datetime

        from db.models import UsageReservation
        from recognition.application.services.usage_admission_service import UsageAdmissionService
        from recognition.domain.portal_contracts import UsageReservationStatus
        from scene.domain.describe_run import DescribeItemStatus

        engine, sf, path = await _usage_sessionmaker()
        try:
            async with sf() as session:
                tenant = await _seed_usage_tenant(session)
                repo = DescribeRunRepository(session, max_items=2)
                queued_id = await repo.create_run(tenant_id=tenant.id, media_ids=[1])
                running_id = await repo.create_run(tenant_id=tenant.id, media_ids=[2])
                await repo.mark_item(
                    tenant_id=tenant.id,
                    run_id=running_id,
                    media_id=2,
                    status=DescribeItemStatus.RUNNING,
                )
                running = await repo.get_run(tenant_id=tenant.id, run_id=running_id)
                running.status = DescribeRunStatus.RUNNING
                running.started_at = datetime.now(tz=UTC)
                queued_ticket = await UsageAdmissionService(session).reserve(
                    tenant.id,
                    idempotency_key="op-queued",
                    job_id=str(queued_id),
                    cost_units=1,
                    operation_id="op-queued",
                    request_fingerprint="fp-queued",
                )
                running_ticket = await UsageAdmissionService(session).reserve(
                    tenant.id,
                    idempotency_key="op-running",
                    job_id=str(running_id),
                    cost_units=1,
                    operation_id="op-running",
                    request_fingerprint="fp-running",
                )
                await session.commit()

            reclaimed = await run_startup_reclaim(sf)
            assert reclaimed == 2

            async with sf() as session:
                queued_row = await session.get(UsageReservation, queued_ticket.reservation_id)
                running_row = await session.get(UsageReservation, running_ticket.reservation_id)
                queued = await DescribeRunRepository(session).get_run(tenant_id=tenant.id, run_id=queued_id)
                running = await DescribeRunRepository(session).get_run(tenant_id=tenant.id, run_id=running_id)
                assert queued is not None and queued.status == DescribeRunStatus.COMPLETED_WITH_ERRORS
                assert running is not None and running.status == DescribeRunStatus.COMPLETED_WITH_ERRORS
                assert queued_row is not None and queued_row.status == UsageReservationStatus.RELEASED
                assert running_row is not None and running_row.status == UsageReservationStatus.COMMITTED
        finally:
            await engine.dispose()
            os.unlink(path)

    import os

    asyncio.run(body())


def test_startup_reclaim_surfaces_fail_closed_recovery(monkeypatch):
    async def body():
        from recognition.application.services import usage_settlement_service as settlement_mod
        from recognition.application.services.usage_settlement_service import SettlementOutcome, SettlementResult

        async def _fail_closed(*_args, **_kwargs):
            return SettlementResult(SettlementOutcome.FAIL_CLOSED, detail="forced reclaim fail-closed")

        monkeypatch.setattr(settlement_mod, "recover_usage_job", _fail_closed)
        engine, sf, path = await _usage_sessionmaker()
        try:
            async with sf() as session:
                tenant = await _seed_usage_tenant(session)
                repo = DescribeRunRepository(session, max_items=1)
                await repo.create_run(tenant_id=tenant.id, media_ids=[7])
                await session.commit()
            with pytest.raises(RuntimeError, match="FAIL_CLOSED|fail-closed|rejected"):
                await run_startup_reclaim(sf)
        finally:
            await engine.dispose()
            os.unlink(path)

    import os

    asyncio.run(body())
