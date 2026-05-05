"""Scan worker process for async analyze jobs.

This worker is designed to run as a separate process from the FastAPI web server.
It claims pending `IdentityScanJobItem` rows and processes them in small batches with bounded concurrency.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import IdentityClusteringJob
from db.settings import get_database_settings
from db.tenant_context import enable_rls_bypass, set_tenant_context
from recognition.application.embedding.detector import FaceDetectorProtocol, InsightFaceFaceDetector, StubFaceDetector
from recognition.application.embedding.generator import (
    EmbeddingGeneratorProtocol,
    InsightFaceEmbeddingGenerator,
    StubEmbeddingGenerator,
)
from recognition.application.scan.queue_repository import ScanQueueItem
from recognition.config import get_settings as get_recognition_settings
from recognition.domain.job import JobStatus
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
        # Store the ID of a clustering job that was just re-queued for retry so
        # the MV refresh can be skipped on the cycle where that exact job runs
        # again. Using the job ID (rather than a boolean) makes the suppression
        # job-scoped: the refresh is only postponed for the specific retried job,
        # not for any unrelated pending work that might be claimed first
        # (finding 1169: same-job MV-refresh suppression).
        self._retry_suppressed_job_id: uuid.UUID | None = None

        # E15-11 BR-08: build a tenant-scoped ObjectStore factory rooted at
        # settings.blob_root so the worker can (a) read multipart-uploaded
        # bytes through the same seam the route wrote into, and (b) clean
        # up the per-job blob directory once every queued item finishes
        # (deferred from the inline-only path in chain_populate_and_process).
        # BR-11: store on self so _ensure_embedding_runtime can preserve it
        # when it rebuilds the scan handler after adapter init.
        from recognition.application.storage import FilesystemObjectStore

        worker_blob_root = settings.blob_root

        def _worker_object_store_factory(tenant_id: str):
            return FilesystemObjectStore(root=worker_blob_root, tenant_id=tenant_id)

        self._object_store_factory = _worker_object_store_factory

        self._scan_handler = ScanItemHandler(
            session_factory=self._session_factory,
            detector=self._detector,
            generator=self._generator,
            max_attempts=self._config.max_attempts,
            max_concurrency=self._config.max_concurrency,
            object_store_factory=self._object_store_factory,
        )
        self._job_handlers = {
            "split": SplitJobHandler(),
            "curation": CurationJobHandler(),
            "clustering": ClusteringJobHandler(session_factory=self._session_factory),
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

        # BR-11: preserve the ObjectStore factory wired in __init__ so the
        # production scan_handler keeps multipart-blob support after the
        # InsightFace adapter loads (or after the stub fallback fires).
        self._scan_handler = ScanItemHandler(
            session_factory=self._session_factory,
            detector=self._detector,
            generator=self._generator,
            max_attempts=self._config.max_attempts,
            max_concurrency=self._config.max_concurrency,
            object_store_factory=self._object_store_factory,
        )

    async def _process_pending_clustering_jobs(self, *, session: AsyncSession, now: datetime) -> bool:
        stmt = (
            select(IdentityClusteringJob)
            .where(IdentityClusteringJob.status == JobStatus.PENDING.value)
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
        job.status = JobStatus.RUNNING
        job.started_at = now
        await session.flush()
        # Commit the "running" state before handing control to the handler.
        # This releases the SELECT FOR UPDATE row lock acquired during job
        # claiming so that per-chunk checkpoint callbacks (which open a
        # fresh session and UPDATE the same row) do not block indefinitely
        # (finding 1163).
        await session.commit()

        job_id = job.id
        tenant_id = job.tenant_id
        job_type = job.job_type

        try:
            handler = self._job_handlers.get(job.job_type)
            if handler is None:
                await ensure_job_context(session=session, job=job)
                job.status = JobStatus.FAILED
                job.error_message = f"unsupported job_type: {job.job_type}"
                job.completed_at = datetime.now(tz=UTC)
                await session.flush()
            else:
                await handler.handle(job, session)
            return True
        except Exception as exc:  # pragma: no cover
            logger.exception(
                "[worker] Clustering job failed: job_id=%s tenant_id=%s job_type=%s",
                job_id,
                tenant_id,
                job_type,
            )
            # Roll back the main session FIRST so its row lock on the job is
            # released before the fresh session tries to acquire it. Without
            # this, the fresh FOR UPDATE query gets SKIP-LOCKED and returns
            # None, leaving the job reclaimable as pending.
            try:
                await session.rollback()
            except Exception:
                logger.warning("[worker] Failed to rollback main session for job_id=%s", job_id)
            # Use a fresh session to persist retry/failed status durably
            # (finding 1161 + finding 1168: bounded retry budget).
            try:
                async with self._session_factory() as fresh_session:
                    await enable_rls_bypass(fresh_session)
                    # Seam 5 (defense-in-depth): also restore tenant context so any
                    # RLS-gated reads on the failed_job row see the correct tenant.
                    # tenant_id is captured before session.rollback() above.
                    if tenant_id is not None:
                        try:
                            await set_tenant_context(fresh_session, uuid.UUID(str(tenant_id)))
                        except Exception:
                            logger.warning(
                                "[worker] Failed to set tenant context in error recovery for job_id=%s; bypass still active",
                                job_id,
                            )
                    failed_stmt = (
                        select(IdentityClusteringJob)
                        .where(IdentityClusteringJob.id == job_id)
                        .with_for_update(skip_locked=True)
                    )
                    fresh_result = await fresh_session.execute(failed_stmt)
                    failed_job = fresh_result.scalar_one_or_none()
                    if failed_job is not None:
                        # Persist retry/checkpoint metadata in payload.
                        existing_payload = dict(failed_job.payload) if failed_job.payload else {}
                        _prev_retry = existing_payload.get("retry_count", 0)
                        new_retry_count = (_prev_retry if isinstance(_prev_retry, int) else 0) + 1
                        existing_payload["retry_count"] = new_retry_count
                        existing_payload["last_error_code"] = type(exc).__name__
                        existing_payload["last_error_at"] = datetime.now(tz=UTC).isoformat()
                        existing_payload["current_stage"] = "clustering"
                        failed_job.payload = existing_payload

                        # Retry budget: re-queue only for known-transient infrastructure
                        # failures; all other errors (including IntegrityError, ValueError,
                        # RuntimeError) fail immediately without retrying because they are
                        # deterministic and retrying cannot fix them
                        # (finding 1168: transient-vs-deterministic classification policy).
                        _transient_exceptions = (
                            OSError,
                            TimeoutError,
                            ConnectionError,
                        )
                        is_transient = isinstance(exc, _transient_exceptions)
                        max_retries = self._config.max_attempts
                        if is_transient and new_retry_count < max_retries:
                            failed_job.status = JobStatus.PENDING
                            failed_job.started_at = None
                            failed_job.completed_at = None
                            self._retry_suppressed_job_id = failed_job.id
                            logger.warning(
                                "[worker] Clustering job %s transient failure (attempt %d/%d), re-queuing: %s",
                                job_id,
                                new_retry_count,
                                max_retries,
                                type(exc).__name__,
                            )
                        else:
                            failed_job.status = JobStatus.FAILED
                            failed_job.error_message = str(exc)
                            failed_job.completed_at = datetime.now(tz=UTC)
                            logger.error(
                                "[worker] Clustering job %s failed permanently (attempt %d/%d%s): %s",
                                job_id,
                                new_retry_count,
                                max_retries,
                                ", deterministic" if not is_transient else "",
                                exc,
                            )
                        await fresh_session.commit()
            except Exception:
                logger.exception(
                    "[worker] Failed to persist retry/failed status for job_id=%s; job may be reclaimed",
                    job_id,
                )
            return True

    async def _refresh_mv_if_needed(self, session: AsyncSession, now: datetime) -> None:
        """Periodically refresh the cluster centroids materialized view."""
        # Job-scoped retry suppression: if a specific clustering job was just
        # re-queued, skip refresh only when that exact job is next in the queue.
        # A non-locking peek query identifies the next pending job without
        # racing with the FOR UPDATE claim that follows (finding 1169).
        if self._retry_suppressed_job_id is not None:
            peek_stmt = (
                select(IdentityClusteringJob.id)
                .where(IdentityClusteringJob.status == JobStatus.PENDING.value)
                .where(IdentityClusteringJob.job_type.in_(["clustering", "curation", "split"]))
                .order_by(IdentityClusteringJob.created_at.asc())
                .limit(1)
            )
            next_job_id = await session.scalar(peek_stmt)
            suppressed = next_job_id == self._retry_suppressed_job_id
            self._retry_suppressed_job_id = None  # always clear
            if suppressed:
                logger.debug("[worker] Skipping MV refresh for retried job %s", next_job_id)
                return
        elapsed = (now - self._last_mv_refresh_time).total_seconds()
        if elapsed < self._config.mv_refresh_interval_seconds:
            return

        logger.info("[worker] Refreshing centroids MV (elapsed=%.1fs)", elapsed)
        try:
            from sqlalchemy import text

            from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

            cluster_repo = SqlAlchemyClusterRepository(session)
            succeeded = await cluster_repo.refresh_centroids_view_concurrent()
            if succeeded:
                await session.commit()
                # Stamp completion time AFTER commit so the interval is measured
                # from the actual end of the refresh, not the start.  If commit
                # fails, _last_mv_refresh_time is not advanced and the next cycle
                # retries immediately.
                self._last_mv_refresh_time = datetime.now(tz=UTC)
                # Re-establish RLS bypass after commit: SET LOCAL is transaction-scoped
                # and is cleared by COMMIT.  The health check queries must see all
                # tenants' rows, not just the current-transaction filtered view.
                await enable_rls_bypass(session)
                # Health check: warn if MV row count diverges from identity_clusters.
                try:
                    mv_count = await session.scalar(text("SELECT COUNT(*) FROM mv_identity_cluster_centroids"))
                    cluster_count = await session.scalar(text("SELECT COUNT(*) FROM identity_clusters"))
                    if mv_count != cluster_count:
                        logger.warning(
                            "[worker] Centroid MV health check divergence: mv_count=%s identity_clusters=%s",
                            mv_count,
                            cluster_count,
                        )
                    else:
                        logger.debug("[worker] Centroid MV health check ok: count=%s", mv_count)
                except Exception:
                    logger.debug("[worker] Centroid MV health check skipped (may be SQLite or unsupported)")
        except Exception:
            logger.exception("[worker] Failed to refresh centroids MV")
            # Don't update _last_mv_refresh_time so we retry next cycle.


async def _main() -> None:
    """CLI entrypoint for local development.

        Uses the shared DB settings loader so local legacy DB aliases are
        canonicalized before the worker probes or opens connections.
    """
    import sys

    from sqlalchemy import text

    from api.logging_config import configure_logging

    configure_logging("INFO")

    postgres_dsn = get_database_settings().postgres_dsn
    if not postgres_dsn:
        logger.error("Database DSN not configured. Exiting.")
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
