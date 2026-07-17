"""Tenant export service implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from db.models import (
    ClusterMergeSuggestion,
    ExportJob,
    IdentityCluster,
    IdentityClusterRepresentative,
    IdentityMember,
    IdentityScanJob,
    IdentityScanJobItem,
    IdentitySuggestion,
    MediaIdentity,
    NameSuggestion,
    Tenant,
)
from recognition.application.services.audit_service import AuditService
from recognition.domain.job import JobStatus
from recognition.infrastructure.repositories._helpers import coerce_uuid

EXPORT_SCHEMA_VERSION = 2


def _serialize_timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _serialize_uuid(value: UUID | str | None) -> str | None:
    return str(value) if value is not None else None


class TenantExportService:
    """Produces a portable export of machine-derived tenant state."""

    def __init__(self, session: AsyncSession, audit_service: AuditService | None = None) -> None:
        self._session = session
        self._audit_service = audit_service or AuditService()

    async def count_exportable_identities(self, tenant_id: str) -> int:
        """Return the number of media identities for the tenant."""
        tenant_uuid = coerce_uuid(tenant_id, on_failure="none")
        if tenant_uuid is None:
            return 0
        result = await self._session.execute(
            select(func.count()).select_from(MediaIdentity).where(MediaIdentity.tenant_id == tenant_uuid)
        )
        return result.scalar_one()

    async def start_async_export(self, tenant_id: str, actor: str) -> dict[str, object]:
        """Create an ExportJob row and return the job_id."""
        tenant_uuid = coerce_uuid(tenant_id, on_failure="none")
        if tenant_uuid is None:
            raise ValueError("invalid tenant_id")
        job = ExportJob(
            tenant_id=tenant_uuid,
            status=JobStatus.PENDING,
            created_by_actor=actor,
        )
        self._session.add(job)
        await self._session.flush()
        return {"job_id": str(job.id), "status": "pending"}

    async def get_export_status(self, job_id: str, tenant_id: str) -> dict[str, object]:
        """Return current status of an export job."""
        job_uuid = coerce_uuid(job_id, on_failure="none")
        tenant_uuid = coerce_uuid(tenant_id, on_failure="none")
        if job_uuid is None or tenant_uuid is None:
            return {"error": "not_found"}
        result = await self._session.execute(
            select(ExportJob).where(
                ExportJob.id == job_uuid,
                ExportJob.tenant_id == tenant_uuid,
            )
        )
        job = result.scalar_one_or_none()
        if job is None:
            return {"error": "not_found"}
        return {
            "job_id": str(job.id),
            "status": job.status,
            "file_size": job.file_size,
            "error_message": job.error_message,
            "data_json": job.data_json,
        }

    async def export_tenant_data(self, tenant_id: str, actor: str) -> dict[str, object]:
        exported_at = datetime.now(tz=UTC)
        tenant = await self._get_tenant(tenant_id)

        await self._audit_service.record_event(
            self._session,
            tenant_id=str(tenant.id),
            event_type="export_started",
            actor=actor,
            scope="tenant",
            payload={"retention_mode": tenant.retention_mode},
        )

        clusters = await self._list_clusters(tenant.id)
        identities = await self._list_identities(tenant.id)
        suggestions = await self._list_suggestions(tenant.id)
        name_suggestions = await self._list_name_suggestions(tenant.id)
        merge_suggestions = await self._list_merge_suggestions(tenant.id)
        scan_jobs = await self._list_scan_jobs(tenant.id)

        tenant.last_export_at = exported_at
        await self._session.flush()

        await self._audit_service.record_event(
            self._session,
            tenant_id=str(tenant.id),
            event_type="export_completed",
            actor=actor,
            scope="tenant",
            payload={
                "cluster_count": len(clusters),
                "identity_count": len(identities),
                "suggestion_count": len(suggestions),
                "name_suggestion_count": len(name_suggestions),
                "merge_suggestion_count": len(merge_suggestions),
                "scan_job_count": len(scan_jobs),
                "exported_at": exported_at.isoformat(),
            },
        )
        await self._session.commit()
        await self._session.refresh(tenant)

        return {
            "tenant_id": str(tenant.id),
            "retention_mode": tenant.retention_mode,
            "exported_at": exported_at.isoformat(),
            "schema_version": EXPORT_SCHEMA_VERSION,
            "clusters": [self._serialize_cluster(cluster) for cluster in clusters],
            "media_identities": [self._serialize_identity(identity) for identity in identities],
            "identity_suggestions": [self._serialize_suggestion(item) for item in suggestions],
            "name_suggestions": [self._serialize_name_suggestion(item) for item in name_suggestions],
            "cluster_merge_suggestions": [self._serialize_merge_suggestion(item) for item in merge_suggestions],
            "scan_jobs": [self._serialize_scan_job(job) for job in scan_jobs],
        }

    async def _get_tenant(self, tenant_id: str) -> Tenant:
        tenant_uuid = coerce_uuid(tenant_id, on_failure="none")
        if tenant_uuid is None:
            raise ValueError("invalid tenant_id")

        tenant = await self._session.get(Tenant, tenant_uuid)
        if tenant is None:
            raise LookupError("tenant not found")
        return tenant

    async def _list_clusters(self, tenant_id: UUID) -> list[IdentityCluster]:
        stmt = (
            select(IdentityCluster)
            .where(IdentityCluster.tenant_id == tenant_id)
            .where(IdentityCluster.disposed_at.is_(None))
            .options(
                selectinload(IdentityCluster.members).selectinload(IdentityMember.identity),
                selectinload(IdentityCluster.representatives).selectinload(IdentityClusterRepresentative.identity),
            )
            .order_by(IdentityCluster.created_at.asc(), IdentityCluster.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().unique().all())

    async def _list_identities(self, tenant_id: UUID) -> list[MediaIdentity]:
        stmt = (
            select(MediaIdentity)
            .where(MediaIdentity.tenant_id == tenant_id)
            .where(MediaIdentity.disposed_at.is_(None))
            .order_by(MediaIdentity.created_at.asc(), MediaIdentity.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _list_suggestions(self, tenant_id: UUID) -> list[IdentitySuggestion]:
        stmt = (
            select(IdentitySuggestion)
            .join(MediaIdentity, IdentitySuggestion.identity_id == MediaIdentity.id)
            .join(IdentityCluster, IdentitySuggestion.suggested_cluster_id == IdentityCluster.id)
            .where(IdentitySuggestion.tenant_id == tenant_id)
            .where(MediaIdentity.disposed_at.is_(None))
            .where(IdentityCluster.disposed_at.is_(None))
            .order_by(IdentitySuggestion.created_at.asc(), IdentitySuggestion.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _list_name_suggestions(self, tenant_id: UUID) -> list[NameSuggestion]:
        stmt = (
            select(NameSuggestion)
            .join(IdentityCluster, NameSuggestion.cluster_id == IdentityCluster.id)
            .where(NameSuggestion.tenant_id == tenant_id)
            .where(IdentityCluster.disposed_at.is_(None))
            .where(NameSuggestion.disposed_at.is_(None))
            .order_by(NameSuggestion.created_at.asc(), NameSuggestion.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _list_merge_suggestions(self, tenant_id: UUID) -> list[ClusterMergeSuggestion]:
        cluster_a = aliased(IdentityCluster)
        cluster_b = aliased(IdentityCluster)
        stmt = (
            select(ClusterMergeSuggestion)
            .join(cluster_a, ClusterMergeSuggestion.cluster_a_id == cluster_a.id)
            .join(cluster_b, ClusterMergeSuggestion.cluster_b_id == cluster_b.id)
            .where(ClusterMergeSuggestion.tenant_id == tenant_id)
            .where(cluster_a.disposed_at.is_(None))
            .where(cluster_b.disposed_at.is_(None))
            .order_by(ClusterMergeSuggestion.created_at.asc(), ClusterMergeSuggestion.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _list_scan_jobs(self, tenant_id: UUID) -> list[IdentityScanJob]:
        stmt = (
            select(IdentityScanJob)
            .where(IdentityScanJob.tenant_id == tenant_id)
            .options(selectinload(IdentityScanJob.items))
            .order_by(IdentityScanJob.created_at.asc(), IdentityScanJob.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().unique().all())

    def _serialize_cluster(self, cluster: IdentityCluster) -> dict[str, object]:
        active_members = [member for member in cluster.members if self._is_active_identity(member.identity)]
        active_representatives = [
            representative
            for representative in cluster.representatives
            if self._is_active_representative(representative)
        ]
        active_identity_ids = {member.identity_id for member in active_members}
        active_identity_ids.update(representative.identity_id for representative in active_representatives)
        representative_identity_id = (
            cluster.representative_identity_id if cluster.representative_identity_id in active_identity_ids else None
        )

        return {
            "id": str(cluster.id),
            "label": cluster.label,
            "identity_type": cluster.identity_type,
            "representative_identity_id": _serialize_uuid(representative_identity_id),
            "identity_count": len(active_members),
            "user_confirmed": cluster.user_confirmed,
            "confirmation_count": cluster.confirmation_count,
            "confirmation_source": cluster.confirmation_source,
            "last_exported_snapshot_id": _serialize_uuid(cluster.last_exported_snapshot_id),
            "disposed_at": _serialize_timestamp(cluster.disposed_at),
            "created_at": _serialize_timestamp(cluster.created_at),
            "updated_at": _serialize_timestamp(cluster.updated_at),
            "members": [
                self._serialize_member(member) for member in sorted(active_members, key=lambda item: str(item.id))
            ],
            "representatives": [
                self._serialize_representative(item)
                for item in sorted(active_representatives, key=lambda representative: str(representative.id))
            ],
        }

    def _serialize_member(self, member: IdentityMember) -> dict[str, object]:
        return {
            "id": str(member.id),
            "identity_id": str(member.identity_id),
            "similarity": member.similarity,
            "assigned_at": _serialize_timestamp(member.assigned_at),
            "created_at": _serialize_timestamp(member.created_at),
            "identity": self._serialize_identity(member.identity),
        }

    def _serialize_representative(self, representative: IdentityClusterRepresentative) -> dict[str, object]:
        return {
            "id": str(representative.id),
            "identity_id": str(representative.identity_id),
            "quality_score": representative.quality_score,
            "diversity_score": representative.diversity_score,
            "pose_pitch": representative.pose_pitch,
            "pose_yaw": representative.pose_yaw,
            "pose_roll": representative.pose_roll,
            "is_pinned": representative.is_user_selected,
            "is_provisional": representative.is_provisional,
            "last_exported_snapshot_id": _serialize_uuid(representative.last_exported_snapshot_id),
            "disposed_at": _serialize_timestamp(representative.disposed_at),
            "created_at": _serialize_timestamp(representative.created_at),
            "identity": self._serialize_identity(representative.identity),
        }

    def _serialize_identity(self, identity: MediaIdentity) -> dict[str, object]:
        return {
            "id": str(identity.id),
            "media_id": identity.media_id,
            "media_url": identity.media_url,
            "identity_type": identity.identity_type,
            "bbox": {
                "x": identity.bbox_x,
                "y": identity.bbox_y,
                "width": identity.bbox_width,
                "height": identity.bbox_height,
            },
            "confidence": identity.confidence,
            "pose_pitch": identity.pose_pitch,
            "pose_yaw": identity.pose_yaw,
            "pose_roll": identity.pose_roll,
            "quality_score": identity.quality_score,
            "image_phash": identity.image_phash,
            "last_exported_snapshot_id": _serialize_uuid(identity.last_exported_snapshot_id),
            "disposed_at": _serialize_timestamp(identity.disposed_at),
            "created_at": _serialize_timestamp(identity.created_at),
            "updated_at": _serialize_timestamp(identity.updated_at),
        }

    def _serialize_suggestion(self, suggestion: IdentitySuggestion) -> dict[str, object]:
        return {
            "id": str(suggestion.id),
            "identity_id": str(suggestion.identity_id),
            "suggested_cluster_id": str(suggestion.suggested_cluster_id),
            "representative_similarity": suggestion.representative_similarity,
            "avg_member_similarity": suggestion.avg_member_similarity,
            "confidence_score": suggestion.confidence_score,
            "priority": suggestion.priority,
            "resolution": suggestion.resolution,
            "source": suggestion.source,
            "source_job_id": _serialize_uuid(suggestion.source_job_id),
            "created_at": _serialize_timestamp(suggestion.created_at),
            "expires_at": _serialize_timestamp(suggestion.expires_at),
            "resolved_at": _serialize_timestamp(suggestion.resolved_at),
            "refreshed_at": _serialize_timestamp(suggestion.refreshed_at),
        }

    def _serialize_merge_suggestion(self, suggestion: ClusterMergeSuggestion) -> dict[str, object]:
        return {
            "id": str(suggestion.id),
            "cluster_a_id": str(suggestion.cluster_a_id),
            "cluster_b_id": str(suggestion.cluster_b_id),
            "similarity": suggestion.similarity,
            "confidence_score": suggestion.confidence_score,
            "resolution": suggestion.resolution,
            "source": suggestion.source,
            "source_job_id": _serialize_uuid(suggestion.source_job_id),
            "created_at": _serialize_timestamp(suggestion.created_at),
            "expires_at": _serialize_timestamp(suggestion.expires_at),
            "resolved_at": _serialize_timestamp(suggestion.resolved_at),
            "refreshed_at": _serialize_timestamp(suggestion.refreshed_at),
        }

    def _serialize_name_suggestion(self, suggestion: NameSuggestion) -> dict[str, object]:
        return {
            "id": str(suggestion.id),
            "cluster_id": str(suggestion.cluster_id),
            "suggested_name": suggestion.suggested_name,
            "confidence_score": suggestion.confidence_score,
            "source": suggestion.source,
            "source_job_id": _serialize_uuid(suggestion.source_job_id),
            "resolution": suggestion.resolution,
            "last_exported_snapshot_id": _serialize_uuid(suggestion.last_exported_snapshot_id),
            "disposed_at": _serialize_timestamp(suggestion.disposed_at),
            "created_at": _serialize_timestamp(suggestion.created_at),
            "expires_at": _serialize_timestamp(suggestion.expires_at),
            "resolved_at": _serialize_timestamp(suggestion.resolved_at),
        }

    def _serialize_scan_job(self, job: IdentityScanJob) -> dict[str, object]:
        return {
            "id": str(job.id),
            "status": job.status,
            "media_ids": list(job.media_ids),
            "total_media": job.total_media,
            "processed_media": job.processed_media,
            "identities_detected": job.identities_detected,
            "error_message": job.error_message,
            "message": job.message,
            "created_at": _serialize_timestamp(job.created_at),
            "started_at": _serialize_timestamp(job.started_at),
            "completed_at": _serialize_timestamp(job.completed_at),
            "items": [
                self._serialize_scan_job_item(item) for item in sorted(job.items, key=lambda entry: str(entry.id))
            ],
        }

    def _serialize_scan_job_item(self, item: IdentityScanJobItem) -> dict[str, object]:
        return {
            "id": str(item.id),
            "media_id": item.media_id,
            "media_url": item.media_url,
            "status": item.status,
            "attempts": item.attempts,
            "identities_detected": item.identities_detected,
            "last_error": item.last_error,
            "created_at": _serialize_timestamp(item.created_at),
            "started_at": _serialize_timestamp(item.started_at),
            "completed_at": _serialize_timestamp(item.completed_at),
        }

    @staticmethod
    def _is_active_identity(identity: MediaIdentity) -> bool:
        return identity.disposed_at is None

    @classmethod
    def _is_active_representative(cls, representative: IdentityClusterRepresentative) -> bool:
        return representative.disposed_at is None and cls._is_active_identity(representative.identity)


async def run_export_to_file(job_id: str, tenant_id: str, actor: str) -> None:
    """Background task: run the export and persist the result in ExportJob.data_json."""
    import json  # noqa: PLC0415 - local import required for background task
    import uuid as _uuid  # noqa: PLC0415
    from datetime import datetime as _dt

    from db.session import async_session_factory  # noqa: PLC0415
    from db.tenant_context import set_tenant_context  # noqa: PLC0415

    job_uuid = coerce_uuid(job_id)
    tenant_uuid = _uuid.UUID(str(tenant_id))

    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_uuid)
        result = await session.execute(select(ExportJob).where(ExportJob.id == job_uuid))
        job = result.scalar_one()
        job.status = JobStatus.RUNNING
        job.started_at = _dt.now(tz=UTC)
        await session.commit()

        svc = TenantExportService(session)
        try:
            payload = await svc.export_tenant_data(tenant_id, actor)
            data_bytes = json.dumps(payload, default=str).encode()

            # Re-query after export_tenant_data's internal commit
            result = await session.execute(select(ExportJob).where(ExportJob.id == job_uuid))
            job = result.scalar_one()
            job.data_json = payload
            job.file_size = len(data_bytes)
            job.status = JobStatus.COMPLETED
            job.completed_at = _dt.now(tz=UTC)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            err_result = await session.execute(select(ExportJob).where(ExportJob.id == job_uuid))
            failed_job = err_result.scalar_one_or_none()
            if failed_job is not None:
                failed_job.status = JobStatus.FAILED
                failed_job.error_message = str(exc)[:500]
                failed_job.completed_at = _dt.now(tz=UTC)
                await session.commit()
