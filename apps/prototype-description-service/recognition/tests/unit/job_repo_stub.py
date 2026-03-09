from __future__ import annotations

from datetime import datetime

from recognition.application.orchestration.job_service import JobRepository
from recognition.domain.job import Job
from recognition.domain.repositories import ProjectionStatus


class InMemoryJobRepo(JobRepository):
    """Minimal in-memory job repository for unit tests."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    async def save(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    async def update(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job

    async def get_followup_clustering_job(self, scan_job_id: str) -> Job | None:
        return None

    async def get_active_clustering_job_for_tenant(self, tenant_id: str) -> Job | None:
        return None

    async def get_latest_completed_clustering_job_for_tenant(self, tenant_id: str) -> Job | None:
        return None

    async def get_projection_status(self, job_id: str, tenant_id: str) -> ProjectionStatus | None:
        return None

    async def record_projection_acknowledgement(
        self, *, job_id: str, tenant_id: str, snapshot_version: int, acknowledged_at: datetime
    ) -> ProjectionStatus | None:
        return None
