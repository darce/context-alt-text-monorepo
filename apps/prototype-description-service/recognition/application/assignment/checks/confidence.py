"""
Confidence-based validation for assignment candidates.

Uses adaptive thresholds inspired by CurricularFace curriculum learning:
- Early stage (few labeled clusters): Strict thresholds to avoid false positives
- Developing stage: Thresholds gradually relax as clusters are validated
- Mature stage (30+ labeled clusters): Base threshold reached, system is stable
"""

from __future__ import annotations

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks.base import AssignmentCheck, CheckResult
from recognition.application.assignment.quality import compute_identity_quality
from recognition.application.settings import ClusteringSettings
from recognition.domain.maturity import ClusterMaturityLevel, compute_maturity_adjustment
from recognition.domain.repositories import ClusterRepository


class ConfidenceCheck(AssignmentCheck):
    """Handles confidence gating with adaptive thresholds based on cluster maturity and identity quality."""

    name = "confidence"

    def __init__(
        self,
        settings: ClusteringSettings,
        cluster_repository: ClusterRepository | None = None,
    ) -> None:
        """Initialize the confidence check.

        Args:
            settings: Threshold configuration for confidence-based decisions.
            cluster_repository: Repository to query cluster maturity.
        """
        self.settings = settings
        self.cluster_repository = cluster_repository

    def is_enabled(self) -> bool:
        """Return whether the confidence guard should run.

        Returns:
            bool: True when confidence-based gating is enabled.
        """
        return self.settings.early_stage_suggestion_enabled

    async def evaluate(self, candidate: AssignmentCandidate) -> CheckResult:
        """Evaluate whether a candidate should be accepted based on dynamic thresholds.

        Combines:
        1. Base threshold (from settings)
        2. Cluster maturity adjustment (stricter for new clusters, lenient for mature)
        3. Identity quality adjustment (stricter for poor quality faces, lenient for high confidence)

        Args:
            candidate: Proposed assignment to evaluate.

        Returns:
            CheckResult: Pass/fail outcome.
        """
        if candidate.anchor_linked:
            return CheckResult(
                passed=True,
                metadata={
                    "bypass_reason": "anchor_linked_transitivity",
                    "discovery_similarity": candidate.discovery_similarity,
                },
            )

        # 1. Compute Identity Quality Adjustment for the candidate
        # We need detection metrics from the identity
        identity = candidate.identity
        quality_info = compute_identity_quality(
            confidence=identity.confidence,
            pose_pitch=identity.pose_pitch,
            pose_yaw=identity.pose_yaw,
            pose_roll=identity.pose_roll,
            bbox_width=identity.bbox_width,
            bbox_height=identity.bbox_height,
        )
        quality_adj = quality_info.threshold_adjustment

        # 2. Get Cluster Maturity Adjustment
        maturity_adj = 0.0
        maturity_level_name = "UNKNOWN"

        if self.cluster_repository and candidate.cluster_id:
            maturity_info = await self.cluster_repository.get_maturity_info(candidate.cluster_id)
            if maturity_info:
                maturity_adj = maturity_info.threshold_adjustment
                maturity_level_name = maturity_info.level.name
            else:
                # Cluster not found or repo failed, treat as COLD
                maturity_adj = compute_maturity_adjustment(ClusterMaturityLevel.COLD)
                maturity_level_name = "COLD (fallback)"
        else:
            # No repo available, treat as COLD
            maturity_adj = compute_maturity_adjustment(ClusterMaturityLevel.COLD)
            maturity_level_name = "COLD (no_repo)"

        # 3. Compute Final Threshold
        base = self.settings.similarity_threshold
        # "Strict to base" logic is replaced by "Base + Adjs"
        # If adjustments are positive => stricter.

        final_threshold = base + maturity_adj + quality_adj
        similarity = candidate.discovery_similarity

        metadata = {
            "discovery_similarity": similarity,
            "base_threshold": base,
            "final_threshold": round(final_threshold, 4),
            "maturity_adj": maturity_adj,
            "quality_adj": quality_adj,
            "maturity_level": maturity_level_name,
            "quality_score": quality_info.score,
        }

        if similarity >= final_threshold:
            return CheckResult(passed=True, metadata=metadata)

        return CheckResult(
            passed=False,
            is_fatal=True,
            should_reject=False,
            reason=f"similarity {similarity:.2%} below adaptive threshold {final_threshold:.2%}",
            metadata=metadata,
        )
