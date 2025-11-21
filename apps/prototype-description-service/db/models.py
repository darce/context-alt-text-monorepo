"""SQLAlchemy models for the prototype description service."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.settings import get_database_settings

_DB_SETTINGS = get_database_settings()


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    site_url: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    media_identities: Mapped[list["MediaIdentity"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    identity_clusters: Mapped[list["IdentityCluster"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class MediaIdentity(Base):
    __tablename__ = "media_identities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    media_id: Mapped[int] = mapped_column(Integer, nullable=False)
    media_url: Mapped[str] = mapped_column(Text, nullable=False)

    bbox_x: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_y: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_width: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_height: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    embedding: Mapped[list[float]] = mapped_column(
        Vector(_DB_SETTINGS.pgvector_dimension), nullable=False
    )
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    tenant: Mapped[Tenant] = relationship(back_populates="media_identities")
    cluster_memberships: Mapped[list["IdentityMember"]] = relationship(
        back_populates="identity", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "media_id", "bbox_x", "bbox_y", name="unique_media_identity"
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("idx_media_identities_tenant", "tenant_id"),
        Index(
            "idx_media_identities_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class IdentityCluster(Base):
    __tablename__ = "identity_clusters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(255))
    representative_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_identities.id", ondelete="SET NULL")
    )
    identity_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    roster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    similarity_threshold: Mapped[float | None] = mapped_column(Float)
    clustering_algorithm: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'cosine_similarity'")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    tenant: Mapped[Tenant] = relationship(back_populates="identity_clusters")
    representative_identity: Mapped[MediaIdentity | None] = relationship(
        "MediaIdentity", foreign_keys=[representative_identity_id]
    )
    members: Mapped[list["IdentityMember"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "label", name="unique_tenant_identity_label"),
        Index("idx_identity_clusters_tenant", "tenant_id"),
        Index(
            "idx_identity_clusters_roster",
            "roster_id",
            postgresql_where=text("roster_id IS NOT NULL"),
        ),
    )


class ClusterCentroid(Base):
    __tablename__ = "mv_identity_cluster_centroids"
    __table_args__ = {"info": {"is_materialized_view": True}}

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identity_clusters.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    centroid: Mapped[list[float]] = mapped_column(
        Vector(_DB_SETTINGS.pgvector_dimension)
    )
    refreshed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    cluster: Mapped["IdentityCluster"] = relationship(
        "IdentityCluster",
        primaryjoin="ClusterCentroid.cluster_id == IdentityCluster.id",
        viewonly=True,
    )


class IdentityMember(Base):
    __tablename__ = "identity_members"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_clusters.id", ondelete="CASCADE"), nullable=False
    )
    identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_identities.id", ondelete="CASCADE"), nullable=False
    )
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    cluster: Mapped[IdentityCluster] = relationship(back_populates="members")
    identity: Mapped[MediaIdentity] = relationship(back_populates="cluster_memberships")

    __table_args__ = (
        CheckConstraint("similarity >= 0 AND similarity <= 1", name="similarity_range"),
        UniqueConstraint("cluster_id", "identity_id", name="unique_identity_member"),
        UniqueConstraint("tenant_id", "identity_id", name="unique_identity_membership"),
        Index("idx_identity_members_cluster", "cluster_id"),
        Index("idx_identity_members_identity", "identity_id"),
    )


class IdentityScanJob(Base):
    __tablename__ = "identity_scan_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'")
    )
    media_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    total_media: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_media: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    identities_detected: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="valid_status",
        ),
        Index("idx_scan_jobs_tenant", "tenant_id"),
        Index(
            "idx_scan_jobs_status",
            "status",
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )


__all__ = [
    "Tenant",
    "MediaIdentity",
    "IdentityCluster",
    "ClusterCentroid",
    "IdentityMember",
    "IdentityScanJob",
]
