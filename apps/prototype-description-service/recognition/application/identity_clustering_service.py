"""Clustering service for grouping similar identities using pgvector."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Sequence, Tuple
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ClusterCentroid, IdentityCluster, IdentityMember, MediaIdentity
from db.tenant_context import set_tenant_context
from recognition.application.centroid_utils import (
    compute_centroid,
    compute_similarity,
    _normalize_vector,
    update_centroid_incremental,
)

logger = logging.getLogger(__name__)


class ClusterNotFoundError(Exception):
    """Raised when a cluster cannot be found for the current tenant."""


class ClusterLabelConflictError(Exception):
    """Raised when attempting to reuse an existing cluster label."""


@dataclass
class ClusterSearchEntry:
    """In-memory representation of a cluster centroid for incremental search."""

    cluster: IdentityCluster
    centroid: np.ndarray
    member_count: int


class IdentityClusteringService:
    """Cluster similar identities using pgvector cosine similarity."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        similarity_threshold: float = 0.6,
        strict_validation: bool = False,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.threshold = similarity_threshold
        self.strict_validation = strict_validation

    async def _ensure_tenant_context(self) -> None:
        await set_tenant_context(self.session, self.tenant_id)

    async def cluster_identities_incremental(self) -> List[IdentityCluster]:
        """
        Cluster unassigned identities by comparing them to existing cluster centroids.
        """
        logger.info("Starting incremental clustering for tenant %s", self.tenant_id)
        await self._ensure_tenant_context()

        existing_clusters = await self._get_clusters_with_centroids()
        unclustered = await self._get_unclustered_identities()

        if not unclustered:
            logger.info("No unclustered identities for tenant %s", self.tenant_id)
            return []

        created_clusters: List[IdentityCluster] = []

        for identity in unclustered:
            identity_vector = _normalize_vector(np.array(identity.embedding, dtype=np.float32))
            best_entry, best_similarity = self._find_best_cluster_match(
                identity_vector,
                existing_clusters,
            )

            if best_entry and best_similarity >= self.threshold:
                await self._assign_to_cluster(identity, identity_vector, best_entry, best_similarity)
                logger.debug(
                    "Assigned identity %s to cluster %s (similarity %.3f)",
                    identity.id,
                    best_entry.cluster.label,
                    best_similarity,
                )
            else:
                cluster, entry = await self._create_cluster_with_centroid([identity])
                created_clusters.append(cluster)
                existing_clusters.append(entry)
                logger.debug(
                    "Created new cluster %s for identity %s",
                    cluster.label,
                    identity.id,
                )

        await self.session.commit()
        await self._refresh_centroid_view()

        logger.info(
            "Incremental clustering complete: %d new clusters",
            len(created_clusters),
        )
        return created_clusters

    async def cluster_identities(self) -> List[IdentityCluster]:
        """Backward compatibility shim for legacy callers."""
        return await self.cluster_identities_incremental()

    async def _get_unclustered_identities(self) -> List[MediaIdentity]:
        membership_exists = (
            select(1)
            .where(
                IdentityMember.tenant_id == self.tenant_id,
                IdentityMember.identity_id == MediaIdentity.id,
            )
            .exists()
        )

        stmt = (
            select(MediaIdentity)
            .where(
                MediaIdentity.tenant_id == self.tenant_id,
                ~membership_exists,
            )
            .order_by(MediaIdentity.created_at)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def _get_clusters_with_centroids(self) -> List[ClusterSearchEntry]:
        stmt = (
            select(
                IdentityCluster,
                ClusterCentroid.centroid,
                ClusterCentroid.member_count,
            )
            .join(ClusterCentroid, IdentityCluster.id == ClusterCentroid.cluster_id)
            .where(IdentityCluster.tenant_id == self.tenant_id)
        )

        result = await self.session.execute(stmt)
        entries: List[ClusterSearchEntry] = []

        for cluster, centroid, member_count in result.all():
            if centroid is None or member_count is None:
                continue
            entries.append(
                ClusterSearchEntry(
                    cluster=cluster,
                    centroid=np.array(centroid, dtype=np.float32),
                    member_count=int(member_count),
                )
            )
        return entries

    def _find_best_cluster_match(
        self,
        identity_vector: np.ndarray,
        clusters: List[ClusterSearchEntry],
    ) -> Tuple[ClusterSearchEntry | None, float]:
        best_entry: ClusterSearchEntry | None = None
        best_similarity = 0.0

        for entry in clusters:
            if entry.member_count == 0:
                continue

            similarity = compute_similarity(identity_vector, entry.centroid)
            if similarity > best_similarity:
                best_similarity = similarity
                best_entry = entry

        return best_entry, best_similarity

    async def _assign_to_cluster(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        entry: ClusterSearchEntry,
        similarity: float,
    ) -> None:
        if abs(similarity - self.threshold) <= 0.05:
            logger.warning(
                "Borderline assignment: identity %s to cluster %s (similarity %.4f, threshold %.4f)",
                identity.id,
                entry.cluster.id,
                similarity,
                self.threshold,
            )

        member = IdentityMember(
            tenant_id=self.tenant_id,
            cluster_id=entry.cluster.id,
            identity_id=identity.id,
            similarity=similarity,
            created_by_user_id=identity.created_by_user_id,
        )
        self.session.add(member)

        if similarity + 1e-6 < self.threshold:
            logger.warning(
                "Assigned identity %s to cluster %s with similarity %.4f below threshold %.4f",
                identity.id,
                entry.cluster.id,
                similarity,
                self.threshold,
            )

        old_count = entry.member_count
        entry.member_count += 1
        entry.centroid = update_centroid_incremental(
            entry.centroid,
            old_count,
            identity_vector,
        )

        if self.strict_validation:
            await self._validate_assignment(identity, identity_vector, entry, similarity)

        entry.cluster.identity_count += 1
        entry.cluster.updated_at = datetime.utcnow()

    async def _create_cluster_with_centroid(
        self,
        identities: Sequence[MediaIdentity],
    ) -> Tuple[IdentityCluster, ClusterSearchEntry]:
        if not identities:
            raise ValueError("Cannot create cluster without identities")

        await self._ensure_tenant_context()

        embeddings = [_normalize_vector(np.array(identity.embedding, dtype=np.float32)) for identity in identities]
        centroid_vector = compute_centroid(embeddings)

        representative = max(identities, key=lambda i: i.confidence)
        cluster = IdentityCluster(
            tenant_id=self.tenant_id,
            label=f"cluster-{uuid4().hex[:8]}",
            representative_identity_id=representative.id,
            identity_count=len(identities),
            similarity_threshold=self.threshold,
            clustering_algorithm="pgvector-incremental",
        )
        self.session.add(cluster)
        await self.session.flush()

        for identity in identities:
            similarity = compute_similarity(
                _normalize_vector(np.array(identity.embedding, dtype=np.float32)),
                centroid_vector,
            )
            member = IdentityMember(
                tenant_id=self.tenant_id,
                cluster_id=cluster.id,
                identity_id=identity.id,
                similarity=similarity,
                created_by_user_id=identity.created_by_user_id,
            )
            self.session.add(member)

        entry = ClusterSearchEntry(
            cluster=cluster,
            centroid=np.array(centroid_vector, dtype=np.float32),
            member_count=len(identities),
        )

        return cluster, entry

    async def _validate_assignment(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        entry: ClusterSearchEntry,
        similarity_at_assignment: float,
    ) -> None:
        """Re-check similarity after centroid update to catch drift."""

        recomputed_similarity = compute_similarity(identity_vector, entry.centroid)
        if recomputed_similarity + 1e-6 < self.threshold:
            logger.error(
                "Post-update similarity for identity %s in cluster %s dropped below threshold "
                "(assigned=%.4f, recomputed=%.4f, threshold=%.4f)",
                identity.id,
                entry.cluster.id,
                similarity_at_assignment,
                recomputed_similarity,
                self.threshold,
            )

    async def _refresh_centroid_view(self) -> None:
        try:
            await self.session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            await self.session.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
        except Exception as exc:  # pragma: no cover - best effort refresh
            logger.warning("Failed to refresh centroid view: %s", exc)
        finally:
            await self.session.execute(text("RESET app.bypass_rls"))

    async def get_cluster_summary(self, cluster_id: UUID) -> Dict[str, object]:
        cluster = await self.session.get(IdentityCluster, cluster_id)
        if not cluster:
            raise ValueError("Cluster not found")

        stmt = (
            select(IdentityMember, MediaIdentity)
            .join(MediaIdentity, IdentityMember.identity_id == MediaIdentity.id)
            .where(IdentityMember.cluster_id == cluster_id)
            .order_by(IdentityMember.similarity.desc())
            .limit(10)
        )

        result = await self.session.execute(stmt)
        sample_rows = result.all()

        member_rows = await self.session.execute(
            select(IdentityMember.identity_id).where(IdentityMember.cluster_id == cluster_id)
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

    async def rename_cluster(self, cluster_id: UUID, new_label: str) -> IdentityCluster:
        await self._ensure_tenant_context()
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
        await self._ensure_tenant_context()
        await self.session.refresh(cluster)
        return cluster

    async def merge_cluster_into_label(self, source_id: UUID, target_label: str) -> tuple[IdentityCluster, int]:
        await self._ensure_tenant_context()
        source = await self.session.get(IdentityCluster, source_id)
        if not source or source.tenant_id != self.tenant_id:
            raise ClusterNotFoundError

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

        members_result = await self.session.execute(
            select(IdentityMember).where(IdentityMember.cluster_id == source.id)
        )
        members = members_result.scalars().all()
        for member in members:
            member.cluster_id = target.id
        moved_count = len(members)

        target.identity_count += moved_count
        target.updated_at = datetime.utcnow()

        await self.session.delete(source)
        await self.session.commit()
        await self._ensure_tenant_context()
        await self.session.refresh(target)
        return target, moved_count

    async def merge_similar_clusters(
        self,
        threshold: float = 0.85,
        max_iterations: int = 3,
    ) -> int:
        await self._ensure_tenant_context()
        entries = await self._get_clusters_with_centroids()
        merges_performed = 0
        iterations = 0

        while iterations < max_iterations and len(entries) > 1:
            merged_this_round = False
            i = 0
            while i < len(entries):
                target_entry = entries[i]
                j = i + 1
                while j < len(entries):
                    source_entry = entries[j]
                    similarity = compute_similarity(
                        target_entry.centroid,
                        source_entry.centroid,
                    )
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
                                target_entry.centroid = self._combine_centroids(
                                    target_entry,
                                    source_entry,
                                )
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
            await self._ensure_tenant_context()
            await self._refresh_centroid_view()
        else:
            await self.session.flush()

        return merges_performed

    def _combine_centroids(
        self,
        target: ClusterSearchEntry,
        source: ClusterSearchEntry,
    ) -> np.ndarray:
        total_members = target.member_count + source.member_count
        if total_members == 0:
            return target.centroid

        combined = (
            target.centroid * float(target.member_count)
            + source.centroid * float(source.member_count)
        ) / float(total_members)

        norm = float(np.linalg.norm(combined))
        if norm == 0:
            return combined
        return combined / norm

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
