"""Scan worker process for async analyze jobs.

This worker is designed to run as a separate process from the FastAPI web server.
It claims pending `IdentityScanJobItem` rows and processes them sequentially in small batches.

The initial implementation focuses on durability and correctness (no dropped work), not throughput.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.tenant_context import enable_rls_bypass
from recognition.application.embedding.detector import FaceDetectorProtocol, InsightFaceFaceDetector, StubFaceDetector
from recognition.application.embedding.generator import (
    EmbeddingGeneratorProtocol,
    InsightFaceEmbeddingGenerator,
    StubEmbeddingGenerator,
)
from recognition.application.embedding.service import EmbeddingService
from recognition.application.scan.queue_repository import ScanQueueItem
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.scan.service import ScanService
from recognition.config import get_settings as get_recognition_settings
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScanWorkerConfig:
    """Configuration for ScanWorker."""

    postgres_dsn: str
    poll_interval_seconds: float = 1.0
    claim_batch_size: int = 10
    stale_after_seconds: int = 600
    max_attempts: int = 3


class ScanWorker:
    """Background worker that claims and processes scan queue items."""

    def __init__(self, config: ScanWorkerConfig) -> None:
        self._config = config
        self._engine = create_async_engine(config.postgres_dsn, echo=False, pool_pre_ping=True)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine, expire_on_commit=False
        )

    async def run_forever(self) -> None:
        """Run a claim/process loop forever.

        The worker claims pending items across all jobs using SKIP LOCKED on Postgres.
        """
        while True:
            async with self._session_factory() as session:
                await enable_rls_bypass(session)
                repo = SqlAlchemyScanQueueRepository(session)
                queue = ScanQueueService(repo)

                now = datetime.now(tz=UTC)
                await repo.reclaim_stale_items(
                    stale_after_seconds=self._config.stale_after_seconds,
                    max_attempts=self._config.max_attempts,
                    now=now,
                )

                claimed = await repo.claim_pending_items_any(limit=self._config.claim_batch_size, now=now)
                if not claimed:
                    await session.commit()
                    await asyncio.sleep(self._config.poll_interval_seconds)
                    continue

                for job_id in {item.job_id for item in claimed}:
                    await repo.mark_job_running(job_id=job_id, started_at=now)

                scan_service = _build_scan_service(session)
                await self._process_claimed_items(
                    session=session,
                    scan_service=scan_service,
                    queue=queue,
                    repo=repo,
                    claimed=claimed,
                )
                await session.commit()

    async def _process_claimed_items(
        self,
        *,
        session: AsyncSession,
        scan_service: ScanService,
        queue: ScanQueueService,
        repo: SqlAlchemyScanQueueRepository,
        claimed: list[ScanQueueItem],
    ) -> None:
        now = datetime.now(tz=UTC)
        affected_jobs: set[uuid.UUID] = set()
        for item in claimed:
            affected_jobs.add(item.job_id)
            try:
                identities_detected = await scan_service.process_media_item(
                    tenant_id=str(item.tenant_id),
                    media_id=item.media_id,
                    media_url=item.media_url,
                )
                await repo.mark_item_completed(
                    item_id=item.id,
                    completed_at=now,
                    identities_detected=identities_detected,
                )
            except Exception as exc:  # pragma: no cover
                error_message = str(exc)
                await self._handle_item_failure(
                    repo=repo,
                    item=item,
                    now=now,
                    error_message=error_message,
                )

        for job_id in affected_jobs:
            await queue.refresh_job_progress(job_id=job_id)

    async def _handle_item_failure(
        self,
        *,
        repo: SqlAlchemyScanQueueRepository,
        item: ScanQueueItem,
        now: datetime,
        error_message: str,
    ) -> None:
        if item.attempts < self._config.max_attempts:
            await repo.release_item_for_retry(item_id=item.id, error_message=error_message)
            return
        await repo.mark_item_failed(item_id=item.id, completed_at=now, error_message=error_message)


def _build_scan_service(session: AsyncSession) -> ScanService:
    settings = get_recognition_settings()
    runtime_mode = settings.runtime_mode
    embedder = EmbeddingService()
    if runtime_mode == "test":
        detector: FaceDetectorProtocol = StubFaceDetector()
        generator: EmbeddingGeneratorProtocol = StubEmbeddingGenerator()
    else:
        try:
            from recognition.infrastructure.embeddings import InsightFaceAdapter

            adapter = InsightFaceAdapter()
            detector = InsightFaceFaceDetector(adapter)
            generator = InsightFaceEmbeddingGenerator(adapter)
        except Exception:
            detector = StubFaceDetector()
            generator = StubEmbeddingGenerator()
    return ScanService(session=session, detector=detector, generator=generator, embedder=embedder)


async def _main() -> None:
    """CLI entrypoint for local development.

    Expected environment variables:
      - POSTGRES_DSN (required)
    """
    import os

    postgres_dsn = os.environ["POSTGRES_DSN"]
    worker = ScanWorker(ScanWorkerConfig(postgres_dsn=postgres_dsn))
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(_main())
