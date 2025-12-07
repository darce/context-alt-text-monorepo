"""
Representative-based discovery for identity-to-cluster candidates.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.discovery.base import DiscoveryAlgorithm
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.similarity import extract_face_embedding


class RepresentativeDiscovery(DiscoveryAlgorithm):
    """Find candidate assignments by comparing identities to representatives."""

    discovery_method = DiscoveryMethod.REPRESENTATIVE

    def __init__(self, settings: ClusteringSettings) -> None:
        """Initialize the representative discovery algorithm.

        Args:
            settings: Threshold configuration for representative matching.
        """
        self.settings = settings

    async def discover(
        self,
        identities: Sequence[MediaIdentity],
        representatives_by_cluster: object,
    ) -> list[AssignmentCandidate]:
        """Generate candidates by matching against cluster representatives.

        Args:
            identities: Identities to evaluate against representatives.
            representatives_by_cluster: Representative embeddings keyed by cluster.

        Returns:
            list[AssignmentCandidate]: Candidates suitable for gate evaluation.

        Raises:
            NotImplementedError: Always, until discovery logic is implemented.
        """
        if not isinstance(representatives_by_cluster, dict):
            return []

        candidates: list[AssignmentCandidate] = []
        for identity in identities:
            face_vec = self._normalize_face(np.asarray(identity.embedding, dtype=np.float32))
            best_cluster, best_sim = self._find_best_match(face_vec, representatives_by_cluster)
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

    def _find_best_match(
        self,
        face_vector: np.ndarray,
        representatives_by_cluster: dict[str, list[np.ndarray]],
    ) -> tuple[str | None, float]:
        """Identify the best matching cluster for a face embedding.

        Args:
            face_vector: Face embedding prepared for similarity calculations.
            representatives_by_cluster: Representative embeddings grouped by cluster.

        Returns:
            tuple[UUID | None, float]: Best cluster identifier and similarity score.

        """
        best_cluster: str | None = None
        best_similarity = 0.0

        for cluster_id, representatives in representatives_by_cluster.items():
            for rep in representatives:
                rep_vec = self._normalize_face(np.asarray(rep, dtype=np.float32))
                similarity = float(np.dot(face_vector, rep_vec))
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
