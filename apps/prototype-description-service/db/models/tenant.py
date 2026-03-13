"""Tenant and API key models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from db.models.base_imports import (
    TIMESTAMP,
    UUID,
    Base,
    ForeignKey,
    Index,
    Integer,
    Mapped,
    String,
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
    )
    from db.models.identity import (
        IdentityCluster,
        MediaIdentity,
    )


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_url: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    next_person_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
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

    tenant: Mapped[Tenant] = relationship(back_populates="api_keys")

    __table_args__ = (
        Index("idx_api_keys_tenant", "tenant_id"),
        Index("idx_api_keys_hash", "api_key_hash"),
    )


__all__ = ["Tenant", "ApiKey"]
