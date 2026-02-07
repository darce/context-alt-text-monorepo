"""
Check that rejects candidates violating user constraints.
"""

from __future__ import annotations

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks.base import AssignmentCheck, CheckFailureKind, CheckResult
from recognition.domain.repositories import IdentityConstraintRepository, MemberRepository


class ConstraintCheck(AssignmentCheck):
    """Reject candidates that violate pairwise constraints."""

    name = "constraint_check"

    def __init__(
        self,
        constraint_repo: IdentityConstraintRepository,
        member_repo: MemberRepository,
    ) -> None:
        self.constraint_repo = constraint_repo
        self.member_repo = member_repo

    def is_enabled(self) -> bool:
        return True

    async def evaluate(self, candidate: AssignmentCandidate) -> CheckResult:
        if not candidate.cluster_id:
            return CheckResult(passed=True)

        members = await self.member_repo.get_by_cluster(candidate.cluster_id)
        if not members:
            # Empty cluster or doesn't exist? Should theoretically pass as no constraints can exist against it
            return CheckResult(passed=True)

        member_ids = [m.identity_id for m in members]
        is_blocked = await self.constraint_repo.has_cannot_link(
            tenant_id=candidate.identity.tenant_id,
            identity_id=candidate.identity.id,
            cluster_member_ids=member_ids,
        )

        if is_blocked:
            return CheckResult(
                passed=False,
                is_fatal=True,
                should_reject=True,
                reason="Constraint violation: CANNOT_LINK",
                failure_kind=CheckFailureKind.CONSTRAINT,
            )

        return CheckResult(passed=True)
