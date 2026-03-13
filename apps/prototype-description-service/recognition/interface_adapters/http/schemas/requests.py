"""
Request schemas for recognition HTTP API.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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
    expected_base_version: int = Field(default=0, ge=0)
    idempotency_key: str | None = None

    @field_validator("tenant_id", "target_cluster_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


class AssignOutlierRequest(BaseModel):
    """Request to manually assign an unclustered identity to a cluster."""

    tenant_id: str
    identity_id: str
    similarity: float = 0.0
    expected_base_version: int = Field(default=0, ge=0)
    idempotency_key: str | None = None

    @field_validator("tenant_id", "identity_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)


class CreateClusterForIdentityRequest(BaseModel):
    """Request to create a new labeled cluster containing a single identity."""

    tenant_id: str
    identity_id: str
    label: str
    desired_cluster_id: str | None = None
    expected_base_version: int = Field(default=0, ge=0)
    idempotency_key: str | None = None

    @field_validator("tenant_id", "identity_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return _validate_uuid(v)

    @field_validator("desired_cluster_id")
    @classmethod
    def validate_desired_cluster_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_uuid(v)


class SuggestionActionRequest(BaseModel):
    """Request to act on a suggestion."""

    tenant_id: str

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        return _validate_uuid(v)


class UpdateRetentionPolicyRequest(BaseModel):
    """Request to update the tenant retention mode."""

    retention_mode: str

    @field_validator("retention_mode")
    @classmethod
    def validate_retention_mode(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("retention_mode must not be empty")
        return normalized


class PurgeRequest(BaseModel):
    """Request to permanently delete retained machine-derived state."""

    scope: str = "disposed"
    confirm: bool = False

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("scope must not be empty")
        return normalized


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
    expected_base_version: int = Field(default=0, ge=0)
    idempotency_key: str | None = None

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
    desired_cluster_ids: list[str] | None = None
    idempotency_key: str | None = None

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

    @field_validator("desired_cluster_ids")
    @classmethod
    def validate_desired_cluster_ids(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [_validate_uuid(item) for item in v]


class SplitTopologyCommandRequest(BaseModel):
    """Request to execute split through the topology-command plane."""

    tenant_id: str
    cluster_id: str
    n_clusters: int = Field(default=0, ge=0, description="0=auto-detect, 2+=fixed count")
    anchor_identity_id: str | None = None
    split_mode: str | None = Field(default=None, description="Optional split mode hint")
    desired_cluster_ids: list[str] | None = None
    expected_base_version: int = Field(default=0, ge=0)
    idempotency_key: str

    @field_validator("tenant_id", "cluster_id")
    @classmethod
    def validate_topology_ids(cls, v: str) -> str:
        return _validate_uuid(v)

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("idempotency_key must not be empty")
        return normalized

    @field_validator("anchor_identity_id")
    @classmethod
    def validate_topology_anchor_identity_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_uuid(v)

    @field_validator("desired_cluster_ids")
    @classmethod
    def validate_topology_desired_cluster_ids(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [_validate_uuid(item) for item in v]

    @model_validator(mode="after")
    def validate_desired_cluster_ids_shape(self) -> SplitTopologyCommandRequest:
        if not self.desired_cluster_ids:
            return self

        if self.n_clusters < 2:
            raise ValueError("desired_cluster_ids are only allowed for fixed-count splits")

        if len(set(self.desired_cluster_ids)) != len(self.desired_cluster_ids):
            raise ValueError("desired_cluster_ids must be unique")

        expected_new_cluster_count = self.n_clusters - 1
        if len(self.desired_cluster_ids) != expected_new_cluster_count:
            raise ValueError(f"desired_cluster_ids must contain exactly {expected_new_cluster_count} ids")

        return self


class RevertMergeClusterRequest(BaseModel):
    """Request to restore a previously merged source cluster."""

    tenant_id: str
    target_cluster_id: str
    moved_identity_ids: list[str]
    desired_source_cluster_id: str | None = None
    source_label: str | None = None
    expected_base_version: int = Field(default=0, ge=0)
    idempotency_key: str | None = None

    @field_validator("tenant_id", "target_cluster_id")
    @classmethod
    def validate_revert_ids(cls, v: str) -> str:
        return _validate_uuid(v)

    @field_validator("desired_source_cluster_id")
    @classmethod
    def validate_desired_source_cluster_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_uuid(v)

    @field_validator("moved_identity_ids")
    @classmethod
    def validate_moved_identity_ids(cls, v: list[str]) -> list[str]:
        return [_validate_uuid(item) for item in v]

    @model_validator(mode="after")
    def validate_moved_identity_payload(self) -> RevertMergeClusterRequest:
        if not self.moved_identity_ids:
            raise ValueError("moved_identity_ids must not be empty")
        if len(set(self.moved_identity_ids)) != len(self.moved_identity_ids):
            raise ValueError("moved_identity_ids must be unique")
        return self


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
    snapshot_generation_id: str | None = None

    @field_validator("snapshot_generation_id")
    @classmethod
    def validate_snapshot_generation_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_uuid(v)


class UpdateRetentionPolicyRequest(BaseModel):
    """Request to update tenant retention policy."""

    retention_mode: str


class PurgeRequest(BaseModel):
    """Request to purge retained tenant state."""

    scope: str = "disposed"
    confirm: bool = False


__all__ = [
    "AnalyzeRequest",
    "ClusteringJobRequest",
    "RecoverOrphansRequest",
    "AssignOutlierRequest",
    "AcknowledgeProjectionRequest",
    "CreateClusterForIdentityRequest",
    "MediaItem",
    "MergeClusterRequest",
    "PatchClusterRequest",
    "PinRepresentativeRequest",
    "PurgeRequest",
    "ReassignIdentityRequest",
    "RevertMergeClusterRequest",
    "SplitClusterRequest",
    "SplitTopologyCommandRequest",
    "SuggestionActionRequest",
    "UpdateRetentionPolicyRequest",
]
