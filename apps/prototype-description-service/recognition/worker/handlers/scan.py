"""Scan queue handlers for the worker."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import IdentityClusteringJob
from db.tenant_context import enable_rls_bypass
from recognition.application.embedding.detector import FaceDetectorProtocol
from recognition.application.embedding.generator import EmbeddingGeneratorProtocol
from recognition.application.scan.queue_repository import ScanQueueItem
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.scan.service import ObjectStoreFactory, ScanService
from recognition.application.storage import ObjectStoreError
from recognition.domain.job import JobStatus
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.interface_adapters.http.middleware.correlation import (
    _correlation_id_var,
    generate_correlation_id,
)

logger = logging.getLogger(__name__)


class ScanItemHandler:
    """Process scan queue items and refresh scan job progress."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        detector: FaceDetectorProtocol,
        generator: EmbeddingGeneratorProtocol,
        max_attempts: int,
        max_concurrency: int,
        object_store_factory: ObjectStoreFactory | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._detector = detector
        self._generator = generator
        self._max_attempts = max_attempts
        self._max_concurrency = max_concurrency
        # E15-11 BR-08: when configured, ScanService resolves file:// blob
        # URIs through this factory's per-tenant ObjectStore (the same seam
        # the multipart upload route writes through). Worker-side cleanup
        # in _refresh_job_progress also goes through this factory once a
        # job completes.
        self._object_store_factory = object_store_factory

    async def process_items(self, *, claimed: list[ScanQueueItem]) -> None:
        if not claimed:
            return

        affected_jobs = {item.job_id for item in claimed}
        semaphore = asyncio.Semaphore(min(max(1, self._max_concurrency), len(claimed)))

        async def _process_item(item: ScanQueueItem) -> None:
            request_id = uuid.uuid4()
            bound_correlation_id = item.correlation_id or generate_correlation_id()
            token = _correlation_id_var.set(bound_correlation_id)
            try:
                await _run_item(item, request_id)
            finally:
                _correlation_id_var.reset(token)

        async def _run_item(item: ScanQueueItem, request_id: uuid.UUID) -> None:
            async with semaphore, self._session_factory() as session:
                await enable_rls_bypass(session)
                repo = SqlAlchemyScanQueueRepository(session)
                scan_service = self._build_scan_service(session)
                now = datetime.now(tz=UTC)
                logger.info(
                    "[worker] START scan_item request_id=%s job_id=%s item_id=%s media_id=%s",
                    request_id,
                    item.job_id,
                    item.id,
                    item.media_id,
                )
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
                    await session.commit()
                    logger.info(
                        "[worker] COMPLETE scan_item request_id=%s job_id=%s item_id=%s identities=%s",
                        request_id,
                        item.job_id,
                        item.id,
                        identities_detected,
                    )
                except Exception as exc:  # pragma: no cover
                    error_message = str(exc)
                    await self._handle_item_failure(
                        repo=repo,
                        item=item,
                        now=now,
                        error_message=error_message,
                    )
                    await session.commit()
                    logger.exception(
                        "[worker] FAIL scan_item request_id=%s job_id=%s item_id=%s",
                        request_id,
                        item.job_id,
                        item.id,
                    )

        results = await asyncio.gather(*(_process_item(item) for item in claimed), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("[worker] scan_item task failed", exc_info=result)

        await self._refresh_job_progress(affected_jobs)

    async def _refresh_job_progress(self, job_ids: set[uuid.UUID]) -> None:
        """Recompute progress for affected scan jobs."""
        if not job_ids:
            return
        completed_jobs: list[tuple[uuid.UUID, uuid.UUID]] = []
        async with self._session_factory() as session:
            await enable_rls_bypass(session)
            repo = SqlAlchemyScanQueueRepository(session)
            queue = ScanQueueService(repo)
            for job_id in job_ids:
                completed = await queue.refresh_job_progress(job_id=job_id)
                if completed:
                    tenant_id = await repo.get_job_tenant_id(job_id=job_id)
                    if tenant_id:
                        logger.info(
                            "[worker] Scan job %s completed, auto-creating clustering job for tenant %s",
                            job_id,
                            tenant_id,
                        )
                        clustering_job = IdentityClusteringJob(
                            tenant_id=tenant_id,
                            job_type="clustering",
                            status=JobStatus.PENDING,
                            progress=0.0,
                            total_identities=0,
                            processed_identities=0,
                            message="Auto-triggered after scan completion",
                            payload={"scan_job_id": str(job_id)},
                        )
                        session.add(clustering_job)
                        completed_jobs.append((job_id, tenant_id))
            await session.commit()

        # E15-11 BR-07/BR-08: cleanup the per-job ObjectStore directory
        # only after the worker has actually consumed every queued item
        # for the job. Done outside the DB session so a slow filesystem
        # cannot stall RLS-bypass connections.
        if self._object_store_factory is not None:
            for job_id, tenant_id in completed_jobs:
                try:
                    store = self._object_store_factory(str(tenant_id))
                    store.cleanup(job_id=str(job_id))
                except ObjectStoreError:
                    logger.warning(
                        "[worker] object_store cleanup failed for job_id=%s tenant_id=%s",
                        job_id,
                        tenant_id,
                    )

    async def _handle_item_failure(
        self,
        *,
        repo: SqlAlchemyScanQueueRepository,
        item: ScanQueueItem,
        now: datetime,
        error_message: str,
    ) -> None:
        if item.attempts < self._max_attempts:
            await repo.release_item_for_retry(item_id=item.id, error_message=error_message)
            return
        await repo.mark_item_failed(item_id=item.id, completed_at=now, error_message=error_message)

    def _build_scan_service(self, session: AsyncSession) -> ScanService:
        """Create a ScanService bound to the provided session."""
        return ScanService(
            session=session,
            detector=self._detector,
            generator=self._generator,
            object_store_factory=self._object_store_factory,
        )
