"""Suggestion refresh orchestration."""

from __future__ import annotations

import logging
import time as _time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TypeGuard

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.assignment import AssignmentCandidate, AssignmentGate, AssignmentOutcome, DiscoveryMethod
from recognition.application.assignment.checks import (
    BlockCheck,
    CheckFailureKind,
    ConfidenceCheck,
    ConstraintCheck,
)
from recognition.application.settings import ClusteringSettings
from recognition.application.similarity import RepresentativeCache, SimilaritySearch
from recognition.application.suggestions.eligibility import is_eligible_cluster
from recognition.config import get_settings as get_recognition_settings
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import (
    ClusterRepository,
    IdentityClusterBlockRepository,
    IdentityConstraintRepository,
    SuggestionCreateData,
    SuggestionRepository,
)
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionRefreshReason, SuggestionStatus
from recognition.observability.recognition_runs import RecognitionRunContext

logger = logging.getLogger(__name__)


def _has_reps(reps: Sequence[np.ndarray] | np.ndarray | None) -> TypeGuard[Sequence[np.ndarray] | np.ndarray]:
    if reps is None:
        return False
    if isinstance(reps, np.ndarray):
        return reps.size > 0
    return len(reps) > 0


class SuggestionRefreshService:
    """Orchestrate suggestion refresh workflows."""

    def __init__(
        self,
        repository: SuggestionRepository,
        tenant_id: str,
        cluster_repository: ClusterRepository | None = None,
        *,
        session: AsyncSession | None = None,
        settings: ClusteringSettings | None = None,
        gate: AssignmentGate | None = None,
        block_repository: IdentityClusterBlockRepository | None = None,
        constraint_repository: IdentityConstraintRepository | None = None,
        run_context: RecognitionRunContext | None = None,
    ) -> None:
        self._repository = repository
        self._tenant_id = tenant_id
        self._cluster_repository = cluster_repository
        self._session = session
        self._settings = settings or get_recognition_settings().clustering
        self._search = SimilaritySearch(self._settings)
        self._gate = gate
        self._block_repository = block_repository
        self._constraint_repository = constraint_repository
        self._run_context = run_context

    def bind_run_context(self, context: RecognitionRunContext | None) -> None:
        """Attach or clear the active recognition run context."""
        self._run_context = context

    @staticmethod
    def _build_identity(model: MediaIdentityModel) -> MediaIdentity:
        return MediaIdentity(
            id=str(model.id),
            tenant_id=str(model.tenant_id),
            media_id=str(model.media_id),
            embedding=np.asarray(model.embedding, dtype=np.float32),
            confidence=float(model.confidence),
            bbox_width=int(model.bbox_width),
            bbox_height=int(model.bbox_height),
            bbox_x=int(model.bbox_x),
            bbox_y=int(model.bbox_y),
            pose_pitch=float(model.pose_pitch) if model.pose_pitch is not None else None,
            pose_yaw=float(model.pose_yaw) if model.pose_yaw is not None else None,
            pose_roll=float(model.pose_roll) if model.pose_roll is not None else None,
            image_phash=str(model.image_phash) if model.image_phash is not None else None,
        )

    async def _find_best_cluster_match(
        self,
        identity: MediaIdentity,
        exclude_cluster_ids: set[str] | None = None,
        *,
        representatives_by_cluster: Mapping[str, Sequence[np.ndarray] | np.ndarray] | None = None,
    ) -> tuple[str, float] | None:
        """Find the best cluster match for an identity. Returns (cluster_id, similarity)."""
        if representatives_by_cluster is None:
            if self._cluster_repository is None:
                return None

            clusters_with_reps = await self._cluster_repository.get_labeled_with_representatives(self._tenant_id)
            if not clusters_with_reps:
                return None

            reps_by_cluster: dict[str, list[np.ndarray]] = {}
            for cluster, reps in clusters_with_reps:
                if not is_eligible_cluster(cluster, self._tenant_id):
                    continue

                if not cluster.id:
                    continue
                cluster_id = cluster.id
                if exclude_cluster_ids and cluster_id in exclude_cluster_ids:
                    continue
                if not reps:
                    continue

                reps_by_cluster[cluster_id] = [
                    np.asarray(getattr(rep, "embedding", rep), dtype=np.float32) for rep in reps
                ]

            representatives_by_cluster = reps_by_cluster

        if not representatives_by_cluster:
            return None

        match = self._search.find_best_match(identity.face_vector, representatives_by_cluster)
        if match is None:
            return None

        return match.cluster_id, match.similarity

    def _meets_low_confidence_floor(self, similarity: float) -> bool:
        """Return whether similarity is high enough to show as low-confidence suggestion."""
        return similarity >= self._settings.effective_low_confidence_suggestion_floor

    def _should_surface_gate_reject(self, decision, *, similarity: float) -> bool:
        """Allow selected gate rejections to remain user-reviewable suggestions.

        We only surface gate rejections produced by the confidence check and only
        when they clear the low-confidence floor. Explicit user blocks and
        constraint violations remain hard rejects.
        """
        if not self._meets_low_confidence_floor(similarity):
            return False

        failure_kinds = set(getattr(decision, "failure_kinds", []) or [])
        if not failure_kinds:
            failed_checks = set(getattr(decision, "checks_failed", []) or [])
            if BlockCheck.name in failed_checks:
                failure_kinds.add(CheckFailureKind.BLOCK)
            if ConstraintCheck.name in failed_checks:
                failure_kinds.add(CheckFailureKind.CONSTRAINT)
            if ConfidenceCheck.name in failed_checks:
                failure_kinds.add(CheckFailureKind.CONFIDENCE)
        if CheckFailureKind.BLOCK in failure_kinds or CheckFailureKind.CONSTRAINT in failure_kinds:
            return False

        return CheckFailureKind.CONFIDENCE in failure_kinds

    async def _get_cluster_member_ids(self, cluster_id: str) -> list[str]:
        """Fetch member identity IDs for a cluster for constraint checks."""
        if self._cluster_repository is None:
            return []
        members = await self._cluster_repository.get_members(cluster_id)
        return [member.identity_id for member in members]

    async def _passes_fallback_guards(
        self,
        *,
        tenant_uuid: uuid.UUID,
        identity_id: str,
        cluster_id: str,
        similarity: float,
        cluster_member_ids: Sequence[str] | None = None,
    ) -> bool:
        """Evaluate fallback block/constraint/floor checks when gate is unavailable."""
        if self._block_repository is not None and await self._block_repository.is_blocked(
            tenant_id=self._tenant_id,
            identity_id=identity_id,
            cluster_id=cluster_id,
        ):
            return False

        if self._constraint_repository is not None:
            member_ids = (
                list(cluster_member_ids)
                if cluster_member_ids is not None
                else await self._get_cluster_member_ids(cluster_id)
            )
            if member_ids:
                try:
                    violates = await self._constraint_repository.has_cannot_link(
                        tenant_id=str(tenant_uuid),
                        identity_id=identity_id,
                        cluster_member_ids=member_ids,
                    )
                    if violates:
                        logger.debug(
                            "[suggestions] Skipping cluster due to cannot-link constraint: cluster_id=%s identity_id=%s",
                            cluster_id,
                            identity_id,
                        )
                        return False
                except Exception as exc:
                    logger.warning("[suggestions] Error checking constraints: %s", exc)

        return self._meets_low_confidence_floor(similarity)

    async def _create_or_update_suggestion(
        self,
        identity_id: str,
        cluster_id: str,
        similarity: float,
        reason: SuggestionRefreshReason,
        *,
        confidence_score: float | None = None,
        refreshed_at: datetime | None = None,
    ) -> AssignmentSuggestion:
        """Create a new suggestion or update existing one."""
        if refreshed_at is None:
            refreshed_at = datetime.now(tz=UTC)
        if confidence_score is None:
            confidence_score = similarity

        payload = SuggestionCreateData(
            identity_id=identity_id,
            cluster_id=cluster_id,
            representative_similarity=similarity,
            member_similarity=similarity,
            confidence_score=confidence_score,
            source=reason.value,
            refreshed_at=refreshed_at,
        )
        suggestion = await self._repository.upsert_by_identity_cluster(self._tenant_id, payload)
        logger.info(
            "[suggestions] REFRESHED identity_id=%s cluster_id=%s similarity=%.3f reason=%s",
            identity_id,
            cluster_id,
            similarity,
            reason.value,
        )
        return suggestion

    async def refresh_for_identity(
        self,
        *,
        identity_id: str,
        reason: SuggestionRefreshReason,
    ) -> list[AssignmentSuggestion]:
        """Recompute suggestion candidates for a single identity."""
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

        identity = self._build_identity(model)
        identity_vector = identity.face_vector
        now = datetime.now(tz=UTC)
        suggestions: list[AssignmentSuggestion] = []
        clusters_with_reps = await self._cluster_repository.get_labeled_with_representatives(self._tenant_id)
        if not clusters_with_reps:
            return []

        representatives_by_cluster: dict[str, list[np.ndarray]] = {}
        member_ids_by_cluster: dict[str, list[str]] = {}
        for cluster, reps in clusters_with_reps:
            if not is_eligible_cluster(cluster, self._tenant_id):
                continue

            if not cluster.id:
                continue
            cluster_id = cluster.id
            if not reps:
                continue

            representatives_by_cluster[cluster_id] = [
                np.asarray(getattr(rep, "embedding", rep), dtype=np.float32) for rep in reps
            ]

        if not representatives_by_cluster:
            return []

        matches = self._search.find_all_matches(identity_vector, representatives_by_cluster)
        for match in matches:
            cluster_id = match.cluster_id
            confidence_score = match.similarity

            if self._gate is not None:
                candidate = AssignmentCandidate(
                    identity=identity,
                    identity_vector=identity_vector,
                    cluster_id=cluster_id,
                    discovery_method=DiscoveryMethod.SUGGESTION_REFRESH,
                    discovery_similarity=match.similarity,
                )
                decision = await self._gate.evaluate(candidate)
                # Surfacing mode always creates a reviewable suggestion unless the gate
                # explicitly rejects the match.
                if decision.outcome is AssignmentOutcome.REJECT and not self._should_surface_gate_reject(
                    decision,
                    similarity=match.similarity,
                ):
                    continue
                confidence_score = decision.suggestion_confidence or match.similarity
            else:
                member_ids = member_ids_by_cluster.get(cluster_id)
                if member_ids is None and self._constraint_repository is not None:
                    member_ids = await self._get_cluster_member_ids(cluster_id)
                    member_ids_by_cluster[cluster_id] = member_ids

                if not await self._passes_fallback_guards(
                    tenant_uuid=tenant_uuid,
                    identity_id=str(identity_uuid),
                    cluster_id=cluster_id,
                    similarity=match.similarity,
                    cluster_member_ids=member_ids,
                ):
                    continue
                confidence_score = match.similarity

            suggestion = await self._create_or_update_suggestion(
                identity_id=identity_id,
                cluster_id=cluster_id,
                confidence_score=confidence_score,
                similarity=match.similarity,
                reason=reason,
                refreshed_at=now,
            )
            suggestions.append(suggestion)

        if suggestions:
            logger.info(
                "[suggestions] refresh_for_identity completed: identity_id=%s reason=%s suggestions_count=%d",
                identity_id,
                reason.value,
                len(suggestions),
            )
        else:
            logger.debug(
                "[suggestions] refresh_for_identity: no suggestions created identity_id=%s reason=%s",
                identity_id,
                reason.value,
            )

        return suggestions

    async def refresh_for_cluster(self, cluster_id: str) -> int:
        """Refresh similarity scores for all pending suggestions targeting a cluster."""
        if self._session is None or self._cluster_repository is None:
            return 0

        cluster = await self._cluster_repository.get_by_id(cluster_id)
        if not cluster:
            logger.warning("[suggestions] refresh_for_cluster: cluster not found cluster_id=%s", cluster_id)
            return 0

        rep_cache = await RepresentativeCache.load([cluster_id], self._cluster_repository)
        rep_embeddings = rep_cache.get_representatives(cluster_id)
        if rep_embeddings is None:
            logger.info("[suggestions] refresh_for_cluster: no representatives cluster_id=%s", cluster_id)
            return 0

        representatives_by_cluster = {cluster_id: rep_embeddings}

        suggestions = await self._repository.get_by_cluster(self._tenant_id, cluster_id)
        pending = [s for s in suggestions if s.status == SuggestionStatus.PENDING]

        if not pending:
            return 0

        refreshed = 0
        for suggestion in pending:
            try:
                identity_uuid = uuid.UUID(str(suggestion.identity_id))
            except ValueError:
                continue

            model = await self._session.get(MediaIdentityModel, identity_uuid)
            if model is None or model.embedding is None:
                continue

            identity = self._build_identity(model)
            match = await self._find_best_cluster_match(identity, representatives_by_cluster=representatives_by_cluster)
            if match is None:
                continue
            _cluster_id, best_similarity = match

            old_similarity = suggestion.representative_similarity
            delta = best_similarity - old_similarity

            if abs(delta) > 0.01:
                await self._repository.update_scores(
                    self._tenant_id,
                    suggestion.id,
                    representative_similarity=best_similarity,
                    member_similarity=best_similarity,
                    confidence_score=best_similarity,
                )

                logger.info(
                    "[suggestions] refresh_result cluster_id=%s identity_id=%s "
                    "old_sim=%.4f new_sim=%.4f delta=%+.4f status=%s updated=true",
                    cluster_id,
                    suggestion.identity_id,
                    old_similarity,
                    best_similarity,
                    delta,
                    SuggestionStatus.PENDING.value,
                )
                refreshed += 1
            else:
                logger.debug(
                    "[suggestions] refresh_skipping cluster_id=%s identity_id=%s delta=%.4f (below threshold)",
                    cluster_id,
                    suggestion.identity_id,
                    delta,
                )

        logger.info(
            "[suggestions] refresh_for_cluster_complete cluster_id=%s refreshed=%d",
            cluster_id,
            refreshed,
        )
        return refreshed

    async def surface_for_newly_labeled_cluster(
        self,
        cluster_id: str,
        *,
        cluster_label: str | None = None,
        candidate_cluster_ids: Sequence[str] | None = None,
        representatives_by_cluster: Mapping[str, Sequence[np.ndarray] | np.ndarray] | None = None,
    ) -> int:
        """Create suggestions for identities in unlabeled clusters that match a newly-labeled cluster.

        Args:
            cluster_id: The ID of the newly-labeled cluster.
            cluster_label: The label being applied (optimistic update pattern).
                          If provided, skips the cluster state query to avoid
                          MVCC snapshot isolation issues in background tasks.
            candidate_cluster_ids: Optional list of cluster IDs to scan (skips full tenant lookup).
            representatives_by_cluster: Precomputed representatives to avoid recomputing cache.
        """
        if self._session is None or self._cluster_repository is None:
            return 0
        try:
            tenant_uuid = uuid.UUID(str(self._tenant_id))
        except ValueError:
            return 0

        # When cluster_label is provided, we trust the caller (optimistic update pattern).
        # This avoids MVCC snapshot isolation issues where a background task might
        # see pre-commit data. See Kleppmann Ch 7, Pekka Enberg Ch 11.3.
        if cluster_label is not None:
            logger.info(
                "[suggestions] surface_for_newly_labeled_cluster: using passed label=%s cluster_id=%s (optimistic)",
                cluster_label,
                cluster_id,
            )
        else:
            # Fallback: query the cluster state (used when called synchronously)
            cluster = await self._cluster_repository.get_by_id(cluster_id)
            if not cluster or not cluster.user_confirmed or not cluster.label:
                logger.info(
                    "[suggestions] surface_for_newly_labeled_cluster: cluster not user-labeled cluster_id=%s user_confirmed=%s label=%s",
                    cluster_id,
                    getattr(cluster, "user_confirmed", None),
                    getattr(cluster, "label", None),
                )
                return 0
            cluster_label = cluster.label

        rep_embeddings: Sequence[np.ndarray] | np.ndarray | None = None

        if representatives_by_cluster is None:
            logger.debug("[suggestions] surface: loading representative cache for cluster_id=%s", cluster_id)
            rep_cache = await RepresentativeCache.load([cluster_id], self._cluster_repository)
            rep_embeddings = rep_cache.get_representatives(cluster_id)
            if not _has_reps(rep_embeddings):
                logger.info(
                    "[suggestions] surface_for_newly_labeled_cluster: no representatives cluster_id=%s",
                    cluster_id,
                )
                return 0
            representatives_by_cluster = {cluster_id: rep_embeddings}
        else:
            rep_embeddings = representatives_by_cluster.get(cluster_id)
            if not _has_reps(rep_embeddings):
                logger.info(
                    "[suggestions] surface_for_newly_labeled_cluster: no representatives cluster_id=%s (precomputed)",
                    cluster_id,
                )
                return 0

        _t_start = _time.perf_counter()

        if candidate_cluster_ids is None:
            all_clusters = await self._cluster_repository.get_by_tenant(self._tenant_id, limit=1000)
            _t_get_clusters = _time.perf_counter()
            logger.info(
                "[suggestions] surface: loaded %d total clusters in %.3fs",
                len(all_clusters),
                _t_get_clusters - _t_start,
            )

            unlabeled_clusters = [
                c
                for c in all_clusters
                if c.id != cluster_id and (not c.user_confirmed or not c.label or c.label.startswith("cluster-"))
            ]
            unlabeled_cluster_ids = list(dict.fromkeys(c.id for c in unlabeled_clusters if c.id))
            logger.info(
                "[suggestions] surface: found %d unlabeled clusters to scan (out of %d total)",
                len(unlabeled_clusters),
                len(all_clusters),
            )
            unlabeled_count = len(unlabeled_clusters)
        else:
            unlabeled_cluster_ids = list(
                dict.fromkeys(cid for cid in candidate_cluster_ids if cid and cid != cluster_id)
            )
            unlabeled_count = len(unlabeled_cluster_ids)
            logger.info(
                "[suggestions] surface: using %d provided unlabeled clusters to scan",
                unlabeled_count,
            )

        if not unlabeled_cluster_ids:
            logger.info(
                "[suggestions] surface_for_newly_labeled_cluster: no unlabeled clusters to scan cluster_id=%s",
                cluster_id,
            )
            return 0

        target_cluster_member_ids: list[str] | None = None
        if self._constraint_repository is not None:
            target_cluster_member_ids = await self._get_cluster_member_ids(cluster_id)

        created = 0
        now = datetime.now(tz=UTC)
        _total_db_queries = 0
        _t_loop_start = _time.perf_counter()

        identities_by_cluster = await self._cluster_repository.get_member_identities_for_clusters(unlabeled_cluster_ids)
        _total_db_queries += 1
        _total_members = sum(len(identities) for identities in identities_by_cluster.values())
        seen_identity_ids: set[str] = set()
        duplicate_identity_skips = 0
        logger.info(
            "[suggestions] surface: loaded %d member identities from %d clusters in %.3fs",
            _total_members,
            len(unlabeled_cluster_ids),
            _time.perf_counter() - _t_loop_start,
        )

        processed_identities = 0
        for _cluster_idx, member_cluster_id in enumerate(unlabeled_cluster_ids):
            identities = identities_by_cluster.get(member_cluster_id, [])

            if (_cluster_idx + 1) % 50 == 0:
                _elapsed = _time.perf_counter() - _t_loop_start
                logger.info(
                    "[suggestions] surface: progress %d/%d clusters, %d identities, %.2fs elapsed",
                    _cluster_idx + 1,
                    len(unlabeled_cluster_ids),
                    processed_identities,
                    _elapsed,
                )

            for identity in identities:
                processed_identities += 1
                identity_id = identity.id
                if identity_id in seen_identity_ids:
                    duplicate_identity_skips += 1
                    continue
                seen_identity_ids.add(identity_id)
                match = self._search.find_best_match(identity.face_vector, representatives_by_cluster)
                if match is None:
                    continue
                best_similarity = match.similarity

                if self._gate is not None:
                    candidate = AssignmentCandidate(
                        identity=identity,
                        identity_vector=identity.face_vector,
                        cluster_id=cluster_id,
                        discovery_method=DiscoveryMethod.SUGGESTION_REFRESH,
                        discovery_similarity=best_similarity,
                    )
                    decision = await self._gate.evaluate(candidate)
                    # Surfacing mode always creates a reviewable suggestion unless the
                    # gate explicitly rejects the match.
                    if decision.outcome is AssignmentOutcome.REJECT and not self._should_surface_gate_reject(
                        decision,
                        similarity=best_similarity,
                    ):
                        continue
                    confidence_score = decision.suggestion_confidence or best_similarity
                else:
                    if not await self._passes_fallback_guards(
                        tenant_uuid=tenant_uuid,
                        identity_id=identity_id,
                        cluster_id=cluster_id,
                        similarity=best_similarity,
                        cluster_member_ids=target_cluster_member_ids,
                    ):
                        continue
                    confidence_score = best_similarity

                payload = SuggestionCreateData(
                    identity_id=identity_id,
                    cluster_id=cluster_id,
                    representative_similarity=best_similarity,
                    member_similarity=best_similarity,
                    confidence_score=confidence_score,
                    source="cluster_labeled",
                    refreshed_at=now,
                )
                await self._repository.upsert_by_identity_cluster(self._tenant_id, payload)
                created += 1

                if processed_identities % 1000 == 0:
                    _elapsed = _time.perf_counter() - _t_loop_start
                    logger.info(
                        "[suggestions] surface: progress %d/%d identities scanned, %.2fs elapsed",
                        processed_identities,
                        _total_members,
                        _elapsed,
                    )

                logger.info(
                    "[suggestions] SURFACED identity_id=%s cluster_id=%s cluster_label='%s' similarity=%.3f source=cluster_labeled",
                    identity_id,
                    cluster_id,
                    cluster_label,
                    best_similarity,
                )

        _t_end = _time.perf_counter()
        _total_elapsed = _t_end - _t_start

        # Summary log with N+1 query statistics
        logger.info(
            "[suggestions] surface_for_newly_labeled_cluster SUMMARY: "
            "cluster_id=%s label='%s' "
            "unlabeled_clusters=%d total_members=%d unique_members=%d duplicate_skipped=%d db_queries=%d "
            "suggestions_created=%d total_time=%.2fs",
            cluster_id,
            cluster_label,
            unlabeled_count,
            _total_members,
            len(seen_identity_ids),
            duplicate_identity_skips,
            _total_db_queries,
            created,
            _total_elapsed,
        )

        return created
