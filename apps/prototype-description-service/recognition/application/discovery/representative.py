"""
Representative-based discovery for identity-to-cluster candidates.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.discovery.base import DiscoveryAlgorithm
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.similarity import normalize_face_embedding

logger = logging.getLogger(__name__)


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
        representatives_by_cluster: dict[str, list[np.ndarray]],
        labeled_cluster_ids: set[str] | None = None,
    ) -> list[AssignmentCandidate]:
        """Generate candidates by matching against cluster representatives.

        Args:
            identities: Identities to evaluate against representatives.
            representatives_by_cluster: Representative embeddings keyed by cluster.
            labeled_cluster_ids: Set of cluster IDs that have user-provided labels.
                               Used to prioritize labeled clusters for suggestions.

        Returns:
            list[AssignmentCandidate]: Candidates suitable for gate evaluation.

        Raises:
            NotImplementedError: Always, until discovery logic is implemented.
        """
        labeled_ids = labeled_cluster_ids or set()
        total_reps = sum(len(reps) for reps in representatives_by_cluster.values())
        logger.info(
            "[RepresentativeDiscovery] Starting discovery: %d identities, %d clusters (%d labeled), %d total reps, threshold=%.2f",
            len(identities),
            len(representatives_by_cluster),
            len(labeled_ids),
            total_reps,
            self.settings.similarity_threshold,
        )

        candidates: list[AssignmentCandidate] = []
        # Track best similarities for debugging
        best_similarities: list[tuple[str, str | None, float]] = []
        for identity in identities:
            face_vec = identity.face_vector
            best_cluster, best_sim = self._find_best_match(face_vec, representatives_by_cluster, labeled_ids)
            best_similarities.append((identity.id, best_cluster, best_sim))
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
                logger.debug(
                    "[RepresentativeDiscovery] MATCHED identity %s -> cluster %s with similarity %.4f",
                    identity.id,
                    best_cluster,
                    best_sim,
                )

        # Log sample of best similarities when no candidates found
        if not candidates and best_similarities:
            sample = best_similarities[:5]
            for identity_id, cluster_id, sim in sample:
                logger.info(
                    "[RepresentativeDiscovery] NO MATCH: identity %s best_cluster=%s best_sim=%.4f (threshold=%.2f)",
                    identity_id,
                    cluster_id,
                    sim,
                    self.settings.similarity_threshold,
                )

        logger.info(
            "[RepresentativeDiscovery] Completed: %d candidates from %d identities", len(candidates), len(identities)
        )
        return candidates

    def _find_best_match(
        self,
        face_vector: np.ndarray,
        representatives_by_cluster: dict[str, list[np.ndarray]],
        labeled_cluster_ids: set[str],
    ) -> tuple[str | None, float]:
        """Identify the best matching cluster for a face embedding.

        Logic:
        1. Find global best match (highest similarity).
        2. Find best labeled match (highest similarity among labeled clusters).
        3. If global best is HIGH CONFIDENCE (>= complete_link_min_floor): Use it (Auto-Accept).
        4. Else (Suggestion Range): Prefer best LABELED match if available.
        """
        best_cluster: str | None = None
        best_similarity = 0.0

        best_labeled_cluster: str | None = None
        best_labeled_similarity = 0.0

        for cluster_id, representatives in representatives_by_cluster.items():
            for rep in representatives:
                rep_vec = normalize_face_embedding(np.asarray(rep, dtype=np.float32))
                similarity = float(np.dot(face_vector, rep_vec))

                # Update global best
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_cluster = cluster_id

                # Update labeled best
                if cluster_id in labeled_cluster_ids and similarity > best_labeled_similarity:
                    best_labeled_similarity = similarity
                    best_labeled_cluster = cluster_id

        # Decision Logic
        high_confidence_threshold = self.settings.complete_link_min_floor

        # 1. High Confidence -> Auto-Assign (Label doesn't matter)
        if best_similarity >= high_confidence_threshold:
            return best_cluster, best_similarity

        # 2. Low Confidence (Suggestion) -> Prefer Labeled Cluster
        if best_labeled_cluster and best_labeled_similarity > 0:
            # If we have a labeled match, use it instead of the unlabeled one
            # even if the unlabeled one score is higher (within suggestion range)
            return best_labeled_cluster, best_labeled_similarity

        # 3. No Labeled Match -> Return Unlabeled (or None if below threshold)
        return best_cluster, best_similarity
