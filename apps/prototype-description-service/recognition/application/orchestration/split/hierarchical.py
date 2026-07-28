"""Hierarchical clustering helpers for cluster splitting."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.clustering.hierarchical_clustering import HierarchicalClustering
from recognition.application.orchestration.split.anchor import force_anchor_split
from recognition.config.settings import (
    resolve_effective_clustering_settings,
    resolve_effective_limits_settings,
)

logger = logging.getLogger(__name__)

# Historical split distance floor (cosine-distance units). Never loosen past this
# when limits.similarity is low; stricter limits raise the cut (lower distance).
_LEGACY_SPLIT_DISTANCE_FLOOR = 0.30


def _split_distance_threshold() -> float:
    """Derive hierarchical split distance from profile-resolved limits similarity."""
    limits_sim = float(resolve_effective_limits_settings().similarity_threshold)
    # Unit-vector cosine distance proxy: d ≈ 1 - cosine_similarity.
    from_limits = max(0.0, 1.0 - limits_sim)
    return min(_LEGACY_SPLIT_DISTANCE_FLOOR, from_limits)


def build_clusters_by_label(
    identities: Sequence[MediaIdentityModel],
    *,
    n_clusters: int,
    anchor_key: str | None,
    similarity_floor: float | None = None,
    cluster_id: str | None = None,
) -> dict[int, list[MediaIdentityModel]]:
    """Cluster identities into groups for split operations."""
    hierarchical = HierarchicalClustering(distance_threshold=_split_distance_threshold())
    identity_list = list(identities)
    clusters_by_label = hierarchical.split_identities(identity_list, n_clusters)

    if anchor_key and n_clusters >= 2 and len(clusters_by_label) <= 1:
        clusters_by_label = force_anchor_split(
            identity_list,
            anchor_key,
            similarity_floor=similarity_floor
            if similarity_floor is not None
            else resolve_effective_clustering_settings().anchor_split_similarity_floor,
        )
        if cluster_id:
            logger.info("Split cluster %s: forced anchor split for anchor=%s", cluster_id, anchor_key)
        else:
            logger.info("Split cluster: forced anchor split for anchor=%s", anchor_key)

    return clusters_by_label
