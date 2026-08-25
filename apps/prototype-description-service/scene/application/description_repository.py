"""Tenant-scoped data access for the image_descriptions cache table (E19-1 S3).

Pure persistence: cache-key lookup and insert. Cache misses return ``None`` (no
raise). The VisualFactsService (S4) owns the cache-or-generate decision.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.scene import ImageDescription


class ImageDescriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_cache_key(
        self,
        *,
        tenant_id: uuid.UUID,
        image_hash: str,
        adapter: str,
        model_id: str,
        model_version: str,
        prompt_or_task_version: str,
        context_hash: str,
    ) -> ImageDescription | None:
        stmt = select(ImageDescription).where(
            ImageDescription.tenant_id == tenant_id,
            ImageDescription.image_hash == image_hash,
            ImageDescription.adapter == adapter,
            ImageDescription.model_id == model_id,
            ImageDescription.model_version == model_version,
            ImageDescription.prompt_or_task_version == prompt_or_task_version,
            ImageDescription.context_hash == context_hash,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def insert(self, record: ImageDescription) -> ImageDescription:
        self._session.add(record)
        await self._session.flush()
        return record

    async def insert_or_get_existing(self, record: ImageDescription) -> tuple[ImageDescription, bool]:
        """Insert a cache row, or return the row that won a duplicate-key race."""
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
            return record, True
        except IntegrityError:
            existing = await self.get_by_cache_key(
                tenant_id=record.tenant_id,
                image_hash=record.image_hash,
                adapter=record.adapter,
                model_id=record.model_id,
                model_version=record.model_version,
                prompt_or_task_version=record.prompt_or_task_version,
                context_hash=record.context_hash,
            )
            if existing is None:
                raise
            return existing, False
