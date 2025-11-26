"""Metrics HTTP routes for clustering quality monitoring."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, MediaIdentity
from db.session import get_session
from db.tenant_context import set_tenant_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])


class ClusteringMetricsResponse(BaseModel):
    """Response model for clustering metrics."""

    tenant_id: str
    collected_at: str

    # Cluster distribution
    total_identities: int
    total_clusters: int
    singleton_count: int
    singleton_ratio: float = Field(description="Ratio of singleton clusters to total clusters (lower is better)")

    # Cluster sizes
    avg_cluster_size: float
    median_cluster_size: float | None = None
    max_cluster_size: int

    # Quality indicators (placeholder - requires more complex computation)
    avg_intra_cluster_similarity: float | None = Field(
        default=None,
        description="Average similarity within clusters (higher is better)",
    )


class ClusteringMetricsSnapshotResponse(ClusteringMetricsResponse):
    """Response model for metrics snapshot with label."""

    label: str = Field(description="Label for this snapshot (e.g., 'before_confidence_weighting')")
    snapshot_id: str | None = Field(
        default=None,
        description="ID for persisted snapshots (if saved to database)",
    )


@router.get("/metrics", response_model=ClusteringMetricsResponse)
async def get_clustering_metrics(
    tenant_id: UUID = Query(..., description="Tenant ID for RLS scoping"),
    session: AsyncSession = Depends(get_session),
) -> ClusteringMetricsResponse:
    """
    Get current clustering quality metrics for a tenant.

    Metrics include:
    - Cluster distribution (total, singletons, ratio)
    - Cluster sizes (average, max)
    - Quality indicators (intra-cluster similarity - if computed)
    """
    await set_tenant_context(session, tenant_id)

    # Total identities
    identity_count_stmt = select(func.count(MediaIdentity.id)).where(MediaIdentity.tenant_id == tenant_id)
    identity_result = await session.execute(identity_count_stmt)
    total_identities = identity_result.scalar() or 0

    # Total clusters
    cluster_count_stmt = select(func.count(IdentityCluster.id)).where(IdentityCluster.tenant_id == tenant_id)
    cluster_result = await session.execute(cluster_count_stmt)
    total_clusters = cluster_result.scalar() or 0

    # Singleton count (clusters with exactly 1 member)
    singleton_stmt = select(func.count(IdentityCluster.id)).where(
        IdentityCluster.tenant_id == tenant_id,
        IdentityCluster.identity_count == 1,
    )
    singleton_result = await session.execute(singleton_stmt)
    singleton_count = singleton_result.scalar() or 0

    # Cluster sizes
    size_stats_stmt = select(
        func.avg(IdentityCluster.identity_count).label("avg_size"),
        func.max(IdentityCluster.identity_count).label("max_size"),
    ).where(IdentityCluster.tenant_id == tenant_id)
    size_result = await session.execute(size_stats_stmt)
    size_row = size_result.one_or_none()

    avg_cluster_size = float(size_row.avg_size) if size_row and size_row.avg_size else 0.0
    max_cluster_size = int(size_row.max_size) if size_row and size_row.max_size else 0

    # Compute singleton ratio
    singleton_ratio = singleton_count / total_clusters if total_clusters > 0 else 0.0

    return ClusteringMetricsResponse(
        tenant_id=str(tenant_id),
        collected_at=datetime.utcnow().isoformat(),
        total_identities=total_identities,
        total_clusters=total_clusters,
        singleton_count=singleton_count,
        singleton_ratio=round(singleton_ratio, 4),
        avg_cluster_size=round(avg_cluster_size, 2),
        median_cluster_size=None,  # Would require window function
        max_cluster_size=max_cluster_size,
        avg_intra_cluster_similarity=None,  # Expensive to compute, optional
    )


@router.get("/metrics/snapshot", response_model=ClusteringMetricsSnapshotResponse)
async def get_clustering_metrics_snapshot(
    tenant_id: UUID = Query(..., description="Tenant ID for RLS scoping"),
    label: str = Query(..., description="Label for this snapshot"),
    session: AsyncSession = Depends(get_session),
) -> ClusteringMetricsSnapshotResponse:
    """
    Get clustering metrics as a labeled snapshot for A/B comparison.

    Use this endpoint to capture metrics before and after changes:
    - GET /metrics/snapshot?label=before_confidence_weighting
    - (make changes)
    - GET /metrics/snapshot?label=after_confidence_weighting
    """
    # Get base metrics
    metrics = await get_clustering_metrics(tenant_id=tenant_id, session=session)

    return ClusteringMetricsSnapshotResponse(
        **metrics.model_dump(),
        label=label,
        snapshot_id=None,  # Not persisted yet
    )
