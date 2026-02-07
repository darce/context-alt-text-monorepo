"""
SQLAlchemy-backed implementation of ClusterRepository.

This is scaffolding only; methods are implemented in Phase 5.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np
from sqlalchemy import Select, delete, exists, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import instance_state

from db.models import IdentityCluster as ClusterModel
from db.models import IdentityClusterRepresentative, IdentitySuggestion, MediaIdentity
from db.models import IdentityMember as IdentityMemberModel
from db.settings import get_database_settings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity as DomainIdentity
from recognition.domain.maturity import ClusterMaturityInfo, compute_maturity_adjustment, compute_maturity_level
from recognition.domain.repositories import ClusterRepository
from recognition.domain.repositories import IdentityMember as DomainMember
from recognition.domain.representative import ClusterRepresentative
from recognition.infrastructure.repositories._helpers import coerce_uuid as _coerce_uuid
from recognition.infrastructure.repositories._helpers import ensure_media_identity as _ensure_media_identity
from recognition.shared.db.helpers import execute_dml, get_rowcount

_DB_SETTINGS = get_database_settings()
logger = logging.getLogger(__name__)
_TOP_UNLABELED_FALLBACK_REP_LIMIT = 4

if TYPE_CHECKING:
    from recognition.application.settings.clustering import MaturitySettings


class SqlAlchemyClusterRepository(ClusterRepository):
    """Persist clusters using an async SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, cluster_id: str):
        """Fetch a cluster by ID."""
        stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel)
            .where(ClusterModel.id == _coerce_uuid(cluster_id))
            .options(selectinload(ClusterModel.members))
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def get_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        labeled_only: bool = False,
        search: str | None = None,
    ):
        """Fetch clusters for a tenant, with representatives eagerly loaded for discovery."""
        stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel)
            .where(ClusterModel.tenant_id == _coerce_uuid(tenant_id))
            .options(
                selectinload(ClusterModel.representatives).selectinload(IdentityClusterRepresentative.identity),
                selectinload(ClusterModel.centroid_data),
            )
            .order_by(ClusterModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        if labeled_only:
            stmt = stmt.where(ClusterModel.label.isnot(None))
            stmt = stmt.where(ClusterModel.user_confirmed.is_(True))

        if search:
            escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(ClusterModel.label.ilike(f"%{escaped_search}%", escape="\\"))

        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def get_top_unlabeled(
        self,
        tenant_id: str,
        limit: int = 10,
        min_identity_count: int = 2,
    ) -> list[IdentityCluster]:
        """Fetch top unlabeled clusters globally by size, with representatives for thumbnails.

        This endpoint is productivity-first: prioritize the largest unlabeled clusters
        across the tenant (not latest-run scoped), so users label the most observations first.
        Dismissed clusters and singletons are excluded.
        """
        from sqlalchemy import or_

        tenant_uuid = _coerce_uuid(tenant_id)
        if tenant_uuid is None:
            return []

        accepted_member_suggestion_exists = (
            select(1)
            .select_from(IdentityMemberModel)
            .join(
                IdentitySuggestion,
                IdentitySuggestion.identity_id == IdentityMemberModel.identity_id,
            )
            .where(IdentityMemberModel.cluster_id == ClusterModel.id)
            .where(IdentitySuggestion.tenant_id == tenant_uuid)
            .where(IdentitySuggestion.resolution == "accepted")
            .where(IdentitySuggestion.suggested_cluster_id != ClusterModel.id)
        )

        stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel)
            .where(ClusterModel.tenant_id == tenant_uuid)
            .where(ClusterModel.user_confirmed.is_(False))
            .where(or_(ClusterModel.label.is_(None), ClusterModel.label.startswith("cluster-")))
            .where(ClusterModel.identity_count >= min_identity_count)
            .where(ClusterModel.dismissed_at.is_(None))
            .where(~exists(accepted_member_suggestion_exists))
            .options(
                selectinload(ClusterModel.representatives).selectinload(IdentityClusterRepresentative.identity),
            )
            .order_by(ClusterModel.identity_count.desc(), ClusterModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        results = [self._to_domain(row) for row in result.scalars().all()]
        clusters_requiring_top_up = [
            cluster.id
            for cluster in results
            if cluster.id and len(cluster.representatives or []) < _TOP_UNLABELED_FALLBACK_REP_LIMIT
        ]
        topped_up_clusters = 0
        if clusters_requiring_top_up:
            fallback_representatives = await self._get_member_fallback_representatives(
                clusters_requiring_top_up,
                max_per_cluster=_TOP_UNLABELED_FALLBACK_REP_LIMIT,
            )
            for cluster in results:
                if not cluster.id:
                    continue
                existing_representatives = list(cluster.representatives or [])
                if len(existing_representatives) >= _TOP_UNLABELED_FALLBACK_REP_LIMIT:
                    continue

                member_reps = fallback_representatives.get(cluster.id, [])
                if not member_reps:
                    continue

                merged_representatives: list[ClusterRepresentative] = []
                seen_identity_ids: set[str] = set()
                for representative in [*existing_representatives, *member_reps]:
                    identity_id = str(representative.identity_id)
                    if identity_id in seen_identity_ids:
                        continue
                    seen_identity_ids.add(identity_id)
                    merged_representatives.append(representative)
                    if len(merged_representatives) >= _TOP_UNLABELED_FALLBACK_REP_LIMIT:
                        break

                if len(merged_representatives) > len(existing_representatives):
                    cluster.representatives = merged_representatives
                    topped_up_clusters += 1

        logger.info(
            "Top clusters (size-priority): tenant_id=%s returned=%d limit=%d min_identity_count=%d rep_topup_candidates=%d rep_topup_applied=%d",
            tenant_id,
            len(results),
            limit,
            min_identity_count,
            len(clusters_requiring_top_up),
            topped_up_clusters,
        )
        return results

    async def _get_member_fallback_representatives(
        self,
        cluster_ids: Sequence[str],
        *,
        max_per_cluster: int,
    ) -> dict[str, list[ClusterRepresentative]]:
        """Build thumbnail-capable fallback representatives from top-scoring cluster members."""
        cluster_uuids = [_coerce_uuid(cluster_id) for cluster_id in cluster_ids]
        cluster_uuids = [cluster_id for cluster_id in cluster_uuids if cluster_id is not None]
        if not cluster_uuids:
            return {}

        stmt = (
            select(
                IdentityMemberModel.cluster_id,
                IdentityMemberModel.id,
                IdentityMemberModel.identity_id,
                IdentityMemberModel.similarity,
                IdentityMemberModel.assigned_at,
                MediaIdentity.media_id,
                MediaIdentity.media_url,
                MediaIdentity.bbox_x,
                MediaIdentity.bbox_y,
                MediaIdentity.bbox_width,
                MediaIdentity.bbox_height,
                MediaIdentity.thumbnail_url,
            )
            .join(MediaIdentity, MediaIdentity.id == IdentityMemberModel.identity_id)
            .where(IdentityMemberModel.cluster_id.in_(cluster_uuids))
            .order_by(
                IdentityMemberModel.cluster_id,
                IdentityMemberModel.similarity.desc(),
                IdentityMemberModel.assigned_at.asc(),
            )
        )
        result = await self._session.execute(stmt)
        fallback_by_cluster: dict[str, list[ClusterRepresentative]] = defaultdict(list)
        now = datetime.now(tz=UTC)
        for row in result:
            cluster_key = str(row.cluster_id)
            existing = fallback_by_cluster[cluster_key]
            if len(existing) >= max_per_cluster:
                continue

            assigned_at = row.assigned_at if isinstance(row.assigned_at, datetime) else now
            existing.append(
                ClusterRepresentative(
                    id=str(row.id),
                    cluster_id=cluster_key,
                    identity_id=str(row.identity_id),
                    embedding=np.zeros(_DB_SETTINGS.pgvector_dimension, dtype=np.float32),
                    created_at=assigned_at,
                    quality_score=float(row.similarity),
                    media_id=int(row.media_id) if row.media_id is not None else None,
                    media_url=row.media_url,
                    bbox_x=int(row.bbox_x) if row.bbox_x is not None else None,
                    bbox_y=int(row.bbox_y) if row.bbox_y is not None else None,
                    bbox_width=int(row.bbox_width) if row.bbox_width is not None else None,
                    bbox_height=int(row.bbox_height) if row.bbox_height is not None else None,
                    thumbnail_url=row.thumbnail_url,
                )
            )

        return dict(fallback_by_cluster)

    async def dismiss_cluster(self, cluster_id: str) -> bool:
        """Mark a cluster as dismissed so it no longer appears in the naming queue.

        Args:
            cluster_id: UUID of the cluster to dismiss.

        Returns:
            True if a cluster was found and dismissed, False otherwise.
        """
        cluster_uuid = _coerce_uuid(cluster_id)
        if cluster_uuid is None:
            return False
        stmt = (
            update(ClusterModel)
            .where(ClusterModel.id == cluster_uuid)
            .where(ClusterModel.dismissed_at.is_(None))
            .values(dismissed_at=datetime.now(tz=UTC))
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def undismiss_cluster(self, cluster_id: str) -> bool:
        """Clear the dismissed flag on a cluster to resurface it in the naming queue.

        Args:
            cluster_id: UUID of the cluster to undismiss.

        Returns:
            True if a cluster was found and undismissed, False otherwise.
        """
        cluster_uuid = _coerce_uuid(cluster_id)
        if cluster_uuid is None:
            return False
        stmt = (
            update(ClusterModel)
            .where(ClusterModel.id == cluster_uuid)
            .where(ClusterModel.dismissed_at.is_not(None))
            .values(dismissed_at=None)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def get_labeled_with_representatives(
        self,
        tenant_id: str,
    ) -> list[tuple[IdentityCluster, list[ClusterRepresentative]]]:
        """Fetch labeled clusters with representatives via eager loading."""
        tenant_uuid = _coerce_uuid(tenant_id)
        if tenant_uuid is None:
            return []

        stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel)
            .where(ClusterModel.tenant_id == tenant_uuid)
            .where(ClusterModel.user_confirmed.is_(True))
            .where(ClusterModel.label.is_not(None))
            .where(~ClusterModel.label.startswith("cluster-"))
            .options(selectinload(ClusterModel.representatives).selectinload(IdentityClusterRepresentative.identity))
        )
        result = await self._session.execute(stmt)
        output: list[tuple[IdentityCluster, list[ClusterRepresentative]]] = []
        for model in result.scalars().all():
            cluster = self._to_domain(model)
            representatives = list(cluster.representatives or [])
            output.append((cluster, representatives))
        return output

    async def save(self, cluster):
        """Persist a new cluster."""
        tenant_uuid = _coerce_uuid(cluster.tenant_id)
        if tenant_uuid is None:
            raise ValueError("tenant_id must be a valid UUID-compatible string")

        if cluster.representative_identity_id:
            await _ensure_media_identity(
                self._session,
                tenant_uuid,
                _coerce_uuid(cluster.representative_identity_id),
            )
        model = self._to_model(cluster)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def update(self, cluster):
        """Update cluster metadata."""
        stmt = select(ClusterModel).where(ClusterModel.id == _coerce_uuid(cluster.id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise ValueError(f"Cluster not found: {cluster.id}")

        model.label = cluster.label
        model.user_confirmed = cluster.user_confirmed
        model.identity_count = cluster.identity_count
        rep_uuid = _coerce_uuid(cluster.representative_identity_id) if cluster.representative_identity_id else None
        if rep_uuid is not None:
            await _ensure_media_identity(self._session, model.tenant_id, rep_uuid)
        model.representative_identity_id = rep_uuid
        if cluster.clustering_algorithm:
            model.clustering_algorithm = cluster.clustering_algorithm

        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def delete(self, cluster_id: str) -> None:
        """Delete a cluster."""
        stmt = select(ClusterModel).where(ClusterModel.id == _coerce_uuid(cluster_id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()

    async def refresh_centroids_view(self) -> None:
        """Refresh the materialized view for cluster centroids.

        This is a PostgreSQL-specific operation. SQLite and other databases
        will silently skip this operation.
        """
        try:
            # Use CONCURRENTLY if possible, but it requires a unique index on the MV
            # For now, standard refresh.
            # SQLite and other databases don't support REFRESH MATERIALIZED VIEW
            await self._session.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
        except Exception:
            logger.warning("Failed to refresh centroid materialized view", exc_info=True)

    async def refresh_centroids_view_concurrent(self) -> None:
        """Refresh the materialized view concurrently.

        This allows reads to continue during the refresh and avoids locking the table.
        It requires a unique index on the MV, which is created in the migration.
        """
        try:
            # Use CONCURRENTLY for background scheduled refreshes
            # This is critical to avoid locking the MV during updates
            await self._session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_identity_cluster_centroids"))
        except Exception:
            logger.warning("Failed to refresh centroid materialized view concurrently", exc_info=True)

    async def get_unclustered(self, tenant_id: str):
        """Return media identities not yet assigned to any cluster."""
        tenant_uuid = _coerce_uuid(tenant_id)
        stmt = (
            select(MediaIdentity)
            .where(MediaIdentity.tenant_id == tenant_uuid)
            .where(~exists(select(IdentityMemberModel.id).where(IdentityMemberModel.identity_id == MediaIdentity.id)))
        )
        result = await self._session.execute(stmt)
        identities = result.scalars().all()
        return [self._to_domain_identity(model) for model in identities]

    async def get_representative_count(self, cluster_id: str) -> int:
        """Count representatives for a cluster."""
        stmt = select(func.count(IdentityClusterRepresentative.id)).where(
            IdentityClusterRepresentative.cluster_id == _coerce_uuid(cluster_id)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_all_representatives(self, cluster_id: str) -> list[ClusterRepresentative]:
        """Return all representative domain objects for a cluster."""
        stmt = (
            select(IdentityClusterRepresentative, MediaIdentity.image_phash, MediaIdentity.media_id)
            .join(MediaIdentity, MediaIdentity.id == IdentityClusterRepresentative.identity_id)
            .where(IdentityClusterRepresentative.cluster_id == _coerce_uuid(cluster_id))
        )
        result = await self._session.execute(stmt)
        reps = []
        for model_rep, phash, media_id in result:
            reps.append(
                ClusterRepresentative(
                    id=str(model_rep.id),
                    cluster_id=str(model_rep.cluster_id),
                    identity_id=str(model_rep.identity_id),
                    embedding=np.array(model_rep.embedding, dtype=np.float32),
                    created_at=model_rep.created_at,
                    tenant_id=str(model_rep.tenant_id),
                    quality_score=float(model_rep.quality_score),
                    diversity_score=float(model_rep.diversity_score) if model_rep.diversity_score else None,
                    media_id=media_id,
                    image_phash=phash,
                    is_user_selected=bool(model_rep.is_user_selected),
                    is_provisional=bool(model_rep.is_provisional),
                    pose_pitch=float(model_rep.pose_pitch) if model_rep.pose_pitch is not None else None,
                    pose_yaw=float(model_rep.pose_yaw) if model_rep.pose_yaw is not None else None,
                    pose_roll=float(model_rep.pose_roll) if model_rep.pose_roll is not None else None,
                )
            )
        return reps

    async def mark_representative_user_selected(
        self,
        representative_id: str,
        is_selected: bool = True,
    ) -> None:
        """Mark a representative as user-selected (pinned)."""
        stmt = select(IdentityClusterRepresentative).where(
            IdentityClusterRepresentative.id == _coerce_uuid(representative_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise ValueError(f"Representative {representative_id} not found")
        model.is_user_selected = is_selected
        await self._session.flush()

    async def get_user_selected_representatives(
        self,
        cluster_id: str,
    ) -> list[ClusterRepresentative]:
        """Get all user-selected representatives for a cluster."""
        stmt = (
            select(IdentityClusterRepresentative, MediaIdentity.image_phash, MediaIdentity.media_id)
            .join(MediaIdentity, MediaIdentity.id == IdentityClusterRepresentative.identity_id)
            .where(IdentityClusterRepresentative.cluster_id == _coerce_uuid(cluster_id))
            .where(IdentityClusterRepresentative.is_user_selected.is_(True))
        )
        result = await self._session.execute(stmt)
        reps = []
        for model_rep, _phash, _media_id in result:
            reps.append(
                ClusterRepresentative(
                    id=str(model_rep.id),
                    cluster_id=str(model_rep.cluster_id),
                    identity_id=str(model_rep.identity_id),
                    embedding=np.array(model_rep.embedding, dtype=np.float32),
                    created_at=model_rep.created_at,
                    tenant_id=str(model_rep.tenant_id),
                    quality_score=float(model_rep.quality_score),
                    diversity_score=float(model_rep.diversity_score) if model_rep.diversity_score else None,
                    is_user_selected=bool(model_rep.is_user_selected),
                    is_provisional=bool(model_rep.is_provisional),
                    pose_pitch=float(model_rep.pose_pitch) if model_rep.pose_pitch is not None else None,
                    pose_yaw=float(model_rep.pose_yaw) if model_rep.pose_yaw is not None else None,
                    pose_roll=float(model_rep.pose_roll) if model_rep.pose_roll is not None else None,
                )
            )
        return reps

    async def confirm_provisional_representatives(self, cluster_id: str) -> int:
        """Mark all provisional representatives in a cluster as confirmed."""
        from sqlalchemy import update

        stmt = (
            update(IdentityClusterRepresentative)
            .where(IdentityClusterRepresentative.cluster_id == _coerce_uuid(cluster_id))
            .where(IdentityClusterRepresentative.is_provisional.is_(True))
            .values(is_provisional=False)
        )
        result = await execute_dml(self._session, stmt)
        await self._session.flush()
        return get_rowcount(result)

    async def confirm_all_provisional_reps(self, tenant_id: str) -> int:
        """Mark all provisional representatives for a tenant as confirmed."""
        from sqlalchemy import update

        stmt = (
            update(IdentityClusterRepresentative)
            .where(IdentityClusterRepresentative.tenant_id == _coerce_uuid(tenant_id))
            .where(IdentityClusterRepresentative.is_provisional.is_(True))
            .values(is_provisional=False)
        )
        result = await execute_dml(self._session, stmt)
        await self._session.flush()
        return get_rowcount(result)

    async def cleanup_orphaned_provisional_reps(self, tenant_id: str) -> int:
        """Remove provisional reps from clusters with no active batch."""
        stmt = delete(IdentityClusterRepresentative).where(
            IdentityClusterRepresentative.tenant_id == _coerce_uuid(tenant_id),
            IdentityClusterRepresentative.is_provisional.is_(True),
        )
        result = await execute_dml(self._session, stmt)
        await self._session.flush()
        return get_rowcount(result)

    async def get_maturity_info(self, cluster_id: str, *, settings: MaturitySettings) -> ClusterMaturityInfo | None:
        """Fetch maturity information for a cluster including pose coverage."""
        cluster_uuid = _coerce_uuid(cluster_id)
        if cluster_uuid is None:
            return None

        # Query cluster info + representative count
        stmt = (
            select(
                ClusterModel.identity_count,
                ClusterModel.user_confirmed,
                func.count(IdentityClusterRepresentative.id).label("representative_count"),
            )
            .outerjoin(IdentityClusterRepresentative, ClusterModel.id == IdentityClusterRepresentative.cluster_id)
            .where(ClusterModel.id == cluster_uuid)
            .group_by(ClusterModel.id)
        )
        result = await self._session.execute(stmt)
        row = result.first()

        if not row:
            return None

        # Extract values
        identity_count = int(row.identity_count)
        user_confirmed = bool(row.user_confirmed)
        representative_count = int(row.representative_count)

        # Compute pose bucket coverage from representatives
        pose_bucket_coverage = await self._compute_pose_bucket_coverage(cluster_uuid, settings)

        # Compute domain logic
        level = compute_maturity_level(
            identity_count=identity_count,
            representative_count=representative_count,
            user_confirmed=user_confirmed,
            settings=settings,
            pose_bucket_coverage=pose_bucket_coverage,
        )
        adjustment = compute_maturity_adjustment(level, settings=settings)

        return ClusterMaturityInfo(
            level=level,
            identity_count=identity_count,
            representative_count=representative_count,
            user_confirmed=user_confirmed,
            threshold_adjustment=adjustment,
            pose_bucket_coverage=pose_bucket_coverage,
        )

    async def _compute_pose_bucket_coverage(self, cluster_id: uuid.UUID, settings: MaturitySettings) -> float:
        """Compute the fraction of pose buckets filled by cluster representatives.

        Args:
            cluster_id: Cluster UUID.
            settings: Maturity settings with bucket size and total buckets.

        Returns:
            Fraction of pose buckets covered (0.0 to 1.0).
        """
        # Get representative identities with pose data
        stmt = (
            select(MediaIdentity.pose_pitch, MediaIdentity.pose_yaw)
            .join(IdentityClusterRepresentative, MediaIdentity.id == IdentityClusterRepresentative.identity_id)
            .where(IdentityClusterRepresentative.cluster_id == cluster_id)
            .where(MediaIdentity.pose_pitch.isnot(None))
            .where(MediaIdentity.pose_yaw.isnot(None))
        )
        result = await self._session.execute(stmt)
        rows = result.all()

        if not rows:
            return 0.0

        # Count unique pose buckets
        bucket_size = settings.pose_bucket_size
        filled_buckets: set[tuple[int, int]] = set()
        for pose_pitch, pose_yaw in rows:
            bucket = (int(pose_pitch // bucket_size), int(pose_yaw // bucket_size))
            filled_buckets.add(bucket)

        # Return coverage fraction
        total_buckets = settings.total_pose_buckets
        return len(filled_buckets) / total_buckets if total_buckets > 0 else 0.0

    async def get_curriculum_t(self, cluster_id: str) -> float | None:
        """Fetch the curriculum bias parameter for a cluster."""
        stmt = select(ClusterModel.curriculum_t).where(ClusterModel.id == _coerce_uuid(cluster_id))
        result = await self._session.execute(stmt)
        value = result.scalar_one_or_none()
        return float(value) if value is not None else None

    async def set_curriculum_t(self, cluster_id: str, value: float) -> None:
        """Persist the curriculum bias parameter for a cluster."""
        stmt = (
            update(ClusterModel)
            .where(ClusterModel.id == _coerce_uuid(cluster_id))
            .values(curriculum_t=value, curriculum_t_updated_at=datetime.now(tz=UTC))
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def get_member_embeddings(self, cluster_id: str):
        """Return embeddings for members of the cluster."""
        stmt = (
            select(MediaIdentity.embedding)
            .join(IdentityMemberModel, IdentityMemberModel.identity_id == MediaIdentity.id)
            .where(IdentityMemberModel.cluster_id == _coerce_uuid(cluster_id))
        )
        result = await self._session.execute(stmt)
        return [np.asarray(row[0], dtype=np.float32) for row in result.all()]

    async def get_member_identities(self, cluster_id: str) -> list[DomainIdentity]:
        """Return identity records for all members of a cluster."""
        stmt: Select[tuple[MediaIdentity]] = (
            select(MediaIdentity)
            .join(IdentityMemberModel, IdentityMemberModel.identity_id == MediaIdentity.id)
            .where(IdentityMemberModel.cluster_id == _coerce_uuid(cluster_id))
        )
        result = await self._session.execute(stmt)
        return [self._to_domain_identity(model, cluster_id=cluster_id) for model in result.scalars().all()]

    async def get_member_identities_for_clusters(self, cluster_ids: Sequence[str]) -> dict[str, list[DomainIdentity]]:
        """Return identity records for members across multiple clusters, grouped by cluster."""
        cluster_uuids = [_coerce_uuid(cluster_id) for cluster_id in cluster_ids]
        cluster_uuids = [cluster_id for cluster_id in cluster_uuids if cluster_id is not None]
        if not cluster_uuids:
            return {}

        stmt: Select[tuple[MediaIdentity, uuid.UUID]] = (
            select(MediaIdentity, IdentityMemberModel.cluster_id)
            .join(IdentityMemberModel, IdentityMemberModel.identity_id == MediaIdentity.id)
            .where(IdentityMemberModel.cluster_id.in_(cluster_uuids))
            .where(MediaIdentity.embedding.isnot(None))
        )
        result = await self._session.execute(stmt)
        grouped: dict[str, list[DomainIdentity]] = defaultdict(list)
        for model, cluster_id in result.all():
            if not cluster_id:
                continue
            cluster_key = str(cluster_id)
            grouped[cluster_key].append(self._to_domain_identity(model, cluster_id=cluster_key))
        return dict(grouped)

    async def get_member_identities_with_similarity(self, cluster_id: str) -> list[tuple[MediaIdentity, float]]:
        """Return identity ORM records with their membership similarity for a cluster.

        Unlike get_member_identities, this returns the raw ORM model with thumbnail_url
        and the similarity score from the member record, for API responses.
        """
        stmt = (
            select(MediaIdentity, IdentityMemberModel.similarity)
            .join(IdentityMemberModel, IdentityMemberModel.identity_id == MediaIdentity.id)
            .where(IdentityMemberModel.cluster_id == _coerce_uuid(cluster_id))
        )
        result = await self._session.execute(stmt)
        return [(row[0], float(row[1])) for row in result.all()]

    async def get_roster_entry_name(self, roster_id: str) -> str | None:
        """Resolve a roster entry UUID to display name."""
        roster_uuid = _coerce_uuid(roster_id)
        if roster_uuid is None:
            return None

        try:
            result = await self._session.execute(
                text("SELECT name FROM roster_entries WHERE id = :rid LIMIT 1"),
                {"rid": str(roster_uuid)},
            )
        except Exception as exc:
            logger.debug("Roster lookup failed for roster_id=%s err=%s", roster_id, exc)
            return None

        roster_name = result.scalar_one_or_none()
        if roster_name is None:
            return None
        normalized = str(roster_name).strip()
        return normalized or None

    async def get_members(self, cluster_id: str) -> list[DomainMember]:
        """Return member records for a cluster."""
        stmt: Select[tuple[IdentityMemberModel]] = select(IdentityMemberModel).where(
            IdentityMemberModel.cluster_id == _coerce_uuid(cluster_id)
        )
        result = await self._session.execute(stmt)
        return [
            DomainMember(
                id=str(member.id),
                cluster_id=str(member.cluster_id),
                identity_id=str(member.identity_id),
                similarity=float(member.similarity),
                tenant_id=str(member.tenant_id) if member.tenant_id else None,
                assigned_at=member.assigned_at,
            )
            for member in result.scalars().all()
        ]

    async def get_singleton_identities(
        self,
        tenant_id: str,
        *,
        limit: int | None = None,
    ) -> list[DomainIdentity]:
        """Fetch identities that belong to singleton clusters for a tenant."""
        stmt: Select[tuple[MediaIdentity, uuid.UUID]] = (
            select(MediaIdentity, IdentityMemberModel.cluster_id)
            .join(IdentityMemberModel, IdentityMemberModel.identity_id == MediaIdentity.id)
            .join(ClusterModel, ClusterModel.id == IdentityMemberModel.cluster_id)
            .where(ClusterModel.tenant_id == _coerce_uuid(tenant_id))
            .where(ClusterModel.identity_count == 1)
            .where(ClusterModel.user_confirmed.is_(False))
            .where(MediaIdentity.embedding.isnot(None))
            .order_by(ClusterModel.created_at.desc())
        )
        if limit:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        identities: list[DomainIdentity] = []
        for model, cluster_id in result.all():
            identities.append(
                self._to_domain_identity(
                    model,
                    cluster_id=str(cluster_id) if cluster_id else None,
                )
            )
        return identities

    async def assign_identity_to_cluster(self, identity: DomainIdentity, cluster_id: str) -> None:
        """Persist a membership between an identity and cluster."""
        member = IdentityMemberModel(
            tenant_id=_coerce_uuid(identity.tenant_id),
            cluster_id=_coerce_uuid(cluster_id),
            identity_id=_coerce_uuid(identity.id),
            similarity=0.0,
        )
        self._session.add(member)
        await self._session.flush()

    async def add_representative(self, representative: ClusterRepresentative) -> None:
        """Persist a representative embedding for a cluster."""
        rep = IdentityClusterRepresentative(
            id=_coerce_uuid(representative.id) if representative.id else None,
            tenant_id=_coerce_uuid(representative.tenant_id),
            cluster_id=_coerce_uuid(representative.cluster_id),
            identity_id=_coerce_uuid(representative.identity_id),
            embedding=list(representative.embedding),
            quality_score=float(getattr(representative, "quality_score", 1.0)),
            diversity_score=getattr(representative, "diversity_score", None),
            is_user_selected=getattr(representative, "is_user_selected", False),
            is_provisional=getattr(representative, "is_provisional", False),
            pose_pitch=float(representative.pose_pitch) if representative.pose_pitch is not None else None,
            pose_yaw=float(representative.pose_yaw) if representative.pose_yaw is not None else None,
            pose_roll=float(representative.pose_roll) if representative.pose_roll is not None else None,
        )
        self._session.add(rep)
        await self._session.flush()

    async def remove_representative(self, representative_id: str) -> None:
        """Remove a specific representative."""
        stmt = delete(IdentityClusterRepresentative).where(
            IdentityClusterRepresentative.id == _coerce_uuid(representative_id)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def clear_representatives(self, cluster_id: str) -> None:
        """Remove all stored representatives for a cluster."""
        stmt = delete(IdentityClusterRepresentative).where(
            IdentityClusterRepresentative.cluster_id == _coerce_uuid(cluster_id)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def count_labeled(self) -> int:
        """Count clusters with user-provided labels (not auto-generated like 'cluster-xxx').

        Uses RLS (Row Level Security) to filter by current tenant context.
        """
        stmt = select(func.count(ClusterModel.id)).where(
            ClusterModel.label.is_not(None),
            ~ClusterModel.label.startswith("cluster-"),
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    def _to_domain(self, model: ClusterModel) -> IdentityCluster:
        """Convert a SQLAlchemy model into the domain object."""
        # Convert representatives only if eagerly loaded (via selectinload)
        # Check if the relationship has been loaded to avoid triggering lazy load
        domain_reps: list[ClusterRepresentative] = []
        state = instance_state(model)
        if "representatives" in state.dict:
            # Relationship was eagerly loaded, safe to access
            model_reps = model.representatives
            representative_count = len(model_reps)

            # Compute pose buckets summary for the whole cluster
            filled_buckets = set()
            bucket_size = 30.0  # Default from ClusteringSettings
            for r in model_reps:
                if r.identity:
                    pitch = r.identity.pose_pitch
                    yaw = r.identity.pose_yaw
                    if pitch is not None and yaw is not None:
                        filled_buckets.add((int(pitch // bucket_size), int(yaw // bucket_size)))

            for rep in model_reps:
                # Extract debug metrics from identity if loaded
                rep_state = instance_state(rep)
                debug_metrics = None
                media_id = None
                media_url = None
                bbox_x = None
                bbox_y = None
                bbox_width = None
                bbox_height = None
                identity_loaded = "identity" in rep_state.dict and rep.identity is not None
                if identity_loaded:
                    identity = rep.identity
                    media_id = identity.media_id
                    media_url = identity.media_url
                    bbox_x = int(identity.bbox_x) if identity.bbox_x is not None else None
                    bbox_y = int(identity.bbox_y) if identity.bbox_y is not None else None
                    bbox_width = int(identity.bbox_width) if identity.bbox_width is not None else None
                    bbox_height = int(identity.bbox_height) if identity.bbox_height is not None else None
                    logger.debug(
                        "Loaded representative identity pose rep_id=%s identity_id=%s pose_pitch=%s pose_yaw=%s",
                        rep.id,
                        identity.id,
                        identity.pose_pitch,
                        identity.pose_yaw,
                    )
                    debug_metrics = {
                        "pose": {
                            "pitch": float(identity.pose_pitch or 0),
                            "yaw": float(identity.pose_yaw or 0),
                            "roll": float(identity.pose_roll or 0),
                        },
                        "age": float(identity.age or 0),
                        "gender": "male" if identity.gender == 1 else "female",
                        "det_score": float(identity.confidence),
                        "bbox_area": int(identity.bbox_width * identity.bbox_height),
                        "landmark_quality": float(identity.quality_score or 1.0),
                        "clustering_method": None,
                        "clustering_algorithm": None,
                        "similarity_threshold": None,
                        "match_similarity": None,
                        "representative_count": representative_count,
                        "pose_buckets": {
                            "filled": len(filled_buckets),
                            "total": 13,  # 10 base + 3 bonus
                            "current_bucket": (
                                int(identity.pose_pitch // bucket_size),
                                int(identity.pose_yaw // bucket_size),
                            )
                            if identity.pose_pitch is not None and identity.pose_yaw is not None
                            else None,
                        },
                    }
                else:
                    logger.debug(
                        "Representative identity not loaded rep_id=%s identity_loaded=%s",
                        rep.id,
                        identity_loaded,
                    )
                domain_reps.append(
                    ClusterRepresentative(
                        id=str(rep.id),
                        cluster_id=str(rep.cluster_id),
                        identity_id=str(rep.identity_id),
                        embedding=np.array(rep.embedding, dtype=np.float32),
                        created_at=rep.created_at,
                        tenant_id=str(rep.tenant_id) if rep.tenant_id else None,
                        quality_score=float(rep.quality_score),
                        diversity_score=float(rep.diversity_score) if rep.diversity_score else None,
                        media_id=media_id,
                        media_url=media_url,
                        bbox_x=bbox_x,
                        bbox_y=bbox_y,
                        bbox_width=bbox_width,
                        bbox_height=bbox_height,
                        thumbnail_url=identity.thumbnail_url if identity_loaded else None,
                        is_user_selected=bool(rep.is_user_selected),
                        is_provisional=bool(rep.is_provisional),
                        debug_metrics=debug_metrics,
                    )
                )

        # Extract centroid from materialized view relationship if available
        centroid = None
        if hasattr(model, "centroid_data") and model.centroid_data is not None:
            centroid = np.array(model.centroid_data.centroid, dtype=np.float32)

        return IdentityCluster(
            id=str(model.id) if model.id else None,
            tenant_id=str(model.tenant_id),
            label=model.label,
            is_labeled=bool(model.label),
            identity_count=model.identity_count,
            created_at=model.created_at if isinstance(model.created_at, datetime) else None,
            representative_identity_id=str(model.representative_identity_id)
            if model.representative_identity_id
            else None,
            clustering_algorithm=model.clustering_algorithm,
            user_confirmed=model.user_confirmed,
            dismissed_at=model.dismissed_at if isinstance(model.dismissed_at, datetime) else None,
            representatives=domain_reps,
            centroid=centroid,
        )

    def _to_domain_identity(self, model: MediaIdentity, *, cluster_id: str | None = None) -> DomainIdentity:
        """Convert MediaIdentity ORM model to domain representation."""
        return DomainIdentity(
            id=str(model.id),
            tenant_id=str(model.tenant_id),
            media_id=str(model.media_id),
            embedding=np.asarray(model.embedding, dtype=np.float32),
            confidence=float(model.confidence),
            bbox_width=int(model.bbox_width),
            bbox_height=int(model.bbox_height),
            bbox_x=int(model.bbox_x),
            bbox_y=int(model.bbox_y),
            pose_pitch=float(model.pose_pitch) if model.pose_pitch is not None else None,
            pose_yaw=float(model.pose_yaw) if model.pose_yaw is not None else None,
            pose_roll=float(model.pose_roll) if model.pose_roll is not None else None,
            image_phash=model.image_phash,
            cluster_id=cluster_id,
        )

    def _to_model(self, cluster: IdentityCluster) -> ClusterModel:
        """Convert a domain cluster into a SQLAlchemy model instance."""
        model_kwargs: dict[str, Any] = {
            "tenant_id": _coerce_uuid(cluster.tenant_id),
            "label": cluster.label,
            "identity_count": cluster.identity_count,
            "clustering_algorithm": cluster.clustering_algorithm,
            "user_confirmed": cluster.user_confirmed,
        }

        if cluster.id is not None:
            model_kwargs["id"] = _coerce_uuid(cluster.id)
        if cluster.representative_identity_id:
            model_kwargs["representative_identity_id"] = _coerce_uuid(cluster.representative_identity_id)
        if cluster.created_at:
            model_kwargs["created_at"] = cluster.created_at
        if cluster.dismissed_at:
            model_kwargs["dismissed_at"] = cluster.dismissed_at

        return ClusterModel(**model_kwargs)
