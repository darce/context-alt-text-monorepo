"""Scan worker process for async analyze jobs.

This worker is designed to run as a separate process from the FastAPI web server.
It claims pending `IdentityScanJobItem` rows and processes them in small batches with bounded concurrency.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import IdentityClusteringJob
from db.tenant_context import enable_rls_bypass
from recognition.application.embedding.detector import FaceDetectorProtocol, InsightFaceFaceDetector, StubFaceDetector
from recognition.application.embedding.generator import (
    EmbeddingGeneratorProtocol,
    InsightFaceEmbeddingGenerator,
    StubEmbeddingGenerator,
)
from recognition.application.scan.queue_repository import ScanQueueItem
from recognition.config import get_settings as get_recognition_settings
from recognition.infrastructure.embeddings import get_shared_insightface_adapter
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.worker.handlers.clustering import ClusteringJobHandler, CurationJobHandler, SplitJobHandler
from recognition.worker.handlers.scan import ScanItemHandler
from recognition.worker.handlers.utils import ensure_job_context

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScanWorkerConfig:
    """Configuration for ScanWorker."""

    postgres_dsn: str
    poll_interval_seconds: float = 1.0
    claim_batch_size: int = 10
    max_concurrency: int = 5
    stale_after_seconds: int = 600
    max_attempts: int = 3
    mv_refresh_interval_seconds: int = 60


class ScanWorker:
    """Background worker that claims and processes scan queue items."""

    def __init__(self, config: ScanWorkerConfig) -> None:
        self._config = config
        connect_args: dict[str, object] = {}
        if config.postgres_dsn.startswith("postgresql"):
            connect_args["server_settings"] = {"application_name": "scan_worker"}
        self._engine = create_async_engine(
            config.postgres_dsn,
            echo=False,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine, expire_on_commit=False
        )
        self._http_client: httpx.AsyncClient | None = None
        self._detector: FaceDetectorProtocol = StubFaceDetector()
        self._generator: EmbeddingGeneratorProtocol = StubEmbeddingGenerator()
        self._embedding_runtime_ready = False
        self._embedding_retry_after: datetime | None = None

        settings = get_recognition_settings()
        self._runtime_mode = settings.runtime_mode

        self._last_mv_refresh_time: datetime = datetime.min.replace(tzinfo=UTC)
        self._scan_handler = ScanItemHandler(
            session_factory=self._session_factory,
            detector=self._detector,
            generator=self._generator,
            max_attempts=self._config.max_attempts,
            max_concurrency=self._config.max_concurrency,
        )
        self._job_handlers = {
            "split": SplitJobHandler(),
            "curation": CurationJobHandler(),
            "clustering": ClusteringJobHandler(),
        }

    async def __aenter__(self) -> ScanWorker:
        """Prepare worker resources."""
        await self._ensure_embedding_runtime()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Release worker resources."""
        if self._http_client is not None:
            await self._http_client.aclose()
        await self._engine.dispose()

    async def run_forever(self) -> None:
        """Run a claim/process loop forever.

        The worker claims pending items across all jobs using SKIP LOCKED on Postgres.
        """
        while True:
            claimed: list[ScanQueueItem] = []
            should_sleep = False
            async with self._session_factory() as session:
                await enable_rls_bypass(session)
                repo = SqlAlchemyScanQueueRepository(session)

                now = datetime.now(tz=UTC)
                await self._refresh_mv_if_needed(session, now)

                if await self._process_pending_clustering_jobs(session=session, now=now):
                    await session.commit()
                    should_sleep = True
                else:
                    await repo.reclaim_stale_items(
                        stale_after_seconds=self._config.stale_after_seconds,
                        max_attempts=self._config.max_attempts,
                        now=now,
                    )

                    claimed = await repo.claim_pending_items_any(limit=self._config.claim_batch_size, now=now)
                    if not claimed:
                        await session.commit()
                        should_sleep = True
                    else:
                        for job_id in {item.job_id for item in claimed}:
                            await repo.mark_job_running(job_id=job_id, started_at=now)
                        await session.commit()

            if should_sleep:
                await asyncio.sleep(self._config.poll_interval_seconds)
                continue

            await self._process_claimed_items(claimed=claimed)

    async def _process_claimed_items(
        self,
        *,
        claimed: list[ScanQueueItem],
    ) -> None:
        await self._ensure_embedding_runtime()
        await self._scan_handler.process_items(claimed=claimed)

    async def _ensure_embedding_runtime(self) -> None:
        """Initialize scan inference dependencies once per worker process."""
        if self._embedding_runtime_ready or self._runtime_mode == "test":
            return
        now = datetime.now(tz=UTC)
        if self._embedding_retry_after is not None and now < self._embedding_retry_after:
            return
        try:
            adapter = await get_shared_insightface_adapter()
            if self._http_client is None:
                self._http_client = httpx.AsyncClient(timeout=30.0)
            self._detector = InsightFaceFaceDetector(adapter, client=self._http_client)
            self._generator = InsightFaceEmbeddingGenerator(adapter)
            self._embedding_retry_after = None
            self._embedding_runtime_ready = True
        except Exception:
            logger.exception("Failed to initialize InsightFace adapter, falling back to stubs.")
            self._detector = StubFaceDetector()
            self._generator = StubEmbeddingGenerator()
            self._embedding_retry_after = now + timedelta(seconds=30)

        self._scan_handler = ScanItemHandler(
            session_factory=self._session_factory,
            detector=self._detector,
            generator=self._generator,
            max_attempts=self._config.max_attempts,
            max_concurrency=self._config.max_concurrency,
        )

    async def _process_pending_clustering_jobs(self, *, session: AsyncSession, now: datetime) -> bool:
        stmt = (
            select(IdentityClusteringJob)
            .where(IdentityClusteringJob.status == "pending")
            .where(IdentityClusteringJob.job_type.in_(["clustering", "curation", "split"]))
            .order_by(IdentityClusteringJob.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None:
            return False

        await ensure_job_context(session=session, job=job)
        job.status = "running"
        job.started_at = now
        await session.flush()

        try:
            handler = self._job_handlers.get(job.job_type)
            if handler is None:
                await ensure_job_context(session=session, job=job)
                job.status = "failed"
                job.error_message = f"unsupported job_type: {job.job_type}"
                job.completed_at = datetime.now(tz=UTC)
                await session.flush()
            else:
                await handler.handle(job, session)
            return True
        except Exception as exc:  # pragma: no cover
            await ensure_job_context(session=session, job=job)
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(tz=UTC)
            await session.flush()
            return True

    async def _refresh_mv_if_needed(self, session: AsyncSession, now: datetime) -> None:
        """Periodically refresh the cluster centroids materialized view."""
        elapsed = (now - self._last_mv_refresh_time).total_seconds()
        if elapsed < self._config.mv_refresh_interval_seconds:
            return

        logger.info("[worker] Refreshing centroids MV (elapsed=%.1fs)", elapsed)
        try:
            from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

            cluster_repo = SqlAlchemyClusterRepository(session)
            await cluster_repo.refresh_centroids_view_concurrent()
            self._last_mv_refresh_time = now
            await session.commit()
        except Exception:
            logger.exception("[worker] Failed to refresh centroids MV")
            # Don't update _last_mv_refresh_time so we retry next cycle,
            # but maybe backoff/limit retries logic is needed if it fails persistently?
            # For now, let it retry next loop.


async def _main() -> None:
    """CLI entrypoint for local development.

    Expected environment variables:
      - POSTGRES_DSN (required)
    """
    import os
    import sys

    from sqlalchemy import text

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    postgres_dsn = os.environ.get("POSTGRES_DSN")
    if not postgres_dsn:
        logger.error("POSTGRES_DSN not set. Exiting.")
        sys.exit(1)

    # Wait for database availability before starting main loop
    async def wait_for_database(dsn: str, max_retries: int = 30) -> bool:
        """Wait for database to be available.

        Returns True if available, False if exhausted retries.
        """
        engine = create_async_engine(dsn, echo=False)
        for attempt in range(max_retries):
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                    logger.info("Database connection established.")
                    await engine.dispose()
                    return True
            except Exception as exc:
                logger.warning(
                    "Database not ready (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries,
                    exc,
                )
                await asyncio.sleep(2)
        await engine.dispose()
        return False

    # Initial wait for database
    if not await wait_for_database(postgres_dsn):
        logger.error("Database unavailable after max retries. Exiting.")
        sys.exit(1)

    backoff = 2.0
    while True:
        try:
            async with ScanWorker(ScanWorkerConfig(postgres_dsn=postgres_dsn)) as worker:
                await worker.run_forever()
            backoff = 2.0
        except asyncio.CancelledError:
            logger.info("Scan worker stopped.")
            break
        except Exception as exc:
            logger.error("Scan worker crashed (retrying in %.1fs): %s", backoff, exc)
            # Wait for db to be available again before retrying
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            if not await wait_for_database(postgres_dsn, max_retries=10):
                logger.warning("Database still unavailable, will retry...")


if __name__ == "__main__":
    asyncio.run(_main())
