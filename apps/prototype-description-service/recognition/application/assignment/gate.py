"""
Assignment gate orchestrating validation checks for cluster assignments.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks import (
    BlockCheck,
    CheckFailureKind,
    ConfidenceCheck,
    ConstraintCheck,
)
from recognition.application.assignment.checks.base import AssignmentCheck
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.settings import ClusteringSettings
from recognition.domain.repositories import (
    ClusterRepository,
    IdentityClusterBlockRepository,
    IdentityConstraintRepository,
    MemberRepository,
)


class AssignmentGate:
    """Routes every assignment candidate through a single validation pipeline."""

    def __init__(
        self,
        settings: ClusteringSettings,
        cluster_repository: ClusterRepository,
        block_repository: IdentityClusterBlockRepository | None = None,
        constraint_repository: IdentityConstraintRepository | None = None,
        member_repository: MemberRepository | None = None,
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
        self.block_repository = block_repository
        self.constraint_repository = constraint_repository
        self.member_repository = member_repository
        if checks is None:
            gate_checks: list[AssignmentCheck] = [
                ConfidenceCheck(settings, cluster_repository),
            ]
            if block_repository is not None:
                gate_checks.insert(0, BlockCheck(block_repository))
            if constraint_repository is not None and member_repository is not None:
                # Constraints (MUST/CANNOT link) are strong signals, check early
                gate_checks.insert(1, ConstraintCheck(constraint_repository, member_repository))

            self.checks = gate_checks
        else:
            self.checks = list(checks)

    async def evaluate(self, candidate: AssignmentCandidate) -> AssignmentDecision:
        """Evaluate a candidate through all configured checks.

        Args:
            candidate: Proposed identity-to-cluster assignment to validate.

        Returns:
            AssignmentDecision: Outcome including passed and failed checks.
        """
        checks_passed: list[str] = []
        checks_failed: list[str] = []
        failure_kinds: list[CheckFailureKind] = []
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
            if result.failure_kind is not None:
                failure_kinds.append(result.failure_kind)
            if result.is_fatal:
                outcome = AssignmentOutcome.REJECT if result.should_reject else AssignmentOutcome.SUGGEST
                return AssignmentDecision(
                    outcome=outcome,
                    candidate=candidate,
                    checks_passed=checks_passed,
                    checks_failed=checks_failed,
                    rejection_reason=result.reason,
                    metadata=all_metadata,
                    failure_kinds=failure_kinds,
                )

        return AssignmentDecision(
            outcome=AssignmentOutcome.ACCEPT,
            candidate=candidate,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            metadata=all_metadata,
            failure_kinds=failure_kinds,
        )

    def add_check(self, check: AssignmentCheck) -> None:
        """Append an additional check to the evaluation pipeline.

        Args:
            check: Validation check to add.
        """
        self.checks.append(check)
