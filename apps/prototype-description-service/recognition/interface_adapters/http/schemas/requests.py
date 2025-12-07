"""
Request schemas for recognition HTTP API.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _validate_uuid(value: str) -> str:
    """Validate that a value resembles the expected ID format."""
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        raise TypeError("id must be a string")
    if len(value) < 1:
        raise ValueError("id must be at least 1 character")
    if not all(ch.isalnum() or ch == "-" for ch in value):
        raise ValueError("id must contain only alphanumeric characters or dashes")
    return value


class MediaItem(BaseModel):
    """WordPress-compatible media item descriptor."""

    media_id: int
    media_url: str


class AnalyzeRequest(BaseModel):
    """Request to analyze media for faces."""

    media_ids: list[str] | None = Field(default=None)
    media_items: list[MediaItem] | None = Field(default=None)
    tenant_id: str

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        return _validate_uuid(v)


class ClusteringJobRequest(BaseModel):
    """Request to trigger clustering job."""

    tenant_id: str
    mode: Literal["sync", "async"] = "sync"

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        return _validate_uuid(v)


class PatchClusterRequest(BaseModel):
    """Request to update cluster attributes."""

    tenant_id: str
    label: str | None = None

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        return _validate_uuid(v)


class MergeClusterRequest(BaseModel):
    """Request to merge a source cluster into a target cluster."""

    tenant_id: str
    target_cluster_id: str
    target_label: str | None = None

    @field_validator("tenant_id", "target_cluster_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


class AssignOutlierRequest(BaseModel):
    """Request to manually assign an unclustered identity to a cluster."""

    tenant_id: str
    identity_id: str
    similarity: float = 0.0

    @field_validator("tenant_id", "identity_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


class SuggestionActionRequest(BaseModel):
    """Request to act on a suggestion."""

    tenant_id: str

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        return _validate_uuid(v)


__all__ = [
    "AnalyzeRequest",
    "ClusteringJobRequest",
    "AssignOutlierRequest",
    "MergeClusterRequest",
    "PatchClusterRequest",
    "SuggestionActionRequest",
]
