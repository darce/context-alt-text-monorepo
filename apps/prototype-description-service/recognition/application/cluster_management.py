"""Cluster management helpers (merge, centroid combination)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityMember, MediaIdentity

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
