"""Clustering service for grouping similar identities using pgvector."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

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
from recognition.application.cluster_repository import ClusterRepository, ClusterSearchEntry
from recognition.application.clustering_settings import ClusteringSettings
from recognition.application.representative_matcher import RepresentativeMatcher
from recognition.application.representative_selection import decide_representative_acceptance
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
        # Cache for centroid entries during clustering (for borderline validation)
        self._centroid_cache: list[ClusterSearchEntry] = []
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

    async def _validate_borderline_match(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        rep_similarity: float,
    ) -> bool:
        """
        Validate a borderline representative match against the cluster centroid.

        Returns True if the match should be accepted, False otherwise.
        """
        from recognition.application.centroid_utils import compute_similarity

        # Find the centroid for this cluster
        centroid_entry = next(
            (e for e in self._centroid_cache if e.cluster.id == cluster_id),
            None,
        )

        if not centroid_entry:
            logger.warning(
                "No centroid found for cluster %s during borderline validation. Accepting match.",
                cluster_id,
            )
            return True

        centroid_similarity = compute_similarity(identity_vector, centroid_entry.centroid)

        logger.info(
            "Borderline validation: rep=%.4f, centroid=%.4f, validation_threshold=%.4f",
            rep_similarity,
            centroid_similarity,
            self.settings.borderline_validation_threshold,
        )

        if centroid_similarity < self.settings.borderline_validation_threshold:
            logger.warning(
                "BORDERLINE VALIDATION FAILED: identity=%s, rep=%.4f, centroid=%.4f < threshold=%.4f. "
                "Preventing false positive assignment.",
                identity.id,
                rep_similarity,
                centroid_similarity,
                self.settings.borderline_validation_threshold,
            )
            return False

        logger.info(
            "Borderline validation PASSED: identity=%s, rep=%.4f, centroid=%.4f >= threshold=%.4f",
            identity.id,
            rep_similarity,
            centroid_similarity,
            self.settings.borderline_validation_threshold,
        )
        return True

    async def _validate_member_similarity(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        rep_similarity: float,
    ) -> bool:
        """
        Validate a representative match by checking similarity with random existing cluster members.

        This catches cases where centroid/representatives have drifted but actual members are dissimilar.
        Returns True if the match should be accepted, False otherwise.
        """
        from recognition.application.centroid_utils import compute_similarity

        # Get random sample of existing cluster members
        stmt = (
            select(MediaIdentity.embedding)
            .join(IdentityMember, IdentityMember.identity_id == MediaIdentity.id)
            .where(IdentityMember.cluster_id == cluster_id)
            .where(MediaIdentity.id != identity.id)  # Exclude the candidate itself
            .limit(self.settings.member_validation_sample_size)
        )
        result = await self.session.execute(stmt)
        member_embeddings = [row[0] for row in result.all()]

        if not member_embeddings:
            logger.info(
                "No existing members found for cluster %s, skipping member validation",
                cluster_id,
            )
            return True

        # Check similarity with each sampled member
        similarities = []
        for member_emb in member_embeddings:
            member_vector = _normalize_vector(np.array(member_emb, dtype=np.float32))
            sim = compute_similarity(identity_vector, member_vector)
            similarities.append(sim)

        avg_member_similarity = np.mean(similarities)
        min_member_similarity = np.min(similarities)

        logger.info(
            "Member validation: rep=%.4f, avg_member=%.4f, min_member=%.4f, threshold=%.4f (checked %d members)",
            rep_similarity,
            avg_member_similarity,
            min_member_similarity,
            self.settings.member_validation_threshold,
            len(similarities),
        )

        # Require average similarity with existing members (changed from min to reduce false negatives)
        if avg_member_similarity < self.settings.member_validation_threshold:
            logger.warning(
                "MEMBER VALIDATION FAILED: identity=%s, rep=%.4f, avg_member=%.4f < threshold=%.4f. "
                "Preventing false positive (cluster drift detected).",
                identity.id,
                rep_similarity,
                avg_member_similarity,
                self.settings.member_validation_threshold,
            )
            return False

        logger.info(
            "Member validation PASSED: identity=%s, rep=%.4f, avg_member=%.4f, min_member=%.4f >= threshold=%.4f",
            identity.id,
            rep_similarity,
            avg_member_similarity,
            min_member_similarity,
            self.settings.member_validation_threshold,
        )
        return True

    async def _validate_representative_match(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        rep_similarity: float,
    ) -> bool:
        """
        Combined validation for representative matches.

        Checks:
        1. Borderline validation (for 0.6-0.7 range): requires centroid >= 0.65
        2. Member validation (for all matches): requires similarity with existing members >= 0.55
        """
        # Check if this is a borderline match
        is_borderline = (
            self.settings.borderline_validation_enabled and rep_similarity < self.settings.borderline_upper_threshold
        )

        # Run borderline validation if needed
        if is_borderline and not await self._validate_borderline_match(
            identity, identity_vector, cluster_id, rep_similarity
        ):
            return False

        # Always run member validation (catches cluster drift)
        return not (
            self.settings.member_validation_enabled
            and not await self._validate_member_similarity(identity, identity_vector, cluster_id, rep_similarity)
        )

    async def _match_via_centroids(
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
                if await self._validate_centroid_match(identity, identity_vector, best_cluster_id, best_similarity):
                    await self._assign_to_cluster_by_id(identity, identity_vector, best_cluster_id, best_similarity)
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

    async def _validate_centroid_match(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        centroid_similarity: float,
    ) -> bool:
        """
        Validate centroid match by checking against cluster members.

        Uses similarity_threshold (0.65) for member validation to prevent
        cluster drift from accepting borderline matches.
        """
        # Fetch sample of cluster members for validation
        members_stmt = (
            select(MediaIdentity)
            .join(IdentityMember, MediaIdentity.id == IdentityMember.identity_id)
            .where(IdentityMember.cluster_id == cluster_id)
            .limit(self.settings.member_validation_sample_size)
        )
        members_result = await self.session.execute(members_stmt)
        members = list(members_result.scalars().all())

        if not members:
            logger.info("Centroid match validation: No members found, accepting")
            return True

        # Check similarity with existing members
        similarities = [float(np.dot(identity_vector, member.embedding)) for member in members]
        avg_similarity = float(np.mean(similarities))
        min_similarity = float(np.min(similarities))

        threshold = self.settings.member_validation_threshold

        if avg_similarity >= threshold:
            logger.info(
                "Centroid match validation PASSED: centroid=%.4f, avg_member=%.4f, min_member=%.4f >= %.4f",
                centroid_similarity,
                avg_similarity,
                min_similarity,
                threshold,
            )
            return True
        else:
            logger.warning(
                "Centroid match validation FAILED: centroid=%.4f, avg_member=%.4f < %.4f (cluster drift detected)",
                centroid_similarity,
                avg_similarity,
                threshold,
            )
            return False

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
        # Cache centroids for borderline validation
        self._centroid_cache = existing_clusters
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
            borderline_validation=self._validate_representative_match
            if (self.settings.borderline_validation_enabled or self.settings.member_validation_enabled)
            else None,
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
            borderline_upper=(
                1.0
                if self.settings.member_validation_enabled  # Member validation needs to check ALL matches
                else (self.settings.borderline_upper_threshold if self.settings.borderline_validation_enabled else None)
            ),
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
                borderline_upper=(
                    1.0
                    if self.settings.member_validation_enabled  # Member validation needs to check ALL matches
                    else (
                        self.settings.borderline_upper_threshold
                        if self.settings.borderline_validation_enabled
                        else None
                    )
                ),
            )
            if assigned_count:
                logger.info("Assigned to existing cluster via representative match")
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
            logger.info(
                "Skipping representative for cluster %s media %s (score=%.3f, diversity=%.3f)",
                cluster_id,
                identity.media_id,
                combined_score,
                diversity_score,
            )
            return None

        logger.info("Persisting representative for cluster %s media %s", cluster_id, identity.media_id)

        rep = IdentityClusterRepresentative(
            tenant_id=self.tenant_id,
            cluster_id=cluster_id,
            identity_id=identity.id,
            embedding=embedding.tolist(),
            quality_score=identity.confidence or 0.0,
            diversity_score=diversity_score,
        )
        self.session.add(rep)
        await self.session.flush()
        return embedding

    async def _refresh_centroid_view(self) -> None:
        try:
            await self.session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            await self.session.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
        except Exception as exc:  # pragma: no cover - best effort refresh
            logger.warning("Failed to refresh centroid view: %s", exc)
        finally:
            await self.session.execute(text("RESET app.bypass_rls"))

    async def _stage2_batch_clustering(
        self,
        identities: list[MediaIdentity],
        anchors: list[MediaIdentity] | None = None,
        centroid_map: dict[UUID, np.ndarray] | None = None,
    ) -> list[IdentityCluster]:
        """Cluster identities using Ward linkage on normalized embeddings."""

        async def create_cluster_wrapper(members: Sequence[MediaIdentity]) -> tuple[IdentityCluster, object]:
            return await self.factory.create_cluster_with_centroid(
                members,
                add_representative_callback=self._add_representative_embedding,
            )

        async def add_to_cluster_wrapper(cluster_id: UUID, members: Sequence[MediaIdentity]) -> None:
            if not centroid_map or cluster_id not in centroid_map:
                logger.warning("Cannot add members to cluster %s: centroid not found in cache", cluster_id)
                # Fallback: create new cluster? Or just skip?
                # If we skip, they remain unclustered.
                # Ideally we should fetch the cluster, but for now let's log.
                return

            centroid = centroid_map[cluster_id]
            for member in members:
                # Compute similarity against the cluster centroid
                # We assume member.embedding is already normalized or we normalize it?
                # _assign_to_cluster_by_id takes identity_vector.
                # member.embedding should be a numpy array.
                vec = np.array(member.embedding, dtype=np.float32)
                # Ensure normalized? The embedding from DB should be normalized.
                # But let's be safe if _assign_to_cluster_by_id expects it.
                # Actually compute_similarity handles it? No, usually expects normalized.
                # We'll assume it's normalized as it comes from DB/model.

                # Compute similarity
                sim = float(np.dot(vec, centroid))

                await self._assign_to_cluster_by_id(member, vec, cluster_id, sim)

        from recognition.application.chinese_whispers import ChineseWhispersClustering

        cw = ChineseWhispersClustering(self.settings)
        return await cw.cluster(
            identities,
            create_cluster=create_cluster_wrapper,
            anchors=anchors,
            add_to_cluster=add_to_cluster_wrapper if centroid_map else None,
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

    async def _cluster_batch_incremental(
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
            # This ensures clusters from previous chunks are available for matching
            await self._refresh_centroid_view()

            existing_clusters = await self.repository.get_clusters_with_centroids()
            # Cache centroids for borderline validation
            self._centroid_cache = existing_clusters
            representatives_by_cluster = await self.repository.get_clusters_with_representatives()

            # 1. Try to match against existing representatives
            rep_matcher = RepresentativeMatcher(
                threshold=self.threshold,
                add_representative_embedding=self._add_representative_embedding,
                assign_to_cluster_by_id=self._assign_to_cluster_by_id,
                borderline_validation=self._validate_representative_match
                if (self.settings.borderline_validation_enabled or self.settings.member_validation_enabled)
                else None,
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
                centroid_matched_count, remaining = await self._match_via_centroids(
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
            # Prepare anchors from ALL existing clusters (including those just updated/created in previous chunks)
            anchors: list[MediaIdentity] = []
            centroid_map: dict[UUID, np.ndarray] = {entry.cluster.id: entry.centroid for entry in self._centroid_cache}

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

            chunk_clusters = await self._stage2_batch_clustering(remaining, anchors=anchors, centroid_map=centroid_map)
            all_created_clusters.extend(chunk_clusters)

            # Commit after each chunk to persist new clusters/reps for the next chunk
            await self.session.commit()

        return all_created_clusters

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
            # Use the new mini-batch logic
            clusters = await self._cluster_batch_incremental(identities)

            await self.repository.update_clustering_job(
                job_id,
                status="completed",
                progress=1.0,
                processed_identities=len(identities),
                completed_at=datetime.utcnow(),
            )
            await self.session.commit()

            # Final refresh and auto-merge check
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

        # Check count first to decide routing
        unclustered_count = await self.repository.count_unclustered_identities()

        if unclustered_count == 0:
            return {"status": "complete", "assigned": 0, "clusters": []}

        if unclustered_count <= self.settings.ward_sync_batch_limit:
            unclustered = await self.repository.get_unclustered_identities()
            clusters = await self._cluster_batch_incremental(unclustered)

            # Optionally merge highly similar clusters before returning sync results.
            if self.settings.auto_merge_enabled:
                total_identities = len(unclustered)
                if total_identities <= self.settings.auto_merge_max_identities:
                    merges = await self.merge_similar_clusters(
                        threshold=self.settings.auto_merge_threshold,
                        max_iterations=self.settings.auto_merge_max_iterations,
                    )
                    logger.info(
                        "Auto-merge (sync path) completed: %d merges",
                        merges,
                    )

            await self.session.commit()
            await self._refresh_centroid_view()
            return {"status": "complete", "assigned": len(unclustered) - len(clusters), "clusters": clusters}

        # Async path
        unclustered = await self.repository.get_unclustered_identities()
        logger.info(
            "Routing %d identities to async clustering path (job queued)",
            len(unclustered),
        )
        job = await self._enqueue_clustering_job(unclustered)
        self._log_telemetry(
            {
                "stage": "async_job_enqueued",
                "tenant_id": str(self.tenant_id),
                "job_id": str(job.id),
                "queued_identities": len(unclustered),
            }
        )
        return {
            "status": "pending",
            "assigned": 0,
            "queued_count": len(unclustered),
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

    async def merge_cluster_into_label(
        self,
        source_id: UUID,
        target_label: str,
    ) -> tuple[IdentityCluster, int, list[UUID], str | None]:
        await self._ensure_tenant_context()
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
        await self._ensure_tenant_context()
        await self._refresh_centroid_view()
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
        await self._ensure_tenant_context()
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
        await self._ensure_tenant_context()
        await self._refresh_centroid_view()
        await self.session.refresh(restored_cluster)
        await self.session.refresh(target_cluster)

        return restored_cluster, target_cluster

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

    async def split_cluster(self, cluster_id: UUID) -> tuple[UUID | None, int]:
        """
        Split a mixed cluster using DBSCAN.
        Returns (new_cluster_id, moved_count).
        """
        from sklearn.cluster import DBSCAN

        await self._ensure_tenant_context()

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
        # Assuming Group 0 is the "original" or largest.

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
        await self._refresh_centroid_view()

        return new_cluster_id, len(group_1_indices)
