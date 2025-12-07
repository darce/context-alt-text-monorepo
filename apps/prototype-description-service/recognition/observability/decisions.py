"""
Decision logging models for the recognition service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DecisionType(Enum):
    """Outcome categories for assignment gate evaluations."""

    ACCEPT = "accept"
    SUGGEST = "suggest"
    REJECT = "reject"


@dataclass
class DecisionLog:
    """Structured record of a single assignment decision."""

    identity_id: str
    cluster_id: str | None
    decision: DecisionType
    similarity: float | None
    reason: str | None
    timestamp: datetime
