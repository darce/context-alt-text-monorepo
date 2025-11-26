"""Factory for creating new identity clusters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityMember, MediaIdentity
from recognition.application.clustering.centroid_utils import (
    compute_centroid,
    compute_similarity,
)
from recognition.application.clustering.cluster_repository import ClusterSearchEntry
from recognition.domain.embeddings import prepare_embedding


class ClusterFactory:
    """Handles creation of new identity clusters."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        similarity_threshold: float,
    ):
        self.session = session
        self.tenant_id = tenant_id
        self.threshold = similarity_threshold

    async def create_cluster_with_centroid(
        self,
        identities: Sequence[MediaIdentity],
        add_representative_callback: Callable[[UUID, MediaIdentity], Awaitable[np.ndarray | None]] | None = None,
    ) -> tuple[IdentityCluster, ClusterSearchEntry]:
        """
        Create a new cluster from a sequence of identities.

        Args:
            identities: One or more identities to cluster together
            add_representative_callback: Optional callback to add representatives after creation

        Returns:
            Tuple of (cluster, search_entry) for the newly created cluster
        """
        if not identities:
            raise ValueError("Cannot create cluster without identities")

        # Compute centroid from normalized embeddings (ensure 1024D for compatibility)
        embeddings = [prepare_embedding(identity.embedding) for identity in identities]
        centroid_vector = compute_centroid(embeddings)

        # Use highest confidence identity as representative
        representative = max(identities, key=lambda i: i.confidence)

        # Create cluster entity
        cluster = IdentityCluster(
            tenant_id=self.tenant_id,
            label=f"cluster-{uuid4().hex[:8]}",
            representative_identity_id=representative.id,
            identity_count=len(identities),
            similarity_threshold=self.threshold,
            clustering_algorithm="pgvector-incremental",
        )
        self.session.add(cluster)
        await self.session.flush()

        # Create membership records
        for identity in identities:
            similarity = compute_similarity(
                prepare_embedding(identity.embedding),
                centroid_vector,
            )
            member = IdentityMember(
                tenant_id=self.tenant_id,
                cluster_id=cluster.id,
                identity_id=identity.id,
                similarity=similarity,
                created_by_user_id=identity.created_by_user_id,
            )
            self.session.add(member)

        # Add representative embeddings if callback provided
        if add_representative_callback:
            for identity in identities:
                await add_representative_callback(cluster.id, identity)

        # Build search entry for incremental clustering
        entry = ClusterSearchEntry(
            cluster=cluster,
            centroid=np.array(centroid_vector, dtype=np.float32),
            member_count=len(identities),
        )

        return cluster, entry
