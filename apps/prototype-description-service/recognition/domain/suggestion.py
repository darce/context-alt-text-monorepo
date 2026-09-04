"""
Assignment suggestion domain model for human-in-the-loop review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, StrEnum

from recognition.domain.representative import ClusterRepresentative


class SuggestionStatus(Enum):
    """Lifecycle status for an assignment suggestion."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SuggestedLabelSource(StrEnum):
    """Source of a suggested label."""

    IDENTITY = "identity"
    ROSTER = "roster"
    SIMILAR_CLUSTER = "similar_cluster"
    NONE = "none"


@dataclass(frozen=True)
class BulkAcceptResult:
    """Typed count payload for bulk suggestion acceptance."""

    accepted_count: int
    skipped_count: int = 0


class SuggestionRefreshReason(StrEnum):
    """Reason code for refreshing suggestion candidates."""

    BOOTSTRAP = "bootstrap"
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
    """Represents a proposed identity-to-cluster assignment awaiting review.

    This intentionally carries a smaller payload than merge/name suggestions because
    the assignment flow only needs the active review state plus the similarity scores.
    """

    id: str
    identity_id: str
    cluster_id: str
    representative_similarity: float
    member_similarity: float
    status: SuggestionStatus
    evidence_generation: int = 0
    confidence_score: float | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    source_job_id: str | None = None


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
    survivor_cluster_id: str | None = None


@dataclass
class NameSuggestion:
    """Represents a proposed cluster label awaiting review.

    ``representatives`` carries domain ``ClusterRepresentative`` rows for preview
    thumbnails. HTTP thumb URL rewriting stays in the interface-adapter layer.
    """

    id: str
    cluster_id: str
    suggested_name: str
    source: SuggestedLabelSource
    status: SuggestionStatus
    confidence_score: float | None = None
    source_job_id: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    resolved_at: datetime | None = None
    last_exported_snapshot_id: str | None = None
    disposed_at: datetime | None = None
    representatives: list[ClusterRepresentative] = field(default_factory=list)
