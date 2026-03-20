"""Suggestion domain models for human-in-the-loop review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SuggestionStatus(Enum):
    """Lifecycle status for an assignment suggestion."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class SuggestedLabelSource(str, Enum):
    """Source of a suggested label."""

    IDENTITY = "identity"
    ROSTER = "roster"
    SIMILAR_CLUSTER = "similar_cluster"
    NONE = "none"


class SuggestionRefreshReason(str, Enum):
    """Reason code for refreshing suggestion candidates."""

    MANUAL_SPLIT = "manual_split"
    WRONG_PERSON = "wrong_person"
    MANUAL_ASSIGN = "manual_assign"
    MANUAL_MERGE = "manual_merge"


@dataclass
class SuggestedLabel:
    """A suggested label for a cluster."""

    label: str
    source: SuggestedLabelSource
    confidence: float
    target_cluster_id: str | None = None


@dataclass
class AssignmentSuggestion:
    """Represents a proposed identity-to-cluster assignment awaiting review."""

    id: str
    identity_id: str
    cluster_id: str
    representative_similarity: float
    member_similarity: float
    status: SuggestionStatus
    evidence_generation: int = 0
    confidence_score: float | None = None
    expires_at: datetime | None = None
    source_job_id: str | None = None
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    refreshed_at: datetime | None = None
    source: str | None = None


@dataclass
class MergeSuggestion:
    """Represents a proposed cluster-to-cluster merge awaiting review."""

    id: str
    cluster_a_id: str
    cluster_b_id: str
    similarity: float
    status: SuggestionStatus
    confidence_score: float | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    source_job_id: str | None = None
    resolved_at: datetime | None = None
    refreshed_at: datetime | None = None
    source: str | None = None


@dataclass
class NameSuggestion:
    """Represents a proposed cluster label awaiting review."""

    id: str
    cluster_id: str
    suggested_name: str
    confidence_score: float | None
    source: SuggestedLabelSource
    status: SuggestionStatus
    created_at: datetime | None = None
    expires_at: datetime | None = None
    source_job_id: str | None = None
    resolved_at: datetime | None = None


@dataclass(frozen=True)
class BulkAcceptResult:
    """Summary of a bulk-accept operation across suggestion types."""

    accepted_count: int
    skipped_count: int
