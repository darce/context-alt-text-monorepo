"""Cluster centroid maintenance.

Extracted from ``AssignmentWriter`` (Slice 9 increment 2) to give the
centroid-recompute + materialized-view-refresh concern its own cohesive home.
``AssignmentWriter`` delegates to this class to preserve its public API.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import numpy as np

from recognition.domain.repositories import ClusterRepository, MvRefreshOutcome


class CentroidMaintainer:
    """Recompute cluster centroids and refresh the centroids materialized view."""

    def __init__(self, cluster_repository: ClusterRepository) -> None:
        self._clusters = cluster_repository

    @staticmethod
    def unit_normalized_mean(embeddings: Sequence[np.ndarray]) -> np.ndarray | None:
        """Single source of truth for centroid math: stack -> mean -> divide by L2 norm.

        Returns the unit-normalized mean of ``embeddings``, or None when empty. A
        zero-norm mean is returned un-normalized (legacy behaviour preserved).
        """
        if len(embeddings) == 0:
            return None
        stacked = np.stack(list(embeddings))
        mean_vector = np.mean(stacked, axis=0)
        norm = float(np.linalg.norm(mean_vector))
        if norm > 0:
            mean_vector = mean_vector / norm
        return cast(np.ndarray, mean_vector)

    async def recompute_centroid(self, cluster_id: str) -> np.ndarray | None:
        """Recompute a cluster centroid as the unit-normalized mean of its representatives.

        Returns None if the cluster has no representatives (no centroid update).
        """
        reps = await self._clusters.get_all_representatives(cluster_id)
        if not reps:
            return None

        # Handle both raw embedding vectors and full ClusterRepresentative objects.
        rep_vecs = [cast(np.ndarray, getattr(r, "embedding", r)) for r in reps]
        return self.unit_normalized_mean(rep_vecs)

    async def refresh_centroids_view(self) -> None:
        """Trigger a refresh of the cluster centroids view (no-op if the repo lacks it)."""
        refresh = getattr(self._clusters, "refresh_centroids_view", None)
        if callable(refresh):
            await refresh()

    async def refresh_centroids_view_concurrent(self) -> MvRefreshOutcome:
        """Trigger a concurrent refresh of the centroids view."""
        refresh = getattr(self._clusters, "refresh_centroids_view_concurrent", None)
        if callable(refresh):
            return cast(MvRefreshOutcome, await refresh())
        return MvRefreshOutcome.FAILED
