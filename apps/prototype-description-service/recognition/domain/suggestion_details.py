"""Domain-level detail models for suggestion review surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class FaceBox:
    """Bounding box for a detected face."""

    x: int
    y: int
    width: int
    height: int


@dataclass
class SuggestionDetails:
    """Suggestion details enriched with identity and cluster context."""

    id: str
    identity_id: str
    cluster_id: str
    representative_similarity: float
    member_similarity: float
    status: str
    confidence_score: float | None = None
    expires_at: datetime | None = None
    source_job_id: str | None = None
    cluster_label: str | None = None
    cluster_identity_count: int | None = None
    identity_media_id: int | None = None
    identity_media_url: str | None = None
    identity_bbox: FaceBox | None = None
    representative_media_id: int | None = None
    representative_media_url: str | None = None
    representative_bbox: FaceBox | None = None
    suggested_label: str | None = None
    suggested_label_source: str | None = None
    suggested_label_confidence: float | None = None


@dataclass
class MergeSuggestionDetails:
    """Merge suggestion details enriched with cluster context."""

    id: str
    cluster_a_id: str
    cluster_b_id: str
    similarity: float
    status: str
    confidence_score: float | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    source_job_id: str | None = None
    cluster_a_label: str | None = None
    cluster_b_label: str | None = None
    cluster_a_identity_count: int | None = None
    cluster_b_identity_count: int | None = None
    cluster_a_representative_media_id: int | None = None
    cluster_a_representative_media_url: str | None = None
    cluster_a_representative_bbox: FaceBox | None = None
    cluster_b_representative_media_id: int | None = None
    cluster_b_representative_media_url: str | None = None
    cluster_b_representative_bbox: FaceBox | None = None
    survivor_cluster_id: str | None = None
