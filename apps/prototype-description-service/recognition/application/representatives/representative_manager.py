"""Representative embedding management.

Handles the logic for adding representative embeddings to clusters
with diversity and quality guards.
"""

from __future__ import annotations

import logging
from uuid import UUID

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusterRepresentative, MediaIdentity
from recognition.application.clustering.cluster_repository import ClusterRepository
from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.representatives.representative_selection import decide_representative_acceptance
from recognition.domain.embeddings import prepare_embedding

logger = logging.getLogger(__name__)


class RepresentativeManager:
    """Manages representative embeddings for clusters."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        repository: ClusterRepository,
        settings: ClusteringSettings,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.repository = repository
        self.settings = settings

    async def add_representative(self, cluster_id: UUID, identity: MediaIdentity) -> np.ndarray | None:
        """
        Add a representative embedding for a cluster with diversity/quality guards.

        Returns the normalized embedding if accepted; otherwise None.
        """
        embedding = prepare_embedding(identity.embedding)

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
