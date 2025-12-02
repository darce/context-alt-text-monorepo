"""
HDBSCAN Clustering for Face Recognition.

HDBSCAN (Hierarchical Density-Based Spatial Clustering of Applications with Noise)
is better than Chinese Whispers for small-to-medium batches (≤500 identities) because:
1. It handles varying density clusters (different quality embeddings)
2. It explicitly identifies outliers instead of forcing assignments
3. It produces more stable, reproducible results

For large batches (>500), Chinese Whispers remains preferred due to O(E) vs O(n²) complexity.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeAlias
from uuid import UUID

import numpy as np

try:
    import hdbscan as hdbscan_lib  # type: ignore[import-untyped]
except ImportError:
    hdbscan_lib = None

from db.models import IdentityCluster, MediaIdentity
from recognition.application.clustering.clustering_settings import ClusteringSettings

logger = logging.getLogger(__name__)

CreateClusterFn: TypeAlias = Callable[[Sequence[MediaIdentity]], Awaitable[tuple[IdentityCluster, object]]]
AddToClusterFn: TypeAlias = Callable[[UUID, Sequence[MediaIdentity]], Awaitable[None]]

# Type alias for anchor embeddings: cluster_id -> list of representative embeddings
AnchorEmbeddings: TypeAlias = dict[UUID, list[np.ndarray]]


class HDBSCANClustering:
    """
    Implements HDBSCAN clustering for face embeddings.

    HDBSCAN is a density-based clustering algorithm that:
    - Finds clusters of varying densities
    - Explicitly labels outliers as noise (-1)
    - Does not require a predefined number of clusters
    """

    def __init__(self, settings: ClusteringSettings, adaptive_threshold: float | None = None) -> None:
        if hdbscan_lib is None:
            raise ImportError("hdbscan package is required for HDBSCANClustering. Install with: pip install hdbscan")

        self.settings = settings
        self.min_cluster_size = settings.hdbscan_min_cluster_size
        self.min_samples = settings.hdbscan_min_samples
        self.adaptive_threshold = adaptive_threshold

        # Compute cluster_selection_epsilon from adaptive threshold
        # Higher similarity threshold → lower distance epsilon
        # For normalized embeddings: distance = 1 - similarity
        effective_sim = adaptive_threshold if adaptive_threshold else settings.similarity_threshold
        self.cluster_selection_epsilon = 1.0 - effective_sim  # e.g., 0.88 sim → 0.12 distance

    async def cluster(
        self,
        identities: list[MediaIdentity],
        create_cluster: CreateClusterFn,
        anchor_embeddings: AnchorEmbeddings | None = None,
        add_to_cluster: AddToClusterFn | None = None,
        job_id: UUID | None = None,
    ) -> list[IdentityCluster]:
        """
        Cluster identities using HDBSCAN.

        Args:
            identities: New identities to cluster.
            create_cluster: Callback to create new clusters.
            anchor_embeddings: Optional dict mapping cluster_id to representative embeddings.
                              Used to match new clusters to existing clusters.
            add_to_cluster: Optional callback to add members to existing clusters.
            job_id: Optional job ID for log correlation.

        Returns:
            List of newly created clusters (outliers become singletons).
        """
        log_prefix = f"[job={job_id}] " if job_id else ""
        if not identities:
            return []

        if len(identities) == 1:
            cluster, _ = await create_cluster([identities[0]])
            return [cluster]

        # Build embedding matrix
        embeddings = np.array(
            [np.array(ident.embedding, dtype=np.float32) for ident in identities],
            dtype=np.float32,
        )

        # Ensure embeddings are normalized (they should be from InsightFace)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / np.where(norms > 0, norms, 1.0)

        # Convert to distance matrix (HDBSCAN uses distances, not similarities)
        # For normalized embeddings: distance = 1 - cosine_similarity = 1 - dot_product
        similarity_matrix = np.dot(embeddings, embeddings.T)
        distance_matrix = 1.0 - similarity_matrix

        # HDBSCAN requires float64 - convert from float32
        distance_matrix = distance_matrix.astype(np.float64)

        # Clip distances and ensure valid values for HDBSCAN
        # Also add small epsilon to diagonal to avoid numerical issues
        distance_matrix = np.clip(distance_matrix, 0.0, 2.0)
        np.fill_diagonal(distance_matrix, 0.0)  # Ensure diagonal is exactly 0

        # Check for NaN/Inf values
        if np.any(~np.isfinite(distance_matrix)):
            logger.warning(
                "%sHDBSCAN: Distance matrix contains NaN/Inf, falling back to Chinese Whispers",
                log_prefix,
            )
            from recognition.application.clustering.chinese_whispers import ChineseWhispersClustering

            fallback = ChineseWhispersClustering(self.settings, adaptive_threshold=self.adaptive_threshold)
            return await fallback.cluster(identities, create_cluster, anchor_embeddings, add_to_cluster, job_id)

        # Run HDBSCAN with cluster_selection_epsilon for stricter/looser clustering
        try:
            clusterer = hdbscan_lib.HDBSCAN(
                min_cluster_size=self.min_cluster_size,
                min_samples=self.min_samples,
                metric="precomputed",
                cluster_selection_method="eom",  # Excess of Mass - better for varying densities
                cluster_selection_epsilon=self.cluster_selection_epsilon,  # Respects adaptive threshold
            )
            labels = clusterer.fit_predict(distance_matrix)
        except Exception as e:
            logger.warning(
                "%sHDBSCAN failed with error: %s, falling back to Chinese Whispers",
                log_prefix,
                str(e),
            )
            from recognition.application.clustering.chinese_whispers import ChineseWhispersClustering

            fallback = ChineseWhispersClustering(self.settings, adaptive_threshold=self.adaptive_threshold)
            return await fallback.cluster(identities, create_cluster, anchor_embeddings, add_to_cluster, job_id)

        # Log results
        unique_labels = set(labels)
        n_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)
        n_outliers = sum(1 for label in labels if label == -1)
        logger.info(
            "%sHDBSCAN: %d identities → %d clusters, %d outliers (min_cluster_size=%d, min_samples=%d, eps=%.4f)",
            log_prefix,
            len(identities),
            n_clusters,
            n_outliers,
            self.min_cluster_size,
            self.min_samples,
            self.cluster_selection_epsilon,
        )

        # Group by label
        clusters_by_label: dict[int, list[MediaIdentity]] = {}
        outliers: list[MediaIdentity] = []

        for identity, label in zip(identities, labels, strict=True):
            if label == -1:
                outliers.append(identity)
            else:
                clusters_by_label.setdefault(label, []).append(identity)

        # Try to match clusters to anchors first
        created_clusters: list[IdentityCluster] = []
        anchor_embeddings = anchor_embeddings or {}

        if anchor_embeddings and add_to_cluster:
            for label, members in list(clusters_by_label.items()):
                # Compute cluster centroid
                member_embeddings = np.array([np.array(m.embedding, dtype=np.float32) for m in members])
                centroid = member_embeddings.mean(axis=0)
                norm = np.linalg.norm(centroid)
                if norm > 0:
                    centroid = centroid / norm

                # Find best anchor match
                best_anchor_id: UUID | None = None
                best_similarity = 0.0

                for cluster_id, reps in anchor_embeddings.items():
                    for rep in reps:
                        sim = float(np.dot(centroid, rep))
                        if sim > best_similarity:
                            best_similarity = sim
                            best_anchor_id = cluster_id

                # If good match, add to existing cluster
                # Use adaptive threshold if set, otherwise base threshold
                effective_threshold = self.adaptive_threshold or self.settings.similarity_threshold
                if best_anchor_id and best_similarity >= effective_threshold:
                    logger.info(
                        "%sHDBSCAN cluster (label=%d, %d members) → anchor %s (sim=%.4f, threshold=%.4f)",
                        log_prefix,
                        label,
                        len(members),
                        best_anchor_id,
                        best_similarity,
                        effective_threshold,
                    )
                    await add_to_cluster(best_anchor_id, members)
                    del clusters_by_label[label]

        # Create new clusters for remaining groups
        for label, members in clusters_by_label.items():
            cluster, _ = await create_cluster(members)
            created_clusters.append(cluster)
            media_ids = [str(m.media_id) for m in members]
            logger.info(
                "%sHDBSCAN created cluster %s from label=%d (%d members): media_ids=[%s]",
                log_prefix,
                cluster.id,
                label,
                len(members),
                ", ".join(media_ids),
            )

        # Outliers become singleton clusters
        for outlier in outliers:
            cluster, _ = await create_cluster([outlier])
            created_clusters.append(cluster)
            logger.debug(
                "%sHDBSCAN outlier (media_id=%s) → singleton cluster %s", log_prefix, outlier.media_id, cluster.id
            )

        logger.info(
            "%sHDBSCAN complete: %d new clusters, %d singletons from outliers",
            log_prefix,
            len(created_clusters) - len(outliers),
            len(outliers),
        )

        return created_clusters
