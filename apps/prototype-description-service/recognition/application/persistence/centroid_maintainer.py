"""Cluster centroid maintenance.

Extracted from ``AssignmentWriter`` (Slice 9 increment 2) to give the
centroid-recompute + materialized-view-refresh concern its own cohesive home.
``AssignmentWriter`` delegates to this class to preserve its public API.
"""

from __future__ import annotations

from typing import cast

import numpy as np

from recognition.domain.repositories import ClusterRepository


class CentroidMaintainer:
    """Recompute cluster centroids and refresh the centroids materialized view."""

    def __init__(self, cluster_repository: ClusterRepository) -> None:
        self._clusters = cluster_repository

    async def recompute_centroid(self, cluster_id: str) -> np.ndarray | None:
        """Recompute a cluster centroid as the unit-normalized mean of its representatives.

        Returns None if the cluster has no representatives (no centroid update).
        """
        reps = await self._clusters.get_all_representatives(cluster_id)
        if not reps:
            return None

        # Handle both raw embedding vectors and full ClusterRepresentative objects.
        rep_vecs = [cast(np.ndarray, getattr(r, "embedding", r)) for r in reps]
        stacked = np.stack(rep_vecs)
        mean_vector = np.mean(stacked, axis=0)

        norm = np.linalg.norm(mean_vector)
        if norm > 0:
            mean_vector = mean_vector / norm

        return cast(np.ndarray, mean_vector)

    async def refresh_centroids_view(self) -> None:
        """Trigger a refresh of the cluster centroids view (no-op if the repo lacks it)."""
        refresh = getattr(self._clusters, "refresh_centroids_view", None)
        if callable(refresh):
            await refresh()

    async def refresh_centroids_view_concurrent(self) -> bool:
        """Trigger a concurrent refresh of the centroids view. True on success or if unsupported."""
        refresh = getattr(self._clusters, "refresh_centroids_view_concurrent", None)
        if callable(refresh):
            return bool(await refresh())
        return True
