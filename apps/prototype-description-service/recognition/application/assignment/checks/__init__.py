"""
Assignment validation checks used by the unified gate.
"""

from recognition.application.assignment.checks.base import AssignmentCheck, CheckResult
from recognition.application.assignment.checks.block import BlockCheck
from recognition.application.assignment.checks.confidence import ConfidenceCheck
from recognition.application.assignment.checks.constraint import ConstraintCheck
from recognition.application.settings import ClusteringSettings
from recognition.domain.repositories import ClusterRepository, IdentityClusterBlockRepository

__all__ = [
    "AssignmentCheck",
    "CheckResult",
    "BlockCheck",
    "ClusterRepository",
    "IdentityClusterBlockRepository",
    "ClusteringSettings",
    "ConfidenceCheck",
    "ConstraintCheck",
]
