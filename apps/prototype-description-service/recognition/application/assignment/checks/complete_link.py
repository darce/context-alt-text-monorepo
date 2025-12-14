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

        # Bypass complete-link check for anchor-linked candidates from GraphDiscovery.
        # Transitivity has already established the connection via the graph algorithm
        # (Chinese Whispers/HDBSCAN grouped them with known cluster anchors).
        # This is the key fix for batch consistency: trusting graph transitivity.
        if candidate.anchor_linked:
            return CheckResult(
                passed=True,
                metadata={
                    "bypass_reason": "anchor_linked_transitivity",
                    "discovery_similarity": candidate.discovery_similarity,
                },
            )

        # Fetch cluster metadata to determine if it is user-labeled
        cluster = await self.cluster_repository.get_by_id(candidate.cluster_id)
        is_unlabeled = False
        if cluster:
            is_unlabeled = not cluster.user_confirmed and (not cluster.label or cluster.label.startswith("cluster-"))

        # For Unlabeled clusters, we use the discovery threshold as the floor.
        # This ensures that "Split Batches" behave like "Single Batches" (where graph clustering
        # groups items at the lower threshold).
        target_min_floor = self.settings.similarity_threshold if is_unlabeled else self.settings.complete_link_min_floor
        # Average threshold also relaxed for unlabeled targets to encourage merging
        target_avg_threshold = (
            self.settings.similarity_threshold if is_unlabeled else self.settings.complete_link_avg_threshold
        )

        representatives = await self.cluster_repository.get_all_representatives(candidate.cluster_id)
        rep_count = len(representatives)
        if rep_count < 2:
            # Singleton target: verify against the single representative
            # For Unlabeled, simply passing discovery (limit) is enough
            # For Labeled, we might want stricter check? But standard logic covers it.
            return CheckResult(
                passed=True,
                metadata={
                    "min_similarity": 1.0,
                    "avg_similarity": 1.0,
                    "representative_count": rep_count,
                    "target_is_unlabeled": is_unlabeled,
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
            "target_is_unlabeled": is_unlabeled,
            "target_min_floor": target_min_floor,
        }

        if min_sim < target_min_floor or avg_sim < target_avg_threshold:
            # ADAPTIVE LOGIC: If cluster is mature, relax thresholds (only applies to Labeled/Standard logic)
            # Unlabeled logic is already floored to base threshold, so no relaxation needed
            if not is_unlabeled:
                is_mature = rep_count >= self.settings.adaptive_threshold_maturity_point
                relaxation = self.settings.adaptive_relaxation_amount if is_mature else 0.0

                adaptive_min = target_min_floor - relaxation
                adaptive_avg = target_avg_threshold - relaxation

                if min_sim >= adaptive_min and avg_sim >= adaptive_avg:
                    metadata["adaptive_relaxation_applied"] = True
                    metadata["relaxation_amount"] = relaxation
                    return CheckResult(passed=True, metadata=metadata)

            # FAIL:
            # If Unlabeled: REJECT (don't suggest garbage matching to garbage).
            # If Labeled: SUGGEST (ask user to confirm).
            should_reject = bool(is_unlabeled)

            return CheckResult(
                passed=False,
                is_fatal=True,
                should_reject=should_reject,
                reason=f"complete-link similarity below threshold (unlabeled={is_unlabeled})",
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
