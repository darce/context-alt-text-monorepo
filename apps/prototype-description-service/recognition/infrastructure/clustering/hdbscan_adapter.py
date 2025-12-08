"""
GraphAlgorithm adapter using HDBSCAN for cluster discovery.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from recognition.application.discovery.graph import GraphAlgorithm
from recognition.domain.identity import MediaIdentity


class HdbscanGraphAlgorithm(GraphAlgorithm):
    """Run HDBSCAN clustering and return integer labels for embeddings."""

    def __init__(
        self,
        min_cluster_size: int = 2,
        min_samples: int = 1,
        metric: str = "euclidean",
        cluster_selection_epsilon: float = 0.12,
    ) -> None:
        """Initialize the HDBSCAN algorithm parameters.

        Args:
            min_cluster_size: Minimum size of clusters.
            min_samples: Minimum samples parameter for HDBSCAN.
            metric: Distance metric to use.
            cluster_selection_epsilon: Cluster selection epsilon parameter (distance space).
        """
        self.min_cluster_size = min_cluster_size
        self.min_samples = min_samples
        self.metric = metric
        self.cluster_selection_epsilon = cluster_selection_epsilon

    def cluster(
        self,
        embeddings: Sequence[np.ndarray],
        identities: Sequence[MediaIdentity] | None = None,
    ) -> list[int]:
        """Cluster embeddings with HDBSCAN and return labels.

        Args:
            embeddings: Sequence of embedding vectors.
            identities: Unused; kept for interface compatibility.

        Returns:
            list[int]: Cluster labels, -1 for noise points.
        """
        try:
            import hdbscan
        except Exception as exc:  # pragma: no cover - dependency may be missing in dev
            raise RuntimeError(
                "hdbscan is not installed. Install with the 'clustering' extra to enable HDBSCAN clustering."
            ) from exc

        data = np.array(embeddings, dtype=np.float32)
        if data.size == 0:
            return []

        # HDBSCAN requires at least min_cluster_size samples to form a cluster
        # and will fail if k (min_samples) exceeds the number of points
        if len(data) < self.min_cluster_size:
            # With fewer samples than min_cluster_size, all points are noise
            return [-1] * len(data)

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            metric=self.metric,
            cluster_selection_epsilon=self.cluster_selection_epsilon,
        )
        labels = clusterer.fit_predict(data)
        return [int(label) for label in labels]
