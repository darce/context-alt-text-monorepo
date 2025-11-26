"""Clustering service for grouping similar identities using pgvector.

This is a thin orchestrator that delegates to specialized modules:
- TenantContextManager: Database context and view refresh
- RepresentativeManager: Adding representative embeddings
- ClusterValidator: Validation of identity-to-cluster matches
- BatchClusteringProcessor: Batch and centroid-based matching
- ClusteringJobService: Async job management
- ClusterOperations: Rename, merge, revert, split operations
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityClusteringJob
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
from recognition.application.clustering.clustering_logger import (
    log_batch_complete,
    log_batch_start,
    log_cluster_created,
)
from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.clustering.tenant_context import TenantContextManager
from recognition.application.representatives.representative_manager import RepresentativeManager
from recognition.application.representatives.representative_matcher import RepresentativeMatcher
from recognition.config import get_settings
from recognition.domain.embeddings import prepare_embedding

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

    # =========================================================================
    # Main clustering entry points
    # =========================================================================

    async def cluster_identities_incremental(self) -> list[IdentityCluster]:
        """Cluster unassigned identities by comparing them to existing cluster centroids."""
        batch_start_time = time.time()

        logger.info("Starting incremental clustering for tenant %s", self.tenant_id)
        self._log_telemetry({"stage": "incremental_start", "tenant_id": str(self.tenant_id)})
        await self._context.ensure_context()

        # Refresh and load existing clusters
        await self._context.refresh_centroid_view()
        existing_clusters = await self.repository.get_clusters_with_centroids()
        self._centroid_cache = existing_clusters
        self._validator.set_centroid_cache(existing_clusters)
        representatives_by_cluster = await self.repository.get_clusters_with_representatives()
        unclustered = await self.repository.get_unclustered_identities()

        if not unclustered:
            logger.info("No unclustered identities for tenant %s", self.tenant_id)
            return []

        log_batch_start(
            tenant_id=self.tenant_id,
            batch_size=len(unclustered),
            existing_clusters=len(existing_clusters),
            algorithm="incremental",
        )

        created_clusters: list[IdentityCluster] = []
        rep_matcher = self._create_representative_matcher()

        logger.info(
            "=== Clustering batch: %d unclustered, %d existing clusters, %d with reps ===",
            len(unclustered),
            len(existing_clusters),
            len(representatives_by_cluster),
        )

        # Initial representative matching
        borderline_upper = self._get_borderline_upper()
        _, unclustered, representatives_by_cluster = await rep_matcher.match(
            unclustered, representatives_by_cluster, borderline_upper=borderline_upper
        )

        logger.info("After initial rep matching: %d identities remaining", len(unclustered))

        # Process remaining identities one by one
        for idx, identity in enumerate(unclustered):
            logger.info(
                "--- Processing identity %d/%d: media_id=%s ---",
                idx + 1,
                len(unclustered),
                identity.media_id,
            )
            identity_vector = prepare_embedding(identity.embedding)

            # Try representative matching
            assigned_count, _, representatives_by_cluster = await rep_matcher.match(
                [identity], representatives_by_cluster, borderline_upper=borderline_upper
            )
            if assigned_count:
                logger.info("Assigned via representative match")
                continue

            # Try centroid matching for clusters without representatives
            centroid_candidates = [e for e in existing_clusters if e.cluster.id not in representatives_by_cluster]
            best_entry, best_similarity = self.assigner.find_best_cluster_match(identity_vector, centroid_candidates)

            if best_entry and best_similarity >= self.threshold:
                logger.info("✓ Matched via centroid (similarity=%.4f)", best_similarity)
                await self.assigner.assign_to_cluster(identity, identity_vector, best_entry, best_similarity)
                rep_embedding = await self._rep_manager.add_representative(best_entry.cluster.id, identity)
                if rep_embedding is not None:
                    representatives_by_cluster.setdefault(best_entry.cluster.id, []).append(rep_embedding)
            else:
                # Create new cluster
                logger.info("✗ Creating NEW cluster")
                cluster, entry = await self.factory.create_cluster_with_centroid(
                    [identity],
                    add_representative_callback=self._rep_manager.add_representative,
                )
                created_clusters.append(cluster)
                existing_clusters.append(entry)
                reps = await self.repository.get_cluster_representatives(cluster.id)
                if reps:
                    representatives_by_cluster[cluster.id] = reps

                log_cluster_created(
                    tenant_id=self.tenant_id,
                    cluster_id=cluster.id,
                    member_count=1,
                    algorithm="incremental",
                )

        logger.info("=== Batch complete: created %d new clusters ===", len(created_clusters))

        await self.session.commit()
        await self._context.refresh_centroid_view()

        # Log metrics
        batch_duration_ms = (time.time() - batch_start_time) * 1000
        singleton_count = sum(1 for c in created_clusters if c.identity_count == 1)
        log_batch_complete(
            tenant_id=self.tenant_id,
            batch_size=len(unclustered),
            assigned_count=len(unclustered) - len(created_clusters),
            created_count=len(created_clusters),
            singleton_count=singleton_count,
            duration_ms=batch_duration_ms,
            algorithm="incremental",
        )

        # Auto-merge if enabled
        await self._run_auto_merge_if_enabled(existing_clusters)

        logger.info("Incremental clustering complete: %d new clusters", len(created_clusters))
        self._log_telemetry(
            {
                "stage": "incremental_complete",
                "tenant_id": str(self.tenant_id),
                "created_clusters": len(created_clusters),
            }
        )
        return created_clusters

    async def cluster_identities(self) -> list[IdentityCluster]:
        """Backward compatibility shim for legacy callers."""
        return await self.cluster_identities_incremental()

    async def cluster_identities_hybrid(self) -> dict[str, object]:
        """Two-stage clustering with sync/async routing."""
        await self._context.ensure_context()

        unclustered_count = await self.repository.count_unclustered_identities()

        if unclustered_count == 0:
            return {"status": "complete", "assigned": 0, "clusters": []}

        if unclustered_count <= self.settings.ward_sync_batch_limit:
            # Sync path
            unclustered = await self.repository.get_unclustered_identities()
            clusters = await self._batch_processor.cluster_batch_incremental(unclustered)
            await self._run_auto_merge_if_enabled([])
            await self.session.commit()
            await self._context.refresh_centroid_view()
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

    def _create_representative_matcher(self) -> RepresentativeMatcher:
        """Create a RepresentativeMatcher with current settings."""
        return RepresentativeMatcher(
            threshold=self.threshold,
            add_representative_embedding=self._rep_manager.add_representative,
            assign_to_cluster_by_id=self.assigner.assign_to_cluster_by_id,
            borderline_validation=(
                self._validator.validate_representative_match
                if (self.settings.borderline_validation_enabled or self.settings.member_validation_enabled)
                else None
            ),
            settings=self.settings,
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

    async def split_cluster(self, cluster_id: UUID) -> tuple[UUID | None, int]:
        """Split a mixed cluster using DBSCAN."""
        return await self._operations.split_cluster(cluster_id)
