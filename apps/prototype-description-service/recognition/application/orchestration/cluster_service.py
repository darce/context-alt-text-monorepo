"""
ClusterService orchestrates discovery, gate evaluation, and assignment writes.

This file is intentionally kept as a façade. Larger workflows and user-driven
cluster curation operations live in dedicated modules under
`recognition.application.orchestration`.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from recognition.application.clustering.constrained_hac import ConstrainedHAC

from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.assignment import AssignmentGate
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.orchestration.cluster_merge import (
    merge_cluster as merge_cluster_op,
)
from recognition.application.orchestration.cluster_merge import (
    post_merge_retry_matching as post_merge_retry_matching_op,
)
from recognition.application.orchestration.curation import (
    assign_outlier_to_cluster as assign_outlier_to_cluster_op,
)
from recognition.application.orchestration.curation import (
    create_cluster_for_identity as create_cluster_for_identity_op,
)
from recognition.application.orchestration.curation import (
    get_identity_cluster_id as get_identity_cluster_id_op,
)
from recognition.application.orchestration.curation import (
    list_clusters as list_clusters_op,
)
from recognition.application.orchestration.curation import (
    remove_identity_from_cluster as remove_identity_from_cluster_op,
)
from recognition.application.orchestration.curation import (
    update_cluster as update_cluster_op,
)
from recognition.application.orchestration.incremental_clustering import (
    cluster_unclustered_identities as cluster_unclustered_identities_op,
)
from recognition.application.orchestration.incremental_clustering import (
    get_chunk_size as get_chunk_size_op,
)
from recognition.application.orchestration.protocols import (
    MergeSuggestionServiceProtocol,
    SuggestionRefreshServiceProtocol,
    SuggestionServiceProtocol,
)
from recognition.application.orchestration.split import split_cluster as split_cluster_op
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings.clustering import HACSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import (
    ClusterRepository,
    IdentityClusterBlockRepository,
    IdentityConstraintRepository,
)
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
        suggestion_refresh_service: SuggestionRefreshServiceProtocol | None = None,
        merge_suggestion_service: MergeSuggestionServiceProtocol | None = None,
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
        self.suggestion_refresh_service = suggestion_refresh_service
        self.merge_suggestion_service = merge_suggestion_service
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

    @property
    def cluster_repository(self) -> ClusterRepository:
        """Access the underlying cluster repository."""
        return self.assignment_writer.cluster_repository

    @property
    def session(self) -> AsyncSession:
        """Get the database session, raising if not configured.

        Raises:
            RuntimeError: If ClusterService was constructed without a session.
        """
        if self._session is None:
            raise RuntimeError(
                "ClusterService requires a database session for this operation. Pass session= to the constructor."
            )
        return self._session

    async def cluster_unclustered_identities(
        self,
        tenant_id: str,
        job_id: str | None = None,
        *,
        progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
        commit: bool = True,
    ):
        """Cluster any identities not yet assigned to a cluster."""
        result = await cluster_unclustered_identities_op(
            tenant_id=tenant_id,
            job_id=job_id,
            session=self.session,  # Uses property with clear error
            gate=self.gate,
            representative_discovery=self.representative_discovery,
            centroid_discovery=self.centroid_discovery,
            graph_discovery=self.graph_discovery,
            assignment_writer=self.assignment_writer,
            suggestion_service=self.suggestion_service,
            merge_suggestion_service=self.merge_suggestion_service,
            clustering_logger=self.logger,
            constrained_hac=self.constrained_hac,
            hac_settings=self.hac_settings,
            progress_callback=progress_callback,
            commit=commit,
        )

        if self.suggestion_refresh_service and result.created_cluster_ids:
            try:
                surfaced = await self.suggestion_refresh_service.backfill_for_new_unlabeled_clusters(
                    tenant_id=tenant_id, created_cluster_ids=result.created_cluster_ids
                )
                if surfaced > 0:
                    logger.info(
                        "[suggestions] backfill surfaced=%d tenant_id=%s clusters=%d",
                        surfaced,
                        tenant_id,
                        len(result.created_cluster_ids),
                    )
                if commit:
                    await self.session.commit()
            except Exception as exc:
                logger.warning("[suggestions] backfill failed tenant_id=%s err=%s", tenant_id, exc)

        if commit and self.merge_suggestion_service is not None:
            try:
                await self.assignment_writer.refresh_centroids_view()
                created = await self.merge_suggestion_service.generate_for_tenant(tenant_id)
                singleton_created = 0
                if self.constrained_hac and self.hac_settings:
                    singleton_created = await self.merge_suggestion_service.generate_singleton_merge_suggestions(
                        tenant_id,
                        constrained_hac=self.constrained_hac,
                        hac_settings=self.hac_settings,
                    )
                total_created = created + singleton_created
                if total_created > 0:
                    logger.info(
                        "[merge_suggestions] queued=%d singleton_queued=%d tenant_id=%s",
                        created,
                        singleton_created,
                        tenant_id,
                    )
                    await self.session.commit()
            except Exception as exc:
                logger.warning("[merge_suggestions] generation failed tenant_id=%s err=%s", tenant_id, exc)

        return result

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
        search: str | None = None,
    ):
        """Return clusters for a tenant using the persistence layer."""
        clusters = await list_clusters_op(
            cluster_repo=self.assignment_writer.cluster_repository,
            session=self._session,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            include_outliers=include_outliers,
            labeled_only=labeled_only,
            search=search,
        )

        # Populate suggested_label fields for unlabeled clusters
        # We attach these dynamically so Pydantic model_validate can pick them up
        if not labeled_only:
            from recognition.application.suggestions.label_inference import infer_suggested_label

            for cluster in clusters:
                if not cluster.label and self._session:
                    try:
                        suggestion = await infer_suggested_label(
                            tenant_id=tenant_id,
                            cluster_id=str(cluster.id),
                            session=self._session,
                            cluster_repository=self.cluster_repository,
                            settings=self.gate.settings,
                        )
                        if suggestion:
                            cluster.suggested_label = suggestion.label  # type: ignore[attr-defined]
                            cluster.suggested_label_source = suggestion.source.value if suggestion.source else None  # type: ignore[attr-defined]
                            cluster.suggested_label_confidence = suggestion.confidence  # type: ignore[attr-defined]
                    except Exception as e:
                        # Log error but don't break listing
                        logger.warning("Failed to infer label for cluster %s: %s", cluster.id, e)

        return clusters

    async def get_cluster_members(self, cluster_id: str, tenant_id: str):
        """Return all member identities for a cluster."""
        # Ensure tenant ownership implicitly via repo RLS or explicit check?
        # The repo methods usually filter by tenant if supported, but get_member_identities(cluster_id)
        # assumes cluster_id is unique globally or we need to check tenant.
        # But for now, we rely on the router to check tenant access before calling this.
        # Ideally repo should check tenant.
        return await self.cluster_repository.get_member_identities(cluster_id)

    async def update_cluster(
        self,
        cluster_id: str,
        tenant_id: str,
        label: str | None,
        *,
        surface_suggestions: bool = True,
    ) -> IdentityCluster | None:
        """Update cluster label and confirmation state.

        When a cluster becomes user-labeled, optionally surface suggestions for
        identities in unlabeled clusters that match this newly-labeled cluster.
        """
        was_user_confirmed = False
        if surface_suggestions:
            cluster_repo = self.assignment_writer.cluster_repository
            old_cluster = await cluster_repo.get_by_id(cluster_id)
            was_user_confirmed = old_cluster.user_confirmed if old_cluster else False

        result = await update_cluster_op(
            cluster_id=cluster_id,
            tenant_id=tenant_id,
            label=label,
            assignment_writer=self.assignment_writer,
            clustering_logger=self.logger,
        )

        # If cluster just became user-labeled, surface suggestions
        if (
            surface_suggestions
            and result
            and label
            and not was_user_confirmed
            and self.suggestion_refresh_service is not None
        ):
            try:
                surfaced = await self.suggestion_refresh_service.surface_for_newly_labeled_cluster(cluster_id)
                if surfaced > 0:
                    logger.info(
                        "[curation] Surfaced %d suggestions after labeling cluster_id=%s label='%s'",
                        surfaced,
                        cluster_id,
                        label,
                    )
            except Exception as e:
                logger.warning("[curation] Failed to surface suggestions: %s", e)

        return result

    async def create_cluster_for_identity(
        self, identity_id: str, label: str, tenant_id: str, desired_cluster_id: str | None = None
    ) -> IdentityCluster:
        return await create_cluster_for_identity_op(
            identity_id=identity_id,
            label=label,
            tenant_id=tenant_id,
            desired_cluster_id=desired_cluster_id,
            session=self._session,
            assignment_writer=self.assignment_writer,
            suggestion_service=self.suggestion_service,
        )

    async def merge_cluster(
        self,
        source_cluster_id: str,
        tenant_id: str,
        target_cluster_id: str,
        target_label: str | None = None,
        *,
        defer_recompute: bool = False,
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
            merge_suggestion_service=self.merge_suggestion_service,
            clustering_logger=self.logger,
            session=self._session,
            defer_recompute=defer_recompute,
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
            suggestion_service=self.suggestion_service,
            clustering_logger=self.logger,
        )

    async def get_identity_cluster_id(self, identity_id: str) -> str | None:
        """Get the cluster ID that an identity currently belongs to."""
        return await get_identity_cluster_id_op(
            member_repo=self.assignment_writer.member_repository,
            identity_id=identity_id,
        )

    async def remove_identity_from_cluster(self, identity_id: str, recompute: bool = True) -> bool:
        """Remove an identity from its current cluster (make it an orphan)."""
        tenant_id_for_logging = getattr(self.assignment_writer.member_repository, "_tenant_id", None) or getattr(
            self.assignment_writer.member_repository, "tenant_id", None
        )

        cluster_id = None
        if self.suggestion_refresh_service:
            # Capture cluster ID before removal so we can refresh suggestions for it
            cluster_id = await self.get_identity_cluster_id(identity_id)

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

        result = await remove_identity_from_cluster_op(
            identity_id=identity_id,
            member_repo=self.assignment_writer.member_repository,
            cluster_repo=self.assignment_writer.cluster_repository,
            assignment_writer=self.assignment_writer,
            recompute=recompute,
            tenant_id_for_logging=tenant_id_for_logging,
            media_id=media_id,
            session=self._session,
            clustering_logger=self.logger,
        )

        if result and cluster_id and self.suggestion_refresh_service:
            try:
                await self.suggestion_refresh_service.refresh_for_cluster(cluster_id)
            except Exception as e:
                logger.warning(
                    "[curation] Failed to refresh suggestions after removing identity %s from cluster %s: %s",
                    identity_id,
                    cluster_id,
                    e,
                )

        return result

    async def split_cluster(
        self,
        cluster_id: str,
        n_clusters: int = 0,
        anchor_identity_id: str | None = None,
        split_mode: str | None = None,
        desired_cluster_ids: list[str] | None = None,
        recompute: bool = True,
    ) -> tuple[list[str], list[int]]:
        """Split a mixed cluster using hierarchical clustering."""
        return await split_cluster_op(
            cluster_id=cluster_id,
            n_clusters=n_clusters,
            anchor_identity_id=anchor_identity_id,
            split_mode=split_mode,
            desired_cluster_ids=desired_cluster_ids,
            session=self._session,
            cluster_repo=self.assignment_writer.cluster_repository,
            member_repo=self.assignment_writer.member_repository,
            block_repo=self.block_repository,
            suggestion_refresh_service=self.suggestion_refresh_service,
            assignment_writer=self.assignment_writer,
            recompute=recompute,
            clustering_logger=self.logger,
        )
