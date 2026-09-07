"""Scan worker process for async analyze jobs.

This worker is designed to run as a separate process from the FastAPI web server.
It claims pending `IdentityScanJobItem` rows and processes them in small batches with bounded concurrency.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from prometheus_client import start_http_server
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import IdentityClusteringJob
from db.settings import get_database_settings
from db.tenant_context import enable_rls_bypass, set_tenant_context
from recognition.application.embedding.detector import (
    FaceDetectorProtocol,
    StubFaceDetector,
    UnavailableFaceDetector,
)
from recognition.application.embedding.generator import (
    EmbeddingGeneratorProtocol,
    StubEmbeddingGenerator,
)
from recognition.application.scan.capability import (
    ScanWorkerCounters,
    format_capability_reason,
    publish_embedding_runtime_capability,
)
from recognition.application.scan.queue_repository import ScanQueueItem
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.config import get_settings as get_recognition_settings
from recognition.domain.job import CLUSTERING_JOB_TYPES, JobStatus
from recognition.domain.repositories import MvRefreshOutcome
from recognition.infrastructure.embeddings.runtime_factory import build_embedding_runtime
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.observability.face_pipeline_metrics import FacePipelineMetrics
from recognition.worker.handlers.clustering import ClusteringJobHandler, CurationJobHandler, SplitJobHandler
from recognition.worker.handlers.scan import ScanItemHandler
from recognition.worker.handlers.utils import ensure_job_context

logger = logging.getLogger(__name__)

# Clustering-family job types the worker claims/recovers (everything except
# ANALYZE). Sourced from the canonical CLUSTERING_JOB_TYPES frozenset; sorted to
# bind deterministically in the SQL `IN` filter (sr-007 single source of truth).
_CLUSTERING_JOB_TYPE_VALUES: tuple[str, ...] = tuple(sorted(t.value for t in CLUSTERING_JOB_TYPES))

_DEFAULT_WORKER_METRICS_PORT = 9108
_DEFAULT_WORKER_METRICS_ADDR = "127.0.0.1"

# Process exporter state: registry identity (not a bare bool) so a restart that
# accidentally constructs a second FacePipelineMetrics fails loud instead of
# silently serving a dead registry (COORD-FINAL-01).
_process_metrics_exporter_registry: object | None = None


def _resolve_worker_metrics_port() -> int:
    """Parse RECOGNITION_SCAN_WORKER_METRICS_PORT (default 9108); range 1..65535."""
    raw = os.getenv("RECOGNITION_SCAN_WORKER_METRICS_PORT", str(_DEFAULT_WORKER_METRICS_PORT))
    try:
        port = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid RECOGNITION_SCAN_WORKER_METRICS_PORT={raw!r}; must be an integer 1..65535"
        ) from exc
    if port < 1 or port > 65535:
        raise ValueError(
            f"Invalid RECOGNITION_SCAN_WORKER_METRICS_PORT={port}; must be in range 1..65535"
        )
    return port


def _validate_worker_metrics_addr(raw: str) -> str:
    """Reject empty / whitespace / control-character bind addresses (fail closed)."""
    if not isinstance(raw, str):
        raise ValueError(
            f"Invalid RECOGNITION_SCAN_WORKER_METRICS_ADDR={raw!r}; must be a non-empty string"
        )
    addr = raw.strip()
    if not addr:
        raise ValueError(
            f"Invalid RECOGNITION_SCAN_WORKER_METRICS_ADDR={raw!r}; must be non-empty "
            "(default 127.0.0.1; empty would bind all interfaces in prometheus_client)"
        )
    if any(ord(ch) < 32 for ch in addr):
        raise ValueError(
            f"Invalid RECOGNITION_SCAN_WORKER_METRICS_ADDR={raw!r}; "
            "must not contain control characters"
        )
    return addr


def _resolve_worker_metrics_addr() -> str:
    """Parse RECOGNITION_SCAN_WORKER_METRICS_ADDR (default 127.0.0.1)."""
    raw = os.getenv("RECOGNITION_SCAN_WORKER_METRICS_ADDR", _DEFAULT_WORKER_METRICS_ADDR)
    return _validate_worker_metrics_addr(raw)


def _resolve_worker_metrics_export_enabled() -> bool:
    """Explicit export switch; default on. Set 0/false/no/off to disable."""
    raw = os.getenv("RECOGNITION_SCAN_WORKER_METRICS_EXPORT_ENABLED", "1").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    raise ValueError(
        f"Invalid RECOGNITION_SCAN_WORKER_METRICS_EXPORT_ENABLED={raw!r}; "
        "use 1/true/yes/on or 0/false/no/off"
    )


def start_process_metrics_exporter(
    *,
    metrics: FacePipelineMetrics,
    config: ScanWorkerConfig,
) -> None:
    """Start the process-local Prometheus HTTP exporter (composition root).

    Called once from ``_main`` before the outer restart loop. Idempotent when
    the same registry is already bound; fails loud if a *different* registry is
    supplied after a prior start (prevents silent dead-registry scrapes).
    Explicit ``metrics_export_enabled=False`` skips without binding.
    """
    global _process_metrics_exporter_registry
    if not config.metrics_export_enabled:
        logger.info(
            "[worker] metrics export disabled (RECOGNITION_SCAN_WORKER_METRICS_EXPORT_ENABLED)"
        )
        return
    registry = metrics.registry
    if _process_metrics_exporter_registry is registry:
        return
    if _process_metrics_exporter_registry is not None:
        raise RuntimeError(
            "metrics exporter already started with a different registry; "
            "hoist one FacePipelineMetrics before the outer restart loop "
            "(COORD-FINAL-01)"
        )
    # Fail-loud: start_http_server exceptions propagate to process composition.
    start_http_server(
        int(config.metrics_port),
        str(config.metrics_addr),
        registry=registry,
    )
    _process_metrics_exporter_registry = registry
    logger.info(
        "[worker] Prometheus metrics exporter listening on %s:%s",
        config.metrics_addr,
        config.metrics_port,
    )


def reset_process_metrics_exporter_for_tests() -> None:
    """Test hook: clear process exporter bind state (never used in production)."""
    global _process_metrics_exporter_registry
    _process_metrics_exporter_registry = None


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
    # FINALB-06: process-local Prometheus exporter (validated 1..65535).
    metrics_port: int = field(default_factory=_resolve_worker_metrics_port)
    # COORD-FINAL-01: bind address (default loopback; operators may override).
    metrics_addr: str = field(default_factory=_resolve_worker_metrics_addr)
    # Explicit disable only — never silently omit export (OBS-08).
    metrics_export_enabled: bool = field(default_factory=_resolve_worker_metrics_export_enabled)

    def __post_init__(self) -> None:
        port = int(self.metrics_port)
        if port < 1 or port > 65535:
            raise ValueError(f"metrics_port={port} out of range; must be 1..65535")
        object.__setattr__(self, "metrics_port", port)
        object.__setattr__(self, "metrics_addr", _validate_worker_metrics_addr(str(self.metrics_addr)))


class ScanWorker:
    """Background worker that claims and processes scan queue items."""

    def __init__(
        self,
        config: ScanWorkerConfig,
        *,
        metrics: FacePipelineMetrics | None = None,
    ) -> None:
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
        # Process-local face_pipeline metrics (not the API registry). Injected
        # from composition root so outer restart reuses one registry.
        self._face_pipeline_metrics = metrics if metrics is not None else FacePipelineMetrics()
        self._metrics_exporter_started = False

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
        # Cumulative reconcile counters published on every heartbeat ([OBS-05]/[OBS-08]).
        self._scan_counters = ScanWorkerCounters()

        self._scan_handler = ScanItemHandler(
            session_factory=self._session_factory,
            detector=self._detector,
            generator=self._generator,
            max_attempts=self._config.max_attempts,
            max_concurrency=self._config.max_concurrency,
            object_store_factory=self._object_store_factory,
            counters=self._scan_counters,
        )
        self._job_handlers = {
            "split": SplitJobHandler(),
            "curation": CurationJobHandler(),
            "clustering": ClusteringJobHandler(session_factory=self._session_factory),
        }

    def start_metrics_exporter(self) -> None:
        """Start process-local Prometheus HTTP exporter (test / direct-use seam).

        Production composition uses :func:`start_process_metrics_exporter` once
        from ``_main``. This method delegates there with instance-level
        idempotence so unit tests can exercise export without entering the
        worker lifecycle (which must never bind a port).
        """
        if self._metrics_exporter_started:
            return
        start_process_metrics_exporter(
            metrics=self._face_pipeline_metrics,
            config=self._config,
        )
        self._metrics_exporter_started = True

    async def __aenter__(self) -> ScanWorker:
        """Prepare worker resources (does not start the metrics exporter)."""
        await self._ensure_embedding_runtime()
        await self._heartbeat_embedding_runtime_capability()
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
            await self._probe_and_publish_embedding_runtime_capability()
            async with self._session_factory() as session:
                await enable_rls_bypass(session)
                repo = SqlAlchemyScanQueueRepository(session)

                now = datetime.now(tz=UTC)
                await self._refresh_mv_if_needed(session, now)

                await repo.reclaim_stale_items(
                    stale_after_seconds=self._config.stale_after_seconds,
                    max_attempts=self._config.max_attempts,
                    now=now,
                )
                queue = ScanQueueService(repo)
                terminated = await queue.terminate_stalled_jobs(
                    stale_after_seconds=self._config.stale_after_seconds,
                    now=now,
                )
                if terminated:
                    logger.warning("[worker] Terminated %d stalled scan job(s)", terminated)

                if await self._process_pending_clustering_jobs(session=session, now=now):
                    await session.commit()
                    should_sleep = True
                elif not self._can_claim_scan_items():
                    # Runtime not ready: keep clustering (above) but do not claim
                    # scan items — claiming would burn attempts under Unavailable*.
                    await session.commit()
                    should_sleep = True
                else:
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

    def _can_claim_scan_items(self) -> bool:
        """Whether this worker may claim pending scan items this cycle.

        Test mode always claims (stubs). Production requires a ready embedding
        runtime so Unavailable* does not burn attempt budgets on tight loops.
        Clustering is independent and still runs when this returns False.

        An Unavailable detector always demotes the sticky ready flag so a
        mid-life outage cannot keep the claim gate open (R2-06).
        """
        if self._runtime_mode == "test":
            return True
        if isinstance(self._detector, UnavailableFaceDetector):
            self._embedding_runtime_ready = False
            return False
        return self._embedding_runtime_ready

    async def _probe_and_publish_embedding_runtime_capability(self) -> None:
        """Retry runtime initialization even while intake is rejecting new jobs."""
        await self._ensure_embedding_runtime()
        await self._heartbeat_embedding_runtime_capability()

    async def _ensure_embedding_runtime(self) -> None:
        """Initialize scan inference dependencies once per worker process.

        Ready is sticky-true only while the live detector is usable. An
        UnavailableFaceDetector demotes the flag so the next probe re-enters
        the factory after the retry window (mid-life outage recovery).
        """
        if self._runtime_mode == "test":
            return
        # Demote sticky-true when the live detector is Unavailable so claim
        # guard and capability heartbeat stay consistent (R2-06).
        if isinstance(self._detector, UnavailableFaceDetector):
            self._embedding_runtime_ready = False
        if self._embedding_runtime_ready:
            return
        now = datetime.now(tz=UTC)
        if self._embedding_retry_after is not None and now < self._embedding_retry_after:
            return
        settings = get_recognition_settings()
        # Pre-S3 semantics (S3CR-02): do not allocate httpx.AsyncClient until the
        # factory returns a usable detector; on Unavailable close/clear any client
        # so none exists while the runtime is not ready. Retry after 30s.
        self._detector, self._generator = await build_embedding_runtime(
            settings=settings,
            http_client=self._http_client,
            metrics=self._face_pipeline_metrics,
        )
        if isinstance(self._detector, UnavailableFaceDetector):
            self._embedding_runtime_ready = False
            self._embedding_retry_after = now + timedelta(seconds=30)
            if self._http_client is not None:
                await self._http_client.aclose()
                self._http_client = None
        else:
            if self._http_client is None:
                self._http_client = httpx.AsyncClient(timeout=30.0)
                # Attach shared client after success (factory ran with None).
                if hasattr(self._detector, "_client"):
                    self._detector._client = self._http_client
            self._embedding_retry_after = None
            self._embedding_runtime_ready = True

        # BR-11: preserve the ObjectStore factory wired in __init__ so the
        # production scan_handler keeps multipart-blob support after the
        # adapter loads (or after the fail-closed fallback fires).
        self._scan_handler = ScanItemHandler(
            session_factory=self._session_factory,
            detector=self._detector,
            generator=self._generator,
            max_attempts=self._config.max_attempts,
            max_concurrency=self._config.max_concurrency,
            object_store_factory=self._object_store_factory,
            counters=self._scan_counters,
        )
        await self._heartbeat_embedding_runtime_capability()

    async def _publish_embedding_runtime_capability(self, session: AsyncSession) -> None:
        """Write the worker-published embedding-runtime heartbeat for API intake.

        Contract expansion (S3CR-07 / S4): ``reason`` carries ``profile=<name>`` plus
        always-present cumulative counters (zeros until first media) so silence is
        distinguishable from health ([OBS-05], [OBS-08]). Pre-S3 used ``reason=None``
        on the ready path; consumers must accept the profile + counter suffix.
        """
        from recognition.shared.db.dialect import is_postgres

        if not is_postgres(session):
            return
        profile = get_recognition_settings().face_pipeline.profile
        if self._runtime_mode == "test" or self._embedding_runtime_ready:
            available = True
            reason = format_capability_reason(profile=profile, counters=self._scan_counters)
        elif isinstance(self._detector, UnavailableFaceDetector):
            available = False
            base = self._detector.reason or "embedding runtime unavailable"
            reason = format_capability_reason(
                profile=profile,
                available_detail=base,
                counters=self._scan_counters,
            )
        else:
            available = False
            reason = format_capability_reason(
                profile=profile,
                available_detail="embedding runtime not initialized",
                counters=self._scan_counters,
            )
        await publish_embedding_runtime_capability(session, available=available, reason=reason)

    async def _heartbeat_embedding_runtime_capability(self) -> None:
        async with self._session_factory() as session:
            await enable_rls_bypass(session)
            await self._publish_embedding_runtime_capability(session)
            await session.commit()

    async def _process_pending_clustering_jobs(self, *, session: AsyncSession, now: datetime) -> bool:
        job = await self._claim_next_clustering_job(session=session, now=now)
        if job is None:
            return False

        # Capture identity before the handler runs: the main session is rolled
        # back in the failure path, after which the ORM instance is unusable.
        job_id = job.id
        tenant_id = job.tenant_id
        job_type = job.job_type

        try:
            await self._dispatch_clustering_job(job=job, session=session)
            return True
        except Exception as exc:
            logger.exception(
                "[worker] Clustering job failed: job_id=%s tenant_id=%s job_type=%s",
                job_id,
                tenant_id,
                job_type,
            )
            await self._record_clustering_job_failure(exc=exc, session=session, job_id=job_id, tenant_id=tenant_id)
            return True

    async def _claim_next_clustering_job(self, *, session: AsyncSession, now: datetime) -> IdentityClusteringJob | None:
        """Claim the next pending clustering/curation/split job via SKIP LOCKED.

        Marks the claimed row RUNNING and commits so the SELECT FOR UPDATE row
        lock is released before the handler runs (finding 1163). Returns None
        when the queue holds no eligible job.
        """
        stmt = (
            select(IdentityClusteringJob)
            .where(IdentityClusteringJob.status == JobStatus.PENDING.value)
            .where(IdentityClusteringJob.job_type.in_(_CLUSTERING_JOB_TYPE_VALUES))
            .order_by(IdentityClusteringJob.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None:
            return None

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
        return job

    async def _dispatch_clustering_job(self, *, job: IdentityClusteringJob, session: AsyncSession) -> None:
        """Route a claimed job to its handler, failing it if the type is unknown."""
        handler = self._job_handlers.get(job.job_type)
        if handler is None:
            await ensure_job_context(session=session, job=job)
            job.status = JobStatus.FAILED
            job.error_message = f"unsupported job_type: {job.job_type}"
            job.completed_at = datetime.now(tz=UTC)
            await session.flush()
        else:
            await handler.handle(job, session)

    async def _record_clustering_job_failure(
        self, *, exc: Exception, session: AsyncSession, job_id: uuid.UUID, tenant_id: uuid.UUID | None
    ) -> None:
        """Durably persist retry/failed status for a job whose handler raised.

        Classifies the error as transient (re-queue within the bounded retry
        budget) or deterministic (permanent fail) and writes the outcome through
        a fresh session so it survives the main session's rollback
        (finding 1161 + finding 1168: bounded retry budget).
        """
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
                .where(IdentityClusteringJob.job_type.in_(_CLUSTERING_JOB_TYPE_VALUES))
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
            outcome = await cluster_repo.refresh_centroids_view_concurrent()
            if outcome is MvRefreshOutcome.SKIPPED_HEADROOM:
                logger.warning(
                    "[worker] Skipped centroids MV refresh due to insufficient disk headroom "
                    "(free/min bytes guard); retrying on the next cycle"
                )
            elif outcome is MvRefreshOutcome.FAILED:
                logger.warning("[worker] Centroids MV refresh failed; retrying on the next cycle")
            elif outcome is MvRefreshOutcome.REFRESHED:
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

    # COORD-FINAL-01: one config + one metrics registry for the whole process.
    # Exporter starts once here (fail-loud); replacement ScanWorkers share the
    # same metrics object so post-restart scrapes stay live.
    worker_config = ScanWorkerConfig(postgres_dsn=postgres_dsn)
    process_metrics = FacePipelineMetrics()
    start_process_metrics_exporter(metrics=process_metrics, config=worker_config)

    backoff = 2.0
    while True:
        try:
            async with ScanWorker(worker_config, metrics=process_metrics) as worker:
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
