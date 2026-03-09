"""
Request schemas for recognition HTTP API.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from recognition.interface_adapters.http.validation_utils import validate_uuid_format

# Alias for backward compatibility with external usage
_validate_uuid = validate_uuid_format


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


class RecoverOrphansRequest(BaseModel):
    """Request to re-cluster orphaned identities."""

    tenant_id: str

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


class CreateClusterForIdentityRequest(BaseModel):
    """Request to create a new labeled cluster containing a single identity."""

    tenant_id: str
    identity_id: str
    label: str

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


class ReassignIdentityRequest(BaseModel):
    """Request to reassign an identity to a different cluster.

    Used for:
    - Accepting inline suggestions (moving singleton to labeled cluster)
    - Moving identity between clusters (correction)
    - Removing from cluster (set target_cluster_id to null)
    """

    tenant_id: str
    identity_id: str
    target_cluster_id: str | None = None
    block_from_cluster: bool = True

    @field_validator("tenant_id", "identity_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)

    @field_validator("target_cluster_id")
    @classmethod
    def validate_target_cluster_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_uuid(v)


class SplitClusterRequest(BaseModel):
    """Request to split a cluster using hierarchical clustering.

    Args:
        tenant_id: The tenant that owns the cluster
        n_clusters: Number of clusters to split into.
                   0 = auto-detect based on similarity (default)
                   2+ = force exactly this many clusters
        anchor_identity_id: Identity ID used to keep labels with the selected person.
        split_mode: Optional split mode hint (ex: "anchor", "media").
        mode: Execution mode ("sync" or "async").
    """

    tenant_id: str
    n_clusters: int = Field(default=0, ge=0, description="0=auto-detect, 2+=fixed count")
    anchor_identity_id: str | None = None
    split_mode: str | None = Field(default=None, description="Optional split mode hint")
    mode: Literal["sync", "async"] = Field(default="sync", description="Execution mode")

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        return _validate_uuid(v)

    @field_validator("anchor_identity_id")
    @classmethod
    def validate_anchor_identity_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_uuid(v)


class PinRepresentativeRequest(BaseModel):
    """Request to pin/unpin a representative."""

    tenant_id: str
    is_pinned: bool = True

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        return _validate_uuid(v)


class AcknowledgeProjectionRequest(BaseModel):
    """Request to acknowledge that a snapshot version was projected locally."""

    snapshot_version: int = Field(..., gt=0)


__all__ = [
    "AnalyzeRequest",
    "ClusteringJobRequest",
    "RecoverOrphansRequest",
    "AssignOutlierRequest",
    "AcknowledgeProjectionRequest",
    "CreateClusterForIdentityRequest",
    "MergeClusterRequest",
    "PatchClusterRequest",
    "PinRepresentativeRequest",
    "ReassignIdentityRequest",
    "SplitClusterRequest",
    "SuggestionActionRequest",
]
