"""SQLAlchemy models for the prototype description service."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.settings import get_database_settings

_DB_SETTINGS = get_database_settings()


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_url: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    media_identities: Mapped[list[MediaIdentity]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    identity_clusters: Mapped[list[IdentityCluster]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    identity_suggestions: Mapped[list[IdentitySuggestion]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    api_key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    rate_limit_tier: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="api_keys")

    __table_args__ = (
        Index("idx_api_keys_tenant", "tenant_id"),
        Index("idx_api_keys_hash", "api_key_hash"),
    )


class MediaIdentity(Base):
    __tablename__ = "media_identities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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

    embedding: Mapped[list[float]] = mapped_column(Vector(_DB_SETTINGS.pgvector_dimension), nullable=False)

    # InsightFace metadata
    pose_pitch: Mapped[float | None] = mapped_column(Float, nullable=True)
    pose_yaw: Mapped[float | None] = mapped_column(Float, nullable=True)
    pose_roll: Mapped[float | None] = mapped_column(Float, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0=female, 1=male
    image_phash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    tenant: Mapped[Tenant] = relationship(back_populates="media_identities")
    cluster_memberships: Mapped[list[IdentityMember]] = relationship(
        back_populates="identity", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "media_id", "bbox_x", "bbox_y", name="unique_media_identity"),
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(255))
    representative_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_identities.id", ondelete="SET NULL")
    )
    identity_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    roster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    similarity_threshold: Mapped[float | None] = mapped_column(Float)
    clustering_algorithm: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'cosine_similarity'")
    )
    # User confirmation tracking for cold-start ground truth
    user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    confirmation_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    confirmation_source: Mapped[str | None] = mapped_column(String(20))  # label, merge, assignment, split, reject
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    tenant: Mapped[Tenant] = relationship(back_populates="identity_clusters")
    representative_identity: Mapped[MediaIdentity | None] = relationship(
        "MediaIdentity", foreign_keys=[representative_identity_id]
    )
    members: Mapped[list[IdentityMember]] = relationship(back_populates="cluster", cascade="all, delete-orphan")
    representatives: Mapped[list[IdentityClusterRepresentative]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )
    # Relationship to materialized view for centroid loading
    centroid_data: Mapped[ClusterCentroid | None] = relationship(
        "ClusterCentroid",
        primaryjoin="IdentityCluster.id == ClusterCentroid.cluster_id",
        foreign_keys="ClusterCentroid.cluster_id",
        uselist=False,
        viewonly=True,
        lazy="joined",
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
    centroid: Mapped[list[float]] = mapped_column(Vector(_DB_SETTINGS.pgvector_dimension))
    refreshed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    cluster: Mapped[IdentityCluster] = relationship(
        "IdentityCluster",
        primaryjoin="ClusterCentroid.cluster_id == IdentityCluster.id",
        viewonly=True,
    )


class IdentityClusterRepresentative(Base):
    __tablename__ = "identity_cluster_representatives"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_clusters.id", ondelete="CASCADE"), nullable=False
    )
    identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_identities.id", ondelete="CASCADE"), nullable=False
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(_DB_SETTINGS.pgvector_dimension), nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    diversity_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    tenant: Mapped[Tenant] = relationship()
    cluster: Mapped[IdentityCluster] = relationship(back_populates="representatives")
    identity: Mapped[MediaIdentity] = relationship()

    __table_args__ = (
        UniqueConstraint("cluster_id", "identity_id", name="unique_cluster_representative"),
        CheckConstraint("quality_score >= 0 AND quality_score <= 1", name="quality_score_range"),
    )


class IdentityMember(Base):
    __tablename__ = "identity_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    assigned_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"))
    media_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer).with_variant(JSON(), "sqlite"), nullable=False)
    total_media: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_media: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    identities_detected: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    items: Mapped[list[IdentityScanJobItem]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class IdentityScanJobItem(Base):
    """Queue item for an IdentityScanJob.

    Each item corresponds to scanning a single media URL (and potentially producing multiple identities/faces).
    """

    __tablename__ = "identity_scan_job_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_scan_jobs.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    media_id: Mapped[int] = mapped_column(Integer, nullable=False)
    media_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    identities_detected: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    job: Mapped[IdentityScanJob] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'skipped', 'cancelled')",
            name="valid_item_status",
        ),
        Index("idx_scan_job_items_job", "job_id"),
        Index(
            "idx_scan_job_items_pending",
            "job_id",
            "status",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "idx_scan_job_items_stale",
            "status",
            "started_at",
            postgresql_where=text("status = 'processing'"),
        ),
        Index("idx_scan_job_items_tenant_id", "tenant_id", "id"),
    )


class IdentityClusteringJob(Base):
    __tablename__ = "identity_clustering_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"))
    progress: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    total_identities: Mapped[int | None] = mapped_column(Integer)
    processed_identities: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="valid_status",
        ),
        Index("idx_clustering_jobs_tenant", "tenant_id"),
        Index(
            "idx_clustering_jobs_status",
            "status",
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )


class RecognitionRun(Base):
    __tablename__ = "recognition_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'running'"))
    source: Mapped[str | None] = mapped_column(String(50))
    scan_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_scan_jobs.id", ondelete="SET NULL")
    )
    clustering_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_clustering_jobs.id", ondelete="SET NULL")
    )
    git_sha: Mapped[str | None] = mapped_column(String(64))
    settings_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=dict,
    )
    dataset_selector: Mapped[dict[str, object]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=dict,
    )
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    tenant: Mapped[Tenant] = relationship()
    events: Mapped[list[RecognitionEvent]] = relationship(back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="valid_recognition_run_status"),
        Index("idx_recognition_runs_tenant", "tenant_id"),
        Index("idx_recognition_runs_status", "status"),
        Index("idx_recognition_runs_scan_job", "scan_job_id"),
        Index("idx_recognition_runs_clustering_job", "clustering_job_id"),
    )


class RecognitionEvent(Base):
    __tablename__ = "recognition_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recognition_runs.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_identities.id", ondelete="SET NULL")
    )
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_clusters.id", ondelete="SET NULL")
    )
    source_cluster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    target_cluster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=dict,
    )

    tenant: Mapped[Tenant] = relationship()
    run: Mapped[RecognitionRun] = relationship(back_populates="events")

    __table_args__ = (
        Index("idx_recognition_events_tenant", "tenant_id"),
        Index("idx_recognition_events_run_time", "run_id", "timestamp"),
        Index("idx_recognition_events_type", "event_type"),
        Index("idx_recognition_events_identity", "identity_id"),
        Index("idx_recognition_events_cluster", "cluster_id"),
    )


class ClusteringJobReport(Base):
    __tablename__ = "clustering_job_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    total_identities: Mapped[int] = mapped_column(Integer, nullable=False)
    accept_count: Mapped[int] = mapped_column(Integer, nullable=False)
    suggest_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reject_count: Mapped[int] = mapped_column(Integer, nullable=False)
    clusters_created: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_similarity: Mapped[float | None] = mapped_column(Float)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    tenant: Mapped[Tenant | None] = relationship()

    __table_args__ = (
        Index("idx_clustering_reports_tenant", "tenant_id"),
        Index("idx_clustering_reports_job", "job_id"),
    )


class AssignmentDecision(Base):
    __tablename__ = "assignment_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True)
    identity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cluster_id: Mapped[str | None] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    similarity: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    algorithm: Mapped[str | None] = mapped_column(String(50))
    job_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    tenant: Mapped[Tenant | None] = relationship()

    __table_args__ = (
        Index("idx_assignment_decisions_tenant", "tenant_id"),
        Index("idx_assignment_decisions_cluster", "cluster_id"),
        Index("idx_assignment_decisions_decision", "decision"),
        Index("idx_assignment_decisions_timestamp", "timestamp"),
    )


class IdentitySuggestion(Base):
    """Borderline cluster match suggestions for user confirmation.

    Stores suggestions for matches that fall in the borderline range
    (0.55-0.68 avg_member_similarity) to surface to users for confirmation,
    rather than being silently rejected or auto-assigned.

    Priority levels (lower = more urgent):
    - 1 (CRITICAL): Cold start, first 30 clusters, needs immediate confirmation
    - 2 (HIGH): High similarity (>0.90) but cluster not yet user-confirmed
    - 3 (NORMAL): Regular suggestions
    - 4 (LOW): Borderline matches, low confidence

    Resolution states:
    - pending: Awaiting user review
    - accepted: User confirmed the match (identity assigned to cluster)
    - rejected: User rejected the match
    - expired: Suggestion invalidated (e.g., cluster deleted, identity reassigned)
    """

    __tablename__ = "identity_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_identities.id", ondelete="CASCADE"), nullable=False
    )
    suggested_cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_clusters.id", ondelete="CASCADE"), nullable=False
    )

    # Similarity scores
    representative_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    avg_member_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)

    # Priority level (1=critical, 2=high, 3=normal, 4=low)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    # Resolution status
    resolution: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"))

    # Relationships
    tenant: Mapped[Tenant] = relationship(back_populates="identity_suggestions")
    identity: Mapped[MediaIdentity] = relationship()
    suggested_cluster: Mapped[IdentityCluster] = relationship()

    __table_args__ = (
        CheckConstraint(
            "representative_similarity >= 0 AND representative_similarity <= 1",
            name="representative_similarity_range",
        ),
        CheckConstraint(
            "avg_member_similarity >= 0 AND avg_member_similarity <= 1",
            name="avg_member_similarity_range",
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="confidence_score_range",
        ),
        CheckConstraint(
            "resolution IN ('pending', 'accepted', 'rejected', 'expired')",
            name="valid_resolution",
        ),
        UniqueConstraint("identity_id", "suggested_cluster_id", name="unique_identity_suggestion"),
        Index("idx_identity_suggestions_tenant", "tenant_id"),
        Index("idx_identity_suggestions_identity", "identity_id"),
        Index("idx_identity_suggestions_cluster", "suggested_cluster_id"),
        Index(
            "idx_identity_suggestions_pending",
            "tenant_id",
            "confidence_score",
            postgresql_where=text("resolution = 'pending'"),
        ),
    )


__all__ = [
    "Tenant",
    "MediaIdentity",
    "IdentityCluster",
    "ClusterCentroid",
    "IdentityMember",
    "IdentityScanJob",
    "IdentityScanJobItem",
    "IdentitySuggestion",
    "RecognitionRun",
    "RecognitionEvent",
    "ClusteringJobReport",
    "AssignmentDecision",
]
