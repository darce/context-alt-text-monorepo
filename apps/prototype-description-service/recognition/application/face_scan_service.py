"""Application service for scanning media and persisting faces."""

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

from db.models import FaceScanJob, MediaFace
from recognition.domain.entities import FaceEmbedding
from recognition.infrastructure.embedding_provider import FaceEmbeddingProvider

logger = logging.getLogger(__name__)


class FaceScanService:
    """Service coordinating embedding extraction and MediaFace persistence."""

    def __init__(self, session: AsyncSession, embedding_provider: FaceEmbeddingProvider, tenant_id: UUID) -> None:
        self.session = session
        self.embedding_provider = embedding_provider
        self.tenant_id = tenant_id

    async def scan_batch(
        self,
        job: FaceScanJob,
        media_items: Iterable[dict[str, object]],
        user_id: Optional[int] = None,
    ) -> None:
        job.started_at = datetime.utcnow()
        job.status = "running"
        await self.session.flush()

        processed_media = 0
        faces_detected = 0

        try:
            for media_item in media_items:
                media_id = int(media_item["media_id"])
                media_url = str(media_item["media_url"])

                image = await self._fetch_image(media_url)
                embeddings = await self.embedding_provider.analyze(image)

                saved_faces = await self._save_faces(
                    media_id=media_id,
                    media_url=media_url,
                    embeddings=embeddings,
                    created_by_user_id=user_id,
                )

                processed_media += 1
                faces_detected += len(saved_faces)
                job.processed_media = processed_media
                job.faces_detected = faces_detected
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

    async def _save_faces(
        self,
        media_id: int,
        media_url: str,
        embeddings: Iterable[FaceEmbedding],
        created_by_user_id: Optional[int],
    ) -> list[MediaFace]:
        existing_keys = await self._existing_face_keys(media_id)
        new_keys: set[tuple[int, int]] = set()
        saved: list[MediaFace] = []
        for embedding in embeddings:
            detection = embedding.detection
            x_min, y_min, x_max, y_max = detection.bbox
            width = max(0, x_max - x_min)
            height = max(0, y_max - y_min)

            key = (x_min, y_min)
            if key in existing_keys or key in new_keys:
                logger.info(
                    "Skipping duplicate face for tenant %s media %s at bbox (%s, %s)",
                    self.tenant_id,
                    media_id,
                    x_min,
                    y_min,
                )
                continue
            new_keys.add(key)

            face = MediaFace(
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
            self.session.add(face)
            saved.append(face)

        return saved

    async def _fetch_image(self, url: str) -> Image.Image:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return Image.open(BytesIO(response.content)).convert("RGB")

    async def _existing_face_keys(self, media_id: int) -> set[tuple[int, int]]:
        stmt = select(MediaFace.bbox_x, MediaFace.bbox_y).where(
            MediaFace.tenant_id == self.tenant_id,
            MediaFace.media_id == media_id,
            MediaFace.is_deleted.is_(False),
        )
        result = await self.session.execute(stmt)
        return {(row[0], row[1]) for row in result.all()}
