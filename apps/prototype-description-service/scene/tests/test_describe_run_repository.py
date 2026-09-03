"""Describe-run repository persistence and idempotency."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus
from scene.domain.description import DescriptionResultTier


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


def test_record_item_result_persists_tier_and_increments_generation():
    async def body():
        session = SimpleNamespace(flush=AsyncMock())
        item = SimpleNamespace(
            alt_text_draft=None,
            caption=None,
            provenance=None,
            tier=None,
            result_generation=0,
            image_bytes=b"image",
        )
        repo = DescribeRunRepository(session)
        repo._get_item = AsyncMock(return_value=item)

        for draft, tier in (
            ("provisional draft", DescriptionResultTier.PROVISIONAL_CPU),
            ("final draft", DescriptionResultTier.FINAL_GPU),
        ):
            assert await repo.record_item_result(
                tenant_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                media_id=101,
                alt_text_draft=draft,
                caption=draft,
                provenance={"model_id": "org/model@revision"},
                tier=tier,
            )

        assert item.tier == DescriptionResultTier.FINAL_GPU
        assert item.result_generation == 2
        assert item.image_bytes is None
        assert session.flush.await_count == 2

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
