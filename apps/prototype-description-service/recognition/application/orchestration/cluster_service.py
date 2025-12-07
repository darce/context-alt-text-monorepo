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
from recognition.application.discovery.graph import GraphDiscoveryResult
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity

logger = logging.getLogger(__name__)
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.observability import ClusteringLogger, DecisionType
from recognition.observability.reports import BatchJobReport
from recognition.shared.ids import generate_id


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

        graph_result: GraphDiscoveryResult | list[AssignmentCandidate] = await self.graph_discovery.discover(
            remaining, anchor_embeddings
        )
        graph_candidates: list[AssignmentCandidate] = (
            graph_result.candidates if isinstance(graph_result, GraphDiscoveryResult) else graph_result
        )
        new_clusters = graph_result.new_clusters if isinstance(graph_result, GraphDiscoveryResult) else []

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

    async def cluster_unclustered_identities(self, tenant_id: str):
        """Cluster any identities not yet assigned to a cluster."""
        logger.info("[clustering] cluster_unclustered_identities called with tenant_id=%s", tenant_id)
        job_id = str(generate_id())
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

        logger.info(
            "[clustering] Starting clustering for %d unclustered identities, tenant=%s",
            len(domain_identities),
            tenant_id,
        )

        # ============================================================
        # PHASE 1: Try to match identities to existing cluster representatives
        # ============================================================
        from recognition.infrastructure.clustering import DeterministicChineseWhispers

        # Settings for clustering
        rep_match_threshold = 0.60  # Threshold for representative matching
        cw_threshold = 0.68  # Threshold for Chinese Whispers clustering

        # Get existing clusters with their representatives
        existing_clusters = await self.assignment_writer._clusters.get_by_tenant(str(tenant_id), limit=1000, offset=0)
        logger.info("[clustering] Found %d existing clusters", len(existing_clusters))

        # Build representative embeddings map: cluster_id -> list of representative embeddings
        rep_embeddings_by_cluster: dict[str, list[np.ndarray]] = {}
        for cluster in existing_clusters:
            if cluster.id is None:
                continue
            reps = getattr(cluster, "representatives", []) or []
            if reps:
                rep_embeddings_by_cluster[cluster.id] = [
                    np.array(r.embedding, dtype=np.float32) for r in reps if r.embedding is not None
                ]

        # Try to match each identity to existing representatives
        matched_identities: list[tuple[MediaIdentity, str, float]] = []  # (identity, cluster_id, similarity)
        remaining_identities: list[MediaIdentity] = []

        for identity in domain_identities:
            identity_embedding = np.array(identity.embedding, dtype=np.float32)
            # Normalize for cosine similarity
            norm = np.linalg.norm(identity_embedding)
            if norm > 0:
                identity_embedding = identity_embedding / norm

            best_cluster_id: str | None = None
            best_similarity = 0.0

            # Compare against all representatives
            for cluster_id, rep_list in rep_embeddings_by_cluster.items():
                for rep_emb in rep_list:
                    rep_norm = np.linalg.norm(rep_emb)
                    if rep_norm > 0:
                        rep_emb_normalized = rep_emb / rep_norm
                    else:
                        rep_emb_normalized = rep_emb
                    similarity = float(np.dot(identity_embedding, rep_emb_normalized))
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_cluster_id = cluster_id

            if best_cluster_id and best_similarity >= rep_match_threshold:
                matched_identities.append((identity, best_cluster_id, best_similarity))
            else:
                remaining_identities.append(identity)

        logger.info(
            "[clustering] Phase 1 complete: %d matched to existing clusters, %d remaining",
            len(matched_identities),
            len(remaining_identities),
        )

        # Assign matched identities to their clusters
        assigned_count = 0
        for identity, cluster_id, similarity in matched_identities:
            await self.assignment_writer.assign_to_existing_cluster(
                identity=identity,
                cluster_id=cluster_id,
                similarity=similarity,
            )
            assigned_count += 1
            logger.info(
                "[clustering] Assigned identity %s to cluster %s (similarity=%.4f)",
                identity.id,
                cluster_id,
                similarity,
            )

        # ============================================================
        # PHASE 2: Run Chinese Whispers on remaining unmatched identities
        # ============================================================
        clusters_created = 0
        if remaining_identities:
            logger.info(
                "[clustering] Phase 2: Running Chinese Whispers on %d remaining identities (threshold=%.2f)",
                len(remaining_identities),
                cw_threshold,
            )
            embeddings = [i.embedding for i in remaining_identities]
            cw = DeterministicChineseWhispers(threshold=cw_threshold, max_iterations=20)
            labels = cw.cluster(embeddings, remaining_identities)

            # Group identities by cluster label
            cluster_groups: dict[int, list[MediaIdentity]] = {}
            for identity, label in zip(remaining_identities, labels, strict=False):
                cluster_groups.setdefault(label, []).append(identity)

            logger.info(
                "[clustering] Chinese Whispers produced %d clusters from %d identities",
                len(cluster_groups),
                len(remaining_identities),
            )

            # Persist each new cluster
            for label, members in cluster_groups.items():
                if members:
                    logger.info(
                        "[clustering] Creating cluster for label %d with %d members: %s",
                        label,
                        len(members),
                        [m.id for m in members],
                    )
                    await self.assignment_writer.persist_new_cluster(
                        tenant_id=tenant_id,
                        identities=members,
                        similarities=[1.0] * len(members),
                        algorithm="chinese_whispers",
                    )
                    clusters_created += 1

        logger.info(
            "[clustering] Complete: %d assigned to existing, %d new clusters created",
            assigned_count,
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
                "assigned_to_existing": assigned_count,
            },
        )()

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
        if not cluster or cluster.tenant_id != tenant_id:
            return None

        cluster.label = label
        cluster.is_labeled = bool(label)
        cluster.user_confirmed = bool(label)
        updated = await self.assignment_writer._clusters.update(cluster)

        # Recompute representatives/centroid if hooks exist (label changes can affect reps)
        recompute_reps = getattr(self.assignment_writer, "recompute_representatives", None)
        if callable(recompute_reps):
            await recompute_reps(cluster_id)
        recompute_centroid = getattr(self.assignment_writer, "recompute_centroid", None)
        if callable(recompute_centroid):
            await recompute_centroid(cluster_id)

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
            if source.tenant_id != tenant_id or target.tenant_id != tenant_id:
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

            if hasattr(self, "log_merge_audit"):
                with contextlib.suppress(Exception):
                    await self.log_merge_audit(source_cluster_id, target_cluster_id)

            # Ensure member_count reflects reassignment
            updated.member_count = len(await member_repo.get_by_cluster(target_cluster_id))
            return updated

        if self._session is not None:
            async with self._session.begin():
                return await _merge()
        return await _merge()

    async def log_merge_audit(self, source_id: str, target_id: str) -> None:  # pragma: no cover - override hook
        """Optional audit hook; can be overridden or monkeypatched in tests."""
        if self.logger:
            self.logger.log_decision(
                identity_id="merge",
                cluster_id=target_id,
                decision=DecisionType.ACCEPT,
                reason=f"merge {source_id}->{target_id}",
                metadata={"source_cluster_id": source_id, "target_cluster_id": target_id},
            )

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

        recompute_reps = getattr(self.assignment_writer, "recompute_representatives", None)
        if callable(recompute_reps):
            await recompute_reps(target_cluster_id)
        recompute_centroid = getattr(self.assignment_writer, "recompute_centroid", None)
        if callable(recompute_centroid):
            await recompute_centroid(target_cluster_id)

        return cluster
