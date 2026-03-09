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
from recognition.application.embedding.detector import FaceDetectorProtocol
from recognition.application.embedding.generator import EmbeddingGeneratorProtocol
from recognition.application.scan.scan_queue_service import ScanQueueService

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
    runtime_mode = settings.runtime_mode

    detector: FaceDetectorProtocol
    generator: EmbeddingGeneratorProtocol

    if runtime_mode == "test":
        from recognition.application.embedding.detector import StubFaceDetector
        from recognition.application.embedding.generator import StubEmbeddingGenerator

        detector = StubFaceDetector()
        generator = StubEmbeddingGenerator()
    else:
        try:
            from recognition.application.embedding.detector import InsightFaceFaceDetector, StubFaceDetector
            from recognition.application.embedding.generator import (
                InsightFaceEmbeddingGenerator,
                StubEmbeddingGenerator,
            )

            if adapter_provider is not None:
                adapter: InsightFaceAdapter = await adapter_provider()
            else:
                from recognition.infrastructure.embeddings import get_shared_insightface_adapter

                adapter = await get_shared_insightface_adapter()

            detector = InsightFaceFaceDetector(adapter)
            generator = InsightFaceEmbeddingGenerator(adapter)
        except ImportError:
            from recognition.application.embedding.detector import StubFaceDetector
            from recognition.application.embedding.generator import StubEmbeddingGenerator

            logger.warning("InsightFace not installed, using stub detectors.")
            detector = StubFaceDetector()
            generator = StubEmbeddingGenerator()

    # 1. Mark Running (Short transaction)
    async with session_factory() as session:
        tenant_uuid = uuid.UUID(str(tenant_id))
        await set_tenant_context(session, tenant_uuid)

        from recognition.application.scan.service import ScanService

        scan_service = ScanService(session=session)
        await scan_service.mark_job_running(uuid.UUID(str(job_id)))

    # 2. Inference (No DB connection)
    sources_list = list(media_sources) if media_sources else (list(media_ids) if media_ids else [])
    detections = await detector.detect(sources_list)

    # Generate embeddings if specific detector didn't provide them (e.g. stub or some configs)
    from recognition.application.embedding.generator import EmbeddingResult

    detections_needing_embeddings = [d for d in detections if d.embedding is None]
    if detections_needing_embeddings:
        face_bytes = [str(det.media_id).encode() for det in detections_needing_embeddings]
        embeddings: list[EmbeddingResult] = await generator.generate(face_bytes)
        for det, result in zip(detections_needing_embeddings, embeddings, strict=False):
            det.embedding = result.embedding

    # 3. Save Results (Short transaction)
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

        await scan_service.save_job_results(
            job_id=uuid.UUID(str(job_id)),
            tenant_id=str(tenant_id),
            media_ids=media_ids or [],
            media_sources=media_sources,
            detections=detections,
        )


async def populate_scan_job_items_async(
    *,
    tenant_id: str,
    job_id: str,
    media_items: list[tuple[int, str]],
    scan_queue: ScanQueueService | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Populate scan job items outside the request context."""
    if scan_queue is not None:
        await scan_queue.populate_scan_job_items(
            job_id=uuid.UUID(str(job_id)),
            tenant_id=uuid.UUID(str(tenant_id)),
            media_items=media_items,
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
) -> None:
    """Chain populate and optional inline processing to ensure order."""
    await populate_scan_job_items_async(
        tenant_id=tenant_id,
        job_id=job_id,
        media_items=media_items,
        scan_queue=scan_queue,
        session_factory=session_factory,
    )
    if inline_processing:
        await process_scan_job_inline(
            tenant_id=tenant_id,
            job_id=job_id,
            media_ids=media_ids,
            media_sources=media_sources,
            session_factory=session_factory,
            adapter_provider=adapter_provider,
        )
