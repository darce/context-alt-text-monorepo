"""
Unified assignment pipeline scaffolding for recognition v4.2.4.
"""

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.assignment.gate import AssignmentGate
from recognition.application.assignment.joint import PhotoConflictResult, group_accepted_by_media, resolve_photo_conflicts
from recognition.application.persistence.assignment_writer import AssignmentWriter

__all__ = [
    "AssignmentCandidate",
    "AssignmentDecision",
    "AssignmentGate",
    "AssignmentOutcome",
    "AssignmentWriter",
    "DiscoveryMethod",
    "PhotoConflictResult",
    "group_accepted_by_media",
    "resolve_photo_conflicts",
]
