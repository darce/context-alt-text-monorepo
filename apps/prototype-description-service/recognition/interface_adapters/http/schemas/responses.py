"""
Response schemas for recognition HTTP API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from recognition.interface_adapters.http.validation_utils import validate_uuid_format

# Alias for backward compatibility with external usage
_validate_uuid = validate_uuid_format


class BboxResponse(BaseModel):
    """Bounding box response."""

    w: int
    h: int


class FaceBoxResponse(BaseModel):
    """Full bounding box response for face thumbnails."""

    x: int
    y: int
    width: int
    height: int


class ClusterMemberResponse(BaseModel):
    """Cluster member with identity details for review panels.

    Matches the frontend ClusterIdentity type with identity_id, media_id as int,
    similarity, confidence, full bbox, and optional thumbnail_url.
    """

    identity_id: str
    media_id: int
    similarity: float
    confidence: float
    bbox: FaceBoxResponse
    thumbnail_url: str | None = None
    media_url: str | None = None


class IdentityResponse(BaseModel):
    """Identity details returned from analysis."""

    id: str
    tenant_id: str
    media_id: str
    bbox: BboxResponse
    confidence: float
    thumbnail_url: str | None = None

    @field_validator("id", "tenant_id", "media_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


class PoseResponse(BaseModel):
    """Pose angles for a detected identity."""

    pitch: float
    yaw: float
    roll: float


class PoseBucketResponse(BaseModel):
    """Pose bucket summary for debug displays."""

    filled: int
    total: int
    current_bucket: tuple[int, int] | None = None


class DetectedIdentityDebugExtras(BaseModel):
    """Debug-only fields returned when include_debug=true."""

    pose: PoseResponse
    age: float
    gender: Literal["female", "male"]
    det_score: float
    bbox_area: int
    landmark_quality: float
    clustering_method: str | None = None
    clustering_algorithm: str | None = None
    similarity_threshold: float | None = None
    match_similarity: float | None = None
    representative_count: int | None = None
    pose_buckets: PoseBucketResponse | None = None


class RepresentativeResponse(BaseModel):
    """Cluster representative details."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    media_id: str | int
    thumb_url: str | None = None
    media_url: str | None = None
    bbox: FaceBoxResponse | None = None
    is_pinned: bool = Field(False, alias="is_user_selected")
    debug_metrics: dict[str, Any] | None = None

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
    suggested_label: str | None = None
    suggested_label_source: Literal["identity", "roster", "similar_cluster", "none"] | None = None
    suggested_label_confidence: float | None = None
    suggested_target_cluster_id: str | None = None

    @field_validator("id", "tenant_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


class OrphanRecoveryResponse(BaseModel):
    """Summary of an orphan recovery run."""

    orphans_found: int
    recovered: int
    suggested: int
    rejected: int
    clusters_created: int


class SuggestionResponse(BaseModel):
    """Suggestion details."""

    id: str
    identity_id: str
    cluster_id: str
    rep_similarity: float
    member_similarity: float | None
    status: Literal["pending", "accepted", "rejected"]
    cluster_label: str | None = None
    cluster_identity_count: int | None = None
    identity_media_id: int | None = None
    identity_media_url: str | None = None
    identity_thumbnail_url: str | None = None
    identity_bbox: FaceBoxResponse | None = None
    representative_media_id: int | None = None
    representative_media_url: str | None = None
    representative_thumbnail_url: str | None = None
    representative_bbox: FaceBoxResponse | None = None
    suggested_label: str | None = None
    suggested_label_source: Literal["identity", "roster", "similar_cluster", "none"] | None = None
    suggested_label_confidence: float | None = None
    cluster_thumbnails: list[str] = Field(default_factory=list)

    @field_validator("id", "identity_id", "cluster_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


class MergeSuggestionResponse(BaseModel):
    """Merge suggestion details."""

    id: str
    cluster_a_id: str
    cluster_b_id: str
    similarity: float
    status: Literal["pending", "accepted", "rejected"]
    cluster_a_label: str | None = None
    cluster_b_label: str | None = None
    cluster_a_identity_count: int | None = None
    cluster_b_identity_count: int | None = None
    cluster_a_representative_media_id: int | None = None
    cluster_a_representative_media_url: str | None = None
    cluster_a_representative_thumbnail_url: str | None = None
    cluster_a_representative_bbox: FaceBoxResponse | None = None
    cluster_b_representative_media_id: int | None = None
    cluster_b_representative_media_url: str | None = None
    cluster_b_representative_thumbnail_url: str | None = None
    cluster_b_representative_bbox: FaceBoxResponse | None = None

    @field_validator("id", "cluster_a_id", "cluster_b_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


class ClusterSuggestionMatch(BaseModel):
    """A suggested cluster match for an identity (frontend-compatible format)."""

    suggestion_id: str | None = None
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
    phase: Literal["queued", "detecting", "clustering", "complete"] | None = None
    images_processed: int | None = None
    faces_found: int | None = None
    clusters_created: int | None = None


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


class ClusterSnapshotMemberResponse(BaseModel):
    """Cluster member in the snapshot payload.

    Matches contracts/cluster-snapshot-api.md schema.
    """

    identity_uuid: str
    cluster_uuid: str
    attachment_id: int
    bbox: FaceBoxResponse
    image_width: int
    image_height: int
    thumb_path: str
    similarity: float


class ClusterSnapshotClusterResponse(BaseModel):
    """Cluster summary in the snapshot payload.

    Matches contracts/cluster-snapshot-api.md schema.
    """

    cluster_uuid: str
    label: str | None
    curation_state: Literal["active", "dismissed", "confirmed"]
    is_user_confirmed: bool
    identity_count: int
    representative_thumb_path: str | None


class ClusterSnapshotResponse(BaseModel):
    """Full snapshot response for tenant cluster state.

    Matches contracts/cluster-snapshot-api.md schema.
    """

    tenant_id: str
    snapshot_version: int
    generated_at: datetime
    clusters: list[ClusterSnapshotClusterResponse]
    members: list[ClusterSnapshotMemberResponse]


__all__ = [
    "BboxResponse",
    "ClusterResponse",
    "ClusteringJobStatusResponse",
    "ClusterSnapshotClusterResponse",
    "ClusterSnapshotMemberResponse",
    "ClusterSnapshotResponse",
    "ConnectionPoolStats",
    "CreateClusterForIdentityResponse",
    "HealthCheckResponse",
    "IdentityResponse",
    "IdentitySuggestionsResponse",
    "JobProgressResponse",
    "JobStatusResponse",
    "AsyncSplitClusterResponse",
    "ReassignIdentityResponse",
    "RepresentativeResponse",
    "SplitClusterResponse",
    "MergeSuggestionResponse",
    "SuggestionResponse",
]
