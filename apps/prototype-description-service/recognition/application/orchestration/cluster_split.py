"""
Cluster splitting operations.
"""

from __future__ import annotations

import contextlib
import logging
import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster as IdentityClusterModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.observability import ClusteringLogger
from recognition.shared.ids import generate_id

logger = logging.getLogger(__name__)


async def split_cluster(
    *,
    cluster_id: str,
    n_clusters: int,
    session: AsyncSession | None,
    cluster_repo: ClusterRepository,
    member_repo: MemberRepository,
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

    # 2. Use HierarchicalClustering to split identities
    hierarchical = HierarchicalClustering(distance_threshold=0.30)
    clusters_by_label = hierarchical.split_identities(identities, n_clusters)

    # Check if we found multiple groups
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
    label_owner = None
    if user_label and original_cluster.representative_identity_id:
        rep_id = original_cluster.representative_identity_id.lower()
        label_owner = identity_to_label.get(rep_id)

    if user_label and label_owner is None:
        reference_vec = original_cluster.centroid
        if reference_vec is None:
            reference_vec = np.mean(np.asarray([id.embedding for id in identities], dtype=np.float32), axis=0)
        else:
            reference_vec = np.asarray(reference_vec, dtype=np.float32)
        reference_norm = float(np.linalg.norm(reference_vec))
        if reference_norm > 0:
            reference_vec = reference_vec / reference_norm

        best_label = None
        best_similarity = -1.0
        for label, group_members in clusters_by_label.items():
            group_vec = np.mean(np.asarray([m.embedding for m in group_members], dtype=np.float32), axis=0)
            group_norm = float(np.linalg.norm(group_vec))
            if group_norm > 0:
                group_vec = group_vec / group_norm
            similarity = float(np.dot(group_vec, reference_vec))
            if similarity > best_similarity:
                best_similarity = similarity
                best_label = label
        label_owner = best_label

    if user_label and label_owner is None:
        label_owner = largest_label

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

    # Log the split event
    if clustering_logger and new_cluster_ids:
        with contextlib.suppress(Exception):
            clustering_logger.log_cluster_split(
                original_cluster_id=cluster_id,
                new_cluster_ids=new_cluster_ids,
                moved_counts=moved_counts,
                tenant_id=original_cluster.tenant_id,
            )

    logger.info(
        "[curation] SPLIT original_cluster=%s original_label='%s' new_clusters=%s moved_counts=%s "
        "moved_details=%s tenant_id=%s user_action=manual_split",
        cluster_id,
        original_cluster.label,
        new_cluster_ids,
        moved_counts,
        split_details,
        original_cluster.tenant_id,
    )

    return new_cluster_ids, moved_counts
