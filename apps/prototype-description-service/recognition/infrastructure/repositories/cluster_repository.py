"""
SQLAlchemy-backed implementation of ClusterRepository.

This is scaffolding only; methods are implemented in Phase 5.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import Select, delete, exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import instance_state

from db.models import IdentityCluster as ClusterModel
from db.models import IdentityClusterRepresentative, IdentityMember, MediaIdentity
from db.settings import get_database_settings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity as DomainIdentity
from recognition.domain.maturity import (
    ClusterMaturityInfo,
    compute_maturity_adjustment,
    compute_maturity_level,
)
from recognition.domain.repositories import ClusterRepository
from recognition.domain.representative import ClusterRepresentative

_DB_SETTINGS = get_database_settings()


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

    async def get_by_tenant(self, tenant_id: str, *, limit: int = 100, offset: int = 0):
        """Fetch clusters for a tenant, with representatives eagerly loaded for discovery."""
        stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel)
            .where(ClusterModel.tenant_id == _coerce_uuid(tenant_id))
            .options(selectinload(ClusterModel.representatives).selectinload(IdentityClusterRepresentative.identity))
            .order_by(ClusterModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

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
        model.identity_count = cluster.member_count
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
        with contextlib.suppress(Exception):
            # Use CONCURRENTLY if possible, but it requires a unique index on the MV
            # For now, standard refresh.
            # SQLite and other databases don't support REFRESH MATERIALIZED VIEW
            await self._session.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))

    async def get_unclustered(self, tenant_id: str):
        """Return media identities not yet assigned to any cluster."""
        tenant_uuid = _coerce_uuid(tenant_id)
        stmt = (
            select(MediaIdentity)
            .where(MediaIdentity.tenant_id == tenant_uuid)
            .where(~exists(select(IdentityMember.id).where(IdentityMember.identity_id == MediaIdentity.id)))
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
                )
            )
        return reps

    async def get_maturity_info(self, cluster_id: str) -> ClusterMaturityInfo | None:
        """Fetch maturity information for a cluster."""
        stmt = (
            select(
                ClusterModel.identity_count,
                ClusterModel.user_confirmed,
                func.count(IdentityClusterRepresentative.id).label("representative_count"),
            )
            .outerjoin(IdentityClusterRepresentative, ClusterModel.id == IdentityClusterRepresentative.cluster_id)
            .where(ClusterModel.id == _coerce_uuid(cluster_id))
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

        # Compute domain logic
        level = compute_maturity_level(
            identity_count=identity_count,
            representative_count=representative_count,
            user_confirmed=user_confirmed,
        )
        adjustment = compute_maturity_adjustment(level)

        return ClusterMaturityInfo(
            level=level,
            identity_count=identity_count,
            representative_count=representative_count,
            user_confirmed=user_confirmed,
            threshold_adjustment=adjustment,
        )

    async def get_member_embeddings(self, cluster_id: str):
        """Return embeddings for members of the cluster."""
        stmt = (
            select(MediaIdentity.embedding)
            .join(IdentityMember, IdentityMember.identity_id == MediaIdentity.id)
            .where(IdentityMember.cluster_id == _coerce_uuid(cluster_id))
        )
        result = await self._session.execute(stmt)
        return [np.asarray(row[0], dtype=np.float32) for row in result.all()]

    async def get_member_identities(self, cluster_id: str) -> list[DomainIdentity]:
        """Return identity records for all members of a cluster."""
        stmt: Select[tuple[MediaIdentity]] = (
            select(MediaIdentity)
            .join(IdentityMember, IdentityMember.identity_id == MediaIdentity.id)
            .where(IdentityMember.cluster_id == _coerce_uuid(cluster_id))
        )
        result = await self._session.execute(stmt)
        return [self._to_domain_identity(model) for model in result.scalars().all()]

    async def assign_identity_to_cluster(self, identity: DomainIdentity, cluster_id: str) -> None:
        """Persist a membership between an identity and cluster."""
        member = IdentityMember(
            tenant_id=_coerce_uuid(identity.tenant_id),
            cluster_id=_coerce_uuid(cluster_id),
            identity_id=_coerce_uuid(identity.id),
            similarity=0.0,
        )
        self._session.add(member)
        await self._session.flush()

    async def add_representative(self, representative) -> None:
        """Persist a representative embedding for a cluster."""
        rep = IdentityClusterRepresentative(
            tenant_id=_coerce_uuid(representative.tenant_id),
            cluster_id=_coerce_uuid(representative.cluster_id),
            identity_id=_coerce_uuid(representative.identity_id),
            embedding=list(representative.embedding),
            quality_score=float(getattr(representative, "quality_score", 1.0)),
            diversity_score=getattr(representative, "diversity_score", None),
        )
        self._session.add(rep)
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
            for rep in model_reps:
                # Extract media_id from identity if loaded, otherwise None
                rep_state = instance_state(rep)
                media_id = None
                if "identity" in rep_state.dict and rep.identity:
                    media_id = rep.identity.media_id
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
            member_count=model.identity_count,
            created_at=model.created_at if isinstance(model.created_at, datetime) else None,
            representative_identity_id=str(model.representative_identity_id)
            if model.representative_identity_id
            else None,
            clustering_algorithm=model.clustering_algorithm,
            user_confirmed=model.user_confirmed,
            representatives=domain_reps,
            centroid=centroid,
        )

    def _to_domain_identity(self, model: MediaIdentity) -> DomainIdentity:
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
            image_phash=model.image_phash,
            cluster_id=None,
        )

    def _to_model(self, cluster: IdentityCluster) -> ClusterModel:
        """Convert a domain cluster into a SQLAlchemy model instance."""
        model_kwargs: dict[str, Any] = {
            "tenant_id": _coerce_uuid(cluster.tenant_id),
            "label": cluster.label,
            "identity_count": cluster.member_count,
            "clustering_algorithm": cluster.clustering_algorithm,
            "user_confirmed": cluster.user_confirmed,
        }

        if cluster.id is not None:
            model_kwargs["id"] = _coerce_uuid(cluster.id)
        if cluster.representative_identity_id:
            model_kwargs["representative_identity_id"] = _coerce_uuid(cluster.representative_identity_id)
        if cluster.created_at:
            model_kwargs["created_at"] = cluster.created_at

        return ClusterModel(**model_kwargs)


def _coerce_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Convert str/UUID to uuid.UUID, generating a stable UUID for short IDs."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        # Fall back to a deterministic UUID so short IDs remain storable.
        return uuid.uuid5(uuid.NAMESPACE_URL, str(value))


async def _ensure_media_identity(session: AsyncSession, tenant_id: uuid.UUID, identity_id: uuid.UUID | None) -> None:
    """Create a placeholder media identity when assigning representatives."""
    if identity_id is None:
        return

    existing = await session.get(MediaIdentity, identity_id)
    if existing:
        return

    media = MediaIdentity(
        id=identity_id,
        tenant_id=tenant_id,
        media_id=abs(identity_id.int) % 1_000_000,
        media_url="http://example.test/media.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=1.0,
        embedding=[0.0] * _DB_SETTINGS.pgvector_dimension,
    )
    session.add(media)
    await session.flush()
    await session.refresh(media)
