"""
Cluster splitting operations.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from dataclasses import dataclass
from enum import Enum

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster as IdentityClusterModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.events.broadcaster import get_event_broadcaster
from recognition.application.orchestration.protocols import SuggestionServiceProtocol
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.suggestions.service import SuggestionRefreshReason
from recognition.config import get_settings as get_recognition_settings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import (
    ClusterRepository,
    IdentityClusterBlockRepository,
    MemberRepository,
)
from recognition.observability import ClusteringLogger, DecisionType
from recognition.shared.ids import generate_id
from recognition.shared.similarity import compute_face_similarity

logger = logging.getLogger(__name__)


class SplitStrategy(str, Enum):
    """Strategy used to split a cluster."""

    HIERARCHICAL = "hierarchical"
    ANCHOR_FORCED = "anchor_forced"


class SplitScope(str, Enum):
    """Scope hint for split operations."""

    CLUSTER = "cluster"
    MEDIA = "media"
    ANCHOR = "anchor"


@dataclass(frozen=True)
class SplitPlan:
    """Plan describing how a user-initiated split should be executed.

    Attributes:
        cluster_id: Cluster UUID to split.
        n_clusters: Desired number of clusters (0 = auto-detect, 2+ = fixed).
        anchor_identity_id: Identity UUID that should retain the original label.
        strategy: Split strategy to apply.
        split_mode: Optional mode hint (ex: "anchor", "media").
    """

    cluster_id: str
    n_clusters: int
    anchor_identity_id: str | None
    strategy: SplitStrategy
    split_mode: str | None = None


async def split_cluster(
    *,
    cluster_id: str,
    n_clusters: int,
    anchor_identity_id: str | None = None,
    split_mode: str | None = None,
    session: AsyncSession | None,
    cluster_repo: ClusterRepository,
    member_repo: MemberRepository,
    block_repo: IdentityClusterBlockRepository | None = None,
    suggestion_service: SuggestionServiceProtocol | None = None,
    assignment_writer: AssignmentWriter | None = None,
    recompute: bool = True,
    clustering_logger: ClusteringLogger | None = None,
) -> tuple[list[str], list[int]]:
    """Split a mixed cluster using hierarchical clustering."""
    from recognition.application.clustering.hierarchical_clustering import HierarchicalClustering

    if session is None:
        raise RuntimeError("No session available for split_cluster")

    # 1. Fetch all identities in the cluster
    members = await member_repo.get_by_cluster(cluster_id)
    if not members or len(members) < 2:
        logger.info(
            "Split cluster %s: only %d identities, need at least 2 to split",
            cluster_id,
            len(members) if members else 0,
        )
        return [], []

    # Load identity embeddings
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

    # 2. Use HierarchicalClustering to split identities
    hierarchical = HierarchicalClustering(distance_threshold=0.30)
    clusters_by_label = hierarchical.split_identities(identities, n_clusters)

    # Check if we found multiple groups
    if anchor_key and n_clusters >= 2 and len(clusters_by_label) <= 1:
        clusters_by_label = _force_anchor_split(
            identities,
            anchor_key,
            similarity_floor=get_recognition_settings().clustering.anchor_split_similarity_floor,
        )
        logger.info(
            "Split cluster %s: forced anchor split for anchor=%s",
            cluster_id,
            anchor_key,
        )

    if len(clusters_by_label) <= 1:
        logger.info("Split cluster %s: All faces similar enough to stay together, nothing to split", cluster_id)
        return [], []

    # Build label array for compatibility with existing code
    identity_to_label: dict[str, int] = {}
    for label, group_members in clusters_by_label.items():
        for identity in group_members:
            identity_to_label[str(identity.id)] = label

    labels = [identity_to_label[str(id.id)] for id in identities]
    ids = [str(id.id) for id in identities]
    identity_media_map = {str(identity.id).lower(): identity.media_id for identity in identities}

    logger.info("Split cluster %s: Hierarchical clustering labels=%s", cluster_id, labels)

    # 3. Count members per group
    label_counts: dict[int, int] = {}
    for label in labels:
        label_counts[label] = label_counts.get(label, 0) + 1

    # Sort by count descending, keep largest in original cluster
    sorted_labels = sorted(label_counts.items(), key=lambda x: x[1], reverse=True)
    largest_label = sorted_labels[0][0]

    # Get the original cluster for updates
    original_cluster = await cluster_repo.get_by_id(cluster_id)
    if not original_cluster:
        logger.error("Split cluster %s: Original cluster not found", cluster_id)
        return [], []

    # Mark original as user-confirmed
    was_user_confirmed = original_cluster.user_confirmed
    original_cluster.user_confirmed = True

    user_label = None
    if original_cluster.label and (was_user_confirmed or not original_cluster.label.startswith("cluster-")):
        user_label = original_cluster.label

    # Keep user labels on the group that best matches the original cluster.
    # Keep user labels on the group that best matches the original cluster.
    label_owner = _determine_label_owner(
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

    new_cluster_ids: list[str] = []
    moved_counts: list[int] = []
    split_details: list[dict[str, object]] = []
    remaining_identity_ids = [ids[i] for i, lbl in enumerate(labels) if lbl == largest_label]
    moved_identity_ids_all: list[str] = []

    # 4. Create new clusters for each non-largest group
    for label, count in sorted_labels[1:]:  # Skip largest (index 0)
        identity_ids_for_group = [ids[i] for i, lbl in enumerate(labels) if lbl == label]
        moved_media_ids: list[int] = []
        for identity_id in identity_ids_for_group:
            media_id = identity_media_map.get(identity_id.lower())
            if media_id is not None:
                moved_media_ids.append(int(media_id))

        new_cluster_id = str(generate_id())
        assigned_label = label_assignments.get(label)
        # Use unique suffix to avoid label collision on repeated splits
        unique_suffix = new_cluster_id[:4]
        fallback_label = f"Split from {cluster_id[:8]} ({unique_suffix})"
        next_label = assigned_label or fallback_label
        new_cluster = IdentityCluster(
            id=new_cluster_id,
            tenant_id=original_cluster.tenant_id,
            label=next_label,
            identity_count=count,
            is_labeled=bool(next_label),
            user_confirmed=True,
        )
        await cluster_repo.save(new_cluster)

        # Move members
        for identity_id in identity_ids_for_group:
            await member_repo.remove_by_identity_id(identity_id)
            await member_repo.add_member(new_cluster_id, identity_id=identity_id, similarity=1.0)
            if block_repo is not None:
                await block_repo.add_block(
                    tenant_id=original_cluster.tenant_id,
                    identity_id=identity_id,
                    blocked_cluster_id=cluster_id,
                    reason="manual_split",
                )
            moved_identity_ids_all.append(identity_id)
        if block_repo is not None and remaining_identity_ids:
            for identity_id in remaining_identity_ids:
                await block_repo.add_block(
                    tenant_id=original_cluster.tenant_id,
                    identity_id=identity_id,
                    blocked_cluster_id=new_cluster_id,
                    reason="manual_split",
                )

        new_cluster_ids.append(new_cluster_id)
        moved_counts.append(count)

        logger.info(
            "Split cluster %s (%s): Created new cluster %s (%s) with %d identities "
            "moved_identity_ids=%s moved_media_ids=%s",
            cluster_id,
            original_cluster.label,
            new_cluster_id,
            next_label,
            count,
            identity_ids_for_group,
            moved_media_ids,
        )
        split_details.append(
            {
                "cluster_id": new_cluster_id,
                "label": next_label,
                "moved_identity_ids": identity_ids_for_group,
                "moved_media_ids": moved_media_ids,
            }
        )

    # 5. Update original cluster count
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
        recompute_reps = getattr(assignment_writer, "recompute_representatives", None)
        if callable(recompute_reps):
            for affected_id in affected_cluster_ids:
                await recompute_reps(affected_id)
        recompute_centroid = getattr(assignment_writer, "recompute_centroid", None)
        if callable(recompute_centroid):
            for affected_id in affected_cluster_ids:
                await recompute_centroid(affected_id)
        refresh_view = getattr(assignment_writer, "refresh_centroids_view", None)
        if callable(refresh_view):
            await refresh_view()

    if suggestion_service and (moved_identity_ids_all or anchor_key):
        impacted_ids = {*(moved_identity_ids_all), *(remaining_identity_ids if anchor_key else [])}
        if anchor_key:
            impacted_ids.add(anchor_key)
        for identity_id in impacted_ids:
            with contextlib.suppress(Exception):
                await suggestion_service.refresh_for_identity(
                    identity_id=identity_id,
                    reason=SuggestionRefreshReason.MANUAL_SPLIT,
                )

    # Log the split event
    if clustering_logger and new_cluster_ids:
        with contextlib.suppress(Exception):
            clustering_logger.log_cluster_split(
                original_cluster_id=cluster_id,
                new_cluster_ids=new_cluster_ids,
                moved_counts=moved_counts,
                tenant_id=original_cluster.tenant_id,
            )

    # Log split as FALSE_POSITIVE for moved identities (curation metrics)
    if clustering_logger:
        for identity_id in moved_identity_ids_all:
            with contextlib.suppress(Exception):
                clustering_logger.log_decision(
                    identity_id=identity_id,
                    cluster_id=cluster_id,  # From original cluster
                    decision=DecisionType.REJECT,
                    reason="false_positive_split",
                    metadata={
                        "action": "split",
                        "tenant_id": original_cluster.tenant_id,
                    },
                )

    # Broadcast split event
    broadcaster = get_event_broadcaster()
    await broadcaster.broadcast(
        "cluster_split",
        {
            "original_cluster_id": cluster_id,
            "new_cluster_ids": new_cluster_ids,
            "moved_counts": moved_counts,
        },
        tenant_id=original_cluster.tenant_id,
    )

    return new_cluster_ids, moved_counts


def _force_anchor_split(
    identities: list[MediaIdentityModel],
    anchor_identity_id: str,
    *,
    similarity_floor: float | None = None,
) -> dict[int, list[MediaIdentityModel]]:
    """Force a two-way split around an anchor identity."""
    if similarity_floor is None:
        similarity_floor = get_recognition_settings().clustering.anchor_split_similarity_floor

    anchor = None
    remaining: list[MediaIdentityModel] = []
    for identity in identities:
        if str(identity.id).lower() == anchor_identity_id:
            anchor = identity
        else:
            remaining.append(identity)
    if anchor is None or not remaining:
        return {0: identities}

    anchor_vec = np.asarray(anchor.embedding, dtype=np.float32)
    anchor_group: list[MediaIdentityModel] = [anchor]
    other_group: list[MediaIdentityModel] = []
    similarity_by_identity: list[tuple[MediaIdentityModel, float]] = []

    for identity in remaining:
        identity_vec = np.asarray(identity.embedding, dtype=np.float32)
        similarity = compute_face_similarity(anchor_vec, identity_vec)
        similarity_by_identity.append((identity, similarity))
        if similarity >= similarity_floor:
            anchor_group.append(identity)
        else:
            other_group.append(identity)

    if not other_group:
        farthest_identity, _similarity = min(similarity_by_identity, key=lambda item: item[1])
        anchor_group = [member for member in anchor_group if member is not farthest_identity]
        other_group = [farthest_identity]

    if not other_group:
        return {0: identities}

    return {0: anchor_group, 1: other_group}


def _determine_label_owner(
    *,
    user_label: str | None,
    original_cluster: IdentityCluster,
    anchor_key: str | None,
    identity_to_label: dict[str, int],
    largest_label: int,
    clusters_by_label: dict[int, list[MediaIdentityModel]],
    original_identities: list[MediaIdentityModel],
) -> int | None:
    """Determine which cluster group should inherit the original label."""
    if not user_label:
        return None

    # 1. Anchor override
    if anchor_key:
        anchor_label = identity_to_label.get(anchor_key)
        if anchor_label is not None:
            return anchor_label

    # 2. Representative match
    if original_cluster.representative_identity_id:
        rep_id = original_cluster.representative_identity_id.lower()
        rep_label = identity_to_label.get(rep_id)
        if rep_label is not None:
            return rep_label

    # 3. Centroid similarity match
    reference_vec = original_cluster.centroid
    if reference_vec is None:
        reference_vec = np.mean(np.asarray([id.embedding for id in original_identities], dtype=np.float32), axis=0)
    else:
        reference_vec = np.asarray(reference_vec, dtype=np.float32)

    reference_norm = float(np.linalg.norm(reference_vec))
    if reference_norm > 0:
        reference_vec = reference_vec / reference_norm

    best_label = None
    best_similarity = -1.0

    for label, group_members in clusters_by_label.items():
        if not group_members:
            continue
        group_vec = np.mean(np.asarray([m.embedding for m in group_members], dtype=np.float32), axis=0)
        group_norm = float(np.linalg.norm(group_vec))
        if group_norm > 0:
            group_vec = group_vec / group_norm

        similarity = float(np.dot(group_vec, reference_vec))
        if similarity > best_similarity:
            best_similarity = similarity
            best_label = label

    if best_label is not None:
        return best_label

    # 4. Fallback to largest group
    return largest_label
