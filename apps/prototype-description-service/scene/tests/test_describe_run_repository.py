"""Describe-run repository persistence and idempotency."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus


async def _sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=cast(list[Table], [DescribeRun.__table__, DescribeRunItem.__table__]),
        )
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_create_run_and_terminal_item_writes_are_idempotent():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=3)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[101, 102])
            await repo.mark_item(
                tenant_id=tenant,
                run_id=run_id,
                media_id=101,
                status=DescribeItemStatus.COMPLETED,
            )
            await repo.mark_item(
                tenant_id=tenant,
                run_id=run_id,
                media_id=101,
                status=DescribeItemStatus.COMPLETED,
            )
            await repo.mark_item(
                tenant_id=tenant,
                run_id=run_id,
                media_id=102,
                status=DescribeItemStatus.FAILED,
                error_message="vlm timeout",
            )
            await s.commit()

        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=3)
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
            items = await repo.list_run_items(tenant_id=tenant, run_id=run_id)

        assert run is not None
        assert run.total_items == 2
        assert run.completed_items == 1
        assert run.failed_items == 1
        assert run.skipped_items == 0
        assert run.status == DescribeRunStatus.COMPLETED_WITH_ERRORS
        assert sorted((item.media_id, item.status) for item in items) == [
            (101, DescribeItemStatus.COMPLETED),
            (102, DescribeItemStatus.FAILED),
        ]
        await engine.dispose()

    asyncio.run(body())


def test_create_run_rejects_empty_and_oversize_lists():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=2)
            with pytest.raises(ValueError, match="at least one"):
                await repo.create_run(tenant_id=tenant, media_ids=[])
            with pytest.raises(ValueError, match="at most 2"):
                await repo.create_run(tenant_id=tenant, media_ids=[1, 2, 3])
        await engine.dispose()

    asyncio.run(body())


def test_reclaim_interrupted_runs_resets_only_stale_running_items():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        now = datetime.now(tz=UTC)
        async with sf() as s:
            repo = DescribeRunRepository(s, max_items=5)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[201, 202, 203])
            await repo.mark_item(
                tenant_id=tenant,
                run_id=run_id,
                media_id=201,
                status=DescribeItemStatus.RUNNING,
                now=now - timedelta(minutes=10),
            )
            await repo.mark_item(
                tenant_id=tenant,
                run_id=run_id,
                media_id=202,
                status=DescribeItemStatus.RUNNING,
                now=now,
            )
            await repo.mark_item(
                tenant_id=tenant,
                run_id=run_id,
                media_id=203,
                status=DescribeItemStatus.COMPLETED,
                now=now - timedelta(minutes=10),
            )
            reclaimed = await repo.reclaim_interrupted_runs(tenant_id=tenant, cutoff=now - timedelta(minutes=5))
            await s.commit()

        async with sf() as s:
            rows = (
                await s.execute(
                    select(DescribeRunItem.media_id, DescribeRunItem.status, DescribeRunItem.started_at)
                    .where(DescribeRunItem.run_id == run_id)
                    .order_by(DescribeRunItem.media_id)
                )
            ).all()

        assert reclaimed == 1
        assert rows[0] == (201, DescribeItemStatus.QUEUED, None)
        assert rows[1][0:2] == (202, DescribeItemStatus.RUNNING)
        assert rows[1][2] is not None
        assert rows[2][0:2] == (203, DescribeItemStatus.COMPLETED)
        await engine.dispose()

    asyncio.run(body())
