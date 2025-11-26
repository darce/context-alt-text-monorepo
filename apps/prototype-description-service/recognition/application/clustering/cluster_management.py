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
        """Rename a cluster, ensuring the new label is unique for the tenant."""
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
            )
            self.session.add(target)
            await self.session.flush()

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

    async def split_cluster(self, cluster_id: UUID) -> tuple[UUID | None, int]:
        """
        Split a mixed cluster using DBSCAN.
        Returns (new_cluster_id, moved_count).
        """
        from sklearn.cluster import DBSCAN

        await self._ensure_context()

        # 1. Fetch all identities in the cluster
        stmt = (
            select(MediaIdentity)
            .join(IdentityMember, MediaIdentity.id == IdentityMember.identity_id)
            .where(IdentityMember.cluster_id == cluster_id)
        )
        result = await self.session.execute(stmt)
        identities = result.scalars().all()

        if not identities or len(identities) < 2:
            return None, 0

        # 2. Prepare embeddings
        embeddings = np.array([id.embedding for id in identities])
        ids = [id.id for id in identities]

        # 3. Run DBSCAN
        # eps=0.35 corresponds to cosine similarity of ~0.65
        clustering = DBSCAN(eps=0.35, min_samples=2, metric="cosine").fit(embeddings)
        labels = clustering.labels_

        unique_labels = set(labels)
        if len(unique_labels) <= 1:
            # Only one group (or all noise), nothing to split
            return None, 0

        # 4. Perform Split
        # We move Group 1 (and others if any) to a new cluster.
        group_1_indices = [i for i, label in enumerate(labels) if label == 1]
        if not group_1_indices:
            return None, 0

        new_cluster_id = uuid4()
        new_cluster = IdentityCluster(
            id=new_cluster_id,
            tenant_id=self.tenant_id,
            label=f"Split from {str(cluster_id)[:8]}",
            identity_count=len(group_1_indices),
            clustering_algorithm="dbscan_split",
        )
        self.session.add(new_cluster)
        await self.session.flush()

        group_1_identity_ids = [ids[i] for i in group_1_indices]

        # Move members
        update_members_stmt = text(
            "UPDATE identity_members SET cluster_id = :new_cluster_id WHERE identity_id = ANY(:identity_ids)"
        ).bindparams(new_cluster_id=new_cluster_id, identity_ids=group_1_identity_ids)
        await self.session.execute(update_members_stmt)

        # Move representatives
        update_reps_stmt = text(
            "UPDATE identity_cluster_representatives SET cluster_id = :new_cluster_id WHERE identity_id = ANY(:identity_ids)"
        ).bindparams(new_cluster_id=new_cluster_id, identity_ids=group_1_identity_ids)
        await self.session.execute(update_reps_stmt)

        # Update counts
        remaining_count = len(identities) - len(group_1_indices)
        update_count_stmt = text(
            "UPDATE identity_clusters SET identity_count = :count WHERE id = :cluster_id"
        ).bindparams(count=remaining_count, cluster_id=cluster_id)
        await self.session.execute(update_count_stmt)

        await self.session.commit()
        await self._refresh_view()

        return new_cluster_id, len(group_1_indices)
