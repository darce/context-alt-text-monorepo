"""
Repository protocol definitions for cluster persistence (Phase 5).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from recognition.domain.cluster import IdentityCluster
from recognition.domain.constraints import IdentityConstraint
from recognition.domain.identity import MediaIdentity
from recognition.domain.job import Job
from recognition.domain.maturity import ClusterMaturityInfo
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


class ClusterNotFoundError(Exception):
    """Raised when a requested cluster is not found."""


class ClusterRepository(Protocol):
    """Abstract interface for reading and writing cluster data."""

    # Core CRUD
    async def get_by_id(self, cluster_id: str) -> IdentityCluster | None: ...

    async def get_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        labeled_only: bool = False,
        search: str | None = None,
    ) -> list[IdentityCluster]: ...

    async def save(self, cluster: IdentityCluster) -> IdentityCluster: ...

    async def update(self, cluster: IdentityCluster) -> IdentityCluster: ...

    async def delete(self, cluster_id: str) -> None: ...

    async def refresh_centroids_view(self) -> None:
        """Refresh the materialized view for cluster centroids."""
        ...

    async def refresh_centroids_view_concurrent(self) -> None:
        """Refresh the materialized view concurrently."""
        ...

    # Clustering helpers
    async def get_unclustered(self, tenant_id: str) -> Sequence[MediaIdentity]: ...

    async def get_representative_count(self, cluster_id: str) -> int: ...

    async def get_all_representatives(self, cluster_id: str) -> Sequence[ClusterRepresentative]: ...

    async def get_maturity_info(self, cluster_id: str) -> ClusterMaturityInfo | None:
        """Fetch maturity information for a cluster.

        Args:
            cluster_id: Cluster to query.

        Returns:
            ClusterMaturityInfo or None if cluster not found.
        """
        ...

    async def get_member_embeddings(self, cluster_id: str) -> Sequence[Any]: ...

    async def get_member_identities(self, cluster_id: str) -> Sequence[MediaIdentity]:
        """Fetch identities that are members of a cluster."""
        ...

    async def get_members(self, cluster_id: str) -> list[IdentityMember]:
        """Fetch member records for a cluster."""
        ...

    async def assign_identity_to_cluster(self, identity: MediaIdentity, cluster_id: str) -> None: ...

    async def add_representative(self, representative: ClusterRepresentative) -> None: ...

    async def remove_representative(self, representative_id: str) -> None: ...

    async def clear_representatives(self, cluster_id: str) -> None:
        """Remove all stored representatives for a cluster."""
        ...

    async def count_labeled(self) -> int:
        """Count clusters with user-provided labels (not auto-generated)."""
        ...

    async def get_labeled_with_representatives(
        self,
        tenant_id: str,
    ) -> list[tuple[IdentityCluster, list[ClusterRepresentative]]]:
        """Fetch labeled clusters with representatives in single query.

        Uses eager loading to avoid N+1 query problem.

        Args:
            tenant_id: Tenant UUID string.

        Returns:
            List of (cluster, representatives) tuples.
        """
        ...

    async def get_top_unlabeled(
        self,
        tenant_id: str,
        limit: int = 10,
    ) -> list[IdentityCluster]:
        """Get unlabeled clusters sorted by identity_count descending.

        Args:
            tenant_id: Tenant scope.
            limit: Maximum clusters to return.

        Returns:
            Unlabeled clusters with highest member counts.
        """
        ...

    async def mark_representative_user_selected(
        self,
        representative_id: str,
        is_selected: bool = True,
    ) -> None:
        """Mark a representative as user-selected (pinned).

        Args:
            representative_id: UUID of the representative to mark.
            is_selected: True to pin, False to unpin.

        Raises:
            ValueError: If representative not found.
        """
        ...

    async def get_user_selected_representatives(
        self,
        cluster_id: str,
    ) -> Sequence[ClusterRepresentative]:
        """Get all user-selected representatives for a cluster.

        Args:
            cluster_id: Cluster UUID.

        Returns:
            List of pinned representatives.
        """
        ...

    async def confirm_provisional_representatives(self, cluster_id: str) -> int:
        """Mark all provisional representatives in a cluster as confirmed.

        Args:
            cluster_id: Cluster whose provisional reps should be confirmed.

        Returns:
            Number of representatives confirmed.
        """
        ...

    async def confirm_all_provisional_reps(self, tenant_id: str) -> int:
        """Mark all provisional representatives for a tenant as confirmed.

        Args:
            tenant_id: Tenant scope.

        Returns:
            Number of representatives confirmed.
        """
        ...

    async def cleanup_orphaned_provisional_reps(self, tenant_id: str) -> int:
        """Remove provisional reps from clusters with no active batch.

        Called during startup to clean up after crashes.

        Returns:
            Number of provisional reps removed.
        """
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

    async def add_member_if_not_exists(
        self, cluster_id: str, identity_id: str, similarity: float
    ) -> IdentityMember | None:
        """Add a member only if not already in this cluster.

        Returns the member if created, None if already exists.
        This prevents duplicate key errors when retrying assignments.
        """
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
class IdentityClusterBlock:
    """Durable block preventing auto-assignment to a specific cluster."""

    id: str
    tenant_id: str
    identity_id: str
    blocked_cluster_id: str
    reason: str | None = None
    created_at: datetime | None = None
    created_by_user_id: int | None = None
    expires_at: datetime | None = None


class IdentityClusterBlockRepository(Protocol):
    """Abstract interface for identity-cluster block persistence."""

    async def block(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        cluster_id: str,
        reason: str | None = None,
        created_by_user_id: int | None = None,
        expires_at: datetime | None = None,
    ) -> IdentityClusterBlock:
        """Persist a new block preventing auto-assignment."""
        ...

    async def add_block(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        blocked_cluster_id: str,
        reason: str | None = None,
        created_by_user_id: int | None = None,
        expires_at: datetime | None = None,
    ) -> IdentityClusterBlock:
        """Persist a new block (Legacy name)."""
        ...

    async def remove_block(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        blocked_cluster_id: str,
    ) -> bool:
        """Remove a block. Returns True if a block was removed."""
        ...

    async def get_blocks_for_identity(
        self,
        *,
        tenant_id: str,
        identity_id: str,
    ) -> list[IdentityClusterBlock]:
        """List all blocks for an identity in a tenant."""
        ...

    async def is_blocked(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        cluster_id: str,
    ) -> bool:
        """Return True if the identity is blocked from the given cluster."""
        ...


@dataclass(frozen=True)
class SuggestionCreateData:
    """Input data for creating a suggestion."""

    identity_id: str
    cluster_id: str
    representative_similarity: float
    member_similarity: float
    confidence_score: float
    source: str | None = None
    refreshed_at: datetime | None = None


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

    async def bulk_update_status(
        self,
        tenant_id: str,
        suggestion_ids: Sequence[str],
        status: SuggestionStatus,
    ) -> int:
        """Update status for multiple suggestions in one call.

        Args:
            tenant_id: Tenant UUID string.
            suggestion_ids: Suggestion UUIDs to update.
            status: Status to apply.

        Returns:
            Count of suggestions updated.
        """
        ...

    async def upsert_by_identity_cluster(
        self,
        tenant_id: str,
        payload: SuggestionCreateData,
    ) -> AssignmentSuggestion:
        """Create or update a suggestion for the identity+cluster pair.

        Args:
            tenant_id: Tenant UUID string.
            payload: Suggestion data (identity, cluster, scores).

        Returns:
            The created or updated suggestion.
        """
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


class IdentityConstraintRepository(Protocol):
    """Protocol for identity constraint persistence."""

    async def create_cannot_link(
        self,
        tenant_id: str,
        identity_a: str,
        identity_b: str,
        source: str,
        created_by_user_id: int | None = None,
    ) -> IdentityConstraint:
        """Create a new pairwise CANNOT_LINK constraint."""
        ...

    async def create(
        self,
        tenant_id: str,
        identity_a: str,
        identity_b: str,
        constraint_type: str,
        source: str,
        created_by_user_id: int | None = None,
    ) -> IdentityConstraint:
        """Create a new pairwise constraint.

        Args:
            tenant_id: Tenant scope.
            identity_a: First identity ID.
            identity_b: Second identity ID.
            constraint_type: MUST_LINK or CANNOT_LINK (as string).
            source: User action source (as string).
            created_by_user_id: Optional user ID.

        Returns:
            Created constraint with canonical ordering applied.

        Notes:
            Implementations may return the existing constraint if one already exists.
        """
        ...

    async def get(
        self,
        tenant_id: str,
        identity_a: str,
        identity_b: str,
    ) -> IdentityConstraint | None:
        """Get constraint between two identities (order-agnostic).

        Args:
            tenant_id: Tenant scope.
            identity_a: First identity ID.
            identity_b: Second identity ID.

        Returns:
            Constraint if exists, None otherwise.
        """
        ...

    async def get_all_for_identity(
        self,
        tenant_id: str,
        identity_id: str,
    ) -> list[IdentityConstraint]:
        """Get all constraints involving an identity.

        Args:
            tenant_id: Tenant scope.
            identity_id: Identity to query.

        Returns:
            List of constraints where identity_id is either a or b.
        """
        ...

    async def get_all(self, tenant_id: str) -> list[IdentityConstraint]:
        """Get all constraints for a tenant."""
        ...

    async def has_cannot_link(
        self,
        tenant_id: str,
        identity_id: str,
        cluster_member_ids: list[str],
    ) -> bool:
        """Check if identity has cannot-link with any cluster member.

        Args:
            tenant_id: Tenant scope.
            identity_id: Identity to check.
            cluster_member_ids: Members of target cluster.

        Returns:
            True if any cannot-link constraint exists.
        """
        ...
