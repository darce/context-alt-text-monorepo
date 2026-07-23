"""
Agglomerative Hierarchical Clustering for Face Recognition.

Hierarchical clustering is ideal for cluster splitting scenarios where:
1. We want to split a mixed cluster into distinct groups
2. We can visualize relationships via a dendrogram
3. We want flexibility between auto-detecting cluster count vs. forcing a specific count

Uses scipy's linkage with average linkage and cosine distance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from db.models import MediaIdentity

logger = logging.getLogger(__name__)


class HierarchicalClustering:
    """
    Implements Agglomerative Hierarchical Clustering for face embeddings.

    This is particularly useful for splitting mixed clusters where we want
    to use dendrogram-based analysis to find natural groupings.
    """

    def __init__(
        self,
        distance_threshold: float = 0.30,
        linkage_method: str = "average",
    ) -> None:
        """
        Initialize hierarchical clustering.

        Args:
            distance_threshold: Distance threshold for auto-detecting clusters.
                               A distance of 0.30 = similarity of 0.70.
            linkage_method: Linkage method for scipy. Options: 'single', 'complete',
                           'average', 'weighted', 'centroid', 'median', 'ward'.
                           'average' is recommended for face clustering.
        """
        self.distance_threshold = distance_threshold
        self.linkage_method = linkage_method

    def cluster_embeddings(
        self,
        embeddings: np.ndarray,
        n_clusters: int = 0,
        job_id: UUID | None = None,
    ) -> np.ndarray:
        """
        Cluster embeddings using hierarchical clustering.

        Args:
            embeddings: Numpy array of shape (n_samples, n_features).
                       Should be L2-normalized for cosine distance.
            n_clusters: Number of clusters to split into.
                       0 = auto-detect based on distance threshold (default).
                       2+ = force exactly this many clusters.
            job_id: Optional job ID for log correlation.

        Returns:
            Array of cluster labels (0-indexed) for each embedding.
        """
        log_prefix = f"[job={job_id}] " if job_id else ""

        if len(embeddings) < 2:
            return np.array([0] * len(embeddings))

        # Build linkage matrix using cosine distance
        linkage_matrix = linkage(
            embeddings,
            method=self.linkage_method,
            metric="cosine",
        )

        # Cut dendrogram - either at fixed n_clusters or by distance threshold
        if n_clusters >= 2:
            labels = fcluster(linkage_matrix, t=n_clusters, criterion="maxclust")
            logger.info(
                "%sHierarchical clustering: Using fixed n_clusters=%d",
                log_prefix,
                n_clusters,
            )
        else:
            labels = fcluster(
                linkage_matrix,
                t=self.distance_threshold,
                criterion="distance",
            )
            n_found = len(set(labels))
            logger.info(
                "%sHierarchical clustering: Auto-detected %d clusters (distance_threshold=%.2f)",
                log_prefix,
                n_found,
                self.distance_threshold,
            )

        # fcluster labels are 1-indexed, convert to 0-indexed
        labels = labels - 1

        return np.asarray(labels)

    def split_identities(
        self,
        identities: list[MediaIdentity],
        n_clusters: int = 0,
        job_id: UUID | None = None,
    ) -> dict[int, list[MediaIdentity]]:
        """
        Split identities into groups using hierarchical clustering.

        Args:
            identities: List of MediaIdentity objects to split.
            n_clusters: Number of clusters (0 = auto-detect).
            job_id: Optional job ID for log correlation.

        Returns:
            Dictionary mapping cluster label to list of identities.
        """
        log_prefix = f"[job={job_id}] " if job_id else ""

        if not identities:
            return {}

        if len(identities) == 1:
            return {0: identities}

        # FIR23-05 / FIR23-01: never mix embedding spaces in a split. Single-model
        # input is a no-op; mixed → majority model (lex tie-break); null embeddings
        # are quality-dropped and counted in the log.
        usable: list[MediaIdentity] = []
        dropped_null_embedding = 0
        for identity in identities:
            emb = getattr(identity, "embedding", None)
            if emb is None:
                dropped_null_embedding += 1
                continue
            usable.append(identity)
        if dropped_null_embedding:
            logger.info(
                "%sHierarchical split: dropped %d identities with null embedding (quality drop)",
                log_prefix,
                dropped_null_embedding,
            )
        models = [
            str(getattr(identity, "embedding_model", None) or "")
            for identity in usable
            if getattr(identity, "embedding_model", None)
        ]
        distinct_models = {m for m in models if m}
        if len(distinct_models) > 1:
            counts: dict[str, int] = {}
            for model in models:
                counts[model] = counts.get(model, 0) + 1
            chosen = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
            before = len(usable)
            usable = [
                identity
                for identity in usable
                if str(getattr(identity, "embedding_model", None) or "") == chosen
            ]
            logger.info(
                "%sHierarchical split: mixed embedding_model; kept model=%s dropped=%d",
                log_prefix,
                chosen,
                before - len(usable),
            )
        if not usable:
            return {}
        if len(usable) == 1:
            return {0: usable}
        identities = usable

        # Extract embeddings
        embeddings = np.array([id.embedding for id in identities])

        # Log pairwise similarities for debugging (only for small clusters)
        if len(embeddings) <= 10:
            min_sim = 1.0
            max_sim = 0.0
            for i in range(len(embeddings)):
                for j in range(i + 1, len(embeddings)):
                    sim = float(np.dot(embeddings[i], embeddings[j]))
                    min_sim = min(min_sim, sim)
                    max_sim = max(max_sim, sim)
            logger.info(
                "%sHierarchical split: %d identities, similarity range [%.4f, %.4f]",
                log_prefix,
                len(embeddings),
                min_sim,
                max_sim,
            )

        # Cluster
        labels = self.cluster_embeddings(embeddings, n_clusters, job_id)

        logger.info(
            "%sHierarchical split: labels=%s",
            log_prefix,
            labels.tolist(),
        )

        # Group by label
        clusters_by_label: dict[int, list[MediaIdentity]] = {}
        for identity, label in zip(identities, labels, strict=True):
            clusters_by_label.setdefault(int(label), []).append(identity)

        return clusters_by_label

    def compute_similarity_matrix(self, embeddings: np.ndarray) -> np.ndarray:
        """
        Compute pairwise cosine similarity matrix.

        Args:
            embeddings: Numpy array of shape (n_samples, n_features).

        Returns:
            Similarity matrix of shape (n_samples, n_samples).
        """
        # Ensure embeddings are normalized
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalized = embeddings / np.where(norms > 0, norms, 1.0)

        return np.asarray(np.dot(normalized, normalized.T))
