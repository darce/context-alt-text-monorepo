"""
AssignmentWriter interface for persisting gate decisions (Phase 5).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.assignment.quality import compute_identity_quality as _compute_quality_info
from recognition.application.labeling.auto_labeler import allocate_person_label, should_auto_label
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.locator import IdentityLocator
from recognition.domain.repositories import ClusterNotFoundError, ClusterRepository, MemberData, MemberRepository
from recognition.domain.representative import ClusterRepresentative
from recognition.observability import ClusteringLogger
from recognition.observability.recognition_runs import RecognitionRunContext
from recognition.shared.similarity import compute_face_similarity, extract_face_embedding

logger = logging.getLogger(__name__)


def _compute_fingerprint(embedding: np.ndarray) -> str:
    """Compute a stable fingerprint for a face embedding."""
    import hashlib

    # Use face-only portion for fingerprinting
    face_vec = extract_face_embedding(embedding)
    return hashlib.sha256(face_vec.tobytes()).hexdigest()[:8]


def _normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    """Normalize a face embedding to unit length.

    Args:
        embedding: Raw embedding vector (512D or 1024D).

    Returns:
        Normalized 512D face embedding.
    """
    face_vec = extract_face_embedding(embedding)
    norm = float(np.linalg.norm(face_vec))
    if norm == 0:
        return face_vec.astype(np.float32)
    return face_vec.astype(np.float32) / norm


def _compute_identity_quality(identity: MediaIdentity, settings: ClusteringSettings) -> float:
    """Compute quality score for a media identity.

    Delegates to the canonical compute_identity_quality in quality.py which
    considers detection confidence, pose angles, and face size.

    Args:
        identity: MediaIdentity with confidence and bbox dimensions.
        settings: Clustering settings containing quality parameters.

    Returns:
        Quality score between 0.0 and 1.0.
    """
    info = _compute_quality_info(
        confidence=identity.confidence,
        pose_pitch=identity.pose_pitch,
        pose_yaw=identity.pose_yaw,
        pose_roll=identity.pose_roll,
        bbox_width=identity.bbox_width,
        bbox_height=identity.bbox_height,
        settings=settings.quality,
    )
    return info.score


def _select_diverse_representatives(
    identities: list[MediaIdentity],
    max_reps: int,
) -> list[MediaIdentity]:
    """Select representatives via Farthest-Point Sampling for diversity.

    This algorithm ensures geometric diversity by selecting representatives
    that maximize minimum distance from already-chosen representatives,
    preventing the loss of "bridge" faces that connect different pose angles.

    Args:
        identities: Pool of candidate identities.
        max_reps: Maximum number of representatives to select.

    Returns:
        Selected representatives in insertion order (first is highest confidence).
    """
    if not identities:
        return []
    k = min(max_reps, len(identities))

    # Seed with highest-confidence face
    sorted_by_conf = sorted(identities, key=lambda i: i.confidence, reverse=True)
    selected: list[MediaIdentity] = [sorted_by_conf[0]]
    selected_vecs: list[np.ndarray] = [_normalize_embedding(np.asarray(sorted_by_conf[0].embedding, dtype=np.float32))]
    remaining = set(range(1, len(sorted_by_conf)))

    for _ in range(k - 1):
        if not remaining:
            break
        best_idx: int | None = None
        best_min_dist = -1.0
        for idx in remaining:
            vec = _normalize_embedding(np.asarray(sorted_by_conf[idx].embedding, dtype=np.float32))
            # Distance = 1 - cosine_similarity (since embeddings are normalized)
            min_dist = min(float(1 - np.dot(vec, sv)) for sv in selected_vecs)
            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_idx = idx
        if best_idx is None:
            break
        selected.append(sorted_by_conf[best_idx])
        selected_vecs.append(_normalize_embedding(np.asarray(sorted_by_conf[best_idx].embedding, dtype=np.float32)))
        remaining.remove(best_idx)

    return selected


def _get_pose_bucket(identity: MediaIdentity | ClusterRepresentative, bucket_size: float) -> tuple[int, int] | None:
    """Get the (pitch, yaw) bucket for an identity or representative."""
    pitch = identity.pose_pitch
    yaw = identity.pose_yaw
    if pitch is None or yaw is None:
        return None
    bucket = (int(pitch // bucket_size), int(yaw // bucket_size))
    identity_ref = getattr(identity, "id", None) or getattr(identity, "identity_id", None)
    logger.debug(
        "[pose_bucket] identity=%s pitch=%.2f yaw=%.2f bucket=%s size=%.1f",
        identity_ref,
        pitch,
        yaw,
        bucket,
        bucket_size,
    )
    return bucket


def _is_novel_pose(
    identity: MediaIdentity,
    existing_reps: Sequence[ClusterRepresentative],
    bucket_size: float,
) -> bool:
    """Check if identity's pose fall into a bucket not covered by existing reps."""
    new_bucket = _get_pose_bucket(identity, bucket_size)
    if not new_bucket:
        logger.debug(
            "[pose_bucket] identity=%s has no pose data, cannot determine novelty",
            identity.id,
        )
        return False

    existing_buckets = []
    for rep in existing_reps:
        rep_bucket = _get_pose_bucket(rep, bucket_size)
        if rep_bucket:
            existing_buckets.append(rep_bucket)
        if rep_bucket == new_bucket:
            logger.debug(
                "[pose_bucket] identity=%s bucket=%s already covered by rep=%s",
                identity.id,
                new_bucket,
                rep.identity_id,
            )
            return False  # Covered

    logger.info(
        "[pose_bucket] NOVEL_POSE identity=%s bucket=%s existing_buckets=%s",
        identity.id,
        new_bucket,
        existing_buckets,
    )
    return True


def _find_upgradeable_representative(
    identity: MediaIdentity,
    existing_reps: Sequence[ClusterRepresentative],
    bucket_size: float,
    settings: ClusteringSettings,
) -> ClusterRepresentative | None:
    """Find an existing representative in the same pose bucket to replace (upgrade).

    Returns the representative to replace if the new identity is significantly better.
    """
    new_bucket = _get_pose_bucket(identity, bucket_size)
    if not new_bucket:
        return None

    new_quality = _compute_identity_quality(identity, settings)
    margin = 0.1

    for rep in existing_reps:
        rep_bucket = _get_pose_bucket(rep, bucket_size)
        if rep_bucket == new_bucket:
            rep_quality = rep.quality_score or 0
            if new_quality > rep_quality + margin:
                logger.info(
                    "[pose_bucket] UPGRADE identity=%s bucket=%s new_quality=%.3f > rep=%s rep_quality=%.3f",
                    identity.id,
                    new_bucket,
                    new_quality,
                    rep.identity_id,
                    rep_quality,
                )
                return rep
            else:
                logger.debug(
                    "[pose_bucket] identity=%s bucket=%s quality=%.3f not better than rep=%s quality=%.3f",
                    identity.id,
                    new_bucket,
                    new_quality,
                    rep.identity_id,
                    rep_quality,
                )

    return None


class AssignmentWriter:
    """Persist assignment decisions and cluster updates."""

    def __init__(
        self,
        settings: ClusteringSettings,
        cluster_repository: ClusterRepository,
        member_repository: MemberRepository,
        *,
        run_context: RecognitionRunContext | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        self._settings = settings
        self._clusters = cluster_repository
        self._members = member_repository
        self._run_context = run_context
        self._session = session
        self._last_rep_count: int | None = None

    def bind_run_context(self, context: RecognitionRunContext | None) -> None:
        """Attach or clear the active recognition run context.

        Args:
            context: Run context for emitting `recognition_events`, or None to disable event emission.
        """
        self._run_context = context

    @property
    def cluster_repository(self) -> ClusterRepository:
        """Expose the cluster repository for orchestration and tests."""
        return self._clusters

    @property
    def member_repository(self) -> MemberRepository:
        """Expose the member repository for orchestration and tests."""
        return self._members

    def _emit_cluster_created_event(
        self,
        *,
        cluster_id: str,
        identities: list[MediaIdentity],
        similarities: list[float],
        algorithm: str,
    ) -> None:
        """Emit a `cluster_created` event when a run context is available.

        Args:
            cluster_id: Newly created cluster UUID (string form).
            identities: Initial member identities for the cluster.
            similarities: Similarity scores aligned with `identities`.
            algorithm: Cluster creation algorithm label (e.g. "graph").
        """
        if self._run_context is None:
            return

        members: list[dict[str, object]] = []
        for identity, similarity in zip(identities, similarities, strict=False):
            member_payload: dict[str, object] = {
                "identity_id": identity.id,
                "similarity": float(similarity),
                "embedding_fingerprint": _compute_fingerprint(identity.embedding),
            }
            locator_payload = _locator_payload(identity)
            if locator_payload is not None:
                member_payload["identity_locator"] = locator_payload
            members.append(member_payload)

        self._run_context.add_event(
            event_type="cluster_created",
            cluster_id=cluster_id,
            payload={
                "creation_method": algorithm,
                "identity_count": len(identities),
                "members": members,
            },
        )

    def _emit_representative_selected_event(
        self,
        *,
        cluster_id: str,
        identity: MediaIdentity,
        reason: str,
        quality_score: float | None = None,
        diversity_score: float | None = None,
    ) -> None:
        """Emit a `representative_selected` event when a run context is available.

        Args:
            cluster_id: Cluster UUID (string form).
            identity: Selected representative identity.
            reason: Selection reason (e.g. "fps_seed", "diverse_addition").
            quality_score: Optional quality score for the representative.
            diversity_score: Optional diversity score for the representative.
        """
        if self._run_context is None:
            return

        payload: dict[str, object] = {"reason": reason}
        if quality_score is not None:
            payload["quality_score"] = float(quality_score)
        if diversity_score is not None:
            payload["diversity_score"] = float(diversity_score)

        locator_payload = _locator_payload(identity)
        if locator_payload is not None:
            payload["identity_locator"] = locator_payload

        self._run_context.add_event(
            event_type="representative_selected",
            identity_id=identity.id,
            cluster_id=cluster_id,
            payload=payload,
        )

    async def _create_and_add_representative(
        self,
        cluster_id: str,
        identity: MediaIdentity,
        reason: str,
        is_provisional: bool = False,
        is_user_selected: bool = False,
        existing_rep_count: int | None = None,
    ) -> ClusterRepresentative:
        """Create and persist a representative, emitting events."""
        if existing_rep_count is not None:
            max_reps = self._settings.max_representatives_per_cluster
            if existing_rep_count >= max_reps and "novel_pose" in reason:
                logger.info(
                    "[pose_bucket] NOVEL_POSE_ABOVE_CAP cluster=%s identity=%s current_reps=%d",
                    cluster_id,
                    identity.id,
                    existing_rep_count,
                )
        quality = _compute_identity_quality(identity, self._settings)
        rep = ClusterRepresentative(
            id=str(uuid.uuid4()),
            cluster_id=cluster_id,
            identity_id=identity.id,
            embedding=identity.embedding,
            created_at=datetime.now(tz=UTC),
            tenant_id=identity.tenant_id,
            quality_score=quality,
            image_phash=identity.image_phash,
            pose_pitch=identity.pose_pitch,
            pose_yaw=identity.pose_yaw,
            pose_roll=identity.pose_roll,
            is_provisional=is_provisional,
            is_user_selected=is_user_selected,
        )
        await self._clusters.add_representative(rep)
        self._emit_representative_selected_event(
            cluster_id=cluster_id,
            identity=identity,
            reason=reason,
            quality_score=rep.quality_score,
            diversity_score=rep.diversity_score,
        )

        # Check for pose bucket completion event
        if (
            self._run_context
            and identity.pose_pitch is not None
            and identity.pose_yaw is not None
            and "novel_pose" in reason
        ):
            self._run_context.add_event(
                event_type="pose_bucket_completion",
                identity_id=identity.id,
                cluster_id=cluster_id,
                payload={
                    "pitch": float(identity.pose_pitch),
                    "yaw": float(identity.pose_yaw),
                    "quality": float(quality),
                },
            )

        return rep

    async def persist_assignment(self, decision: AssignmentDecision, batch_mode: bool = False) -> None:
        """Persist an accepted assignment decision.

        Args:
            decision: The assignment decision to persist.
            batch_mode: If True, newly added representatives are marked as provisional.
        """
        if decision.outcome is not AssignmentOutcome.ACCEPT:
            raise ValueError(f"Cannot persist non-ACCEPT decision: {decision.outcome}")

        cluster = await self._clusters.get_by_id(decision.candidate.cluster_id)
        if not cluster:
            raise ClusterNotFoundError(decision.candidate.cluster_id)

        # Use conflict-safe insert so retries and planner-overlap races do not
        # raise integrity errors (finding 1166: accepted path idempotent write).
        existing_member = await self._members.add_member_if_not_exists(
            cluster_id=decision.candidate.cluster_id,
            identity_id=decision.candidate.identity.id,
            similarity=decision.candidate.discovery_similarity,
        )

        # If the identity was already a member (ON CONFLICT DO NOTHING returned None),
        # skip representative, centroid, and curriculum updates to remain idempotent.
        if existing_member is None:
            return

        should_add, cached_reps = await self._should_add_representative(decision, batch_mode=batch_mode)
        if should_add:
            # Store the full 1024D embedding, not the face-only 512D vector
            # Identify if this was an upgrade vs novel addition for the reason
            is_upgrade = getattr(self, "_last_decision_was_upgrade", False)
            reason = "representative_upgrade" if is_upgrade else "diverse_addition"
            if not is_upgrade and getattr(self, "_last_decision_was_novel_pose", False):
                reason = "novel_pose_addition"

            rep = await self._create_and_add_representative(
                cluster_id=decision.candidate.cluster_id,
                identity=decision.candidate.identity,
                reason=reason,
                is_provisional=batch_mode,
                existing_rep_count=self._last_rep_count,
            )

            if is_upgrade and self._run_context:
                self._run_context.add_event(
                    event_type="representative_upgraded",
                    identity_id=decision.candidate.identity.id,
                    cluster_id=decision.candidate.cluster_id,
                    payload={
                        "representative_id": rep.id,
                        "quality": float(rep.quality_score or 0),
                    },
                )

            # Compute centroid from the cached reps (returned by _should_add_representative)
            # plus the newly added rep -- this avoids a redundant get_all_representatives
            # DB round-trip (Phase 3: duplicate-read elimination).
            all_rep_embeddings = [r.embedding for r in cached_reps]
            all_rep_embeddings.append(rep.embedding)
            if all_rep_embeddings:
                stacked = np.stack(all_rep_embeddings)
                mean_vec = np.mean(stacked, axis=0)
                norm = float(np.linalg.norm(mean_vec))
                cluster.centroid = cast(np.ndarray, mean_vec / norm if norm > 0 else mean_vec)

        cluster.identity_count += 1
        await self._clusters.update(cluster)

        # Update curriculum bias (EMA of accepted similarities)
        # This provides continuous threshold adaptation based on actual match quality
        similarity = decision.candidate.discovery_similarity
        await self._update_curriculum_t(decision.candidate.cluster_id, similarity)

    async def persist_assignments_chunk(
        self,
        decisions: list[AssignmentDecision],
        batch_mode: bool = False,
    ) -> tuple[int, int, int]:
        """Bulk-persist accepted assignment decisions for one processing chunk.

        Groups decisions by cluster and issues a single bulk INSERT per cluster
        (ON CONFLICT DO NOTHING) instead of N per-identity round-trips.  Only
        newly-inserted members receive representative, centroid, and curriculum
        updates; idempotent skips are counted but not re-processed.

        Returns:
            (total_persisted, total_skipped, reps_added) - persisted is newly inserted,
            skipped is ON CONFLICT matches (already a member of this cluster),
            reps_added is the count of new representatives created (representative churn proxy).
        """
        if not decisions:
            return 0, 0, 0

        from collections import defaultdict

        by_cluster: dict[str, list[AssignmentDecision]] = defaultdict(list)
        for decision in decisions:
            by_cluster[decision.candidate.cluster_id].append(decision)

        total_persisted = 0
        total_skipped = 0
        _reps_added = 0

        for cluster_id, cluster_decisions in by_cluster.items():
            cluster = await self._clusters.get_by_id(cluster_id)
            if not cluster:
                logger.warning(
                    "[assignment_writer] persist_assignments_chunk: cluster %s not found, skipping",
                    cluster_id,
                )
                total_skipped += len(cluster_decisions)
                continue

            member_data = [
                MemberData(
                    identity_id=d.candidate.identity.id,
                    similarity=d.candidate.discovery_similarity,
                )
                for d in cluster_decisions
            ]
            created_members, skipped = await self._members.bulk_add_members_if_not_exists(cluster_id, member_data)
            total_skipped += skipped

            if not created_members:
                continue

            created_identity_ids = {m.identity_id for m in created_members}
            newly_inserted = [d for d in cluster_decisions if d.candidate.identity.id in created_identity_ids]
            total_persisted += len(newly_inserted)

            # Per-identity: representative and centroid updates for new members only.
            for decision in newly_inserted:
                should_add, cached_reps = await self._should_add_representative(decision, batch_mode=batch_mode)
                if should_add:
                    is_upgrade = getattr(self, "_last_decision_was_upgrade", False)
                    reason = "representative_upgrade" if is_upgrade else "diverse_addition"
                    if not is_upgrade and getattr(self, "_last_decision_was_novel_pose", False):
                        reason = "novel_pose_addition"
                    rep = await self._create_and_add_representative(
                        cluster_id=cluster_id,
                        identity=decision.candidate.identity,
                        reason=reason,
                        is_provisional=batch_mode,
                        existing_rep_count=len(cached_reps),
                    )
                    _reps_added += 1
                    all_rep_embeddings = [r.embedding for r in cached_reps]
                    all_rep_embeddings.append(rep.embedding)
                    if all_rep_embeddings:
                        stacked = np.stack(all_rep_embeddings)
                        mean_vec = np.mean(stacked, axis=0)
                        norm = float(np.linalg.norm(mean_vec))
                        cluster.centroid = cast(np.ndarray, mean_vec / norm if norm > 0 else mean_vec)

            # Single cluster identity_count update for all newly inserted members.
            cluster.identity_count += len(newly_inserted)
            await self._clusters.update(cluster)

            # Curriculum EMA: per-identity atomic update but only for new members.
            for decision in newly_inserted:
                await self._update_curriculum_t(cluster_id, decision.candidate.discovery_similarity)

        return total_persisted, total_skipped, _reps_added

    async def _update_curriculum_t(self, cluster_id: str, similarity: float) -> None:
        """Update the cluster's curriculum bias using an atomic EMA update.

        The curriculum parameter t tracks the running average of accepted similarities,
        allowing thresholds to adapt based on actual match quality rather than
        discrete maturity buckets.

        Formula: t_new = alpha * r_k + (1 - alpha) * t_prev
        Where alpha = 0.99 (fast adaptation to new observations)

        Delegates to the atomic repository method to avoid the chatty
        get_curriculum_t + set_curriculum_t round-trip (Phase 3 efficiency).
        """
        alpha = 0.99
        update_ema = getattr(self._clusters, "update_curriculum_t_ema", None)
        if callable(update_ema):
            await update_ema(cluster_id, similarity, alpha)
        else:
            # Fallback for repositories that don't yet implement atomic EMA.
            t_prev = await self._clusters.get_curriculum_t(cluster_id) or 0.0
            t_new = alpha * similarity + (1 - alpha) * t_prev
            t_new = max(0.0, min(1.0, t_new))
            await self._clusters.set_curriculum_t(cluster_id, t_new)

    async def refresh_centroids_view(self) -> None:
        """Trigger a refresh of the cluster centroids view."""
        # Call repo if it supports it
        refresh = getattr(self._clusters, "refresh_centroids_view", None)
        if callable(refresh):
            await refresh()

    async def refresh_centroids_view_concurrent(self) -> bool:
        """Trigger a concurrent refresh of the cluster centroids view. Returns True on success."""
        refresh = getattr(self._clusters, "refresh_centroids_view_concurrent", None)
        if callable(refresh):
            return bool(await refresh())
        return True

    async def _should_add_representative(
        self, decision: AssignmentDecision, batch_mode: bool = False
    ) -> tuple[bool, list[ClusterRepresentative]]:
        """Determine if the assigned identity should become a representative.

        Returns ``(should_add, cached_reps)`` where ``cached_reps`` reflects
        the current DB state *after* any upgrade removal so the caller can
        compute the new centroid from cached data without a second DB round-trip
        (Phase 3 duplicate-read elimination).
        """
        cluster_id = decision.candidate.cluster_id

        # Fetch all reps once; this is the only get_all_representatives call
        # for the accepted-assignment path (Phase 3: remove duplicate reads).
        existing_reps: list[ClusterRepresentative] = list(await self._clusters.get_all_representatives(cluster_id))
        current_count = len(existing_reps)
        self._last_rep_count = current_count

        # Track which rep was removed so cached_reps reflects current DB state.
        removed_rep_id: str | None = None

        # 1. Check for upgrade opportunity (replace lower quality rep in same pose bucket)
        upgrade_target = _find_upgradeable_representative(
            decision.candidate.identity,
            existing_reps,
            self._settings.pose_bucket_size,
            self._settings,
        )
        if upgrade_target:
            # User-selected representatives are protected from automatic upgrades
            if getattr(upgrade_target, "is_user_selected", False):
                self._last_decision_was_upgrade = False
                return False, existing_reps

            await self._clusters.remove_representative(upgrade_target.id)
            removed_rep_id = upgrade_target.id
            logger.info(
                "[pose_bucket] QUALITY_UPGRADE cluster=%s old_identity=%s new_identity=%s quality_diff=%.3f",
                cluster_id,
                upgrade_target.identity_id,
                decision.candidate.identity.id,
                _compute_identity_quality(decision.candidate.identity, self._settings)
                - (upgrade_target.quality_score or 0),
            )
            self._last_decision_was_upgrade = True

        self._last_decision_was_upgrade = False

        # cached_reps = existing_reps minus any rep just removed by the upgrade path.
        cached_reps = [r for r in existing_reps if r.id != removed_rep_id] if removed_rep_id else existing_reps

        # 2. Check limits with bonus
        max_base = self._settings.max_representatives_per_cluster
        max_total = max_base + self._settings.pose_diversity_bonus

        # In batch_mode, we allow adding even if we reached the limit,
        # provided it's a novel pose or diverse, because they will be provisional.
        # Actually, the upgrade logic (1) already handles replacing.
        # For new additions:
        if not batch_mode and current_count >= max_total:
            return False, cached_reps

        # 3. If above base limit, only add if novel pose
        if current_count >= max_base:
            if _is_novel_pose(decision.candidate.identity, existing_reps, self._settings.pose_bucket_size):
                self._last_decision_was_novel_pose = True
                return True, cached_reps
            # If batch_mode, we might still want to add it if it's "better" than nothing?
            # No, if not novel pose and no upgrade target, it's redundant.
            return False, cached_reps

        self._last_decision_was_novel_pose = False

        if not existing_reps:
            return True, cached_reps

        # 4. Standard diversity check (embedding distance)
        for rep in existing_reps:
            rep_embedding = cast(np.ndarray, getattr(rep, "embedding", rep))
            similarity = compute_face_similarity(decision.candidate.identity_vector, rep_embedding)
            if similarity > self._settings.representative_diversity_threshold:
                # If we are here, it means we are NOT in the novel pose path (or below max_base).
                # If below max_base, we enforce diversity.
                # If above max_base, we already checked novel pose (which implies diversity in pose space).
                # But novel pose == false -> we fell through.
                # So if similarity is high, we reject.
                return False, cached_reps

        return True, cached_reps

    async def _select_reps_to_preserve(
        self,
        cluster_id: str,
    ) -> list[ClusterRepresentative]:
        """Identify representatives that MUST be preserved during recompute.

        Preserves:
        1. All user-selected (pinned) representatives.
        2. The highest-quality representative from each covered pose bucket.
        """
        all_reps = await self._clusters.get_all_representatives(cluster_id)
        if not all_reps:
            return []

        # 1. Start with all pinned reps
        pinned = [rep for rep in all_reps if rep.is_user_selected]
        preserved: dict[str, ClusterRepresentative] = {rep.id: rep for rep in pinned}
        logger.debug("[_select_reps_to_preserve] Found %d pinned reps", len(pinned))

        # 2. Add best-of-bucket for all buckets
        buckets: dict[tuple[int, int], ClusterRepresentative] = {}
        for rep in all_reps:
            bucket = _get_pose_bucket(rep, self._settings.pose_bucket_size)
            if bucket is None:
                continue

            if bucket not in buckets or rep.quality_score > buckets[bucket].quality_score:
                buckets[bucket] = rep

        for rep in buckets.values():
            if rep.id not in preserved:
                logger.debug(
                    "[_select_reps_to_preserve] Adding best-of-bucket rep: %s for bucket %s",
                    rep.identity_id,
                    _get_pose_bucket(rep, self._settings.pose_bucket_size),
                )
                preserved[rep.id] = rep
            else:
                logger.debug(
                    "[_select_reps_to_preserve] Best-of-bucket rep %s already preserved (pinned)",
                    rep.identity_id,
                )

        return list(preserved.values())

    def _select_diverse_representatives_seeded(
        self,
        identities: list[MediaIdentity],
        requested_count: int,
        seeded_embeddings: list[np.ndarray],
    ) -> list[MediaIdentity]:
        """Select diverse representatives using Furthest Point Sampling, seeded with existing reps.

        This ensures newly selected reps are diverse relative to BOTH each other
        AND the already-preserved representatives.
        """
        if not identities or requested_count <= 0:
            return []

        # Seed the selected set with normalized preserved embeddings
        selected_vecs = [_normalize_embedding(ev) for ev in seeded_embeddings]

        # We only want to select from identities that aren't already represented by seeds
        # (though recompute_representatives usually filters these out anyway)
        selected_identities: list[MediaIdentity] = []

        num_to_pick = min(requested_count, len(identities))

        # Pool of candidates
        pool = identities

        for _ in range(num_to_pick):
            best_idx: int | None = None
            best_min_dist = -1.0

            for idx, candidate in enumerate(pool):
                cand_vec = _normalize_embedding(candidate.embedding)
                # Distance to nearest already-selected representative (including seeds)
                if not selected_vecs:
                    min_dist = 1.0  # First one if no seeds
                else:
                    min_dist = min(float(1 - np.dot(cand_vec, sv)) for sv in selected_vecs)

                if min_dist > best_min_dist:
                    best_min_dist = min_dist
                    best_idx = idx

            if best_idx is None:
                break

            picked = pool.pop(best_idx)
            selected_identities.append(picked)
            selected_vecs.append(_normalize_embedding(picked.embedding))

        return selected_identities

    async def recompute_centroid(self, cluster_id: str) -> np.ndarray | None:
        """Recompute cluster centroid from representatives.

        Returns None if no representatives exist for the cluster.
        """
        reps = await self._clusters.get_all_representatives(cluster_id)
        if not reps:
            # No representatives yet - return None to signal no centroid update
            return None

        # Calculate mean vector
        # Handle both raw embedding vectors and full ClusterRepresentative objects
        rep_vecs = [cast(np.ndarray, getattr(r, "embedding", r)) for r in reps]
        stacked = np.stack(rep_vecs)
        mean_vector = np.mean(stacked, axis=0)

        # Normalize
        norm = np.linalg.norm(mean_vector)
        if norm > 0:
            mean_vector = mean_vector / norm

        return cast(np.ndarray, mean_vector)

    async def recompute_representatives(self, cluster_id: str) -> None:
        """Recompute cluster representatives using FPS for diversity while preserving pins/quality."""
        cluster = await self._clusters.get_by_id(cluster_id)
        if not cluster:
            raise ClusterNotFoundError(cluster_id)

        # 1. Identify what to preserve
        preserved = await self._select_reps_to_preserve(cluster_id)
        preserved_ids = {p.identity_id for p in preserved}
        preserved_embeddings = [p.embedding for p in preserved]

        # 2. Clear representatives
        await self._clusters.clear_representatives(cluster_id)

        # 3. Get all member identities (excluding already preserved ones)
        identities = list(await self._clusters.get_member_identities(cluster_id))
        identities = [i for i in identities if i.embedding is not None and i.id not in preserved_ids]
        # Sort by quality so FPS starts with the best one if no seeds
        identities.sort(key=lambda i: _compute_identity_quality(i, self._settings), reverse=True)

        # 4. Fill remaining slots with diverse additions
        max_base = self._settings.max_representatives_per_cluster
        available_slots = max_base - len(preserved)

        selected_new: list[MediaIdentity] = []
        if available_slots > 0 and identities:
            selected_new = self._select_diverse_representatives_seeded(
                identities, available_slots, preserved_embeddings
            )

        # 5. Persist preserved reps
        for rep in preserved:
            await self._clusters.add_representative(rep)

        # 6. Persist newly selected diverse reps
        for identity in selected_new:
            await self._create_and_add_representative(
                cluster_id=cluster_id,
                identity=identity,
                reason="fps_recompute_diversity",
            )

        # Update cluster primary representative
        # First choice: pinned rep. Second choice: first preserved rep. Third choice: first new rep.
        pinned = [p for p in preserved if p.is_user_selected]
        if pinned:
            cluster.representative_identity_id = pinned[0].identity_id
        elif preserved:
            cluster.representative_identity_id = preserved[0].identity_id
        elif selected_new:
            cluster.representative_identity_id = selected_new[0].id
        else:
            cluster.representative_identity_id = None

        await self._clusters.update(cluster)

    async def persist_new_cluster(
        self,
        tenant_id: str,
        identities: list[MediaIdentity],
        similarities: list[float],
        algorithm: str = "graph",
        cluster_id: str | None = None,
        clustering_logger: ClusteringLogger | None = None,
    ) -> IdentityCluster:
        """Create a new cluster for the provided identities."""
        if len(identities) != len(similarities):
            raise ValueError("identities and similarities must have the same length")

        cluster = await self._clusters.save(
            IdentityCluster(
                id=cluster_id,
                tenant_id=tenant_id,
                label=None,
                is_labeled=False,
                identity_count=len(identities),
                created_at=datetime.now(tz=UTC),
                clustering_algorithm=algorithm,
            )
        )
        member_data = [
            MemberData(identity_id=identity.id, similarity=similarity)
            for identity, similarity in zip(identities, similarities, strict=False)
        ]
        if cluster.id is None:
            raise ClusterNotFoundError("new cluster id missing after save")
        cluster_id_str: str = cluster.id
        created_members, skipped = await self._members.bulk_add_members_if_not_exists(cluster_id_str, member_data)
        if skipped:
            logger.warning(
                "[assignment_writer] persist_new_cluster skipped %d duplicate members for cluster %s",
                skipped,
                cluster_id_str,
            )
            # Correct identity_count to reflect actual persisted members (finding 1162).
            cluster.identity_count = len(created_members)
            cluster = await self._clusters.update(cluster)
        self._emit_cluster_created_event(
            cluster_id=cluster_id_str,
            identities=identities,
            similarities=similarities,
            algorithm=algorithm,
        )

        # Log per-identity assignments
        if clustering_logger:
            for identity, similarity in zip(identities, similarities, strict=False):
                try:
                    media_id_int = int(identity.media_id) if identity.media_id else 0
                    clustering_logger.log_initial_assignment(
                        identity_id=identity.id,
                        media_id=media_id_int,
                        cluster_id=cluster_id_str,
                        similarity=similarity,
                        algorithm=algorithm,
                        tenant_id=tenant_id,
                    )
                except (TypeError, ValueError, AttributeError) as _log_exc:
                    logger.debug(
                        "[assignment_writer] log_initial_assignment suppressed for identity %s: %s",
                        identity.id,
                        _log_exc,
                    )

        # Create initial representative(s) using diversity-aware sampling (FPS)
        # to preserve "bridge" faces that connect different pose angles
        if identities:
            diverse_reps = _select_diverse_representatives(
                identities,
                self._settings.max_representatives_per_cluster,
            )
            for identity in diverse_reps:
                await self._create_and_add_representative(
                    cluster_id=cluster_id_str,
                    identity=identity,
                    reason="fps_seed",
                )

            # Recompute and persist the centroid immediately.
            # Without this, CentroidDiscovery cannot find this cluster in subsequent batches.
            new_centroid = await self.recompute_centroid(cluster_id_str)
            if new_centroid is not None:
                cluster.centroid = new_centroid
                await self._clusters.update(cluster)

        if should_auto_label(
            member_count=len(identities),
            similarities=similarities,
            algorithm=algorithm,
            settings=self._settings.auto_label,
        ):
            if self._session is None:
                logger.warning(
                    "[auto_label] skipped: no session available cluster_id=%s tenant_id=%s",
                    cluster.id,
                    tenant_id,
                )
            else:
                label = await allocate_person_label(
                    tenant_id=tenant_id,
                    session=self._session,
                    prefix=self._settings.auto_label.prefix,
                )
                cluster.label = label
                cluster.is_labeled = True
                cluster = await self._clusters.update(cluster)
                avg_similarity = sum(similarities) / len(similarities)
                logger.info(
                    "[auto_label] Applied label=%s cluster_id=%s members=%d avg_sim=%.3f",
                    label,
                    cluster.id,
                    len(identities),
                    avg_similarity,
                )

        return cluster

    async def update_cluster_metadata(
        self,
        cluster_id: str,
        label: str | None = None,
        representative_id: str | None = None,
    ) -> IdentityCluster:
        """Update cluster label or representative metadata."""
        cluster = await self._clusters.get_by_id(cluster_id)
        if not cluster:
            raise ClusterNotFoundError(cluster_id)

        cluster.label = label
        cluster.is_labeled = bool(label)
        if representative_id is not None:
            cluster.representative_identity_id = representative_id

        return await self._clusters.update(cluster)

    async def refresh_representatives_for_cluster(self, cluster_id: str) -> None:
        """Trigger recomputation of representatives for a specific cluster.

        Args:
            cluster_id: The UUID of the cluster to refresh.
        """
        await self.recompute_representatives(cluster_id)

    async def assign_to_existing_cluster(
        self,
        identity: MediaIdentity,
        cluster_id: str,
        similarity: float,
    ) -> None:
        """Assign an identity to an existing cluster via representative match."""
        cluster = await self._clusters.get_by_id(cluster_id)
        if not cluster:
            raise ClusterNotFoundError(cluster_id)

        # Add as member
        await self._members.add_member(
            cluster_id=cluster_id,
            identity_id=identity.id,
            similarity=similarity,
        )

        # Optionally add as representative if diverse enough
        existing_reps = await self._clusters.get_all_representatives(cluster_id)
        current_count = len(existing_reps) if existing_reps else 0

        if current_count < self._settings.max_representatives_per_cluster:
            is_diverse = True
            if existing_reps:
                identity_vec = np.array(identity.embedding, dtype=np.float32)
                for rep in existing_reps:
                    rep_embedding = cast(np.ndarray, getattr(rep, "embedding", rep))
                    rep_sim = compute_face_similarity(identity_vec, rep_embedding)
                    if rep_sim > self._settings.representative_diversity_threshold:
                        is_diverse = False
                        break

            if is_diverse:
                await self._create_and_add_representative(
                    cluster_id=cluster_id,
                    identity=identity,
                    reason="diverse_addition",
                    existing_rep_count=current_count,
                )

        # Update member count
        cluster.identity_count += 1
        await self._clusters.update(cluster)


def _locator_payload(identity: MediaIdentity) -> dict[str, object] | None:
    if identity.bbox_x is None or identity.bbox_y is None:
        return None
    try:
        return IdentityLocator(
            media_id=int(identity.media_id),
            bbox_x=int(identity.bbox_x),
            bbox_y=int(identity.bbox_y),
            bbox_width=int(identity.bbox_width),
            bbox_height=int(identity.bbox_height),
            crop_hash=None,
        ).to_dict()
    except (TypeError, ValueError):
        return None
