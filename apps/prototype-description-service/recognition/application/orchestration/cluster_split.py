"""
Cluster splitting operations.
"""

from __future__ import annotations

import contextlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    identity_ids = [m.identity_id for m in members]
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
        for member in group_members:
            identity_to_label[str(member.id)] = label

    labels = [identity_to_label[str(id.id)] for id in identities]
    ids = [str(id.id) for id in identities]

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
    original_cluster.user_confirmed = True
    await cluster_repo.update(original_cluster)

    new_cluster_ids: list[str] = []
    moved_counts: list[int] = []

    # 4. Create new clusters for each non-largest group
    for label, count in sorted_labels[1:]:  # Skip largest (index 0)
        identity_ids_for_group = [ids[i] for i, lbl in enumerate(labels) if lbl == label]

        new_cluster_id = str(generate_id())
        new_cluster = IdentityCluster(
            id=new_cluster_id,
            tenant_id=original_cluster.tenant_id,
            label=f"Split from {cluster_id[:8]}",
            member_count=count,
            is_labeled=False,
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
            "Split cluster %s: Created new cluster %s with %d identities",
            cluster_id,
            new_cluster_id,
            count,
        )

    # 5. Update original cluster count
    remaining_count = label_counts[largest_label]
    original_cluster.member_count = remaining_count
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
        "[curation] SPLIT original_cluster=%s new_clusters=%s moved_counts=%s tenant_id=%s user_action=manual_split",
        cluster_id,
        new_cluster_ids,
        moved_counts,
        original_cluster.tenant_id,
    )

    return new_cluster_ids, moved_counts

