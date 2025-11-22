"""Assignment logic for identities to clusters."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityMember, MediaIdentity
from recognition.application.assignment_guard import log_borderline_assignment
from recognition.application.centroid_utils import (
    compute_similarity,
    update_centroid_incremental,
)
from recognition.application.cluster_repository import ClusterSearchEntry
from recognition.application.clustering_settings import ClusteringSettings

logger = logging.getLogger(__name__)


class ClusterAssigner:
    """Handles assignment of identities to clusters."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        settings: ClusteringSettings,
    ):
        self.session = session
        self.tenant_id = tenant_id
        self.settings = settings
        self.threshold = settings.similarity_threshold
        self.strict_validation = False

    def enable_strict_validation(self) -> None:
        """Enable post-assignment validation checks."""
        self.strict_validation = True

    async def assign_to_cluster_by_id(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        similarity: float,
    ) -> None:
        """Assign an identity to a cluster by cluster ID."""
        cluster = await self.session.get(IdentityCluster, cluster_id)
        if cluster is None:
            raise ValueError(f"Cluster {cluster_id} not found")

        entry = ClusterSearchEntry(
            cluster=cluster,
            centroid=np.array(identity_vector, dtype=np.float32),
            member_count=0,
        )
        await self.assign_to_cluster(identity, identity_vector, entry, similarity)

    async def assign_to_cluster(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        entry: ClusterSearchEntry,
        similarity: float,
    ) -> None:
        """
        Assign an identity to a cluster and update the cluster's centroid.

        This creates a membership record, updates the in-memory centroid,
        and optionally validates the assignment.
        """
        log_borderline_assignment(
            logger,
            identity.id,
            entry.cluster.id,
            similarity,
            self.threshold,
            self.settings.borderline_window,
        )

        # Create membership record
        member = IdentityMember(
            tenant_id=self.tenant_id,
            cluster_id=entry.cluster.id,
            identity_id=identity.id,
            similarity=similarity,
            created_by_user_id=identity.created_by_user_id,
        )
        self.session.add(member)

        # Warn if assignment is below threshold
        if similarity + 1e-6 < self.threshold:
            logger.warning(
                "Assigned identity %s to cluster %s with similarity %.4f below threshold %.4f",
                identity.id,
                entry.cluster.id,
                similarity,
                self.threshold,
            )

        # Update in-memory centroid for incremental clustering
        old_count = entry.member_count
        entry.member_count += 1
        entry.centroid = update_centroid_incremental(
            entry.centroid,
            old_count,
            identity_vector,
        )

        # Validate assignment if strict mode enabled
        if self.strict_validation:
            await self._validate_assignment(identity, identity_vector, entry, similarity)

        # Update cluster metadata
        entry.cluster.identity_count += 1
        entry.cluster.updated_at = datetime.utcnow()

    async def _validate_assignment(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        entry: ClusterSearchEntry,
        similarity_at_assignment: float,
    ) -> None:
        """Re-check similarity after centroid update to catch drift."""
        recomputed_similarity = compute_similarity(identity_vector, entry.centroid)
        if recomputed_similarity + 1e-6 < self.threshold:
            logger.error(
                "Post-update similarity for identity %s in cluster %s dropped below threshold "
                "(assigned=%.4f, recomputed=%.4f, threshold=%.4f)",
                identity.id,
                entry.cluster.id,
                similarity_at_assignment,
                recomputed_similarity,
                self.threshold,
            )

    def find_best_cluster_match(
        self,
        identity_vector: np.ndarray,
        clusters: list[ClusterSearchEntry],
    ) -> tuple[ClusterSearchEntry | None, float]:
        """Find the cluster with highest similarity to the identity vector."""
        best_entry: ClusterSearchEntry | None = None
        best_similarity = 0.0

        for entry in clusters:
            if entry.member_count == 0:
                continue

            similarity = compute_similarity(identity_vector, entry.centroid)
            if similarity > best_similarity:
                best_similarity = similarity
                best_entry = entry

        return best_entry, best_similarity
