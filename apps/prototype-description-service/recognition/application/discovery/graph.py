"""
Graph-based discovery (HDBSCAN/Chinese Whispers) for assignment candidates.
"""

from __future__ import annotations

import importlib.util
import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.discovery.base import DiscoveryAlgorithm
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.similarity import extract_face_embedding


@dataclass
class AnchorIdentity:
    """Lightweight wrapper for anchor nodes."""

    id: str
    cluster_id: str
    confidence: float = 1.0


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
        inject_anchors: bool = True,
    ) -> GraphDiscoveryResult:
        """Generate candidates and new-cluster groups via graph algorithms.

        Args:
            identities: Identities to cluster using graph algorithms.
            anchor_embeddings: Optional representative embeddings keyed by cluster.
            inject_anchors: If True, inject representatives as anchor nodes into the graph.

        Returns:
            GraphDiscoveryResult: Matched candidates and unmatched cluster groups.
        """
        if not identities:
            return GraphDiscoveryResult([], [])
        if not isinstance(anchor_embeddings, dict):
            anchor_embeddings = {}

        # 1. Prepare Inputs
        anchors: list[AnchorIdentity] = []
        anchor_vecs: list[np.ndarray] = []

        if inject_anchors:
            for cluster_id, reps in anchor_embeddings.items():
                for rep in reps:
                    # Create a unique ID for the anchor node to ensure stability
                    # We use a deterministic namespace if possible, or just random
                    anchor = AnchorIdentity(
                        id=f"anchor-{uuid.uuid4()}",
                        cluster_id=cluster_id,
                    )
                    anchors.append(anchor)
                    anchor_vecs.append(self._normalize_face(np.asarray(rep, dtype=np.float32)))

        # Combine new identities with anchors
        face_vectors = [
            self._normalize_face(np.asarray(identity.embedding, dtype=np.float32)) for identity in identities
        ]

        # Combined lists for the algorithm
        # Note: We must cast AnchorIdentity to Any or a compatible Protocol if strictly typed,
        # but Python is dynamic. AnchorIdentity has .id and .confidence, satisfying CW/HDBSCAN usage.
        combined_identities = list(identities) + anchors
        combined_vectors = face_vectors + anchor_vecs

        # 2. Run Clustering
        algorithm = self._select_algorithm(len(combined_identities))
        labels = algorithm.cluster(combined_vectors, cast(list[MediaIdentity], combined_identities))

        if len(labels) != len(combined_identities):
            raise ValueError("Graph algorithm returned mismatched labels")

        # 3. Group and Resolve
        grouped = self._group_by_label(combined_identities, combined_vectors, labels)

        candidates: list[AssignmentCandidate] = []
        new_clusters: list[tuple[list[MediaIdentity], list[float]]] = []

        for _label, items in grouped.items():
            # Separate anchors and new members
            group_anchors = [item for item, _ in items if isinstance(item, AnchorIdentity)]
            # Use type check or list comprehension to filter MediaIdentity
            new_members_with_vecs = [(item, vec) for item, vec in items if isinstance(item, MediaIdentity)]

            if not new_members_with_vecs:
                continue

            new_members = [m for m, _ in new_members_with_vecs]
            member_vectors_group = [v for _, v in new_members_with_vecs]

            target_cluster_id: str | None = None
            similarity = 0.0

            if group_anchors:
                # Connected to existing cluster(s) via anchors
                target_cluster_id = self._resolve_anchor_conflict(group_anchors)
                # Compute avg similarity to the matched anchors for the score
                # OR compute similarity to the specific matched cluster's anchors in the group
                matched_anchor_vecs = [
                    v for item, v in items if isinstance(item, AnchorIdentity) and item.cluster_id == target_cluster_id
                ]
                similarity = self._compute_avg_similarity(member_vectors_group, matched_anchor_vecs)
            else:
                # Fallback: Try centroid matching for components with NO anchors
                # This covers cases where inject_anchors=False OR no anchors ended up in this component
                # (though with inject_anchors=True, if they were close enough, they should have merged)
                if not inject_anchors and anchor_embeddings:
                    target_cluster_id, similarity = self._match_to_anchor(member_vectors_group, anchor_embeddings)

            # 4. Generate Output
            # Use lower threshold for anchor-linked groups (transitivity already established the link)
            threshold = (
                self.settings.anchor_discovery_threshold if group_anchors else self.settings.similarity_threshold
            )
            if target_cluster_id and similarity >= threshold:
                for member, member_vec in new_members_with_vecs:
                    candidates.append(
                        AssignmentCandidate(
                            identity=member,
                            identity_vector=member_vec,
                            cluster_id=target_cluster_id,
                            discovery_method=self.discovery_method,
                            discovery_similarity=similarity,
                            anchor_linked=bool(group_anchors),  # Trust transitivity
                        )
                    )

            else:
                # New Cluster
                member_sims = self._compute_member_similarities(member_vectors_group)
                new_clusters.append((new_members, member_sims))

        # Handle noise points: when no anchors matched (new cluster formation mode),
        # create singleton clusters for each noise identity
        # NOTE: HDBSCAN labels noise as -1. Our _group_by_label skips -1.
        # We need to look for identities that got label -1.

        # Re-scan labels for noise
        # Since _group_by_label skips -1, we can just find them in the original lists
        # or rely on _group_by_label to NOT skip them?
        # The existing code skipped -1. Let's keep that logic but handle singletons.

        # Actually, let's look at how _group_by_label was implemented.
        # It skipped -1.
        # If we have noise, we likely want to propose them as singletons OR ignore them?
        # Existing logic: "if not anchor_embeddings and noise_identities: create singleton"

        noise_identities = [
            (identity, face_vec)
            for identity, face_vec, label in zip(combined_identities, combined_vectors, labels, strict=False)
            if label == -1 and isinstance(identity, MediaIdentity)
        ]

        if noise_identities and anchor_embeddings:
            # Try to match noise points to existing anchors before creating singletons.
            # This reduces false negatives when HDBSCAN marks points as noise.
            for identity, face_vec in noise_identities:
                best_cluster, best_sim = self._match_single_to_anchors(face_vec, anchor_embeddings)
                if best_cluster and best_sim >= self.settings.anchor_discovery_threshold:
                    # Matched to existing cluster via anchor
                    candidates.append(
                        AssignmentCandidate(
                            identity=identity,
                            identity_vector=face_vec,
                            cluster_id=best_cluster,
                            discovery_method=self.discovery_method,
                            discovery_similarity=best_sim,
                            anchor_linked=True,  # Trust anchor transitivity
                        )
                    )
                else:
                    # No anchor match - create singleton
                    new_clusters.append(([identity], [1.0]))
        elif noise_identities:
            # No anchors available - all noise becomes singletons
            for identity, _ in noise_identities:
                new_clusters.append(([identity], [1.0]))

        return GraphDiscoveryResult(candidates, new_clusters)

    def _resolve_anchor_conflict(self, anchors: list[AnchorIdentity]) -> str:
        """Resolve which cluster to assign when multiple anchors are present.

        Strategy: Majority vote.
        """
        counts: dict[str, int] = {}
        for anchor in anchors:
            counts[anchor.cluster_id] = counts.get(anchor.cluster_id, 0) + 1

        # Return cluster with most anchors in this component
        return max(counts, key=lambda k: counts.get(k, 0))

    def _compute_avg_similarity(self, members: list[np.ndarray], anchors: list[np.ndarray]) -> float:
        """Compute average similarity between members and anchors."""
        if not members or not anchors:
            return 0.0

        # Centroid of members
        member_centroid = self._normalize(np.mean(np.stack(members), axis=0))
        # Centroid of anchors
        anchor_centroid = self._normalize(np.mean(np.stack(anchors), axis=0))

        return float(np.dot(member_centroid, anchor_centroid))

    def _group_by_label(
        self,
        identities: Sequence[MediaIdentity | AnchorIdentity],
        face_vectors: Sequence[np.ndarray],
        labels: Sequence[int],
    ) -> dict[int, list[tuple[MediaIdentity | AnchorIdentity, np.ndarray]]]:
        """Group identities and face embeddings by cluster label, skipping noise."""
        grouped: dict[int, list[tuple[MediaIdentity | AnchorIdentity, np.ndarray]]] = {}
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
            # Convert cosine similarity threshold to euclidean distance for normalized vectors.
            # For unit vectors: euclidean_distance = sqrt(2 * (1 - cosine_similarity))
            # This ensures HDBSCAN clusters faces that would pass our similarity threshold.
            import math

            from recognition.infrastructure.clustering import HdbscanGraphAlgorithm

            target_cosine = float(self.settings.similarity_threshold)
            epsilon = math.sqrt(2.0 * (1.0 - target_cosine))
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

    def _match_single_to_anchors(
        self,
        face_vec: np.ndarray,
        anchor_embeddings: dict[str, list[np.ndarray]],
    ) -> tuple[str | None, float]:
        """Match a single noise point to existing anchor clusters.

        Args:
            face_vec: Face embedding for the noise point.
            anchor_embeddings: Representative embeddings keyed by cluster identifier.

        Returns:
            tuple[str | None, float]: Best anchor cluster and similarity score.
        """
        best_anchor: str | None = None
        best_similarity = 0.0

        for anchor_id, reps in anchor_embeddings.items():
            if not reps:
                continue
            # Find best match among this cluster's representatives
            for rep in reps:
                rep_vec = self._normalize_face(np.asarray(rep, dtype=np.float32))
                sim = float(np.dot(face_vec, rep_vec))
                if sim > best_similarity:
                    best_similarity = sim
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
