from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import (
    DescribeDemandLease,
    DescribeOperation,
    DescribeRun,
    DescribeRunItem,
    DescribeStartup,
)
from db.models.tenant import Tenant
from scene.application.describe_operation_repository import DescribeOperationRepository
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import run_describe_job

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000cc")


async def _database():
    path = os.path.join(tempfile.gettempdir(), f"dw2_describeru_1_{uuid.uuid4().hex}.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=cast(
                list[Table],
                [
                    Tenant.__table__,
                    DescribeStartup.__table__,
                    DescribeOperation.__table__,
                    DescribeDemandLease.__table__,
                    DescribeRun.__table__,
                    DescribeRunItem.__table__,
                ],
            ),
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(Tenant(id=TENANT_ID, site_url="http://test.local"))
        await session.commit()
    return path, engine, session_factory


async def _readiness_case(session_factory):
    now = datetime.now(UTC)
    async with session_factory() as session:
        run_id = await DescribeRunRepository(session).create_run(
            tenant_id=TENANT_ID,
            media_ids=[1],
            images={1: (b"image", "image/png")},
        )
        run = await DescribeRunRepository(session).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        operation = await DescribeOperationRepository(session, lease_seconds=180).accept(
            tenant_id=TENANT_ID,
            request_digest=run.request_digest,
            now=now,
        )
        run.operation_id = operation.operation_id
        await session.commit()
    return run_id, now, operation.operation_id


async def _associate_startup(
    session_factory, *, operation_id: str, now: datetime, startup_id: str
) -> None:
    async with session_factory() as session:
        await DescribeOperationRepository(session, lease_seconds=180).associate_startup(
            tenant_id=TENANT_ID,
            operation_id=operation_id,
            startup_id=startup_id,
            started_at=now,
            now=now + timedelta(seconds=1),
        )
        await session.commit()


def test_readiness_sees_startup_committed_by_a_second_session(monkeypatch):
    import scene.application.describe_run_worker as wmod

    async def body():
        path, engine, session_factory = await _database()
        run_id, now, operation_id = await _readiness_case(session_factory)
        await wmod._record_run_pickup(session_factory=session_factory, tenant_id=TENANT_ID, run_id=run_id)

        original_lock = getattr(DescribeRunRepository, "get_run_for_update", None)
        association_committed = False
        if original_lock is not None:

            async def commit_association_before_locked_read(self, *, tenant_id, run_id):
                nonlocal association_committed
                if not association_committed:
                    await _associate_startup(
                        session_factory, operation_id=operation_id, now=now, startup_id="raced-boot"
                    )
                    association_committed = True
                return await original_lock(self, tenant_id=tenant_id, run_id=run_id)

            monkeypatch.setattr(DescribeRunRepository, "get_run_for_update", commit_association_before_locked_read)

        await wmod._record_run_readiness(
            session_factory=session_factory,
            tenant_id=TENANT_ID,
            run_id=run_id,
            cold=True,
        )
        assert association_committed
        async with session_factory() as session:
            run = await DescribeRunRepository(session).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.startup_id == "raced-boot"
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_readiness_reads_operation_startup_after_locking_the_run(monkeypatch):
    import scene.application.describe_run_worker as wmod

    async def body():
        path, engine, session_factory = await _database()
        run_id, now, operation_id = await _readiness_case(session_factory)
        await _associate_startup(
            session_factory, operation_id=operation_id, now=now, startup_id="locked-boot"
        )
        await wmod._record_run_pickup(session_factory=session_factory, tenant_id=TENANT_ID, run_id=run_id)

        events: list[str] = []
        original_lock = getattr(DescribeRunRepository, "get_run_for_update", None)
        original_observed_startup = wmod._observed_startup
        if original_lock is not None:

            async def trace_locked_read(self, *, tenant_id, run_id):
                result = await original_lock(self, tenant_id=tenant_id, run_id=run_id)
                events.append("run_locked")
                return result

            monkeypatch.setattr(DescribeRunRepository, "get_run_for_update", trace_locked_read)

        async def trace_startup_read(session, *, tenant_id, operation_id, for_update=False):
            events.append("startup_read_for_update" if for_update else "startup_read")
            return await original_observed_startup(
                session,
                tenant_id=tenant_id,
                operation_id=operation_id,
                for_update=for_update,
            )

        monkeypatch.setattr(wmod, "_observed_startup", trace_startup_read)
        monkeypatch.setattr(wmod, "_session_supports_row_lock", lambda session: True)
        await wmod._record_run_readiness(
            session_factory=session_factory,
            tenant_id=TENANT_ID,
            run_id=run_id,
            cold=True,
        )
        assert events[:2] == ["run_locked", "startup_read_for_update"]
        async with session_factory() as session:
            run = await DescribeRunRepository(session).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.startup_id == "locked-boot"
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_warm_readiness_does_not_replace_concurrent_cold_ramp_up(monkeypatch):
    import scene.application.describe_run_worker as wmod

    async def body():
        path, engine, session_factory = await _database()
        async with session_factory() as session:
            run_id = await DescribeRunRepository(session).create_run(
                tenant_id=TENANT_ID,
                media_ids=[1],
                images={1: (b"image", "image/png")},
            )
            await session.commit()
        await wmod._record_run_pickup(session_factory=session_factory, tenant_id=TENANT_ID, run_id=run_id)
        async with session_factory() as session:
            run = await DescribeRunRepository(session).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None and run.started_at is not None
        started_at = run.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        cold_ready_at = started_at + timedelta(seconds=5)

        original_record_readiness = DescribeRunRepository.record_readiness
        cold_recorded = False

        async def interleave_cold_readiness(self, **kwargs):
            nonlocal cold_recorded
            if not cold_recorded:
                # SQLite's read transaction would prevent the competing session from committing.
                await self._session.rollback()
                async with session_factory() as other_session:
                    other_repo = DescribeRunRepository(other_session)
                    assert await original_record_readiness(
                        other_repo,
                        tenant_id=TENANT_ID,
                        run_id=run_id,
                        now=cold_ready_at,
                        operation_id="cold-operation",
                        startup_id="cold-startup",
                        startup_ms=125.0,
                    )
                    await other_session.commit()
                cold_recorded = True
            return await original_record_readiness(self, **kwargs)

        monkeypatch.setattr(DescribeRunRepository, "record_readiness", interleave_cold_readiness)
        await wmod._record_run_readiness(
            session_factory=session_factory,
            tenant_id=TENANT_ID,
            run_id=run_id,
            cold=False,
        )
        assert cold_recorded
        async with session_factory() as session:
            run = await DescribeRunRepository(session).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.ramp_up_ms == pytest.approx(5000.0)
        assert run.startup_id == "cold-startup"
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_worker_timeout_persists_timing_from_cancelled_adapter_attempt():
    from scene.application.visual_facts_service import AdapterAttemptTiming

    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as exc:
            exc.attempt_timing = AdapterAttemptTiming(processing_ms=37, entered_adapter=True)
            raise

    async def body():
        path, engine, session_factory = await _database()
        async with session_factory() as session:
            run_id = await DescribeRunRepository(session).create_run(
                tenant_id=TENANT_ID,
                media_ids=[1],
                images={1: (b"image", "image/png")},
            )
            await session.commit()
        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=session_factory,
            describe_one=describe_one,
            timeout_seconds=0.01,
        )
        async with session_factory() as session:
            items = await DescribeRunRepository(session).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        assert len(items) == 1
        assert items[0].processing_ms == 37.0
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())
