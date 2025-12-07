"""Application service for scanning media and persisting identities."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from io import BytesIO
from uuid import UUID, uuid4

import httpx
import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityScanJob, MediaIdentity
from recognition.application.clustering.centroid_utils import _normalize_vector
from recognition.domain.entities import IdentityEmbedding
from recognition.infrastructure.embedding_provider import FaceEmbeddingProvider
from recognition.infrastructure.thumbnail_service import ThumbnailService

logger = logging.getLogger(__name__)


class IdentityScanService:
    """Service coordinating embedding extraction and MediaIdentity persistence."""

    def __init__(self, session: AsyncSession, embedding_provider: FaceEmbeddingProvider, tenant_id: UUID) -> None:
        self.session = session
        self.embedding_provider = embedding_provider
        self.tenant_id = tenant_id
        self._thumbnail_service = ThumbnailService()

    async def scan_identities(
        self,
        job: IdentityScanJob,
        media_items: Iterable[dict[str, object]],
        user_id: int | None = None,
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
                media_id = int(media_item["media_id"])  # type: ignore[call-overload]
                media_url = str(media_item["media_url"])

                image = await self._fetch_image(media_url)
                embeddings = await self.embedding_provider.analyze(image)

                saved_identities = await self._save_identities(
                    media_id=media_id,
                    media_url=media_url,
                    embeddings=embeddings,
                    created_by_user_id=user_id,
                    source_image=image,
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
        created_by_user_id: int | None,
        source_image: Image.Image,
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
                embedding=_normalize_vector(np.array(embedding.embedding, dtype=np.float32)).tolist(),
                created_by_user_id=created_by_user_id,
            )
            self.session.add(identity)
            if getattr(identity, "id", None) is None:
                identity.id = uuid4()
            self._generate_thumbnail_if_enabled(identity, embedding, source_image)
            saved.append(identity)

        return saved

    def _generate_thumbnail_if_enabled(
        self, identity: MediaIdentity, embedding: IdentityEmbedding, image: Image.Image
    ) -> None:
        if not self._thumbnail_service.enabled:
            return
        bbox = (
            float(identity.bbox_x),
            float(identity.bbox_y),
            float(identity.bbox_width),
            float(identity.bbox_height),
        )
        url = self._thumbnail_service.save(image=image, bbox=bbox, identity_id=identity.id)
        if url:
            identity.thumbnail_url = url

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
