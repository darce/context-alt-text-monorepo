"""Hierarchical clustering helpers for cluster splitting."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.clustering.hierarchical_clustering import HierarchicalClustering
from recognition.application.orchestration.split.anchor import force_anchor_split
from recognition.config import get_settings as get_recognition_settings

logger = logging.getLogger(__name__)


def build_clusters_by_label(
    identities: Sequence[MediaIdentityModel],
    *,
    n_clusters: int,
    anchor_key: str | None,
    similarity_floor: float | None = None,
    cluster_id: str | None = None,
) -> dict[int, list[MediaIdentityModel]]:
    """Cluster identities into groups for split operations."""
    hierarchical = HierarchicalClustering(distance_threshold=0.30)
    identity_list = list(identities)
    clusters_by_label = hierarchical.split_identities(identity_list, n_clusters)

    if anchor_key and n_clusters >= 2 and len(clusters_by_label) <= 1:
        clusters_by_label = force_anchor_split(
            identity_list,
            anchor_key,
            similarity_floor=similarity_floor
            if similarity_floor is not None
            else get_recognition_settings().clustering.anchor_split_similarity_floor,
        )
        if cluster_id:
            logger.info("Split cluster %s: forced anchor split for anchor=%s", cluster_id, anchor_key)
        else:
            logger.info("Split cluster: forced anchor split for anchor=%s", anchor_key)

    return clusters_by_label
