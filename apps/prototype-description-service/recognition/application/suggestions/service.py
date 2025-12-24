"""
Suggestion service backed by SuggestionRepository.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MediaIdentity as MediaIdentityModel
from db.models import RecognitionRun
from recognition.application.assignment import AssignmentCandidate
from recognition.application.settings import ClusteringSettings
from recognition.config import get_settings as get_recognition_settings
from recognition.domain.repositories import (
    ClusterRepository,
    IdentityClusterBlockRepository,
    IdentityConstraintRepository,
    SuggestionCreateData,
    SuggestionRepository,
)
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionRefreshReason, SuggestionStatus
from recognition.observability.recognition_runs import RecognitionRunContext
from recognition.shared.similarity import compute_face_similarity, extract_face_embedding

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
        settings: ClusteringSettings | None = None,
        block_repository: IdentityClusterBlockRepository | None = None,
        constraint_repository: IdentityConstraintRepository | None = None,
    ) -> None:
        self._repository = repository
        self._tenant_id = tenant_id
        self._cluster_repository = cluster_repository
        self._session = session
        self._run_context = run_context
        self._settings = settings or get_recognition_settings().clustering
        self._block_repository = block_repository
        self._constraint_repository = constraint_repository

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

    def _is_eligible_cluster(self, cluster) -> bool:
        """Check if a cluster is eligible for suggestions.

        Eligible clusters must verify:
        1. Tenant match (if service is tenant-scoped)
        2. User labeled (not auto-generated)
        3. User confirmed (explicitly curated)
        """
        if self._tenant_id and cluster.tenant_id.lower() != self._tenant_id.lower():
            logger.info("[suggestions] Skipping suggestion: tenant mismatch cluster_id=%s", cluster.id)
            return False

        if not cluster.user_confirmed or not cluster.label or cluster.label.startswith("cluster-"):
            logger.info(
                "[suggestions] Skipping suggestion: cluster not user-labeled cluster_id=%s",
                cluster.id,
            )
            return False

        return True

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

            if not self._is_eligible_cluster(cluster):
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

    async def refresh_for_identity(
        self,
        *,
        identity_id: str,
        reason: SuggestionRefreshReason,
    ) -> list[AssignmentSuggestion]:
        """Recompute suggestion candidates for a single identity.

        Args:
            identity_id: Identity UUID string to refresh suggestions for.
            reason: Trigger reason for the refresh.

        Returns:
            List of refreshed suggestions (pending state).

        Raises:
            NotImplementedError: Until refresh logic is implemented.
        """
        if self._session is None or self._cluster_repository is None:
            return []

        try:
            tenant_uuid = uuid.UUID(str(self._tenant_id))
            identity_uuid = uuid.UUID(str(identity_id))
        except ValueError:
            return []

        model = await self._session.get(MediaIdentityModel, identity_uuid)
        if model is None or model.tenant_id != tenant_uuid or model.embedding is None:
            return []

        identity_embedding = extract_face_embedding(np.asarray(model.embedding, dtype=np.float32))
        if identity_embedding.size == 0:
            return []

        now = datetime.now(tz=UTC)
        suggestions: list[AssignmentSuggestion] = []
        clusters_with_reps = await self._cluster_repository.get_labeled_with_representatives(self._tenant_id)
        if not clusters_with_reps:
            return []

        for cluster, reps in clusters_with_reps:
            if not self._is_eligible_cluster(cluster):
                continue

            if not cluster.id:
                continue
            cluster_id = cluster.id

            if self._block_repository is not None and await self._block_repository.is_blocked(
                tenant_id=self._tenant_id,
                identity_id=identity_id,
                cluster_id=cluster_id,
            ):
                continue

            # Skip clusters with cannot-link constraints (Phase 3 constraint-aware suggestions)
            if self._constraint_repository is not None:
                member_repo = getattr(self._cluster_repository, "_member_repo", None)
                if member_repo is not None:
                    try:
                        members = await member_repo.get_by_cluster(cluster_id)
                        member_ids = [str(m.identity_id) for m in members]
                        violates = await self._constraint_repository.has_cannot_link(
                            tenant_id=str(tenant_uuid),
                            identity_id=str(identity_uuid),
                            cluster_member_ids=member_ids,
                        )
                        if violates:
                            logger.debug(
                                "[suggestions] Skipping cluster due to cannot-link constraint: cluster_id=%s identity_id=%s",
                                cluster_id,
                                identity_id,
                            )
                            continue
                    except Exception as e:
                        logger.warning("[suggestions] Error checking constraints: %s", e)

            if not reps:
                continue

            best_similarity = 0.0
            for rep in reps:
                rep_vec = np.asarray(getattr(rep, "embedding", rep), dtype=np.float32)
                similarity = compute_face_similarity(identity_embedding, rep_vec)
                best_similarity = max(best_similarity, similarity)

            if best_similarity < self._settings.suggestion_floor:
                continue
            if best_similarity >= self._settings.suggestion_ceiling:
                continue

            payload = SuggestionCreateData(
                identity_id=identity_id,
                cluster_id=cluster_id,
                representative_similarity=best_similarity,
                member_similarity=best_similarity,
                confidence_score=best_similarity,
                source=reason.value,
                refreshed_at=now,
            )
            suggestion = await self._repository.upsert_by_identity_cluster(self._tenant_id, payload)
            suggestions.append(suggestion)

        return suggestions

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
                await self._ensure_run_context()
                self._emit_suggestion_resolved_event(
                    identity_id=suggestion.identity_id,
                    cluster_id=suggestion.cluster_id,
                    resolution="rejected",
                    suggestion_id=suggestion.id,
                    source="manual_reject",
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
