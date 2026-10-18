"""Atlas models — workbench curation 2D projection runs, points, and queue dispositions."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKeyConstraint

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
    Text,
    UniqueConstraint,
    datetime,
    func,
    mapped_column,
    relationship,
    uuid,
)

if TYPE_CHECKING:
    from db.models.identity import MediaIdentity
    from db.models.tenant import Tenant


class AtlasRunStatus(StrEnum):
    """Lifecycle states for an atlas build run."""

    BUILDING = "building"
    COMPLETE = "complete"
    FAILED = "failed"


class AtlasDispositionAction(StrEnum):
    """Queue disposition actions recorded against an atlas point."""

    REVIEWED = "reviewed"
    SKIPPED = "skipped"


def _jsonb_compatible() -> JSONB:
    """JSONB on Postgres, JSON on sqlite (test) — a fresh type per column."""
    return JSONB().with_variant(JSON(), "sqlite")


class IdentityAtlasRun(Base):
    __tablename__ = "identity_atlas_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict] = mapped_column(_jsonb_compatible(), nullable=False)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    tenant: Mapped[Tenant] = relationship()
    points: Mapped[list[IdentityAtlasPoint]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('building', 'complete', 'failed')",
            name="valid_atlas_run_status",
        ),
        Index("idx_identity_atlas_runs_tenant", "tenant_id"),
    )


class IdentityAtlasPoint(Base):
    __tablename__ = "identity_atlas_points"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_atlas_runs.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_identities.id", ondelete="CASCADE"), nullable=False
    )
    media_id: Mapped[int] = mapped_column(Integer, nullable=False)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    queue_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    uncertainty: Mapped[dict] = mapped_column(_jsonb_compatible(), nullable=False)

    run: Mapped[IdentityAtlasRun] = relationship(back_populates="points")
    tenant: Mapped[Tenant] = relationship()
    identity: Mapped[MediaIdentity] = relationship()
    dispositions: Mapped[list[IdentityAtlasQueueDisposition]] = relationship(
        back_populates="point", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("run_id", "identity_id", name="uq_identity_atlas_points_run_identity"),
        # Target for composite FK from dispositions: forces disposition.run_id
        # to match the referenced point's run_id (FIR-9 cross-run attach).
        UniqueConstraint("id", "run_id", name="uq_identity_atlas_points_id_run"),
        Index("idx_identity_atlas_points_run_queue_rank", "run_id", "queue_rank"),
        Index("idx_identity_atlas_points_tenant", "tenant_id"),
        # Purge disposed scope filters points on (tenant_id, identity_id).
        Index("idx_identity_atlas_points_tenant_identity", "tenant_id", "identity_id"),
    )


class IdentityAtlasQueueDisposition(Base):
    __tablename__ = "identity_atlas_queue_dispositions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_atlas_runs.id", ondelete="CASCADE"), nullable=False
    )
    # Composite FK with run_id (see __table_args__) — not a single-column FK.
    point_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    point: Mapped[IdentityAtlasPoint] = relationship(back_populates="dispositions")
    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (
        UniqueConstraint("run_id", "point_id", name="uq_identity_atlas_dispositions_run_point"),
        # Composite FK: disposition.run_id must equal the point's run_id.
        ForeignKeyConstraint(
            ["point_id", "run_id"],
            ["identity_atlas_points.id", "identity_atlas_points.run_id"],
            ondelete="CASCADE",
            name="fk_identity_atlas_dispositions_point_run",
        ),
        CheckConstraint(
            "action IN ('reviewed', 'skipped')",
            name="valid_atlas_disposition_action",
        ),
        Index("idx_identity_atlas_queue_dispositions_tenant", "tenant_id"),
        # Point-delete CASCADE looks up dispositions by point_id.
        Index("idx_identity_atlas_queue_dispositions_point", "point_id"),
    )


__all__ = [
    "AtlasDispositionAction",
    "AtlasRunStatus",
    "IdentityAtlasPoint",
    "IdentityAtlasQueueDisposition",
    "IdentityAtlasRun",
]
