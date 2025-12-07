"""Job management for async clustering operations.

Provides job enqueueing and processing for clustering operations that exceed
the sync batch limit.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityClusteringJob, MediaIdentity
from recognition.application.clustering.cluster_repository import ClusterRepository

if TYPE_CHECKING:
    from recognition.application.clustering.batch_clustering import BatchClusteringProcessor
    from recognition.application.clustering.clustering_settings import ClusteringSettings

logger = logging.getLogger(__name__)


class ClusterNotFoundError(Exception):
    """Raised when a clustering job cannot be found."""


class ClusteringJobService:
    """Manages async clustering job lifecycle."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        repository: ClusterRepository,
        settings: ClusteringSettings,
        ensure_tenant_context: Callable[[], Awaitable[None]],
        refresh_view: Callable[[], Awaitable[None]],
        merge_similar_clusters: Callable[..., Awaitable[int]],
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.repository = repository
        self.settings = settings
        self._ensure_tenant_context = ensure_tenant_context
        self._refresh_view = refresh_view
        self._merge_similar_clusters = merge_similar_clusters
        # Will be set by orchestrator
        self._batch_processor: BatchClusteringProcessor | None = None

    def set_batch_processor(self, processor: BatchClusteringProcessor) -> None:
        """Set the batch processor (injected by orchestrator)."""
        self._batch_processor = processor

    async def enqueue_clustering_job(
        self,
        identities: list[MediaIdentity],
        created_by_user_id: int | None = None,
    ) -> IdentityClusteringJob:
        """Enqueue a clustering job for async processing."""
        await self._ensure_tenant_context()
        job = await self.repository.create_clustering_job(
            total_identities=len(identities),
            created_by_user_id=created_by_user_id,
        )
        await self.session.commit()
        logger.info(
            "Enqueued clustering job %s for tenant %s (count=%d)",
            job.id,
            self.tenant_id,
            len(identities),
        )
        return job

    async def get_clustering_job(self, job_id: UUID) -> IdentityClusteringJob | None:
        """Get a clustering job by ID."""
        await self._ensure_tenant_context()
        return await self.repository.get_clustering_job(job_id)

    async def process_clustering_job(self, job_id: UUID) -> list[IdentityCluster]:
        """
        Process a queued clustering job (synchronous execution for now).
        In a Celery deployment this would be executed by a worker.
        """
        if self._batch_processor is None:
            raise RuntimeError("Batch processor not set. Call set_batch_processor first.")

        await self._ensure_tenant_context()
        job = await self.repository.update_clustering_job(
            job_id,
            status="running",
            progress=0.0,
            started_at=datetime.utcnow(),
        )
        if not job:
            raise ClusterNotFoundError(f"Clustering job {job_id} not found")
        logger.info("Processing clustering job %s for tenant %s", job_id, self.tenant_id)

        identities = await self.repository.get_unclustered_identities()
        await self.repository.update_clustering_job(
            job_id,
            total_identities=len(identities),
        )

        try:
            # Use the batch processor with job_id for log correlation
            clusters = await self._batch_processor.process_clustering_batch(identities, job_id=job_id)

            await self.repository.update_clustering_job(
                job_id,
                status="completed",
                progress=1.0,
                processed_identities=len(identities),
                completed_at=datetime.utcnow(),
            )
            await self.session.commit()

            # Final refresh and auto-merge check
            await self._refresh_view()
            if self.settings.auto_merge_enabled:
                total_identities = len(identities)
                if total_identities <= self.settings.auto_merge_max_identities:
                    merges = await self._merge_similar_clusters(
                        threshold=self.settings.auto_merge_threshold,
                        max_iterations=self.settings.auto_merge_max_iterations,
                    )
                    logger.info(
                        "Auto-merge completed for clustering job %s: %d merges",
                        job_id,
                        merges,
                    )
                else:
                    logger.info(
                        "Skipping auto-merge for job %s: %d identities exceeds cap %d",
                        job_id,
                        total_identities,
                        self.settings.auto_merge_max_identities,
                    )
            logger.info(
                "Clustering job %s completed for tenant %s (clusters=%d)",
                job_id,
                self.tenant_id,
                len(clusters),
            )
            return clusters
        except Exception as exc:
            await self.repository.update_clustering_job(
                job_id,
                status="failed",
                error_message=str(exc),
                completed_at=datetime.utcnow(),
            )
            await self.session.commit()
            logger.exception("Clustering job %s failed for tenant %s", job_id, self.tenant_id)
            raise
