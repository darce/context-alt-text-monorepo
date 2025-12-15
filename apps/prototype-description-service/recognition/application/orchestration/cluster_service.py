"""
ClusterService orchestrates discovery, gate evaluation, and assignment writes.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

import numpy as np
from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusteringJob
from db.models import IdentityMember as MemberModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.assignment import AssignmentCandidate, AssignmentGate, AssignmentOutcome
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.observability import ClusteringLogger, DecisionType
from recognition.observability.reports import BatchJobReport
from recognition.shared.ids import generate_id

logger = logging.getLogger(__name__)


class SuggestionService(Protocol):
    """Protocol for creating assignment suggestions."""

    async def create(self, candidate: AssignmentCandidate, confidence: float | None = None) -> None:
        """Create a suggestion record for later human review."""


class ClusterService:
    """Coordinates discovery outputs, gate evaluation, and persistence."""

    def __init__(
        self,
        gate: AssignmentGate,
        representative_discovery: RepresentativeDiscovery,
        centroid_discovery: CentroidDiscovery,
        graph_discovery: GraphDiscovery,
        assignment_writer: AssignmentWriter,
        suggestion_service: SuggestionService,
        logger: ClusteringLogger | None = None,
        visualizer=None,
        decision_store=None,
        observability_repo=None,
        session: AsyncSession | None = None,
    ) -> None:
        self.gate = gate
        self.representative_discovery = representative_discovery
        self.centroid_discovery = centroid_discovery
        self.graph_discovery = graph_discovery
        self.assignment_writer = assignment_writer
        self.suggestion_service = suggestion_service
        self.logger = logger
        self.visualizer = visualizer
        self.decision_store = decision_store
        self.observability_repo = observability_repo
        self._session = session

    async def cluster(
        self,
        identities: Iterable,
        representatives_by_cluster: object,
        centroids_by_cluster: object,
        anchor_embeddings: object,
        session: AsyncSession | None = None,
    ) -> None:
        """Run discovery across all paths and route candidates through the gate."""
        identity_list = list(identities)
        job_id = str(generate_id())
        algorithm_label = "hybrid"
        report = BatchJobReport(
            job_id=job_id,
            algorithm=algorithm_label,
            started_at=datetime.now(tz=UTC),
            completed_at=None,
            total_identities=len(identity_list),
            accept_count=0,
            suggest_count=0,
            reject_count=0,
            clusters_created=0,
            avg_similarity=None,
        )
        tenant_id = identity_list[0].tenant_id if identity_list else None
        if self.logger:
            self.logger.log_batch_start(
                identity_count=len(identity_list), algorithm=algorithm_label, tenant_id=tenant_id
            )

        rep_candidates = await self.representative_discovery.discover(identity_list, representatives_by_cluster)
        remaining_ids = {c.identity.id for c in rep_candidates}
        remaining = [i for i in identity_list if i.id not in remaining_ids]

        centroid_candidates = await self.centroid_discovery.discover(remaining, centroids_by_cluster)
        centroid_remaining = {c.identity.id for c in centroid_candidates}
        remaining = [i for i in remaining if i.id not in centroid_remaining]

        graph_result = await self.graph_discovery.discover(remaining, anchor_embeddings)
        graph_candidates = graph_result.candidates
        new_clusters = graph_result.new_clusters

        all_candidates = rep_candidates + centroid_candidates + graph_candidates
        report.clusters_created = len({c.cluster_id for c in all_candidates})

        async def _persist_candidates() -> None:
            for candidate in all_candidates:
                decision = await self.gate.evaluate(candidate)
                if decision.outcome is AssignmentOutcome.ACCEPT:
                    await self.assignment_writer.persist_assignment(decision)
                    await self._log_decision(decision)
                elif decision.outcome is AssignmentOutcome.SUGGEST:
                    await self.suggestion_service.create(candidate, decision.suggestion_confidence)
                    await self._log_decision(decision)
                else:
                    await self._log_decision(decision)

                report.add_decision(decision.outcome.value, candidate.discovery_similarity)

        if session:
            async with session.begin():
                await _persist_candidates()
                await self._persist_new_clusters(new_clusters, algorithm_label)
        else:
            await _persist_candidates()
            await self._persist_new_clusters(new_clusters, algorithm_label)

        # Refresh centroids view if possible
        refresh = getattr(self.assignment_writer, "refresh_centroids_view", None)
        if callable(refresh):
            await refresh()

        report.completed_at = datetime.now(tz=UTC)
        if self.logger:
            self.logger.log_batch_complete(report)
        if self.visualizer:
            with contextlib.suppress(Exception):
                self.visualizer.generate_batch_report_chart(
                    report, algorithm=algorithm_label, timestamp=report.completed_at
                )
        if self.observability_repo and tenant_id:
            with contextlib.suppress(Exception):
                await self.observability_repo.save_batch_report(report, tenant_id=str(tenant_id))

    async def _log_decision(self, decision) -> None:
        """Log and persist a decision if configured."""
        if not self.logger:
            return
        decision_type = {
            AssignmentOutcome.ACCEPT: DecisionType.ACCEPT,
            AssignmentOutcome.SUGGEST: DecisionType.SUGGEST,
            AssignmentOutcome.REJECT: DecisionType.REJECT,
        }[decision.outcome]
        decision_log = self.logger.log_decision(
            identity_id=decision.candidate.identity.id,
            cluster_id=decision.candidate.cluster_id,
            decision=decision_type,
            similarity=decision.candidate.discovery_similarity,
            reason=decision.rejection_reason,
            metadata=decision.metadata,
            algorithm="hybrid",
            job_id=None,
            media_id=getattr(decision.candidate.identity, "media_id", None),
        )
        if self.decision_store:
            with contextlib.suppress(Exception):
                self.decision_store.add(
                    {
                        "id": decision_log.identity_id,
                        "tenant_id": getattr(decision.candidate.identity, "tenant_id", None),
                        "cluster_id": decision_log.cluster_id,
                        "decision": decision_log.decision.value,
                        "similarity": decision_log.similarity,
                        "reason": decision_log.reason,
                        "timestamp": decision_log.timestamp.isoformat(),
                    }
                )
        if self.observability_repo:
            with contextlib.suppress(Exception):
                await self.observability_repo.add_decision(
                    decision_log,
                    tenant_id=getattr(decision.candidate.identity, "tenant_id", None),
                    algorithm="hybrid",
                    job_id=None,
                    metadata=decision.metadata or {},
                )

    async def _persist_new_clusters(
        self,
        clusters: list[tuple[list, list[float]]],
        algorithm_label: str,
    ) -> None:
        """Persist newly formed clusters from graph discovery."""
        for members, similarities in clusters:
            if not members:
                continue
            tenant_id = getattr(members[0], "tenant_id", None)
            if tenant_id is None:
                continue
            await self.assignment_writer.persist_new_cluster(
                tenant_id=tenant_id,
                identities=members,
                similarities=similarities,
                algorithm=algorithm_label,
            )

    async def cluster_unclustered_identities(self, tenant_id: str, job_id: str | None = None):
        """Cluster any identities not yet assigned to a cluster."""
        if job_id is None:
            job_id = str(generate_id())
        logger.info(
            "[clustering] batch_start job_id=%s tenant_id=%s",
            job_id,
            tenant_id,
        )
        started_at = datetime.now(tz=UTC)

        if self._session is None:
            logger.warning("[clustering] No session available, returning early")
            finished_at = started_at
            return type(
                "ClusterJobResult",
                (),
                {
                    "job_id": job_id,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "completed": 0,
                    "total": 0,
                    "clusters_created": 0,
                },
            )()

        try:
            # Handle both UUID format and MD5 hash format (32 hex chars without dashes)
            tenant_str = str(tenant_id).replace("-", "")
            if len(tenant_str) == 32:
                # Insert dashes to make it a valid UUID format
                formatted = (
                    f"{tenant_str[:8]}-{tenant_str[8:12]}-{tenant_str[12:16]}-{tenant_str[16:20]}-{tenant_str[20:]}"
                )
                tenant_uuid = uuid.UUID(formatted)
            else:
                tenant_uuid = uuid.UUID(str(tenant_id))
        except ValueError as e:
            logger.error("[clustering] Invalid tenant_id format: %s, error=%s", tenant_id, e)
            finished_at = started_at
            return type(
                "ClusterJobResult",
                (),
                {
                    "job_id": job_id,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "completed": 0,
                    "total": 0,
                    "clusters_created": 0,
                },
            )()

        # Fetch existing clusters for discovery inputs (representatives/centroids)
        await self.assignment_writer._clusters.get_by_tenant(str(tenant_id), limit=1000, offset=0)

        clustering_job = IdentityClusteringJob(
            tenant_id=tenant_uuid,
            status="running",
            started_at=started_at,
            progress=0.0,
            total_identities=0,
            processed_identities=0,
        )
        self._session.add(clustering_job)
        await self._session.flush()

        stmt: Select[tuple[MediaIdentityModel]] = (
            select(MediaIdentityModel)
            .where(MediaIdentityModel.tenant_id == tenant_uuid)
            .where(~exists(select(MemberModel.id).where(MemberModel.identity_id == MediaIdentityModel.id)))
        )
        result = await self._session.execute(stmt)
        unclustered = result.scalars().all()

        if not unclustered:
            clustering_job.status = "completed"
            clustering_job.progress = 1.0
            clustering_job.completed_at = datetime.now(tz=UTC)
            finished_at = clustering_job.completed_at
            job_label = str(clustering_job.id)
            await self._session.flush()
            await self._session.commit()
            return type(
                "ClusterJobResult",
                (),
                {
                    "job_id": job_label,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "completed": 0,
                    "total": 0,
                    "clusters_created": 0,
                },
            )()

        domain_identities = [
            MediaIdentity(
                id=str(row.id),
                tenant_id=str(row.tenant_id),
                media_id=str(row.media_id),
                embedding=np.array(row.embedding, dtype=np.float32),
                confidence=row.confidence,
                bbox_width=row.bbox_width,
                bbox_height=row.bbox_height,
            )
            for row in unclustered
        ]

        # Log all media IDs in this batch
        media_ids = [i.media_id for i in domain_identities]
        logger.info(
            "[clustering] batch_processing job_id=%s count=%d media_ids=%s",
            job_id,
            len(domain_identities),
            media_ids[:20] if len(media_ids) > 20 else media_ids,  # Limit to first 20 for log readability
        )

        total_identities = len(domain_identities)
        clustering_job.total_identities = total_identities
        clustering_job.processed_identities = 0
        clustering_job.progress = 0.0
        await self._session.flush()

        # Process higher-confidence faces first to seed good representatives early.
        domain_identities.sort(key=lambda identity: identity.confidence, reverse=True)

        accept_count = 0
        suggest_count = 0
        reject_count = 0
        clusters_created = 0
        processed = 0
        remaining_identities = list(domain_identities)

        while remaining_identities:
            chunk_size = self._get_chunk_size(processed)
            chunk = remaining_identities[:chunk_size]
            remaining_identities = remaining_identities[chunk_size:]

            logger.info(
                "[clustering] chunk_processing job_id=%s processed=%d/%d chunk_size=%d",
                job_id,
                processed,
                total_identities,
                len(chunk),
            )

            # ============================================================
            # Gather cluster data for discovery algorithms (refresh each chunk)
            # ============================================================
            existing_clusters = await self.assignment_writer._clusters.get_by_tenant(
                str(tenant_id), limit=1000, offset=0
            )
            logger.info("[clustering] Found %d existing clusters for discovery", len(existing_clusters))

            representatives_by_cluster: dict[str, list[np.ndarray]] = {}
            labeled_cluster_ids: set[str] = set()

            for cluster in existing_clusters:
                if cluster.id is None:
                    continue

                is_user_labeled = cluster.user_confirmed or (cluster.label and not cluster.label.startswith("cluster-"))
                if is_user_labeled:
                    labeled_cluster_ids.add(cluster.id)

                reps = getattr(cluster, "representatives", []) or []
                if reps:
                    representatives_by_cluster[cluster.id] = [
                        np.array(r.embedding, dtype=np.float32) for r in reps if r.embedding is not None
                    ]

            centroids_by_cluster: dict[str, np.ndarray] = {}
            for cluster in existing_clusters:
                if cluster.id is None:
                    continue
                centroid = getattr(cluster, "centroid", None)
                if centroid is not None:
                    centroids_by_cluster[cluster.id] = np.array(centroid, dtype=np.float32)

            anchor_embeddings = representatives_by_cluster

            # ============================================================
            # UNIFIED PIPELINE (chunked): Discovery -> Gate -> Writer
            # ============================================================
            rep_candidates = await self.representative_discovery.discover(
                chunk,
                representatives_by_cluster,
                labeled_cluster_ids=labeled_cluster_ids,
            )
            matched_ids = {c.identity.id for c in rep_candidates}
            chunk_remaining = [i for i in chunk if i.id not in matched_ids]
            logger.info(
                "[clustering] RepresentativeDiscovery: %d candidates, %d remaining",
                len(rep_candidates),
                len(chunk_remaining),
            )

            centroid_candidates = await self.centroid_discovery.discover(chunk_remaining, centroids_by_cluster)
            centroid_matched_ids = {c.identity.id for c in centroid_candidates}
            chunk_remaining = [i for i in chunk_remaining if i.id not in centroid_matched_ids]
            logger.info(
                "[clustering] CentroidDiscovery: %d candidates, %d remaining",
                len(centroid_candidates),
                len(chunk_remaining),
            )

            augmented_anchors = (
                {k: list(v) for k, v in anchor_embeddings.items()} if isinstance(anchor_embeddings, dict) else {}
            )
            for candidate in rep_candidates + centroid_candidates:
                if candidate.cluster_id and candidate.identity.embedding is not None:
                    augmented_anchors.setdefault(candidate.cluster_id, []).append(
                        np.asarray(candidate.identity.embedding, dtype=np.float32)
                    )

            graph_result = await self.graph_discovery.discover(chunk_remaining, augmented_anchors)
            graph_candidates = graph_result.candidates
            new_cluster_proposals = graph_result.new_clusters
            logger.info(
                "[clustering] GraphDiscovery: %d candidates, %d new cluster proposals",
                len(graph_candidates),
                len(new_cluster_proposals),
            )

            all_candidates = rep_candidates + centroid_candidates + graph_candidates
            logger.info("[clustering] Total candidates to evaluate through gate: %d", len(all_candidates))

            accepted_ids: set[str] = set()
            suggested_ids: set[str] = set()
            rejected_ids: set[str] = set()

            for candidate in all_candidates:
                decision = await self.gate.evaluate(candidate)
                logger.info(
                    "[clustering] Gate decision for identity %s -> cluster %s: %s (checks passed: %s, failed: %s)",
                    candidate.identity.id,
                    candidate.cluster_id,
                    decision.outcome.value,
                    decision.checks_passed,
                    decision.checks_failed,
                )

                if decision.outcome == AssignmentOutcome.ACCEPT:
                    await self.assignment_writer.persist_assignment(decision)
                    accept_count += 1
                    accepted_ids.add(candidate.identity.id)
                    logger.info(
                        "[clustering] ACCEPTED job_id=%s identity=%s media_id=%s cluster=%s",
                        job_id,
                        candidate.identity.id,
                        candidate.identity.media_id,
                        candidate.cluster_id,
                    )
                elif decision.outcome == AssignmentOutcome.SUGGEST:
                    await self.suggestion_service.create(candidate, decision.suggestion_confidence)
                    suggest_count += 1
                    suggested_ids.add(candidate.identity.id)
                    logger.info(
                        "[clustering] SUGGESTED job_id=%s identity=%s media_id=%s cluster=%s confidence=%.2f reason=%s",
                        job_id,
                        candidate.identity.id,
                        candidate.identity.media_id,
                        candidate.cluster_id,
                        decision.suggestion_confidence or 0.0,
                        decision.rejection_reason,
                    )
                else:  # REJECT
                    reject_count += 1
                    rejected_ids.add(candidate.identity.id)
                    logger.info(
                        "[clustering] REJECTED job_id=%s identity=%s media_id=%s cluster=%s reason=%s",
                        job_id,
                        candidate.identity.id,
                        candidate.identity.media_id,
                        candidate.cluster_id,
                        decision.rejection_reason,
                    )

            already_in_new_clusters = {member.id for members, _ in new_cluster_proposals for member in members}
            all_processed_ids = accepted_ids | suggested_ids | rejected_ids | already_in_new_clusters
            no_candidates = [i for i in chunk if i.id not in all_processed_ids]
            rejected_identities = [i for i in chunk if i.id in rejected_ids]
            still_unclustered = no_candidates + rejected_identities

            logger.info(
                "[clustering] Identities needing new clusters: %d (no candidates: %d, rejected: %d)",
                len(still_unclustered),
                len(no_candidates),
                len(rejected_identities),
            )

            if still_unclustered:
                final_result = await self.graph_discovery.discover(still_unclustered, {})
                for members, similarities in final_result.new_clusters:
                    if members:
                        await self.assignment_writer.persist_new_cluster(
                            tenant_id=tenant_id,
                            identities=members,
                            similarities=similarities,
                            algorithm="graph",
                        )
                        clusters_created += 1
                        logger.info(
                            "[clustering] new_cluster job_id=%s member_count=%d media_ids=%s",
                            job_id,
                            len(members),
                            [m.media_id for m in members],
                        )

            for members, similarities in new_cluster_proposals:
                if members:
                    await self.assignment_writer.persist_new_cluster(
                        tenant_id=tenant_id,
                        identities=members,
                        similarities=similarities,
                        algorithm="graph",
                    )
                    clusters_created += 1
                    logger.info(
                        "[clustering] new_cluster job_id=%s member_count=%d media_ids=%s",
                        job_id,
                        len(members),
                        [m.media_id for m in members],
                    )

            processed += len(chunk)
            clustering_job.processed_identities = processed
            clustering_job.progress = (processed / total_identities) if total_identities else 1.0
            await self._session.flush()

        # Refresh centroids view if possible (keeps centroid discovery inputs current in future batches)
        refresh = getattr(self.assignment_writer, "refresh_centroids_view", None)
        if callable(refresh):
            await refresh()

        logger.info(
            "[clustering] batch_complete job_id=%s accepted=%d suggested=%d rejected=%d new_clusters=%d",
            job_id,
            accept_count,
            suggest_count,
            reject_count,
            clusters_created,
        )

        clustering_job.total_identities = len(domain_identities)
        clustering_job.processed_identities = len(domain_identities)
        clustering_job.progress = 1.0
        clustering_job.status = "completed"
        clustering_job.completed_at = datetime.now(tz=UTC)
        await self._session.flush()
        await self._session.commit()
        job_label = str(clustering_job.id)
        finished_at = clustering_job.completed_at or datetime.now(tz=UTC)
        if self.logger:
            clustering_job_report = BatchJobReport(
                job_id=job_label,
                algorithm="graph",  # or "incremental"
                started_at=started_at,
                completed_at=finished_at,
                total_identities=len(domain_identities),
                accept_count=accept_count,
                suggest_count=suggest_count,
                reject_count=reject_count,
                clusters_created=clusters_created,
                avg_similarity=None,
            )
            self.logger.log_batch_complete(clustering_job_report)

        return type(
            "ClusterJobResult",
            (),
            {
                "job_id": job_label,
                "started_at": started_at,
                "finished_at": finished_at,
                "completed": len(domain_identities),
                "total": len(domain_identities),
                "clusters_created": clusters_created,
                "accepted": accept_count,
                "suggested": suggest_count,
                "rejected": reject_count,
            },
        )()

    @staticmethod
    def _get_chunk_size(total_processed: int) -> int:
        """Return adaptive chunk size for incremental cold-start clustering."""
        if total_processed < 20:
            return 5
        if total_processed < 50:
            return 10
        if total_processed < 200:
            return 25
        return 50

    async def list_clusters(self, tenant_id: str, limit: int = 100, offset: int = 0, include_outliers: bool = False):
        """Return clusters for a tenant using the persistence layer."""
        clusters = await self.assignment_writer._clusters.get_by_tenant(tenant_id, limit=limit, offset=offset)
        for cluster in clusters:
            cluster.representatives = getattr(cluster, "representatives", []) or []
        if include_outliers:
            outlier_cluster = await self._build_outlier_cluster(tenant_id)
            if outlier_cluster and outlier_cluster.member_count > 0:
                outlier_cluster.representatives = getattr(outlier_cluster, "representatives", []) or []
                clusters.append(outlier_cluster)
            return clusters
        return [c for c in clusters if not self._is_outlier_cluster(c)]

    async def update_cluster(self, cluster_id: str, tenant_id: str, label: str | None) -> IdentityCluster | None:
        """Update cluster label and confirmation state."""
        cluster = await self.assignment_writer._clusters.get_by_id(cluster_id)
        # Normalize UUIDs to lowercase for comparison (db stores lowercase)
        if not cluster or cluster.tenant_id.lower() != tenant_id.lower():
            return None

        old_label = cluster.label
        cluster.label = label
        cluster.is_labeled = bool(label)
        cluster.user_confirmed = bool(label)
        updated = await self.assignment_writer._clusters.update(cluster)

        # Log the rename event
        if self.logger and old_label != label:
            with contextlib.suppress(Exception):
                self.logger.log_cluster_renamed(
                    cluster_id=cluster_id,
                    old_label=old_label,
                    new_label=label,
                    tenant_id=tenant_id,
                )

        logger.info(
            "[curation] RENAMED cluster_id=%s old_label='%s' new_label='%s' tenant_id=%s user_action=manual_rename",
            cluster_id,
            old_label,
            label,
            tenant_id,
        )

        # Recompute representatives/centroid if hooks exist (label changes can affect reps)
        recompute_reps = getattr(self.assignment_writer, "recompute_representatives", None)
        if callable(recompute_reps):
            await recompute_reps(cluster_id)
        recompute_centroid = getattr(self.assignment_writer, "recompute_centroid", None)
        if callable(recompute_centroid):
            await recompute_centroid(cluster_id)

        return updated

    async def create_cluster_for_identity(self, identity_id: str, label: str, tenant_id: str) -> IdentityCluster:
        """Create a new user-labeled cluster containing a single identity.

        Args:
            identity_id: Media identity UUID to place into the new cluster.
            label: Human-readable label for the cluster.
            tenant_id: Tenant that owns the identity and new cluster.

        Returns:
            The newly created cluster.

        Raises:
            ValueError: If the identity is missing or tenant-scoped validation fails.
            RuntimeError: If no database session is available.
        """
        if self._session is None:
            raise RuntimeError("Database session is required for create_cluster_for_identity")

        try:
            tenant_uuid = uuid.UUID(str(tenant_id))
            identity_uuid = uuid.UUID(str(identity_id))
        except ValueError as exc:
            raise ValueError("Invalid tenant_id or identity_id") from exc

        identity_model = await self._session.get(MediaIdentityModel, identity_uuid)
        if not identity_model or identity_model.tenant_id != tenant_uuid:
            raise ValueError("Identity not found")

        # If the identity is already assigned, detach it first so the new cluster is consistent.
        existing_cluster_id = await self.get_identity_cluster_id(identity_id)
        if existing_cluster_id:
            await self.remove_identity_from_cluster(identity_id)

        identity = MediaIdentity(
            id=str(identity_model.id),
            tenant_id=str(identity_model.tenant_id),
            media_id=str(identity_model.media_id),
            embedding=np.asarray(identity_model.embedding, dtype=np.float32),
            confidence=float(identity_model.confidence),
            bbox_width=int(identity_model.bbox_width),
            bbox_height=int(identity_model.bbox_height),
        )

        cluster = await self.assignment_writer.persist_new_cluster(
            tenant_id=tenant_id,
            identities=[identity],
            similarities=[1.0],
            algorithm="manual",
        )

        if cluster.id is None:
            raise ValueError("Cluster creation failed")

        updated = await self.assignment_writer.update_cluster_metadata(
            cluster_id=cluster.id,
            label=label,
            representative_id=identity_id,
        )

        updated.user_confirmed = True
        updated = await self.assignment_writer._clusters.update(updated)

        refresh_view = getattr(self.assignment_writer, "refresh_centroids_view", None)
        if callable(refresh_view):
            await refresh_view()

        logger.info(
            "[curation] CREATED cluster_id=%s label='%s' identity=%s tenant_id=%s user_action=manual_create",
            updated.id,
            updated.label,
            identity_id,
            tenant_id,
        )

        return updated

    async def merge_cluster(
        self,
        source_cluster_id: str,
        tenant_id: str,
        target_cluster_id: str,
        target_label: str | None = None,
    ) -> IdentityCluster | None:
        """Merge a source cluster into a target cluster by reassigning members."""
        cluster_repo: ClusterRepository = self.assignment_writer._clusters
        member_repo: MemberRepository = self.assignment_writer._members

        async def _merge() -> IdentityCluster | None:
            source = await cluster_repo.get_by_id(source_cluster_id)
            target = await cluster_repo.get_by_id(target_cluster_id)
            if not source or not target:
                return None
            # Normalize UUIDs to lowercase for comparison (db stores lowercase)
            if source.tenant_id.lower() != tenant_id.lower() or target.tenant_id.lower() != tenant_id.lower():
                return None

            # If source and target are identical, treat as a label/confirmation update.
            if source.id == target.id:
                return await self.update_cluster(target_cluster_id, tenant_id, label=target_label or target.label)

            moved = await member_repo.move_members(source_cluster_id, target_cluster_id)
            target.member_count = (target.member_count or 0) + moved
            target.label = target_label or target.label
            target.is_labeled = bool(target.label)
            target.user_confirmed = True
            updated: IdentityCluster = await cluster_repo.update(target)

            await cluster_repo.delete(source_cluster_id)

            recompute_reps = getattr(self.assignment_writer, "recompute_representatives", None)
            if callable(recompute_reps):
                await recompute_reps(target_cluster_id)
            recompute_centroid = getattr(self.assignment_writer, "recompute_centroid", None)
            if callable(recompute_centroid):
                await recompute_centroid(target_cluster_id)

            refresh_view = getattr(self.assignment_writer, "refresh_centroids_view", None)
            if callable(refresh_view):
                await refresh_view()

            # Log the merge event
            if self.logger:
                with contextlib.suppress(Exception):
                    self.logger.log_cluster_merged(
                        source_cluster_id=source_cluster_id,
                        target_cluster_id=target_cluster_id,
                        moved_count=moved,
                        tenant_id=tenant_id,
                    )

            logger.info(
                "[curation] MERGED source_cluster=%s target_cluster=%s moved_count=%d tenant_id=%s user_action=manual_merge",
                source_cluster_id,
                target_cluster_id,
                moved,
                tenant_id,
            )

            # Ensure member_count reflects reassignment
            updated.member_count = len(await member_repo.get_by_cluster(target_cluster_id))
            return updated

        # Session is already managed by the caller (FastAPI dependency)
        # so we don't need to start a new transaction here
        return await _merge()

    @staticmethod
    def _is_outlier_cluster(cluster) -> bool:
        """Return True if the cluster is considered an outlier/noise grouping."""
        label = (getattr(cluster, "label", "") or "").lower()
        algorithm = (getattr(cluster, "clustering_algorithm", "") or "").lower()
        return label in {"outlier", "-1", "noise"} or algorithm in {"outlier", "noise"}

    async def _build_outlier_cluster(self, tenant_id: str) -> IdentityCluster | None:
        """Construct a pseudo-cluster representing unassigned identities for the tenant."""
        if self._session is None:
            return None

        try:
            tenant_uuid = uuid.UUID(str(tenant_id))
        except ValueError:
            return None

        stmt: Select[tuple[MediaIdentityModel]] = (
            select(MediaIdentityModel)
            .where(MediaIdentityModel.tenant_id == tenant_uuid)
            .where(~exists(select(MemberModel.id).where(MemberModel.identity_id == MediaIdentityModel.id)))
        )
        result = await self._session.execute(stmt)
        unclustered = result.scalars().all()
        if not unclustered:
            return None

        return IdentityCluster(
            id=f"outliers-{tenant_id}",
            tenant_id=str(tenant_id),
            label="outliers",
            is_labeled=False,
            member_count=len(unclustered),
            created_at=datetime.now(tz=UTC),
            clustering_algorithm="outlier",
            user_confirmed=False,
            representatives=[],
        )

    async def assign_outlier_to_cluster(
        self, identity_id: str, target_cluster_id: str, tenant_id: str, similarity: float = 0.0
    ) -> IdentityCluster | None:
        """Manually assign an unclustered identity to an existing cluster."""
        cluster_repo: ClusterRepository = self.assignment_writer._clusters
        member_repo: MemberRepository = self.assignment_writer._members

        cluster = await cluster_repo.get_by_id(target_cluster_id)
        if not cluster or cluster.tenant_id != tenant_id:
            return None
        try:
            cluster_tenant_uuid = uuid.UUID(str(cluster.tenant_id))
        except ValueError:
            return None

        if self._session is None:
            return None

        try:
            identity_uuid = uuid.UUID(str(identity_id))
        except ValueError:
            return None

        identity_model = await self._session.get(MediaIdentityModel, identity_uuid)
        if not identity_model or identity_model.tenant_id != cluster_tenant_uuid:
            return None

        existing_members = await member_repo.get_by_cluster(target_cluster_id)
        if any(m.identity_id == str(identity_model.id) for m in existing_members):
            return cluster

        await member_repo.add_member(target_cluster_id, identity_id=str(identity_model.id), similarity=similarity)
        cluster.member_count += 1
        cluster = await cluster_repo.update(cluster)

        logger.info(
            "[curation] ASSIGNED identity=%s target_cluster=%s similarity=%.4f tenant_id=%s user_action=manual_assign",
            identity_model.id,
            target_cluster_id,
            similarity,
            tenant_id,
        )

        recompute_reps = getattr(self.assignment_writer, "recompute_representatives", None)
        if callable(recompute_reps):
            await recompute_reps(target_cluster_id)
        recompute_centroid = getattr(self.assignment_writer, "recompute_centroid", None)
        if callable(recompute_centroid):
            await recompute_centroid(target_cluster_id)

        return cluster

    async def get_identity_cluster_id(self, identity_id: str) -> str | None:
        """Get the cluster ID that an identity currently belongs to."""
        member_repo: MemberRepository = self.assignment_writer._members
        members = await member_repo.get_by_identity_id(identity_id)
        if members:
            return members[0].cluster_id
        return None

    async def remove_identity_from_cluster(self, identity_id: str) -> bool:
        """Remove an identity from its current cluster (make it an orphan)."""
        member_repo: MemberRepository = self.assignment_writer._members
        cluster_repo: ClusterRepository = self.assignment_writer._clusters

        members = await member_repo.get_by_identity_id(identity_id)
        if not members:
            return True  # Already not in any cluster

        cluster_id = members[0].cluster_id
        removed = await member_repo.remove_by_identity_id(identity_id)

        if removed:
            # Update cluster member count
            cluster = await cluster_repo.get_by_id(cluster_id)
            if cluster and cluster.member_count > 0:
                cluster.member_count -= 1
                await cluster_repo.update(cluster)

        logger.info(
            "[curation] REMOVED identity=%s from cluster=%s tenant_id=%s user_action=manual_remove",
            identity_id,
            cluster_id,
            self.assignment_writer._members.tenant_id
            if hasattr(self.assignment_writer._members, "tenant_id")
            else "unknown",
        )

        return True

    async def split_cluster(
        self,
        cluster_id: str,
        n_clusters: int = 0,
    ) -> tuple[list[str], list[int]]:
        """
        Split a mixed cluster using hierarchical clustering.

        If n_clusters=0 (default), automatically determines the optimal split
        based on face similarity. If n_clusters>=2, forces exactly that many groups.
        The largest group stays in the original cluster; others become new clusters.

        Args:
            cluster_id: The cluster to split
            n_clusters: Number of clusters to split into.
                       0 = auto-detect based on similarity threshold (default)
                       2+ = force exactly this many clusters

        Returns:
            Tuple of (new_cluster_ids, moved_counts) for each new cluster created.
        """
        from recognition.application.clustering.hierarchical_clustering import HierarchicalClustering

        session = self._session
        if not session:
            raise RuntimeError("No session available for split_cluster")

        cluster_repo: ClusterRepository = self.assignment_writer._clusters
        member_repo: MemberRepository = self.assignment_writer._members

        # 1. Fetch all identities in the cluster
        members = await member_repo.get_by_cluster(cluster_id)
        if not members or len(members) < 2:
            logger.info(
                "Split cluster %s: only %d identities, need at least 2 to split",
                cluster_id,
                len(members) if members else 0,
            )
            return [], []

        # Load identity embeddings
        identity_ids = [m.identity_id for m in members]
        stmt = select(MediaIdentityModel).where(MediaIdentityModel.id.in_(identity_ids))
        result = await session.execute(stmt)
        identities = list(result.scalars().all())

        if len(identities) < 2:
            return [], []

        # 2. Use HierarchicalClustering to split identities
        hierarchical = HierarchicalClustering(distance_threshold=0.30)
        clusters_by_label = hierarchical.split_identities(identities, n_clusters)

        # Check if we found multiple groups
        if len(clusters_by_label) <= 1:
            logger.info("Split cluster %s: All faces similar enough to stay together, nothing to split", cluster_id)
            return [], []

        # Build label array for compatibility with existing code
        identity_to_label: dict[str, int] = {}
        for label, group_members in clusters_by_label.items():
            for member in group_members:
                identity_to_label[str(member.id)] = label

        labels = [identity_to_label[str(id.id)] for id in identities]
        ids = [str(id.id) for id in identities]

        logger.info("Split cluster %s: Hierarchical clustering labels=%s", cluster_id, labels)

        # 3. Count members per group
        label_counts: dict[int, int] = {}
        for label in labels:
            label_counts[label] = label_counts.get(label, 0) + 1

        # Sort by count descending, keep largest in original cluster
        sorted_labels = sorted(label_counts.items(), key=lambda x: x[1], reverse=True)
        largest_label = sorted_labels[0][0]

        # Get the original cluster for updates
        original_cluster = await cluster_repo.get_by_id(cluster_id)
        if not original_cluster:
            logger.error("Split cluster %s: Original cluster not found", cluster_id)
            return [], []

        # Mark original as user-confirmed
        original_cluster.user_confirmed = True
        await cluster_repo.update(original_cluster)

        new_cluster_ids: list[str] = []
        moved_counts: list[int] = []

        # 4. Create new clusters for each non-largest group
        for label, count in sorted_labels[1:]:  # Skip largest (index 0)
            identity_ids_for_group = [ids[i] for i, lbl in enumerate(labels) if lbl == label]

            new_cluster_id = str(generate_id())
            new_cluster = IdentityCluster(
                id=new_cluster_id,
                tenant_id=original_cluster.tenant_id,
                label=f"Split from {cluster_id[:8]}",
                member_count=count,
                is_labeled=False,
                user_confirmed=True,
            )
            await cluster_repo.save(new_cluster)

            # Move members
            for identity_id in identity_ids_for_group:
                await member_repo.remove_by_identity_id(identity_id)
                await member_repo.add_member(new_cluster_id, identity_id=identity_id, similarity=1.0)

            new_cluster_ids.append(new_cluster_id)
            moved_counts.append(count)

            logger.info(
                "Split cluster %s: Created new cluster %s with %d identities",
                cluster_id,
                new_cluster_id,
                count,
            )

        # 5. Update original cluster count
        remaining_count = label_counts[largest_label]
        original_cluster.member_count = remaining_count
        await cluster_repo.update(original_cluster)

        total_moved = sum(moved_counts)
        logger.info(
            "Split cluster %s complete: created %d new clusters, moved %d identities, %d remain",
            cluster_id,
            len(new_cluster_ids),
            total_moved,
            remaining_count,
        )

        # Log the split event
        if self.logger and new_cluster_ids:
            with contextlib.suppress(Exception):
                self.logger.log_cluster_split(
                    original_cluster_id=cluster_id,
                    new_cluster_ids=new_cluster_ids,
                    moved_counts=moved_counts,
                    tenant_id=original_cluster.tenant_id,
                )

        logger.info(
            "[curation] SPLIT original_cluster=%s new_clusters=%s moved_counts=%s tenant_id=%s user_action=manual_split",
            cluster_id,
            new_cluster_ids,
            moved_counts,
            new_cluster_ids,
            moved_counts,
            original_cluster.tenant_id,
        )

        return new_cluster_ids, moved_counts
