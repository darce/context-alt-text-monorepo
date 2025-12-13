"""
Member distribution validation for assignment candidates.
"""

from __future__ import annotations

import numpy as np

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks.base import AssignmentCheck, CheckResult
from recognition.application.settings import ClusteringSettings
from recognition.domain.repositories import ClusterRepository


class MemberDistributionCheck(AssignmentCheck):
    """Validates that a candidate fits the existing member distribution."""

    name = "member_distribution"

    def __init__(
        self,
        settings: ClusteringSettings,
        cluster_repository: ClusterRepository,
    ) -> None:
        """Initialize the member distribution check.

        Args:
            settings: Threshold configuration for member similarity validation.
            cluster_repository: Repository used to fetch member embeddings.
        """
        self.settings = settings
        self.cluster_repository = cluster_repository

    def is_enabled(self) -> bool:
        """Return whether member distribution validation should run.

        Returns:
            bool: True when the distribution guard is active.
        """
        return self.settings.member_validation_min_floor > 0.0 and self.settings.member_validation_avg_threshold > 0.0

    async def evaluate(self, candidate: AssignmentCandidate) -> CheckResult:
        """Validate that the candidate aligns with cluster member embeddings.

        Args:
            candidate: Proposed assignment to test against member distribution.

        Returns:
            CheckResult: Pass/fail outcome with distribution metadata.
        """
        # Bypass member distribution check for very high-confidence representative matches.
        # If the discovery similarity is extremely high (>=0.95), the identity almost
        # certainly belongs to this cluster and we don't need to verify against ALL members.
        if candidate.discovery_similarity >= 0.95:
            return CheckResult(
                passed=True,
                metadata={
                    "bypass_reason": "high_confidence_representative_match",
                    "discovery_similarity": candidate.discovery_similarity,
                },
            )

        members = await self.cluster_repository.get_member_embeddings(candidate.cluster_id)
        member_count = len(members)

        if member_count == 0:
            return CheckResult(
                passed=True,
                metadata={
                    "member_count": 0,
                    "min_similarity": 1.0,
                    "avg_similarity": 1.0,
                },
            )

        candidate_vec = self._normalize(candidate.identity_vector)
        similarities: list[float] = []
        for member in members:
            member_vec = self._normalize(np.asarray(member, dtype=np.float32))
            similarities.append(float(np.dot(candidate_vec, member_vec)))

        min_sim = float(min(similarities))
        avg_sim = float(sum(similarities) / len(similarities))
        metadata = {
            "member_count": member_count,
            "min_similarity": min_sim,
            "avg_similarity": avg_sim,
        }

        if (
            min_sim < self.settings.member_validation_min_floor
            or avg_sim < self.settings.member_validation_avg_threshold
        ):
            return CheckResult(
                passed=False,
                is_fatal=True,
                should_reject=True,
                reason="candidate does not fit member distribution",
                metadata=metadata,
            )

        return CheckResult(passed=True, metadata=metadata)

    @staticmethod
    def _normalize(vector: np.ndarray) -> np.ndarray:
        """Return normalized copy of the vector."""
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return vector.astype(np.float32)
        return vector.astype(np.float32) / norm
