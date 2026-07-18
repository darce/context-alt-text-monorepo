"""ScanService orchestrates face detection and embedding generation."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityScanJob, MediaIdentity
from db.settings import get_database_settings
from recognition.application.embedding.detector import (
    DetectionAdapterError,
    DetectionTimeoutError,
    FaceDetection,
    FaceDetectorProtocol,
    StubFaceDetector,
)
from recognition.application.embedding.generator import (
    EmbeddingAdapterError,
    EmbeddingGeneratorProtocol,
    EmbeddingResult,
    EmbeddingTimeoutError,
    StubEmbeddingGenerator,
)
from recognition.application.integrations import AdapterBreakerOpenError
from recognition.application.storage import ObjectStore
from recognition.domain.job import JobStatus

ObjectStoreFactory = Callable[[str], ObjectStore]

logger = logging.getLogger(__name__)

_DB_SETTINGS = get_database_settings()


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Per-media identity reconcile counts (row recycling, not assignment/unknown).

    ``matched`` / ``new`` are re-scan MediaIdentity row recycling counts from IoU
    matching. Assignment/unknown metrics live in clustering (FIR-6).
    ``detected`` is the inbound detection count; ``total`` is rows written/updated
    (``matched + new``), preserving the pre-S4 ``process_media_item`` int semantics.
    """

    detected: int
    matched: int
    new: int

    @property
    def total(self) -> int:
        """Rows matched or newly inserted (historical identities_detected count)."""
        return self.matched + self.new

    def __int__(self) -> int:
        return self.total


async def run_scan_three_phase[PersistResult](
    *,
    mark_running: Callable[[], Awaitable[object]],
    detect: Callable[[], Awaitable[list[FaceDetection]]],
    persist: Callable[[list[FaceDetection]], Awaitable[PersistResult]],
) -> PersistResult:
    """Execute the canonical scan-job shape used by both sync and inline callers.

    The helper intentionally stays narrow: it centralizes the ordered phase
    contract that review and tests assert, while the caller retains ownership
    of session scope, tenant context, and failure mapping for each phase.
    """

    await mark_running()
    detections = await detect()
    return await persist(detections)


class ScanService:
    """Perform face detection + embedding generation and persist results."""

    def __init__(
        self,
        session: AsyncSession,
        detector: FaceDetectorProtocol | None = None,
        generator: EmbeddingGeneratorProtocol | None = None,
        object_store_factory: ObjectStoreFactory | None = None,
    ) -> None:
        self._session = session
        self._detector = detector or StubFaceDetector()
        self._generator = generator or StubEmbeddingGenerator(embedding_dim=_DB_SETTINGS.pgvector_dimension)
        # E15-11: when configured, file:// blob URIs in process_media_item
        # are resolved through this factory's ObjectStore (bound to the
        # active tenant) so the worker reads bytes from disk via the same
        # tenant-binding seam the multipart route writes through. Legacy
        # callers (tests, scan_worker before S1.5) leave this None and
        # the URL string is passed straight to the detector unchanged.
        self._object_store_factory = object_store_factory

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
            status=JobStatus.PENDING,
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

    async def mark_job_running(self, job_id: uuid.UUID) -> IdentityScanJob:
        """Mark a scan job as running."""
        scan_job = await self._session.get(IdentityScanJob, job_id)
        if scan_job is None:
            raise RuntimeError(f"scan job not found: {job_id}")

        scan_job.status = JobStatus.RUNNING
        scan_job.started_at = datetime.now(tz=UTC)
        await self._session.commit()
        return scan_job

    async def mark_job_failed(self, job_id: uuid.UUID, error_message: str) -> IdentityScanJob:
        """Mark a scan job as failed with a boundary-level error message."""
        scan_job = await self._session.get(IdentityScanJob, job_id)
        if scan_job is None:
            raise RuntimeError(f"scan job not found: {job_id}")

        scan_job.status = JobStatus.FAILED
        scan_job.error_message = error_message
        scan_job.completed_at = datetime.now(tz=UTC)
        await self._session.commit()
        return scan_job

    async def save_job_results(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: str,
        media_ids: Iterable[str],
        media_sources: Iterable[str] | None,
        detections: list[FaceDetection],
    ) -> IdentityScanJob:
        """Persist detection results and mark job as completed."""
        media_ids_list = list(media_ids)
        sources_list = list(media_sources) if media_sources else media_ids_list
        source_to_media_id = dict(zip(sources_list, media_ids_list, strict=False))
        tenant_uuid = uuid.UUID(str(tenant_id))

        scan_job = await self._session.get(IdentityScanJob, job_id)
        if scan_job is None:
            raise RuntimeError(f"scan job not found: {job_id}")

        [_extract_media_id(mid) for mid in media_ids_list]

        # Group detections by media_id to process them per image for ID recycling
        detections_by_media: dict[int, list[FaceDetection]] = {}
        source_to_media_id_int = {s: _extract_media_id(str(m)) for s, m in source_to_media_id.items()}

        for det in detections:
            mid_int = source_to_media_id_int.get(det.media_id, _extract_media_id(str(det.media_id)))
            if mid_int not in detections_by_media:
                detections_by_media[mid_int] = []
            detections_by_media[mid_int].append(det)

        total_persisted = 0
        for mid_int, dets in detections_by_media.items():
            # Use specific URL if available from sources
            url = None
            for s, m_int in source_to_media_id_int.items():
                if m_int == mid_int and s.startswith(("http://", "https://")):
                    url = s
                    break

            started = time.perf_counter()
            result = await self._persist_identities(
                tenant_uuid=tenant_uuid,
                media_id=mid_int,
                detections=dets,
                media_url=url,
            )
            duration_ms = (time.perf_counter() - started) * 1000.0
            _emit_scan_media_reconciled(
                media_id=mid_int,
                tenant_id=str(tenant_uuid),
                job_id=str(job_id),
                result=result,
                detections=dets,
                duration_ms=duration_ms,
            )
            total_persisted += result.total

        scan_job.processed_media = len(media_ids_list)
        scan_job.identities_detected = total_persisted
        scan_job.status = JobStatus.COMPLETED
        scan_job.completed_at = datetime.now(tz=UTC)
        await self._session.commit()
        return scan_job

    async def process_scan_job(
        self,
        *,
        tenant_id: str,
        job_id: uuid.UUID,
        media_ids: Iterable[str],
        media_sources: Iterable[str] | None = None,
    ) -> IdentityScanJob:
        """Process an existing scan job id and persist embeddings.

        This method preserves the legacy single-session path while routing the
        ordered phase contract through ``run_scan_three_phase``. Callers that
        need the explicit no-DB gap around adapter inference should use
        ``tasks.scan.process_scan_job_inline``.
        """
        sources_list = list(media_sources) if media_sources else list(media_ids)
        try:
            return await run_scan_three_phase(
                mark_running=lambda: self.mark_job_running(job_id),
                detect=lambda: self._detector.detect(sources_list),
                persist=lambda detections: self.save_job_results(
                    job_id=job_id,
                    tenant_id=tenant_id,
                    media_ids=media_ids,
                    media_sources=media_sources,
                    detections=detections,
                ),
            )
        except (
            AdapterBreakerOpenError,
            DetectionTimeoutError,
            EmbeddingTimeoutError,
            DetectionAdapterError,
            EmbeddingAdapterError,
        ) as exc:
            await self.mark_job_failed(job_id, str(exc))
            raise

    async def process_media_item(
        self,
        *,
        tenant_id: str,
        media_id: int,
        media_url: str,
        job_id: uuid.UUID | str | None = None,
    ) -> ReconcileResult:
        """Process a single media item and persist detected identities.

        Uses 'Identity ID Recycling' to preserve existing UUIDs for the same faces,
        which ensures that cluster labels and memberships are not lost during re-scans.

        E15-11: when ``media_url`` is a ``file://`` blob URI minted by the
        multipart upload route's ObjectStore.put, resolve it to raw bytes
        through the per-tenant ``object_store_factory`` (refusing
        cross-tenant URIs at open() time) and pass the bytes to the
        detector. Legacy URL transport (http://, https://) keeps passing
        the URL string unchanged.

        Returns:
            ReconcileResult with detected/matched/new counts. Callers that need
            the historical int (identities_detected = matched + new) use
            ``.total`` or ``int(result)``.
        """
        started = time.perf_counter()
        tenant_uuid = uuid.UUID(str(tenant_id))
        detector_source: bytes | str = media_url
        if media_url.startswith("file://") and self._object_store_factory is not None:
            store = self._object_store_factory(str(tenant_id))
            with store.open(media_url) as fh:
                detector_source = fh.read()
        detections: list[FaceDetection] = await self._detector.detect([detector_source])
        result = await self._persist_identities(
            tenant_uuid=tenant_uuid,
            media_id=media_id,
            detections=detections,
            media_url=media_url,
        )
        duration_ms = (time.perf_counter() - started) * 1000.0
        _emit_scan_media_reconciled(
            media_id=media_id,
            tenant_id=str(tenant_uuid),
            job_id=str(job_id) if job_id is not None else None,
            result=result,
            detections=detections,
            duration_ms=duration_ms,
        )
        return result

    async def _persist_identities(
        self,
        *,
        tenant_uuid: uuid.UUID,
        media_id: int,
        detections: list[FaceDetection],
        media_url: str | None = None,
    ) -> ReconcileResult:
        """Persist detections with Identity ID Recycling; return reconcile counts.

        ``matched`` / ``new`` are re-scan row recycling counts, not assignment or
        unknown labels (those live in clustering / FIR-6).
        """
        # 1. Fetch existing identities for this media item
        stmt = select(MediaIdentity).where(
            MediaIdentity.tenant_id == tenant_uuid,
            MediaIdentity.media_id == int(media_id),
        )
        result = await self._session.execute(stmt)
        existing_identities = list(result.scalars().all())

        # 2. Generate embeddings if needed
        detections_needing_embeddings = [d for d in detections if d.embedding is None]
        if detections_needing_embeddings:
            face_bytes = [str(det.media_id).encode() for det in detections_needing_embeddings]
            embeddings: list[EmbeddingResult] = await self._generator.generate(face_bytes)
            for det, emb_result in zip(detections_needing_embeddings, embeddings, strict=False):
                det.embedding = emb_result.embedding

        # 3. Match new detections to existing identities using BBOX IOU
        matched: list[tuple[MediaIdentity, FaceDetection]] = []
        unmatched_new: list[FaceDetection] = list(detections)
        orphaned_old: list[MediaIdentity] = list(existing_identities)

        for old in existing_identities:
            if not unmatched_new:
                break

            best_iou = 0.0
            best_det_idx = -1
            old_bbox = (old.bbox_x, old.bbox_y, old.bbox_x + old.bbox_width, old.bbox_y + old.bbox_height)

            for idx, det in enumerate(unmatched_new):
                iou = _compute_iou(old_bbox, det.bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_det_idx = idx

            if best_iou > 0.5:
                matched.append((old, unmatched_new.pop(best_det_idx)))
                orphaned_old.remove(old)

        expected_dim = int(_DB_SETTINGS.pgvector_dimension)

        # 4. Update matched identities (preserves PK/UUID)
        for old_row, det in matched:
            if det.embedding is None:
                continue
            _assert_embedding_dimension(det, expected_dim=expected_dim)
            if not det.model_id:
                raise ValueError("embedding_model provenance missing on FaceDetection")
            old_row.bbox_x = int(det.bbox[0])
            old_row.bbox_y = int(det.bbox[1])
            old_row.bbox_width = int(det.bbox[2] - det.bbox[0])
            old_row.bbox_height = int(det.bbox[3] - det.bbox[1])
            old_row.confidence = float(det.confidence)
            old_row.embedding = det.embedding.tolist()
            old_row.embedding_model = det.model_id
            old_row.pose_pitch = det.pose_pitch
            old_row.pose_yaw = det.pose_yaw
            old_row.pose_roll = det.pose_roll
            if det.landmark_quality is not None:
                old_row.quality_score = det.landmark_quality
            old_row.image_phash = det.image_phash
            old_row.updated_at = datetime.now(tz=UTC)

        # 5. Insert new detections
        new_rows = []
        default_url = f"http://example.test/{media_id}.jpg"
        final_url = media_url or default_url

        for det in unmatched_new:
            if det.embedding is None:
                continue
            _assert_embedding_dimension(det, expected_dim=expected_dim)
            if not det.model_id:
                raise ValueError("embedding_model provenance missing on FaceDetection")
            new_rows.append(
                MediaIdentity(
                    tenant_id=tenant_uuid,
                    media_id=int(media_id),
                    media_url=str(final_url),
                    bbox_x=int(det.bbox[0]),
                    bbox_y=int(det.bbox[1]),
                    bbox_width=int(det.bbox[2] - det.bbox[0]),
                    bbox_height=int(det.bbox[3] - det.bbox[1]),
                    confidence=float(det.confidence),
                    embedding=det.embedding.tolist(),
                    embedding_model=det.model_id,
                    pose_pitch=det.pose_pitch,
                    pose_yaw=det.pose_yaw,
                    pose_roll=det.pose_roll,
                    quality_score=det.landmark_quality,
                    image_phash=det.image_phash,
                )
            )
        self._session.add_all(new_rows)

        # 6. Delete orphaned
        if orphaned_old:
            for orphan in orphaned_old:
                await self._session.delete(orphan)

        await self._session.flush()
        # total = matched + new preserves pre-S4 int return (len(matched)+len(new_rows)).
        return ReconcileResult(
            detected=len(detections),
            matched=len(matched),
            new=len(new_rows),
        )


def _assert_embedding_dimension(det: FaceDetection, *, expected_dim: int) -> None:
    """Fail closed when a detection embedding does not match pgvector width ([EMB-01])."""
    if det.embedding is None:
        return
    actual = len(det.embedding)
    if actual != expected_dim:
        raise ValueError(f"embedding length {actual} != pgvector_dimension {expected_dim}")


def _face_pipeline_profile() -> str:
    from recognition.config import get_settings

    return str(get_settings().face_pipeline.profile)


def _embedding_model_from_detections(detections: list[FaceDetection]) -> str | None:
    for det in detections:
        if det.model_id:
            return det.model_id
    return None


def _emit_scan_media_reconciled(
    *,
    media_id: int,
    tenant_id: str,
    job_id: str | None,
    result: ReconcileResult,
    detections: list[FaceDetection],
    duration_ms: float,
) -> None:
    """Emit one wide structured log event per processed media item ([OBS-01..03]).

    ``matched`` / ``new`` are re-scan row recycling counts, not assignment/unknown.
    """
    # Late import: correlation middleware lives under interface_adapters.http and
    # importing it at module load would cycle through deps.services → ScanService.
    from recognition.interface_adapters.http.middleware.correlation import get_correlation_id

    logger.info(
        "scan_media_reconciled",
        extra={
            "event": "scan_media_reconciled",
            "media_id": media_id,
            "tenant_id": tenant_id,
            "job_id": job_id,
            "correlation_id": get_correlation_id(),
            "detected": result.detected,
            "matched": result.matched,
            "new": result.new,
            "embedding_model": _embedding_model_from_detections(detections),
            "profile": _face_pipeline_profile(),
            "duration_ms": round(duration_ms, 3),
        },
    )


def _extract_media_id(value: str) -> int:
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits:
        return int(digits[-6:])
    return abs(hash(value)) % 1_000_000


def _compute_iou(bbox1: tuple[float, float, float, float], bbox2: tuple[float, float, float, float]) -> float:
    """Compute Intersection over Union (IoU) of two bounding boxes.

    Boxes are (x1, y1, x2, y2).
    """
    x_left = max(bbox1[0], bbox2[0])
    y_top = max(bbox1[1], bbox2[1])
    x_right = min(bbox1[2], bbox2[2])
    y_bottom = min(bbox1[3], bbox2[3])

    if x_right < x_left or y_bottom < y_top:
        return 0.0

    intersection_area = (x_right - x_left) * (y_bottom - y_top)
    bbox1_area = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    bbox2_area = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])

    union_area = float(bbox1_area + bbox2_area - intersection_area)
    if union_area <= 0:
        return 0.0

    return intersection_area / union_area


__all__ = ["ReconcileResult", "ScanService", "run_scan_three_phase"]
