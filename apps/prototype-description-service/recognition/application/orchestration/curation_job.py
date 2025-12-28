"""
Post-curation recompute job runner.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from recognition.application.orchestration.cluster_service import ClusterService
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.constraints import ConstraintSource, ConstraintType
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
    source_cluster_id: str | None = None,
) -> dict[str, int]:
    """Execute post-curation cleanup tasks.

    Args:
        tenant_id: Tenant owning the clusters.
        cluster_ids: Clusters to recompute.
        assignment_writer: Writer used to recompute representatives/centroid.
        cluster_repo: Repository used to inspect unclustered identities.
        cluster_service: Optional cluster service for incremental clustering.
        run_incremental_clustering: Whether to re-cluster orphans.
        source_cluster_id: Optional source cluster ID to delete after merge cleanup.

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

    identities_clustered = 0
    if run_incremental_clustering and cluster_service is not None:
        unclustered = await cluster_repo.get_unclustered(tenant_id)
        if unclustered:
            result = await cluster_service.cluster_unclustered_identities(tenant_id, commit=False)
            identities_clustered = int(getattr(result, "completed", 0) or 0)

    if source_cluster_id and cluster_service is not None and unique_cluster_ids:
        target_cluster_id = unique_cluster_ids[0]
        constraint_repo = getattr(cluster_service, "constraint_repository", None)
        if constraint_repo is not None:
            try:
                source_cluster = await cluster_repo.get_by_id(source_cluster_id)
                target_cluster = await cluster_repo.get_by_id(target_cluster_id)
                source_rep_id = getattr(source_cluster, "representative_identity_id", None) if source_cluster else None
                target_rep_id = getattr(target_cluster, "representative_identity_id", None) if target_cluster else None
                if source_rep_id and target_rep_id and source_rep_id != target_rep_id:
                    await constraint_repo.create(
                        tenant_id=tenant_id,
                        identity_a=str(source_rep_id),
                        identity_b=str(target_rep_id),
                        constraint_type=ConstraintType.MUST_LINK.value,
                        source=ConstraintSource.MERGE.value,
                    )
            except Exception as exc:
                logger.warning(
                    "[curation_job] must_link create failed tenant_id=%s source_cluster_id=%s target_cluster_id=%s: %s",
                    tenant_id,
                    source_cluster_id,
                    target_cluster_id,
                    exc,
                )

        try:
            await cluster_service.retry_matching(target_cluster_id=target_cluster_id, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning(
                "[curation_job] retry_matching failed tenant_id=%s target_cluster_id=%s: %s",
                tenant_id,
                target_cluster_id,
                exc,
            )

        try:
            await cluster_service.suggestion_service.refresh_for_cluster(target_cluster_id)
        except Exception as exc:
            logger.warning(
                "[curation_job] refresh_for_cluster failed tenant_id=%s cluster_id=%s: %s",
                tenant_id,
                target_cluster_id,
                exc,
            )

    logger.info(
        "[curation_job] COMPLETE tenant_id=%s clusters_recomputed=%d identities_clustered=%d",
        tenant_id,
        len(unique_cluster_ids),
        identities_clustered,
    )

    if source_cluster_id:
        logger.info("[curation_job] cleaning up merged source_cluster=%s", source_cluster_id)
        # Delete source cluster after recomputations are complete
        if cluster_repo:
            await cluster_repo.delete(source_cluster_id)

    return {
        "clusters_recomputed": len(unique_cluster_ids),
        "identities_clustered": identities_clustered,
    }
