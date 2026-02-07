"""
Assignment validation checks used by the unified gate.
"""

from recognition.application.assignment.checks.base import AssignmentCheck, CheckFailureKind, CheckResult
from recognition.application.assignment.checks.block import BlockCheck
from recognition.application.assignment.checks.confidence import ConfidenceCheck
from recognition.application.assignment.checks.constraint import ConstraintCheck

__all__ = [
    "AssignmentCheck",
    "CheckResult",
    "CheckFailureKind",
    "BlockCheck",
    "ConfidenceCheck",
    "ConstraintCheck",
]
