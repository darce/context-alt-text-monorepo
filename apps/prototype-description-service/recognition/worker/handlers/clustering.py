"""Clustering-related job handlers for the worker."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusteringJob
from recognition.application.orchestration.curation_job import run_curation_job
from recognition.application.orchestration.job_service import JobService
from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository
from recognition.interface_adapters.http.dependencies import build_cluster_service
from recognition.worker.handlers.base import JobHandler
from recognition.worker.handlers.utils import (
    coerce_int,
    coerce_optional_str,
    coerce_str_list,
    compute_progress,
    ensure_job_context,
)

if TYPE_CHECKING:
    from recognition.application.orchestration.cluster_service import ClusterService

logger = logging.getLogger(__name__)


class CurationJobHandler(JobHandler[IdentityClusteringJob]):
    """Handle curation jobs."""

    async def handle(self, job: IdentityClusteringJob, session: AsyncSession) -> None:
        cluster_ids = coerce_str_list(job.payload.get("cluster_ids") if job.payload else None)
        if not cluster_ids:
            await ensure_job_context(session=session, job=job)
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
            cluster_repo=cluster_service.assignment_writer.cluster_repository,
            cluster_service=cluster_service,
            source_cluster_id=coerce_optional_str(job.payload.get("source_cluster_id")),
        )
        await ensure_job_context(session=session, job=job)
        completed = int(result_counts.get("clusters_recomputed", 0))
        total = max(int(job.total_identities or 0), len(cluster_ids))
        job.processed_identities = completed
        job.total_identities = total
        job.progress = compute_progress(completed, total)
        job.status = "completed"
        job.completed_at = datetime.now(tz=UTC)
        await session.flush()


class ClusteringJobHandler(JobHandler[IdentityClusteringJob]):
    """Handle clustering jobs."""

    def __init__(self, cluster_service: ClusterService | None = None) -> None:
        self._cluster_service = cluster_service

    async def handle(self, job: IdentityClusteringJob, session: AsyncSession) -> None:
        cluster_service = self._cluster_service
        if cluster_service is None:
            cluster_service = await build_cluster_service(session=session, tenant_id=str(job.tenant_id))

        async def progress_callback(completed: int, total: int):
            job.processed_identities = completed
            job.total_identities = total
            job.progress = compute_progress(completed, total)
            await session.flush()

        result = await cluster_service.cluster_unclustered_identities(
            tenant_id=str(job.tenant_id),
            job_id=str(job.id),
            progress_callback=progress_callback,
            commit=False,
        )

        await ensure_job_context(session=session, job=job)
        job.processed_identities = result.completed
        job.total_identities = result.total
        job.progress = 1.0
        job.status = "completed"
        job.completed_at = datetime.now(tz=UTC)
        await session.flush()


class SplitJobHandler(JobHandler[IdentityClusteringJob]):
    """Handle split jobs."""

    async def handle(self, job: IdentityClusteringJob, session: AsyncSession) -> None:
        payload = job.payload or {}
        cluster_id_value = payload.get("cluster_id")
        if not cluster_id_value:
            raise ValueError("Split job missing cluster_id")

        cluster_id = str(cluster_id_value)
        n_clusters = coerce_int(payload.get("n_clusters"), default=0)
        anchor_identity_id = coerce_optional_str(payload.get("anchor_identity_id"))
        split_mode = coerce_optional_str(payload.get("split_mode"))

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

        await ensure_job_context(session=session, job=job)
        total = max(1, len(new_ids))
        job.processed_identities = total
        job.total_identities = total
        job.progress = compute_progress(total, total)
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
