"""
Base classes for assignment validation checks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from recognition.application.assignment.candidate import AssignmentCandidate


@dataclass
class CheckResult:
    """Outcome of a single assignment validation check."""

    passed: bool
    is_fatal: bool = False
    should_reject: bool = False
    reason: str | None = None
    metadata: dict[str, Any] | None = None


class AssignmentCheck(ABC):
    """Abstract base class for all assignment validation checks."""

    name: str

    @abstractmethod
    def is_enabled(self) -> bool:
        """Return whether this check should run.

        Returns:
            bool: True if the check should execute for the candidate.
        """
        ...

    @abstractmethod
    async def evaluate(self, candidate: AssignmentCandidate) -> CheckResult:
        """Evaluate the given candidate against this check.

        Args:
            candidate: Proposed assignment to validate.

        Returns:
            CheckResult: Pass/fail outcome and metadata.
        """
        ...
