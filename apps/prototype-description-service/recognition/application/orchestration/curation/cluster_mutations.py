"""Cluster mutation helpers for curation workflows."""

from __future__ import annotations

import contextlib
import logging
import uuid
from enum import StrEnum

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.events.broadcaster import get_event_broadcaster
from recognition.application.identity_mapping import media_identity_from_model
from recognition.application.orchestration.curation.cluster_queries import get_identity_cluster_id
from recognition.application.orchestration.curation.similarity import (
    check_and_refresh_representatives,
    compute_curation_similarity,
)
from recognition.application.orchestration.protocols import SuggestionServiceProtocol
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import IdentityCluster, ReservedClusterLabelError, is_reserved_label_shape
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.observability import ClusteringLogger, CurationEventType
from recognition.shared.tenant import coerce_tenant_uuid

logger = logging.getLogger(__name__)

_CURRICULUM_FALSE_NEGATIVE_DELTA = 0.01
_CURRICULUM_FALSE_POSITIVE_DELTA = -0.05


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


async def _adjust_curriculum_t(
    *,
    cluster_repo: ClusterRepository,
    cluster_id: str,
    delta: float,
    reason: str,
) -> None:
    """Apply a bounded curriculum adjustment for a cluster."""
    current = await cluster_repo.get_curriculum_t(cluster_id) or 0.0
    updated = _clamp01(current + delta)
    await cluster_repo.set_curriculum_t(cluster_id, updated)
    logger.info(
        "[curriculum] cluster_id=%s reason=%s prev=%.4f delta=%.4f next=%.4f",
        cluster_id,
        reason,
        current,
        delta,
        updated,
    )


async def update_cluster(
    *,
    cluster_id: str,
    tenant_id: str,
    label: str | None,
    assignment_writer: AssignmentWriter,
    clustering_logger: ClusteringLogger | None = None,
) -> IdentityCluster | None:
    """Update cluster label and confirmation state."""
    if is_reserved_label_shape(label):
        raise ReservedClusterLabelError(label)

    cluster_repo: ClusterRepository = assignment_writer.cluster_repository
    cluster = await cluster_repo.get_by_id(cluster_id)
    if not cluster or cluster.tenant_id.lower() != tenant_id.lower():
        return None

    old_label = cluster.label
    if old_label == label:
        logger.debug(
            "[curation] Skipping rename (no change) cluster_id=%s label='%s'",
            cluster_id,
            label,
        )
        return cluster

    cluster.label = label
    cluster.is_labeled = bool(label)
    cluster.user_confirmed = bool(label)
    updated = await cluster_repo.update(cluster)

    if clustering_logger and old_label != label:
        with contextlib.suppress(Exception):
            clustering_logger.log_cluster_renamed(
                cluster_id=cluster_id,
                old_label=old_label,
                new_label=label,
                tenant_id=tenant_id,
            )

    logger.info(
        "[curation] RENAMED cluster_id=%s old_label='%s' new_label='%s' "
        "tenant_id=%s user_action=manual_rename metadata_only=true",
        cluster_id,
        old_label,
        label,
        tenant_id,
    )

    broadcaster = get_event_broadcaster()
    await broadcaster.broadcast(
        "cluster_updated",
        {"cluster_id": cluster_id, "reason": "metadata_only_update", "label": label},
        tenant_id=tenant_id,
    )

    return updated


async def remove_identity_from_cluster(
    *,
    identity_id: str,
    member_repo: MemberRepository,
    cluster_repo: ClusterRepository,
    assignment_writer: AssignmentWriter | None = None,
    recompute: bool = True,
    tenant_id_for_logging: str | None = None,
    media_id: int | None = None,
    clustering_logger: ClusteringLogger | None = None,
    session: AsyncSession | None = None,
) -> bool:
    """Remove an identity from its current cluster (make it an orphan)."""
    members = await member_repo.get_by_identity_id(identity_id)
    if not members:
        return True

    cluster_id = members[0].cluster_id
    removed = await member_repo.remove_by_identity_id(identity_id)

    if removed:
        cluster = await cluster_repo.get_by_id(cluster_id)
        if cluster and cluster.identity_count > 0:
            cluster.identity_count -= 1
            await cluster_repo.update(cluster)

        with contextlib.suppress(Exception):
            await _adjust_curriculum_t(
                cluster_repo=cluster_repo,
                cluster_id=cluster_id,
                delta=_CURRICULUM_FALSE_POSITIVE_DELTA,
                reason="manual_remove",
            )

        refreshed = False
        if session and assignment_writer:
            refreshed = await check_and_refresh_representatives(
                cluster_id=cluster_id,
                removed_identity_id=identity_id,
                assignment_writer=assignment_writer,
                session=session,
                refresh=recompute,
            )

        if assignment_writer and recompute:
            if not refreshed:
                await assignment_writer.recompute_representatives(cluster_id)
            await assignment_writer.recompute_centroid(cluster_id)

        broadcaster = get_event_broadcaster()
        await broadcaster.broadcast(
            "cluster_updated",
            {"cluster_id": cluster_id, "reason": "identity_removed"},
            tenant_id=tenant_id_for_logging,
        )

    logger.info(
        "[curation] REMOVED identity=%s media_id=%s from cluster=%s tenant_id=%s user_action=manual_remove",
        identity_id,
        media_id,
        cluster_id,
        tenant_id_for_logging or "unknown",
    )

    if clustering_logger and removed:
        clustering_logger.log_curation_action(
            action=CurationEventType.REMOVE_MEMBER,
            identity_id=identity_id,
            previous_cluster_id=cluster_id,
            tenant_id=tenant_id_for_logging,
        )

    return True


async def create_cluster_for_identity(
    *,
    identity_id: str,
    label: str,
    tenant_id: str,
    desired_cluster_id: str | None,
    session: AsyncSession | None,
    assignment_writer: AssignmentWriter,
    suggestion_service: SuggestionServiceProtocol | None = None,
) -> IdentityCluster:
    """Create a new user-labeled cluster containing a single identity."""
    if is_reserved_label_shape(label):
        raise ReservedClusterLabelError(label)

    if session is None:
        raise RuntimeError("Database session is required for create_cluster_for_identity")

    try:
        tenant_uuid = coerce_tenant_uuid(tenant_id)
        identity_uuid = uuid.UUID(str(identity_id))
    except ValueError as exc:
        raise ValueError("Invalid tenant_id or identity_id") from exc

    identity_model = await session.get(MediaIdentityModel, identity_uuid)
    if not identity_model or identity_model.tenant_id != tenant_uuid:
        raise ValueError("Identity not found")

    cluster_repo: ClusterRepository = assignment_writer.cluster_repository
    member_repo: MemberRepository = assignment_writer.member_repository

    existing_cluster_id = await get_identity_cluster_id(member_repo=member_repo, identity_id=identity_id)
    if existing_cluster_id:
        await remove_identity_from_cluster(
            identity_id=identity_id,
            member_repo=member_repo,
            cluster_repo=cluster_repo,
            assignment_writer=assignment_writer,
            tenant_id_for_logging=tenant_id,
            media_id=int(identity_model.media_id),
            session=session,
        )

    identity = media_identity_from_model(identity_model)

    cluster = await assignment_writer.persist_new_cluster(
        tenant_id=tenant_id,
        identities=[identity],
        similarities=[1.0],
        algorithm="manual",
        cluster_id=desired_cluster_id,
    )

    if cluster.id is None:
        raise ValueError("Cluster creation failed")

    updated = await assignment_writer.update_cluster_metadata(
        cluster_id=cluster.id,
        label=label,
        representative_id=identity_id,
    )

    updated.user_confirmed = True
    updated = await cluster_repo.update(updated)

    if suggestion_service and updated.id:
        with contextlib.suppress(Exception):
            await suggestion_service.resolve_for_identity_exclusive(
                identity_id=identity_id,
                accepted_cluster_id=updated.id,
                reason="manual_curation",
            )

    return updated


class CurationActionType(StrEnum):
    FALSE_POSITIVE = "false_positive"
    FALSE_NEGATIVE = "false_negative"


async def assign_outlier_to_cluster(
    *,
    identity_id: str,
    target_cluster_id: str,
    tenant_id: str,
    similarity: float,
    session: AsyncSession | None,
    assignment_writer: AssignmentWriter,
    suggestion_service: SuggestionServiceProtocol | None = None,
    clustering_logger: ClusteringLogger | None = None,
) -> IdentityCluster | None:
    """Manually assign an unclustered identity to an existing cluster."""
    cluster_repo: ClusterRepository = assignment_writer.cluster_repository
    member_repo: MemberRepository = assignment_writer.member_repository

    cluster = await cluster_repo.get_by_id(target_cluster_id)
    if not cluster or cluster.tenant_id != tenant_id:
        return None
    try:
        cluster_tenant_uuid = uuid.UUID(str(cluster.tenant_id))
    except ValueError:
        return None

    if session is None:
        return None

    try:
        identity_uuid = uuid.UUID(str(identity_id))
    except ValueError:
        return None

    identity_model = await session.get(MediaIdentityModel, identity_uuid)
    if not identity_model or identity_model.tenant_id != cluster_tenant_uuid:
        return None

    source_cluster_id = await get_identity_cluster_id(member_repo=member_repo, identity_id=str(identity_model.id))
    is_false_positive = source_cluster_id is not None

    if source_cluster_id:
        if source_cluster_id == target_cluster_id:
            return cluster

        await remove_identity_from_cluster(
            identity_id=str(identity_model.id),
            member_repo=member_repo,
            cluster_repo=cluster_repo,
            assignment_writer=assignment_writer,
            recompute=True,
            tenant_id_for_logging=tenant_id,
            media_id=int(identity_model.media_id),
            clustering_logger=clustering_logger,
            session=session,
        )

    added = await member_repo.add_member_if_not_exists(
        target_cluster_id, identity_id=str(identity_model.id), similarity=similarity
    )
    if added is None:
        logger.info(
            "[curation] Identity already in target cluster identity=%s cluster=%s",
            identity_model.id,
            target_cluster_id,
        )
        return cluster

    cluster.identity_count += 1
    cluster = await cluster_repo.update(cluster)

    action_type = CurationActionType.FALSE_POSITIVE if is_false_positive else CurationActionType.FALSE_NEGATIVE

    logger.info(
        "[curation] ASSIGNED identity=%s media_id=%s target_cluster=%s similarity=%.4f tenant_id=%s "
        "user_action=manual_assign action_type=%s source_cluster=%s",
        identity_model.id,
        identity_model.media_id,
        target_cluster_id,
        similarity,
        tenant_id,
        action_type.value,
        source_cluster_id,
    )

    await assignment_writer.recompute_representatives(target_cluster_id)
    await assignment_writer.recompute_centroid(target_cluster_id)

    with contextlib.suppress(Exception):
        await _adjust_curriculum_t(
            cluster_repo=cluster_repo,
            cluster_id=target_cluster_id,
            delta=_CURRICULUM_FALSE_NEGATIVE_DELTA,
            reason="manual_assign",
        )

    if similarity == 0.0:
        try:
            identity_embedding_arr = np.asarray(identity_model.embedding, dtype=np.float32)
            similarity = await compute_curation_similarity(
                identity_embedding=identity_embedding_arr,
                target_cluster_id=target_cluster_id,
                session=session,
            )
        except Exception as exc:
            logger.warning("Failed to compute curation similarity: %s", exc)

    if suggestion_service:
        with contextlib.suppress(Exception):
            await suggestion_service.resolve_for_identity_exclusive(
                identity_id=identity_id,
                accepted_cluster_id=target_cluster_id,
                reason="manual_assign",
            )
    if clustering_logger:
        clustering_logger.log_curation_action(
            action=CurationEventType.ASSIGN_OUTLIER,
            identity_id=identity_id,
            target_cluster_id=target_cluster_id,
            previous_cluster_id=source_cluster_id,
            similarity=similarity,
        )

    broadcaster = get_event_broadcaster()
    await broadcaster.broadcast(
        "suggestions_updated",
        {"cluster_id": target_cluster_id, "reason": "identity_assigned"},
        tenant_id=tenant_id,
    )

    return cluster
