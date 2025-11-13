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

    media_faces: Mapped[list["MediaFace"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    face_clusters: Mapped[list["FaceCluster"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class MediaFace(Base):
    __tablename__ = "media_faces"

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
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    tenant: Mapped[Tenant] = relationship(back_populates="media_faces")
    cluster_members: Mapped[list["ClusterMember"]] = relationship(
        back_populates="face", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "media_id", "bbox_x", "bbox_y", name="unique_media_face"
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index(
            "idx_media_faces_tenant",
            "tenant_id",
            postgresql_where=text("NOT is_deleted"),
        ),
        Index(
            "idx_media_faces_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class FaceCluster(Base):
    __tablename__ = "face_clusters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(255))
    representative_face_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_faces.id", ondelete="SET NULL")
    )
    face_count: Mapped[int] = mapped_column(
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

    tenant: Mapped[Tenant] = relationship(back_populates="face_clusters")
    representative_face: Mapped[MediaFace | None] = relationship(
        "MediaFace", foreign_keys=[representative_face_id]
    )
    members: Mapped[list["ClusterMember"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "label", name="unique_tenant_label"),
        Index("idx_face_clusters_tenant", "tenant_id"),
        Index(
            "idx_face_clusters_roster",
            "roster_id",
            postgresql_where=text("roster_id IS NOT NULL"),
        ),
    )


class ClusterMember(Base):
    __tablename__ = "cluster_members"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("face_clusters.id", ondelete="CASCADE"), nullable=False
    )
    face_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_faces.id", ondelete="CASCADE"), nullable=False
    )
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    cluster: Mapped[FaceCluster] = relationship(back_populates="members")
    face: Mapped[MediaFace] = relationship(back_populates="cluster_members")

    __table_args__ = (
        CheckConstraint("similarity >= 0 AND similarity <= 1", name="similarity_range"),
        UniqueConstraint("cluster_id", "face_id", name="unique_cluster_member"),
        UniqueConstraint("tenant_id", "face_id", name="unique_face_membership"),
        Index("idx_cluster_members_cluster", "cluster_id"),
        Index("idx_cluster_members_face", "face_id"),
    )


class FaceScanJob(Base):
    __tablename__ = "face_scan_jobs"

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
    faces_detected: Mapped[int] = mapped_column(
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
    "MediaFace",
    "FaceCluster",
    "ClusterMember",
    "FaceScanJob",
]
