"""
Suggestion service backed by SuggestionRepository.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RecognitionRun
from recognition.application.assignment import AssignmentCandidate
from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.eligibility import is_eligible_cluster
from recognition.application.suggestions.label_inference import infer_suggested_label
from recognition.config import get_settings as get_recognition_settings
from recognition.domain.repositories import (
    ClusterRepository,
    IdentityClusterBlockRepository,
    IdentityConstraintRepository,
    SuggestionCreateData,
    SuggestionRepository,
)
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus
from recognition.interface_adapters.schemas.suggestion_details import SuggestionDetails
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
        block_repository: IdentityClusterBlockRepository | None = None,
        constraint_repository: IdentityConstraintRepository | None = None,
        settings: ClusteringSettings | None = None,
    ) -> None:
        self._repository = repository
        self._tenant_id = tenant_id
        self._cluster_repository = cluster_repository
        self._session = session
        self._run_context = run_context
        self._block_repository = block_repository
        self._constraint_repository = constraint_repository
        self._settings = settings or get_recognition_settings().clustering

    def bind_run_context(self, context: RecognitionRunContext | None) -> None:
        """Attach or clear the active recognition run context.

        Args:
            context: Run context for emitting `recognition_events`, or None to disable event emission.
        """
        self._run_context = context

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
        if self._run_context is None:
            return

        self._run_context.add_event(
            event_type="suggestion_resolved",
            identity_id=identity_id,
            cluster_id=cluster_id,
            payload={
                "resolution": resolution,
                "outcome_cluster_id": cluster_id,
                "suggestion_id": suggestion_id,
                "source": source,
            },
        )

    async def _ensure_run_context(self) -> None:
        if self._run_context is not None:
            return
        if self._session is None:
            return
        try:
            tenant_uuid = uuid.UUID(str(self._tenant_id))
        except ValueError:
            return

        stmt = (
            select(RecognitionRun.id)
            .where(RecognitionRun.tenant_id == tenant_uuid)
            .order_by(RecognitionRun.created_at.desc())
            .limit(1)
        )
        run_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if run_id is None:
            return
        self._run_context = RecognitionRunContext(session=self._session, tenant_id=tenant_uuid, run_id=run_id)

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

            if not is_eligible_cluster(cluster, self._tenant_id):
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

    async def resolve_for_identity_exclusive(
        self,
        *,
        identity_id: str,
        accepted_cluster_id: str,
        reason: str | None = None,
    ) -> int:
        """Resolve suggestions for an identity, accepting one and rejecting the rest.

        Args:
            identity_id: Identity UUID string to resolve suggestions for.
            accepted_cluster_id: Cluster UUID string to accept.
            reason: Optional reason for audit logging.

        Returns:
            Count of suggestions updated.

        Raises:
            NotImplementedError: Until resolution logic is implemented.
        """
        suggestions = await self._repository.get_by_identity(self._tenant_id, identity_id)
        if not suggestions:
            return 0

        pending = [s for s in suggestions if s.status == SuggestionStatus.PENDING]
        if not pending:
            return 0

        accepted_id = None
        for suggestion in pending:
            if suggestion.cluster_id == accepted_cluster_id:
                accepted_id = suggestion.id
                break

        updated = 0
        if accepted_id is not None:
            await self._repository.update_status(self._tenant_id, accepted_id, SuggestionStatus.ACCEPTED)
            updated += 1
            await self._ensure_run_context()
            self._emit_suggestion_resolved_event(
                identity_id=identity_id,
                cluster_id=accepted_cluster_id,
                resolution="accepted",
                suggestion_id=accepted_id,
                source=reason or "manual_accept",
            )

        reject_ids = [s.id for s in pending if s.id != accepted_id]
        if reject_ids:
            updated += await self._repository.bulk_update_status(
                self._tenant_id,
                reject_ids,
                SuggestionStatus.REJECTED,
            )
            await self._ensure_run_context()
            for suggestion_id in reject_ids:
                self._emit_suggestion_resolved_event(
                    identity_id=identity_id,
                    cluster_id=accepted_cluster_id,
                    resolution="rejected",
                    suggestion_id=suggestion_id,
                    source=reason or "manual_reject",
                )

        return updated

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
                await self._ensure_run_context()
                self._emit_suggestion_resolved_event(
                    identity_id=suggestion.identity_id,
                    cluster_id=suggestion.cluster_id,
                    resolution="accepted",
                    suggestion_id=suggestion.id,
                    source="manual_accept",
                )
            return suggestion
        except ValueError:
            logger.warning("[curation] Failed to accept suggestion_id=%s: Not found", suggestion_id)
            return None  # Not found

    async def reject(self, suggestion_id: str) -> AssignmentSuggestion | None:
        """Mark a suggestion as rejected and create negative constraints."""
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
                await self._ensure_run_context()
                self._emit_suggestion_resolved_event(
                    identity_id=suggestion.identity_id,
                    cluster_id=suggestion.cluster_id,
                    resolution="rejected",
                    suggestion_id=suggestion.id,
                    source="manual_reject",
                )

                # Create negative constraints to prevent future auto-assignment
                if self._cluster_repository and self._constraint_repository:
                    cluster = await self._cluster_repository.get_by_id(suggestion.cluster_id)
                    if cluster and cluster.representative_identity_id:
                        await self._constraint_repository.create_cannot_link(
                            tenant_id=self._tenant_id,
                            identity_a=suggestion.identity_id,
                            identity_b=cluster.representative_identity_id,
                            source="manual_reject",
                        )

                if self._block_repository:
                    await self._block_repository.add_block(
                        tenant_id=self._tenant_id,
                        identity_id=suggestion.identity_id,
                        blocked_cluster_id=suggestion.cluster_id,
                        reason="manual_reject",
                    )

            return suggestion
        except ValueError:
            logger.warning("[curation] Failed to reject suggestion_id=%s: Not found", suggestion_id)
            return None  # Not found

    async def list_pending(self, limit: int = 50, offset: int = 0) -> list[SuggestionDetails]:
        """List pending suggestions with identity + cluster details for the service tenant."""
        suggestions = await self._repository.list_pending_with_details(self._tenant_id, limit, offset)
        if self._session is None:
            return suggestions

        for suggestion in suggestions:
            if suggestion.cluster_label:
                continue
            inferred = await infer_suggested_label(
                tenant_id=self._tenant_id,
                cluster_id=suggestion.cluster_id,
                session=self._session,
                cluster_repository=self._cluster_repository,
                settings=self._settings,
            )
            if inferred:
                suggestion.suggested_label = inferred.label
                suggestion.suggested_label_source = inferred.source
                suggestion.suggested_label_confidence = inferred.confidence

        return suggestions

    async def resolve_for_identity(self, identity_id: str, cluster_id: str, resolution: str = "accepted") -> int:
        """Resolve pending suggestions for an identity+cluster combination.

        Used when user confirms a suggestion via reassignment (not via suggestion accept).
        Returns the number of suggestions resolved.
        """
        suggestions = await self._repository.get_by_identity(self._tenant_id, identity_id)
        await self._ensure_run_context()
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
                self._emit_suggestion_resolved_event(
                    identity_id=identity_id,
                    cluster_id=cluster_id,
                    resolution=resolution,
                    suggestion_id=suggestion.id,
                    source="implicit_assignment",
                )
        return resolved_count


__all__ = ["SuggestionService"]
