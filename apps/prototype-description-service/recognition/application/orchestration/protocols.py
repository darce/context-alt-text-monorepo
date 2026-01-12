"""
Shared protocols for the orchestration layer to avoid circular dependencies and duplication.
"""

from __future__ import annotations

from typing import Protocol

from recognition.application.assignment import AssignmentCandidate
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionRefreshReason


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
