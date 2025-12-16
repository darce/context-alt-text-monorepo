"""
Repository protocol definitions for cluster persistence (Phase 5).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.job import Job
from recognition.domain.representative import ClusterRepresentative
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus


@dataclass(frozen=True)
class IdentityMember:
    """Domain representation of a cluster member."""

    id: str
    cluster_id: str
    identity_id: str
    similarity: float
    tenant_id: str | None = None
    assigned_at: datetime | None = None


@dataclass(frozen=True)
class MemberData:
    """Input data for bulk member creation."""

    identity_id: str
    similarity: float


class ClusterRepository(Protocol):
    """Abstract interface for reading and writing cluster data."""

    # Core CRUD
    async def get_by_id(self, cluster_id: str) -> IdentityCluster | None: ...

    async def get_by_tenant(self, tenant_id: str, *, limit: int = 100, offset: int = 0) -> list[IdentityCluster]: ...

    async def save(self, cluster: IdentityCluster) -> IdentityCluster: ...

    async def update(self, cluster: IdentityCluster) -> IdentityCluster: ...

    async def delete(self, cluster_id: str) -> None: ...

    async def refresh_centroids_view(self) -> None:
        """Refresh the materialized view for cluster centroids."""
        ...

    # Clustering helpers
    async def get_unclustered(self, tenant_id: str) -> Sequence[MediaIdentity]: ...

    async def get_representative_count(self, cluster_id: str) -> int: ...

    async def get_all_representatives(self, cluster_id: str) -> Sequence[Any]: ...

    async def get_member_embeddings(self, cluster_id: str) -> Sequence[Any]: ...

    async def get_member_identities(self, cluster_id: str) -> Sequence[MediaIdentity]:
        """Fetch identities that are members of a cluster."""
        ...

    async def assign_identity_to_cluster(self, identity: MediaIdentity, cluster_id: str) -> None: ...

    async def add_representative(self, representative: ClusterRepresentative) -> None: ...

    async def clear_representatives(self, cluster_id: str) -> None:
        """Remove all stored representatives for a cluster."""
        ...

    async def count_labeled(self) -> int:
        """Count clusters with user-provided labels (not auto-generated)."""
        ...


class MemberRepository(Protocol):
    """Abstract interface for cluster member persistence."""

    async def get_by_cluster(self, cluster_id: str) -> list[IdentityMember]:
        """Fetch all members belonging to a cluster."""
        ...

    async def get_by_identity_id(self, identity_id: str) -> list[IdentityMember]:
        """Fetch all member records for an identity (usually 0 or 1)."""
        ...

    async def add_member(self, cluster_id: str, identity_id: str, similarity: float) -> IdentityMember:
        """Add a single member to a cluster."""
        ...

    async def bulk_add_members(self, cluster_id: str, members: Sequence[MemberData]) -> list[IdentityMember]:
        """Bulk insert members for efficiency."""
        ...

    async def move_members(self, source_cluster_id: str, target_cluster_id: str) -> int:
        """Reassign all members from one cluster to another."""
        ...

    async def remove_member(self, member_id: str) -> None:
        """Remove a member from a cluster."""
        ...

    async def remove_by_identity_id(self, identity_id: str) -> bool:
        """Remove member record(s) for an identity. Returns True if any were removed."""
        ...


@dataclass(frozen=True)
class SuggestionCreateData:
    """Input data for creating a suggestion."""

    identity_id: str
    cluster_id: str
    representative_similarity: float
    member_similarity: float
    confidence_score: float


class SuggestionRepository(Protocol):
    """Abstract interface for suggestion persistence."""

    async def create(self, tenant_id: str, payload: SuggestionCreateData) -> AssignmentSuggestion:
        """Persist a new suggestion."""
        ...

    async def update_scores(
        self,
        tenant_id: str,
        suggestion_id: str,
        *,
        representative_similarity: float,
        member_similarity: float,
        confidence_score: float,
    ) -> AssignmentSuggestion:
        """Update similarity/confidence scores for an existing suggestion."""
        ...

    async def get_by_identity(self, tenant_id: str, identity_id: str) -> list[AssignmentSuggestion]:
        """List suggestions for an identity within a tenant."""
        ...

    async def get_by_cluster(self, tenant_id: str, cluster_id: str) -> list[AssignmentSuggestion]:
        """List suggestions for a cluster within a tenant."""
        ...

    async def update_status(self, tenant_id: str, suggestion_id: str, status: SuggestionStatus) -> AssignmentSuggestion:
        """Update suggestion resolution state."""
        ...

    async def list_pending(self, tenant_id: str, limit: int, offset: int) -> list[AssignmentSuggestion]:
        """List pending suggestions for a tenant."""
        ...


class JobRepository(Protocol):
    """Abstract interface for job persistence."""

    async def save(self, job: Job) -> Job:
        """Persist a job record."""
        ...

    async def get(self, job_id: str) -> Job | None:
        """Fetch a job by ID."""
        ...

    async def update(self, job: Job) -> Job:
        """Update a job's state."""
        ...
