"""S3: ImageDescriptionRepository cache-key hit/miss on aiosqlite in-memory."""

import asyncio
import uuid
from typing import cast

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import ImageDescription
from scene.application.description_repository import ImageDescriptionRepository


def _row(tenant_id: uuid.UUID, **over) -> ImageDescription:
    fields = {
        "tenant_id": tenant_id,
        "media_id": 42,
        "image_hash": "a" * 64,
        "context_hash": "b" * 64,
        "adapter": "seeded",
        "model_id": "seeded-fixtures",
        "model_version": "1",
        "prompt_or_task_version": "1",
        "visual_facts": {"caption": "A cat", "objects": [], "ocr_text": None},
        "alt_text_draft": "A cat.",
        "context_used": {"sources": [], "applied": False},
        "provider_disclosure": {"provider": "none", "left_service_boundary": False},
        "retention_class": "retain_all",
        "duration_ms": 5,
    }
    fields.update(over)
    return ImageDescription(**fields)


async def _sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=cast(list[Table], [ImageDescription.__table__]))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_insert_then_cache_hit_and_context_miss():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            await ImageDescriptionRepository(s).insert(_row(tenant))
            await s.commit()
        async with sf() as s:
            repo = ImageDescriptionRepository(s)
            hit = await repo.get_by_cache_key(
                tenant_id=tenant,
                image_hash="a" * 64,
                adapter="seeded",
                model_id="seeded-fixtures",
                model_version="1",
                prompt_or_task_version="1",
                context_hash="b" * 64,
            )
            assert hit is not None
            assert hit.alt_text_draft == "A cat."
            assert hit.visual_facts["caption"] == "A cat"
            miss = await repo.get_by_cache_key(
                tenant_id=tenant,
                image_hash="a" * 64,
                adapter="seeded",
                model_id="seeded-fixtures",
                model_version="1",
                prompt_or_task_version="1",
                context_hash="c" * 64,
            )
            assert miss is None
        await engine.dispose()

    asyncio.run(body())


def test_version_bump_is_a_cache_miss():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            await ImageDescriptionRepository(s).insert(_row(tenant))
            await s.commit()
        async with sf() as s:
            miss = await ImageDescriptionRepository(s).get_by_cache_key(
                tenant_id=tenant,
                image_hash="a" * 64,
                adapter="seeded",
                model_id="seeded-fixtures",
                model_version="1",
                prompt_or_task_version="2",
                context_hash="b" * 64,
            )
            assert miss is None
        await engine.dispose()

    asyncio.run(body())


def test_duplicate_cache_key_returns_existing_row_without_aborting_transaction():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        async with sf() as s:
            repo = ImageDescriptionRepository(s)
            first, first_inserted = await repo.insert_or_get_existing(_row(tenant, media_id=42))
            second, second_inserted = await repo.insert_or_get_existing(_row(tenant, media_id=99))
            await s.commit()

        assert first_inserted is True
        assert second_inserted is False
        assert second.id == first.id
        assert second.media_id == 42
        await engine.dispose()

    asyncio.run(body())
