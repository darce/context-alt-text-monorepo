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
from recognition.application.settings import ClusteringSettings
from recognition.domain.repositories import ClusterRepository


def __getattr__(name: str):
    if name == "check_health":
        from recognition.application.health import check_health

        return check_health
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
