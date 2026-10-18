"""SQLAlchemy-backed repository for Job domain objects."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusteringJob, IdentityScanJob
from recognition.domain.job import CLUSTERING_JOB_TYPES, Job, JobStatus, JobType, ProjectionStatus
from recognition.domain.repositories import JobRepository
from recognition.infrastructure.repositories._helpers import coerce_uuid as _coerce_uuid


class SqlAlchemyJobRepository(JobRepository):
    """Persist Job domain objects into clustering/scan job tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def save(self, job: Job) -> Job:
        """Create a new job record."""
        if job.type is JobType.ANALYZE:
            scan_model = IdentityScanJob(
                tenant_id=_coerce_uuid(job.tenant_id, on_failure="none"),
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
        if job.type in CLUSTERING_JOB_TYPES:
            progress = _compute_progress(job.progress_completed, job.progress_total)
            payload = job.payload or {}
            cluster_model = IdentityClusteringJob(
                tenant_id=_coerce_uuid(job.tenant_id, on_failure="none"),
                job_type=job.type.value,
                status=job.status.value,
                progress=progress,
                total_identities=job.progress_total,
                processed_identities=job.progress_completed,
                message=job.message,
                snapshot_version=_coerce_positive_int(payload.get("snapshot_version")),
                source_job_id=_coerce_payload_uuid(payload.get("source_job_id")),
                projection_acknowledged_at=_coerce_datetime(payload.get("projection_acknowledged_at")),
                payload=payload,
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
        job_uuid = _coerce_uuid(job_id, on_failure="none")
        if job_uuid is None:
            return None

        scan = await self._session.get(IdentityScanJob, job_uuid)
        if scan:
            return Job(
                id=str(scan.id),
                type=JobType.ANALYZE,
                tenant_id=str(scan.tenant_id),
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
                tenant_id=str(clustering.tenant_id),
                status=JobStatus(clustering.status),
                progress_completed=clustering.processed_identities or 0,
                progress_total=clustering.total_identities or 0,
                error_message=clustering.error_message,
                message=clustering.message,
                payload=_hydrate_projection_payload(clustering),
                started_at=clustering.started_at or datetime.now(tz=UTC),
                finished_at=clustering.completed_at,
            )

        return None

    async def get_followup_clustering_job(self, scan_job_id: str) -> Job | None:
        """Return the newest clustering job linked to a scan job, if one exists."""
        stmt = (
            select(IdentityClusteringJob)
            .where(IdentityClusteringJob.job_type == JobType.CLUSTERING.value)
            .where(IdentityClusteringJob.payload["scan_job_id"].as_string() == scan_job_id)
            .order_by(IdentityClusteringJob.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        clustering = _first_clustering_row(result)
        if clustering is None:
            return None
        return Job(
            id=str(clustering.id),
            type=JobType.CLUSTERING,
            tenant_id=str(clustering.tenant_id),
            status=JobStatus(clustering.status),
            progress_completed=clustering.processed_identities or 0,
            progress_total=clustering.total_identities or 0,
            error_message=clustering.error_message,
            message=clustering.message,
            payload=_hydrate_projection_payload(clustering),
            started_at=clustering.started_at or datetime.now(tz=UTC),
            finished_at=clustering.completed_at,
        )

    async def get_active_clustering_job_for_tenant(self, tenant_id: str) -> Job | None:
        """Return the newest pending/running clustering job for a tenant."""
        tenant_uuid = _coerce_uuid(tenant_id, on_failure="none")
        if tenant_uuid is None:
            return None
        stmt = (
            select(IdentityClusteringJob)
            .where(
                IdentityClusteringJob.tenant_id == tenant_uuid,
                IdentityClusteringJob.job_type == JobType.CLUSTERING.value,
                IdentityClusteringJob.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
            )
            .order_by(IdentityClusteringJob.started_at.desc(), IdentityClusteringJob.created_at.desc())
        )
        result = await self._session.execute(stmt)
        clustering = _first_clustering_row(result)
        if clustering is None:
            return None
        return Job(
            id=str(clustering.id),
            type=JobType.CLUSTERING,
            tenant_id=str(clustering.tenant_id),
            status=JobStatus(clustering.status),
            progress_completed=clustering.processed_identities or 0,
            progress_total=clustering.total_identities or 0,
            error_message=clustering.error_message,
            message=clustering.message,
            payload=_hydrate_projection_payload(clustering),
            started_at=clustering.started_at or datetime.now(tz=UTC),
            finished_at=clustering.completed_at,
        )

    async def get_latest_completed_clustering_job_for_tenant(self, tenant_id: str) -> Job | None:
        """Return the newest completed clustering job for a tenant."""
        tenant_uuid = _coerce_uuid(tenant_id, on_failure="none")
        if tenant_uuid is None:
            return None
        stmt = (
            select(IdentityClusteringJob)
            .where(
                IdentityClusteringJob.tenant_id == tenant_uuid,
                IdentityClusteringJob.job_type == JobType.CLUSTERING.value,
                IdentityClusteringJob.status == JobStatus.COMPLETED.value,
            )
            .order_by(IdentityClusteringJob.completed_at.desc(), IdentityClusteringJob.created_at.desc())
        )
        result = await self._session.execute(stmt)
        clustering = _first_clustering_row(result)
        if clustering is None:
            return None
        return Job(
            id=str(clustering.id),
            type=JobType.CLUSTERING,
            tenant_id=str(clustering.tenant_id),
            status=JobStatus(clustering.status),
            progress_completed=clustering.processed_identities or 0,
            progress_total=clustering.total_identities or 0,
            error_message=clustering.error_message,
            message=clustering.message,
            payload=_hydrate_projection_payload(clustering),
            started_at=clustering.started_at or datetime.now(tz=UTC),
            finished_at=clustering.completed_at,
        )

    async def update(self, job: Job) -> Job:
        """Update an existing job."""
        job_uuid = _coerce_uuid(job.id, on_failure="none")
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
        elif job.type in CLUSTERING_JOB_TYPES:
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
            payload = job.payload or {}
            cluster_model.snapshot_version = _coerce_positive_int(payload.get("snapshot_version"))
            cluster_model.source_job_id = _coerce_payload_uuid(payload.get("source_job_id"))
            cluster_model.projection_acknowledged_at = _coerce_datetime(payload.get("projection_acknowledged_at"))
            cluster_model.payload = payload
            cluster_model.error_message = job.error_message

        await self._session.flush()
        return job

    async def get_projection_status(self, job_id: str, tenant_id: str) -> ProjectionStatus | None:
        """Return projection metadata for a clustering job payload when present."""
        job_uuid = _coerce_uuid(job_id, on_failure="none")
        tenant_uuid = _coerce_uuid(tenant_id, on_failure="none")
        if job_uuid is None or tenant_uuid is None:
            return None

        clustering = await self._session.get(IdentityClusteringJob, job_uuid)
        if clustering is None or clustering.tenant_id != tenant_uuid:
            return None

        snapshot_version = clustering.snapshot_version
        if snapshot_version is None:
            return None

        acknowledged_at = clustering.projection_acknowledged_at
        return ProjectionStatus(
            snapshot_version=snapshot_version,
            source_job_id=str(clustering.source_job_id or clustering.id),
            acknowledged_at=acknowledged_at,
        )

    async def record_projection_acknowledgement(
        self,
        *,
        job_id: str,
        tenant_id: str,
        snapshot_version: int,
        acknowledged_at: datetime,
    ) -> ProjectionStatus | None:
        """Persist projection acknowledgement metadata on the clustering job payload."""
        job_uuid = _coerce_uuid(job_id, on_failure="none")
        tenant_uuid = _coerce_uuid(tenant_id, on_failure="none")
        if job_uuid is None or tenant_uuid is None or snapshot_version <= 0:
            return None

        clustering = await self._session.get(IdentityClusteringJob, job_uuid)
        if clustering is None or clustering.tenant_id != tenant_uuid:
            return None

        clustering.snapshot_version = snapshot_version
        clustering.source_job_id = clustering.source_job_id or job_uuid
        clustering.projection_acknowledged_at = acknowledged_at
        await self._session.flush()

        return ProjectionStatus(
            snapshot_version=snapshot_version,
            source_job_id=str(clustering.source_job_id or clustering.id),
            acknowledged_at=acknowledged_at,
        )


def _compute_progress(completed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return min(1.0, completed / total)


def _coerce_positive_int(value: object) -> int | None:
    try:
        coerced = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None


def _hydrate_projection_payload(clustering: IdentityClusteringJob) -> dict[str, object]:
    payload = dict(clustering.payload or {})
    if clustering.snapshot_version is not None:
        payload["snapshot_version"] = clustering.snapshot_version
    if clustering.source_job_id is not None:
        payload["source_job_id"] = str(clustering.source_job_id)
    if clustering.projection_acknowledged_at is not None:
        payload["projection_acknowledged_at"] = clustering.projection_acknowledged_at.isoformat()
    return payload


def _first_clustering_row(result: object) -> IdentityClusteringJob | None:
    scalars = getattr(result, "scalars", None)
    if not callable(scalars):
        return None

    scalar_result = scalars()
    first = getattr(scalar_result, "first", None)
    if callable(first):
        value = first()
        return value if isinstance(value, IdentityClusteringJob) else None

    all_rows = getattr(scalar_result, "all", None)
    if callable(all_rows):
        rows = all_rows()
        if isinstance(rows, list) and rows:
            first_row = rows[0]
            return first_row if isinstance(first_row, IdentityClusteringJob) else None

    return None


def _coerce_payload_uuid(value: object) -> UUID | None:
    if isinstance(value, (str, UUID)):
        return _coerce_uuid(value, on_failure="none")
    return None


def _coerce_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or value == "":
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
