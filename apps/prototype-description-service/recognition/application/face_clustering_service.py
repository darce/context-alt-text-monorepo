"""Clustering service for grouping similar faces using pgvector."""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ClusterMember, FaceCluster, MediaFace

logger = logging.getLogger(__name__)


class FaceClusteringService:
    """Cluster similar faces using pgvector cosine similarity."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        similarity_threshold: float = 0.6,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.threshold = similarity_threshold

    async def cluster_faces(self) -> List[FaceCluster]:
        logger.info("Starting face clustering for tenant %s", self.tenant_id)

        unclustered_faces = await self._get_unclustered_faces()
        if not unclustered_faces:
            logger.info("No unclustered faces for tenant %s", self.tenant_id)
            return []

        processed_ids = set()
        clusters: List[FaceCluster] = []

        for seed_face in unclustered_faces:
            if seed_face.id in processed_ids:
                continue

            candidates = await self._find_similar_faces(seed_face)
            if len(candidates) < 2:
                processed_ids.add(seed_face.id)
                continue

            cluster = await self._create_cluster(candidates)
            clusters.append(cluster)

            for face, _ in candidates:
                processed_ids.add(face.id)

        logger.info(
            "Created %d clusters for tenant %s",
            len(clusters),
            self.tenant_id,
        )
        return clusters

    async def _get_unclustered_faces(self) -> List[MediaFace]:
        membership_exists = (
            select(1)
            .where(
                ClusterMember.tenant_id == self.tenant_id,
                ClusterMember.face_id == MediaFace.id,
            )
            .exists()
        )

        stmt = (
            select(MediaFace)
            .where(
                MediaFace.tenant_id == self.tenant_id,
                MediaFace.is_deleted.is_(False),
                ~membership_exists,
            )
            .order_by(MediaFace.created_at)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def _find_similar_faces(self, query_face: MediaFace) -> List[Tuple[MediaFace, float]]:
        max_distance = 1 - self.threshold
        distance_expr = MediaFace.embedding.cosine_distance(query_face.embedding).label("distance")

        membership_exists = (
            select(1)
            .where(
                ClusterMember.tenant_id == self.tenant_id,
                ClusterMember.face_id == MediaFace.id,
            )
            .exists()
        )

        stmt = (
            select(MediaFace, distance_expr)
            .where(
                MediaFace.tenant_id == self.tenant_id,
                MediaFace.is_deleted.is_(False),
                ~membership_exists,
                distance_expr < max_distance,
            )
            .order_by(distance_expr)
            .limit(100)
        )

        result = await self.session.execute(stmt)
        rows = result.all()
        faces_with_scores: List[Tuple[MediaFace, float]] = []

        for face, distance in rows:
            similarity = max(0.0, 1 - float(distance))
            faces_with_scores.append((face, similarity))

        return faces_with_scores

    async def _create_cluster(self, faces_with_scores: List[Tuple[MediaFace, float]]) -> FaceCluster:
        representative = max(faces_with_scores, key=lambda pair: pair[0].confidence)[0]

        cluster = FaceCluster(
            tenant_id=self.tenant_id,
            label=f"cluster-{uuid4().hex[:8]}",
            representative_face_id=representative.id,
            face_count=len(faces_with_scores),
            similarity_threshold=self.threshold,
            clustering_algorithm="pgvector-cosine",
        )
        self.session.add(cluster)
        await self.session.flush()

        for face, similarity in faces_with_scores:
            member = ClusterMember(
                tenant_id=self.tenant_id,
                cluster_id=cluster.id,
                face_id=face.id,
                similarity=similarity,
                created_by_user_id=face.created_by_user_id,
            )
            self.session.add(member)

        await self.session.commit()
        logger.info("Created cluster %s with %d faces", cluster.id, len(faces_with_scores))
        return cluster

    async def get_cluster_summary(self, cluster_id: UUID) -> Dict[str, object]:
        cluster = await self.session.get(FaceCluster, cluster_id)
        if not cluster:
            raise ValueError("Cluster not found")

        stmt = (
            select(ClusterMember, MediaFace)
            .join(MediaFace, ClusterMember.face_id == MediaFace.id)
            .where(ClusterMember.cluster_id == cluster_id)
            .order_by(ClusterMember.similarity.desc())
            .limit(10)
        )

        result = await self.session.execute(stmt)
        sample_rows = result.all()

        member_rows = await self.session.execute(
            select(ClusterMember.face_id).where(ClusterMember.cluster_id == cluster_id)
        )
        member_ids = [str(row[0]) for row in member_rows]

        return {
            "id": str(cluster.id),
            "label": cluster.label,
            "face_count": cluster.face_count,
            "member_ids": member_ids,
            "representative_face": {
                "media_id": cluster.representative_face.media_id if cluster.representative_face else None,
                "bbox": {
                    "x": cluster.representative_face.bbox_x if cluster.representative_face else 0,
                    "y": cluster.representative_face.bbox_y if cluster.representative_face else 0,
                    "width": cluster.representative_face.bbox_width if cluster.representative_face else 0,
                    "height": cluster.representative_face.bbox_height if cluster.representative_face else 0,
                },
            },
            "sample_faces": [
                {
                    "id": str(face.id),
                    "media_id": face.media_id,
                    "similarity": member.similarity,
                    "bbox": {
                        "x": face.bbox_x,
                        "y": face.bbox_y,
                        "width": face.bbox_width,
                        "height": face.bbox_height,
                    },
                    "confidence": face.confidence,
                }
                for member, face in sample_rows
            ],
        }
