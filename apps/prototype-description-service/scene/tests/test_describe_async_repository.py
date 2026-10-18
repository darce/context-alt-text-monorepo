"""VLM-5 Slice 1: single-run async describe repository + status projection.

Covers create→provisional→final/degraded/failed lifecycle, total projection over
every DescribeItemStatus, cross-tenant purge under RLS bypass, and reclaim that
preserves provisional visual_facts as degraded [TEST-13], [DATA-14], [RES-07], [SEC-01].
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import CheckConstraint, Column, Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.types import TypeDecorator

import scene.application.describe_run_repository as repo_mod
from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import (
    DescribeItemStatus,
    DescribeJobStatus,
    DescribeRunStatus,
    RunKind,
    describe_job_error,
    describe_job_status,
)
from scene.domain.description import DescriptionResultTier

identity_schema = importlib.import_module("db.migrations.versions.001_identity_schema")


async def _sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=cast(list[Table], [DescribeRun.__table__, DescribeRunItem.__table__]),
        )
    return engine, async_sessionmaker(engine, expire_on_commit=False)


_PROVISIONAL_FACTS = {"tier": "provisional_cpu", "alt_text_draft": "cpu draft", "caption": "c"}
_FINAL_FACTS = {"tier": "final_gpu", "alt_text_draft": "gpu draft", "caption": "c"}


def test_create_single_run_then_provisional_then_final():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_single_run(
                tenant_id=tenant,
                media_id=42,
                image_bytes=b"img-bytes",
                image_content_type="image/jpeg",
            )
            await s.commit()

        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            item = await repo.get_single_run_item(tenant_id=tenant, run_id=run_id)
            assert run is not None
            assert run.run_kind == RunKind.SINGLE
            assert run.total_items == 1
            assert item is not None
            assert item.media_id == 42
            assert item.image_bytes == b"img-bytes"
            assert item.status == DescribeItemStatus.QUEUED
            assert describe_job_status(item) is DescribeJobStatus.QUEUED

            await repo.mark_item(
                tenant_id=tenant,
                run_id=run_id,
                media_id=42,
                status=DescribeItemStatus.RUNNING,
            )
            await repo.set_item_provisional(
                tenant_id=tenant,
                run_id=run_id,
                media_id=42,
                visual_facts=_PROVISIONAL_FACTS,
            )
            await s.commit()

        async with sf() as s:
            repo = DescribeRunRepository(s)
            item = await repo.get_single_run_item(tenant_id=tenant, run_id=run_id)
            assert item is not None
            assert item.status == DescribeItemStatus.RUNNING
            assert item.visual_facts == _PROVISIONAL_FACTS
            assert item.tier == DescriptionResultTier.PROVISIONAL_CPU
            assert item.result_generation == 1
            assert item.image_bytes == b"img-bytes"  # kept for GPU supersede
            assert describe_job_status(item) is DescribeJobStatus.PROVISIONAL

            await repo.set_item_final(
                tenant_id=tenant,
                run_id=run_id,
                media_id=42,
                visual_facts=_FINAL_FACTS,
            )
            await s.commit()

        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            item = await repo.get_single_run_item(tenant_id=tenant, run_id=run_id)
            assert run is not None and item is not None
            assert item.status == DescribeItemStatus.COMPLETED
            assert item.visual_facts == _FINAL_FACTS
            assert item.tier == DescriptionResultTier.FINAL_GPU
            assert item.result_generation == 2
            assert item.image_bytes is None
            assert run.status == DescribeRunStatus.COMPLETED
            assert describe_job_status(item) is DescribeJobStatus.FINAL
        await engine.dispose()

    asyncio.run(body())


def test_set_item_degraded_and_failed_lifecycle():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()

        # Degraded path: provisional then GPU fails.
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_single_run(tenant_id=tenant, media_id=7, image_bytes=b"x")
            await repo.mark_item(tenant_id=tenant, run_id=run_id, media_id=7, status=DescribeItemStatus.RUNNING)
            await repo.set_item_provisional(
                tenant_id=tenant,
                run_id=run_id,
                media_id=7,
                visual_facts=_PROVISIONAL_FACTS,
            )
            await repo.set_item_degraded(
                tenant_id=tenant,
                run_id=run_id,
                media_id=7,
                error="gpu timeout",
            )
            await s.commit()

        async with sf() as s:
            repo = DescribeRunRepository(s)
            item = await repo.get_single_run_item(tenant_id=tenant, run_id=run_id)
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            assert item is not None and run is not None
            assert item.status == DescribeItemStatus.COMPLETED
            assert item.visual_facts == _PROVISIONAL_FACTS
            assert item.tier == DescriptionResultTier.PROVISIONAL_CPU
            assert item.last_error == "gpu timeout"
            assert item.image_bytes is None
            assert describe_job_status(item) is DescribeJobStatus.DEGRADED
            assert run.status == DescribeRunStatus.COMPLETED

        # Failed path: no provisional before failure.
        async with sf() as s:
            repo = DescribeRunRepository(s)
            fail_id = await repo.create_single_run(tenant_id=tenant, media_id=8, image_bytes=b"y")
            await repo.mark_item(tenant_id=tenant, run_id=fail_id, media_id=8, status=DescribeItemStatus.RUNNING)
            await repo.set_item_failed(
                tenant_id=tenant,
                run_id=fail_id,
                media_id=8,
                error="cpu boom",
            )
            await s.commit()

        async with sf() as s:
            repo = DescribeRunRepository(s)
            item = await repo.get_single_run_item(tenant_id=tenant, run_id=fail_id)
            assert item is not None
            assert item.status == DescribeItemStatus.FAILED
            assert item.last_error == "cpu boom"
            assert item.image_bytes is None
            assert describe_job_status(item) is DescribeJobStatus.FAILED
            assert describe_job_error(item) == "cpu boom"
        await engine.dispose()

    asyncio.run(body())


def test_describe_job_status_is_total_over_every_item_status():
    """One case per DescribeItemStatus member — projection must never raise (design g)."""

    def _item(**kwargs):
        defaults = {
            "status": DescribeItemStatus.QUEUED,
            "visual_facts": None,
            "tier": None,
            "result_generation": 0,
            "last_error": None,
        }
        defaults.update(kwargs)

        class _I:
            pass

        obj = _I()
        for k, v in defaults.items():
            setattr(obj, k, v)
        return obj

    assert describe_job_status(_item(status=DescribeItemStatus.QUEUED)) is DescribeJobStatus.QUEUED
    assert describe_job_error(_item(status=DescribeItemStatus.QUEUED)) is None

    running_bare = _item(status=DescribeItemStatus.RUNNING)
    assert describe_job_status(running_bare) is DescribeJobStatus.RUNNING

    running_prov = _item(
        status=DescribeItemStatus.RUNNING,
        visual_facts=_PROVISIONAL_FACTS,
        tier=DescriptionResultTier.PROVISIONAL_CPU,
        result_generation=1,
    )
    assert describe_job_status(running_prov) is DescribeJobStatus.PROVISIONAL

    completed_final = _item(
        status=DescribeItemStatus.COMPLETED,
        visual_facts=_FINAL_FACTS,
        tier=DescriptionResultTier.FINAL_GPU,
        result_generation=2,
    )
    assert describe_job_status(completed_final) is DescribeJobStatus.FINAL

    completed_degraded = _item(
        status=DescribeItemStatus.COMPLETED,
        visual_facts=_PROVISIONAL_FACTS,
        tier=DescriptionResultTier.PROVISIONAL_CPU,
        result_generation=1,
        last_error="interrupted by service restart",
    )
    assert describe_job_status(completed_degraded) is DescribeJobStatus.DEGRADED
    assert describe_job_error(completed_degraded) == "interrupted by service restart"

    failed = _item(status=DescribeItemStatus.FAILED, last_error="x")
    assert describe_job_status(failed) is DescribeJobStatus.FAILED
    assert describe_job_error(failed) == "x"

    skipped = _item(status=DescribeItemStatus.SKIPPED)
    assert describe_job_status(skipped) is DescribeJobStatus.FAILED
    assert describe_job_error(skipped) == "cancelled"

    # Totality: every enum member is exercised above.
    exercised = {
        DescribeItemStatus.QUEUED,
        DescribeItemStatus.RUNNING,
        DescribeItemStatus.COMPLETED,
        DescribeItemStatus.FAILED,
        DescribeItemStatus.SKIPPED,
    }
    assert exercised == set(DescribeItemStatus)


def test_purge_expired_single_runs_cross_tenant_and_requires_bypass(monkeypatch):
    async def body():
        engine, sf = await _sessionmaker()
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        now = datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC)
        old = now - timedelta(hours=25)
        fresh = now - timedelta(hours=1)

        async with sf() as s:
            repo = DescribeRunRepository(s)
            # Expired terminal singles — two tenants.
            for tenant, media_id in ((tenant_a, 1), (tenant_b, 2)):
                run_id = await repo.create_single_run(tenant_id=tenant, media_id=media_id, image_bytes=b"z")
                await repo.set_item_failed(tenant_id=tenant, run_id=run_id, media_id=media_id, error="done")
                run = await repo.get_run(tenant_id=tenant, run_id=run_id)
                assert run is not None
                run.completed_at = old
                run.created_at = old

            # Fresh terminal single — must survive.
            keep_id = await repo.create_single_run(tenant_id=tenant_a, media_id=99, image_bytes=b"keep")
            await repo.set_item_failed(tenant_id=tenant_a, run_id=keep_id, media_id=99, error="fresh")
            keep_run = await repo.get_run(tenant_id=tenant_a, run_id=keep_id)
            assert keep_run is not None
            keep_run.completed_at = fresh
            keep_run.created_at = fresh

            # Bulk terminal expired — must not be purged (run_kind filter).
            bulk_id = await repo.create_run(tenant_id=tenant_a, media_ids=[100])
            await repo.mark_item(
                tenant_id=tenant_a,
                run_id=bulk_id,
                media_id=100,
                status=DescribeItemStatus.COMPLETED,
            )
            bulk = await repo.get_run(tenant_id=tenant_a, run_id=bulk_id)
            assert bulk is not None
            bulk.completed_at = old
            bulk.created_at = old

            # Non-terminal single expired — must not be purged.
            inflight_id = await repo.create_single_run(tenant_id=tenant_b, media_id=55, image_bytes=b"live")
            inflight = await repo.get_run(tenant_id=tenant_b, run_id=inflight_id)
            assert inflight is not None
            inflight.created_at = old
            await s.commit()

        async with sf() as s:
            repo = DescribeRunRepository(s)
            deleted = await repo.purge_expired_single_runs(now=now, retention_hours=24)
            await s.commit()
            assert deleted == 2

            # Surviving rows.
            assert await repo.get_run(tenant_id=tenant_a, run_id=keep_id) is not None
            assert await repo.get_run(tenant_id=tenant_a, run_id=bulk_id) is not None
            assert await repo.get_run(tenant_id=tenant_b, run_id=inflight_id) is not None

        # Without bypass on a non-SQLite session → fail closed [SEC-01].
        class _NotBypassedResult:
            def scalar(self):
                return None

        class _NotBypassedSession:
            async def execute(self, *_args, **_kwargs):
                return _NotBypassedResult()

        monkeypatch.setattr(repo_mod, "is_sqlite", lambda _session: False)
        with pytest.raises(RuntimeError, match="RLS-bypassed"):
            await DescribeRunRepository(_NotBypassedSession()).purge_expired_single_runs(now=now, retention_hours=24)

        await engine.dispose()

    asyncio.run(body())


def test_reclaim_preserves_provisional_visual_facts_as_degraded():
    """Design (e): single-run with provisional → completed + last_error; projects degraded."""

    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_single_run(tenant_id=tenant, media_id=11, image_bytes=b"stranded")
            await repo.mark_item(tenant_id=tenant, run_id=run_id, media_id=11, status=DescribeItemStatus.RUNNING)
            await repo.set_item_provisional(
                tenant_id=tenant,
                run_id=run_id,
                media_id=11,
                visual_facts=_PROVISIONAL_FACTS,
            )
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            assert run is not None
            run.status = DescribeRunStatus.RUNNING
            await s.commit()

        reclaimed = await repo_mod.run_startup_reclaim(sf)
        assert reclaimed == 1

        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            item = await repo.get_single_run_item(tenant_id=tenant, run_id=run_id)
            assert run is not None and item is not None
            assert item.status == DescribeItemStatus.COMPLETED
            assert item.visual_facts == _PROVISIONAL_FACTS
            assert item.last_error == "interrupted by service restart"
            assert item.image_bytes is None
            assert describe_job_status(item) is DescribeJobStatus.DEGRADED
            assert run.status == DescribeRunStatus.COMPLETED

        # Without provisional → failed.
        async with sf() as s:
            repo = DescribeRunRepository(s)
            bare_id = await repo.create_single_run(tenant_id=tenant, media_id=12, image_bytes=b"no-prov")
            await repo.mark_item(tenant_id=tenant, run_id=bare_id, media_id=12, status=DescribeItemStatus.RUNNING)
            run = await repo.get_run(tenant_id=tenant, run_id=bare_id)
            assert run is not None
            run.status = DescribeRunStatus.RUNNING
            await s.commit()

        reclaimed = await repo_mod.run_startup_reclaim(sf)
        assert reclaimed == 1

        async with sf() as s:
            repo = DescribeRunRepository(s)
            item = await repo.get_single_run_item(tenant_id=tenant, run_id=bare_id)
            assert item is not None
            assert item.status == DescribeItemStatus.FAILED
            assert item.last_error == "interrupted by service restart"
            assert describe_job_status(item) is DescribeJobStatus.FAILED
        await engine.dispose()

    asyncio.run(body())


async def _usage_sessionmaker():
    import os
    import tempfile

    from db.models import UsageReservation
    from db.models.jobs import IdentityScanJob, IdentityScanJobItem
    from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
    from db.models.tenant import Tenant

    path = os.path.join(tempfile.gettempdir(), f"app1_async_reclaim_{uuid.uuid4().hex}.db")
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
            allowance_version="async-reclaim-v1",
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


def test_startup_reclaim_settles_queued_and_running_single_runs():
    async def body():
        import os
        from datetime import UTC, datetime

        from db.models import UsageReservation
        from recognition.application.services.usage_admission_service import UsageAdmissionService
        from recognition.domain.portal_contracts import UsageReservationStatus

        engine, sf, path = await _usage_sessionmaker()
        try:
            async with sf() as session:
                tenant = await _seed_usage_tenant(session)
                repo = DescribeRunRepository(session)
                queued_id = await repo.create_single_run(
                    tenant_id=tenant.id,
                    media_id=21,
                    image_bytes=b"queued",
                )
                running_id = await repo.create_single_run(
                    tenant_id=tenant.id,
                    media_id=22,
                    image_bytes=b"running",
                )
                await repo.mark_item(
                    tenant_id=tenant.id,
                    run_id=running_id,
                    media_id=22,
                    status=DescribeItemStatus.RUNNING,
                )
                running = await repo.get_run(tenant_id=tenant.id, run_id=running_id)
                assert running is not None
                running.status = DescribeRunStatus.RUNNING
                running.started_at = datetime.now(tz=UTC)
                queued_ticket = await UsageAdmissionService(session).reserve(
                    tenant.id,
                    idempotency_key="op-async-queued",
                    job_id=str(queued_id),
                    cost_units=1,
                    operation_id="op-async-queued",
                    request_fingerprint="fp-async-queued",
                )
                running_ticket = await UsageAdmissionService(session).reserve(
                    tenant.id,
                    idempotency_key="op-async-running",
                    job_id=str(running_id),
                    cost_units=1,
                    operation_id="op-async-running",
                    request_fingerprint="fp-async-running",
                )
                await session.commit()

            reclaimed = await repo_mod.run_startup_reclaim(sf)
            assert reclaimed == 2

            async with sf() as session:
                queued_row = await session.get(UsageReservation, queued_ticket.reservation_id)
                running_row = await session.get(UsageReservation, running_ticket.reservation_id)
                assert queued_row is not None and queued_row.status == UsageReservationStatus.RELEASED
                assert running_row is not None and running_row.status == UsageReservationStatus.COMMITTED
        finally:
            await engine.dispose()
            os.unlink(path)

    asyncio.run(body())


def test_bulk_create_run_defaults_to_run_kind_bulk():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=2)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[1])
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            assert run is not None
            assert run.run_kind == RunKind.BULK
        await engine.dispose()

    asyncio.run(body())


def test_create_run_signatures_keep_optional_caller_job_id():
    bulk = inspect.signature(DescribeRunRepository.create_run)
    single = inspect.signature(DescribeRunRepository.create_single_run)
    for params in (bulk.parameters, single.parameters):
        assert params["run_id"].default is None
        assert params["operation_id"].default is None
    assert single.parameters["request_digest"].default is None
    assert "run_id" in bulk.parameters
    assert list(bulk.parameters)[:3] == ["self", "tenant_id", "media_ids"]
    assert list(single.parameters)[:4] == ["self", "tenant_id", "media_id", "image_bytes"]


def test_create_run_persists_caller_job_id_and_operation_identity():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        caller_bulk = uuid.uuid4()
        caller_single = uuid.uuid4()
        fingerprint = "a" * 64
        async with sf() as s:
            repo = DescribeRunRepository(s)
            bulk_id = await repo.create_run(
                tenant_id=tenant,
                media_ids=[1, 2],
                run_id=caller_bulk,
                operation_id="op-bulk",
                request_digest=fingerprint,
            )
            single_id = await repo.create_single_run(
                tenant_id=tenant,
                media_id=9,
                image_bytes=b"img",
                run_id=caller_single,
                operation_id="op-single",
                request_digest=fingerprint,
            )
            omitted = await repo.create_single_run(tenant_id=tenant, media_id=10, image_bytes=b"y")
            await s.commit()
            bulk = await repo.get_run(tenant_id=tenant, run_id=bulk_id)
            single = await repo.get_run(tenant_id=tenant, run_id=single_id)
            leftover = await repo.get_run(tenant_id=tenant, run_id=omitted)
        assert bulk_id == caller_bulk
        assert single_id == caller_single
        assert bulk is not None and bulk.operation_id == "op-bulk"
        assert bulk.request_digest == fingerprint
        assert single is not None and single.operation_id == "op-single"
        assert single.request_digest == fingerprint
        assert leftover is not None and leftover.id != caller_single
        await engine.dispose()

    asyncio.run(body())


@dataclass
class _MigrationRecorder:
    """Record create_table args so ORM metadata can be compared to migration DDL."""

    created_tables: list[str] = field(default_factory=list)
    created_table_args: dict[str, tuple[object, ...]] = field(default_factory=dict)

    def execute(self, sql: str) -> None:  # noqa: ARG002
        return None

    def get_bind(self):
        class _FakeResult:
            def __init__(self, row):
                self._row = row

            def scalar(self):
                return self._row[0] if self._row else None

            def first(self):
                return self._row

            def one(self):
                assert self._row is not None, "expected one catalog row"
                return self._row

        class _FakeBind:
            def execute(self, stmt, params=None):  # noqa: ANN001, ARG002
                # These DDL-shape tests model a role allowed to create the view.
                if "has_schema_privilege" in str(stmt) and "has_table_privilege" in str(stmt):
                    return _FakeResult(("public", True, True, True, True, True))
                if "relrowsecurity" in str(stmt):
                    return _FakeResult((False, False))
                return _FakeResult(None)

        return _FakeBind()

    def create_table(self, name: str, *args, **kwargs) -> None:  # noqa: ANN002, ANN003, ARG002
        self.created_tables.append(name)
        self.created_table_args[name] = args

    def create_index(self, name: str, table_name: str, columns, *args, **kwargs) -> None:  # noqa: ANN001, ARG002
        return None

    def drop_table(self, name: str, *args, **kwargs) -> None:  # noqa: ANN002, ANN003, ARG002
        return None

    def drop_index(self, name: str, table_name: str | None = None, *args, **kwargs) -> None:  # noqa: ANN002, ARG002
        return None


def _column_signature(col: Column) -> tuple[str, int | None, bool]:
    """(storage-type, length, nullable) — catches type/width/nullability drift.

    VLM5-F2B-BR-02: name-only parity passed a migration-only String(32)->String(64)
    widening; the signature comparison fails it.  The ORM's ``_TimingFloat`` is
    an intentional ``Float`` TypeDecorator that rejects non-finite binds, so
    compare its storage implementation to the migration's ``Float`` column.
    """
    column_type = col.type
    if isinstance(column_type, TypeDecorator):
        column_type = column_type.impl
    return (type(column_type).__name__, getattr(column_type, "length", None), col.nullable)


def _migration_columns_and_checks(
    table_name: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, tuple[str, int | None, bool]], set[str]]:
    recorder = _MigrationRecorder()
    monkeypatch.setattr(identity_schema, "op", recorder)
    identity_schema.upgrade()
    args = recorder.created_table_args[table_name]
    columns = {cast(Column, a).name: _column_signature(cast(Column, a)) for a in args if isinstance(a, Column)}
    checks = {cast(CheckConstraint, a).name for a in args if isinstance(a, CheckConstraint) and a.name}
    return columns, checks


def test_describe_run_orm_matches_migration_schema(monkeypatch: pytest.MonkeyPatch):
    """VLM5-S1A-BR-01 [rg-005]: ORM DescribeRun/Item columns + CHECKs match migration.

    Fails if run_kind / visual_facts / tier / result_generation (or a CHECK name)
    is added or renamed on only one of the two surfaces.
    """
    run_mig_cols, run_mig_checks = _migration_columns_and_checks("image_description_runs", monkeypatch)
    item_mig_cols, item_mig_checks = _migration_columns_and_checks("image_description_run_items", monkeypatch)

    run_orm_cols = {c.name: _column_signature(c) for c in DescribeRun.__table__.columns}
    item_orm_cols = {c.name: _column_signature(c) for c in DescribeRunItem.__table__.columns}
    run_orm_checks = {c.name for c in DescribeRun.__table__.constraints if isinstance(c, CheckConstraint) and c.name}
    item_orm_checks = {
        c.name for c in DescribeRunItem.__table__.constraints if isinstance(c, CheckConstraint) and c.name
    }

    # Headline VLM-5 columns must exist on both surfaces.
    assert "run_kind" in run_orm_cols and "run_kind" in run_mig_cols
    for col in ("visual_facts", "tier", "result_generation"):
        assert col in item_orm_cols and col in item_mig_cols

    # Full storage signature parity: names AND (storage type, length, nullable)
    # per column.  ORM-only bind validation wrappers are normalized by
    # _column_signature rather than misreported as database schema drift.
    assert run_orm_cols == run_mig_cols
    assert item_orm_cols == item_mig_cols
    assert run_orm_checks == run_mig_checks
    assert item_orm_checks == item_mig_checks
    assert "valid_describe_run_kind" in run_orm_checks
    assert "valid_describe_item_status" in item_orm_checks


def test_single_run_mutators_reject_mismatched_tenant():
    """VLM5-S1A-BR-05 [PERF-07], [DIAG-02]: wrong-tenant reads/writes are no-ops.

    get_single_run_item / set_item_provisional / set_item_final / set_item_degraded /
    set_item_failed with a foreign tenant_id return None/False and leave the owner
    row untouched.
    """

    async def body():
        engine, sf = await _sessionmaker()
        owner = uuid.uuid4()
        foreign = uuid.uuid4()
        media_id = 42

        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_single_run(
                tenant_id=owner,
                media_id=media_id,
                image_bytes=b"owner-bytes",
                image_content_type="image/jpeg",
            )
            await repo.mark_item(
                tenant_id=owner,
                run_id=run_id,
                media_id=media_id,
                status=DescribeItemStatus.RUNNING,
            )
            await s.commit()

        async with sf() as s:
            repo = DescribeRunRepository(s)
            before = await repo.get_single_run_item(tenant_id=owner, run_id=run_id)
            assert before is not None
            assert before.status == DescribeItemStatus.RUNNING
            assert before.image_bytes == b"owner-bytes"
            assert before.visual_facts is None
            assert before.tier is None
            assert before.result_generation == 0
            assert before.last_error is None

            assert await repo.get_single_run_item(tenant_id=foreign, run_id=run_id) is None
            assert (
                await repo.set_item_provisional(
                    tenant_id=foreign,
                    run_id=run_id,
                    media_id=media_id,
                    visual_facts=_PROVISIONAL_FACTS,
                )
                is False
            )
            assert (
                await repo.set_item_final(
                    tenant_id=foreign,
                    run_id=run_id,
                    media_id=media_id,
                    visual_facts=_FINAL_FACTS,
                )
                is False
            )
            assert (
                await repo.set_item_degraded(
                    tenant_id=foreign,
                    run_id=run_id,
                    media_id=media_id,
                    error="foreign degraded",
                )
                is False
            )
            assert (
                await repo.set_item_failed(
                    tenant_id=foreign,
                    run_id=run_id,
                    media_id=media_id,
                    error="foreign failed",
                )
                is False
            )
            await s.commit()

        async with sf() as s:
            repo = DescribeRunRepository(s)
            after = await repo.get_single_run_item(tenant_id=owner, run_id=run_id)
            assert after is not None
            assert after.status == DescribeItemStatus.RUNNING
            assert after.image_bytes == b"owner-bytes"
            assert after.visual_facts is None
            assert after.tier is None
            assert after.result_generation == 0
            assert after.last_error is None
            assert after.media_id == media_id
        await engine.dispose()

    asyncio.run(body())
