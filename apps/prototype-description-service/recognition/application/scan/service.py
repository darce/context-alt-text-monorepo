"""ScanService orchestrates face detection and embedding generation."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityScanJob, MediaIdentity
from db.settings import get_database_settings
from recognition.application.embedding.detector import FaceDetectorProtocol, StubFaceDetector
from recognition.application.embedding.generator import EmbeddingGeneratorProtocol, StubEmbeddingGenerator
from recognition.application.embedding.service import EmbeddingResult, EmbeddingService, FaceDetection

_DB_SETTINGS = get_database_settings()


class ScanService:
    """Perform face detection + embedding generation and persist results."""

    def __init__(
        self,
        session: AsyncSession,
        detector: FaceDetectorProtocol | None = None,
        generator: EmbeddingGeneratorProtocol | None = None,
        embedder: EmbeddingService | None = None,
    ) -> None:
        self._session = session
        self._detector = detector or StubFaceDetector()
        self._generator = generator or StubEmbeddingGenerator(embedding_dim=_DB_SETTINGS.pgvector_dimension)
        self._embedder = embedder or EmbeddingService(embedding_dim=_DB_SETTINGS.pgvector_dimension)

    async def analyze_media(self, tenant_id: str, media_ids: Iterable[str]) -> IdentityScanJob:
        """Detect faces for the provided media_ids and persist embeddings."""
        media_ids_list = list(media_ids)
        tenant_uuid = uuid.UUID(str(tenant_id))
        started_at = datetime.now(tz=UTC)
        scan_job = IdentityScanJob(
            tenant_id=tenant_uuid,
            status="running",
            media_ids=[_extract_media_id(mid) for mid in media_ids_list],
            total_media=len(media_ids_list),
            processed_media=0,
            identities_detected=0,
            started_at=started_at,
        )
        self._session.add(scan_job)
        await self._session.flush()

        # Delete existing identities for these media items (allows re-scan)
        media_int_ids = [_extract_media_id(mid) for mid in media_ids_list]
        await self._session.execute(
            delete(MediaIdentity).where(
                MediaIdentity.tenant_id == tenant_uuid,
                MediaIdentity.media_id.in_(media_int_ids),
            )
        )

        # Detect faces (deterministic stub in tests)
        detections: list[FaceDetection] = await self._detector.detect(media_ids)
        # Generate embeddings for each detection (keep sequence aligned)
        face_bytes = [str(det.media_id).encode() for det in detections]
        embeddings: list[EmbeddingResult] = await self._generator.generate(face_bytes)

        media_rows = []
        for det, result in zip(detections, embeddings, strict=False):
            media_rows.append(
                MediaIdentity(
                    tenant_id=tenant_uuid,
                    media_id=_extract_media_id(det.media_id),
                    media_url=f"http://example.test/{det.media_id}.jpg",
                    bbox_x=int(det.bbox[0]),
                    bbox_y=int(det.bbox[1]),
                    bbox_width=int(det.bbox[2] - det.bbox[0]),
                    bbox_height=int(det.bbox[3] - det.bbox[1]),
                    confidence=float(det.confidence),
                    embedding=result.embedding.tolist(),
                )
            )
        self._session.add_all(media_rows)

        scan_job.processed_media = len(media_rows)
        scan_job.identities_detected = len(media_rows)
        scan_job.status = "completed"
        scan_job.completed_at = datetime.now(tz=UTC)
        await self._session.commit()
        # Note: Don't refresh after commit - the object already has all values set
        # and refresh can fail if session expires objects on commit
        return scan_job


def _extract_media_id(value: str) -> int:
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits:
        return int(digits[-6:])
    return abs(hash(value)) % 1_000_000


__all__ = ["ScanService"]
