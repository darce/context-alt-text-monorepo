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
from recognition.application.embedding.service import EmbeddingService
from recognition.application.orchestration.curation_job import run_curation_job
from recognition.application.orchestration.job_service import JobService
from recognition.application.scan.queue_repository import ScanQueueItem
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.scan.service import ScanService
from recognition.config import get_settings as get_recognition_settings
from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.interface_adapters.http.dependencies import build_cluster_service

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
                if await self._process_pending_clustering_jobs(session=session, now=now):
                    await session.commit()
                    await asyncio.sleep(self._config.poll_interval_seconds)
                    continue

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

    async def _process_pending_clustering_jobs(self, *, session: AsyncSession, now: datetime) -> bool:
        stmt = (
            select(IdentityClusteringJob)
            .where(IdentityClusteringJob.status == "pending")
            .where(IdentityClusteringJob.job_type.in_(["curation", "split"]))
            .order_by(IdentityClusteringJob.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None:
            return False

        job.status = "running"
        job.started_at = now
        await session.flush()

        try:
            if job.job_type == "split":
                await self._handle_split_job(job=job, session=session)
            elif job.job_type == "curation":
                await self._handle_curation_job(job=job, session=session)
            else:
                job.status = "failed"
                job.error_message = f"unsupported job_type: {job.job_type}"
                job.completed_at = datetime.now(tz=UTC)
                await session.flush()
            return True
        except Exception as exc:  # pragma: no cover
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(tz=UTC)
            await session.flush()
            return True

    async def _handle_curation_job(self, *, job: IdentityClusteringJob, session: AsyncSession) -> None:
        cluster_ids = _coerce_str_list(job.payload.get("cluster_ids") if job.payload else None)
        if not cluster_ids:
            job.status = "failed"
            job.error_message = "missing cluster ids"
            job.completed_at = datetime.now(tz=UTC)
            await session.flush()
            return

        cluster_service = await build_cluster_service(session=session, tenant_id=str(job.tenant_id))
        result_counts = await run_curation_job(
            tenant_id=str(job.tenant_id),
            cluster_ids=cluster_ids,
            assignment_writer=cluster_service.assignment_writer,
            cluster_repo=cluster_service.assignment_writer._clusters,
            cluster_service=cluster_service,
        )
        completed = int(result_counts.get("clusters_recomputed", 0))
        total = max(int(job.total_identities or 0), len(cluster_ids))
        job.processed_identities = completed
        job.total_identities = total
        job.progress = _compute_progress(completed, total)
        job.status = "completed"
        job.completed_at = datetime.now(tz=UTC)
        await session.flush()

    async def _handle_split_job(self, *, job: IdentityClusteringJob, session: AsyncSession) -> None:
        """Execute a split job.

        Args:
            job: Job with split payload.
            session: Active database session.

        Raises:
            ValueError: If payload is invalid.
        """
        payload = job.payload or {}
        cluster_id_value = payload.get("cluster_id")
        if not cluster_id_value:
            raise ValueError("Split job missing cluster_id")

        cluster_id = str(cluster_id_value)
        n_clusters = _coerce_int(payload.get("n_clusters"), default=0)
        anchor_identity_id = _coerce_optional_str(payload.get("anchor_identity_id"))
        split_mode = _coerce_optional_str(payload.get("split_mode"))

        logger.info(
            "[worker] START split_job job_id=%s cluster_id=%s n_clusters=%d tenant_id=%s",
            job.id,
            cluster_id,
            n_clusters,
            job.tenant_id,
        )

        cluster_service = await build_cluster_service(session=session, tenant_id=str(job.tenant_id))
        new_ids, counts = await cluster_service.split_cluster(
            cluster_id=cluster_id,
            n_clusters=n_clusters,
            anchor_identity_id=anchor_identity_id,
            split_mode=split_mode,
            recompute=False,
        )

        if new_ids:
            job_service = JobService(
                repository=SqlAlchemyJobRepository(session),
                cluster_service=cluster_service,
                scan_service=None,
            )
            await job_service.queue_curation_followup(
                tenant_id=str(job.tenant_id),
                cluster_ids=[cluster_id, *new_ids],
            )

        total = max(1, len(new_ids))
        job.processed_identities = total
        job.total_identities = total
        job.progress = _compute_progress(total, total)
        job.status = "completed"
        job.message = f"Split complete: created {len(new_ids)} clusters"
        job.completed_at = datetime.now(tz=UTC)
        await session.flush()

        logger.info(
            "[worker] COMPLETE split_job job_id=%s new_clusters=%s moved_counts=%s",
            job.id,
            new_ids,
            counts,
        )


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


def _compute_progress(completed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return min(1.0, completed / total)


def _coerce_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    results: list[str] = []
    for item in value:
        if isinstance(item, str):
            results.append(item)
        elif isinstance(item, uuid.UUID):
            results.append(str(item))
    return results


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _coerce_int(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return int(value)
        except ValueError:
            return default
    return default


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
