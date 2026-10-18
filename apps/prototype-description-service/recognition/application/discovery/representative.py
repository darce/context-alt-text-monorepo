"""
Representative-based discovery for identity-to-cluster candidates.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.settings import ClusteringSettings
from recognition.application.similarity import SimilaritySearch
from recognition.domain.identity import MediaIdentity

logger = logging.getLogger(__name__)


class RepresentativeDiscovery:
    """Find candidate assignments by comparing identities to representatives."""

    discovery_method = DiscoveryMethod.REPRESENTATIVE

    def __init__(self, settings: ClusteringSettings) -> None:
        """Initialize the representative discovery algorithm.

        Args:
            settings: Threshold configuration for representative matching.
        """
        self.settings = settings
        self._search = SimilaritySearch(settings)

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

        if not representatives_by_cluster:
            return []

        query_embeddings = [identity.face_vector for identity in identities]
        best_matches = self._search.find_best_matches(
            query_embeddings,
            representatives_by_cluster,
            min_similarity=0.0,
        )

        labeled_representatives = {
            cluster_id: reps for cluster_id, reps in representatives_by_cluster.items() if cluster_id in labeled_ids
        }
        if labeled_representatives:
            labeled_matches = self._search.find_best_matches(
                query_embeddings,
                labeled_representatives,
                min_similarity=0.0,
            )
        else:
            labeled_matches = [None for _ in query_embeddings]

        candidates: list[AssignmentCandidate] = []
        best_similarities: list[tuple[str, str | None, float]] = []
        high_confidence_threshold = self.settings.complete_link_min_floor

        for identity, best_match, labeled_match in zip(identities, best_matches, labeled_matches, strict=False):
            best_cluster = best_match.cluster_id if best_match else None
            best_sim = best_match.similarity if best_match else 0.0
            best_similarities.append((identity.id, best_cluster, best_sim))

            labeled_cluster = labeled_match.cluster_id if labeled_match else None
            labeled_sim = labeled_match.similarity if labeled_match else 0.0

            selected_cluster: str | None
            selected_sim: float
            if best_cluster and best_sim >= high_confidence_threshold:
                selected_cluster = best_cluster
                selected_sim = best_sim
            elif labeled_cluster:
                selected_cluster = labeled_cluster
                selected_sim = labeled_sim
            else:
                selected_cluster = best_cluster
                selected_sim = best_sim

            if selected_cluster and selected_sim >= self.settings.similarity_threshold:
                candidates.append(
                    AssignmentCandidate(
                        identity=identity,
                        identity_vector=identity.face_vector,
                        cluster_id=selected_cluster,
                        discovery_method=self.discovery_method,
                        discovery_similarity=selected_sim,
                    )
                )
                logger.debug(
                    "[RepresentativeDiscovery] MATCHED identity %s -> cluster %s with similarity %.4f",
                    identity.id,
                    selected_cluster,
                    selected_sim,
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
