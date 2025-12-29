"""
Cluster curation operations.

This module contains user-driven cluster management operations (CRUD-ish and curation):
- list clusters (optionally with an outlier pseudo-cluster)
- rename / confirm clusters
- create a new labeled cluster for a single identity
- assign/remove identities to/from clusters
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import UTC, datetime
from enum import Enum

import numpy as np
from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusterRepresentative as RepModel
from db.models import IdentityMember as MemberModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.events.broadcaster import get_event_broadcaster
from recognition.application.orchestration.protocols import SuggestionServiceProtocol
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.observability import ClusteringLogger, CurationEventType
from recognition.shared.similarity import compute_face_similarity

logger = logging.getLogger(__name__)


def is_outlier_cluster(cluster: object) -> bool:
    """Return True if the cluster is considered an outlier/noise grouping."""
    label = (getattr(cluster, "label", "") or "").lower()
    algorithm = (getattr(cluster, "clustering_algorithm", "") or "").lower()
    return label in {"outlier", "-1", "noise"} or algorithm in {"outlier", "noise"}


async def build_outlier_cluster(session: AsyncSession | None, tenant_id: str) -> IdentityCluster | None:
    """Construct a pseudo-cluster representing unassigned identities for the tenant."""
    if session is None:
        return None

    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
    except ValueError:
        return None

    stmt: Select[tuple[MediaIdentityModel]] = (
        select(MediaIdentityModel)
        .where(MediaIdentityModel.tenant_id == tenant_uuid)
        .where(~exists(select(MemberModel.id).where(MemberModel.identity_id == MediaIdentityModel.id)))
    )
    result = await session.execute(stmt)
    unclustered = result.scalars().all()
    if not unclustered:
        return None

    return IdentityCluster(
        id=f"outliers-{tenant_id}",
        tenant_id=str(tenant_id),
        label="outliers",
        is_labeled=False,
        identity_count=len(unclustered),
        created_at=datetime.now(tz=UTC),
        clustering_algorithm="outlier",
        user_confirmed=False,
        representatives=[],
    )


async def list_clusters(
    *,
    cluster_repo: ClusterRepository,
    session: AsyncSession | None,
    tenant_id: str,
    limit: int = 100,
    offset: int = 0,
    include_outliers: bool = False,
    labeled_only: bool = False,
    search: str | None = None,
) -> list[IdentityCluster]:
    """Return clusters for a tenant using the persistence layer."""
    clusters = await cluster_repo.get_by_tenant(
        tenant_id, limit=limit, offset=offset, labeled_only=labeled_only, search=search
    )
    for cluster in clusters:
        cluster.representatives = getattr(cluster, "representatives", []) or []
    if include_outliers:
        outlier_cluster = await build_outlier_cluster(session, tenant_id)
        if outlier_cluster and outlier_cluster.identity_count > 0:
            outlier_cluster.representatives = getattr(outlier_cluster, "representatives", []) or []
            clusters.append(outlier_cluster)
        return clusters
    return [c for c in clusters if not is_outlier_cluster(c)]


async def update_cluster(
    *,
    cluster_id: str,
    tenant_id: str,
    label: str | None,
    assignment_writer: AssignmentWriter,
    clustering_logger: ClusteringLogger | None = None,
) -> IdentityCluster | None:
    """Update cluster label and confirmation state."""
    cluster_repo: ClusterRepository = assignment_writer._clusters
    cluster = await cluster_repo.get_by_id(cluster_id)
    # Normalize UUIDs to lowercase for comparison (db stores lowercase)
    if not cluster or cluster.tenant_id.lower() != tenant_id.lower():
        return None

    old_label = cluster.label

    # Idempotency check: skip if label is unchanged
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

    # Log the rename event
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

    # Broadcast metadata update
    broadcaster = get_event_broadcaster()
    await broadcaster.broadcast(
        "cluster_updated",
        {"cluster_id": cluster_id, "reason": "metadata_only_update", "label": label},
        tenant_id=tenant_id,
    )

    return updated


async def get_identity_cluster_id(*, member_repo: MemberRepository, identity_id: str) -> str | None:
    """Get the cluster ID that an identity currently belongs to."""
    members = await member_repo.get_by_identity_id(identity_id)
    if members:
        return members[0].cluster_id
    return None


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
        return True  # Already not in any cluster

    cluster_id = members[0].cluster_id
    removed = await member_repo.remove_by_identity_id(identity_id)

    if removed:
        # Update cluster member count
        cluster = await cluster_repo.get_by_id(cluster_id)
        if cluster and cluster.identity_count > 0:
            cluster.identity_count -= 1
            await cluster_repo.update(cluster)
        # Check for representative refresh (Phase 3)
        # Always check and remove stale rep, but only refresh if recompute is True
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
            recompute_reps = getattr(assignment_writer, "recompute_representatives", None)
            # Only recompute if we didn't already trigger a refresh (or if generic recompute is needed)
            # check_and_refresh_representatives calls refresh_representatives_for_cluster if true.
            if not refreshed and callable(recompute_reps):
                await recompute_reps(cluster_id)

            recompute_centroid = getattr(assignment_writer, "recompute_centroid", None)
            if callable(recompute_centroid):
                await recompute_centroid(cluster_id)

        # Broadcast cluster change
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
    session: AsyncSession | None,
    assignment_writer: AssignmentWriter,
    suggestion_service: SuggestionServiceProtocol | None = None,
) -> IdentityCluster:
    """Create a new user-labeled cluster containing a single identity."""
    if session is None:
        raise RuntimeError("Database session is required for create_cluster_for_identity")

    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
        identity_uuid = uuid.UUID(str(identity_id))
    except ValueError as exc:
        raise ValueError("Invalid tenant_id or identity_id") from exc

    identity_model = await session.get(MediaIdentityModel, identity_uuid)
    if not identity_model or identity_model.tenant_id != tenant_uuid:
        raise ValueError("Identity not found")

    cluster_repo: ClusterRepository = assignment_writer._clusters
    member_repo: MemberRepository = assignment_writer._members

    # If the identity is already assigned, detach it first so the new cluster is consistent.
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

    identity = MediaIdentity(
        id=str(identity_model.id),
        tenant_id=str(identity_model.tenant_id),
        media_id=str(identity_model.media_id),
        embedding=np.asarray(identity_model.embedding, dtype=np.float32),
        confidence=float(identity_model.confidence),
        bbox_width=int(identity_model.bbox_width),
        bbox_height=int(identity_model.bbox_height),
    )

    cluster = await assignment_writer.persist_new_cluster(
        tenant_id=tenant_id,
        identities=[identity],
        similarities=[1.0],
        algorithm="manual",
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

    # [Optimized] We rely on the scheduled background refresh
    # refresh_view = getattr(assignment_writer, "refresh_centroids_view", None)
    # if callable(refresh_view):
    #     await refresh_view()

    # Resolve any pending suggestions for this identity
    if suggestion_service and updated.id:
        with contextlib.suppress(Exception):
            await suggestion_service.resolve_for_identity_exclusive(
                identity_id=identity_id,
                accepted_cluster_id=updated.id,
                reason="manual_curation",
            )

    return updated


class CurationActionType(str, Enum):
    FALSE_POSITIVE = "false_positive"  # Moved FROM auto-assigned cluster
    FALSE_NEGATIVE = "false_negative"  # Assigned FROM singleton/outlier
    NEW_IDENTITY = "new_identity"  # Created new cluster
    BLOCK = "cannot_link"  # Explicit wrong person constraint


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
    cluster_repo: ClusterRepository = assignment_writer._clusters
    member_repo: MemberRepository = assignment_writer._members

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

    # Determine source state for metrics
    source_cluster_id = await get_identity_cluster_id(member_repo=member_repo, identity_id=str(identity_model.id))
    is_false_positive = source_cluster_id is not None

    # If identity is in a DIFFERENT cluster, remove it first
    if source_cluster_id:
        if source_cluster_id == target_cluster_id:
            return cluster  # Already in target

        await remove_identity_from_cluster(
            identity_id=str(identity_model.id),
            member_repo=member_repo,
            cluster_repo=cluster_repo,
            assignment_writer=assignment_writer,
            recompute=True,  # Recompute source cluster's centroids
            tenant_id_for_logging=tenant_id,
            media_id=int(identity_model.media_id),
            clustering_logger=clustering_logger,
            session=session,
        )

    # Use idempotent add to prevent duplicate key errors on retry
    added = await member_repo.add_member_if_not_exists(
        target_cluster_id, identity_id=str(identity_model.id), similarity=similarity
    )
    if added is None:
        # Identity was already in target cluster (shouldn't happen after above check, but be safe)
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

    recompute_reps = getattr(assignment_writer, "recompute_representatives", None)
    if callable(recompute_reps):
        await recompute_reps(target_cluster_id)
    recompute_centroid = getattr(assignment_writer, "recompute_centroid", None)
    if callable(recompute_centroid):
        await recompute_centroid(target_cluster_id)

    # If existing similarity is 0.0 (default), try to compute real similarity against reps
    if similarity == 0.0:
        try:
            # Load identity embedding
            identity_embedding_arr = np.asarray(identity_model.embedding, dtype=np.float32)
            similarity = await compute_curation_similarity(
                identity_embedding=identity_embedding_arr,
                target_cluster_id=target_cluster_id,
                session=session,
            )
        except Exception as exc:
            logger.warning("Failed to compute curation similarity: %s", exc)

    # Resolve any pending suggestions for this identity
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

    # Broadcast suggestion refresh event
    broadcaster = get_event_broadcaster()
    await broadcaster.broadcast(
        "suggestions_updated",
        {"cluster_id": target_cluster_id, "reason": "identity_assigned"},
        tenant_id=tenant_id,
    )

    return cluster


async def compute_curation_similarity(
    *,
    identity_embedding: np.ndarray,
    target_cluster_id: str,
    session: AsyncSession,
) -> float:
    """Compute similarity between an identity and target cluster representatives.

    Used during manual curation to log accurate similarity values instead of 0.0.

    Args:
        identity_embedding: 512-dim embedding vector of the identity
        target_cluster_id: UUID of the cluster to compare against
        session: Database session for loading representatives

    Returns:
        Maximum cosine similarity to any representative in target cluster.
        Returns 0.0 if cluster has no representatives.

    Raises:
        ValueError: If cluster not found
    """
    result = await session.execute(select(RepModel).where(RepModel.cluster_id == uuid.UUID(target_cluster_id)))
    reps = result.scalars().all()

    if not reps:
        return 0.0

    max_sim = 0.0
    for rep in reps:
        # Each rep.embedding is a list or numpy array, convert to standard format
        if rep.embedding is not None:
            rep_embedding = np.asarray(rep.embedding, dtype=np.float32)
            sim = compute_face_similarity(identity_embedding, rep_embedding)
            max_sim = max(max_sim, sim)

    return float(max_sim)


async def check_and_refresh_representatives(
    *,
    cluster_id: str,
    removed_identity_id: str,
    assignment_writer: AssignmentWriter,
    session: AsyncSession,
    refresh: bool = True,
) -> bool:
    """Check if removed identity was a representative and trigger refresh if so.

    Args:
        cluster_id: Cluster the identity was removed from
        removed_identity_id: Identity that was removed
        assignment_writer: Writer for representative operations
        session: Database session
        refresh: Whether to trigger representative refresh (default: True)

    Returns:
        True if representative refresh was triggered, False otherwise.
    """
    # Check if identity was a representative
    result = await session.execute(
        select(RepModel).where(
            RepModel.cluster_id == uuid.UUID(cluster_id),
            RepModel.identity_id == uuid.UUID(removed_identity_id),
        )
    )
    rep = result.scalar_one_or_none()

    if rep is None:
        return False

    # Delete the stale representative
    await session.delete(rep)
    await session.flush()  # Ensure deletion applies before refresh logic reads reps

    logger.info(
        "[curation] REPRESENTATIVE_REMOVED identity=%s cluster=%s triggered_refresh=%s",
        removed_identity_id,
        cluster_id,
        str(refresh).lower(),
    )

    if refresh:
        # Trigger representative refresh for the cluster
        await assignment_writer.refresh_representatives_for_cluster(cluster_id)
        return True

    return False
