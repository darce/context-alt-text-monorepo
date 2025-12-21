"""SQLAlchemy-backed repository for Job domain objects."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusteringJob, IdentityScanJob
from recognition.domain.job import Job, JobStatus, JobType
from recognition.domain.repositories import JobRepository


class SqlAlchemyJobRepository(JobRepository):
    """Persist Job domain objects into clustering/scan job tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, job: Job) -> Job:
        """Create a new job record."""
        if job.type is JobType.ANALYZE:
            scan_model = IdentityScanJob(
                tenant_id=_coerce_uuid(job.tenant_id),
                status=job.status.value,
                media_ids=[],
                total_media=job.progress_total,
                processed_media=job.progress_completed,
                error_message=job.error_message,
                message=job.message,
                started_at=job.started_at if job.status is JobStatus.RUNNING else None,
                completed_at=job.finished_at,
            )
            self._session.add(scan_model)
            await self._session.flush()
            await self._session.refresh(scan_model)
            job.id = str(scan_model.id)
            return job
        if job.type in (JobType.CLUSTERING, JobType.CURATION, JobType.SPLIT):
            progress = _compute_progress(job.progress_completed, job.progress_total)
            cluster_model = IdentityClusteringJob(
                tenant_id=_coerce_uuid(job.tenant_id),
                job_type=job.type.value,
                status=job.status.value,
                progress=progress,
                total_identities=job.progress_total,
                processed_identities=job.progress_completed,
                message=job.message,
                payload=job.payload or {},
                started_at=job.started_at if job.status is JobStatus.RUNNING else None,
                completed_at=job.finished_at,
            )
            self._session.add(cluster_model)
            await self._session.flush()
            await self._session.refresh(cluster_model)
            job.id = str(cluster_model.id)
            return job
        raise ValueError(f"Unsupported job type: {job.type}")

    async def get(self, job_id: str) -> Job | None:
        """Fetch a job by ID."""
        job_uuid = _coerce_uuid(job_id)
        if job_uuid is None:
            return None

        scan = await self._session.get(IdentityScanJob, job_uuid)
        if scan:
            return Job(
                id=str(scan.id),
                type=JobType.ANALYZE,
                tenant_id="",  # tenant not stored on model; populated via context
                status=JobStatus(scan.status),
                progress_completed=scan.processed_media or 0,
                progress_total=scan.total_media or 0,
                error_message=scan.error_message,
                message=scan.message,
                started_at=scan.started_at or datetime.now(tz=UTC),
                finished_at=scan.completed_at,
            )

        clustering = await self._session.get(IdentityClusteringJob, job_uuid)
        if clustering:
            job_type = JobType(clustering.job_type) if clustering.job_type else JobType.CLUSTERING
            return Job(
                id=str(clustering.id),
                type=job_type,
                tenant_id="",  # tenant not stored on model; populated via context
                status=JobStatus(clustering.status),
                progress_completed=clustering.processed_identities or 0,
                progress_total=clustering.total_identities or 0,
                error_message=clustering.error_message,
                message=clustering.message,
                payload=clustering.payload or {},
                started_at=clustering.started_at or datetime.now(tz=UTC),
                finished_at=clustering.completed_at,
            )

        return None

    async def update(self, job: Job) -> Job:
        """Update an existing job."""
        job_uuid = _coerce_uuid(job.id)
        if job.type is JobType.ANALYZE:
            scan_stmt = select(IdentityScanJob).where(IdentityScanJob.id == job_uuid)
            scan_result = await self._session.execute(scan_stmt)
            scan_model = scan_result.scalar_one_or_none()
            if not scan_model:
                return await self.save(job)
            scan_model.status = job.status.value
            scan_model.processed_media = job.progress_completed
            scan_model.total_media = job.progress_total
            scan_model.started_at = job.started_at if job.status is not JobStatus.PENDING else None
            scan_model.completed_at = job.finished_at
            scan_model.error_message = job.error_message
            scan_model.message = job.message
        elif job.type in (JobType.CLUSTERING, JobType.CURATION, JobType.SPLIT):
            cluster_stmt = select(IdentityClusteringJob).where(IdentityClusteringJob.id == job_uuid)
            cluster_result = await self._session.execute(cluster_stmt)
            cluster_model: IdentityClusteringJob | None = cluster_result.scalar_one_or_none()
            if not cluster_model:
                return await self.save(job)
            cluster_model.job_type = job.type.value
            cluster_model.status = job.status.value
            cluster_model.processed_identities = job.progress_completed
            cluster_model.total_identities = job.progress_total
            cluster_model.progress = _compute_progress(job.progress_completed, job.progress_total)
            cluster_model.started_at = job.started_at if job.status is not JobStatus.PENDING else None
            cluster_model.completed_at = job.finished_at
            cluster_model.message = job.message
            cluster_model.payload = job.payload or {}
            cluster_model.error_message = job.error_message

        await self._session.flush()
        return job


def _coerce_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _compute_progress(completed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return min(1.0, completed / total)
