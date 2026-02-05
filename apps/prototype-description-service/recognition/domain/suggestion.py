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


@dataclass
class MergeSuggestion:
    """Represents a proposed cluster-to-cluster merge awaiting review."""

    id: str
    cluster_a_id: str
    cluster_b_id: str
    similarity: float
    status: SuggestionStatus
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    refreshed_at: datetime | None = None
    source: str | None = None


@dataclass
class FaceBox:
    """Bounding box for a detected face."""

    x: int
    y: int
    width: int
    height: int


@dataclass
class SuggestionDetails:
    """Suggestion details with identity + cluster context for UI rendering."""

    id: str
    identity_id: str
    cluster_id: str
    representative_similarity: float
    member_similarity: float
    status: str
    cluster_label: str | None = None
    cluster_identity_count: int | None = None
    identity_media_id: int | None = None
    identity_media_url: str | None = None
    identity_thumbnail_url: str | None = None
    identity_bbox: FaceBox | None = None
    representative_media_id: int | None = None
    representative_media_url: str | None = None
    representative_thumbnail_url: str | None = None
    representative_bbox: FaceBox | None = None
    suggested_label: str | None = None
    suggested_label_source: SuggestedLabelSource | None = None
    suggested_label_confidence: float | None = None
    cluster_thumbnails: list[str] | None = None


@dataclass
class MergeSuggestionDetails:
    """Merge suggestion details with cluster context for UI rendering."""

    id: str
    cluster_a_id: str
    cluster_b_id: str
    similarity: float
    status: str
    created_at: datetime | None = None
    cluster_a_label: str | None = None
    cluster_b_label: str | None = None
    cluster_a_identity_count: int | None = None
    cluster_b_identity_count: int | None = None
    cluster_a_representative_media_id: int | None = None
    cluster_a_representative_media_url: str | None = None
    cluster_a_representative_thumbnail_url: str | None = None
    cluster_a_representative_bbox: FaceBox | None = None
    cluster_b_representative_media_id: int | None = None
    cluster_b_representative_media_url: str | None = None
    cluster_b_representative_thumbnail_url: str | None = None
    cluster_b_representative_bbox: FaceBox | None = None
