"""Job models - scan and clustering job tracking."""

from __future__ import annotations

from db.models.base_imports import (
    ARRAY,
    JSON,
    JSONB,
    TIMESTAMP,
    UUID,
    Base,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Mapped,
    String,
    Text,
    datetime,
    func,
    mapped_column,
    relationship,
    text,
    uuid,
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
    message: Mapped[str | None] = mapped_column(Text)
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
    job_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'clustering'"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"))
    progress: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    total_identities: Mapped[int | None] = mapped_column(Integer)
    processed_identities: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=dict,
    )
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
        CheckConstraint(
            "job_type IN ('clustering', 'curation', 'split')",
            name="valid_job_type",
        ),
        Index("idx_clustering_jobs_tenant", "tenant_id"),
        Index(
            "idx_clustering_jobs_status",
            "status",
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )


__all__ = [
    "IdentityScanJob",
    "IdentityScanJobItem",
    "IdentityClusteringJob",
]
