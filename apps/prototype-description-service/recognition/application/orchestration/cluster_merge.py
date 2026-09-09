"""
Cluster merge operations.

Keeps merge concerns (member reassignment, representative recomputation, and post-merge retry matching)
out of the main ClusterService façade.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

import numpy as np
from sqlalchemy import Select, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityMember as MemberModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.assignment import AssignmentCandidate, AssignmentGate, AssignmentOutcome, DiscoveryMethod
from recognition.application.events.broadcaster import get_event_broadcaster
from recognition.application.identity_mapping import media_identity_from_model
from recognition.application.orchestration.curation import update_cluster
from recognition.application.orchestration.protocols import MergeSuggestionServiceProtocol, SuggestionServiceProtocol
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.suggestions.embedding_space import (
    models_are_same_space,
    same_space_representative_vectors,
)
from recognition.domain.cluster import IdentityCluster, ReservedClusterLabelError, is_reserved_label_shape
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus
from recognition.observability import ClusteringLogger
from recognition.shared.similarity import normalize_face_embedding
from recognition.shared.tenant import coerce_tenant_uuid

logger = logging.getLogger(__name__)


async def _retry_pending_suggestions(
    *,
    pending_suggestions: Sequence[AssignmentSuggestion],
    target_cluster_id: str,
    session: AsyncSession,
    member_repo: MemberRepository,
    gate: AssignmentGate,
    assignment_writer: AssignmentWriter,
    suggestion_service: SuggestionServiceProtocol,
    gallery_model: str | None,
    rep_face_vecs: Sequence[np.ndarray],
    processed_identity_ids: set[str],
) -> tuple[int, int, int]:
    """Re-score pending suggestions against one representative space."""
    accepted = 0
    suggested = 0
    evaluated = 0

    for suggestion in pending_suggestions:
        identity_id = suggestion.identity_id
        if not identity_id or identity_id in processed_identity_ids:
            continue
        processed_identity_ids.add(identity_id)

        existing_members = await member_repo.get_by_identity_id(identity_id)
        if existing_members:
            resolution = "accepted" if any(m.cluster_id == target_cluster_id for m in existing_members) else "rejected"
            await suggestion_service.resolve_for_identity(identity_id, target_cluster_id, resolution=resolution)
            continue

        try:
            identity_uuid = uuid.UUID(str(identity_id))
        except ValueError:
            continue

        model = await session.get(MediaIdentityModel, identity_uuid)
        if not model or model.embedding is None:
            continue

        identity = media_identity_from_model(model)
        if not models_are_same_space(identity.embedding_model, gallery_model):
            await suggestion_service.resolve_for_identity(identity_id, target_cluster_id, resolution="rejected")
            continue

        face_vec = normalize_face_embedding(identity.embedding)
        best_sim = max(float(np.dot(face_vec, rep_vec)) for rep_vec in rep_face_vecs)
        candidate = AssignmentCandidate(
            identity=identity,
            identity_vector=face_vec,
            cluster_id=target_cluster_id,
            discovery_method=DiscoveryMethod.REPRESENTATIVE,
            discovery_similarity=best_sim,
        )

        decision = None
        confidence_score = best_sim
        if best_sim >= gate.settings.similarity_threshold:
            evaluated += 1
            decision = await gate.evaluate(candidate)
            suggestion_confidence = decision.suggestion_confidence
            if suggestion_confidence is not None:
                confidence_score = float(suggestion_confidence)

        await suggestion_service.update_scores(
            suggestion.id,
            representative_similarity=best_sim,
            member_similarity=best_sim,
            confidence_score=confidence_score,
        )

        if decision is None:
            continue
        if decision.outcome == AssignmentOutcome.ACCEPT:
            await assignment_writer.persist_assignment(decision)
            accepted += 1
            await suggestion_service.resolve_for_identity(identity.id, target_cluster_id, resolution="accepted")
        elif decision.outcome == AssignmentOutcome.SUGGEST:
            suggested += 1

    return accepted, suggested, evaluated


async def _retry_unclustered_models(
    *,
    models: Sequence[MediaIdentityModel],
    target_cluster_id: str,
    gate: AssignmentGate,
    assignment_writer: AssignmentWriter,
    suggestion_service: SuggestionServiceProtocol,
    gallery_model: str | None,
    rep_face_vecs: Sequence[np.ndarray],
    processed_identity_ids: set[str],
    min_similarity_for_unclustered: float,
) -> tuple[int, int, int]:
    """Assign or suggest high-confidence identities from one gallery space."""
    accepted = 0
    suggested = 0
    evaluated = 0

    for model in models:
        identity_id = str(model.id)
        if identity_id in processed_identity_ids:
            continue
        processed_identity_ids.add(identity_id)

        identity = media_identity_from_model(model)
        if not models_are_same_space(identity.embedding_model, gallery_model):
            continue
        face_vec = normalize_face_embedding(identity.embedding)
        best_sim = max(float(np.dot(face_vec, rep_vec)) for rep_vec in rep_face_vecs)
        if best_sim < min_similarity_for_unclustered or best_sim < gate.settings.similarity_threshold:
            continue

        evaluated += 1
        candidate = AssignmentCandidate(
            identity=identity,
            identity_vector=face_vec,
            cluster_id=target_cluster_id,
            discovery_method=DiscoveryMethod.REPRESENTATIVE,
            discovery_similarity=best_sim,
        )
        decision = await gate.evaluate(candidate)
        if decision.outcome == AssignmentOutcome.ACCEPT:
            await assignment_writer.persist_assignment(decision)
            accepted += 1
        elif decision.outcome == AssignmentOutcome.SUGGEST:
            await suggestion_service.create(candidate, decision.suggestion_confidence)
            suggested += 1

    return accepted, suggested, evaluated


async def post_merge_retry_matching(
    *,
    tenant_id: str,
    target_cluster_id: str,
    session: AsyncSession | None,
    gate: AssignmentGate,
    assignment_writer: AssignmentWriter,
    suggestion_service: SuggestionServiceProtocol,
    max_unclustered: int = 200,
    min_similarity_for_unclustered: float = 0.95,
) -> None:
    """Best-effort post-merge matching pass for the updated target cluster.

    Session contract: ``session`` must already be under the correct tenant
    context (``app.current_tenant``) with RLS bypass enabled
    (``app.bypass_rls = 'true'``).  Both settings are transaction-scoped
    (``SET LOCAL``); callers that commit before invoking this function must
    re-establish them after the commit.  If ``session`` is ``None`` this
    function returns immediately without doing work.
    """
    if session is None:
        return

    cluster_repo: ClusterRepository = assignment_writer.cluster_repository
    member_repo: MemberRepository = assignment_writer.member_repository

    reps = await cluster_repo.get_all_representatives(target_cluster_id)
    if not reps:
        return

    gallery_model, gallery_vectors = same_space_representative_vectors(reps)
    rep_face_vecs = [normalize_face_embedding(vector) for vector in gallery_vectors]
    if not rep_face_vecs:
        return

    processed_identity_ids: set[str] = set()

    # 1) Re-evaluate pending suggestions for the target cluster.
    suggestions_for_cluster = await suggestion_service.get_by_cluster(target_cluster_id)
    pending_suggestions = [s for s in suggestions_for_cluster if s.status == SuggestionStatus.PENDING]
    accepted, suggested, evaluated = await _retry_pending_suggestions(
        pending_suggestions=pending_suggestions,
        target_cluster_id=target_cluster_id,
        session=session,
        member_repo=member_repo,
        gate=gate,
        assignment_writer=assignment_writer,
        suggestion_service=suggestion_service,
        gallery_model=gallery_model,
        rep_face_vecs=rep_face_vecs,
        processed_identity_ids=processed_identity_ids,
    )

    # 2) Try high-confidence matches from remaining unclustered identities.
    try:
        tenant_uuid = coerce_tenant_uuid(tenant_id)
    except ValueError:
        tenant_uuid = None

    if tenant_uuid is not None and max_unclustered > 0:
        stmt: Select[tuple[MediaIdentityModel]] = (
            select(MediaIdentityModel)
            .where(MediaIdentityModel.tenant_id == tenant_uuid)
            .where(~exists(select(MemberModel.id).where(MemberModel.identity_id == MediaIdentityModel.id)))
            .order_by(MediaIdentityModel.confidence.desc())
            .limit(max_unclustered)
        )
        if gallery_model is not None:
            stmt = stmt.where(MediaIdentityModel.embedding_model == gallery_model)
        else:
            stmt = stmt.where(MediaIdentityModel.embedding_model.is_(None))
        result = await session.execute(stmt)
        unclustered_models = result.scalars().all()
        additional_accepted, additional_suggested, additional_evaluated = await _retry_unclustered_models(
            models=unclustered_models,
            target_cluster_id=target_cluster_id,
            gate=gate,
            assignment_writer=assignment_writer,
            suggestion_service=suggestion_service,
            gallery_model=gallery_model,
            rep_face_vecs=rep_face_vecs,
            processed_identity_ids=processed_identity_ids,
            min_similarity_for_unclustered=min_similarity_for_unclustered,
        )
        accepted += additional_accepted
        suggested += additional_suggested
        evaluated += additional_evaluated

    if accepted or suggested:
        logger.info(
            "[clustering] post_merge_retry tenant_id=%s target_cluster=%s evaluated=%d accepted=%d suggested=%d",
            tenant_id,
            target_cluster_id,
            evaluated,
            accepted,
            suggested,
        )


async def merge_cluster(
    *,
    source_cluster_id: str,
    tenant_id: str,
    target_cluster_id: str,
    target_label: str | None,
    assignment_writer: AssignmentWriter,
    suggestion_service: SuggestionServiceProtocol,
    gate: AssignmentGate,
    merge_suggestion_service: MergeSuggestionServiceProtocol | None = None,
    clustering_logger: ClusteringLogger | None = None,
    session: AsyncSession | None = None,
    defer_recompute: bool = False,
    moved_by_merge_id: str | None = None,
) -> IdentityCluster | None:
    """Merge a source cluster into a target cluster by reassigning members."""
    if is_reserved_label_shape(target_label):
        raise ReservedClusterLabelError(target_label)

    cluster_repo: ClusterRepository = assignment_writer.cluster_repository
    member_repo: MemberRepository = assignment_writer.member_repository

    source = await cluster_repo.get_by_id(source_cluster_id)
    target = await cluster_repo.get_by_id(target_cluster_id)
    if not source or not target:
        return None
    # Normalize UUIDs to lowercase for comparison (db stores lowercase)
    if source.tenant_id.lower() != tenant_id.lower() or target.tenant_id.lower() != tenant_id.lower():
        return None

    # If source and target are identical, treat as a label/confirmation update.
    if source.id == target.id:
        return await update_cluster(
            cluster_id=target_cluster_id,
            tenant_id=tenant_id,
            label=target_label or target.label,
            assignment_writer=assignment_writer,
            clustering_logger=clustering_logger,
        )

    moved_identity_ids: list[uuid.UUID] = []
    if moved_by_merge_id and session is not None:
        source_members = await member_repo.get_by_cluster(source_cluster_id)
        for member in source_members:
            try:
                moved_identity_ids.append(uuid.UUID(str(member.identity_id)))
            except ValueError:
                continue

    moved = await member_repo.move_members(source_cluster_id, target_cluster_id)
    if moved_by_merge_id and session is not None and moved_identity_ids:
        try:
            provenance_uuid = uuid.UUID(str(moved_by_merge_id))
        except ValueError:
            provenance_uuid = None
        if provenance_uuid is not None:
            await session.execute(
                update(MediaIdentityModel)
                .where(MediaIdentityModel.id.in_(moved_identity_ids))
                .values(moved_by_merge_id=provenance_uuid)
            )
            await session.flush()

    target.identity_count = (target.identity_count or 0) + moved
    final_label = target_label or target.label
    target.label = final_label
    target.is_labeled = bool(final_label)
    # Only stamp operator confirmation for a meaningful final label. Reserved /
    # empty survivors must keep their prior user_confirmed (do not force False).
    if final_label and not is_reserved_label_shape(final_label):
        target.user_confirmed = True
    updated: IdentityCluster = await cluster_repo.update(target)

    # Source cluster deletion moved to end of function to prevent early commit failures
    #
    # In deferred mode, source deletion happens in a queued curation job. Until that
    # job runs, keep source hidden from top-unlabeled queues by zeroing its count now.
    # Otherwise stale identity_count can surface an empty cluster card in the UI.
    if defer_recompute:
        source.identity_count = 0
        await cluster_repo.update(source)

    # [Optimized] Constraint creation deferred/removed from sync path.
    # Logic for MUST_LINK creation should be moved to curation_job if needed.

    if not defer_recompute:
        await assignment_writer.recompute_representatives(target_cluster_id)
        await assignment_writer.recompute_centroid(target_cluster_id)
        # Best-effort: the merge is already applied. refresh_centroids_view is
        # fail-fast (INFRA-5), but a transient MV-refresh failure must not roll
        # back a completed user-facing merge (bulk-accept would discard the whole
        # batch). The recomputed centroid is persisted; the scan worker's periodic
        # concurrent refresh heals the MV lag.
        try:
            await assignment_writer.refresh_centroids_view()
        except Exception:
            logger.warning(
                "Post-merge centroid MV refresh failed for target_cluster_id=%s; "
                "centroids may lag until the next scheduled refresh",
                target_cluster_id,
                exc_info=True,
            )

        # Resolve any pending suggestions for identities moved into the target cluster
        try:
            members = await member_repo.get_by_cluster(target_cluster_id)
            for member in members:
                # We only need to check identities that were recently moved,
                # but resolve_for_identity_exclusive already checks for pending status.
                await suggestion_service.resolve_for_identity_exclusive(
                    identity_id=str(member.identity_id),
                    accepted_cluster_id=target_cluster_id,
                    reason="manual_merge",
                )
        except Exception:
            logger.warning(
                "Failed to resolve pending suggestions after merge for target_cluster_id=%s",
                target_cluster_id,
                exc_info=True,
            )

    # Broadcast merge event
    broadcaster = get_event_broadcaster()
    await broadcaster.broadcast(
        "cluster_merged",
        {
            "source_cluster_id": source_cluster_id,
            "target_cluster_id": target_cluster_id,
            "moved_count": moved,
        },
        tenant_id=tenant_id,
    )

    if not defer_recompute:
        # Delete source cluster LAST, after all recomputations and logging are complete.
        # This avoids "Cluster not found" 404s during session flush if other operations reference it.
        if merge_suggestion_service is not None:
            try:
                await merge_suggestion_service.delete_by_cluster(tenant_id, source_cluster_id)
                await merge_suggestion_service.delete_by_cluster(tenant_id, target_cluster_id)
            except Exception:
                logger.warning(
                    "Failed to delete merge suggestions for source_cluster_id=%s target_cluster_id=%s",
                    source_cluster_id,
                    target_cluster_id,
                    exc_info=True,
                )
        await cluster_repo.delete(source_cluster_id)

        # Ensure identity_count reflects reassignment via full count if checked immediately
        updated.identity_count = len(await member_repo.get_by_cluster(target_cluster_id))

    return updated
