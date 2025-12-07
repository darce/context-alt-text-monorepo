"""
Suggestion service backed by SuggestionRepository.
"""

from __future__ import annotations

from recognition.application.assignment import AssignmentCandidate
from recognition.domain.repositories import SuggestionCreateData, SuggestionRepository
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus


class SuggestionService:
    """Coordinate suggestion persistence and expose simple operations."""

    def __init__(self, repository: SuggestionRepository, tenant_id: str) -> None:
        self._repository = repository
        self._tenant_id = tenant_id

    async def create(self, candidate: AssignmentCandidate, confidence: float | None = None) -> AssignmentSuggestion:
        """Persist a suggestion derived from an assignment candidate."""
        similarity = candidate.discovery_similarity
        payload = SuggestionCreateData(
            identity_id=candidate.identity.id,
            cluster_id=candidate.cluster_id,
            representative_similarity=similarity,
            member_similarity=similarity,
            confidence_score=confidence if confidence is not None else similarity,
        )
        return await self._repository.create(self._tenant_id, payload)

    async def list_for_identity(self, identity_id: str) -> list[AssignmentSuggestion]:
        """Return suggestions for an identity, scoped to the service tenant."""
        return await self._repository.get_by_identity(self._tenant_id, identity_id)

    async def get_by_cluster(self, cluster_id: str) -> list[AssignmentSuggestion]:
        """Return suggestions for a cluster, scoped to the service tenant."""
        return await self._repository.get_by_cluster(self._tenant_id, cluster_id)

    async def accept(self, suggestion_id: str) -> AssignmentSuggestion | None:
        """Mark a suggestion as accepted."""
        try:
            return await self._repository.update_status(self._tenant_id, suggestion_id, SuggestionStatus.ACCEPTED)
        except ValueError:
            return None  # Not found

    async def reject(self, suggestion_id: str) -> AssignmentSuggestion | None:
        """Mark a suggestion as rejected."""
        try:
            return await self._repository.update_status(self._tenant_id, suggestion_id, SuggestionStatus.REJECTED)
        except ValueError:
            return None  # Not found

    async def list_pending(self, limit: int = 50, offset: int = 0) -> list[AssignmentSuggestion]:
        """List pending suggestions for the service tenant."""
        return await self._repository.list_pending(self._tenant_id, limit, offset)


__all__ = ["SuggestionService"]
