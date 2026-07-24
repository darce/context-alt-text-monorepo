"""Scan job background tasks and helpers."""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.tenant_context import clear_tenant_context, set_tenant_context
from recognition.application.embedding.detector import (
    DetectionAdapterError,
    DetectionTimeoutError,
    FaceDetection,
    FaceDetectorProtocol,
)
from recognition.application.embedding.generator import (
    EmbeddingAdapterError,
    EmbeddingGeneratorProtocol,
    EmbeddingTimeoutError,
)
from recognition.application.integrations import AdapterBreakerOpenError
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.storage import ObjectStore, ObjectStoreError

ObjectStoreFactory = Callable[[str], ObjectStore]

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from recognition.infrastructure.embeddings import InsightFaceAdapter


# NOTE: Tier-based batch limits removed for MVP. Business tier throttling
# can be added post-MVP when needed. See docs/tasks/4.0/4.11.0/progress-tracking-investigation-2026-01-20.md


def extract_media_id(value: str) -> int:
    """Convert short ID into an integer media identifier."""
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits:
        return int(digits[-6:])
    return abs(hash(value)) % 1_000_000


async def scan_worker_available(session: AsyncSession) -> bool:
    """Return True when a scan worker connection is visible."""
    try:
        result = await session.execute(
            text(
                """
                SELECT 1
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND application_name = :app_name
                LIMIT 1
                """
            ),
            {"app_name": "scan_worker"},
        )
        return result.scalar_one_or_none() is not None
    except Exception:
        return False


async def process_scan_job_inline(
    *,
    tenant_id: str,
    job_id: str,
    media_ids: list[str] | None,
    media_sources: list[str],
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    adapter_provider: Callable[[], Awaitable[InsightFaceAdapter]] | None = None,
) -> None:
    """Inline processor used in tests/dev to keep integration tests deterministic."""
    if session_factory is None:
        from db.session import async_session_factory as default_session_factory

        session_factory = default_session_factory

    # Prepare services OUTSIDE the DB session to avoid holding connections during load
    from recognition.config import get_settings as get_recognition_settings

    settings = get_recognition_settings()

    from recognition.infrastructure.embeddings.runtime_factory import build_embedding_runtime

    # Inline/HTTP path: no shared httpx client (URL-fetch opens per-image clients
    # by design). Worker injects a process-scoped client — see E2E-08 / services.py.
    detector: FaceDetectorProtocol
    generator: EmbeddingGeneratorProtocol
    detector, generator = await build_embedding_runtime(
        settings=settings,
        adapter_provider=adapter_provider,
    )

    sources_list = list(media_sources) if media_sources else (list(media_ids) if media_ids else [])

    async def mark_running_phase() -> None:
        async with session_factory() as session:
            tenant_uuid = uuid.UUID(str(tenant_id))
            await set_tenant_context(session, tenant_uuid)

            from recognition.application.scan.service import ScanService

            scan_service = ScanService(session=session)
            await scan_service.mark_job_running(uuid.UUID(str(job_id)))

    async def detect_phase() -> list[FaceDetection]:
        detections = await detector.detect(sources_list)

        # Generate embeddings if specific detector didn't provide them (e.g. stub or some configs)
        from recognition.application.embedding.generator import EmbeddingResult

        detections_needing_embeddings = [d for d in detections if d.embedding is None]
        if detections_needing_embeddings:
            face_bytes = [str(det.media_id).encode() for det in detections_needing_embeddings]
            embeddings: list[EmbeddingResult] = await generator.generate(face_bytes)
            for det, result in zip(detections_needing_embeddings, embeddings, strict=False):
                det.embedding = result.embedding

        return detections

    async def persist_phase(detections: list[FaceDetection]) -> object:
        async with session_factory() as session:
            tenant_uuid = uuid.UUID(str(tenant_id))
            await set_tenant_context(session, tenant_uuid)

            # We need generator instance here just to satisfy init, even if logic was done above
            from recognition.application.scan.service import ScanService

            scan_service = ScanService(
                session=session,
                detector=detector,
                generator=generator,
            )

            try:
                return await scan_service.save_job_results(
                    job_id=uuid.UUID(str(job_id)),
                    tenant_id=str(tenant_id),
                    media_ids=media_ids or [],
                    media_sources=media_sources,
                    detections=detections,
                )
            except Exception:
                # Explicit rollback before context exit so staged identity work
                # cannot ride a later failure-status session (LOCAL47C-02).
                # Do not rely on AsyncSession.__aexit__ alone.
                await session.rollback()
                raise

    from recognition.application.scan.service import PersistIntegrityError, run_scan_three_phase

    try:
        await run_scan_three_phase(
            mark_running=mark_running_phase,
            detect=detect_phase,
            persist=persist_phase,
        )
    except (
        AdapterBreakerOpenError,
        DetectionTimeoutError,
        EmbeddingTimeoutError,
        DetectionAdapterError,
        EmbeddingAdapterError,
        PersistIntegrityError,
    ) as exc:
        async with session_factory() as session:
            tenant_uuid = uuid.UUID(str(tenant_id))
            await set_tenant_context(session, tenant_uuid)

            from recognition.application.scan.service import ScanService

            scan_service = ScanService(session=session)
            await scan_service.mark_job_failed(uuid.UUID(str(job_id)), str(exc))
        raise


async def populate_scan_job_items_async(
    *,
    tenant_id: str,
    job_id: str,
    media_items: list[tuple[int, str]],
    scan_queue: ScanQueueService | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    correlation_id: str | None = None,
) -> None:
    """Populate scan job items outside the request context."""
    if scan_queue is not None:
        await scan_queue.populate_scan_job_items(
            job_id=uuid.UUID(str(job_id)),
            tenant_id=uuid.UUID(str(tenant_id)),
            media_items=media_items,
            correlation_id=correlation_id,
        )
        return

    from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository

    if session_factory is None:
        from db.session import async_session_factory as default_session_factory

        session_factory = default_session_factory

    async with session_factory() as session:
        tenant_uuid = uuid.UUID(str(tenant_id))
        await set_tenant_context(session, tenant_uuid)
        try:
            repo = SqlAlchemyScanQueueRepository(session)
            queue = ScanQueueService(repo)
            await queue.populate_scan_job_items(
                job_id=uuid.UUID(str(job_id)),
                tenant_id=tenant_uuid,
                media_items=media_items,
                commit_hook=session.commit,
                correlation_id=correlation_id,
            )
            await session.commit()
        finally:
            with contextlib.suppress(Exception):
                await clear_tenant_context(session)


async def chain_populate_and_process(
    *,
    tenant_id: str,
    job_id: str,
    media_items: list[tuple[int, str]],
    media_ids: list[str] | None,
    media_sources: list[str],
    scan_queue: ScanQueueService | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    inline_processing: bool = False,
    adapter_provider: Callable[[], Awaitable[InsightFaceAdapter]] | None = None,
    correlation_id: str | None = None,
    object_store_factory: ObjectStoreFactory | None = None,
) -> None:
    """Chain populate and optional inline processing to ensure order.

    E15-11 S1.6 (revised by BR-07): when ``object_store_factory`` is
    configured AND ``inline_processing`` is True, the per-job blob
    directory is removed via ``factory(tenant_id).cleanup(job_id=job_id)``
    after the inline processor returns OR raises (the bytes have just
    been consumed in this call). For ``inline_processing=False`` the
    external scan_worker has not yet claimed the queue items; cleanup
    on that path is the worker's responsibility (see
    ``ScanItemHandler._refresh_job_progress``). Pre-empting cleanup here
    would leak every multipart job because the worker would find no
    blobs by the time it ran. JSON / URL-transport callers leave the
    factory as None and no cleanup is attempted on either path.
    """
    await populate_scan_job_items_async(
        tenant_id=tenant_id,
        job_id=job_id,
        media_items=media_items,
        scan_queue=scan_queue,
        session_factory=session_factory,
        correlation_id=correlation_id,
    )
    if not inline_processing:
        return
    try:
        await process_scan_job_inline(
            tenant_id=tenant_id,
            job_id=job_id,
            media_ids=media_ids,
            media_sources=media_sources,
            session_factory=session_factory,
            adapter_provider=adapter_provider,
        )
    finally:
        if object_store_factory is not None:
            try:
                store = object_store_factory(tenant_id)
                store.cleanup(job_id=job_id)
            except ObjectStoreError:
                logger.warning(
                    "object_store cleanup failed for job_id=%s tenant_id=%s",
                    job_id,
                    tenant_id,
                )
