"""
Shared protocols for the orchestration layer to avoid circular dependencies and duplication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from recognition.application.assignment import AssignmentCandidate
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionRefreshReason

if TYPE_CHECKING:
    from recognition.application.settings.clustering import HACSettings
    from recognition.domain.repositories import ConstrainedHACProtocol


class SuggestionServiceProtocol(Protocol):
    """Protocol for creating and resolving assignment suggestions."""

    async def create(self, candidate: AssignmentCandidate, confidence: float | None = None) -> None:
        """Create a suggestion record for later human review."""
        ...

    async def update_scores(
        self,
        suggestion_id: str,
        *,
        representative_similarity: float,
        member_similarity: float | None = None,
        confidence_score: float | None = None,
    ) -> AssignmentSuggestion | None:
        """Update similarity/confidence metrics for an existing suggestion."""
        ...

    async def resolve_for_identity(
        self,
        identity_id: str,
        cluster_id: str,
        resolution: str,
        source: str = "manual_curation",
    ) -> bool:
        """Accept or reject a single suggestion for an identity."""
        ...

    async def resolve_for_identity_exclusive(
        self,
        identity_id: str,
        accepted_cluster_id: str,
        reason: str = "manual_assign",
    ) -> int:
        """Accept one assignment and reject all other suggestions for an identity."""
        ...


class SuggestionRefreshServiceProtocol(Protocol):
    """Protocol for refreshing and surfacing suggestions."""

    async def refresh_for_identity(
        self,
        *,
        identity_id: str,
        reason: SuggestionRefreshReason,
    ) -> list[AssignmentSuggestion]:
        """Refresh suggestions for a specific identity."""
        ...

    async def refresh_for_cluster(self, cluster_id: str) -> int:
        """Refresh suggestions for a whole cluster."""
        ...

    async def surface_for_newly_labeled_cluster(self, cluster_id: str) -> int:
        """Surface suggestions after a cluster is user-labeled."""
        ...


class MergeSuggestionServiceProtocol(Protocol):
    """Protocol for generating cluster-to-cluster merge suggestions."""

    async def generate_for_tenant(self, tenant_id: str) -> int:
        """Generate merge suggestions for a tenant after clustering."""
        ...

    async def generate_singleton_merge_suggestions(
        self,
        tenant_id: str,
        *,
        constrained_hac: ConstrainedHACProtocol | None,
        hac_settings: HACSettings | None,
        limit: int = 1000,
    ) -> int:
        """Generate merge suggestions for singleton clusters using HAC."""
        ...

    async def delete_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
        """Delete pending merge suggestions involving the provided cluster."""
        ...
