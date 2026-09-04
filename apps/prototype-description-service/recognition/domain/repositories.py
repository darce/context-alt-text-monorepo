"""
Repository protocol definitions for cluster persistence (Phase 5).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from recognition.domain.cluster import IdentityCluster
from recognition.domain.constraints import IdentityConstraint
from recognition.domain.identity import MediaIdentity
from recognition.domain.job import Job, ProjectionStatus
from recognition.domain.maturity import ClusterMaturityInfo
from recognition.domain.representative import ClusterRepresentative
from recognition.domain.suggestion import AssignmentSuggestion, MergeSuggestion, SuggestionStatus
from recognition.domain.suggestion_details import MergeSuggestionDetails, SuggestionDetails

if TYPE_CHECKING:
    from recognition.application.settings.clustering import MaturitySettings


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

    def __init__(self, cluster_id: str) -> None:
        super().__init__(f"Cluster not found: {cluster_id}")
        self.cluster_id = cluster_id


class ClusterRepository(Protocol):
    """Abstract interface for reading and writing cluster data."""

    # Core CRUD
    async def get_by_id(self, cluster_id: str) -> IdentityCluster | None: ...

    async def get_by_ids(self, cluster_ids: Sequence[str]) -> list[IdentityCluster]:
        """Fetch multiple clusters in one query (batched ``get_by_id``)."""
        ...

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

    async def refresh_centroids_view_concurrent(self) -> bool:
        """Refresh the materialized view concurrently. Returns True on success, False on failure."""
        ...

    # Clustering helpers
    async def get_unclustered(self, tenant_id: str) -> Sequence[MediaIdentity]: ...

    async def get_representative_count(self, cluster_id: str) -> int: ...

    async def get_all_representatives(self, cluster_id: str) -> Sequence[ClusterRepresentative]: ...

    async def get_maturity_info(self, cluster_id: str, *, settings: MaturitySettings) -> ClusterMaturityInfo | None:
        """Fetch maturity information for a cluster.

        Args:
            cluster_id: Cluster to query.
            settings: Maturity settings to apply.

        Returns:
            ClusterMaturityInfo or None if cluster not found.
        """
        ...

    async def get_curriculum_t(self, cluster_id: str) -> float | None:
        """Fetch the curriculum bias parameter for a cluster.

        Args:
            cluster_id: Cluster to query.

        Returns:
            Curriculum bias value or None if cluster not found.
        """
        ...

    async def set_curriculum_t(self, cluster_id: str, value: float) -> None:
        """Persist the curriculum bias parameter for a cluster.

        Args:
            cluster_id: Cluster to update.
            value: Curriculum bias value to store.
        """
        ...

    async def update_curriculum_t_ema(self, cluster_id: str, new_similarity: float, alpha: float) -> None:
        """Atomically apply exponential moving-average update to curriculum_t.

        Computes new_value = alpha * new_similarity + (1 - alpha) * current_value
        using a single SQL UPDATE expression so there is no read-modify-write race.
        If curriculum_t is NULL the new_similarity is used as the initial value.

        Args:
            cluster_id: Cluster to update.
            new_similarity: New similarity value to blend in.
            alpha: EMA smoothing factor in (0, 1].
        """
        ...

    async def get_member_embeddings(self, cluster_id: str) -> Sequence[np.ndarray]: ...

    async def get_representative_embeddings(self, cluster_id: str) -> Sequence[np.ndarray]:
        """Fetch representative embeddings for a cluster."""
        ...

    async def get_representative_embeddings_with_model(self, cluster_id: str) -> tuple[list[np.ndarray], str | None]:
        """Fetch representative embeddings plus the chosen embedding_model (FIR23-01).

        Returns:
            ``(embeddings, chosen_embedding_model)`` where ``chosen_embedding_model``
            is the model space selected by ``_filter_embedding_pairs_to_single_model``
            for the returned vectors, or ``None`` when nothing was returned / no
            model could be determined.
        """
        ...

    async def get_representative_embeddings_with_quality(
        self, cluster_id: str
    ) -> tuple[list[np.ndarray], str | None, list[tuple[float | None, float | None, float | None]]]:
        """Same ranking rows as ``get_representative_embeddings_with_model`` plus quality.

        Returns:
            ``(embeddings, chosen_embedding_model, qualities)`` where each quality
            triple is ``(representative_quality, identity_quality, detection_confidence)``
            aligned 1:1 with ``embeddings``. Missing metrics are ``None`` (callers
            fail closed — None stays None). Legacy ``_to_domain`` debug_metrics
            aliased identity_quality as ``landmark_quality`` (or 1.0).
        """
        ...

    async def get_member_fallback_embeddings(self, cluster_id: str, limit: int = 4) -> Sequence[np.ndarray]:
        """Fetch top member embeddings for fallback similarity checks."""
        ...

    async def get_member_fallback_embeddings_with_model(
        self, cluster_id: str, limit: int = 4
    ) -> tuple[list[np.ndarray], str | None]:
        """Fetch top member fallback embeddings plus the chosen embedding_model.

        Returns:
            ``(embeddings, chosen_embedding_model)`` — same semantics as
            ``get_representative_embeddings_with_model``.
        """
        ...

    async def get_member_fallback_embeddings_with_quality(
        self, cluster_id: str, limit: int = 4
    ) -> tuple[list[np.ndarray], str | None, list[tuple[float | None, float | None, float | None]]]:
        """Same member-fallback rows as the with_model loader plus quality triples.

        Triple slots are ``(representative_quality, identity_quality,
        detection_confidence)``. This path has no representative row, so
        representative_quality is NULL. Fail closed: None stays None (unlike
        legacy debug_metrics ``landmark_quality`` alias which used ``or 1.0``).
        """
        ...

    async def get_member_identities(self, cluster_id: str) -> Sequence[MediaIdentity]:
        """Fetch identities that are members of a cluster."""
        ...

    async def get_member_identity_count(self, cluster_id: str) -> int:
        """Count identities that are members of a cluster."""
        ...

    async def get_member_identities_with_similarity(
        self,
        cluster_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[Any, float]]:
        """Fetch cluster members and similarity scores for review UIs."""
        ...

    async def get_member_identities_for_clusters(
        self, cluster_ids: Sequence[str]
    ) -> Mapping[str, Sequence[MediaIdentity]]:
        """Fetch identities that are members of any of the provided clusters.

        Returns:
            Mapping from cluster_id to member identities.
        """
        ...

    async def get_members(self, cluster_id: str) -> list[IdentityMember]:
        """Fetch member records for a cluster."""
        ...

    async def get_roster_entry_name(self, roster_id: str) -> str | None:
        """Resolve a roster entry ID to its display name."""
        ...

    async def get_singleton_identities(
        self,
        tenant_id: str,
        *,
        limit: int | None = None,
    ) -> list[MediaIdentity]:
        """Fetch identities that belong to singleton clusters for a tenant."""
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

    async def get_confirmed_labeled(self, tenant_id: str) -> list[IdentityCluster]:
        """Fetch confirmed, human-labeled clusters for tenant."""
        ...

    async def get_unlabeled_created_after(self, tenant_id: str, *, minutes_ago: int) -> list[IdentityCluster]:
        """Fetch recently created unlabeled clusters for backfill fallback."""
        ...

    async def get_top_unlabeled(
        self,
        tenant_id: str,
        limit: int = 10,
        min_identity_count: int = 2,
    ) -> list[IdentityCluster]:
        """Get unlabeled clusters sorted by identity_count descending.

        Args:
            tenant_id: Tenant scope.
            limit: Maximum clusters to return.
            min_identity_count: Minimum identity count (default 2 to skip singletons).

        Returns:
            Unlabeled clusters with highest member counts.
        """
        ...

    async def dismiss_cluster(self, cluster_id: str) -> bool:
        """Mark a cluster as dismissed from the naming queue.

        Args:
            cluster_id: UUID of the cluster to dismiss.

        Returns:
            True if a cluster was found and dismissed, False otherwise.
        """
        ...

    async def undismiss_cluster(self, cluster_id: str) -> bool:
        """Clear the dismissed flag on a cluster.

        Args:
            cluster_id: UUID of the cluster to undismiss.

        Returns:
            True if a cluster was found and undismissed, False otherwise.
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

    async def get_snapshot(
        self, tenant_id: str, *, stamp_export: bool = False
    ) -> tuple[list[IdentityCluster], list[tuple[IdentityMember, MediaIdentity]], int, str | None]:
        """Get complete cluster snapshot for tenant projection.

        Args:
            tenant_id: Tenant UUID string.

        Returns:
            Tuple of (clusters, member_tuples, snapshot_version, snapshot_generation_id) where:
            - clusters: All clusters for the tenant
            - member_tuples: List of (IdentityMember, MediaIdentity) pairs
            - snapshot_version: Monotonic version number (unix timestamp of max cluster updated_at)
            - snapshot_generation_id: Stable UUID associated with the exported snapshot when stamping is enabled
        """
        ...

    async def get_delta(
        self,
        tenant_id: str,
        *,
        since_version: int,
    ) -> tuple[list[IdentityCluster], list[tuple[IdentityMember, MediaIdentity]], int]:
        """Get a version-filtered cluster delta for tenant projection."""
        ...

    async def get_members_by_cluster_ids(
        self, tenant_id: str, cluster_ids: Sequence[str]
    ) -> list[tuple[IdentityMember, MediaIdentity]]:
        """Get member+identity tuples for the requested clusters only."""
        ...

    async def get_clusters_by_ids(self, tenant_id: str, cluster_ids: Sequence[str]) -> list[IdentityCluster]:
        """Get cluster summaries for the requested cluster ids only."""
        ...

    async def get_snapshot_version(self, tenant_id: str) -> int:
        """Get the tenant snapshot version without loading full snapshot payloads."""
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

    async def bulk_add_members_if_not_exists(
        self, cluster_id: str, members: Sequence[MemberData]
    ) -> tuple[list[IdentityMember], int]:
        """Bulk insert members using ON CONFLICT DO NOTHING semantics.

        Returns a tuple of (created_members, skipped_count) for observability.
        Prevents duplicate-key errors when retrying or when planner overlap occurs.
        """
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
    expires_at: datetime | None = None
    source_job_id: str | None = None


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

    async def list_for_identities(
        self,
        tenant_id: str,
        identity_ids: Sequence[str],
        *,
        top_k: int,
    ) -> list[SuggestionDetails]:
        """Top-k pending labeled-cluster suggestions per identity (one windowed query)."""
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

    async def list_pending_with_details(self, tenant_id: str, limit: int, offset: int) -> list[SuggestionDetails]:
        """List pending suggestions with identity and cluster details."""
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


@dataclass(frozen=True)
class MergeSuggestionCreateData:
    """Input data for creating a cluster merge suggestion."""

    cluster_a_id: str
    cluster_b_id: str
    similarity: float
    confidence_score: float | None = None
    source: str | None = None
    refreshed_at: datetime | None = None
    expires_at: datetime | None = None
    source_job_id: str | None = None
    survivor_cluster_id: str | None = None


class MergeSuggestionRepository(Protocol):
    """Abstract interface for cluster merge suggestion persistence."""

    async def upsert_pending(self, tenant_id: str, payload: MergeSuggestionCreateData) -> MergeSuggestion:
        """Create or update a pending merge suggestion for a cluster pair."""
        ...

    async def list_pending_with_details(
        self,
        tenant_id: str,
        limit: int,
        offset: int,
    ) -> list[MergeSuggestionDetails]:
        """Return pending merge suggestions with cluster details."""
        ...

    async def update_status(
        self,
        tenant_id: str,
        suggestion_id: str,
        status: SuggestionStatus,
    ) -> MergeSuggestion:
        """Update the resolution of a merge suggestion."""
        ...

    async def get_by_id(self, tenant_id: str, suggestion_id: str) -> MergeSuggestion | None:
        """Fetch a merge suggestion by id."""
        ...

    async def delete_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
        """Delete pending merge suggestions involving the provided cluster.

        Args:
            tenant_id: Tenant UUID string.
            cluster_id: Cluster UUID string to match.

        Returns:
            Number of pending suggestions deleted.
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

    async def get_followup_clustering_job(self, scan_job_id: str) -> Job | None:
        """Return the newest clustering job linked to a scan job, if one exists."""
        ...

    async def get_active_clustering_job_for_tenant(self, tenant_id: str) -> Job | None:
        """Return the newest pending/running clustering job for a tenant, if one exists."""
        ...

    async def get_latest_completed_clustering_job_for_tenant(self, tenant_id: str) -> Job | None:
        """Return the newest completed clustering job for a tenant, if one exists."""
        ...

    async def get_projection_status(self, job_id: str, tenant_id: str) -> ProjectionStatus | None:
        """Return projection metadata for a clustering job when available."""
        ...

    async def record_projection_acknowledgement(
        self,
        *,
        job_id: str,
        tenant_id: str,
        snapshot_version: int,
        acknowledged_at: datetime,
    ) -> ProjectionStatus | None:
        """Persist a projection acknowledgement for the provided job."""
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


class ConstrainedHACProtocol(Protocol):
    """Protocol for constrained hierarchical agglomerative clustering.

    This follows Apple's two-pass strategy: after conservative first-pass
    clustering (HDBSCAN), HAC merges remaining singletons using cannot-link
    constraints from user feedback.
    """

    async def refine_clusters(
        self,
        *,
        tenant_id: uuid.UUID,
        embeddings: dict[uuid.UUID, np.ndarray],
        distance_threshold_override: float | None = None,
    ) -> dict[uuid.UUID, uuid.UUID]:
        """Cluster embeddings using constrained HAC.

        Args:
            tenant_id: Tenant scope for constraint lookup.
            embeddings: Map of identity_id -> face embedding vector.
            distance_threshold_override: If provided, use this instead of default threshold.

        Returns:
            Map of identity_id -> cluster_id for merged identities.
            Identities not assigned to a cluster are omitted.
        """
        ...
