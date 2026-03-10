"""Cluster split orchestration."""

from __future__ import annotations

import contextlib
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster as IdentityClusterModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.events.broadcaster import get_event_broadcaster
from recognition.application.orchestration.protocols import SuggestionRefreshServiceProtocol
from recognition.application.orchestration.split.anchor import determine_label_owner
from recognition.application.orchestration.split.hierarchical import build_clusters_by_label
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import (
    ClusterRepository,
    IdentityClusterBlockRepository,
    MemberRepository,
)
from recognition.domain.suggestion import SuggestionRefreshReason
from recognition.observability import ClusteringLogger, DecisionType
from recognition.shared.ids import generate_id

logger = logging.getLogger(__name__)


@dataclass
class SplitGroup:
    label: int
    identity_ids: list[str]
    count: int
    moved_media_ids: list[int]
    new_cluster_id: str | None = None
    new_cluster_label: str | None = None


async def _create_split_clusters(
    *,
    original_cluster: IdentityCluster,
    split_groups: list[SplitGroup],
    label_assignments: dict[int, str],
    cluster_repo: ClusterRepository,
    original_cluster_id: str,
    desired_cluster_ids: list[str] | None = None,
) -> list[str]:
    """Create new clusters for each split group. Returns new cluster IDs."""
    new_cluster_ids: list[str] = []

    normalized_desired_cluster_ids = desired_cluster_ids or []

    for index, group in enumerate(split_groups):
        new_cluster_id = (
            normalized_desired_cluster_ids[index] if index < len(normalized_desired_cluster_ids) else str(generate_id())
        )
        assigned_label = label_assignments.get(group.label)
        unique_suffix = new_cluster_id[:4]
        fallback_label = f"Split from {original_cluster_id[:8]} ({unique_suffix})"
        next_label = assigned_label or fallback_label
        new_cluster = IdentityCluster(
            id=new_cluster_id,
            tenant_id=original_cluster.tenant_id,
            label=next_label,
            identity_count=group.count,
            is_labeled=bool(next_label),
            user_confirmed=True,
        )
        await cluster_repo.save(new_cluster)
        group.new_cluster_id = new_cluster_id
        group.new_cluster_label = next_label
        new_cluster_ids.append(new_cluster_id)

    return new_cluster_ids


async def _reassign_members(
    *,
    split_groups: list[SplitGroup],
    new_cluster_ids: list[str],
    member_repo: MemberRepository,
    block_repo: IdentityClusterBlockRepository | None,
    remaining_identity_ids: list[str],
    tenant_id: str,
    original_cluster_id: str,
) -> None:
    """Move members from original cluster to new clusters."""
    for group, new_cluster_id in zip(split_groups, new_cluster_ids, strict=False):
        for identity_id in group.identity_ids:
            await member_repo.remove_by_identity_id(identity_id)
            await member_repo.add_member(new_cluster_id, identity_id=identity_id, similarity=1.0)
            if block_repo is not None:
                await block_repo.add_block(
                    tenant_id=tenant_id,
                    identity_id=identity_id,
                    blocked_cluster_id=original_cluster_id,
                    reason="manual_split",
                )

        if block_repo is not None and remaining_identity_ids:
            for identity_id in remaining_identity_ids:
                await block_repo.add_block(
                    tenant_id=tenant_id,
                    identity_id=identity_id,
                    blocked_cluster_id=new_cluster_id,
                    reason="manual_split",
                )


async def _emit_split_events(
    *,
    original_cluster_id: str,
    new_cluster_ids: list[str],
    moved_counts: list[int],
    tenant_id: str,
    clustering_logger: ClusteringLogger | None,
) -> None:
    """Emit cluster_split events."""
    if clustering_logger and new_cluster_ids:
        with contextlib.suppress(Exception):
            clustering_logger.log_cluster_split(
                original_cluster_id=original_cluster_id,
                new_cluster_ids=new_cluster_ids,
                moved_counts=moved_counts,
                tenant_id=tenant_id,
            )

    broadcaster = get_event_broadcaster()
    await broadcaster.broadcast(
        "cluster_split",
        {
            "original_cluster_id": original_cluster_id,
            "new_cluster_ids": new_cluster_ids,
            "moved_counts": moved_counts,
        },
        tenant_id=tenant_id,
    )


async def split_cluster(
    *,
    cluster_id: str,
    n_clusters: int,
    anchor_identity_id: str | None = None,
    split_mode: str | None = None,
    desired_cluster_ids: list[str] | None = None,
    session: AsyncSession | None,
    cluster_repo: ClusterRepository,
    member_repo: MemberRepository,
    block_repo: IdentityClusterBlockRepository | None = None,
    suggestion_refresh_service: SuggestionRefreshServiceProtocol | None = None,
    assignment_writer: AssignmentWriter | None = None,
    recompute: bool = True,
    clustering_logger: ClusteringLogger | None = None,
) -> tuple[list[str], list[int]]:
    """Split a mixed cluster using hierarchical clustering."""
    if session is None:
        raise RuntimeError("No session available for split_cluster")

    members = await member_repo.get_by_cluster(cluster_id)
    if not members or len(members) < 2:
        logger.info(
            "Split cluster %s: only %d identities, need at least 2 to split",
            cluster_id,
            len(members) if members else 0,
        )
        return [], []

    identity_ids: list[uuid.UUID] = []
    for member in members:
        try:
            identity_ids.append(uuid.UUID(str(member.identity_id)))
        except ValueError:
            continue
    if len(identity_ids) < 2:
        return [], []

    stmt = select(MediaIdentityModel).where(MediaIdentityModel.id.in_(identity_ids))
    result = await session.execute(stmt)
    identities = list(result.scalars().all())

    if len(identities) < 2:
        return [], []

    identity_lookup = {str(identity.id).lower(): identity for identity in identities}
    anchor_key = None
    if anchor_identity_id:
        anchor_key = anchor_identity_id.lower()
        if anchor_key not in identity_lookup and identity_lookup:
            anchor_key = next(iter(identity_lookup.keys()))
            logger.info(
                "Split cluster %s: anchor identity not found, falling back to %s",
                cluster_id,
                anchor_key,
            )
    if split_mode:
        logger.info("Split cluster %s: split_mode=%s", cluster_id, split_mode)

    clusters_by_label = build_clusters_by_label(
        identities,
        n_clusters=n_clusters,
        anchor_key=anchor_key,
        cluster_id=cluster_id,
    )

    if len(clusters_by_label) <= 1:
        logger.info("Split cluster %s: All faces similar enough to stay together, nothing to split", cluster_id)
        return [], []

    identity_to_label: dict[str, int] = {}
    for label, group_members in clusters_by_label.items():
        for identity in group_members:
            identity_to_label[str(identity.id)] = label

    labels = [identity_to_label[str(identity.id)] for identity in identities]
    ids = [str(identity.id) for identity in identities]
    identity_media_map = {str(identity.id).lower(): identity.media_id for identity in identities}

    logger.info("Split cluster %s: Hierarchical clustering labels=%s", cluster_id, labels)

    label_counts: dict[int, int] = {}
    for label in labels:
        label_counts[label] = label_counts.get(label, 0) + 1

    sorted_labels = sorted(label_counts.items(), key=lambda x: x[1], reverse=True)
    largest_label = sorted_labels[0][0]

    original_cluster = await cluster_repo.get_by_id(cluster_id)
    if not original_cluster:
        logger.error("Split cluster %s: Original cluster not found", cluster_id)
        return [], []

    was_user_confirmed = original_cluster.user_confirmed
    original_cluster.user_confirmed = True

    user_label = None
    if original_cluster.label and (was_user_confirmed or not original_cluster.label.startswith("cluster-")):
        user_label = original_cluster.label

    label_owner = determine_label_owner(
        user_label=user_label,
        original_cluster=original_cluster,
        anchor_key=anchor_key,
        identity_to_label=identity_to_label,
        largest_label=largest_label,
        clusters_by_label=clusters_by_label,
        original_identities=identities,
    )

    if anchor_key and label_owner is not None and label_owner in label_counts:
        if label_owner != largest_label:
            sorted_labels = [
                (label_owner, label_counts[label_owner]),
                *[item for item in sorted_labels if item[0] != label_owner],
            ]
        largest_label = label_owner

    label_assignments: dict[int, str] = {}
    if user_label:
        tenant_uuid = uuid.UUID(original_cluster.tenant_id)
        label_rows = await session.execute(
            select(IdentityClusterModel.label).where(IdentityClusterModel.tenant_id == tenant_uuid)
        )
        existing_labels = {row[0] for row in label_rows if row[0]}
        taken_labels = set(existing_labels)
        split_index = 1
        for label, _count in sorted_labels:
            if label == label_owner:
                label_assignments[label] = user_label
                continue
            while True:
                candidate = f"{user_label} (split {split_index})"
                split_index += 1
                if candidate not in taken_labels:
                    label_assignments[label] = candidate
                    taken_labels.add(candidate)
                    break

        if label_owner != largest_label:
            original_cluster.label = label_assignments.get(largest_label, original_cluster.label)
            original_cluster.is_labeled = bool(original_cluster.label)
            await cluster_repo.update(original_cluster)

    remaining_identity_ids = [ids[i] for i, lbl in enumerate(labels) if lbl == largest_label]
    split_groups: list[SplitGroup] = []
    for label, count in sorted_labels[1:]:
        identity_ids_for_group = [ids[i] for i, lbl in enumerate(labels) if lbl == label]
        moved_media_ids: list[int] = []
        for identity_id in identity_ids_for_group:
            media_id = identity_media_map.get(identity_id.lower())
            if media_id is not None:
                moved_media_ids.append(int(media_id))

        split_groups.append(
            SplitGroup(
                label=label,
                identity_ids=identity_ids_for_group,
                count=count,
                moved_media_ids=moved_media_ids,
            )
        )

    new_cluster_ids = await _create_split_clusters(
        original_cluster=original_cluster,
        split_groups=split_groups,
        label_assignments=label_assignments,
        cluster_repo=cluster_repo,
        original_cluster_id=cluster_id,
        desired_cluster_ids=desired_cluster_ids,
    )
    moved_counts = [group.count for group in split_groups]
    moved_identity_ids_all = [identity_id for group in split_groups for identity_id in group.identity_ids]

    await _reassign_members(
        split_groups=split_groups,
        new_cluster_ids=new_cluster_ids,
        member_repo=member_repo,
        block_repo=block_repo,
        remaining_identity_ids=remaining_identity_ids,
        tenant_id=original_cluster.tenant_id,
        original_cluster_id=cluster_id,
    )

    for group in split_groups:
        if group.new_cluster_id is None or group.new_cluster_label is None:
            continue
        logger.info(
            "Split cluster %s (%s): Created new cluster %s (%s) with %d identities "
            "moved_identity_ids=%s moved_media_ids=%s",
            cluster_id,
            original_cluster.label,
            group.new_cluster_id,
            group.new_cluster_label,
            group.count,
            group.identity_ids,
            group.moved_media_ids,
        )

    remaining_count = label_counts[largest_label]
    original_cluster.identity_count = remaining_count
    if label_assignments:
        original_cluster.label = label_assignments.get(largest_label, original_cluster.label)
        original_cluster.is_labeled = bool(original_cluster.label)
    await cluster_repo.update(original_cluster)

    total_moved = sum(moved_counts)
    logger.info(
        "Split cluster %s complete: created %d new clusters, moved %d identities, %d remain",
        cluster_id,
        len(new_cluster_ids),
        total_moved,
        remaining_count,
    )

    if assignment_writer and new_cluster_ids and recompute:
        affected_cluster_ids = [cluster_id, *new_cluster_ids]
        for affected_id in affected_cluster_ids:
            await assignment_writer.recompute_representatives(affected_id)
        for affected_id in affected_cluster_ids:
            await assignment_writer.recompute_centroid(affected_id)
        await assignment_writer.refresh_centroids_view()

    if suggestion_refresh_service and (moved_identity_ids_all or anchor_key):
        impacted_ids = {*(moved_identity_ids_all), *(remaining_identity_ids if anchor_key else [])}
        if anchor_key:
            impacted_ids.add(anchor_key)
        for identity_id in impacted_ids:
            with contextlib.suppress(Exception):
                await suggestion_refresh_service.refresh_for_identity(
                    identity_id=identity_id,
                    reason=SuggestionRefreshReason.MANUAL_SPLIT,
                )

    if clustering_logger:
        for identity_id in moved_identity_ids_all:
            with contextlib.suppress(Exception):
                clustering_logger.log_decision(
                    identity_id=identity_id,
                    cluster_id=cluster_id,
                    decision=DecisionType.REJECT,
                    reason="false_positive_split",
                    metadata={
                        "action": "split",
                        "tenant_id": original_cluster.tenant_id,
                    },
                )

    await _emit_split_events(
        original_cluster_id=cluster_id,
        new_cluster_ids=new_cluster_ids,
        moved_counts=moved_counts,
        tenant_id=original_cluster.tenant_id,
        clustering_logger=clustering_logger,
    )

    return new_cluster_ids, moved_counts
