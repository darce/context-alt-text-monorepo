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
from recognition.shared.similarity import extract_face_embedding


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
        centroids_by_cluster: object,
    ) -> list[AssignmentCandidate]:
        """Generate candidates by matching identities to cluster centroids.

        Args:
            identities: Identities to evaluate against centroid embeddings.
            centroids_by_cluster: Centroid embeddings keyed by cluster identifier.

        Returns:
            list[AssignmentCandidate]: Candidates suitable for gate evaluation.
        """
        if not isinstance(centroids_by_cluster, dict):
            return []

        candidates: list[AssignmentCandidate] = []
        for identity in identities:
            face_vec = self._normalize_face(np.asarray(identity.embedding, dtype=np.float32))
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
            centroid_vec = self._normalize_face(np.asarray(centroid, dtype=np.float32))
            similarity = float(np.dot(face_vector, centroid_vec))
            if similarity > best_similarity:
                best_similarity = similarity
                best_cluster = cluster_id

        return best_cluster, best_similarity

    def _normalize_face(self, embedding: np.ndarray) -> np.ndarray:
        """Extract the 512D face embedding and normalize to unit length."""
        return self._normalize(extract_face_embedding(embedding))

    @staticmethod
    def _normalize(vector: np.ndarray) -> np.ndarray:
        """Return normalized copy of the vector."""
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return vector.astype(np.float32)
        return vector.astype(np.float32) / norm
