"""Portal identity, entitlement, usage, billing, and key-history models."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    from db.models.tenant import Tenant


def _json_col():
    """Use JSONB in PostgreSQL and JSON for the SQLite test substrate."""
    return JSONB().with_variant(JSON(), "sqlite")


class PortalIdentity(Base):
    __tablename__ = "portal_identity"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_portal_identity_tenant_id"),
        UniqueConstraint("issuer", "subject", name="uq_portal_identity_issuer_subject"),
        Index("idx_portal_identity_reclaim", "status", "updated_at"),
    )


class TenantEntitlement(Base):
    __tablename__ = "tenant_entitlement"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    plan_code: Mapped[str] = mapped_column(Text, nullable=False)
    allowance_version: Mapped[str] = mapped_column(Text, nullable=False)
    allowance_jobs: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    period_start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'expired'"))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    grace_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_entitlement_tenant_id"),
        Index("idx_tenant_entitlement_reclaim", "updated_at"),
    )


class UsageReservation(Base):
    __tablename__ = "usage_reservation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'reserved'"))
    reserved_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    cost_units: Mapped[int] = mapped_column(Integer, nullable=False)

    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_usage_reservation_tenant_idempotency_key"),
        Index("idx_usage_reservation_tenant_period_status", "tenant_id", "period_start", "status"),
        Index("idx_usage_reservation_reclaim", "status", "settled_at"),
    )


class BillingSubscriptionProjection(Base):
    __tablename__ = "billing_subscription_projection"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'"))
    current_period_end: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    past_due_since: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_billing_subscription_projection_tenant_id"),
        UniqueConstraint(
            "provider",
            "provider_customer_id",
            name="uq_billing_subscription_projection_provider_customer",
        ),
        Index("idx_billing_subscription_projection_reclaim", "updated_at"),
    )


class BillingWebhookInbox(Base):
    __tablename__ = "billing_webhook_inbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(_json_col(), nullable=False)
    received_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'received'"))

    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_billing_webhook_inbox_provider_event"),
        Index("idx_billing_webhook_inbox_reclaim", "status", "processed_at"),
    )


class ApiKeyRotationHistory(Base):
    __tablename__ = "api_key_rotation_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False
    )
    replaced_by_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    cutoff_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (
        Index("idx_api_key_rotation_history_tenant_created", "tenant_id", "created_at"),
        Index("idx_api_key_rotation_history_reclaim", "created_at"),
    )


__all__ = [
    "ApiKeyRotationHistory",
    "BillingSubscriptionProjection",
    "BillingWebhookInbox",
    "PortalIdentity",
    "TenantEntitlement",
    "UsageReservation",
]
