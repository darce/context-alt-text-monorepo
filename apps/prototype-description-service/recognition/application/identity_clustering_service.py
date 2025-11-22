"""Clustering service for grouping similar identities using pgvector."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    IdentityCluster,
    IdentityClusteringJob,
    IdentityClusterRepresentative,
    IdentityMember,
    MediaIdentity,
)
from db.tenant_context import set_tenant_context
from recognition.application.centroid_utils import (
    _normalize_vector,
)
from recognition.application.cluster_assignment import ClusterAssigner
from recognition.application.cluster_factory import ClusterFactory
from recognition.application.cluster_management import ClusterMerger, build_cluster_summary
from recognition.application.cluster_repository import ClusterRepository
from recognition.application.clustering_settings import ClusteringSettings
from recognition.application.representative_matcher import RepresentativeMatcher
from recognition.application.representative_selection import decide_representative_acceptance
from recognition.application.ward_clustering import run_ward_clustering
from recognition.config import get_settings

logger = logging.getLogger(__name__)


class ClusterNotFoundError(Exception):
    """Raised when a cluster cannot be found for the current tenant."""


class ClusterLabelConflictError(Exception):
    """Raised when attempting to reuse an existing cluster label."""


class IdentityClusteringService:
    """Cluster similar identities using pgvector cosine similarity."""

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
        self.repository = ClusterRepository(session, tenant_id)
        self.factory = ClusterFactory(session, tenant_id, self.threshold)
        self.assigner = ClusterAssigner(session, tenant_id, self.settings)
        if strict_validation:
            self.assigner.enable_strict_validation()

    def _log_telemetry(self, event: dict[str, object]) -> None:
        """Lightweight structured telemetry via logger."""
        logger.info("clustering_telemetry: %s", event)

    async def _ensure_tenant_context(self) -> None:
        await set_tenant_context(self.session, self.tenant_id)
        # Only enable per-statement logging when explicitly requested; silently skip if not permitted.
        if os.getenv("CLUSTERING_SQL_DEBUG") in {"1", "true", "True"}:
            try:
                await self.session.execute(text("SET LOCAL log_min_duration_statement = 0"))
            except Exception as exc:  # pragma: no cover - best-effort optional debug
                logger.debug("Skipping log_min_duration_statement due to permissions: %s", exc)
                # Rollback the aborted transaction and restart
                await self.session.rollback()
                # Re-establish tenant context after rollback
                await set_tenant_context(self.session, self.tenant_id)
        if os.getenv("ALLOW_RLS_BYPASS_FOR_TESTS") == "1":
            from asyncpg.exceptions import InFailedSQLTransactionError
            from sqlalchemy.exc import DBAPIError

            try:
                await self.session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            except DBAPIError as e:
                # Only rollback if transaction is actually aborted
                if e.orig and isinstance(e.orig.__cause__, InFailedSQLTransactionError):
                    await self.session.rollback()
                    await self.session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
                else:
                    raise

    async def cluster_identities_incremental(self) -> list[IdentityCluster]:
        """
        Cluster unassigned identities by comparing them to existing cluster centroids.
        """
        logger.info("Starting incremental clustering for tenant %s", self.tenant_id)
        self._log_telemetry(
            {
                "stage": "incremental_start",
                "tenant_id": str(self.tenant_id),
            }
        )
        await self._ensure_tenant_context()

        # CRITICAL: Refresh materialized view BEFORE loading existing clusters
        # This ensures clusters from previous batches are available for matching
        await self._refresh_centroid_view()

        existing_clusters = await self.repository.get_clusters_with_centroids()
        representatives_by_cluster = await self.repository.get_clusters_with_representatives()
        unclustered = await self.repository.get_unclustered_identities()

        if not unclustered:
            logger.info("No unclustered identities for tenant %s", self.tenant_id)
            return []

        created_clusters: list[IdentityCluster] = []
        rep_matcher = RepresentativeMatcher(
            threshold=self.threshold,
            add_representative_embedding=self._add_representative_embedding,
            assign_to_cluster_by_id=self._assign_to_cluster_by_id,
        )

        logger.info(
            "=== Clustering batch: %d unclustered identities, %d existing clusters, %d clusters with reps ===",
            len(unclustered),
            len(existing_clusters),
            len(representatives_by_cluster),
        )

        _assigned_via_reps, unclustered, representatives_by_cluster = await rep_matcher.match(
            unclustered,
            representatives_by_cluster,
        )

        logger.info("After initial rep matching: %d identities remaining", len(unclustered))

        for idx, identity in enumerate(unclustered):
            logger.info(
                "--- Processing identity %d/%d: media_id=%s, identity_id=%s ---",
                idx + 1,
                len(unclustered),
                identity.media_id,
                identity.id,
            )
            identity_vector = _normalize_vector(np.array(identity.embedding, dtype=np.float32))

            assigned_count, still_unclustered, representatives_by_cluster = await rep_matcher.match(
                [identity],
                representatives_by_cluster,
            )
            if assigned_count:
                logger.info("✓ Matched to existing cluster via representatives")
                continue

            best_rep_cluster, best_rep_similarity = rep_matcher.best_match(
                identity_vector,
                representatives_by_cluster,
            )
            logger.info(
                "Rep matching: best_cluster=%s, best_similarity=%.4f (threshold=%.4f)",
                best_rep_cluster,
                best_rep_similarity,
                self.threshold,
            )

            centroid_candidates = [
                entry for entry in existing_clusters if entry.cluster.id not in representatives_by_cluster
            ]
            logger.info("Checking %d centroid candidates (clusters without reps)", len(centroid_candidates))

            best_entry, best_similarity = self.assigner.find_best_cluster_match(
                identity_vector,
                centroid_candidates,
            )

            if best_entry and best_similarity >= self.threshold:
                logger.info(
                    "✓ Matched to cluster %s via centroid (similarity=%.4f)",
                    best_entry.cluster.label,
                    best_similarity,
                )
                await self.assigner.assign_to_cluster(identity, identity_vector, best_entry, best_similarity)
                rep_embedding = await self._add_representative_embedding(best_entry.cluster.id, identity)
                if rep_embedding is not None:
                    representatives_by_cluster.setdefault(best_entry.cluster.id, []).append(rep_embedding)
                    logger.debug("Added representative to cluster %s", best_entry.cluster.id)
                logger.debug(
                    "Assigned identity %s to cluster %s (similarity %.3f)",
                    identity.id,
                    best_entry.cluster.label,
                    best_similarity,
                )
            else:
                logger.info(
                    "✗ Creating NEW cluster: best_rep=%.4f, best_centroid=%.4f, threshold=%.4f",
                    best_rep_similarity,
                    best_similarity if best_entry else 0.0,
                    self.threshold,
                )
                logger.info(
                    "Unassigned identity %s (media %s): best_rep=%.3f (cluster=%s), best_centroid=%.3f, threshold=%.3f",
                    identity.id,
                    identity.media_id,
                    best_rep_similarity,
                    best_rep_cluster,
                    best_similarity,
                    self.threshold,
                )
                cluster, entry = await self.factory.create_cluster_with_centroid(
                    [identity],
                    add_representative_callback=self._add_representative_embedding,
                )
                created_clusters.append(cluster)
                existing_clusters.append(entry)
                reps = await self.repository.get_cluster_representatives(cluster.id)
                if reps:
                    representatives_by_cluster[cluster.id] = reps
                    logger.info("New cluster %s has %d representatives", cluster.label, len(reps))
                else:
                    logger.warning("New cluster %s has NO representatives!", cluster.label)
                logger.debug(
                    "Created new cluster %s for identity %s",
                    cluster.label,
                    identity.id,
                )

        logger.info("=== Batch complete: created %d new clusters ===", len(created_clusters))

        await self.session.commit()
        await self._refresh_centroid_view()

        if self.settings.auto_merge_enabled:
            logger.info("Auto-merge enabled, evaluating eligibility...")
            total_identities = sum(entry.member_count for entry in existing_clusters)
            logger.info(
                "Total identities: %d (max for auto-merge: %d)",
                total_identities,
                self.settings.auto_merge_max_identities,
            )
            if total_identities <= self.settings.auto_merge_max_identities:
                logger.info(
                    "Running auto-merge (threshold=%.2f, max_iterations=%d)...",
                    self.settings.auto_merge_threshold,
                    self.settings.auto_merge_max_iterations,
                )
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
                        "total_identities": total_identities,
                    }
                )
            else:
                logger.info(
                    "Skipping auto-merge: %d identities exceeds cap %d",
                    total_identities,
                    self.settings.auto_merge_max_identities,
                )

        logger.info(
            "Incremental clustering complete: %d new clusters",
            len(created_clusters),
        )
        self._log_telemetry(
            {
                "stage": "incremental_complete",
                "tenant_id": str(self.tenant_id),
                "created_clusters": len(created_clusters),
                "remaining_unclustered": len(unclustered),
            }
        )
        return created_clusters

    async def cluster_identities(self) -> list[IdentityCluster]:
        """Backward compatibility shim for legacy callers."""
        return await self.cluster_identities_incremental()

    async def _assign_to_cluster_by_id(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        similarity: float,
    ) -> None:
        """Compatibility wrapper for RepresentativeMatcher callback."""
        await self.assigner.assign_to_cluster_by_id(identity, identity_vector, cluster_id, similarity)

    async def _add_representative_embedding(self, cluster_id: UUID, identity: MediaIdentity) -> np.ndarray | None:
        """
        Add a representative embedding for a cluster with diversity/quality guards.

        Returns the normalized embedding if it was accepted and persisted; otherwise None.
        """

        embedding = _normalize_vector(np.array(identity.embedding, dtype=np.float32))

        existing_reps = await self.repository.get_cluster_representatives(cluster_id)
        existing_from_media = await self.repository.count_representatives_for_media(cluster_id, identity.media_id)

        accept, combined_score, diversity_score = decide_representative_acceptance(
            existing_reps=existing_reps,
            candidate_embedding=embedding,
            quality_score=identity.confidence or 0.0,
            current_media_count=existing_from_media,
            max_reps_per_media=self.settings.max_reps_per_media,
            min_diversity_similarity=self.settings.min_diversity_similarity,
            quality_weight=self.settings.quality_weight,
            diversity_weight=self.settings.diversity_weight,
        )
        if not accept:
            logger.info("Skipping representative for cluster %s media %s", cluster_id, identity.media_id)
            return None

        rep = IdentityClusterRepresentative(
            tenant_id=self.tenant_id,
            cluster_id=cluster_id,
            identity_id=identity.id,
            embedding=embedding.tolist(),
            quality_score=identity.confidence or 0.0,
            diversity_score=diversity_score,
        )
        self.session.add(rep)
        return embedding

    async def _refresh_centroid_view(self) -> None:
        try:
            await self.session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            await self.session.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
        except Exception as exc:  # pragma: no cover - best effort refresh
            logger.warning("Failed to refresh centroid view: %s", exc)
        finally:
            await self.session.execute(text("RESET app.bypass_rls"))

    async def _stage2_batch_clustering(self, identities: list[MediaIdentity]) -> list[IdentityCluster]:
        """Cluster identities using Ward linkage on normalized embeddings."""

        async def create_cluster_wrapper(members: Sequence[MediaIdentity]) -> tuple[IdentityCluster, object]:
            return await self.factory.create_cluster_with_centroid(
                members,
                add_representative_callback=self._add_representative_embedding,
            )

        return await run_ward_clustering(
            identities,
            self.settings,
            create_cluster=create_cluster_wrapper,
            max_identities=self.settings.ward_async_max_identities,
        )

    async def _enqueue_clustering_job(
        self,
        identities: list[MediaIdentity],
        created_by_user_id: int | None = None,
    ) -> IdentityClusteringJob:
        await self._ensure_tenant_context()
        job = await self.repository.create_clustering_job(
            total_identities=len(identities),
            created_by_user_id=created_by_user_id,
        )
        await self.session.commit()
        logger.info(
            "Enqueued clustering job %s for tenant %s (count=%d)",
            job.id,
            self.tenant_id,
            len(identities),
        )
        return job

    async def get_clustering_job(self, job_id: UUID) -> IdentityClusteringJob | None:
        await self._ensure_tenant_context()
        return await self.repository.get_clustering_job(job_id)

    async def process_clustering_job(self, job_id: UUID) -> list[IdentityCluster]:
        """
        Process a queued clustering job (synchronous execution for now).
        In a Celery deployment this would be executed by a worker.
        """

        await self._ensure_tenant_context()
        job = await self.repository.update_clustering_job(
            job_id,
            status="running",
            progress=0.0,
            started_at=datetime.utcnow(),
        )
        if not job:
            raise ClusterNotFoundError(f"Clustering job {job_id} not found")
        logger.info("Processing clustering job %s for tenant %s", job_id, self.tenant_id)

        identities = await self.repository.get_unclustered_identities()
        await self.repository.update_clustering_job(
            job_id,
            total_identities=len(identities),
        )

        try:
            clusters = await self._stage2_batch_clustering(identities)
            await self.repository.update_clustering_job(
                job_id,
                status="completed",
                progress=1.0,
                processed_identities=len(identities),
                completed_at=datetime.utcnow(),
            )
            await self.session.commit()
            await self._refresh_centroid_view()
            if self.settings.auto_merge_enabled:
                total_identities = len(identities)
                if total_identities <= self.settings.auto_merge_max_identities:
                    merges = await self.merge_similar_clusters(
                        threshold=self.settings.auto_merge_threshold,
                        max_iterations=self.settings.auto_merge_max_iterations,
                    )
                    logger.info(
                        "Auto-merge completed for clustering job %s: %d merges",
                        job_id,
                        merges,
                    )
                else:
                    logger.info(
                        "Skipping auto-merge for job %s: %d identities exceeds cap %d",
                        job_id,
                        total_identities,
                        self.settings.auto_merge_max_identities,
                    )
            logger.info(
                "Clustering job %s completed for tenant %s (clusters=%d)",
                job_id,
                self.tenant_id,
                len(clusters),
            )
            return clusters
        except Exception as exc:
            await self.repository.update_clustering_job(
                job_id,
                status="failed",
                error_message=str(exc),
                completed_at=datetime.utcnow(),
            )
            await self.session.commit()
            logger.exception("Clustering job %s failed for tenant %s", job_id, self.tenant_id)
            raise

    async def cluster_identities_hybrid(self) -> dict[str, object]:
        """
        Two-stage clustering:
        - Stage 1: representative matching (online)
        - Stage 2: Ward linkage for remaining identities (sync for ≤100)
        """

        await self._ensure_tenant_context()
        representatives_by_cluster = await self.repository.get_clusters_with_representatives()
        unclustered = await self.repository.get_unclustered_identities()

        rep_matcher = RepresentativeMatcher(
            threshold=self.threshold,
            add_representative_embedding=self._add_representative_embedding,
            assign_to_cluster_by_id=self._assign_to_cluster_by_id,
        )
        assigned_count, remaining, representatives_by_cluster = await rep_matcher.match(
            unclustered,
            representatives_by_cluster,
        )

        if not remaining:
            await self.session.commit()
            await self._refresh_centroid_view()
            return {"status": "complete", "assigned": assigned_count, "clusters": []}

        if len(remaining) <= self.settings.ward_sync_batch_limit:
            clusters = await self._stage2_batch_clustering(remaining)

            # Optionally merge highly similar clusters before returning sync results.
            if self.settings.auto_merge_enabled:
                total_identities = len(remaining)
                if total_identities <= self.settings.auto_merge_max_identities:
                    merges = await self.merge_similar_clusters(
                        threshold=self.settings.auto_merge_threshold,
                        max_iterations=self.settings.auto_merge_max_iterations,
                    )
                    logger.info(
                        "Auto-merge (sync path) completed: %d merges",
                        merges,
                    )
                else:
                    logger.info(
                        "Skipping auto-merge (sync path): %d identities exceeds cap %d",
                        total_identities,
                        self.settings.auto_merge_max_identities,
                    )

            await self.session.commit()
            await self._refresh_centroid_view()
            return {"status": "complete", "assigned": assigned_count, "clusters": clusters}

        logger.info(
            "Routing %d identities to async clustering path (job queued)",
            len(remaining),
        )
        job = await self._enqueue_clustering_job(remaining)
        self._log_telemetry(
            {
                "stage": "async_job_enqueued",
                "tenant_id": str(self.tenant_id),
                "job_id": str(job.id),
                "queued_identities": len(remaining),
            }
        )
        return {
            "status": "pending",
            "assigned": assigned_count,
            "queued_count": len(remaining),
            "job_id": str(job.id),
        }

    async def get_cluster_summary(self, cluster_id: UUID) -> dict[str, object]:
        cluster = await self.session.get(IdentityCluster, cluster_id)
        if not cluster:
            raise ValueError("Cluster not found")

        return await build_cluster_summary(self.session, cluster)

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

        # Move members from source to target
        members_result = await self.session.execute(
            select(IdentityMember).where(IdentityMember.cluster_id == source.id)
        )
        members = members_result.scalars().all()
        for member in members:
            member.cluster_id = target.id
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
        await self._ensure_tenant_context()
        await self._refresh_centroid_view()
        logger.info(
            "Refreshed centroid view after merging cluster %s into %s",
            source_id,
            target.id,
        )

        await self.session.refresh(target)
        return target, moved_count

    async def merge_similar_clusters(
        self,
        threshold: float | None = None,
        max_iterations: int | None = None,
    ) -> int:
        await self._ensure_tenant_context()
        entries = await self.repository.get_clusters_with_centroids()
        merger = ClusterMerger(
            session=self.session,
            tenant_id=self.tenant_id,
            refresh_view=self._refresh_centroid_view,
            ensure_context=self._ensure_tenant_context,
        )
        return await merger.merge_similar(
            entries,
            threshold or self.settings.auto_merge_threshold,
            max_iterations or self.settings.auto_merge_max_iterations,
        )
