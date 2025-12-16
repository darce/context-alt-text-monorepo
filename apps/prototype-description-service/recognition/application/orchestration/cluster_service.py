"""
ClusterService orchestrates discovery, gate evaluation, and assignment writes.

This file is intentionally kept as a façade. Larger workflows and user-driven
cluster curation operations live in dedicated modules under
`recognition.application.orchestration`.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.assignment import AssignmentCandidate, AssignmentGate, AssignmentOutcome
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.orchestration.cluster_curation import (
    assign_outlier_to_cluster as assign_outlier_to_cluster_op,
)
from recognition.application.orchestration.cluster_curation import (
    create_cluster_for_identity as create_cluster_for_identity_op,
)
from recognition.application.orchestration.cluster_curation import (
    get_identity_cluster_id as get_identity_cluster_id_op,
)
from recognition.application.orchestration.cluster_curation import (
    list_clusters as list_clusters_op,
)
from recognition.application.orchestration.cluster_curation import (
    remove_identity_from_cluster as remove_identity_from_cluster_op,
)
from recognition.application.orchestration.cluster_curation import (
    update_cluster as update_cluster_op,
)
from recognition.application.orchestration.cluster_merge import merge_cluster as merge_cluster_op
from recognition.application.orchestration.cluster_split import split_cluster as split_cluster_op
from recognition.application.orchestration.incremental_clustering import (
    cluster_unclustered_identities as cluster_unclustered_identities_op,
)
from recognition.application.orchestration.incremental_clustering import (
    get_chunk_size as get_chunk_size_op,
)
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.cluster import IdentityCluster
from recognition.domain.locator import IdentityLocator
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
        locator_payload: dict[str, object] | None = None
        identity = decision.candidate.identity
        bbox_x = identity.bbox_x
        bbox_y = identity.bbox_y
        if bbox_x is not None and bbox_y is not None:
            try:
                locator_payload = IdentityLocator(
                    media_id=int(identity.media_id),
                    bbox_x=int(bbox_x),
                    bbox_y=int(bbox_y),
                    bbox_width=int(identity.bbox_width),
                    bbox_height=int(identity.bbox_height),
                    crop_hash=None,
                ).to_dict()
            except (TypeError, ValueError):
                locator_payload = None

        metadata = dict(decision.metadata or {})
        gate_settings = getattr(self.gate, "settings", None)
        threshold = getattr(gate_settings, "similarity_threshold", None) if gate_settings is not None else None
        metadata.update(
            {
                "method": decision.candidate.discovery_method.value,
                "stage": f"{decision.candidate.discovery_method.name.title()}Discovery",
                "threshold": float(threshold) if threshold is not None else None,
                "gate_checks": {"passed": decision.checks_passed, "failed": decision.checks_failed},
                "anchor_linked": bool(decision.candidate.anchor_linked),
                "confidence": float(decision.suggestion_confidence)
                if decision.suggestion_confidence is not None
                else decision.candidate.discovery_similarity,
            }
        )
        if locator_payload is not None:
            metadata["identity_locator"] = locator_payload

        decision_log = self.logger.log_decision(
            identity_id=decision.candidate.identity.id,
            cluster_id=decision.candidate.cluster_id,
            decision=decision_type,
            similarity=decision.candidate.discovery_similarity,
            reason=decision.rejection_reason,
            metadata=metadata,
            algorithm="hybrid",
            job_id=None,
            media_id=identity.media_id,
        )
        if self.decision_store:
            with contextlib.suppress(Exception):
                self.decision_store.add(
                    {
                        "id": decision_log.identity_id,
                        "tenant_id": identity.tenant_id,
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
                    tenant_id=identity.tenant_id,
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
        return await cluster_unclustered_identities_op(
            tenant_id=tenant_id,
            job_id=job_id,
            session=self._session,
            gate=self.gate,
            representative_discovery=self.representative_discovery,
            centroid_discovery=self.centroid_discovery,
            graph_discovery=self.graph_discovery,
            assignment_writer=self.assignment_writer,
            suggestion_service=self.suggestion_service,
            clustering_logger=self.logger,
        )

    @staticmethod
    def _get_chunk_size(total_processed: int) -> int:
        """Return adaptive chunk size for incremental cold-start clustering."""
        return get_chunk_size_op(total_processed)

    async def list_clusters(self, tenant_id: str, limit: int = 100, offset: int = 0, include_outliers: bool = False):
        """Return clusters for a tenant using the persistence layer."""
        return await list_clusters_op(
            cluster_repo=self.assignment_writer._clusters,
            session=self._session,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            include_outliers=include_outliers,
        )

    async def update_cluster(self, cluster_id: str, tenant_id: str, label: str | None) -> IdentityCluster | None:
        """Update cluster label and confirmation state."""
        return await update_cluster_op(
            cluster_id=cluster_id,
            tenant_id=tenant_id,
            label=label,
            assignment_writer=self.assignment_writer,
            clustering_logger=self.logger,
        )

    async def create_cluster_for_identity(self, identity_id: str, label: str, tenant_id: str) -> IdentityCluster:
        return await create_cluster_for_identity_op(
            identity_id=identity_id,
            label=label,
            tenant_id=tenant_id,
            session=self._session,
            assignment_writer=self.assignment_writer,
        )

    async def merge_cluster(
        self,
        source_cluster_id: str,
        tenant_id: str,
        target_cluster_id: str,
        target_label: str | None = None,
    ) -> IdentityCluster | None:
        """Merge a source cluster into a target cluster by reassigning members."""
        # Session is already managed by the caller (FastAPI dependency)
        # so we don't need to start a new transaction here
        return await merge_cluster_op(
            source_cluster_id=source_cluster_id,
            tenant_id=tenant_id,
            target_cluster_id=target_cluster_id,
            target_label=target_label,
            assignment_writer=self.assignment_writer,
            suggestion_service=self.suggestion_service,
            gate=self.gate,
            clustering_logger=self.logger,
            session=self._session,
        )

    async def assign_outlier_to_cluster(
        self, identity_id: str, target_cluster_id: str, tenant_id: str, similarity: float = 0.0
    ) -> IdentityCluster | None:
        """Manually assign an unclustered identity to an existing cluster."""
        return await assign_outlier_to_cluster_op(
            identity_id=identity_id,
            target_cluster_id=target_cluster_id,
            tenant_id=tenant_id,
            similarity=similarity,
            session=self._session,
            assignment_writer=self.assignment_writer,
        )

    async def get_identity_cluster_id(self, identity_id: str) -> str | None:
        """Get the cluster ID that an identity currently belongs to."""
        return await get_identity_cluster_id_op(
            member_repo=self.assignment_writer._members,
            identity_id=identity_id,
        )

    async def remove_identity_from_cluster(self, identity_id: str) -> bool:
        """Remove an identity from its current cluster (make it an orphan)."""
        tenant_id_for_logging = getattr(self.assignment_writer._members, "_tenant_id", None) or getattr(
            self.assignment_writer._members, "tenant_id", None
        )
        return await remove_identity_from_cluster_op(
            identity_id=identity_id,
            member_repo=self.assignment_writer._members,
            cluster_repo=self.assignment_writer._clusters,
            tenant_id_for_logging=tenant_id_for_logging,
        )

    async def split_cluster(
        self,
        cluster_id: str,
        n_clusters: int = 0,
    ) -> tuple[list[str], list[int]]:
        """Split a mixed cluster using hierarchical clustering."""
        return await split_cluster_op(
            cluster_id=cluster_id,
            n_clusters=n_clusters,
            session=self._session,
            cluster_repo=self.assignment_writer._clusters,
            member_repo=self.assignment_writer._members,
            clustering_logger=self.logger,
        )
