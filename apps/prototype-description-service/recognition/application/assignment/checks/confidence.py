"""
Confidence-based validation for assignment candidates.
"""

from __future__ import annotations

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks.base import AssignmentCheck, CheckResult
from recognition.application.settings import ClusteringSettings


class ConfidenceCheck(AssignmentCheck):
    """Handles early-stage high-confidence gating and suggestion thresholds."""

    name = "confidence"

    def __init__(self, settings: ClusteringSettings) -> None:
        """Initialize the confidence check.

        Args:
            settings: Threshold configuration for confidence-based decisions.
        """
        self.settings = settings

    def is_enabled(self) -> bool:
        """Return whether the confidence guard should run.

        Returns:
            bool: True when confidence-based gating is enabled.
        """
        return self.settings.early_stage_suggestion_enabled and self.settings.early_stage_high_confidence_threshold > 0

    async def evaluate(self, candidate: AssignmentCandidate) -> CheckResult:
        """Evaluate whether a candidate should be accepted, suggested, or rejected based on confidence.

        Args:
            candidate: Proposed assignment to evaluate for confidence thresholds.

        Returns:
            CheckResult: Pass/fail outcome indicating confidence disposition.
        """
        similarity = candidate.discovery_similarity
        metadata = {"discovery_similarity": similarity}

        if similarity >= self.settings.early_stage_high_confidence_threshold:
            return CheckResult(passed=True, metadata=metadata)

        return CheckResult(
            passed=False,
            is_fatal=True,
            should_reject=False,
            reason="below confidence threshold",
            metadata=metadata,
        )
