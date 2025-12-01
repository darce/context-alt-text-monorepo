"""Cluster management helpers (merge, rename, split, revert)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityClusterRepresentative, IdentityMember, MediaIdentity

logger = logging.getLogger(__name__)

RefreshFn = Callable[[], Awaitable[None]]
EnsureContextFn = Callable[[], Awaitable[None]]


class CentroidEntry(Protocol):
    cluster: IdentityCluster
    centroid: np.ndarray
    member_count: int


def combine_centroids(target: CentroidEntry, source: CentroidEntry) -> np.ndarray:
    total_members = target.member_count + source.member_count
    if total_members == 0:
        return target.centroid

    combined = (target.centroid * float(target.member_count) + source.centroid * float(source.member_count)) / float(
        total_members
    )

    norm = float(np.linalg.norm(combined))
    if norm == 0:
        return combined
    return combined / norm


class ClusterMerger:
    """Merge helpers extracted from the clustering service."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        refresh_view: RefreshFn,
        ensure_context: EnsureContextFn,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self._refresh_view = refresh_view
        self._ensure_context = ensure_context

    async def merge_similar(
        self,
        clusters: Sequence[CentroidEntry],
        threshold: float,
        max_iterations: int,
    ) -> int:
        merges_performed = 0
        iterations = 0
        entries = list(clusters)  # Convert to mutable list for in-place modification

        while iterations < max_iterations and len(entries) > 1:
            merged_this_round = False
            i = 0
            while i < len(entries):
                target_entry = entries[i]
                j = i + 1
                while j < len(entries):
                    source_entry = entries[j]
                    similarity = float(np.dot(target_entry.centroid, source_entry.centroid))
                    if similarity >= threshold:
                        moved = await self._merge_cluster_objects(
                            source_entry.cluster,
                            target_entry.cluster,
                        )
                        if moved:
                            merges_performed += 1
                            merged_this_round = True

                            total_members = target_entry.member_count + source_entry.member_count
                            if total_members > 0:
                                target_entry.centroid = combine_centroids(target_entry, source_entry)
                            target_entry.member_count = total_members
                            entries.pop(j)
                            continue
                    j += 1
                i += 1

            if not merged_this_round:
                break
            iterations += 1

        if merges_performed:
            await self.session.commit()
            await self._ensure_context()
            await self._refresh_view()
        else:
            await self.session.flush()

        return merges_performed

    async def _merge_cluster_objects(self, source: IdentityCluster, target: IdentityCluster) -> int:
        members_result = await self.session.execute(
            select(IdentityMember).where(IdentityMember.cluster_id == source.id)
        )
        members = members_result.scalars().all()
        moved = 0
        for member in members:
            member.cluster_id = target.id
            moved += 1

        target.identity_count += source.identity_count
        target.updated_at = datetime.utcnow()

        await self.session.delete(source)
        return moved


async def build_cluster_summary(session: AsyncSession, cluster: IdentityCluster) -> dict[str, object]:
    stmt = (
        select(IdentityMember, MediaIdentity)
        .join(MediaIdentity, IdentityMember.identity_id == MediaIdentity.id)
        .where(IdentityMember.cluster_id == cluster.id)
        .order_by(IdentityMember.similarity.desc())
        .limit(10)
    )

    result = await session.execute(stmt)
    sample_rows = result.all()

    member_rows = await session.execute(
        select(IdentityMember.identity_id).where(IdentityMember.cluster_id == cluster.id)
    )
    member_ids = [str(row[0]) for row in member_rows]

    return {
        "id": str(cluster.id),
        "label": cluster.label,
        "is_auto_label": bool(cluster.label and cluster.label.startswith("cluster-")),
        "identity_count": cluster.identity_count,
        "member_ids": member_ids,
        "representative_identity": {
            "media_id": cluster.representative_identity.media_id if cluster.representative_identity else None,
            "thumbnail_url": cluster.representative_identity.thumbnail_url if cluster.representative_identity else None,
            "bbox": {
                "x": cluster.representative_identity.bbox_x if cluster.representative_identity else 0,
                "y": cluster.representative_identity.bbox_y if cluster.representative_identity else 0,
                "width": cluster.representative_identity.bbox_width if cluster.representative_identity else 0,
                "height": cluster.representative_identity.bbox_height if cluster.representative_identity else 0,
            },
        },
        "sample_identities": [
            {
                "id": str(identity.id),
                "media_id": identity.media_id,
                "similarity": member.similarity,
                "thumbnail_url": identity.thumbnail_url,
                "bbox": {
                    "x": identity.bbox_x,
                    "y": identity.bbox_y,
                    "width": identity.bbox_width,
                    "height": identity.bbox_height,
                },
                "confidence": identity.confidence,
            }
            for member, identity in sample_rows
        ],
    }


class ClusterNotFoundError(Exception):
    """Raised when a cluster cannot be found for the current tenant."""


class ClusterLabelConflictError(Exception):
    """Raised when attempting to reuse an existing cluster label."""


class ClusterOperations:
    """High-level cluster operations (rename, merge into label, revert, split)."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        threshold: float,
        refresh_view: RefreshFn,
        ensure_context: EnsureContextFn,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.threshold = threshold
        self._refresh_view = refresh_view
        self._ensure_context = ensure_context

    async def rename_cluster(self, cluster_id: UUID, new_label: str) -> IdentityCluster:
        """Rename a cluster, ensuring the new label is unique for the tenant.

        Setting a label is a form of user confirmation - the user is explicitly
        identifying this cluster's contents.
        """
        await self._ensure_context()
        cluster = await self.session.get(IdentityCluster, cluster_id)
        if not cluster or cluster.tenant_id != self.tenant_id:
            raise ClusterNotFoundError

        existing_stmt = select(IdentityCluster).where(
            IdentityCluster.tenant_id == self.tenant_id,
            IdentityCluster.label == new_label,
            IdentityCluster.id != cluster_id,
        )
        existing_cluster = await self.session.execute(existing_stmt)
        if existing_cluster.scalar_one_or_none():
            raise ClusterLabelConflictError

        cluster.label = new_label
        cluster.updated_at = datetime.utcnow()
        # Labeling a cluster is a user confirmation
        cluster.user_confirmed = True
        cluster.confirmation_source = "label"
        await self.session.commit()
        await self._ensure_context()
        await self.session.refresh(cluster)
        return cluster

    async def merge_cluster_into_label(
        self,
        source_id: UUID,
        target_label: str,
    ) -> tuple[IdentityCluster, int, list[UUID], str | None]:
        """
        Merge a source cluster into a target cluster by label.

        Creates the target cluster if it doesn't exist.
        Returns (target_cluster, moved_count, moved_identity_ids, source_label).
        """
        await self._ensure_context()
        source = await self.session.get(IdentityCluster, source_id)
        if not source or source.tenant_id != self.tenant_id:
            raise ClusterNotFoundError
        source_label = source.label

        target_stmt = select(IdentityCluster).where(
            IdentityCluster.tenant_id == self.tenant_id,
            IdentityCluster.label == target_label,
        )
        target_result = await self.session.execute(target_stmt)
        target = target_result.scalar_one_or_none()

        if not target:
            target = IdentityCluster(
                tenant_id=self.tenant_id,
                label=target_label,
                representative_identity_id=source.representative_identity_id,
                identity_count=0,
                similarity_threshold=self.threshold,
                clustering_algorithm=source.clustering_algorithm,
                # Creating a cluster with a label is a user confirmation
                user_confirmed=True,
                confirmation_source="merge",
            )
            self.session.add(target)
            await self.session.flush()
        else:
            # Merging into an existing cluster confirms it
            target.user_confirmed = True
            if not target.confirmation_source:
                target.confirmation_source = "merge"

        # Move members from source to target
        members_result = await self.session.execute(
            select(IdentityMember).where(IdentityMember.cluster_id == source.id)
        )
        members = members_result.scalars().all()
        moved_identity_ids: list[UUID] = []
        for member in members:
            member.cluster_id = target.id
            moved_identity_ids.append(member.identity_id)
        moved_count = len(members)

        # Move representatives from source to target
        logger.info(
            "Moving representatives from cluster %s to %s (label: %s)",
            source.id,
            target.id,
            target_label,
        )
        reps_result = await self.session.execute(
            select(IdentityClusterRepresentative).where(IdentityClusterRepresentative.cluster_id == source.id)
        )
        reps = reps_result.scalars().all()
        for rep in reps:
            rep.cluster_id = target.id
        logger.info("Moved %d representatives to target cluster", len(reps))

        target.identity_count += moved_count
        target.updated_at = datetime.utcnow()

        await self.session.delete(source)
        await self.session.commit()

        # Refresh materialized view to reflect merged cluster state
        await self._ensure_context()
        await self._refresh_view()
        logger.info(
            "Refreshed centroid view after merging cluster %s into %s",
            source_id,
            target.id,
        )

        await self.session.refresh(target)
        return target, moved_count, moved_identity_ids, source_label

    async def _resolve_restore_label(self, desired_label: str | None, target_cluster_id: UUID) -> str | None:
        """Choose a non-conflicting label when recreating a cluster during an undo."""
        if not desired_label:
            return None

        candidate = desired_label
        suffix_attempt = 0

        while suffix_attempt < 3:
            stmt = select(IdentityCluster.id).where(
                IdentityCluster.tenant_id == self.tenant_id,
                IdentityCluster.label == candidate,
                IdentityCluster.id != target_cluster_id,
            )
            existing = await self.session.execute(stmt)
            if not existing.scalar_one_or_none():
                return candidate

            suffix = "(restored)" if suffix_attempt == 0 else f"(restored {suffix_attempt})"
            candidate = f"{desired_label} {suffix}"
            suffix_attempt += 1

        return None

    async def revert_merge(
        self,
        target_cluster_id: UUID,
        moved_identity_ids: Sequence[UUID],
        source_label: str | None,
    ) -> tuple[IdentityCluster, IdentityCluster]:
        """
        Recreate a cluster from a previous merge by moving specific identities out of the target cluster.

        Returns the restored cluster and the updated target cluster.
        """
        await self._ensure_context()
        target_cluster = await self.session.get(IdentityCluster, target_cluster_id)
        if not target_cluster or target_cluster.tenant_id != self.tenant_id:
            raise ClusterNotFoundError

        if not moved_identity_ids:
            raise ValueError("Provide at least one identity to revert.")

        unique_ids = list(set(moved_identity_ids))
        member_stmt = (
            select(IdentityMember, MediaIdentity)
            .join(MediaIdentity, MediaIdentity.id == IdentityMember.identity_id)
            .where(IdentityMember.cluster_id == target_cluster_id)
            .where(IdentityMember.identity_id.in_(unique_ids))
        )
        member_rows = await self.session.execute(member_stmt)
        member_pairs = member_rows.all()

        if not member_pairs:
            raise ValueError("No matching cluster members found to revert.")

        restored_label = await self._resolve_restore_label(source_label, target_cluster_id)
        identities = [identity for _, identity in member_pairs]

        restored_cluster = IdentityCluster(
            tenant_id=self.tenant_id,
            label=restored_label,
            representative_identity_id=identities[0].id if identities else None,
            identity_count=len(member_pairs),
            similarity_threshold=target_cluster.similarity_threshold,
            clustering_algorithm=target_cluster.clustering_algorithm,
        )
        self.session.add(restored_cluster)
        await self.session.flush()

        for member, _ in member_pairs:
            member.cluster_id = restored_cluster.id

        rep_stmt = (
            select(IdentityClusterRepresentative)
            .where(IdentityClusterRepresentative.cluster_id == target_cluster_id)
            .where(IdentityClusterRepresentative.identity_id.in_(unique_ids))
        )
        reps = await self.session.execute(rep_stmt)
        for rep in reps.scalars().all():
            rep.cluster_id = restored_cluster.id

        target_cluster.identity_count = max(target_cluster.identity_count - len(member_pairs), 0)
        target_cluster.updated_at = datetime.utcnow()

        await self.session.commit()
        await self._ensure_context()
        await self._refresh_view()
        await self.session.refresh(restored_cluster)
        await self.session.refresh(target_cluster)

        return restored_cluster, target_cluster

    async def split_cluster(self, cluster_id: UUID, n_clusters: int = 0) -> tuple[list[UUID], list[int]]:
        """
        Split a mixed cluster using Agglomerative Hierarchical Clustering.

        Uses a dendrogram-based approach. If n_clusters=0 (default), automatically
        determines the optimal number of clusters using a distance threshold.
        Otherwise, splits into exactly n_clusters groups.

        Args:
            cluster_id: The cluster to split
            n_clusters: Number of clusters to split into.
                       0 = auto-detect based on similarity threshold (default)
                       2+ = force exactly this many clusters

        Returns:
            Tuple of (new_cluster_ids, moved_counts) for each new cluster created.
            The original cluster keeps the largest group; new clusters get the rest.
        """
        from recognition.application.clustering.hierarchical_clustering import HierarchicalClustering

        await self._ensure_context()

        # 1. Fetch all identities in the cluster
        stmt = (
            select(MediaIdentity)
            .join(IdentityMember, MediaIdentity.id == IdentityMember.identity_id)
            .where(IdentityMember.cluster_id == cluster_id)
        )
        result = await self.session.execute(stmt)
        identities = list(result.scalars().all())

        if not identities or len(identities) < 2:
            logger.info(
                "Split cluster %s: only %d identities, need at least 2 to split",
                cluster_id,
                len(identities) if identities else 0,
            )
            return [], []

        # 2. Use HierarchicalClustering to split identities
        hierarchical = HierarchicalClustering(distance_threshold=0.30)
        clusters_by_label = hierarchical.split_identities(identities, n_clusters)

        # Check if we found multiple groups
        if len(clusters_by_label) <= 1:
            logger.info("Split cluster %s: All faces similar enough to stay together, nothing to split", cluster_id)
            return [], []

        # Build label array for compatibility with existing code
        identity_to_label: dict[UUID, int] = {}
        for label, members in clusters_by_label.items():
            for member in members:
                identity_to_label[member.id] = label

        labels = [identity_to_label[id.id] for id in identities]
        ids = [id.id for id in identities]

        logger.info("Split cluster %s: Hierarchical clustering labels=%s", cluster_id, labels)

        # 5. Count members per group
        label_counts: dict[int, int] = {}
        for label in labels:
            label_counts[label] = label_counts.get(label, 0) + 1

        # Sort by count descending, keep largest in original cluster
        sorted_labels = sorted(label_counts.items(), key=lambda x: x[1], reverse=True)
        largest_label = sorted_labels[0][0]

        # Get the original cluster for updates
        original_cluster = await self.session.get(IdentityCluster, cluster_id)
        if not original_cluster:
            logger.error("Split cluster %s: Original cluster not found", cluster_id)
            return [], []

        # Mark original as user-confirmed
        original_cluster.user_confirmed = True
        if not original_cluster.confirmation_source:
            original_cluster.confirmation_source = "split"

        new_cluster_ids: list[UUID] = []
        moved_counts: list[int] = []

        # 5. Create new clusters for each non-largest group
        for label, count in sorted_labels[1:]:  # Skip largest (index 0)
            indices_for_group = [i for i, lbl in enumerate(labels) if lbl == label]
            identity_ids_for_group = [ids[i] for i in indices_for_group]

            new_cluster_id = uuid4()
            new_cluster = IdentityCluster(
                id=new_cluster_id,
                tenant_id=self.tenant_id,
                label=f"Split from {str(cluster_id)[:8]}",
                identity_count=count,
                clustering_algorithm="hierarchical_split",
                user_confirmed=True,
                confirmation_source="split",
            )
            self.session.add(new_cluster)
            await self.session.flush()

            # Move members
            update_members_stmt = text(
                "UPDATE identity_members SET cluster_id = :new_cluster_id WHERE identity_id = ANY(:identity_ids)"
            ).bindparams(new_cluster_id=new_cluster_id, identity_ids=identity_ids_for_group)
            await self.session.execute(update_members_stmt)

            # Move representatives
            update_reps_stmt = text(
                "UPDATE identity_cluster_representatives SET cluster_id = :new_cluster_id WHERE identity_id = ANY(:identity_ids)"
            ).bindparams(new_cluster_id=new_cluster_id, identity_ids=identity_ids_for_group)
            await self.session.execute(update_reps_stmt)

            new_cluster_ids.append(new_cluster_id)
            moved_counts.append(count)

            logger.info(
                "Split cluster %s: Created new cluster %s with %d identities", cluster_id, new_cluster_id, count
            )

        # 6. Update original cluster count
        remaining_count = label_counts[largest_label]
        update_count_stmt = text(
            "UPDATE identity_clusters SET identity_count = :count WHERE id = :cluster_id"
        ).bindparams(count=remaining_count, cluster_id=cluster_id)
        await self.session.execute(update_count_stmt)

        await self.session.commit()
        await self._refresh_view()

        total_moved = sum(moved_counts)
        logger.info(
            "Split cluster %s complete: created %d new clusters, moved %d identities, %d remain",
            cluster_id,
            len(new_cluster_ids),
            total_moved,
            remaining_count,
        )

        return new_cluster_ids, moved_counts
