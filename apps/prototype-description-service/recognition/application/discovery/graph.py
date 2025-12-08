"""
Graph-based discovery (HDBSCAN/Chinese Whispers) for assignment candidates.
"""

from __future__ import annotations

import importlib.util
from abc import ABC, abstractmethod
from collections.abc import Sequence

import numpy as np

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.discovery.base import DiscoveryAlgorithm
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.similarity import extract_face_embedding


class GraphDiscoveryResult:
    """Result of graph discovery including matched candidates and new clusters."""

    def __init__(
        self,
        candidates: list[AssignmentCandidate],
        new_clusters: list[tuple[list[MediaIdentity], list[float]]],
    ) -> None:
        self.candidates = candidates
        self.new_clusters = new_clusters


class GraphAlgorithm(ABC):
    """Interface for graph clustering algorithms."""

    @abstractmethod
    def cluster(
        self,
        embeddings: Sequence[np.ndarray],
        identities: Sequence[MediaIdentity] | None = None,
    ) -> list[int]:
        """Cluster embeddings and return integer labels."""
        raise NotImplementedError("TODO: Implement graph clustering")


class GraphDiscovery(DiscoveryAlgorithm):
    """Find candidate assignments via graph clustering outputs."""

    discovery_method = DiscoveryMethod.GRAPH

    def __init__(
        self,
        settings: ClusteringSettings,
        algorithm: GraphAlgorithm | None = None,
    ) -> None:
        """Initialize the graph discovery algorithm.

        Args:
            settings: Threshold configuration for graph-based discovery.
            algorithm: Optional graph clustering algorithm implementation.
        """
        self.settings = settings
        self.algorithm = algorithm

    def set_algorithm(self, algorithm: GraphAlgorithm) -> None:
        """Set the clustering algorithm implementation to use.

        Args:
            algorithm: Graph clustering implementation.
        """
        self.algorithm = algorithm

    async def discover(
        self,
        identities: Sequence[MediaIdentity],
        anchor_embeddings: object,
    ) -> GraphDiscoveryResult:
        """Generate candidates and new-cluster groups via graph algorithms.

        Args:
            identities: Identities to cluster using graph algorithms.
            anchor_embeddings: Optional representative embeddings keyed by cluster.

        Returns:
            GraphDiscoveryResult: Matched candidates and unmatched cluster groups.
        """
        if not identities:
            return GraphDiscoveryResult([], [])
        if not isinstance(anchor_embeddings, dict):
            anchor_embeddings = {}

        algorithm = self._select_algorithm(len(identities))
        face_vectors = [
            self._normalize_face(np.asarray(identity.embedding, dtype=np.float32)) for identity in identities
        ]
        labels = algorithm.cluster(face_vectors, identities)
        if len(labels) != len(identities):
            raise ValueError("Graph algorithm returned mismatched labels")

        grouped = self._group_by_label(identities, face_vectors, labels)

        # Collect noise points (label == -1) for special handling
        noise_identities = [
            (identity, face_vec)
            for identity, face_vec, label in zip(identities, face_vectors, labels, strict=False)
            if label == -1
        ]

        candidates: list[AssignmentCandidate] = []
        new_clusters: list[tuple[list[MediaIdentity], list[float]]] = []
        for items in grouped.values():
            member_vectors = [vec for _, vec in items]
            anchor_cluster, similarity = self._match_to_anchor(member_vectors, anchor_embeddings)
            if anchor_cluster and similarity >= self.settings.similarity_threshold:
                for member, member_vec in items:
                    candidates.append(
                        AssignmentCandidate(
                            identity=member,
                            identity_vector=member_vec,
                            cluster_id=anchor_cluster,
                            discovery_method=self.discovery_method,
                            discovery_similarity=similarity,
                        )
                    )
            else:
                members = [member for member, _ in items]
                member_sims = self._compute_member_similarities(member_vectors)
                new_clusters.append((members, member_sims))

        # Handle noise points: when no anchors are provided (new cluster formation mode),
        # create singleton clusters for each noise identity
        if not anchor_embeddings and noise_identities:
            for identity, _face_vec in noise_identities:
                new_clusters.append(([identity], [1.0]))

        return GraphDiscoveryResult(candidates, new_clusters)

    def _group_by_label(
        self,
        identities: Sequence[MediaIdentity],
        face_vectors: Sequence[np.ndarray],
        labels: Sequence[int],
    ) -> dict[int, list[tuple[MediaIdentity, np.ndarray]]]:
        """Group identities and face embeddings by cluster label, skipping noise."""
        grouped: dict[int, list[tuple[MediaIdentity, np.ndarray]]] = {}
        for identity, face_vec, label in zip(identities, face_vectors, labels, strict=False):
            if label == -1:
                continue
            grouped.setdefault(label, []).append((identity, face_vec))
        return grouped

    def _select_algorithm(self, identities_count: int) -> GraphAlgorithm:
        """Choose clustering algorithm based on batch size and configuration."""
        if self.algorithm is not None:
            return self.algorithm

        hdbscan_limit = self.settings.hdbscan_max_batch_size or 500
        if identities_count <= hdbscan_limit and self._hdbscan_available():
            from recognition.infrastructure.clustering import HdbscanGraphAlgorithm

            epsilon = max(0.0, 1.0 - float(self.settings.similarity_threshold))
            return HdbscanGraphAlgorithm(
                min_cluster_size=2,
                min_samples=1,
                cluster_selection_epsilon=epsilon,
            )

        from recognition.infrastructure.clustering import DeterministicChineseWhispers

        return DeterministicChineseWhispers(threshold=float(self.settings.similarity_threshold))

    @staticmethod
    def _hdbscan_available() -> bool:
        """Check if the optional hdbscan dependency is installed."""
        return importlib.util.find_spec("hdbscan") is not None

    def _match_to_anchor(
        self,
        member_vectors: Sequence[np.ndarray],
        anchor_embeddings: dict[str, list[np.ndarray]],
    ) -> tuple[str | None, float]:
        """Match a clustered group to an existing anchor cluster.

        Args:
            member_vectors: Face embeddings for members in the clustered group.
            anchor_embeddings: Representative embeddings keyed by cluster identifier.

        Returns:
            tuple[UUID | None, float]: Best anchor cluster and similarity score.
        """

        best_anchor: str | None = None
        best_similarity = 0.0

        for anchor_id, reps in anchor_embeddings.items():
            if not reps:
                continue
            anchor_vecs = [self._normalize_face(np.asarray(rep, dtype=np.float32)) for rep in reps]
            anchor_mean = self._normalize(np.mean(anchor_vecs, axis=0))

            sims = [float(np.dot(vec, anchor_mean)) for vec in member_vectors]
            avg_sim = float(sum(sims) / len(sims))

            if avg_sim > best_similarity:
                best_similarity = avg_sim
                best_anchor = anchor_id

        return best_anchor, best_similarity

    def _normalize_face(self, embedding: np.ndarray) -> np.ndarray:
        """Extract the face embedding portion and normalize to unit length."""
        return self._normalize(extract_face_embedding(embedding))

    @staticmethod
    def _normalize(vector: np.ndarray) -> np.ndarray:
        """Return normalized copy of the vector."""
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return vector.astype(np.float32)
        return vector.astype(np.float32) / norm

    def _compute_member_similarities(self, member_vectors: Sequence[np.ndarray]) -> list[float]:
        """Compute similarity of each member to the group centroid."""
        if not member_vectors:
            return []
        centroid = self._normalize(np.mean(np.stack(member_vectors, axis=0), axis=0))
        return [float(np.dot(vec, centroid)) for vec in member_vectors]
