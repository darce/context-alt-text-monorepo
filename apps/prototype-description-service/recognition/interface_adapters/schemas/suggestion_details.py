"""
Transport DTOs for suggestion detail payloads.

These shapes are used by repository enrichment and HTTP response mapping.
"""

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
    suggested_label_source: str | None = None
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
