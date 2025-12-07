"""Batch processing for identity clustering.

Provides efficient batch and centroid-based matching for identities that couldn't
be matched via representatives. Includes Chinese Whispers integration for
unclustered identities.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING
from uuid import UUID

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, MediaIdentity
from recognition.application.clustering.cluster_factory import ClusterFactory
from recognition.application.clustering.cluster_repository import ClusterRepository, ClusterSearchEntry
from recognition.application.clustering.cluster_validation import ClusterValidator
from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.representatives import RepresentativeMatcher

if TYPE_CHECKING:
    from recognition.application.clustering.hdbscan_clustering import HDBSCANClustering

logger = logging.getLogger(__name__)


# Type aliases for callbacks
AddRepresentativeCallback = Callable[[UUID, MediaIdentity], Awaitable[np.ndarray | None]]
AssignToClusterCallback = Callable[[MediaIdentity, np.ndarray, UUID, float], Awaitable[None]]
RefreshViewCallback = Callable[[], Awaitable[None]]


# Type alias for ensure_context callback
EnsureContextCallback = Callable[[], Awaitable[None]]

# Type alias for create_suggestion callback (identity_id, cluster_id, rep_sim, avg_member_sim) -> None
CreateSuggestionCallback = Callable[[UUID, UUID, float, float], Awaitable[None]]


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
        ensure_context: EnsureContextCallback | None = None,
        create_suggestion: CreateSuggestionCallback | None = None,
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
        self._ensure_context = ensure_context
        self._create_suggestion = create_suggestion
        self._adaptive_threshold: float | None = None
        self._is_cold_start: bool = False  # Track if this is first chunk with no clusters
        self._cluster_count: int = 0  # Track cluster count for priority calculation

    def set_adaptive_threshold(self, threshold: float) -> None:
        """Set the adaptive threshold for graph clustering algorithms."""
        self._adaptive_threshold = threshold

    def set_cold_start(self, is_cold_start: bool, cluster_count: int = 0) -> None:
        """Set cold start mode for first chunk processing."""
        self._is_cold_start = is_cold_start
        self._cluster_count = cluster_count

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

    async def cluster_via_graph(
        self,
        identities: list[MediaIdentity],
        anchor_embeddings: dict[UUID, list[np.ndarray]] | None = None,
        centroid_map: dict[UUID, np.ndarray] | None = None,
        job_id: UUID | None = None,
        is_first_chunk: bool = False,
    ) -> list[IdentityCluster]:
        """
        Cluster identities using graph-based or density-based algorithms.

        Algorithm selection:
        - RepresentativeOnly for cold start first chunk (no existing clusters)
        - HDBSCAN for batches ≤ hdbscan_max_batch_size (default 500)
        - Chinese Whispers for larger batches (O(E) vs O(n²) complexity)

        Args:
            identities: List of identities to cluster
            anchor_embeddings: Optional dict mapping cluster_id to representative embeddings
            centroid_map: Optional dict mapping cluster_id to centroid vectors
            job_id: Optional job ID for log correlation
            is_first_chunk: Whether this is the first chunk of the first job
        """

        from recognition.application.clustering.chinese_whispers import ChineseWhispersClustering
        from recognition.application.clustering.representative_only_clustering import RepresentativeOnlyClustering

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

        # Select algorithm based on cold start state and batch size
        clusterer: RepresentativeOnlyClustering | ChineseWhispersClustering | HDBSCANClustering

        # Cold start: use representative-only clustering for deterministic, safe clustering
        if self._is_cold_start and is_first_chunk and not anchor_embeddings:
            clusterer = RepresentativeOnlyClustering(
                self.settings,
                adaptive_threshold=self._adaptive_threshold,
                create_suggestion=self._create_suggestion,
            )
            logger.info(
                "Using RepresentativeOnlyClustering for cold start first chunk (%d identities)",
                len(identities),
            )
        elif len(identities) <= self.settings.hdbscan_max_batch_size:
            try:
                from recognition.application.clustering.hdbscan_clustering import HDBSCANClustering

                clusterer = HDBSCANClustering(self.settings, adaptive_threshold=self._adaptive_threshold)
                logger.info("Using HDBSCAN for batch of %d identities", len(identities))
            except ImportError:
                logger.warning("HDBSCAN not available, falling back to Chinese Whispers")
                clusterer = ChineseWhispersClustering(self.settings, adaptive_threshold=self._adaptive_threshold)
        else:
            clusterer = ChineseWhispersClustering(self.settings, adaptive_threshold=self._adaptive_threshold)
            logger.info("Using Chinese Whispers for large batch of %d identities", len(identities))

        return await clusterer.cluster(
            identities,
            create_cluster=create_cluster_wrapper,
            anchor_embeddings=anchor_embeddings,
            add_to_cluster=add_to_cluster_wrapper if centroid_map else None,
            job_id=job_id,
        )

    async def process_clustering_batch(
        self,
        identities: list[MediaIdentity],
        chunk_size: int = 50,
        job_id: UUID | None = None,
    ) -> list[IdentityCluster]:
        """
        Process a batch of identities through the clustering pipeline.

        Clusters identities in small chunks to allow sequential learning.
        This unifies the logic for both sync and async paths, ensuring that
        later chunks can anchor to clusters formed by earlier chunks.

        Args:
            identities: List of identities to cluster
            chunk_size: Number of identities per chunk
            job_id: Optional job ID for log correlation
        """
        all_created_clusters: list[IdentityCluster] = []
        total_identities = len(identities)
        log_prefix = f"[job={job_id}] " if job_id else ""

        # Log effective threshold being used
        effective_threshold = self._adaptive_threshold or self.settings.similarity_threshold
        logger.info(
            "%sUsing effective threshold %.4f for clustering (adaptive=%s, base=%.4f)",
            log_prefix,
            effective_threshold,
            self._adaptive_threshold is not None,
            self.settings.similarity_threshold,
        )

        for i in range(0, total_identities, chunk_size):
            chunk = identities[i : i + chunk_size]
            chunk_num = (i // chunk_size) + 1
            logger.info(
                "%sProcessing clustering chunk %d (%d-%d/%d)",
                log_prefix,
                chunk_num,
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
            # Use adaptive threshold if set, otherwise fall back to settings.similarity_threshold
            effective_threshold = self._adaptive_threshold or self.settings.similarity_threshold
            rep_matcher = RepresentativeMatcher(
                threshold=effective_threshold,
                add_representative_embedding=self._add_representative,
                assign_to_cluster_by_id=self._assign_to_cluster,
                borderline_validation=self.validator.validate_representative_match
                if (self.settings.borderline_validation_enabled or self.settings.member_validation_enabled)
                else None,
                settings=self.settings,
                create_suggestion=self._create_suggestion,
                labeled_cluster_count=self._cluster_count,
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
                # Re-establish tenant context after commit (SET LOCAL is transaction-scoped)
                if self._ensure_context:
                    await self._ensure_context()
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
                        "%sCentroid matching: matched %d/%d remaining identities",
                        log_prefix,
                        centroid_matched_count,
                        centroid_matched_count + len(remaining),
                    )

            if not remaining:
                await self.session.commit()
                # Re-establish tenant context after commit (SET LOCAL is transaction-scoped)
                if self._ensure_context:
                    await self._ensure_context()
                continue

            # 3. If still unmatched, run graph clustering with anchors
            # Pass representative embeddings grouped by cluster_id
            anchor_embeddings: dict[UUID, list[np.ndarray]] = {}
            for cluster_id, reps in representatives_by_cluster.items():
                anchor_embeddings[cluster_id] = [np.array(emb, dtype=np.float32) for emb in reps]

            centroid_map: dict[UUID, np.ndarray] = {entry.cluster.id: entry.centroid for entry in existing_clusters}

            # First chunk with no anchors = cold start first chunk
            is_first_chunk = (chunk_num == 1) and (len(anchor_embeddings) == 0)

            chunk_clusters = await self.cluster_via_graph(
                remaining,
                anchor_embeddings=anchor_embeddings,
                centroid_map=centroid_map,
                job_id=job_id,
                is_first_chunk=is_first_chunk,
            )
            all_created_clusters.extend(chunk_clusters)

            # Commit after each chunk to persist new clusters/reps for the next chunk
            await self.session.commit()
            # Re-establish tenant context after commit (SET LOCAL is transaction-scoped)
            if self._ensure_context:
                await self._ensure_context()

        return all_created_clusters
