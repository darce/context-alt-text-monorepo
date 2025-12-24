"""
Centroid-based discovery for identity-to-cluster candidates.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.discovery.base import DiscoveryAlgorithm
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.similarity import normalize_face_embedding


class CentroidDiscovery(DiscoveryAlgorithm):
    """Find candidate assignments by comparing identities to cluster centroids."""

    discovery_method = DiscoveryMethod.CENTROID

    def __init__(self, settings: ClusteringSettings) -> None:
        """Initialize the centroid discovery algorithm.

        Args:
            settings: Threshold configuration for centroid matching.
        """
        self.settings = settings

    async def discover(
        self,
        identities: Sequence[MediaIdentity],
        centroids_by_cluster: dict[str, np.ndarray],
    ) -> list[AssignmentCandidate]:
        """Generate candidates by matching identities to cluster centroids.

        Args:
            identities: Identities to evaluate against centroid embeddings.
            centroids_by_cluster: Centroid embeddings keyed by cluster identifier.

        Returns:
            list[AssignmentCandidate]: Candidates suitable for gate evaluation.
        """
        candidates: list[AssignmentCandidate] = []
        for identity in identities:
            face_vec = identity.face_vector
            best_cluster, best_sim = self._find_best_centroid_match(face_vec, centroids_by_cluster)

            if best_cluster and best_sim >= self.settings.similarity_threshold:
                candidates.append(
                    AssignmentCandidate(
                        identity=identity,
                        identity_vector=face_vec,
                        cluster_id=best_cluster,
                        discovery_method=self.discovery_method,
                        discovery_similarity=best_sim,
                    )
                )

        return candidates

    def _find_best_centroid_match(
        self,
        face_vector: np.ndarray,
        centroids_by_cluster: dict[str, np.ndarray],
    ) -> tuple[str | None, float]:
        """Identify the centroid with the highest similarity to the face embedding.

        Args:
            face_vector: Face embedding prepared for similarity calculations.
            centroids_by_cluster: Centroid embeddings keyed by cluster identifier.

        Returns:
            tuple[UUID | None, float]: Best cluster identifier and similarity score.
        """

        best_cluster: str | None = None
        best_similarity = 0.0

        for cluster_id, centroid in centroids_by_cluster.items():
            centroid_vec = normalize_face_embedding(np.asarray(centroid, dtype=np.float32))
            similarity = float(np.dot(face_vector, centroid_vec))
            if similarity > best_similarity:
                best_similarity = similarity
                best_cluster = cluster_id

        return best_cluster, best_similarity
