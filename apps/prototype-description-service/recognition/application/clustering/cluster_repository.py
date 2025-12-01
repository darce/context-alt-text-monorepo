"""Repository for cluster-related database operations."""

from __future__ import annotations

from uuid import UUID

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    ClusterCentroid,
    IdentityCluster,
    IdentityClusteringJob,
    IdentityClusterRepresentative,
    IdentityMember,
    MediaIdentity,
)
from recognition.application.clustering.centroid_utils import _normalize_vector


class ClusterSearchEntry:
    """In-memory representation of a cluster centroid for incremental search."""

    def __init__(self, cluster: IdentityCluster, centroid: np.ndarray, member_count: int):
        self.cluster = cluster
        self.centroid = centroid
        self.member_count = member_count


class ClusterRepository:
    """Handles all database queries for clustering operations."""

    def __init__(self, session: AsyncSession, tenant_id: UUID):
        self.session = session
        self.tenant_id = tenant_id

    async def get_cluster_representatives(self, cluster_id: UUID) -> list[np.ndarray]:
        """Get all representative embeddings for a cluster."""
        stmt = (
            select(IdentityClusterRepresentative.embedding)
            .where(IdentityClusterRepresentative.cluster_id == cluster_id)
            .where(IdentityClusterRepresentative.tenant_id == self.tenant_id)
        )
        result = await self.session.execute(stmt)
        reps = []
        for row in result.scalars().all():
            reps.append(_normalize_vector(np.array(row, dtype=np.float32)))
        return reps

    async def count_representatives_for_media(self, cluster_id: UUID, media_id: int) -> int:
        """Count how many representatives exist for a given media in a cluster."""
        stmt = (
            select(func.count())
            .select_from(IdentityClusterRepresentative)
            .join(MediaIdentity, MediaIdentity.id == IdentityClusterRepresentative.identity_id)
            .where(IdentityClusterRepresentative.cluster_id == cluster_id)
            .where(IdentityClusterRepresentative.tenant_id == self.tenant_id)
            .where(MediaIdentity.media_id == media_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_unclustered_identities(self) -> list[MediaIdentity]:
        """Get all identities that haven't been assigned to any cluster."""
        membership_exists = (
            select(1)
            .where(
                IdentityMember.tenant_id == self.tenant_id,
                IdentityMember.identity_id == MediaIdentity.id,
            )
            .exists()
        )

        stmt = (
            select(MediaIdentity)
            .where(
                MediaIdentity.tenant_id == self.tenant_id,
                ~membership_exists,
            )
            .order_by(MediaIdentity.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_unclustered_identities(self) -> int:
        """Count identities that haven't been assigned to any cluster."""
        membership_exists = (
            select(1)
            .where(
                IdentityMember.tenant_id == self.tenant_id,
                IdentityMember.identity_id == MediaIdentity.id,
            )
            .exists()
        )

        stmt = (
            select(func.count())
            .select_from(MediaIdentity)
            .where(
                MediaIdentity.tenant_id == self.tenant_id,
                ~membership_exists,
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def count_labeled_clusters(self) -> int:
        """Count clusters that have a user-assigned label (not auto-generated)."""
        stmt = (
            select(func.count())
            .select_from(IdentityCluster)
            .where(
                IdentityCluster.tenant_id == self.tenant_id,
                IdentityCluster.label.isnot(None),
                # Exclude auto-generated labels like "cluster-abc123"
                ~IdentityCluster.label.like("cluster-%"),
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_clusters_with_centroids(self) -> list[ClusterSearchEntry]:
        """Get all clusters with their computed centroids from the materialized view."""
        stmt = (
            select(
                IdentityCluster,
                ClusterCentroid.centroid,
                ClusterCentroid.member_count,
            )
            .join(ClusterCentroid, IdentityCluster.id == ClusterCentroid.cluster_id)
            .where(IdentityCluster.tenant_id == self.tenant_id)
        )

        result = await self.session.execute(stmt)
        entries: list[ClusterSearchEntry] = []

        for cluster, centroid, member_count in result.all():
            if centroid is None or member_count is None:
                continue
            entries.append(
                ClusterSearchEntry(
                    cluster=cluster,
                    centroid=np.array(centroid, dtype=np.float32),
                    member_count=int(member_count),
                )
            )
        return entries

    async def get_clusters_with_representatives(self) -> dict[UUID, list[np.ndarray]]:
        """Get all clusters that have representative embeddings."""
        stmt = select(
            IdentityClusterRepresentative.cluster_id,
            IdentityClusterRepresentative.embedding,
        ).where(IdentityClusterRepresentative.tenant_id == self.tenant_id)
        result = await self.session.execute(stmt)
        reps: dict[UUID, list[np.ndarray]] = {}
        for cluster_id, embedding in result.all():
            reps.setdefault(cluster_id, []).append(_normalize_vector(np.array(embedding, dtype=np.float32)))
        return reps

    async def create_clustering_job(
        self,
        total_identities: int | None = None,
        created_by_user_id: int | None = None,
    ) -> IdentityClusteringJob:
        """Create a clustering job record for async processing."""

        job = IdentityClusteringJob(
            tenant_id=self.tenant_id,
            status="pending",
            progress=0.0,
            total_identities=total_identities,
            processed_identities=0,
            created_by_user_id=created_by_user_id,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_clustering_job(self, job_id: UUID) -> IdentityClusteringJob | None:
        """Fetch a clustering job scoped to the current tenant."""

        stmt = (
            select(IdentityClusteringJob)
            .where(IdentityClusteringJob.id == job_id)
            .where(IdentityClusteringJob.tenant_id == self.tenant_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_clustering_job(
        self,
        job_id: UUID,
        *,
        status: str | None = None,
        progress: float | None = None,
        processed_identities: int | None = None,
        total_identities: int | None = None,
        error_message: str | None = None,
        started_at: object | None = None,
        completed_at: object | None = None,
    ) -> IdentityClusteringJob | None:
        """Update job fields in-place and return the job."""

        job = await self.get_clustering_job(job_id)
        if not job:
            return None

        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = progress
        if processed_identities is not None:
            job.processed_identities = processed_identities
        if total_identities is not None:
            job.total_identities = total_identities
        if error_message is not None:
            job.error_message = error_message
        if started_at is not None:
            job.started_at = started_at  # type: ignore[assignment]
        if completed_at is not None:
            job.completed_at = completed_at  # type: ignore[assignment]

        await self.session.flush()
        return job
