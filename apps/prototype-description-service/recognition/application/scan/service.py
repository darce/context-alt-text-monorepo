"""ScanService orchestrates face detection and embedding generation."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

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

    async def analyze_media(
        self,
        tenant_id: str,
        media_ids: Iterable[str],
        media_sources: Iterable[str] | None = None,
    ) -> IdentityScanJob:
        """Detect faces for the provided media and persist embeddings.

        Args:
            tenant_id: Tenant identifier.
            media_ids: List of media IDs for tracking/persistence.
            media_sources: Optional list of URLs/sources for the detector.
                           If not provided, media_ids are passed to detector.
        """
        media_ids_list = list(media_ids)
        scan_job = IdentityScanJob(
            tenant_id=uuid.UUID(str(tenant_id)),
            status="pending",
            media_ids=[_extract_media_id(mid) for mid in media_ids_list],
            total_media=len(media_ids_list),
            processed_media=0,
            identities_detected=0,
        )
        self._session.add(scan_job)
        await self._session.flush()
        return await self.process_scan_job(
            tenant_id=tenant_id,
            job_id=scan_job.id,
            media_ids=media_ids_list,
            media_sources=media_sources,
        )

    async def process_scan_job(
        self,
        *,
        tenant_id: str,
        job_id: uuid.UUID,
        media_ids: Iterable[str],
        media_sources: Iterable[str] | None = None,
    ) -> IdentityScanJob:
        """Process an existing scan job id and persist embeddings.

        This is used by the async queue worker path.

        Args:
            tenant_id: Tenant identifier.
            job_id: Existing scan job UUID to update.
            media_ids: List of media IDs for tracking/persistence.
            media_sources: Optional list of URLs/sources for the detector.

        Returns:
            Updated IdentityScanJob.
        """
        media_ids_list = list(media_ids)
        sources_list = list(media_sources) if media_sources else media_ids_list
        source_to_media_id = dict(zip(sources_list, media_ids_list, strict=False))

        tenant_uuid = uuid.UUID(str(tenant_id))
        started_at = datetime.now(tz=UTC)
        scan_job = await self._session.get(IdentityScanJob, job_id)
        if scan_job is None:
            raise RuntimeError(f"scan job not found: {job_id}")
        scan_job.status = "running"
        scan_job.started_at = started_at
        scan_job.total_media = len(media_ids_list)
        scan_job.media_ids = [_extract_media_id(mid) for mid in media_ids_list]
        await self._session.flush()

        media_int_ids = [_extract_media_id(mid) for mid in media_ids_list]
        await self._session.execute(
            delete(MediaIdentity).where(
                MediaIdentity.tenant_id == tenant_uuid,
                MediaIdentity.media_id.in_(media_int_ids),
            )
        )

        detections: list[FaceDetection] = await self._detector.detect(sources_list)

        detections_needing_embeddings = [d for d in detections if d.embedding is None]
        if detections_needing_embeddings:
            face_bytes = [str(det.media_id).encode() for det in detections_needing_embeddings]
            embeddings: list[EmbeddingResult] = await self._generator.generate(face_bytes)
            for det, result in zip(detections_needing_embeddings, embeddings, strict=False):
                det.embedding = result.embedding

        media_rows = []
        for det in detections:
            if det.embedding is None:
                logger.warning("Skipping detection without embedding: %s", str(det.media_id)[:50])
                continue
            original_media_id = source_to_media_id.get(det.media_id, det.media_id)
            media_url = (
                det.media_id
                if str(det.media_id).startswith(("http://", "https://"))
                else f"http://example.test/{det.media_id}.jpg"
            )
            media_rows.append(
                MediaIdentity(
                    tenant_id=tenant_uuid,
                    media_id=_extract_media_id(str(original_media_id)),
                    media_url=media_url,
                    bbox_x=int(det.bbox[0]),
                    bbox_y=int(det.bbox[1]),
                    bbox_width=int(det.bbox[2] - det.bbox[0]),
                    bbox_height=int(det.bbox[3] - det.bbox[1]),
                    confidence=float(det.confidence),
                    embedding=det.embedding.tolist(),
                    pose_pitch=det.pose_pitch,
                    pose_yaw=det.pose_yaw,
                    pose_roll=det.pose_roll,
                    age=det.age,
                    gender=det.gender,
                )
            )
        self._session.add_all(media_rows)

        scan_job.processed_media = len(media_ids_list)
        scan_job.identities_detected = len(media_rows)
        scan_job.status = "completed"
        scan_job.completed_at = datetime.now(tz=UTC)
        await self._session.commit()
        return scan_job

    async def process_media_item(
        self,
        *,
        tenant_id: str,
        media_id: int,
        media_url: str,
    ) -> int:
        """Process a single media item and persist detected identities.

        This method is designed for the async queue worker. It does not create or update
        an `IdentityScanJob` row; it only updates `MediaIdentity` rows for the provided media id.

        Args:
            tenant_id: Tenant identifier.
            media_id: Integer media identifier to associate with persisted identities.
            media_url: Source URL (or identifier) used by the detector.

        Returns:
            Number of identities persisted for this media item.
        """
        tenant_uuid = uuid.UUID(str(tenant_id))

        await self._session.execute(
            delete(MediaIdentity).where(
                MediaIdentity.tenant_id == tenant_uuid,
                MediaIdentity.media_id == int(media_id),
            )
        )

        detections: list[FaceDetection] = await self._detector.detect([media_url])

        detections_needing_embeddings = [d for d in detections if d.embedding is None]
        if detections_needing_embeddings:
            face_bytes = [str(det.media_id).encode() for det in detections_needing_embeddings]
            embeddings: list[EmbeddingResult] = await self._generator.generate(face_bytes)
            for det, result in zip(detections_needing_embeddings, embeddings, strict=False):
                det.embedding = result.embedding

        media_rows = []
        for det in detections:
            if det.embedding is None:
                continue
            media_rows.append(
                MediaIdentity(
                    tenant_id=tenant_uuid,
                    media_id=int(media_id),
                    media_url=str(media_url),
                    bbox_x=int(det.bbox[0]),
                    bbox_y=int(det.bbox[1]),
                    bbox_width=int(det.bbox[2] - det.bbox[0]),
                    bbox_height=int(det.bbox[3] - det.bbox[1]),
                    confidence=float(det.confidence),
                    embedding=det.embedding.tolist(),
                    pose_pitch=det.pose_pitch,
                    pose_yaw=det.pose_yaw,
                    pose_roll=det.pose_roll,
                    age=det.age,
                    gender=det.gender,
                )
            )

        self._session.add_all(media_rows)
        await self._session.flush()
        return len(media_rows)


def _extract_media_id(value: str) -> int:
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits:
        return int(digits[-6:])
    return abs(hash(value)) % 1_000_000


__all__ = ["ScanService"]
