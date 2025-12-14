"""Job orchestration service (skeleton for TDD-driven implementation)."""

from __future__ import annotations

from collections.abc import Iterable

from recognition.domain.job import Job, JobStatus, JobType
from recognition.domain.repositories import JobRepository
from recognition.infrastructure.repositories.cancelable_jobs import is_canceled
from recognition.shared.ids import generate_id


class JobService:
    """Coordinates background job lifecycle for analyze and clustering tasks."""

    def __init__(self, repository: JobRepository, cluster_service, scan_service) -> None:
        self.repository = repository
        self.cluster_service = cluster_service
        self.scan_service = scan_service

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

    async def get_job_status(self, job_id: str) -> Job | None:
        """Return persisted job status."""
        return await self.repository.get(job_id)

    async def cancel_job(self, job_id: str) -> Job:
        """Mark a job as canceled and transition to failed with message."""
        job = await self._get_or_raise(job_id)
        job.fail("canceled")
        return await self.repository.update(job)

    async def process_analyze_job(self, job_id: str, tenant_id: str, media_ids: Iterable[str]) -> Job:
        """Background-friendly wrapper to process analyze job by ID."""
        media_ids_list = list(media_ids)
        job = await self._get_or_raise(job_id)
        job.progress_total = len(media_ids_list)
        job = await self.start_job(job.id)
        try:
            if is_canceled(job.id):
                return await self.fail_job(job.id, "canceled")
            if self.scan_service:
                await self.scan_service.analyze_media(tenant_id, media_ids_list)
            job = await self.update_progress(job.id, completed=len(media_ids_list), total=len(media_ids_list))
            return await self.complete_job(job.id)
        except Exception as exc:
            return await self.fail_job(job.id, str(exc))

    async def process_clustering_job(self, job_id: str, tenant_id: str) -> Job:
        """Background-friendly wrapper to process clustering job by ID."""
        job = await self._get_or_raise(job_id)
        job.progress_total = max(job.progress_total, 1)
        job = await self.start_job(job.id)
        try:
            if is_canceled(job.id):
                return await self.fail_job(job.id, "canceled")
            result = await self.cluster_service.cluster_unclustered_identities(tenant_id, job_id=job_id)
            completed = getattr(result, "completed", 1) or 1
            total = getattr(result, "total", completed) or completed
            job = await self.update_progress(job.id, completed=completed, total=total)
            return await self.complete_job(job.id)
        except Exception as exc:
            return await self.fail_job(job.id, str(exc))

    async def _get_or_raise(self, job_id: str) -> Job:
        job = await self.repository.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        return job
