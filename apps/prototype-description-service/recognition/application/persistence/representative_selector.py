"""RepresentativeSelector: the representative-selection surface of the clustering writer.

Extracted from ``AssignmentWriter`` (Slice 9 sub-slice 3b) so the admission decision,
pose-bucket/upgrade logic, and FPS diversity math live in one cohesive object instead
of being interleaved with persistence orchestration. The class is *not* pure: the
admission decision issues a representative removal (upgrade path) and the preserve
query reads representatives, so it legitimately takes a ``ClusterRepository``.

Dependency direction is downward only (``domain.*`` + ``application.settings`` +
``application.assignment.{decision,quality}`` + ``shared.similarity``); this module
must never import ``assignment_writer`` so the two form no import cycle.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np

from recognition.application.assignment.decision import AssignmentDecision
from recognition.application.assignment.quality import compute_identity_quality as _compute_quality_info
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository
from recognition.domain.representative import ClusterRepresentative
from recognition.shared.similarity import compute_face_similarity, extract_face_embedding

logger = logging.getLogger(__name__)


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
    considers detection confidence and face size (pose-neutral, FIR2-BR-03).

    Args:
        identity: MediaIdentity with confidence and bbox dimensions.
        settings: Clustering settings containing quality parameters.

    Returns:
        Quality score between 0.0 and 1.0.
    """
    info = _compute_quality_info(
        confidence=identity.confidence,
        bbox_width=identity.bbox_width,
        bbox_height=identity.bbox_height,
        settings=settings.quality,
        occlusion_severity=identity.occlusion_severity,
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


@dataclass(frozen=True)
class RepAdmission:
    """Result of the representative-admission decision.

    Replaces the former ``_last_*`` instance-state side effects of
    ``should_add_representative`` with an explicit return value. ``was_upgrade`` is
    True when the decision replaced a lower-quality representative in the same pose
    bucket (Slice 9 sub-slice 3a-fix restored this signal after a reset bug had pinned
    it False). ``rep_count`` is the pre-upgrade-removal representative count (what
    ``persist_assignment`` passes as ``existing_rep_count``).
    """

    should_add: bool
    cached_reps: list[ClusterRepresentative]
    rep_count: int
    was_upgrade: bool
    was_novel_pose: bool


class RepresentativeSelector:
    """Own the representative-selection surface for a cluster repository.

    Not pure: ``should_add_representative`` removes an upgraded-out representative and
    ``select_reps_to_preserve`` reads representatives, so the selector holds the
    ``ClusterRepository``. Persistence orchestration (creating/persisting reps, emitting
    events) remains on ``AssignmentWriter``.
    """

    def __init__(self, settings: ClusteringSettings, cluster_repository: ClusterRepository) -> None:
        self._settings = settings
        self._clusters = cluster_repository

    async def should_add_representative(self, decision: AssignmentDecision, batch_mode: bool = False) -> RepAdmission:
        """Determine if the assigned identity should become a representative.

        Returns a :class:`RepAdmission` whose ``cached_reps`` reflects the current
        DB state *after* any upgrade removal so the caller can compute the new
        centroid from cached data without a second DB round-trip (Phase 3
        duplicate-read elimination). ``rep_count`` is the pre-removal count.

        ``was_upgrade`` is True when an existing lower-quality representative in the
        same pose bucket was removed to make room for this one (Slice 9 sub-slice
        3a-fix; the upgrade reason + ``representative_upgraded`` event depend on it).
        """
        cluster_id = decision.candidate.cluster_id

        # Fetch all reps once; this is the only get_all_representatives call
        # for the accepted-assignment path (Phase 3: remove duplicate reads).
        existing_reps: list[ClusterRepresentative] = list(await self._clusters.get_all_representatives(cluster_id))
        current_count = len(existing_reps)

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
                return RepAdmission(False, existing_reps, current_count, was_upgrade=False, was_novel_pose=False)

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

        # cached_reps = existing_reps minus any rep just removed by the upgrade path.
        cached_reps = [r for r in existing_reps if r.id != removed_rep_id] if removed_rep_id else existing_reps

        # An upgrade occurred iff we removed a lower-quality rep in the same pose
        # bucket above. Carrying this through restores the upgrade reason + the
        # representative_upgraded event that the former unconditional reset
        # clobbered (Slice 9 sub-slice 3a-fix; behaviour-changing observability fix).
        was_upgrade = removed_rep_id is not None

        # 2. Check limits with bonus
        max_base = self._settings.max_representatives_per_cluster
        max_total = max_base + self._settings.pose_diversity_bonus

        # In batch_mode, we allow adding even if we reached the limit,
        # provided it's a novel pose or diverse, because they will be provisional.
        # Actually, the upgrade logic (1) already handles replacing.
        # For new additions:
        if not batch_mode and current_count >= max_total:
            return RepAdmission(False, cached_reps, current_count, was_upgrade=False, was_novel_pose=False)

        # 3. If above base limit, only add if novel pose
        if current_count >= max_base:
            if _is_novel_pose(decision.candidate.identity, existing_reps, self._settings.pose_bucket_size):
                return RepAdmission(True, cached_reps, current_count, was_upgrade=was_upgrade, was_novel_pose=True)
            # If batch_mode, we might still want to add it if it's "better" than nothing?
            # No, if not novel pose and no upgrade target, it's redundant.
            return RepAdmission(False, cached_reps, current_count, was_upgrade=False, was_novel_pose=False)

        if not existing_reps:
            return RepAdmission(True, cached_reps, current_count, was_upgrade=was_upgrade, was_novel_pose=False)

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
                return RepAdmission(False, cached_reps, current_count, was_upgrade=False, was_novel_pose=False)

        return RepAdmission(True, cached_reps, current_count, was_upgrade=was_upgrade, was_novel_pose=False)

    async def select_reps_to_preserve(
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
        logger.debug("[select_reps_to_preserve] Found %d pinned reps", len(pinned))

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
                    "[select_reps_to_preserve] Adding best-of-bucket rep: %s for bucket %s",
                    rep.identity_id,
                    _get_pose_bucket(rep, self._settings.pose_bucket_size),
                )
                preserved[rep.id] = rep
            else:
                logger.debug(
                    "[select_reps_to_preserve] Best-of-bucket rep %s already preserved (pinned)",
                    rep.identity_id,
                )

        return list(preserved.values())

    def select_diverse_representatives_seeded(
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
