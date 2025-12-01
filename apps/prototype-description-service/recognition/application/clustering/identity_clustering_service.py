"""Clustering service for grouping similar identities using pgvector.

This is a thin orchestrator that delegates to specialized modules:
- TenantContextManager: Database context and view refresh
- RepresentativeManager: Adding representative embeddings
- ClusterValidator: Validation of identity-to-cluster matches
- BatchClusteringProcessor: Batch and centroid-based matching
- ClusteringJobService: Async job management
- ClusterOperations: Rename, merge, revert, split operations
- SuggestionService: Borderline match suggestions for user review
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ClusterCentroid, IdentityCluster, IdentityClusteringJob, MediaIdentity
from recognition.application.clustering.batch_clustering import BatchClusteringProcessor
from recognition.application.clustering.cluster_assignment import ClusterAssigner
from recognition.application.clustering.cluster_factory import ClusterFactory
from recognition.application.clustering.cluster_management import (
    ClusterLabelConflictError,
    ClusterMerger,
    ClusterNotFoundError,
    ClusterOperations,
    build_cluster_summary,
)
from recognition.application.clustering.cluster_repository import ClusterRepository, ClusterSearchEntry
from recognition.application.clustering.cluster_validation import ClusterValidator
from recognition.application.clustering.clustering_job_service import ClusteringJobService
from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.clustering.suggestion_service import SuggestionService
from recognition.application.clustering.tenant_context import TenantContextManager
from recognition.application.representatives.representative_manager import RepresentativeManager
from recognition.application.representatives.representative_matcher import RepresentativeMatcher
from recognition.config import get_settings

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = [
    "ClusterNotFoundError",
    "ClusterLabelConflictError",
    "IdentityClusteringService",
]


class IdentityClusteringService:
    """Cluster similar identities using pgvector cosine similarity.

    This service orchestrates the clustering workflow by composing:
    - TenantContextManager for DB context
    - RepresentativeManager for representative embeddings
    - ClusterValidator for match validation
    - BatchClusteringProcessor for batch/centroid matching
    - ClusteringJobService for async job management
    - ClusterOperations for rename/merge/split operations
    """

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        similarity_threshold: float | None = None,
        strict_validation: bool = False,
        settings: ClusteringSettings | None = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id

        # Settings
        if settings is not None:
            self.settings = settings
        else:
            clustering_cfg = get_settings().identity_clustering
            self.settings = ClusteringSettings.from_config(
                clustering_cfg,
                similarity_override=similarity_threshold,
            )
        self.threshold = self.settings.similarity_threshold
        self._base_threshold = self.threshold  # Store base threshold for adaptive computation
        self.strict_validation = strict_validation

        # Infrastructure
        self._context = TenantContextManager(session, tenant_id)

        # Core components
        self.repository = ClusterRepository(session, tenant_id)
        self.factory = ClusterFactory(session, tenant_id, self.threshold)
        self.assigner = ClusterAssigner(session, tenant_id, self.settings)

        if strict_validation:
            self.assigner.enable_strict_validation()

        # Representative management
        self._rep_manager = RepresentativeManager(session, tenant_id, self.repository, self.settings)

        # Validation
        self._validator = ClusterValidator(session, tenant_id, self.settings)

        # Suggestion service (for borderline matches)
        self._suggestion_service = SuggestionService(session, tenant_id)

        # Wrapper for creating suggestions that matches the callback signature
        async def create_suggestion_wrapper(
            identity_id: UUID,
            cluster_id: UUID,
            rep_similarity: float,
            avg_member_similarity: float,
        ) -> None:
            await self._suggestion_service.create_suggestion(
                identity_id=identity_id,
                cluster_id=cluster_id,
                representative_similarity=rep_similarity,
                avg_member_similarity=avg_member_similarity,
            )

        # Batch processing
        self._batch_processor = BatchClusteringProcessor(
            session=session,
            tenant_id=tenant_id,
            settings=self.settings,
            repository=self.repository,
            factory=self.factory,
            validator=self._validator,
            add_representative=self._rep_manager.add_representative,
            assign_to_cluster=self.assigner.assign_to_cluster_by_id,
            refresh_view=self._context.refresh_centroid_view,
            ensure_context=self._context.ensure_context,
            create_suggestion=create_suggestion_wrapper,
        )

        # Job service
        self._job_service = ClusteringJobService(
            session=session,
            tenant_id=tenant_id,
            repository=self.repository,
            settings=self.settings,
            ensure_tenant_context=self._context.ensure_context,
            refresh_view=self._context.refresh_centroid_view,
            merge_similar_clusters=self.merge_similar_clusters,
        )
        self._job_service.set_batch_processor(self._batch_processor)

        # Cluster operations
        self._operations = ClusterOperations(
            session=session,
            tenant_id=tenant_id,
            threshold=self.threshold,
            refresh_view=self._context.refresh_centroid_view,
            ensure_context=self._context.ensure_context,
        )

        # Cache for centroid entries
        self._centroid_cache: list[ClusterSearchEntry] = []

    def _log_telemetry(self, event: dict[str, object]) -> None:
        """Lightweight structured telemetry via logger."""
        logger.info("clustering_telemetry: %s", event)

    def _update_adaptive_threshold(self, cluster_count: int) -> float:
        """Update effective threshold based on cluster maturity.

        Computes adaptive threshold and propagates to sub-components.
        Follows curriculum learning: strict early, relax as system matures.

        Args:
            cluster_count: Number of existing clusters.

        Returns:
            The new effective threshold.
        """
        new_threshold = self.settings.compute_adaptive_threshold(cluster_count)

        if new_threshold != self.threshold:
            logger.info(
                "Adaptive threshold: %.4f -> %.4f (cluster_count=%d, base=%.4f, strict=%.4f)",
                self.threshold,
                new_threshold,
                cluster_count,
                self._base_threshold,
                self.settings.adaptive_threshold_strict,
            )
            self.threshold = new_threshold
            # Update sub-components that cache the threshold
            self.factory.threshold = new_threshold
            self.assigner.threshold = new_threshold
            self._operations.threshold = new_threshold
            self._batch_processor.set_adaptive_threshold(new_threshold)

        # Set cold start mode based on cluster count
        is_cold_start = cluster_count < self.settings.adaptive_threshold_maturity_point
        self._batch_processor.set_cold_start(is_cold_start, cluster_count)

        if is_cold_start:
            logger.info(
                "Cold start mode: cluster_count=%d < maturity_point=%d",
                cluster_count,
                self.settings.adaptive_threshold_maturity_point,
            )

        return new_threshold

    # =========================================================================
    # Main clustering entry point
    # =========================================================================

    async def cluster_unclustered_identities(self) -> dict[str, object]:
        """
        Cluster unassigned identities using representative matching and graph clustering.

        Routes to sync or async processing based on batch size.
        This is the single canonical entry point for all clustering operations.

        Returns:
            dict with keys:
                - status: "complete" or "pending"
                - assigned: number of identities assigned to existing clusters
                - clusters: list of newly created clusters (sync only)
                - job_id: job ID for async tracking (async only)
                - queued_count: number queued for async processing (async only)
        """
        await self._context.ensure_context()

        # Get current cluster count for adaptive threshold
        existing_clusters = await self.repository.get_clusters_with_centroids()
        self._update_adaptive_threshold(len(existing_clusters))

        unclustered_count = await self.repository.count_unclustered_identities()

        if unclustered_count == 0:
            return {"status": "complete", "assigned": 0, "clusters": []}

        if unclustered_count <= self.settings.ward_sync_batch_limit:
            # Sync path - generate a job_id for log correlation
            job_id = uuid4()
            logger.info("[job=%s] Starting sync clustering for %d identities", job_id, unclustered_count)
            unclustered = await self.repository.get_unclustered_identities()
            clusters = await self._batch_processor.process_clustering_batch(unclustered, job_id=job_id)
            await self._run_auto_merge_if_enabled([])
            await self.session.commit()
            await self._context.refresh_centroid_view()
            logger.info(
                "[job=%s] Sync clustering complete: %d assigned, %d new clusters",
                job_id,
                len(unclustered) - len(clusters),
                len(clusters),
            )
            return {
                "status": "complete",
                "assigned": len(unclustered) - len(clusters),
                "clusters": clusters,
            }

        # Async path
        unclustered = await self.repository.get_unclustered_identities()
        logger.info("Routing %d identities to async clustering path", len(unclustered))
        job = await self._job_service.enqueue_clustering_job(unclustered)
        self._log_telemetry(
            {
                "stage": "async_job_enqueued",
                "tenant_id": str(self.tenant_id),
                "job_id": str(job.id),
            }
        )
        return {
            "status": "pending",
            "assigned": 0,
            "queued_count": len(unclustered),
            "job_id": str(job.id),
        }

    # =========================================================================
    # Helper methods
    # =========================================================================

    async def _create_representative_matcher(self) -> RepresentativeMatcher:
        """Create a RepresentativeMatcher with current settings.

        Includes labeled cluster count for early-stage suggestion guard.
        """
        # Determine which validation approach to use
        use_suggestion_tier = self.settings.suggestion_enabled and self.settings.member_validation_enabled

        # Get labeled cluster count for early-stage detection
        labeled_cluster_count = await self.repository.count_labeled_clusters()

        # Early-stage also uses suggestions (even without full suggestion tier validation)
        use_suggestions = use_suggestion_tier or self.settings.early_stage_suggestion_enabled

        return RepresentativeMatcher(
            threshold=self.threshold,
            add_representative_embedding=self._rep_manager.add_representative,
            assign_to_cluster_by_id=self.assigner.assign_to_cluster_by_id,
            borderline_validation=(
                self._validator.validate_representative_match
                if (self.settings.borderline_validation_enabled or self.settings.member_validation_enabled)
                and not use_suggestion_tier
                else None
            ),
            settings=self.settings,
            suggestion_validation=(
                self._validator.validate_representative_match_with_suggestion if use_suggestion_tier else None
            ),
            create_suggestion=self._create_suggestion if use_suggestions else None,
            labeled_cluster_count=labeled_cluster_count,
        )

    async def _create_suggestion(
        self,
        identity_id: UUID,
        cluster_id: UUID,
        rep_similarity: float,
        avg_member_similarity: float,
    ) -> None:
        """Create a suggestion record for user review via SuggestionService."""
        # Compute priority based on cold start state and cluster confirmation
        # During cold start, we need to query the cluster's user_confirmed status
        cluster = await self.session.get(IdentityCluster, cluster_id)
        cluster_user_confirmed = cluster.user_confirmed if cluster else False

        priority = SuggestionService.compute_priority(
            representative_similarity=rep_similarity,
            cluster_count=self._batch_processor._cluster_count,
            cluster_user_confirmed=cluster_user_confirmed,
            maturity_point=self.settings.adaptive_threshold_maturity_point,
        )

        await self._suggestion_service.create_suggestion(
            identity_id=identity_id,
            cluster_id=cluster_id,
            representative_similarity=rep_similarity,
            avg_member_similarity=avg_member_similarity,
            priority=priority,
        )

    def _get_borderline_upper(self) -> float | None:
        """Get the borderline upper threshold based on settings."""
        if self.settings.member_validation_enabled:
            return 1.0
        if self.settings.borderline_validation_enabled:
            return self.settings.borderline_upper_threshold
        return None

    async def _run_auto_merge_if_enabled(self, existing_clusters: list[ClusterSearchEntry]) -> None:
        """Run auto-merge if enabled and within identity limit."""
        if not self.settings.auto_merge_enabled:
            return

        total_identities = sum(e.member_count for e in existing_clusters) if existing_clusters else 0
        logger.info("Auto-merge: %d identities (max: %d)", total_identities, self.settings.auto_merge_max_identities)

        if total_identities <= self.settings.auto_merge_max_identities:
            merges = await self.merge_similar_clusters(
                threshold=self.settings.auto_merge_threshold,
                max_iterations=self.settings.auto_merge_max_iterations,
            )
            logger.info("Auto-merge completed: %d merges", merges)
            self._log_telemetry(
                {
                    "stage": "auto_merge_complete",
                    "tenant_id": str(self.tenant_id),
                    "merges": merges,
                }
            )

    # =========================================================================
    # Job management (delegated)
    # =========================================================================

    async def get_clustering_job(self, job_id: UUID) -> IdentityClusteringJob | None:
        """Get a clustering job by ID."""
        return await self._job_service.get_clustering_job(job_id)

    async def process_clustering_job(self, job_id: UUID) -> list[IdentityCluster]:
        """Process a queued clustering job."""
        return await self._job_service.process_clustering_job(job_id)

    # =========================================================================
    # Cluster operations (delegated)
    # =========================================================================

    async def get_cluster_summary(self, cluster_id: UUID) -> dict[str, object]:
        """Get a summary of a cluster."""
        cluster = await self.session.get(IdentityCluster, cluster_id)
        if not cluster:
            raise ValueError("Cluster not found")
        return await build_cluster_summary(self.session, cluster)

    async def rename_cluster(self, cluster_id: UUID, new_label: str) -> IdentityCluster:
        """Rename a cluster."""
        return await self._operations.rename_cluster(cluster_id, new_label)

    async def merge_cluster_into_label(
        self,
        source_id: UUID,
        target_label: str,
    ) -> tuple[IdentityCluster, int, list[UUID], str | None]:
        """Merge a source cluster into a target cluster by label."""
        return await self._operations.merge_cluster_into_label(source_id, target_label)

    async def revert_merge(
        self,
        target_cluster_id: UUID,
        moved_identity_ids: Sequence[UUID],
        source_label: str | None,
    ) -> tuple[IdentityCluster, IdentityCluster]:
        """Revert a merge operation."""
        return await self._operations.revert_merge(target_cluster_id, moved_identity_ids, source_label)

    async def merge_similar_clusters(
        self,
        threshold: float | None = None,
        max_iterations: int | None = None,
    ) -> int:
        """Merge clusters that are similar to each other."""
        await self._context.ensure_context()
        entries = await self.repository.get_clusters_with_centroids()
        merger = ClusterMerger(
            session=self.session,
            tenant_id=self.tenant_id,
            refresh_view=self._context.refresh_centroid_view,
            ensure_context=self._context.ensure_context,
        )
        return await merger.merge_similar(
            entries,
            threshold or self.settings.auto_merge_threshold,
            max_iterations or self.settings.auto_merge_max_iterations,
        )

    async def split_cluster(self, cluster_id: UUID, n_clusters: int = 0) -> tuple[list[UUID], list[int]]:
        """
        Split a mixed cluster using hierarchical clustering.

        Args:
            cluster_id: The cluster to split
            n_clusters: Number of clusters to split into.
                       0 = auto-detect based on similarity (default)
                       2+ = force exactly this many clusters

        Returns:
            Tuple of (new_cluster_ids, moved_counts)
        """
        return await self._operations.split_cluster(cluster_id, n_clusters=n_clusters)

    async def assign_identity_to_cluster(
        self,
        identity_id: UUID,
        cluster_id: UUID,
    ) -> None:
        """
        Assign an identity to a cluster (for suggestion acceptance).

        This is used when a user accepts a suggestion to assign an identity
        to a borderline cluster match.

        Args:
            identity_id: The identity to assign
            cluster_id: The target cluster

        Raises:
            ValueError: If identity or cluster not found
        """
        from recognition.application.clustering.centroid_utils import (
            _normalize_vector,
            compute_similarity,
        )

        await self._context.ensure_context()

        identity = await self.session.get(MediaIdentity, identity_id)
        if not identity or identity.tenant_id != self.tenant_id:
            raise ValueError(f"Identity {identity_id} not found for tenant")

        cluster = await self.session.get(IdentityCluster, cluster_id)
        if not cluster or cluster.tenant_id != self.tenant_id:
            raise ValueError(f"Cluster {cluster_id} not found for tenant")

        # Get identity embedding vector
        identity_vector = _normalize_vector(np.array(identity.embedding, dtype=np.float32))

        # Get cluster centroid for similarity calculation
        centroid_stmt = select(ClusterCentroid).where(ClusterCentroid.cluster_id == cluster_id)
        centroid_result = await self.session.execute(centroid_stmt)
        centroid_record = centroid_result.scalar_one_or_none()

        if centroid_record is not None and centroid_record.centroid is not None:
            centroid_vector = _normalize_vector(np.array(centroid_record.centroid, dtype=np.float32))
            similarity = compute_similarity(identity_vector, centroid_vector)
        else:
            similarity = 1.0  # First member

        await self.assigner.assign_to_cluster_by_id(identity, identity_vector, cluster_id, similarity)

        logger.info(
            "Assigned identity %s to cluster %s via suggestion acceptance (similarity=%.4f)",
            identity_id,
            cluster_id,
            similarity,
        )
