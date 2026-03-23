"""Discovery pipeline helpers for incremental clustering."""

from __future__ import annotations

import contextlib
import logging
import uuid
from typing import TYPE_CHECKING

import numpy as np

from recognition.application.assignment import AssignmentCandidate
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.discovery.graph.helpers import compute_member_similarities
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.identity import MediaIdentity
from recognition.observability import ClusteringLogger
from recognition.shared.similarity import normalize_face_embedding

if TYPE_CHECKING:
    from recognition.application.orchestration.protocols import MergeSuggestionServiceProtocol
    from recognition.application.settings import HACSettings
    from recognition.domain.repositories import ConstrainedHACProtocol

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
    constrained_hac: ConstrainedHACProtocol | None,
    hac_settings: HACSettings | None,
    assignment_writer: AssignmentWriter,
    clustering_logger: ClusteringLogger | None = None,
) -> int:
    """Run constrained HAC refinement on noise identities."""
    if not (
        constrained_hac and hac_settings and still_unclustered and len(still_unclustered) <= hac_settings.max_scope_size
    ):
        return 0

    # HAC requires at least 2 identities to compute pairwise distances
    if len(still_unclustered) < 2:
        logger.debug(
            "[clustering] Skipping HAC refinement: need at least 2 identities, got %d",
            len(still_unclustered),
        )
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
            similarities = compute_member_similarities([member.face_vector for member in members])
            await assignment_writer.persist_new_cluster(
                tenant_id=tenant_id,
                identities=members,
                similarities=similarities,
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


async def run_singleton_hac_refinement(
    *,
    tenant_id: str,
    constrained_hac: ConstrainedHACProtocol | None,
    hac_settings: HACSettings | None,
    assignment_writer: AssignmentWriter,
    merge_suggestion_service: MergeSuggestionServiceProtocol | None = None,
    clustering_logger: ClusteringLogger | None = None,
) -> int:
    """Run constrained HAC refinement on singleton clusters after HDBSCAN."""
    logger.info("[clustering] singleton_hac_start tenant_id=%s", tenant_id)
    if not (constrained_hac and hac_settings):
        logger.info("[clustering] singleton_hac_skip reason=no_hac_configured")
        return 0

    cluster_repo = assignment_writer.cluster_repository
    member_repo = assignment_writer.member_repository

    singletons = await cluster_repo.get_singleton_identities(
        tenant_id,
        limit=hac_settings.max_scope_size,
    )
    logger.info("[clustering] singleton_hac_query singletons_found=%d", len(singletons))
    if len(singletons) < 2:
        logger.info("[clustering] singleton_hac_skip reason=not_enough_singletons count=%d", len(singletons))
        return 0

    embeddings_for_hac: dict[uuid.UUID, np.ndarray] = {}
    identity_to_cluster: dict[uuid.UUID, str] = {}
    for identity in singletons:
        if not identity.cluster_id:
            continue
        try:
            identity_uuid = uuid.UUID(identity.id)
        except ValueError:
            continue
        embeddings_for_hac[identity_uuid] = normalize_face_embedding(np.asarray(identity.embedding, dtype=np.float32))
        identity_to_cluster[identity_uuid] = identity.cluster_id

    logger.info("[clustering] singleton_hac_prepared embeddings=%d", len(embeddings_for_hac))
    if len(embeddings_for_hac) < 2:
        logger.info("[clustering] singleton_hac_skip reason=not_enough_embeddings count=%d", len(embeddings_for_hac))
        return 0

    # Use more lenient threshold for singleton refinement
    singleton_threshold = hac_settings.singleton_distance_threshold
    logger.info(
        "[clustering] singleton_hac_threshold distance=%.3f (similarity=%.1f%%)",
        singleton_threshold,
        (1 - singleton_threshold) * 100,
    )
    hac_clusters = await constrained_hac.refine_clusters(
        tenant_id=uuid.UUID(tenant_id),
        embeddings=embeddings_for_hac,
        distance_threshold_override=singleton_threshold,
    )
    logger.info("[clustering] singleton_hac_refined groups=%d", len(set(hac_clusters.values())))

    hac_groups: dict[uuid.UUID, list[uuid.UUID]] = {}
    for identity_uuid, group_uuid in hac_clusters.items():
        if identity_uuid in identity_to_cluster:
            hac_groups.setdefault(group_uuid, []).append(identity_uuid)

    # Count how many groups have 2+ identities (potential merges)
    merge_candidates = sum(1 for ids in hac_groups.values() if len(ids) >= 2)
    logger.info("[clustering] singleton_hac_groups total=%d merge_candidates=%d", len(hac_groups), merge_candidates)

    merged_clusters = 0
    for identities in hac_groups.values():
        if len(identities) < 2:
            continue
        target_identity = identities[0]
        target_cluster_id = identity_to_cluster.get(target_identity)
        if not target_cluster_id:
            continue

        target_cluster = await cluster_repo.get_by_id(target_cluster_id)
        if not target_cluster:
            continue

        moved_total = 0
        for identity_uuid in identities[1:]:
            source_cluster_id = identity_to_cluster.get(identity_uuid)
            if not source_cluster_id or source_cluster_id == target_cluster_id:
                continue
            moved = await member_repo.move_members(source_cluster_id, target_cluster_id)
            if moved:
                moved_total += moved
                merged_clusters += 1
                delete_by_cluster = getattr(merge_suggestion_service, "delete_by_cluster", None)
                if callable(delete_by_cluster):
                    with contextlib.suppress(Exception):
                        await delete_by_cluster(tenant_id, source_cluster_id)
                        await delete_by_cluster(tenant_id, target_cluster_id)
                await cluster_repo.delete(source_cluster_id)

        if moved_total:
            target_cluster.identity_count = (target_cluster.identity_count or 0) + moved_total
            await cluster_repo.update(target_cluster)
            await assignment_writer.recompute_representatives(target_cluster_id)
            await assignment_writer.recompute_centroid(target_cluster_id)
            logger.info(
                "[clustering] singleton_hac_merge tenant_id=%s target_cluster=%s merged=%d",
                tenant_id,
                target_cluster_id,
                moved_total,
            )

    if merged_clusters:
        await assignment_writer.refresh_centroids_view()

    return merged_clusters
