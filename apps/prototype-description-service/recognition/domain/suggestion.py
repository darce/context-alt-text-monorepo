"""
Assignment suggestion domain model for human-in-the-loop review.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SuggestionStatus(Enum):
    """Lifecycle status for an assignment suggestion."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass
class AssignmentSuggestion:
    """Represents a proposed identity-to-cluster assignment awaiting review."""

    id: str
    identity_id: str
    cluster_id: str
    representative_similarity: float
    member_similarity: float
    status: SuggestionStatus
    created_at: datetime | None = None
