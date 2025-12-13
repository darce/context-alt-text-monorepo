"""
Complete-link validation check to prevent single-representative domination.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks.base import AssignmentCheck, CheckResult
from recognition.application.settings import ClusteringSettings
from recognition.domain.repositories import ClusterRepository


class CompleteLinkCheck(AssignmentCheck):
    """Validates a candidate against all representatives of a cluster."""

    name = "complete_link"

    def __init__(
        self,
        settings: ClusteringSettings,
        cluster_repository: ClusterRepository,
    ) -> None:
        """Initialize the check with dependencies.

        Args:
            settings: Threshold configuration for clustering.
            cluster_repository: Repository used to load representatives.
        """
        self.settings = settings
        self.cluster_repository = cluster_repository

    def is_enabled(self) -> bool:
        """Return whether complete-link validation should run.

        Returns:
            bool: True when this guard is active.
        """
        return self.settings.complete_link_min_floor > 0.0 and self.settings.complete_link_avg_threshold > 0.0

    async def evaluate(self, candidate: AssignmentCandidate) -> CheckResult:
        """Evaluate the candidate against all cluster representatives.

        Args:
            candidate: Proposed assignment requiring validation.

        Returns:
            CheckResult: Pass/fail outcome with similarity metadata.
        """
        # Bypass complete-link check for very high-confidence representative matches.
        # If the discovery similarity is extremely high (>=0.95), the identity almost
        # certainly belongs to this cluster and we don't need to verify against ALL reps.
        if candidate.discovery_similarity >= 0.95:
            return CheckResult(
                passed=True,
                metadata={
                    "bypass_reason": "high_confidence_representative_match",
                    "discovery_similarity": candidate.discovery_similarity,
                },
            )

        representatives = await self.cluster_repository.get_all_representatives(candidate.cluster_id)
        rep_count = len(representatives)
        if rep_count < 2:
            return CheckResult(
                passed=True,
                metadata={
                    "min_similarity": 1.0,
                    "avg_similarity": 1.0,
                    "representative_count": rep_count,
                },
            )

        candidate_vec = self._normalize(candidate.identity_vector)
        similarities: list[float] = []
        for rep in representatives:
            rep_vec = self._normalize(np.asarray(rep, dtype=np.float32))
            similarities.append(float(np.dot(candidate_vec, rep_vec)))

        min_sim = float(min(similarities))
        avg_sim = float(sum(similarities) / len(similarities))
        metadata: dict[str, Any] = {
            "min_similarity": min_sim,
            "avg_similarity": avg_sim,
            "representative_count": rep_count,
        }

        if min_sim < self.settings.complete_link_min_floor or avg_sim < self.settings.complete_link_avg_threshold:
            return CheckResult(
                passed=False,
                is_fatal=True,
                should_reject=False,
                reason="complete-link similarity below threshold",
                metadata=metadata,
            )

        return CheckResult(passed=True, metadata=metadata)

    @staticmethod
    def _normalize(vector: np.ndarray) -> np.ndarray:
        """Return a normalized copy of the provided vector."""
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return vector.astype(np.float32)
        return vector.astype(np.float32) / norm
