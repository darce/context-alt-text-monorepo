"""Discovery pipeline helpers for incremental clustering."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import numpy as np

from recognition.application.assignment import AssignmentCandidate
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.identity import MediaIdentity
from recognition.observability import ClusteringLogger

logger = logging.getLogger(__name__)


async def prepare_cluster_caches(
    assignment_writer: AssignmentWriter,
    tenant_id: str,
) -> tuple[dict[str, list[np.ndarray]], dict[str, np.ndarray], set[str]]:
    """Fetch existing clusters and build cached structures for discovery."""
    existing_clusters = await assignment_writer.cluster_repository.get_by_tenant(tenant_id, limit=1000, offset=0)
    logger.info("[clustering] Found %d existing clusters for discovery", len(existing_clusters))

    representatives_by_cluster: dict[str, list[np.ndarray]] = {}
    labeled_cluster_ids: set[str] = set()

    for cluster in existing_clusters:
        if cluster.id is None:
            continue

        is_user_labeled = cluster.user_confirmed or (cluster.label and not cluster.label.startswith("cluster-"))
        if is_user_labeled:
            labeled_cluster_ids.add(cluster.id)

        reps = getattr(cluster, "representatives", []) or []
        if reps:
            representatives_by_cluster[cluster.id] = [
                np.array(r.embedding, dtype=np.float32) for r in reps if r.embedding is not None
            ]

    centroids_by_cluster: dict[str, np.ndarray] = {}
    for cluster in existing_clusters:
        if cluster.id is None:
            continue
        centroid = getattr(cluster, "centroid", None)
        if centroid is not None:
            centroids_by_cluster[cluster.id] = np.array(centroid, dtype=np.float32)

    return representatives_by_cluster, centroids_by_cluster, labeled_cluster_ids


async def run_discovery_pipeline(
    *,
    chunk: list[MediaIdentity],
    representative_discovery: RepresentativeDiscovery,
    centroid_discovery: CentroidDiscovery,
    graph_discovery: GraphDiscovery,
    representatives_by_cluster: dict[str, list[np.ndarray]],
    centroids_by_cluster: dict[str, np.ndarray],
    labeled_cluster_ids: set[str],
) -> tuple[list[AssignmentCandidate], list[tuple[list[MediaIdentity], list[float]]]]:
    """Run the multi-stage discovery pipeline (Rep -> Centroid -> Graph)."""
    rep_candidates = await representative_discovery.discover(
        chunk,
        representatives_by_cluster,
        labeled_cluster_ids=labeled_cluster_ids,
    )
    matched_ids = {c.identity.id for c in rep_candidates}
    chunk_remaining = [i for i in chunk if i.id not in matched_ids]
    logger.info(
        "[clustering] RepresentativeDiscovery: %d candidates, %d remaining",
        len(rep_candidates),
        len(chunk_remaining),
    )

    centroid_candidates = await centroid_discovery.discover(chunk_remaining, centroids_by_cluster)
    centroid_matched_ids = {c.identity.id for c in centroid_candidates}
    chunk_remaining = [i for i in chunk_remaining if i.id not in centroid_matched_ids]
    logger.info(
        "[clustering] CentroidDiscovery: %d candidates, %d remaining",
        len(centroid_candidates),
        len(chunk_remaining),
    )

    anchor_embeddings = representatives_by_cluster
    augmented_anchors = (
        {k: list(v) for k, v in anchor_embeddings.items()} if isinstance(anchor_embeddings, dict) else {}
    )
    for candidate in rep_candidates + centroid_candidates:
        if candidate.cluster_id and candidate.identity.embedding is not None:
            augmented_anchors.setdefault(candidate.cluster_id, []).append(candidate.identity.face_vector)

    graph_result = await graph_discovery.discover(chunk_remaining, augmented_anchors)
    graph_candidates = graph_result.candidates
    new_cluster_proposals = graph_result.new_clusters
    logger.info(
        "[clustering] GraphDiscovery: %d candidates, %d new cluster proposals",
        len(graph_candidates),
        len(new_cluster_proposals),
    )

    all_candidates = rep_candidates + centroid_candidates + graph_candidates
    return all_candidates, new_cluster_proposals


async def run_hac_refinement(
    *,
    still_unclustered: list[MediaIdentity],
    tenant_id: str,
    job_id: str,
    constrained_hac: Any,
    hac_settings: Any,
    assignment_writer: AssignmentWriter,
    clustering_logger: ClusteringLogger | None = None,
) -> int:
    """Run constrained HAC refinement on noise identities."""
    if not (
        constrained_hac and hac_settings and still_unclustered and len(still_unclustered) <= hac_settings.max_scope_size
    ):
        return 0

    logger.info(
        "[clustering] Running HAC refinement on %d noise identities",
        len(still_unclustered),
    )

    embeddings_for_hac = {uuid.UUID(i.id): i.face_vector for i in still_unclustered}

    if not embeddings_for_hac:
        return 0

    hac_clusters = await constrained_hac.refine_clusters(tenant_id=uuid.UUID(tenant_id), embeddings=embeddings_for_hac)

    hac_groups: dict[uuid.UUID, list[MediaIdentity]] = {}
    for identity in still_unclustered:
        cluster_uuid = hac_clusters.get(uuid.UUID(identity.id))
        if cluster_uuid:
            hac_groups.setdefault(cluster_uuid, []).append(identity)

    clusters_created = 0
    for members in hac_groups.values():
        if len(members) > 1:
            await assignment_writer.persist_new_cluster(
                tenant_id=tenant_id,
                identities=members,
                similarities=[],
                algorithm="constrained_hac",
                clustering_logger=clustering_logger,
            )
            clusters_created += 1
            logger.info(
                "[clustering] hac_cluster job_id=%s identity_count=%d media_ids=%s",
                job_id,
                len(members),
                [m.media_id for m in members],
            )
    return clusters_created
