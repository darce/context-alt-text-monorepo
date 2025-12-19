"""
Assignment gate orchestrating validation checks for cluster assignments.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks import (
    CompleteLinkCheck,
    ConfidenceCheck,
    MaturityCheck,
    MemberDistributionCheck,
)
from recognition.application.assignment.checks.base import AssignmentCheck
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.settings import ClusteringSettings
from recognition.domain.repositories import ClusterRepository


class AssignmentGate:
    """Routes every assignment candidate through a single validation pipeline."""

    def __init__(
        self,
        settings: ClusteringSettings,
        cluster_repository: ClusterRepository,
        checks: Iterable[AssignmentCheck] | None = None,
    ) -> None:
        """Create a new assignment gate.

        Args:
            settings: Threshold configuration used by the gate and its checks.
            cluster_repository: Repository used to fetch cluster data for checks.
            checks: Optional initial collection of checks to run in order.
        """
        self.settings = settings
        self.cluster_repository = cluster_repository
        if checks is None:
            self.checks = [
                MaturityCheck(settings, cluster_repository),
                CompleteLinkCheck(settings, cluster_repository),
                MemberDistributionCheck(settings, cluster_repository),
                ConfidenceCheck(settings, cluster_repository),
            ]
        else:
            self.checks = list(checks)

    async def evaluate(self, candidate: AssignmentCandidate) -> AssignmentDecision:
        """Evaluate a candidate through all configured checks.

        Args:
            candidate: Proposed identity-to-cluster assignment to validate.

        Returns:
            AssignmentDecision: Outcome including passed and failed checks.

        Raises:
        """
        checks_passed: list[str] = []
        checks_failed: list[str] = []
        all_metadata: dict[str, Any] = {}

        for check in self.checks:
            if not check.is_enabled():
                continue

            result = await check.evaluate(candidate)
            if result.metadata:
                all_metadata.update(result.metadata)

            if result.passed:
                checks_passed.append(check.name)
                continue

            checks_failed.append(check.name)
            if result.is_fatal:
                outcome = AssignmentOutcome.REJECT if result.should_reject else AssignmentOutcome.SUGGEST
                return AssignmentDecision(
                    outcome=outcome,
                    candidate=candidate,
                    checks_passed=checks_passed,
                    checks_failed=checks_failed,
                    rejection_reason=result.reason,
                    metadata=all_metadata,
                )

        return AssignmentDecision(
            outcome=AssignmentOutcome.ACCEPT,
            candidate=candidate,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            metadata=all_metadata,
        )

    def add_check(self, check: AssignmentCheck) -> None:
        """Append an additional check to the evaluation pipeline.

        Args:
            check: Validation check to add.
        """
        self.checks.append(check)
