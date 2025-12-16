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

import numpy as np
from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityMember as MemberModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.observability import ClusteringLogger

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
        member_count=len(unclustered),
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
) -> list[IdentityCluster]:
    """Return clusters for a tenant using the persistence layer."""
    clusters = await cluster_repo.get_by_tenant(tenant_id, limit=limit, offset=offset)
    for cluster in clusters:
        cluster.representatives = getattr(cluster, "representatives", []) or []
    if include_outliers:
        outlier_cluster = await build_outlier_cluster(session, tenant_id)
        if outlier_cluster and outlier_cluster.member_count > 0:
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
        "[curation] RENAMED cluster_id=%s old_label='%s' new_label='%s' tenant_id=%s user_action=manual_rename",
        cluster_id,
        old_label,
        label,
        tenant_id,
    )

    # Recompute representatives/centroid if hooks exist (label changes can affect reps)
    recompute_reps = getattr(assignment_writer, "recompute_representatives", None)
    if callable(recompute_reps):
        await recompute_reps(cluster_id)
    recompute_centroid = getattr(assignment_writer, "recompute_centroid", None)
    if callable(recompute_centroid):
        await recompute_centroid(cluster_id)

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
    tenant_id_for_logging: str | None = None,
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
        if cluster and cluster.member_count > 0:
            cluster.member_count -= 1
            await cluster_repo.update(cluster)

    logger.info(
        "[curation] REMOVED identity=%s from cluster=%s tenant_id=%s user_action=manual_remove",
        identity_id,
        cluster_id,
        tenant_id_for_logging or "unknown",
    )

    return True


async def create_cluster_for_identity(
    *,
    identity_id: str,
    label: str,
    tenant_id: str,
    session: AsyncSession | None,
    assignment_writer: AssignmentWriter,
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
            tenant_id_for_logging=tenant_id,
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

    refresh_view = getattr(assignment_writer, "refresh_centroids_view", None)
    if callable(refresh_view):
        await refresh_view()

    logger.info(
        "[curation] CREATED cluster_id=%s label='%s' identity=%s tenant_id=%s user_action=manual_create",
        updated.id,
        updated.label,
        identity_id,
        tenant_id,
    )

    return updated


async def assign_outlier_to_cluster(
    *,
    identity_id: str,
    target_cluster_id: str,
    tenant_id: str,
    similarity: float,
    session: AsyncSession | None,
    assignment_writer: AssignmentWriter,
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

    existing_members = await member_repo.get_by_cluster(target_cluster_id)
    if any(m.identity_id == str(identity_model.id) for m in existing_members):
        return cluster

    await member_repo.add_member(target_cluster_id, identity_id=str(identity_model.id), similarity=similarity)
    cluster.member_count += 1
    cluster = await cluster_repo.update(cluster)

    logger.info(
        "[curation] ASSIGNED identity=%s target_cluster=%s similarity=%.4f tenant_id=%s user_action=manual_assign",
        identity_model.id,
        target_cluster_id,
        similarity,
        tenant_id,
    )

    recompute_reps = getattr(assignment_writer, "recompute_representatives", None)
    if callable(recompute_reps):
        await recompute_reps(target_cluster_id)
    recompute_centroid = getattr(assignment_writer, "recompute_centroid", None)
    if callable(recompute_centroid):
        await recompute_centroid(target_cluster_id)

    return cluster
