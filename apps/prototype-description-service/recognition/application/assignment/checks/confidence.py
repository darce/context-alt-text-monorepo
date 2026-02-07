"""
Confidence-based validation for assignment candidates.

Uses adaptive thresholds with curriculum learning:
- Cold stage (new clusters): Lenient thresholds to bootstrap growth
- Developing stage: Thresholds remain lenient as curriculum_t increases
- Mature stage (confirmed or 10+ members): Maturity adjustment tightens threshold

The curriculum_t parameter (0→1) tracks the running average of accepted
similarities and provides continuous leniency via: curriculum_adj = -0.05 * t
"""

from __future__ import annotations

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks.base import AssignmentCheck, CheckFailureKind, CheckResult
from recognition.application.assignment.quality import IdentityQualityInfo, compute_identity_quality
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.domain.maturity import ClusterMaturityLevel, compute_maturity_adjustment
from recognition.domain.repositories import ClusterRepository


class ConfidenceCheck(AssignmentCheck):
    """Handles confidence gating with adaptive thresholds based on cluster maturity and identity quality."""

    name = "confidence_check"

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

        identity = candidate.identity

        # 1. Get Cluster Maturity Adjustment + Curriculum Bias
        maturity_level = ClusterMaturityLevel.COLD
        maturity_adj = compute_maturity_adjustment(maturity_level, settings=self.settings.maturity)
        maturity_level_name = "COLD (no_repo)"
        curriculum_t = 0.0

        if self.cluster_repository and candidate.cluster_id:
            maturity_info = await self.cluster_repository.get_maturity_info(
                candidate.cluster_id,
                settings=self.settings.maturity,
            )
            if maturity_info:
                maturity_level = maturity_info.level
                maturity_adj = maturity_info.threshold_adjustment
                maturity_level_name = maturity_level.name
            else:
                # Cluster not found or repo failed, treat as COLD
                maturity_level = ClusterMaturityLevel.COLD
                maturity_adj = compute_maturity_adjustment(maturity_level, settings=self.settings.maturity)
                maturity_level_name = "COLD (fallback)"

            # Get curriculum bias (EMA of accepted similarities)
            curriculum_t = await self.cluster_repository.get_curriculum_t(str(candidate.cluster_id)) or 0.0

        # Curriculum adjustment: continuous graduation based on learned match quality
        # t=0 (cold, no history) → 0 adjustment
        # t=0.9 (many high-quality matches) → -0.045 (more lenient)
        curriculum_adj = self.settings.curriculum_coefficient * curriculum_t

        # 2. Compute Identity Quality Adjustment for the candidate
        # We need detection metrics from the identity
        quality_info = compute_identity_quality(
            confidence=identity.confidence,
            pose_pitch=identity.pose_pitch,
            pose_yaw=identity.pose_yaw,
            pose_roll=identity.pose_roll,
            bbox_width=identity.bbox_width,
            bbox_height=identity.bbox_height,
            maturity=maturity_level,
        )
        quality_adj = quality_info.threshold_adjustment

        # 3. Compute Final Threshold + Suggestion Band
        base = self.settings.similarity_threshold
        suggestion_floor = self.settings.suggestion_floor
        suggestion_ceiling = self.settings.suggestion_ceiling

        final_threshold = base + maturity_adj + quality_adj + curriculum_adj
        adjusted_floor = suggestion_floor + maturity_adj + quality_adj + curriculum_adj
        adjusted_ceiling = suggestion_ceiling + maturity_adj + quality_adj + curriculum_adj
        if adjusted_floor > final_threshold:
            adjusted_floor = final_threshold
        similarity = candidate.discovery_similarity

        metadata = {
            "discovery_similarity": similarity,
            "base_threshold": base,
            "final_threshold": round(final_threshold, 4),
            "maturity_adj": maturity_adj,
            "quality_adj": quality_adj,
            "curriculum_t": round(curriculum_t, 4),
            "curriculum_adj": round(curriculum_adj, 4),
            "suggestion_floor": round(adjusted_floor, 4),
            "suggestion_ceiling": round(adjusted_ceiling, 4),
            "maturity_level": maturity_level_name,
            "quality_score": quality_info.score,
        }

        if self._is_fatal_failure(identity=identity, quality_info=quality_info):
            metadata["fatal_quality_failure"] = True
            metadata["quality_review_required"] = True

            # Low-quality detections with meaningful similarity should still surface as
            # user-reviewable suggestions instead of being silently dropped.
            if similarity >= adjusted_floor:
                return CheckResult(
                    passed=False,
                    is_fatal=True,
                    should_reject=False,
                    reason="fatal_quality_failure_suggest",
                    metadata=metadata,
                    failure_kind=CheckFailureKind.CONFIDENCE,
                )

            return CheckResult(
                passed=False,
                is_fatal=True,
                should_reject=True,
                reason="fatal_quality_failure_below_suggestion_floor",
                metadata=metadata,
                failure_kind=CheckFailureKind.CONFIDENCE,
            )

        if similarity >= final_threshold:
            return CheckResult(passed=True, metadata=metadata)

        if similarity >= adjusted_floor:
            return CheckResult(
                passed=False,
                is_fatal=True,
                should_reject=False,
                reason=f"similarity {similarity:.2%} within suggestion band",
                metadata=metadata,
                failure_kind=CheckFailureKind.CONFIDENCE,
            )

        return CheckResult(
            passed=False,
            is_fatal=True,
            should_reject=True,
            reason=f"similarity {similarity:.2%} below suggestion floor {adjusted_floor:.2%}",
            metadata=metadata,
            failure_kind=CheckFailureKind.CONFIDENCE,
        )

    def _is_fatal_failure(self, *, identity: MediaIdentity, quality_info: IdentityQualityInfo) -> bool:
        return (
            identity.confidence < self.settings.fatal_confidence_floor
            or quality_info.score < self.settings.fatal_quality_floor
        )
