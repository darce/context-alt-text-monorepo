"""
ClusterService orchestrates discovery, gate evaluation, and assignment writes.

This file is intentionally kept as a façade. Larger workflows and user-driven
cluster curation operations live in dedicated modules under
`recognition.application.orchestration`.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from recognition.application.clustering.constrained_hac import ConstrainedHAC

from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.assignment import AssignmentGate
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
from recognition.application.orchestration.cluster_merge import (
    merge_cluster as merge_cluster_op,
)
from recognition.application.orchestration.cluster_merge import (
    post_merge_retry_matching as post_merge_retry_matching_op,
)
from recognition.application.orchestration.cluster_split import split_cluster as split_cluster_op
from recognition.application.orchestration.incremental_clustering import (
    cluster_unclustered_identities as cluster_unclustered_identities_op,
)
from recognition.application.orchestration.incremental_clustering import (
    get_chunk_size as get_chunk_size_op,
)
from recognition.application.orchestration.protocols import SuggestionServiceProtocol
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings.clustering import HACSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import IdentityClusterBlockRepository, IdentityConstraintRepository
from recognition.observability import ClusteringLogger

logger = logging.getLogger(__name__)


class ClusterService:
    """Coordinates discovery outputs, gate evaluation, and persistence."""

    # Type annotations for attributes that are set conditionally
    constrained_hac: ConstrainedHAC | None
    hac_settings: HACSettings | None

    def __init__(
        self,
        gate: AssignmentGate,
        representative_discovery: RepresentativeDiscovery,
        centroid_discovery: CentroidDiscovery,
        graph_discovery: GraphDiscovery,
        assignment_writer: AssignmentWriter,
        suggestion_service: SuggestionServiceProtocol,
        block_repository: IdentityClusterBlockRepository | None = None,
        constraint_repository: IdentityConstraintRepository | None = None,
        hac_settings: HACSettings | None = None,
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
        self.block_repository = block_repository
        self.constraint_repository = constraint_repository
        self.logger = logger
        self.visualizer = visualizer
        self.decision_store = decision_store
        self.observability_repo = observability_repo
        self._session = session

        # Initialize ConstrainedHAC if constraint repository is available
        if constraint_repository is not None:
            from recognition.application.clustering.constrained_hac import ConstrainedHAC
            from recognition.application.settings.clustering import HACSettings as DefaultHACSettings

            self.constrained_hac = ConstrainedHAC(
                constraint_repo=constraint_repository, settings=hac_settings or DefaultHACSettings()
            )
            self.hac_settings = hac_settings or DefaultHACSettings()
        else:
            self.constrained_hac = None
            self.hac_settings = None

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
            constrained_hac=self.constrained_hac,
            hac_settings=self.hac_settings,
        )

    @staticmethod
    def _get_chunk_size(total_processed: int) -> int:
        """Return adaptive chunk size for incremental cold-start clustering."""
        return get_chunk_size_op(total_processed)

    async def list_clusters(
        self,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0,
        include_outliers: bool = False,
        labeled_only: bool = False,
    ):
        """Return clusters for a tenant using the persistence layer."""
        return await list_clusters_op(
            cluster_repo=self.assignment_writer._clusters,
            session=self._session,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            include_outliers=include_outliers,
            labeled_only=labeled_only,
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
            constraint_repository=self.constraint_repository,
        )

    async def retry_matching(self, target_cluster_id: str, tenant_id: str) -> None:
        """Run post-merge matching retry (intended for background tasks)."""
        await post_merge_retry_matching_op(
            tenant_id=tenant_id,
            target_cluster_id=target_cluster_id,
            session=self._session,
            gate=self.gate,
            assignment_writer=self.assignment_writer,
            suggestion_service=self.suggestion_service,
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

    async def remove_identity_from_cluster(self, identity_id: str, recompute: bool = True) -> bool:
        """Remove an identity from its current cluster (make it an orphan)."""
        tenant_id_for_logging = getattr(self.assignment_writer._members, "_tenant_id", None) or getattr(
            self.assignment_writer._members, "tenant_id", None
        )
        media_id = None
        if self._session is not None:
            try:
                identity_uuid = uuid.UUID(str(identity_id))
            except ValueError:
                identity_uuid = None
            if identity_uuid is not None:
                model = await self._session.get(MediaIdentityModel, identity_uuid)
                if model is not None:
                    media_id = int(model.media_id)
        return await remove_identity_from_cluster_op(
            identity_id=identity_id,
            member_repo=self.assignment_writer._members,
            cluster_repo=self.assignment_writer._clusters,
            assignment_writer=self.assignment_writer,
            recompute=recompute,
            tenant_id_for_logging=tenant_id_for_logging,
            media_id=media_id,
        )

    async def split_cluster(
        self,
        cluster_id: str,
        n_clusters: int = 0,
        anchor_identity_id: str | None = None,
        split_mode: str | None = None,
        recompute: bool = True,
    ) -> tuple[list[str], list[int]]:
        """Split a mixed cluster using hierarchical clustering."""
        return await split_cluster_op(
            cluster_id=cluster_id,
            n_clusters=n_clusters,
            anchor_identity_id=anchor_identity_id,
            split_mode=split_mode,
            session=self._session,
            cluster_repo=self.assignment_writer._clusters,
            member_repo=self.assignment_writer._members,
            block_repo=self.block_repository,
            suggestion_service=self.suggestion_service,
            assignment_writer=self.assignment_writer,
            recompute=recompute,
            clustering_logger=self.logger,
        )
