"""Tenant and API key models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from db.models.base_imports import (
    JSON,
    JSONB,
    TIMESTAMP,
    UUID,
    Base,
    Boolean,
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
    from db.models.constraints import (
        ClusterMergeSuggestion,
        IdentityClusterBlock,
        IdentitySuggestion,
        NameSuggestion,
    )
    from db.models.identity import (
        IdentityCluster,
        MediaIdentity,
    )


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_url: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # AP-7 concierge customer fields (ADR-012 subset; nullable expand-first).
    primary_contact_email: Mapped[str | None] = mapped_column(String(255), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    plan: Mapped[str | None] = mapped_column(String(50))
    next_person_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    # E19-4a consent gate: default true reflects the signed operator naming
    # agreement; per-person opt-out is the IdentityNameSuppression list.
    naming_agreement_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    retention_mode: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'retain_all'"))
    last_export_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_purge_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    retention_updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
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
    cluster_merge_suggestions: Mapped[list[ClusterMergeSuggestion]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    name_suggestions: Mapped[list[NameSuggestion]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    identity_cluster_blocks: Mapped[list[IdentityClusterBlock]] = relationship(
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
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="api_keys")

    __table_args__ = (
        Index("idx_api_keys_tenant", "tenant_id"),
        Index("idx_api_keys_hash", "api_key_hash"),
    )


class DemoInstance(Base):
    """Per-prospect demo registry row (launch-plan §5).

    Slug is a capability-free public lookup key — never a tenant identity and
    never a credential. ``api_key_ref`` stores the key hash only; the raw key
    is never persisted here.
    """

    __tablename__ = "demo_instances"

    slug: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    api_key_ref: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    seed_bundle: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'default'"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    recognition_quota: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("200"))
    recognition_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    branding_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
    )
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (
        Index("idx_demo_instances_tenant", "tenant_id"),
        Index("idx_demo_instances_expires", "expires_at"),
        # Hot-path lookup: quota enforcement filters demo rows by api_key_ref on
        # every analyze request; without this it seq-scans (DS-2-BR-04).
        Index("idx_demo_instances_api_key_ref", "api_key_ref"),
    )


__all__ = ["Tenant", "ApiKey", "DemoInstance"]
