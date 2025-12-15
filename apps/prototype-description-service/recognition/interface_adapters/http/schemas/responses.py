"""
Response schemas for recognition HTTP API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _validate_uuid(value: str) -> str:
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        raise TypeError("id must be a string")
    if len(value) < 1:
        raise ValueError("id must be at least 1 character")
    if not all(ch.isalnum() or ch == "-" for ch in value):
        raise ValueError("id must contain only alphanumeric characters or dashes")
    return value


class BboxResponse(BaseModel):
    """Bounding box response."""

    w: int
    h: int


class IdentityResponse(BaseModel):
    """Identity details returned from analysis."""

    id: str
    tenant_id: str
    media_id: str
    bbox: BboxResponse
    confidence: float

    @field_validator("id", "tenant_id", "media_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


class RepresentativeResponse(BaseModel):
    """Cluster representative details."""

    id: str
    media_id: str | int
    thumb_url: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return _validate_uuid(v)

    @field_validator("media_id", mode="before")
    @classmethod
    def coerce_media_id(cls, v: str | int) -> str:
        """Accept integer or string media_id, return as string."""
        return str(v) if v is not None else ""


class ClusterResponse(BaseModel):
    """Cluster summary."""

    id: str
    tenant_id: str
    label: str | None
    is_labeled: bool
    member_count: int
    representatives: list[RepresentativeResponse] = Field(default_factory=list)

    @field_validator("id", "tenant_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


class SuggestionResponse(BaseModel):
    """Suggestion details."""

    id: str
    identity_id: str
    cluster_id: str
    rep_similarity: float
    member_similarity: float | None
    status: Literal["pending", "accepted", "rejected"]

    @field_validator("id", "identity_id", "cluster_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


class ClusterSuggestionMatch(BaseModel):
    """A suggested cluster match for an identity (frontend-compatible format)."""

    cluster_id: str
    label: str
    similarity: float
    identity_count: int

    @field_validator("cluster_id")
    @classmethod
    def validate_cluster_id(cls, v: str) -> str:
        return _validate_uuid(v)


class IdentitySuggestionsResponse(BaseModel):
    """Response for identity suggestions endpoint (frontend-compatible format)."""

    matches: list[ClusterSuggestionMatch]


class JobProgressResponse(BaseModel):
    """Job progress summary."""

    completed: int
    total: int


class JobStatusResponse(BaseModel):
    """Job status payload."""

    id: str
    type: Literal["analyze", "clustering"]
    status: Literal["pending", "running", "completed", "failed"]
    progress: JobProgressResponse | None
    started_at: datetime
    finished_at: datetime | None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return _validate_uuid(v)


class ClusteringJobStatusResponse(JobStatusResponse):
    """Clustering job status with clustering-specific fields."""

    clusters_created: int
    total_identities_clustered: int


class CreateClusterForIdentityResponse(BaseModel):
    """Response after creating a new cluster for a single identity."""

    cluster_id: str
    label: str
    identity_id: str
    message: str

    @field_validator("cluster_id", "identity_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


class HealthResponse(BaseModel):
    """Recognition service health response."""

    service: str = "recognition"
    status: str = "ok"
    version: str | None = None


class ReassignIdentityResponse(BaseModel):
    """Response after reassigning an identity to a cluster."""

    identity_id: str
    source_cluster_id: str | None = None
    target_cluster_id: str | None = None
    success: bool = True

    @field_validator("identity_id")
    @classmethod
    def validate_identity_id(cls, v: str) -> str:
        return _validate_uuid(v)


class SplitClusterResponse(BaseModel):
    """Response after splitting a cluster using hierarchical clustering."""

    # New format: lists of all new clusters
    new_cluster_ids: list[str] = Field(default_factory=list, description="IDs of newly created clusters")
    moved_counts: list[int] = Field(default_factory=list, description="Number of identities moved to each new cluster")

    # Legacy fields for backward compatibility
    new_cluster_id: str | None = Field(default=None, description="Legacy: first new cluster ID")
    moved_count: int = Field(default=0, description="Legacy: first moved count")


__all__ = [
    "BboxResponse",
    "ClusterResponse",
    "ClusteringJobStatusResponse",
    "CreateClusterForIdentityResponse",
    "HealthResponse",
    "IdentityResponse",
    "IdentitySuggestionsResponse",
    "JobProgressResponse",
    "JobStatusResponse",
    "ReassignIdentityResponse",
    "RepresentativeResponse",
    "SplitClusterResponse",
    "SuggestionResponse",
]
