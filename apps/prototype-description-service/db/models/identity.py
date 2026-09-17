"""Identity and cluster models - core face recognition entities."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING

from db.models.base_imports import (
    _DB_SETTINGS,
    ARRAY,
    JSON,
    JSONB,
    TIMESTAMP,
    UUID,
    Base,
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Mapped,
    String,
    Text,
    UniqueConstraint,
    Vector,
    datetime,
    func,
    mapped_column,
    relationship,
    text,
    uuid,
)

if TYPE_CHECKING:
    from db.models.tenant import Tenant


def _postgres_only_check(sqltext: str, *, name: str) -> CheckConstraint:
    """Keep PostgreSQL-only vector checks out of SQLite test metadata."""
    return CheckConstraint(sqltext, name=name).ddl_if(dialect="postgresql")


def _jsonb_compatible() -> JSONB:
    """JSONB on Postgres, JSON on sqlite (test) — a fresh type per column."""
    return JSONB().with_variant(JSON(), "sqlite")


def _uuid_array_compatible() -> ARRAY:
    """UUID[] on Postgres, JSON on sqlite (test) — a fresh type per column."""
    return ARRAY(UUID(as_uuid=True)).with_variant(JSON(), "sqlite")


class ClusterMergeKind(StrEnum):
    """Vocabulary for cluster_merge_receipts.kind (sr-007)."""

    AUTO = "auto"
    OPERATOR = "operator"


class ReceiptNotTopError(ValueError):
    """LIFO revert refused: receipt is not the newest unreverted merge (API-05)."""

    code = "receipt_not_top"

    def __init__(self, receipt_id: uuid.UUID) -> None:
        self.receipt_id = receipt_id
        super().__init__("Receipt is not the top unreverted merge")


def require_top_unreverted_receipt(
    receipts: Sequence[ClusterMergeReceipt],
    receipt_id: uuid.UUID,
) -> ClusterMergeReceipt:
    """Return the receipt only when it is the survivor's newest unreverted row."""
    unreverted = [receipt for receipt in receipts if receipt.reverted_at is None]
    if not unreverted:
        raise ReceiptNotTopError(receipt_id)
    top = max(unreverted, key=lambda receipt: receipt.created_at)
    if top.receipt_id != receipt_id:
        raise ReceiptNotTopError(receipt_id)
    return top


class MediaIdentity(Base):
    __tablename__ = "media_identities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    identity_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'face'"))
    media_id: Mapped[int] = mapped_column(Integer, nullable=False)
    media_url: Mapped[str] = mapped_column(Text, nullable=False)

    bbox_x: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_y: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_width: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_height: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    embedding: Mapped[list[float]] = mapped_column(Vector(_DB_SETTINGS.pgvector_dimension), nullable=False)
    # Provenance of the embedding vector (manifest model_id). NOT NULL, no default.
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)

    # InsightFace metadata
    pose_pitch: Mapped[float | None] = mapped_column(Float, nullable=True)
    pose_yaw: Mapped[float | None] = mapped_column(Float, nullable=True)
    pose_roll: Mapped[float | None] = mapped_column(Float, nullable=True)
    # FIR-6 S1 quality factors (written by face_pipeline scan path only; NULL under insightface)
    sharpness: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding_norm: Mapped[float | None] = mapped_column(Float, nullable=True)
    occlusion_severity: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_phash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_exported_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    moved_by_merge_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    disposed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

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
        UniqueConstraint("tenant_id", "media_id", "identity_type", "bbox_x", "bbox_y", name="unique_media_identity"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        _postgres_only_check(
            "abs(vector_norm(embedding) - 1.0) < 0.01",
            name="media_identity_embedding_unit_norm",
        ),
        CheckConstraint(
            "identity_type IN ('face', 'brand', 'pose', 'gait')",
            name="valid_identity_type",
        ),
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
    __allow_unmapped__ = True

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    identity_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'face'"))
    label: Mapped[str | None] = mapped_column(String(255))
    representative_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_identities.id", ondelete="SET NULL")
    )
    identity_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    roster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    similarity_threshold: Mapped[float | None] = mapped_column(Float)
    curriculum_t: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.0"))
    curriculum_t_updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    clustering_algorithm: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'cosine_similarity'")
    )
    # User confirmation tracking for cold-start ground truth
    user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    confirmation_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    confirmation_source: Mapped[str | None] = mapped_column(String(20))  # label, merge, assignment, split, reject
    last_exported_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    disposed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)
    dismissed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="identity_clusters")
    representative_identity: Mapped[MediaIdentity | None] = relationship(
        "MediaIdentity", foreign_keys=[representative_identity_id]
    )
    members: Mapped[list[IdentityMember]] = relationship(back_populates="cluster", cascade="all, delete-orphan")
    representatives: Mapped[list[IdentityClusterRepresentative]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )
    merge_receipts: Mapped[list[ClusterMergeReceipt]] = relationship(
        back_populates="survivor_cluster",
        cascade="all, delete-orphan",
        order_by="ClusterMergeReceipt.created_at.desc()",
        foreign_keys="ClusterMergeReceipt.survivor_cluster_id",
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
        UniqueConstraint("tenant_id", "identity_type", "label", name="unique_tenant_identity_label"),
        CheckConstraint(
            "identity_type IN ('face', 'brand', 'pose', 'gait')",
            name="cluster_valid_identity_type",
        ),
        CheckConstraint(
            "confirmation_source IS NULL OR confirmation_source IN ('label', 'merge', 'assignment', 'split', 'reject')",
            name="valid_confirmation_source",
        ),
        Index("idx_identity_clusters_tenant", "tenant_id"),
        Index(
            "idx_identity_clusters_roster",
            "roster_id",
            postgresql_where=text("roster_id IS NOT NULL"),
        ),
    )

    # Transient fields for API response population (not persisted)
    suggested_label: str | None = None
    suggested_label_source: str | None = None
    suggested_label_confidence: float | None = None


class CurationReplayRecord(Base):
    __tablename__ = "curation_replay_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    result_status: Mapped[str] = mapped_column(String(20), nullable=False)
    backend_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    conflict_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    machine_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'not_applicable'"),
    )
    refresh_requested_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    refresh_completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tenant: Mapped[Tenant] = relationship(backref="curation_replay_records")

    __table_args__ = (
        CheckConstraint(
            "refresh_status IN ('not_applicable', 'queued', 'running', 'no_candidates', 'timed_out', 'completed', 'failed')",
            name="ck_curation_replay_refresh_status",
        ),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_curation_replay_tenant_idempotency"),
        Index("idx_curation_replay_tenant", "tenant_id"),
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
    pose_pitch: Mapped[float | None] = mapped_column(Float)
    pose_yaw: Mapped[float | None] = mapped_column(Float)
    pose_roll: Mapped[float | None] = mapped_column(Float)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    quality_components: Mapped[dict[str, float] | None] = mapped_column(_jsonb_compatible(), nullable=True)
    diversity_score: Mapped[float | None] = mapped_column(Float)
    is_user_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    last_exported_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    disposed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    tenant: Mapped[Tenant] = relationship()
    cluster: Mapped[IdentityCluster] = relationship(back_populates="representatives")
    identity: Mapped[MediaIdentity] = relationship()

    __table_args__ = (
        UniqueConstraint("cluster_id", "identity_id", name="unique_cluster_representative"),
        CheckConstraint("quality_score >= 0 AND quality_score <= 1", name="quality_score_range"),
        _postgres_only_check(
            "abs(vector_norm(embedding) - 1.0) < 0.01",
            name="cluster_rep_embedding_unit_norm",
        ),
    )


class ClusterMergeReceipt(Base):
    """One automatic or operator cluster merge; LIFO undo stack per survivor."""

    __tablename__ = "cluster_merge_receipts"

    receipt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    survivor_cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_clusters.id", ondelete="CASCADE"), nullable=False
    )
    # Historical id only: merge deletes the source cluster, so this is not an FK.
    source_cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    moved_identity_ids: Mapped[list[uuid.UUID]] = mapped_column(_uuid_array_compatible(), nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    reverted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship()
    survivor_cluster: Mapped[IdentityCluster] = relationship(
        back_populates="merge_receipts",
        foreign_keys=[survivor_cluster_id],
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('auto', 'operator')",
            name="cluster_merge_receipt_valid_kind",
        ),
        Index("idx_cluster_merge_receipts_tenant", "tenant_id"),
        Index("idx_cluster_merge_receipts_survivor", "survivor_cluster_id", "created_at"),
    )

    def revert(self, *, now: datetime, sibling_receipts: Sequence[ClusterMergeReceipt] | None = None) -> None:
        """Mark reverted only when this row is the survivor's newest unreverted receipt."""
        stack: Sequence[ClusterMergeReceipt]
        if sibling_receipts is not None:
            stack = sibling_receipts
        elif self.survivor_cluster is not None:
            stack = self.survivor_cluster.merge_receipts
        else:
            stack = (self,)
        require_top_unreverted_receipt(stack, self.receipt_id)
        self.reverted_at = now


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


class IdentityNameSuppression(Base):
    """Per-roster_id do-not-name escape hatch for the E19-4a naming gate."""

    __tablename__ = "identity_name_suppressions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    roster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", "roster_id", name="unique_name_suppression"),
        Index("idx_identity_name_suppressions_tenant", "tenant_id"),
    )


__all__ = [
    "MediaIdentity",
    "IdentityCluster",
    "CurationReplayRecord",
    "ClusterCentroid",
    "IdentityClusterRepresentative",
    "ClusterMergeKind",
    "ClusterMergeReceipt",
    "ReceiptNotTopError",
    "require_top_unreverted_receipt",
    "IdentityMember",
    "IdentityNameSuppression",
]
