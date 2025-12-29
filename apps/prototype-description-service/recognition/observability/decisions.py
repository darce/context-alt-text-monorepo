"""
Decision logging models for the recognition service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DecisionType(Enum):
    """Outcome categories for assignment gate evaluations."""

    ACCEPT = "accept"
    SUGGEST = "suggest"
    REJECT = "reject"


class CurationEventType(Enum):
    """Types of user-initiated curation events."""

    RENAME = "rename"
    MERGE = "merge"
    SPLIT = "split"
    ASSIGN_OUTLIER = "assign_outlier"
    REMOVE_MEMBER = "remove_member"


@dataclass
class DecisionLog:
    """Structured record of a single assignment decision."""

    identity_id: str
    cluster_id: str | None
    decision: DecisionType
    similarity: float | None
    reason: str | None
    timestamp: datetime


@dataclass
class CurationEventLog:
    """Structured record of a user curation action."""

    event_type: CurationEventType
    cluster_id: str
    tenant_id: str
    timestamp: datetime
    details: dict[str, Any] = field(default_factory=dict)
