"""Unit tests for assignment decision outcomes."""

from __future__ import annotations

import numpy as np

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id


def make_candidate() -> AssignmentCandidate:
    """Create a minimal candidate for decision tests."""
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=np.ones(4, dtype=np.float32),
        confidence=0.9,
        bbox_width=10,
        bbox_height=12,
    )
    return AssignmentCandidate(
        identity=identity,
        identity_vector=np.ones(4, dtype=np.float32),
        cluster_id=str(generate_id()),
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.8,
    )


def test_assignment_outcome_enum_values() -> None:
    """Enum should expose the three expected outcomes."""
    assert {outcome.value for outcome in AssignmentOutcome} == {"accept", "suggest", "reject"}


def test_decision_captures_passed_and_failed_checks() -> None:
    """Decision should include check bookkeeping and optional metadata."""
    candidate = make_candidate()
    decision = AssignmentDecision(
        outcome=AssignmentOutcome.SUGGEST,
        candidate=candidate,
        checks_passed=["maturity"],
        checks_failed=["complete_link"],
        rejection_reason="below complete-link threshold",
        suggestion_confidence=0.72,
        metadata={"min_similarity": 0.7},
    )

    assert decision.outcome is AssignmentOutcome.SUGGEST
    assert decision.candidate is candidate
    assert decision.checks_passed == ["maturity"]
    assert decision.checks_failed == ["complete_link"]
    assert decision.rejection_reason == "below complete-link threshold"
    assert decision.suggestion_confidence == 0.72
    assert decision.metadata == {"min_similarity": 0.7}
