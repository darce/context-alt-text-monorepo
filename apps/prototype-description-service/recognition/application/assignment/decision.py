"""
Assignment decision model produced by the AssignmentGate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from recognition.application.assignment.candidate import AssignmentCandidate


class AssignmentOutcome(Enum):
    """Final disposition for an assignment candidate."""

    ACCEPT = "accept"
    SUGGEST = "suggest"
    REJECT = "reject"


@dataclass
class AssignmentDecision:
    """Result of evaluating a candidate through the assignment gate."""

    outcome: AssignmentOutcome
    candidate: AssignmentCandidate
    checks_passed: list[str]
    checks_failed: list[str]
    rejection_reason: str | None = None
    suggestion_confidence: float | None = None
    metadata: dict[str, Any] | None = None
