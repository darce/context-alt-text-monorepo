"""Cluster query helpers for curation workflows."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.orchestration.curation.outlier import build_outlier_cluster, is_outlier_cluster
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import ClusterRepository, MemberRepository


async def list_clusters(
    *,
    cluster_repo: ClusterRepository,
    session: AsyncSession | None,
    tenant_id: str,
    limit: int = 100,
    offset: int = 0,
    include_outliers: bool = False,
    labeled_only: bool = False,
    search: str | None = None,
) -> list[IdentityCluster]:
    """Return clusters for a tenant using the persistence layer."""
    clusters = await cluster_repo.get_by_tenant(
        tenant_id, limit=limit, offset=offset, labeled_only=labeled_only, search=search
    )
    for cluster in clusters:
        cluster.representatives = getattr(cluster, "representatives", []) or []
    if include_outliers:
        outlier_cluster = await build_outlier_cluster(session, tenant_id)
        if outlier_cluster and outlier_cluster.identity_count > 0:
            outlier_cluster.representatives = getattr(outlier_cluster, "representatives", []) or []
            clusters.append(outlier_cluster)
        return clusters
    return [c for c in clusters if not is_outlier_cluster(c)]


async def get_identity_cluster_id(*, member_repo: MemberRepository, identity_id: str) -> str | None:
    """Get the cluster ID that an identity currently belongs to."""
    members = await member_repo.get_by_identity_id(identity_id)
    if members:
        return members[0].cluster_id
    return None
