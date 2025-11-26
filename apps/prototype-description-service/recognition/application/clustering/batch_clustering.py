"""Batch processing for identity clustering.

Provides efficient batch and centroid-based matching for identities that couldn't
be matched via representatives. Includes Chinese Whispers integration for
unclustered identities.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, MediaIdentity
from recognition.application.clustering.cluster_factory import ClusterFactory
from recognition.application.clustering.cluster_repository import ClusterRepository, ClusterSearchEntry
from recognition.application.clustering.cluster_validation import ClusterValidator
from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.representatives import RepresentativeMatcher

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Type aliases for callbacks
AddRepresentativeCallback = Callable[[UUID, MediaIdentity], Awaitable[np.ndarray | None]]
AssignToClusterCallback = Callable[[MediaIdentity, np.ndarray, UUID, float], Awaitable[None]]
RefreshViewCallback = Callable[[], Awaitable[None]]


class BatchClusteringProcessor:
    """Processes batches of identities for clustering."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        settings: ClusteringSettings,
        repository: ClusterRepository,
        factory: ClusterFactory,
        validator: ClusterValidator,
        add_representative: AddRepresentativeCallback,
        assign_to_cluster: AssignToClusterCallback,
        refresh_view: RefreshViewCallback,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.settings = settings
        self.repository = repository
        self.factory = factory
        self.validator = validator
        self._add_representative = add_representative
        self._assign_to_cluster = assign_to_cluster
        self._refresh_view = refresh_view

    async def match_via_centroids(
        self,
        identities: list[MediaIdentity],
        centroid_cache: list[ClusterSearchEntry],
        threshold: float,
    ) -> tuple[int, list[MediaIdentity]]:
        """
        Match identities against cluster centroids for difficult cases.

        This is a fallback matching phase for identities that didn't match
        any representatives but might still belong to existing clusters.

        Returns:
            (matched_count, remaining_identities)
        """
        matched_count = 0
        remaining: list[MediaIdentity] = []

        for identity in identities:
            best_cluster_id: UUID | None = None
            best_similarity = 0.0

            for entry in centroid_cache:
                similarity = float(np.dot(identity.embedding, entry.centroid))

                if similarity > best_similarity and similarity >= threshold:
                    best_cluster_id = entry.cluster.id
                    best_similarity = similarity

            if best_cluster_id:
                # Validate with member check before accepting
                identity_vector = np.array(identity.embedding, dtype=np.float32)
                if await self.validator.validate_centroid_match(
                    identity, identity_vector, best_cluster_id, best_similarity
                ):
                    await self._assign_to_cluster(identity, identity_vector, best_cluster_id, best_similarity)
                    matched_count += 1
                    logger.info(
                        "Centroid match: identity=%s, similarity=%.4f, cluster=%s",
                        identity.id,
                        best_similarity,
                        best_cluster_id,
                    )
                else:
                    remaining.append(identity)
            else:
                remaining.append(identity)

        return matched_count, remaining

    async def stage2_batch_clustering(
        self,
        identities: list[MediaIdentity],
        anchors: list[MediaIdentity] | None = None,
        centroid_map: dict[UUID, np.ndarray] | None = None,
    ) -> list[IdentityCluster]:
        """Cluster identities using Chinese Whispers on normalized embeddings."""

        async def create_cluster_wrapper(members: Sequence[MediaIdentity]) -> tuple[IdentityCluster, object]:
            return await self.factory.create_cluster_with_centroid(
                members,
                add_representative_callback=self._add_representative,
            )

        async def add_to_cluster_wrapper(cluster_id: UUID, members: Sequence[MediaIdentity]) -> None:
            if not centroid_map or cluster_id not in centroid_map:
                logger.warning("Cannot add members to cluster %s: centroid not found in cache", cluster_id)
                return

            centroid = centroid_map[cluster_id]
            for member in members:
                vec = np.array(member.embedding, dtype=np.float32)
                sim = float(np.dot(vec, centroid))
                await self._assign_to_cluster(member, vec, cluster_id, sim)

        from recognition.application.clustering.chinese_whispers import ChineseWhispersClustering

        cw = ChineseWhispersClustering(self.settings)
        return await cw.cluster(
            identities,
            create_cluster=create_cluster_wrapper,
            anchors=anchors,
            add_to_cluster=add_to_cluster_wrapper if centroid_map else None,
        )

    async def cluster_batch_incremental(
        self,
        identities: list[MediaIdentity],
        chunk_size: int = 10,
    ) -> list[IdentityCluster]:
        """
        Cluster identities in small chunks to allow sequential learning.

        This unifies the logic for both sync and async paths, ensuring that
        later chunks can anchor to clusters formed by earlier chunks.
        """
        all_created_clusters: list[IdentityCluster] = []
        total_identities = len(identities)

        for i in range(0, total_identities, chunk_size):
            chunk = identities[i : i + chunk_size]
            logger.info(
                "Processing clustering chunk %d-%d/%d",
                i + 1,
                min(i + chunk_size, total_identities),
                total_identities,
            )

            # CRITICAL: Refresh materialized view BEFORE loading existing clusters
            await self._refresh_view()

            existing_clusters = await self.repository.get_clusters_with_centroids()
            # Update validator cache
            self.validator.set_centroid_cache(existing_clusters)
            representatives_by_cluster = await self.repository.get_clusters_with_representatives()

            # 1. Try to match against existing representatives
            rep_matcher = RepresentativeMatcher(
                threshold=self.settings.similarity_threshold,
                add_representative_embedding=self._add_representative,
                assign_to_cluster_by_id=self._assign_to_cluster,
                borderline_validation=self.validator.validate_representative_match
                if (self.settings.borderline_validation_enabled or self.settings.member_validation_enabled)
                else None,
                settings=self.settings,
            )

            _assigned_count, remaining, representatives_by_cluster = await rep_matcher.match(
                chunk,
                representatives_by_cluster,
                borderline_upper=(
                    1.0
                    if self.settings.member_validation_enabled
                    else (
                        self.settings.borderline_upper_threshold
                        if self.settings.borderline_validation_enabled
                        else None
                    )
                ),
            )

            if not remaining:
                await self.session.commit()
                continue

            # 2. Try centroid matching for remaining identities (fallback for difficult cases)
            centroid_matched_count = 0
            if self.settings.centroid_match_threshold > 0:
                centroid_matched_count, remaining = await self.match_via_centroids(
                    remaining,
                    existing_clusters,
                    threshold=self.settings.centroid_match_threshold,
                )
                if centroid_matched_count > 0:
                    logger.info(
                        "Centroid matching: matched %d/%d remaining identities",
                        centroid_matched_count,
                        centroid_matched_count + len(remaining),
                    )

            if not remaining:
                await self.session.commit()
                continue

            # 3. If still unmatched, run Chinese Whispers with anchors
            anchors: list[MediaIdentity] = []
            centroid_map: dict[UUID, np.ndarray] = {entry.cluster.id: entry.centroid for entry in existing_clusters}

            for cluster_id, reps in representatives_by_cluster.items():
                for rep_emb in reps:
                    anchors.append(
                        MediaIdentity(
                            id=uuid4(),
                            cluster_id=cluster_id,
                            embedding=rep_emb,
                            media_id=-1,  # distinct marker
                        )
                    )

            chunk_clusters = await self.stage2_batch_clustering(remaining, anchors=anchors, centroid_map=centroid_map)
            all_created_clusters.extend(chunk_clusters)

            # Commit after each chunk to persist new clusters/reps for the next chunk
            await self.session.commit()

        return all_created_clusters
