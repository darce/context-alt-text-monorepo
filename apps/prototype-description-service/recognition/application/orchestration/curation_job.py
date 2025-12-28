"""
Post-curation recompute job runner.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from recognition.application.orchestration.cluster_service import ClusterService
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.repositories import ClusterRepository

logger = logging.getLogger(__name__)


async def run_curation_job(
    *,
    tenant_id: str,
    cluster_ids: Sequence[str],
    assignment_writer: AssignmentWriter,
    cluster_repo: ClusterRepository,
    cluster_service: ClusterService | None = None,
    run_incremental_clustering: bool = True,
) -> dict[str, int]:
    """Execute post-curation cleanup tasks.

    Args:
        tenant_id: Tenant owning the clusters.
        cluster_ids: Clusters to recompute.
        assignment_writer: Writer used to recompute representatives/centroid.
        cluster_repo: Repository used to inspect unclustered identities.
        cluster_service: Optional cluster service for incremental clustering.
        run_incremental_clustering: Whether to re-cluster orphans.

    Returns:
        Dict with counts: {"clusters_recomputed": N, "identities_clustered": M}.
    """
    unique_cluster_ids = list(dict.fromkeys(cluster_ids))
    logger.info(
        "[curation_job] START tenant_id=%s cluster_ids=%s",
        tenant_id,
        unique_cluster_ids,
    )

    recompute_reps = getattr(assignment_writer, "recompute_representatives", None)
    recompute_centroid = getattr(assignment_writer, "recompute_centroid", None)
    for cluster_id in unique_cluster_ids:
        if callable(recompute_reps):
            await recompute_reps(cluster_id)
        if callable(recompute_centroid):
            await recompute_centroid(cluster_id)

    refresh_view = getattr(assignment_writer, "refresh_centroids_view", None)
    if callable(refresh_view):
        await refresh_view()

    identities_clustered = 0
    if run_incremental_clustering and cluster_service is not None:
        unclustered = await cluster_repo.get_unclustered(tenant_id)
        if unclustered:
            result = await cluster_service.cluster_unclustered_identities(tenant_id, commit=False)
            identities_clustered = int(getattr(result, "completed", 0) or 0)

    logger.info(
        "[curation_job] COMPLETE tenant_id=%s clusters_recomputed=%d identities_clustered=%d",
        tenant_id,
        len(unique_cluster_ids),
        identities_clustered,
    )
    return {
        "clusters_recomputed": len(unique_cluster_ids),
        "identities_clustered": identities_clustered,
    }
