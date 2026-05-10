"""Job orchestration service (skeleton for TDD-driven implementation)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.orchestration.protocols import CurationRefreshMetricsProtocol
from recognition.domain.job import Job, JobStatus, JobType, ProjectionStatus, SplitJobPayload
from recognition.domain.repositories import JobRepository
from recognition.shared.ids import generate_id


class JobService:
    """Coordinates background job lifecycle for analyze and clustering tasks."""

    def __init__(
        self,
        repository: JobRepository,
        cluster_service,
        scan_service,
        curation_refresh_metrics: CurationRefreshMetricsProtocol | None = None,
    ) -> None:
        self.repository = repository
        self.cluster_service = cluster_service
        self.scan_service = scan_service
        self.curation_refresh_metrics = curation_refresh_metrics

    async def create_job(self, job_type: JobType, tenant_id: str, total: int = 0) -> Job:
        """Create a pending job."""
        job = Job(
            id=str(generate_id()),
            type=job_type,
            tenant_id=tenant_id,
            progress_total=total,
            progress_completed=0,
            status=JobStatus.PENDING,
        )
        return await self.repository.save(job)

    async def start_job(self, job_id: str) -> Job:
        """Transition job to running."""
        job = await self._get_or_raise(job_id)
        job.status = JobStatus.RUNNING
        job.finished_at = None
        return await self.repository.update(job)

    async def complete_job(self, job_id: str) -> Job:
        """Mark job as completed."""
        job = await self._get_or_raise(job_id)
        job.complete()
        return await self.repository.update(job)

    async def fail_job(self, job_id: str, error_message: str) -> Job:
        """Mark job as failed with an error message."""
        job = await self._get_or_raise(job_id)
        job.fail(error_message)
        return await self.repository.update(job)

    async def update_progress(self, job_id: str, completed: int, total: int) -> Job:
        """Update progress counters for a job."""
        job = await self._get_or_raise(job_id)
        job.update_progress(completed, total)
        return await self.repository.update(job)

    async def update_job_message(self, job_id: str, message: str | None) -> Job:
        """Update a job's status message."""
        job = await self._get_or_raise(job_id)
        job.message = message
        return await self.repository.update(job)

    async def queue_analyze(self, tenant_id: str, media_ids: Iterable[str]) -> Job:
        """Queue analyze job and kick off scan/embedding pipeline."""
        media_ids_list = list(media_ids)
        job = await self.create_job(JobType.ANALYZE, tenant_id=tenant_id, total=len(media_ids_list))
        await self.start_job(job.id)
        if self.scan_service:
            await self.scan_service.analyze_media(tenant_id, media_ids_list)
        await self.update_progress(job.id, completed=len(media_ids_list), total=len(media_ids_list))
        return await self.complete_job(job.id)

    async def queue_clustering(self, tenant_id: str) -> Job:
        """Queue clustering job."""
        job = await self.create_job(JobType.CLUSTERING, tenant_id=tenant_id)
        await self.start_job(job.id)
        await self.cluster_service.cluster_unclustered_identities(tenant_id, job_id=job.id)
        await self.update_progress(job.id, completed=1, total=1)
        return await self.complete_job(job.id)

    async def queue_curation_followup(
        self,
        tenant_id: str,
        *,
        cluster_ids: Iterable[str],
        identity_ids: Iterable[str] | None = None,
        source_cluster_id: str | None = None,
        refresh_idempotency_key: str | None = None,
    ) -> Job:
        """Queue curation follow-up work after split or wrong-person removal.

        Args:
            tenant_id: Tenant that owns the affected clusters.
            cluster_ids: Cluster IDs to recompute representatives/centroid for.
            identity_ids: Optional identities affected by the curation action.
            source_cluster_id: Optional source cluster ID (merge cleanup).

        Returns:
            Job describing the queued curation work.

        """
        cluster_ids_list = list(dict.fromkeys(cluster_ids))
        identity_ids_list = list(identity_ids or [])
        if source_cluster_id and str(source_cluster_id).lower() in {cid.lower() for cid in cluster_ids_list}:
            # Never allow merge cleanup to delete a cluster that is also a recompute target.
            source_cluster_id = None
        job = Job(
            id=str(generate_id()),
            type=JobType.CURATION,
            tenant_id=tenant_id,
            progress_total=len(cluster_ids_list),
            progress_completed=0,
            status=JobStatus.PENDING,
            message="curation_followup",
            payload={
                "cluster_ids": cluster_ids_list,
                "identity_ids": identity_ids_list,
                "source_cluster_id": source_cluster_id,
                "refresh_idempotency_key": refresh_idempotency_key,
            },
        )
        return await self.repository.save(job)

    async def queue_split(self, tenant_id: str, payload: SplitJobPayload) -> Job:
        """Queue a split job for async execution."""
        job = Job(
            id=str(generate_id()),
            type=JobType.SPLIT,
            tenant_id=tenant_id,
            progress_total=1,
            progress_completed=0,
            status=JobStatus.PENDING,
            message="split",
            payload=payload.model_dump(),
        )
        return await self.repository.save(job)

    async def get_job_status(self, job_id: str) -> Job | None:
        """Return persisted job status."""
        return await self.repository.get(job_id)

    async def get_followup_clustering_job(self, scan_job_id: str) -> Job | None:
        """Return the chained clustering job for a scan job when present."""
        return await self.repository.get_followup_clustering_job(scan_job_id)

    async def get_active_clustering_job_for_tenant(self, tenant_id: str) -> Job | None:
        """Return the active clustering job for a tenant when one is already queued/running."""
        return await self.repository.get_active_clustering_job_for_tenant(tenant_id)

    async def get_projection_status(self, job_id: str, tenant_id: str) -> ProjectionStatus | None:
        """Return projection metadata for a job."""
        return await self.repository.get_projection_status(job_id, tenant_id)

    async def record_projection_acknowledgement(
        self,
        *,
        job_id: str,
        tenant_id: str,
        snapshot_version: int,
        acknowledged_at: datetime,
    ) -> ProjectionStatus | None:
        """Persist projection acknowledgement metadata for a job."""
        return await self.repository.record_projection_acknowledgement(
            job_id=job_id,
            tenant_id=tenant_id,
            snapshot_version=snapshot_version,
            acknowledged_at=acknowledged_at,
        )

    async def get_latest_completed_clustering_job_for_tenant(self, tenant_id: str) -> Job | None:
        """Return the newest completed clustering job for a tenant."""
        return await self.repository.get_latest_completed_clustering_job_for_tenant(tenant_id)

    async def cancel_job(self, job_id: str) -> Job:
        """Mark a job as canceled and transition to failed with message."""
        job = await self._get_or_raise(job_id)
        job.fail("canceled")
        return await self.repository.update(job)

    async def process_curation_job(
        self,
        job_id: str,
        tenant_id: str,
        *,
        cluster_ids: Iterable[str],
        identity_ids: Iterable[str] | None = None,
        source_cluster_id: str | None = None,
        refresh_idempotency_key: str | None = None,
        session: AsyncSession | None = None,
    ) -> Job:
        """Background-friendly wrapper to process a curation follow-up job by ID."""
        from recognition.application.orchestration.curation_job import run_curation_job

        job = await self._get_or_raise(job_id)
        if not self.cluster_service:
            return await self.fail_job(job.id, "cluster service not available")
        cluster_ids_list = list(cluster_ids)
        payload = job.payload or {}
        if not cluster_ids_list:
            cluster_ids_list = _coerce_str_list(payload.get("cluster_ids"))
        if not cluster_ids_list:
            return await self.fail_job(job.id, "missing cluster ids")

        if source_cluster_id is None:
            payload_source = payload.get("source_cluster_id")
            if payload_source:
                source_cluster_id = str(payload_source)
        if refresh_idempotency_key is None:
            payload_refresh_key = payload.get("refresh_idempotency_key")
            if payload_refresh_key:
                refresh_idempotency_key = str(payload_refresh_key)
        identity_ids_list = list(identity_ids or [])
        if not identity_ids_list:
            identity_ids_list = _coerce_str_list(payload.get("identity_ids"))

        job.progress_total = max(job.progress_total, len(cluster_ids_list))
        job = await self.start_job(job.id)
        replay_session = session
        if replay_session is None:
            repository_session = getattr(self.repository, "session", None)
            replay_session = repository_session if isinstance(repository_session, AsyncSession) else None
        try:
            result = await run_curation_job(
                tenant_id=tenant_id,
                cluster_ids=cluster_ids_list,
                identity_ids=identity_ids_list,
                assignment_writer=self.cluster_service.assignment_writer,
                cluster_repo=self.cluster_service.assignment_writer.cluster_repository,
                cluster_service=self.cluster_service,
                source_cluster_id=source_cluster_id,
                refresh_idempotency_key=refresh_idempotency_key,
                session=replay_session,
                refresh_metrics=self.curation_refresh_metrics,
            )
            completed = int(result.get("clusters_recomputed", 0))
            job = await self.update_progress(job.id, completed=completed, total=job.progress_total)
            return await self.complete_job(job.id)
        except Exception as exc:
            return await self.fail_job(job.id, str(exc))

    async def _get_or_raise(self, job_id: str) -> Job:
        job = await self.repository.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        return job


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
