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
    media_id: str
    thumb_url: str | None = None

    @field_validator("id", "media_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


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


class HealthResponse(BaseModel):
    """Recognition service health response."""

    service: str = "recognition"
    status: str = "ok"
    version: str | None = None


__all__ = [
    "BboxResponse",
    "ClusterResponse",
    "ClusteringJobStatusResponse",
    "HealthResponse",
    "IdentityResponse",
    "JobProgressResponse",
    "JobStatusResponse",
    "RepresentativeResponse",
    "SuggestionResponse",
]
