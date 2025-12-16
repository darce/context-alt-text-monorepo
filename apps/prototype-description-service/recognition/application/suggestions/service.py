"""
Suggestion service backed by SuggestionRepository.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.assignment import AssignmentCandidate
from recognition.domain.repositories import ClusterRepository, SuggestionCreateData, SuggestionRepository
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus
from recognition.observability.recognition_runs import RecognitionRunContext

logger = logging.getLogger(__name__)


class SuggestionService:
    """Coordinate suggestion persistence and expose simple operations."""

    def __init__(
        self,
        repository: SuggestionRepository,
        tenant_id: str,
        cluster_repository: ClusterRepository | None = None,
        *,
        session: AsyncSession | None = None,
        run_context: RecognitionRunContext | None = None,
    ) -> None:
        self._repository = repository
        self._tenant_id = tenant_id
        self._cluster_repository = cluster_repository
        self._session = session
        self._run_context = run_context

    def bind_run_context(self, context: RecognitionRunContext | None) -> None:
        """Attach or clear the active recognition run context.

        Args:
            context: Run context for emitting `recognition_events`, or None to disable event emission.
        """
        raise NotImplementedError("TODO: implement SuggestionService.bind_run_context")

    def _emit_suggestion_resolved_event(
        self,
        *,
        identity_id: str,
        cluster_id: str,
        resolution: str,
        suggestion_id: str | None,
        source: str,
    ) -> None:
        """Emit a `suggestion_resolved` event when a run context is available.

        Args:
            identity_id: Suggested identity UUID (string form).
            cluster_id: Cluster UUID (string form).
            resolution: "accepted" or "rejected".
            suggestion_id: Suggestion UUID when available.
            source: "manual_accept", "manual_reject", or "implicit_assignment".
        """
        raise NotImplementedError("TODO: emit suggestion_resolved recognition event")

    async def create(
        self, candidate: AssignmentCandidate, confidence: float | None = None
    ) -> AssignmentSuggestion | None:
        """Persist a suggestion derived from an assignment candidate.

        Suggestions are only created for user-labeled clusters to avoid presenting
        confusing UUID/unlabeled targets in the UI.
        """
        if self._cluster_repository is not None:
            cluster = await self._cluster_repository.get_by_id(candidate.cluster_id)
            if not cluster:
                logger.info("[suggestions] Skipping suggestion: cluster not found cluster_id=%s", candidate.cluster_id)
                return None
            if self._tenant_id and cluster.tenant_id.lower() != self._tenant_id.lower():
                logger.info("[suggestions] Skipping suggestion: tenant mismatch cluster_id=%s", candidate.cluster_id)
                return None
            if not cluster.user_confirmed or not cluster.label or cluster.label.startswith("cluster-"):
                logger.info(
                    "[suggestions] Skipping suggestion: cluster not user-labeled cluster_id=%s",
                    candidate.cluster_id,
                )
                return None

        similarity = candidate.discovery_similarity
        payload = SuggestionCreateData(
            identity_id=candidate.identity.id,
            cluster_id=candidate.cluster_id,
            representative_similarity=similarity,
            member_similarity=similarity,
            confidence_score=confidence if confidence is not None else similarity,
        )
        return await self._repository.create(self._tenant_id, payload)

    async def update_scores(
        self,
        suggestion_id: str,
        *,
        representative_similarity: float,
        member_similarity: float | None = None,
        confidence_score: float | None = None,
    ) -> AssignmentSuggestion | None:
        """Update similarity/confidence metrics for an existing pending suggestion."""
        member_similarity = representative_similarity if member_similarity is None else member_similarity
        confidence_score = representative_similarity if confidence_score is None else confidence_score
        try:
            return await self._repository.update_scores(
                self._tenant_id,
                suggestion_id,
                representative_similarity=representative_similarity,
                member_similarity=member_similarity,
                confidence_score=confidence_score,
            )
        except ValueError:
            logger.warning("[suggestions] Failed to update scores: suggestion_id=%s not found", suggestion_id)
            return None

    async def list_for_identity(self, identity_id: str) -> list[AssignmentSuggestion]:
        """Return suggestions for an identity, scoped to the service tenant."""
        return await self._repository.get_by_identity(self._tenant_id, identity_id)

    async def get_by_cluster(self, cluster_id: str) -> list[AssignmentSuggestion]:
        """Return suggestions for a cluster, scoped to the service tenant."""
        return await self._repository.get_by_cluster(self._tenant_id, cluster_id)

    async def accept(self, suggestion_id: str) -> AssignmentSuggestion | None:
        """Mark a suggestion as accepted."""
        try:
            suggestion = await self._repository.update_status(self._tenant_id, suggestion_id, SuggestionStatus.ACCEPTED)
            if suggestion:
                logger.info(
                    "[curation] ACCEPTED suggestion_id=%s identity=%s cluster=%s similarity=%.4f user_action=manual_accept",
                    suggestion.id,
                    suggestion.identity_id,
                    suggestion.cluster_id,
                    suggestion.representative_similarity,
                )
            return suggestion
        except ValueError:
            logger.warning("[curation] Failed to accept suggestion_id=%s: Not found", suggestion_id)
            return None  # Not found

    async def reject(self, suggestion_id: str) -> AssignmentSuggestion | None:
        """Mark a suggestion as rejected."""
        try:
            suggestion = await self._repository.update_status(self._tenant_id, suggestion_id, SuggestionStatus.REJECTED)
            if suggestion:
                logger.info(
                    "[curation] REJECTED suggestion_id=%s identity=%s cluster=%s similarity=%.4f user_action=manual_reject",
                    suggestion.id,
                    suggestion.identity_id,
                    suggestion.cluster_id,
                    suggestion.representative_similarity,
                )
            return suggestion
        except ValueError:
            logger.warning("[curation] Failed to reject suggestion_id=%s: Not found", suggestion_id)
            return None  # Not found

    async def list_pending(self, limit: int = 50, offset: int = 0) -> list[AssignmentSuggestion]:
        """List pending suggestions for the service tenant."""
        return await self._repository.list_pending(self._tenant_id, limit, offset)

    async def resolve_for_identity(self, identity_id: str, cluster_id: str, resolution: str = "accepted") -> int:
        """Resolve pending suggestions for an identity+cluster combination.

        Used when user confirms a suggestion via reassignment (not via suggestion accept).
        Returns the number of suggestions resolved.
        """
        suggestions = await self._repository.get_by_identity(self._tenant_id, identity_id)
        resolved_count = 0
        for suggestion in suggestions:
            if suggestion.cluster_id == cluster_id and suggestion.status == SuggestionStatus.PENDING:
                status = SuggestionStatus.ACCEPTED if resolution == "accepted" else SuggestionStatus.REJECTED
                await self._repository.update_status(self._tenant_id, suggestion.id, status)
                resolved_count += 1
                logger.info(
                    "[curation] RESOLVED suggestion_id=%s identity=%s cluster=%s action=%s source=implicit_assignment",
                    suggestion.id,
                    identity_id,
                    cluster_id,
                    resolution,
                )
        return resolved_count


__all__ = ["SuggestionService"]
