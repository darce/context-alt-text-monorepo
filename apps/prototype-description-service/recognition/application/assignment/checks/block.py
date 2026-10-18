"""
Block check to prevent assignment to user-blocked clusters.
"""

from __future__ import annotations

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks.base import AssignmentCheck, CheckFailureKind, CheckResult
from recognition.domain.repositories import IdentityClusterBlockRepository


class BlockCheck(AssignmentCheck):
    """Reject candidates blocked by explicit user curation."""

    name = "block_check"

    def __init__(self, block_repository: IdentityClusterBlockRepository) -> None:
        """Initialize the block check.

        Args:
            block_repository: Repository used to check block constraints.
        """
        self.block_repository = block_repository

    def is_enabled(self) -> bool:
        """Return whether the block check should run."""
        return True

    async def evaluate(self, candidate: AssignmentCandidate) -> CheckResult:
        """Reject assignments that violate a block constraint.

        Args:
            candidate: Proposed assignment to validate.

        Returns:
            CheckResult: Failed result when a block is active.
        """
        is_blocked = await self.block_repository.is_blocked(
            tenant_id=candidate.identity.tenant_id,
            identity_id=candidate.identity.id,
            cluster_id=candidate.cluster_id,
        )
        if is_blocked:
            return CheckResult(
                passed=False,
                is_fatal=True,
                should_reject=True,
                reason="identity blocked from cluster by user",
                metadata={"block_active": True},
                failure_kind=CheckFailureKind.BLOCK,
            )
        return CheckResult(passed=True, metadata={"block_active": False})
