"""
Response schemas for recognition HTTP API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from recognition.interface_adapters.http.validation_utils import validate_uuid_format

# Alias for backward compatibility with external usage
_validate_uuid = validate_uuid_format


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

    model_config = ConfigDict(from_attributes=True)

    id: str
    media_id: str | int
    thumb_url: str | None = None
    is_pinned: bool = Field(False, alias="is_user_selected")

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

    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    label: str | None
    is_labeled: bool
    is_auto_label: bool
    identity_count: int
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
    type: Literal["analyze", "clustering", "curation", "split"]
    status: Literal["pending", "running", "completed", "failed"]
    progress: JobProgressResponse | None
    started_at: datetime
    finished_at: datetime | None
    message: str | None = None

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


class ConnectionPoolStats(BaseModel):
    """Connection pool statistics for monitoring.

    Attributes:
        size: Configured pool size (base connections).
        overflow: Configured max overflow connections.
        checked_out: Currently checked out connections.
        checked_in: Available connections in pool.
        overflow_count: Current overflow connections in use.
        total_capacity: Maximum possible connections.
        utilization_percent: Percentage of capacity in use.
    """

    size: int
    overflow: int
    checked_out: int
    checked_in: int
    overflow_count: int
    total_capacity: int
    utilization_percent: float


class HealthCheckResponse(BaseModel):
    """Health check response with database connectivity.

    Attributes:
        status: "healthy" or "degraded".
        database: Database connection status.
        pool_stats: Connection pool statistics.
        timestamp: ISO timestamp of check.
    """

    status: str
    database: str
    pool_stats: ConnectionPoolStats | None = None
    timestamp: str


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


class AsyncSplitClusterResponse(BaseModel):
    """Response when a split operation is queued for async execution.

    Returns:
        job_id: UUID of the queued clustering job.
        status: Initial job status ("pending").
        message: User-facing message.
    """

    job_id: str
    status: str = "pending"
    message: str = "Split operation queued"


__all__ = [
    "BboxResponse",
    "ClusterResponse",
    "ClusteringJobStatusResponse",
    "ConnectionPoolStats",
    "CreateClusterForIdentityResponse",
    "HealthCheckResponse",
    "HealthResponse",
    "IdentityResponse",
    "IdentitySuggestionsResponse",
    "JobProgressResponse",
    "JobStatusResponse",
    "AsyncSplitClusterResponse",
    "ReassignIdentityResponse",
    "RepresentativeResponse",
    "SplitClusterResponse",
    "SuggestionResponse",
]
