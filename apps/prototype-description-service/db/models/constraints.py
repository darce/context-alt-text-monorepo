"""Constraint models - suggestions, blocks, and pairwise constraints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from db.models.base_imports import (
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
    UniqueConstraint,
    datetime,
    func,
    mapped_column,
    relationship,
    text,
    uuid,
)

if TYPE_CHECKING:
    from db.models.identity import IdentityCluster, MediaIdentity
    from db.models.tenant import Tenant


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
    refreshed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    source: Mapped[str | None] = mapped_column(String(50))

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


class IdentityClusterBlock(Base):
    """Negative constraint preventing identity from joining a cluster."""

    __tablename__ = "identity_cluster_blocks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_identities.id", ondelete="CASCADE"), nullable=False
    )
    blocked_cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_clusters.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="identity_cluster_blocks")
    identity: Mapped[MediaIdentity] = relationship()
    blocked_cluster: Mapped[IdentityCluster] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", "identity_id", "blocked_cluster_id", name="unique_identity_cluster_block"),
        Index("idx_identity_cluster_blocks_identity", "tenant_id", "identity_id"),
        Index("idx_identity_cluster_blocks_cluster", "tenant_id", "blocked_cluster_id"),
    )


class IdentityConstraint(Base):
    """Pairwise constraint between two identities (Must-Link / Cannot-Link)."""

    __tablename__ = "identity_constraints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    identity_a: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_identities.id", ondelete="CASCADE"), nullable=False
    )
    identity_b: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_identities.id", ondelete="CASCADE"), nullable=False
    )
    constraint_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("tenant_id", "identity_a", "identity_b", name="unique_identity_constraint"),
        CheckConstraint("identity_a < identity_b", name="canonical_ordering"),
        Index("idx_identity_constraints_lookup", "tenant_id", "identity_a", "identity_b"),
    )


__all__ = [
    "IdentitySuggestion",
    "IdentityClusterBlock",
    "IdentityConstraint",
]
