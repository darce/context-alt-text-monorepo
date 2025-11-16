"""Clustering service for grouping similar identities using pgvector."""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityMember, MediaIdentity

logger = logging.getLogger(__name__)


class IdentityClusteringService:
    """Cluster similar identities using pgvector cosine similarity."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        similarity_threshold: float = 0.6,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.threshold = similarity_threshold

    async def cluster_identities(self) -> List[IdentityCluster]:
        logger.info("Starting identity clustering for tenant %s", self.tenant_id)

        unclustered_identities = await self._get_unclustered_identities()
        if not unclustered_identities:
            logger.info("No unclustered identities for tenant %s", self.tenant_id)
            return []

        processed_ids = set()
        clusters: List[IdentityCluster] = []

        for seed_identity in unclustered_identities:
            if seed_identity.id in processed_ids:
                continue

            candidates = await self._find_similar_identities(seed_identity)
            if len(candidates) < 2:
                processed_ids.add(seed_identity.id)
                continue

            cluster = await self._create_cluster(candidates)
            clusters.append(cluster)

            for identity, _ in candidates:
                processed_ids.add(identity.id)

        logger.info(
            "Created %d clusters for tenant %s",
            len(clusters),
            self.tenant_id,
        )
        return clusters

    async def _get_unclustered_identities(self) -> List[MediaIdentity]:
        membership_exists = (
            select(1)
            .where(
                IdentityMember.tenant_id == self.tenant_id,
                IdentityMember.identity_id == MediaIdentity.id,
            )
            .exists()
        )

        stmt = (
            select(MediaIdentity)
            .where(
                MediaIdentity.tenant_id == self.tenant_id,
                MediaIdentity.is_deleted.is_(False),
                ~membership_exists,
            )
            .order_by(MediaIdentity.created_at)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def _find_similar_identities(
        self, query_identity: MediaIdentity
    ) -> List[Tuple[MediaIdentity, float]]:
        max_distance = 1 - self.threshold
        distance_expr = MediaIdentity.embedding.cosine_distance(query_identity.embedding).label("distance")

        membership_exists = (
            select(1)
            .where(
                IdentityMember.tenant_id == self.tenant_id,
                IdentityMember.identity_id == MediaIdentity.id,
            )
            .exists()
        )

        stmt = (
            select(MediaIdentity, distance_expr)
            .where(
                MediaIdentity.tenant_id == self.tenant_id,
                MediaIdentity.is_deleted.is_(False),
                ~membership_exists,
                distance_expr < max_distance,
            )
            .order_by(distance_expr)
            .limit(100)
        )

        result = await self.session.execute(stmt)
        rows = result.all()
        identities_with_scores: List[Tuple[MediaIdentity, float]] = []

        for identity, distance in rows:
            similarity = max(0.0, 1 - float(distance))
            identities_with_scores.append((identity, similarity))

        return identities_with_scores

    async def _create_cluster(self, identities_with_scores: List[Tuple[MediaIdentity, float]]) -> IdentityCluster:
        representative = max(identities_with_scores, key=lambda pair: pair[0].confidence)[0]

        cluster = IdentityCluster(
            tenant_id=self.tenant_id,
            label=f"cluster-{uuid4().hex[:8]}",
            representative_identity_id=representative.id,
            identity_count=len(identities_with_scores),
            similarity_threshold=self.threshold,
            clustering_algorithm="pgvector-cosine",
        )
        self.session.add(cluster)
        await self.session.flush()

        for identity, similarity in identities_with_scores:
            member = IdentityMember(
                tenant_id=self.tenant_id,
                cluster_id=cluster.id,
                identity_id=identity.id,
                similarity=similarity,
                created_by_user_id=identity.created_by_user_id,
            )
            self.session.add(member)

        await self.session.commit()
        logger.info("Created cluster %s with %d identities", cluster.id, len(identities_with_scores))
        return cluster

    async def get_cluster_summary(self, cluster_id: UUID) -> Dict[str, object]:
        cluster = await self.session.get(IdentityCluster, cluster_id)
        if not cluster:
            raise ValueError("Cluster not found")

        stmt = (
            select(IdentityMember, MediaIdentity)
            .join(MediaIdentity, IdentityMember.identity_id == MediaIdentity.id)
            .where(IdentityMember.cluster_id == cluster_id)
            .order_by(IdentityMember.similarity.desc())
            .limit(10)
        )

        result = await self.session.execute(stmt)
        sample_rows = result.all()

        member_rows = await self.session.execute(
            select(IdentityMember.identity_id).where(IdentityMember.cluster_id == cluster_id)
        )
        member_ids = [str(row[0]) for row in member_rows]

        return {
            "id": str(cluster.id),
            "label": cluster.label,
            "identity_count": cluster.identity_count,
            "member_ids": member_ids,
            "representative_identity": {
                "media_id": cluster.representative_identity.media_id if cluster.representative_identity else None,
                "bbox": {
                    "x": cluster.representative_identity.bbox_x if cluster.representative_identity else 0,
                    "y": cluster.representative_identity.bbox_y if cluster.representative_identity else 0,
                    "width": cluster.representative_identity.bbox_width if cluster.representative_identity else 0,
                    "height": cluster.representative_identity.bbox_height if cluster.representative_identity else 0,
                },
            },
            "sample_identities": [
                {
                    "id": str(identity.id),
                    "media_id": identity.media_id,
                    "similarity": member.similarity,
                    "bbox": {
                        "x": identity.bbox_x,
                        "y": identity.bbox_y,
                        "width": identity.bbox_width,
                        "height": identity.bbox_height,
                    },
                    "confidence": identity.confidence,
                }
                for member, identity in sample_rows
            ],
        }
