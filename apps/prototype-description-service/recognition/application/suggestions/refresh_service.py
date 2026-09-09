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
from recognition.application.assignment import (
    AssignmentCandidate,
    AssignmentDecision,
    AssignmentGate,
    AssignmentOutcome,
    DiscoveryMethod,
)
from recognition.application.assignment.checks import (
    BlockCheck,
    CheckFailureKind,
    ConfidenceCheck,
    ConstraintCheck,
)
from recognition.application.identity_mapping import media_identity_from_model
from recognition.application.settings import ClusteringSettings
from recognition.application.similarity import RepresentativeCache, SimilaritySearch
from recognition.application.suggestions.eligibility import is_eligible_cluster
from recognition.application.suggestions.embedding_space import (
    models_are_same_space,
    representative_embedding_model,
    same_space_representative_vectors,
    same_space_vector,
)
from recognition.shared.similarity import normalize_face_embedding
from recognition.config.settings import resolve_effective_clustering_settings
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


def _gallery_vector_for_probe(rep: object, probe_model: str | None) -> np.ndarray | None:
    """Return a gallery vector only when it shares the probe's embedding space.

    Stamped probe → fail-closed same_space_vector. Unstamped probe (legacy) →
    only unstamped gallery vectors, so a cv/ort row cannot win the cosine.
    """
    if probe_model:
        return same_space_vector(rep, str(probe_model))
    if representative_embedding_model(rep) is not None:
        return None
    raw = getattr(rep, "embedding", rep)
    vec = np.asarray(raw, dtype=np.float32)
    if vec.size == 0:
        return None
    return vec


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
        self._settings = settings or resolve_effective_clustering_settings()
        self._search = SimilaritySearch(self._settings)
        self._gate = gate
        self._block_repository = block_repository
        self._constraint_repository = constraint_repository
        self._run_context = run_context

    def bind_run_context(self, context: RecognitionRunContext | None) -> None:
        """Attach or clear the active recognition run context."""
        self._run_context = context

    @property
    def tenant_id(self) -> str | None:
        """Public tenant scope for HTTP routing decisions."""
        return self._tenant_id

    @staticmethod
    def _build_identity(model: MediaIdentityModel) -> MediaIdentity:
        return media_identity_from_model(model)

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

                probe_model = identity.embedding_model
                same_space: list[np.ndarray] = []
                for rep in reps:
                    vec = _gallery_vector_for_probe(rep, probe_model)
                    if vec is not None:
                        same_space.append(vec)
                if not same_space:
                    continue
                reps_by_cluster[cluster_id] = same_space

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

    def _should_surface_gate_reject(self, decision: AssignmentDecision, *, similarity: float) -> bool:
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

            probe_model = identity.embedding_model
            same_space: list[np.ndarray] = []
            for rep in reps:
                vec = _gallery_vector_for_probe(rep, probe_model)
                if vec is not None:
                    same_space.append(vec)
            if not same_space:
                continue
            representatives_by_cluster[cluster_id] = same_space

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

    async def refresh_after_curation(
        self,
        *,
        cluster_id: str,
        identity_ids: Sequence[str] | None = None,
        reason: SuggestionRefreshReason,
    ) -> int:
        """Refresh cluster suggestions after a curation event.

        This entrypoint keeps the curation-specific refresh path in one place:
        first refresh existing pending suggestions for the curated cluster, then
        surface missing candidates from current unlabeled clusters, and finally
        fall back to the explicitly affected identity IDs.
        """
        refreshed = await self.refresh_for_cluster(cluster_id)
        total = refreshed

        if total == 0 and self._cluster_repository is not None:
            get_top_unlabeled = getattr(self._cluster_repository, "get_top_unlabeled", None)
            if callable(get_top_unlabeled):
                candidate_clusters = await get_top_unlabeled(
                    self._tenant_id,
                    limit=1000,
                    min_identity_count=1,
                )
                surfaced = await self.surface_for_newly_labeled_cluster(
                    cluster_id,
                    candidate_cluster_ids=[
                        candidate.id for candidate in candidate_clusters if getattr(candidate, "id", None)
                    ],
                )
                total += surfaced

        if total == 0:
            for identity_id in dict.fromkeys(identity_ids or []):
                suggestions = await self.refresh_for_identity(
                    identity_id=identity_id,
                    reason=reason,
                )
                total += len(suggestions)

        return total

    async def refresh_for_cluster(self, cluster_id: str) -> int:
        """Refresh similarity scores for all pending suggestions targeting a cluster."""
        if self._session is None or self._cluster_repository is None:
            return 0

        cluster = await self._cluster_repository.get_by_id(cluster_id)
        if not cluster:
            logger.warning("[suggestions] refresh_for_cluster: cluster not found cluster_id=%s", cluster_id)
            return 0

        labeled_reps = list(await self._cluster_repository.get_all_representatives(cluster_id))
        if not labeled_reps:
            logger.info("[suggestions] refresh_for_cluster: no representatives cluster_id=%s", cluster_id)
            return 0

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
            same_space = [
                vec
                for vec in (_gallery_vector_for_probe(rep, identity.embedding_model) for rep in labeled_reps)
                if vec is not None
            ]
            if not same_space:
                try:
                    await self._repository.update_status(
                        self._tenant_id,
                        suggestion.id,
                        SuggestionStatus.REJECTED,
                    )
                except ValueError:
                    logger.warning(
                        "[suggestions] stale cross-space suggestion disappeared before rejection suggestion_id=%s",
                        suggestion.id,
                    )
                continue
            match = await self._find_best_cluster_match(
                identity,
                representatives_by_cluster={cluster_id: same_space},
            )
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
            logger.info(
                "[suggestions] surface_for_newly_labeled_cluster: skipped implicit full scan cluster_id=%s reason=explicit_backfill_required",
                cluster_id,
            )
            return 0

        unlabeled_cluster_ids = list(dict.fromkeys(cid for cid in candidate_cluster_ids if cid and cid != cluster_id))
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
        # Production get_by_id does not selectinload representatives, and
        # identity_clusters has no embedding_model column, so cluster_embedding_model
        # on that path is always None. Derive the gallery space from the repository's
        # typed representative query (majority model, lex-stable tie-break).
        try:
            load_representatives = self._cluster_repository.get_all_representatives
        except AttributeError:
            # Keep legacy structural adapters usable for all-unstamped vectors;
            # a stamped candidate must fail loudly if the protocol is violated,
            # rather than silently skipping every candidate as cross-space.
            if any(
                identity.embedding_model for identities in identities_by_cluster.values() for identity in identities
            ):
                raise
            labeled_reps = []
        else:
            labeled_reps = list(await load_representatives(cluster_id))
        gallery_model, gallery_vectors = same_space_representative_vectors(labeled_reps)
        if gallery_vectors:
            # Rebuild from current reps so a stale/foreign precomputed cache
            # cannot be cosined against a current-space identity (FIR23-01).
            search_gallery: Mapping[str, Sequence[np.ndarray] | np.ndarray] = {
                cluster_id: [normalize_face_embedding(vector) for vector in gallery_vectors]
            }
        elif gallery_model is None and _has_reps(rep_embeddings):
            search_gallery = {cluster_id: rep_embeddings}
        else:
            logger.info(
                "[suggestions] surface_for_newly_labeled_cluster: no same-space representatives cluster_id=%s",
                cluster_id,
            )
            return 0
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
                if not models_are_same_space(identity.embedding_model, gallery_model):
                    continue
                match = self._search.find_best_match(identity.face_vector, search_gallery)
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

    async def backfill_for_new_unlabeled_clusters(
        self,
        *,
        tenant_id: str,
        created_cluster_ids: Sequence[str],
        fallback_window_minutes: int = 30,
    ) -> int:
        """Surface suggestions for clusters created in the latest clustering batch."""
        if self._session is None or self._cluster_repository is None:
            return 0

        primary_candidate_ids = {cid for cid in created_cluster_ids if cid}
        candidate_ids = set(primary_candidate_ids)
        fallback_recovered = 0
        if fallback_window_minutes > 0:
            recent = await self._cluster_repository.get_unlabeled_created_after(
                tenant_id, minutes_ago=fallback_window_minutes
            )
            fallback_candidate_ids = {str(cluster.id) for cluster in recent if cluster.id}
            fallback_recovered = len(fallback_candidate_ids - primary_candidate_ids)
            candidate_ids.update(fallback_candidate_ids)

        if not candidate_ids:
            logger.info(
                "[suggestions] backfill skipped tenant_id=%s reason=no_candidates primary=%d fallback_recovered=%d",
                tenant_id,
                len(primary_candidate_ids),
                fallback_recovered,
            )
            return 0

        confirmed_clusters = await self._cluster_repository.get_confirmed_labeled(tenant_id)
        if not confirmed_clusters:
            bootstrapped = await self._bootstrap_pending_suggestions(tenant_id, candidate_ids, fallback_recovered)
            logger.info(
                "[suggestions] backfill complete tenant_id=%s primary_candidates=%d "
                "fallback_recovered=%d candidates_total=%d confirmed_total=0 bootstrap_created=%d",
                tenant_id,
                len(primary_candidate_ids),
                fallback_recovered,
                len(candidate_ids),
                bootstrapped,
            )
            return bootstrapped

        total_created = 0
        confirmed_skipped = 0
        confirmed_without_surface = 0
        confirmed_scanned = 0
        for cluster in confirmed_clusters:
            if not cluster.id or not cluster.label:
                confirmed_skipped += 1
                continue
            confirmed_scanned += 1
            surfaced = await self.surface_for_newly_labeled_cluster(
                str(cluster.id),
                cluster_label=cluster.label,
                candidate_cluster_ids=list(candidate_ids),
            )
            total_created += surfaced
            if surfaced == 0:
                confirmed_without_surface += 1

        logger.info(
            "[suggestions] backfill complete tenant_id=%s primary_candidates=%d "
            "fallback_recovered=%d candidates_total=%d confirmed_total=%d confirmed_scanned=%d "
            "confirmed_skipped=%d confirmed_without_surface=%d surfaced_total=%d",
            tenant_id,
            len(primary_candidate_ids),
            fallback_recovered,
            len(candidate_ids),
            len(confirmed_clusters),
            confirmed_scanned,
            confirmed_skipped,
            confirmed_without_surface,
            total_created,
        )
        return total_created

    async def _bootstrap_pending_suggestions(
        self,
        tenant_id: str,
        candidate_ids: set[str],
        fallback_recovered: int,
    ) -> int:
        """Create one self-referential review suggestion per candidate cluster on greenfield tenants."""
        cluster_repository = self._cluster_repository
        if cluster_repository is None:
            return 0

        created = 0
        skipped_without_members = 0

        for cluster_id in sorted(candidate_ids):
            members = await cluster_repository.get_members(cluster_id)
            if not members:
                skipped_without_members += 1
                continue

            seed_identity_id = str(members[0].identity_id)
            await self._create_or_update_suggestion(
                seed_identity_id,
                cluster_id,
                1.0,
                SuggestionRefreshReason.BOOTSTRAP,
                confidence_score=1.0,
            )
            created += 1

        logger.info(
            "[suggestions] bootstrap complete tenant_id=%s candidates=%d "
            "fallback_recovered=%d created=%d skipped_without_members=%d",
            tenant_id,
            len(candidate_ids),
            fallback_recovered,
            created,
            skipped_without_members,
        )
        return created
