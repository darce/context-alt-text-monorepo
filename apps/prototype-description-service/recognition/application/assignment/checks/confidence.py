"""
Confidence-based validation for assignment candidates.

Uses adaptive thresholds inspired by CurricularFace curriculum learning:
- Early stage (few labeled clusters): Strict thresholds to avoid false positives
- Developing stage: Thresholds gradually relax as clusters are validated
- Mature stage (30+ labeled clusters): Base threshold reached, system is stable
"""

from __future__ import annotations

import math

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks.base import AssignmentCheck, CheckResult
from recognition.application.settings import ClusteringSettings
from recognition.domain.repositories import ClusterRepository


def compute_adaptive_threshold(
    labeled_cluster_count: int,
    base_threshold: float,
    strict_threshold: float,
    maturity_point: int,
    decay_rate: float = 3.0,
) -> float:
    """Compute adaptive similarity threshold based on cluster maturity.

    Uses exponential decay from strict to base threshold as clusters grow.
    Inspired by CurricularFace: "address easy samples first, hard ones later".

    For clustering, we invert this: be strict early (avoid false positives when
    no ground truth exists), relax as the system learns (centroids become reliable).
    """
    if labeled_cluster_count == 0:
        return strict_threshold

    # Exponential decay from strict to base threshold
    rate = decay_rate / maturity_point
    adjustment = (strict_threshold - base_threshold) * math.exp(-rate * labeled_cluster_count)
    return base_threshold + adjustment


class ConfidenceCheck(AssignmentCheck):
    """Handles confidence gating with adaptive thresholds based on training maturity."""

    name = "confidence"

    def __init__(
        self,
        settings: ClusteringSettings,
        cluster_repository: ClusterRepository | None = None,
    ) -> None:
        """Initialize the confidence check.

        Args:
            settings: Threshold configuration for confidence-based decisions.
            cluster_repository: Repository to query labeled cluster count for adaptive thresholds.
        """
        self.settings = settings
        self.cluster_repository = cluster_repository
        self._cached_labeled_count: int | None = None

    def is_enabled(self) -> bool:
        """Return whether the confidence guard should run.

        Returns:
            bool: True when confidence-based gating is enabled.
        """
        return self.settings.early_stage_suggestion_enabled and self.settings.early_stage_high_confidence_threshold > 0

    async def evaluate(self, candidate: AssignmentCandidate) -> CheckResult:
        """Evaluate whether a candidate should be accepted, suggested, or rejected based on confidence.

        Uses adaptive thresholds that are strict when few labeled clusters exist,
        and relax as the system learns from more labeled data.

        Args:
            candidate: Proposed assignment to evaluate for confidence thresholds.

        Returns:
            CheckResult: Pass/fail outcome indicating confidence disposition.
        """
        # Bypass confidence check for anchor-linked candidates from GraphDiscovery.
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

        similarity = candidate.discovery_similarity

        # Compute adaptive threshold based on labeled cluster count
        if self.cluster_repository is not None:
            labeled_count = await self.cluster_repository.count_labeled()
        else:
            labeled_count = 0  # Fall back to strict threshold if no repo

        base_threshold = self.settings.similarity_threshold
        strict_threshold = self.settings.early_stage_high_confidence_threshold
        maturity_point = self.settings.adaptive_threshold_maturity_point

        adaptive_threshold = compute_adaptive_threshold(
            labeled_cluster_count=labeled_count,
            base_threshold=base_threshold,
            strict_threshold=strict_threshold,
            maturity_point=maturity_point,
        )

        metadata = {
            "discovery_similarity": similarity,
            "adaptive_threshold": round(adaptive_threshold, 4),
            "labeled_cluster_count": labeled_count,
            "maturity_point": maturity_point,
        }

        if similarity >= adaptive_threshold:
            return CheckResult(passed=True, metadata=metadata)

        return CheckResult(
            passed=False,
            is_fatal=True,
            should_reject=False,
            reason=f"similarity {similarity:.2%} below adaptive threshold {adaptive_threshold:.2%}",
            metadata=metadata,
        )
