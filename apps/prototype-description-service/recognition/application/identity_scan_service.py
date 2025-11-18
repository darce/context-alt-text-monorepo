"""Application service for scanning media and persisting identities."""

from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO
from typing import Iterable, Optional
from uuid import UUID

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityScanJob, MediaIdentity
from recognition.domain.entities import IdentityEmbedding
from recognition.infrastructure.embedding_provider import FaceEmbeddingProvider

logger = logging.getLogger(__name__)


class IdentityScanService:
    """Service coordinating embedding extraction and MediaIdentity persistence."""

    def __init__(self, session: AsyncSession, embedding_provider: FaceEmbeddingProvider, tenant_id: UUID) -> None:
        self.session = session
        self.embedding_provider = embedding_provider
        self.tenant_id = tenant_id

    async def scan_identities(
        self,
        job: IdentityScanJob,
        media_items: Iterable[dict[str, object]],
        user_id: Optional[int] = None,
    ) -> None:
        if hasattr(self.session, "get"):
            persistent_job = await self.session.get(IdentityScanJob, job.id)
            if persistent_job is None:
                raise RuntimeError(f"IdentityScanJob {job.id} no longer exists")
            job = persistent_job
        job.started_at = datetime.utcnow()
        job.status = "running"
        await self.session.flush()

        processed_media = 0
        identities_detected = 0

        try:
            for media_item in media_items:
                media_id = int(media_item["media_id"])
                media_url = str(media_item["media_url"])

                image = await self._fetch_image(media_url)
                embeddings = await self.embedding_provider.analyze(image)

                saved_identities = await self._save_identities(
                    media_id=media_id,
                    media_url=media_url,
                    embeddings=embeddings,
                    created_by_user_id=user_id,
                )

                processed_media += 1
                identities_detected += len(saved_identities)
                job.processed_media = processed_media
                job.identities_detected = identities_detected
                await self.session.flush()

            job.status = "completed"
            job.completed_at = datetime.utcnow()
            await self.session.commit()
        except Exception as exc:  # pragma: no cover - propagated by caller
            logger.exception("Recognition job %s failed", getattr(job, "id", "unknown"))
            await self.session.rollback()
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.utcnow()
            await self.session.commit()
            raise

    async def _save_identities(
        self,
        media_id: int,
        media_url: str,
        embeddings: Iterable[IdentityEmbedding],
        created_by_user_id: Optional[int],
    ) -> list[MediaIdentity]:
        existing_keys = await self._existing_identity_keys(media_id)
        new_keys: set[tuple[int, int]] = set()
        saved: list[MediaIdentity] = []
        for embedding in embeddings:
            detection = embedding.detection
            x_min, y_min, x_max, y_max = detection.bbox
            width = max(0, x_max - x_min)
            height = max(0, y_max - y_min)

            key = (x_min, y_min)
            if key in existing_keys or key in new_keys:
                logger.info(
                    "Skipping duplicate identity for tenant %s media %s at bbox (%s, %s)",
                    self.tenant_id,
                    media_id,
                    x_min,
                    y_min,
                )
                continue
            new_keys.add(key)

            identity = MediaIdentity(
                tenant_id=self.tenant_id,
                media_id=media_id,
                media_url=media_url,
                bbox_x=x_min,
                bbox_y=y_min,
                bbox_width=width,
                bbox_height=height,
                confidence=detection.confidence,
                embedding=embedding.embedding.tolist(),
                created_by_user_id=created_by_user_id,
            )
            self.session.add(identity)
            saved.append(identity)

        return saved

    async def _fetch_image(self, url: str) -> Image.Image:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return Image.open(BytesIO(response.content)).convert("RGB")

    async def _existing_identity_keys(self, media_id: int) -> set[tuple[int, int]]:
        stmt = select(MediaIdentity.bbox_x, MediaIdentity.bbox_y).where(
            MediaIdentity.tenant_id == self.tenant_id,
            MediaIdentity.media_id == media_id,
        )
        result = await self.session.execute(stmt)
        return {(row[0], row[1]) for row in result.all()}
