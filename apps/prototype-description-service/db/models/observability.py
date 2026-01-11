"""Observability models - recognition runs, events, and analytics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from db.models.base_imports import (
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

if TYPE_CHECKING:
    from db.models.tenant import Tenant


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


__all__ = [
    "RecognitionRun",
    "RecognitionEvent",
    "ClusteringJobReport",
    "AssignmentDecision",
]
