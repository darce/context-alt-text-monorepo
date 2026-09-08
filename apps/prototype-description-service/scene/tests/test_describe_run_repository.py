"""Describe-run repository persistence and idempotency."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus
from scene.domain.description import DescriptionResultTier


async def _sessionmaker(database_url: str = "sqlite+aiosqlite:///:memory:"):
    engine = create_async_engine(database_url)
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
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as session:
            repo = DescribeRunRepository(session)
            run_id = await repo.create_run(
                tenant_id=tenant,
                media_ids=[101],
                images={101: (b"image", "image/jpeg")},
            )

            for draft, tier in (
                ("provisional draft", DescriptionResultTier.PROVISIONAL_CPU),
                ("final draft", DescriptionResultTier.FINAL_GPU),
            ):
                assert await repo.record_item_result(
                    tenant_id=tenant,
                    run_id=run_id,
                    media_id=101,
                    alt_text_draft=draft,
                    caption=draft,
                    provenance={"model_id": "org/model@revision"},
                    tier=tier,
                )
            await session.commit()

        async with sf() as verify_session:
            item = (await DescribeRunRepository(verify_session).list_run_items(tenant_id=tenant, run_id=run_id))[0]
        assert item.tier == DescriptionResultTier.FINAL_GPU
        assert item.result_generation == 2
        assert item.image_bytes is None
        await engine.dispose()

    asyncio.run(body())


def test_record_item_result_does_not_replace_final_with_late_provisional():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as session:
            repo = DescribeRunRepository(session)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[101])
            assert await repo.record_item_result(
                tenant_id=tenant,
                run_id=run_id,
                media_id=101,
                alt_text_draft="final draft",
                caption="final caption",
                provenance={"model_id": "org/gpu-model@revision"},
                tier=DescriptionResultTier.FINAL_GPU,
            )
            assert not await repo.record_item_result(
                tenant_id=tenant,
                run_id=run_id,
                media_id=101,
                alt_text_draft="late provisional draft",
                caption="late provisional caption",
                provenance={"model_id": "org/cpu-model@revision"},
                tier=DescriptionResultTier.PROVISIONAL_CPU,
            )
            await session.commit()

        async with sf() as verify_session:
            item = (await DescribeRunRepository(verify_session).list_run_items(tenant_id=tenant, run_id=run_id))[0]
        assert item.alt_text_draft == "final draft"
        assert item.caption == "final caption"
        assert item.provenance == {"model_id": "org/gpu-model@revision"}
        assert item.tier == DescriptionResultTier.FINAL_GPU
        assert item.result_generation == 1
        assert item.image_bytes is None
        await engine.dispose()

    asyncio.run(body())


def test_record_item_result_conditionally_rejects_stale_provisional_and_empty_writes(tmp_path: Path):
    async def body():
        engine, sf = await _sessionmaker(f"sqlite+aiosqlite:///{tmp_path / 'stale-result.db'}")
        tenant = uuid.uuid4()
        async with sf() as setup_session:
            run_id = await DescribeRunRepository(setup_session).create_run(tenant_id=tenant, media_ids=[101])
            await setup_session.commit()

        async with sf() as stale_session, sf() as winner_session:
            stale_repo = DescribeRunRepository(stale_session)
            stale_items = await stale_repo.list_run_items(tenant_id=tenant, run_id=run_id)
            assert stale_items[0].tier is None
            await stale_session.commit()

            winner_repo = DescribeRunRepository(winner_session)
            assert await winner_repo.record_item_result(
                tenant_id=tenant,
                run_id=run_id,
                media_id=101,
                alt_text_draft="final draft",
                caption="final caption",
                provenance={"model_id": "org/gpu-model@revision"},
                tier=DescriptionResultTier.FINAL_GPU,
            )
            await winner_session.commit()

            provisional_written = await stale_repo.record_item_result(
                tenant_id=tenant,
                run_id=run_id,
                media_id=101,
                alt_text_draft="late provisional draft",
                caption="late provisional caption",
                provenance={"model_id": "org/cpu-model@revision"},
                tier=DescriptionResultTier.PROVISIONAL_CPU,
            )
            empty_written = await stale_repo.record_item_result(
                tenant_id=tenant,
                run_id=run_id,
                media_id=101,
                alt_text_draft=None,
                caption=None,
                provenance=None,
            )
            await stale_session.commit()

        async with sf() as verify_session:
            items = await DescribeRunRepository(verify_session).list_run_items(tenant_id=tenant, run_id=run_id)

        assert not provisional_written
        assert not empty_written
        assert items[0].tier == DescriptionResultTier.FINAL_GPU
        assert items[0].result_generation == 1
        assert items[0].alt_text_draft == "final draft"
        assert items[0].caption == "final caption"
        assert items[0].provenance == {"model_id": "org/gpu-model@revision"}
        await engine.dispose()

    asyncio.run(body())


def test_record_item_result_treats_unknown_stored_tier_as_non_final():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as session:
            repo = DescribeRunRepository(session)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[101])
            item = (await repo.list_run_items(tenant_id=tenant, run_id=run_id))[0]
            item.tier = "future_tier"
            await session.commit()

            assert await repo.record_item_result(
                tenant_id=tenant,
                run_id=run_id,
                media_id=101,
                alt_text_draft="replacement draft",
                caption=None,
                provenance=None,
                tier=DescriptionResultTier.PROVISIONAL_CPU,
            )
            await session.commit()

        async with sf() as verify_session:
            items = await DescribeRunRepository(verify_session).list_run_items(tenant_id=tenant, run_id=run_id)
        assert items[0].tier == DescriptionResultTier.PROVISIONAL_CPU
        assert items[0].result_generation == 1
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
