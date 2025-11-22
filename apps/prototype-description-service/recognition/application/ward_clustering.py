"""Ward linkage clustering helpers."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence

from db.models import IdentityCluster, MediaIdentity
from recognition.application.clustering_settings import ClusteringSettings
from recognition.application.clustering_utils import (
    convert_threshold_to_euclidean,
    group_identities_by_label,
    normalize_embeddings,
)

logger = logging.getLogger(__name__)

CreateClusterFn = Callable[[Sequence[MediaIdentity]], Awaitable[tuple[IdentityCluster, object]]]


async def run_ward_clustering(
    identities: list[MediaIdentity],
    settings: ClusteringSettings,
    *,
    create_cluster: CreateClusterFn,
    max_identities: int | None = None,
) -> list[IdentityCluster]:
    if not identities:
        return []

    limit = max_identities or settings.ward_async_max_identities
    if len(identities) > limit:
        raise ValueError(f"Ward clustering batch too large: {len(identities)} > {limit}")

    if len(identities) == 1:
        cluster, _ = await create_cluster([identities[0]])
        return [cluster]

    try:
        from sklearn.cluster import AgglomerativeClustering
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("scikit-learn is required for Ward clustering") from exc

    embeddings = normalize_embeddings(identity.embedding for identity in identities)
    distance_threshold = convert_threshold_to_euclidean(
        settings.similarity_threshold,
        embeddings,
        atol=settings.normalization_atol,
    )

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        metric="euclidean",
        linkage="ward",
        compute_full_tree=True,
    )
    labels = clustering.fit_predict(embeddings)

    created_clusters: list[IdentityCluster] = []
    clusters_by_label = group_identities_by_label(labels, identities)

    for members in clusters_by_label.values():
        cluster, _ = await create_cluster(list(members))  # type: ignore[arg-type]
        created_clusters.append(cluster)

    logger.info(
        "Stage 2 (Ward) created %d clusters from %d identities (threshold=%.2f, distance=%.3f)",
        len(created_clusters),
        len(identities),
        settings.similarity_threshold,
        distance_threshold,
    )
    return created_clusters
