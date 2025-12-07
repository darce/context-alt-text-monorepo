"""
Application layer entrypoint for the recognition service.
"""

from recognition.application.assignment import (
    AssignmentCandidate,
    AssignmentDecision,
    AssignmentGate,
    AssignmentOutcome,
    AssignmentWriter,
    DiscoveryMethod,
)
from recognition.application.health import check_health
from recognition.application.settings import ClusteringSettings
from recognition.domain.repositories import ClusterRepository

__all__ = [
    "AssignmentCandidate",
    "AssignmentDecision",
    "AssignmentGate",
    "AssignmentOutcome",
    "AssignmentWriter",
    "ClusteringSettings",
    "ClusterRepository",
    "DiscoveryMethod",
    "check_health",
]
