"""
AssignmentWriter interface for persisting gate decisions (Phase 5).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import cast

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.labeling.auto_labeler import allocate_person_label, should_auto_label
from recognition.application.persistence.centroid_maintainer import CentroidMaintainer
from recognition.application.persistence.representative_selector import (
    RepAdmission,
    RepresentativeSelector,
    _compute_identity_quality,
    _select_diverse_representatives,
    enrollment_floors_from_settings,
    passes_enrollment_floors,
)
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster, ReservedClusterLabelError, is_reserved_label_shape
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
        self._centroids = CentroidMaintainer(cluster_repository)
        self._reps = RepresentativeSelector(settings, cluster_repository)

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

    def _emit_representative_upgraded_event(
        self,
        *,
        is_upgrade: bool,
        cluster_id: str,
        identity_id: str,
        rep: ClusterRepresentative,
    ) -> None:
        """Emit a `representative_upgraded` event when a genuine quality upgrade occurred.

        Shared by both write paths (`persist_assignment` + `persist_assignments_chunk`) so the
        upgrade reason and its event stay coupled across single and batch persistence.
        """
        if not (is_upgrade and self._run_context):
            return

        self._run_context.add_event(
            event_type="representative_upgraded",
            identity_id=identity_id,
            cluster_id=cluster_id,
            payload={
                "representative_id": rep.id,
                "quality": float(rep.quality_score or 0),
            },
        )

    async def _create_and_add_representative(
        self,
        cluster_id: str,
        identity: MediaIdentity,
        reason: str,
        is_provisional: bool = False,
        is_user_selected: bool = False,
        existing_rep_count: int | None = None,
        *,
        enforce_enrollment_floors: bool = True,
    ) -> ClusterRepresentative | None:
        """Create and persist a representative, emitting events.

        FIR-6 S3b: identities failing active enrollment floors are excluded
        (no rep row, no quality_score write). Returns ``None`` when gated out.
        Pass ``enforce_enrollment_floors=False`` only for the best-available
        fallback when every member fails floors (FIR6S3B-M-01) so the cluster
        still gets a rep+centroid for CentroidDiscovery.
        """
        floors = enrollment_floors_from_settings(self._settings)
        if enforce_enrollment_floors and not passes_enrollment_floors(identity, floors):
            logger.info(
                "[enrollment_gate] SKIP_CREATE cluster=%s identity=%s reason=%s "
                "sharpness=%s embedding_norm=%s occlusion_severity=%s",
                cluster_id,
                identity.id,
                reason,
                identity.sharpness,
                identity.embedding_norm,
                identity.occlusion_severity,
            )
            return None

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

        admission = await self._should_add_representative(decision, batch_mode=batch_mode)
        if admission.should_add:
            # Store the full 1024D embedding, not the face-only 512D vector
            # Identify if this was an upgrade vs novel addition for the reason
            is_upgrade = admission.was_upgrade
            reason = "representative_upgrade" if is_upgrade else "diverse_addition"
            if not is_upgrade and admission.was_novel_pose:
                reason = "novel_pose_addition"

            rep = await self._create_and_add_representative(
                cluster_id=decision.candidate.cluster_id,
                identity=decision.candidate.identity,
                reason=reason,
                is_provisional=batch_mode,
                existing_rep_count=admission.rep_count,
            )

            # Enrollment gate may still refuse create (defensive); skip centroid
            # and upgrade events when no representative was materialised.
            if rep is not None:
                self._emit_representative_upgraded_event(
                    is_upgrade=is_upgrade,
                    cluster_id=decision.candidate.cluster_id,
                    identity_id=decision.candidate.identity.id,
                    rep=rep,
                )

                # Compute centroid from the cached reps (returned by _should_add_representative)
                # plus the newly added rep -- this avoids a redundant get_all_representatives
                # DB round-trip (Phase 3: duplicate-read elimination).
                all_rep_embeddings = [r.embedding for r in admission.cached_reps]
                all_rep_embeddings.append(rep.embedding)
                new_centroid = self._centroids.unit_normalized_mean(all_rep_embeddings)
                if new_centroid is not None:
                    cluster.centroid = new_centroid

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
        *,
        joint_uniqueness_enabled: bool = False,
    ) -> tuple[int, int, int, set[str]]:
        """Bulk-persist accepted assignment decisions for one processing chunk.

        Groups decisions by cluster and issues a single bulk INSERT per cluster
        (ON CONFLICT DO NOTHING) instead of N per-identity round-trips.  Only
        newly-inserted members receive representative, centroid, and curriculum
        updates; idempotent skips are counted but not re-processed.

        When ``joint_uniqueness_enabled`` is True (face_pipeline joint path), a
        same-photo uniqueness guard rejects decisions whose media_id is already
        represented in the target cluster (existing members or an earlier
        higher-similarity decision in this chunk). Rejected identity ids are
        returned so the orchestrator can rebind partition inputs (never orphan).

        Returns:
            (total_persisted, total_skipped, reps_added, guard_rejected_ids) —
            persisted is newly inserted, skipped is ON CONFLICT matches,
            reps_added is new representatives created, guard_rejected_ids are
            identities blocked by the joint uniqueness guard.
        """
        if not decisions:
            return 0, 0, 0, set()

        from collections import defaultdict

        by_cluster: dict[str, list[AssignmentDecision]] = defaultdict(list)
        for decision in decisions:
            by_cluster[decision.candidate.cluster_id].append(decision)

        total_persisted = 0
        total_skipped = 0
        _reps_added = 0
        guard_rejected_ids: set[str] = set()

        for cluster_id, cluster_decisions in by_cluster.items():
            cluster = await self._clusters.get_by_id(cluster_id)
            if not cluster:
                logger.warning(
                    "[assignment_writer] persist_assignments_chunk: cluster %s not found, skipping",
                    cluster_id,
                )
                total_skipped += len(cluster_decisions)
                continue

            if joint_uniqueness_enabled:
                cluster_decisions, rejected = await self._apply_joint_uniqueness_guard(
                    cluster_id, cluster_decisions
                )
                guard_rejected_ids.update(rejected)
                if not cluster_decisions:
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
                admission = await self._should_add_representative(decision, batch_mode=batch_mode)
                if admission.should_add:
                    is_upgrade = admission.was_upgrade
                    reason = "representative_upgrade" if is_upgrade else "diverse_addition"
                    if not is_upgrade and admission.was_novel_pose:
                        reason = "novel_pose_addition"
                    rep = await self._create_and_add_representative(
                        cluster_id=cluster_id,
                        identity=decision.candidate.identity,
                        reason=reason,
                        is_provisional=batch_mode,
                        existing_rep_count=len(admission.cached_reps),
                    )
                    if rep is None:
                        continue
                    _reps_added += 1
                    self._emit_representative_upgraded_event(
                        is_upgrade=is_upgrade,
                        cluster_id=cluster_id,
                        identity_id=decision.candidate.identity.id,
                        rep=rep,
                    )
                    all_rep_embeddings = [r.embedding for r in admission.cached_reps]
                    all_rep_embeddings.append(rep.embedding)
                    new_centroid = self._centroids.unit_normalized_mean(all_rep_embeddings)
                    if new_centroid is not None:
                        cluster.centroid = new_centroid

            # Single cluster identity_count update for all newly inserted members.
            cluster.identity_count += len(newly_inserted)
            await self._clusters.update(cluster)

            # Curriculum EMA: per-identity atomic update but only for new members.
            for decision in newly_inserted:
                await self._update_curriculum_t(cluster_id, decision.candidate.discovery_similarity)

        return total_persisted, total_skipped, _reps_added, guard_rejected_ids

    async def _apply_joint_uniqueness_guard(
        self,
        cluster_id: str,
        decisions: list[AssignmentDecision],
    ) -> tuple[list[AssignmentDecision], set[str]]:
        """Reject same-photo duplicates within a cluster (face_pipeline only).

        Existing cluster members and earlier higher-similarity decisions in this
        batch occupy a media_id; later/lower-similarity faces for that media_id
        are rejected so the orchestrator can route them to new-cluster/unknown.

        An identity already member of the target cluster does not occupy media
        against itself (chunk re-process / ON CONFLICT skip path stays idempotent).
        """
        existing = await self._clusters.get_member_identities(cluster_id)
        occupants_by_media: dict[str, set[str]] = {}
        for identity in existing:
            media_id = str(identity.media_id)
            occupants_by_media.setdefault(media_id, set()).add(str(identity.id))
        ordered = sorted(
            decisions,
            key=lambda decision: (
                decision.candidate.discovery_similarity,
                decision.candidate.identity.confidence,
                decision.candidate.identity.id,
            ),
            reverse=True,
        )
        kept: list[AssignmentDecision] = []
        rejected: set[str] = set()
        batch_media: set[str] = set()
        for decision in ordered:
            identity_id = str(decision.candidate.identity.id)
            media_id = str(decision.candidate.identity.media_id)
            foreign_occupants = occupants_by_media.get(media_id, set()) - {identity_id}
            if foreign_occupants or media_id in batch_media:
                rejected.add(identity_id)
                continue
            kept.append(decision)
            batch_media.add(media_id)
        if rejected:
            logger.info(
                "[assignment_writer] joint_uniqueness cluster=%s rejected=%d kept=%d",
                cluster_id,
                len(rejected),
                len(kept),
            )
        return kept, rejected

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
        await self._centroids.refresh_centroids_view()

    async def refresh_centroids_view_concurrent(self) -> bool:
        """Trigger a concurrent refresh of the cluster centroids view. Returns True on success."""
        return await self._centroids.refresh_centroids_view_concurrent()

    async def _should_add_representative(self, decision: AssignmentDecision, batch_mode: bool = False) -> RepAdmission:
        """Delegate the representative-admission decision to :class:`RepresentativeSelector`.

        Retained as a thin delegator so existing callers and unit tests that exercise
        the admission decision through the writer keep working after the Slice 9 3b
        extraction.
        """
        return await self._reps.should_add_representative(decision, batch_mode)

    async def recompute_centroid(self, cluster_id: str) -> np.ndarray | None:
        """Recompute cluster centroid from representatives.

        Returns None if no representatives exist for the cluster.
        """
        return await self._centroids.recompute_centroid(cluster_id)

    async def recompute_representatives(self, cluster_id: str) -> None:
        """Recompute cluster representatives using FPS for diversity while preserving pins/quality."""
        cluster = await self._clusters.get_by_id(cluster_id)
        if not cluster:
            raise ClusterNotFoundError(cluster_id)

        # 1. Identify what to preserve
        preserved = await self._reps.select_reps_to_preserve(cluster_id)
        preserved_ids = {p.identity_id for p in preserved}
        preserved_embeddings = [p.embedding for p in preserved]

        # 2. Clear representatives
        await self._clusters.clear_representatives(cluster_id)

        # 3. Get all member identities (excluding already preserved ones)
        floors = enrollment_floors_from_settings(self._settings)
        all_members = list(await self._clusters.get_member_identities(cluster_id))
        identities = [
            i
            for i in all_members
            if i.embedding is not None
            and i.id not in preserved_ids
            and passes_enrollment_floors(i, floors)
        ]
        # Best-available fallback (FIR6S3B-M-01): when floors exclude every member
        # and nothing was preserved (pose buckets are None under face_pipeline),
        # still enroll from the full member pool so the cluster never ends with
        # representative_identity_id=None while members exist.
        best_available_fallback = False
        if not identities and not preserved:
            identities = [
                i for i in all_members if i.embedding is not None and i.id not in preserved_ids
            ]
            if identities:
                best_available_fallback = True
                logger.info(
                    "[enrollment_gate] BEST_AVAILABLE_FALLBACK recompute cluster=%s "
                    "members=%d floors=(s>=%.3f,n>=%.3f,o<=%.3f)",
                    cluster_id,
                    len(identities),
                    floors.floor_sharpness,
                    floors.floor_embedding_norm,
                    floors.ceiling_occlusion,
                )
        # Sort by quality so FPS starts with the best one if no seeds
        identities.sort(key=lambda i: _compute_identity_quality(i, self._settings), reverse=True)

        # 4. Fill remaining slots with diverse additions
        max_base = self._settings.max_representatives_per_cluster
        available_slots = max_base - len(preserved)

        selected_new: list[MediaIdentity] = []
        if available_slots > 0 and identities:
            selected_new = self._reps.select_diverse_representatives_seeded(
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
                reason=(
                    "fps_recompute_best_available"
                    if best_available_fallback
                    else "fps_recompute_diversity"
                ),
                enforce_enrollment_floors=not best_available_fallback,
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
        # to preserve "bridge" faces that connect different pose angles.
        # FIR-6 S3b: prefer observations that clear active factor floors.
        # Best-available fallback (FIR6S3B-M-01): when every member fails floors,
        # still seed a rep+centroid so CentroidDiscovery can find the cluster.
        floors = enrollment_floors_from_settings(self._settings)
        eligible = [i for i in identities if passes_enrollment_floors(i, floors)]
        best_available_fallback = False
        if eligible:
            rep_pool = eligible
        elif identities:
            rep_pool = list(identities)
            best_available_fallback = True
            logger.info(
                "[enrollment_gate] BEST_AVAILABLE_FALLBACK persist_new_cluster "
                "cluster=%s members=%d floors=(s>=%.3f,n>=%.3f,o<=%.3f)",
                cluster_id_str,
                len(identities),
                floors.floor_sharpness,
                floors.floor_embedding_norm,
                floors.ceiling_occlusion,
            )
        else:
            rep_pool = []

        if rep_pool:
            diverse_reps = _select_diverse_representatives(
                rep_pool,
                self._settings.max_representatives_per_cluster,
            )
            for identity in diverse_reps:
                await self._create_and_add_representative(
                    cluster_id=cluster_id_str,
                    identity=identity,
                    reason="fps_seed_best_available" if best_available_fallback else "fps_seed",
                    enforce_enrollment_floors=not best_available_fallback,
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
        if is_reserved_label_shape(label):
            raise ReservedClusterLabelError(label)

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
                rep = await self._create_and_add_representative(
                    cluster_id=cluster_id,
                    identity=identity,
                    reason="diverse_addition",
                    existing_rep_count=current_count,
                )
                if rep is None:
                    logger.debug(
                        "[enrollment_gate] assign_to_existing_cluster skipped rep for %s",
                        identity.id,
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
