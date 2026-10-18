"""Portal identity, entitlement, usage, billing, and key-history models."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from db.models.base_imports import (
    JSON,
    JSONB,
    TIMESTAMP,
    UUID,
    Base,
    BigInteger,
    Boolean,
    CheckConstraint,
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


class CheckoutAttemptStatus(StrEnum):
    CREATED = "created"
    PROVIDER_REQUESTED = "provider_requested"
    PENDING = "pending"
    AMBIGUOUS = "ambiguous"
    SUCCEEDED = "succeeded"
    EXPIRED = "expired"
    CANCELED = "canceled"
    FAILED = "failed"


class CheckoutAttemptErrorClass(StrEnum):
    NONE = "none"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"
    EXPIRED = "expired"


CHECKOUT_ATTEMPT_ACTIVE_STATUSES: frozenset[CheckoutAttemptStatus] = frozenset(
    {
        CheckoutAttemptStatus.CREATED,
        CheckoutAttemptStatus.PROVIDER_REQUESTED,
        CheckoutAttemptStatus.PENDING,
        CheckoutAttemptStatus.AMBIGUOUS,
    }
)
_CHECKOUT_ATTEMPT_ACTIVE_STATUS_VALUES: tuple[str, ...] = (
    CheckoutAttemptStatus.CREATED.value,
    CheckoutAttemptStatus.PROVIDER_REQUESTED.value,
    CheckoutAttemptStatus.PENDING.value,
    CheckoutAttemptStatus.AMBIGUOUS.value,
)

_CHECKOUT_ATTEMPT_STATUS_SQL = ", ".join(f"'{status.value}'" for status in CheckoutAttemptStatus)
_CHECKOUT_ATTEMPT_ACTIVE_STATUS_SQL = ", ".join(f"'{value}'" for value in _CHECKOUT_ATTEMPT_ACTIVE_STATUS_VALUES)
_CHECKOUT_ATTEMPT_ERROR_CLASS_SQL = ", ".join(f"'{value.value}'" for value in CheckoutAttemptErrorClass)


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
    operation_id: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    fence_token: Mapped[str] = mapped_column(Text, nullable=False)
    queue_bytes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'reserved'"))
    reserved_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    cost_units: Mapped[int] = mapped_column(Integer, nullable=False)

    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_usage_reservation_tenant_idempotency_key"),
        UniqueConstraint("tenant_id", "operation_id", name="uq_usage_reservation_tenant_operation_id"),
        Index("idx_usage_reservation_tenant_period_status", "tenant_id", "period_start", "status"),
        Index("idx_usage_reservation_reclaim", "status", "settled_at"),
        CheckConstraint("cost_units > 0", name="ck_usage_reservation_cost_units_positive"),
        CheckConstraint("queue_bytes >= 0", name="ck_usage_reservation_queue_bytes_nonnegative"),
        CheckConstraint(
            "status IN ('reserved', 'committed', 'released', 'expired')",
            name="ck_usage_reservation_status",
        ),
        CheckConstraint("length(operation_id) > 0", name="ck_usage_reservation_operation_id_present"),
        CheckConstraint("length(request_fingerprint) > 0", name="ck_usage_reservation_request_fingerprint_present"),
        CheckConstraint("length(fence_token) > 0", name="ck_usage_reservation_fence_token_present"),
    )


class GlobalUsageAdmissionState(Base):
    """Process-wide admission singleton. Not a tenant table; no tenant RLS."""

    __tablename__ = "usage_admission_global_state"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    period_start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    daily_cost_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_cost_units: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    inflight_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    inflight_units: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    queue_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    queue_depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    queue_byte_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    queue_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    stop_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    fence_epoch: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    config_version: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("daily_cost_limit >= 0", name="ck_usage_admission_global_daily_cost_limit"),
        CheckConstraint("daily_cost_units >= 0", name="ck_usage_admission_global_daily_cost_units"),
        CheckConstraint("inflight_limit >= 0", name="ck_usage_admission_global_inflight_limit"),
        CheckConstraint("inflight_units >= 0", name="ck_usage_admission_global_inflight_units"),
        CheckConstraint("queue_limit >= 0", name="ck_usage_admission_global_queue_limit"),
        CheckConstraint("queue_depth >= 0", name="ck_usage_admission_global_queue_depth"),
        CheckConstraint("queue_byte_limit >= 0", name="ck_usage_admission_global_queue_byte_limit"),
        CheckConstraint("queue_bytes >= 0", name="ck_usage_admission_global_queue_bytes"),
        CheckConstraint("fence_epoch >= 1", name="ck_usage_admission_global_fence_epoch"),
        CheckConstraint("length(config_version) > 0", name="ck_usage_admission_global_config_version"),
        CheckConstraint("period_end > period_start", name="ck_usage_admission_global_period"),
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
    environment: Mapped[str | None] = mapped_column(Text, nullable=True)
    seller_account: Mapped[str | None] = mapped_column(Text, nullable=True)

    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_billing_subscription_projection_tenant_id"),
        UniqueConstraint(
            "provider",
            "environment",
            "seller_account",
            "provider_customer_id",
            name="uq_billing_subscription_projection_provider_namespace_customer",
        ),
        Index("idx_billing_subscription_projection_reclaim", "updated_at"),
        CheckConstraint(
            "status IN ('none', 'active', 'past_due', 'canceled', 'refund_hold')",
            name="ck_billing_subscription_projection_status",
        ),
        CheckConstraint(
            "environment IS NULL OR environment IN ('sandbox', 'live')",
            name="ck_billing_subscription_projection_environment",
        ),
    )


class BillingCheckoutAttempt(Base):
    __tablename__ = "billing_checkout_attempt"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[str] = mapped_column(Text, nullable=False)
    seller_account: Mapped[str] = mapped_column(Text, nullable=False)
    plan_code: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    client_idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text(f"'{CheckoutAttemptStatus.CREATED.value}'")
    )
    provider_checkout_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_class: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text(f"'{CheckoutAttemptErrorClass.NONE.value}'")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "environment",
            "seller_account",
            "idempotency_key",
            name="uq_billing_checkout_attempt_provider_key",
        ),
        Index(
            "uq_billing_checkout_attempt_client_key",
            "tenant_id",
            "provider",
            "environment",
            "seller_account",
            "client_idempotency_key",
            unique=True,
            postgresql_where=text("client_idempotency_key IS NOT NULL"),
            sqlite_where=text("client_idempotency_key IS NOT NULL"),
        ),
        Index(
            "uq_billing_checkout_attempt_one_active",
            "tenant_id",
            "provider",
            "environment",
            "seller_account",
            unique=True,
            postgresql_where=text(f"status IN ({_CHECKOUT_ATTEMPT_ACTIVE_STATUS_SQL})"),
            sqlite_where=text(f"status IN ({_CHECKOUT_ATTEMPT_ACTIVE_STATUS_SQL})"),
        ),
        Index("idx_billing_checkout_attempt_reclaim", "updated_at"),
        CheckConstraint(
            f"status IN ({_CHECKOUT_ATTEMPT_STATUS_SQL})",
            name="ck_billing_checkout_attempt_status",
        ),
        CheckConstraint(
            "environment IN ('sandbox', 'live')",
            name="ck_billing_checkout_attempt_environment",
        ),
        CheckConstraint(
            "provider IN ('polar', 'fake')",
            name="ck_billing_checkout_attempt_provider",
        ),
        CheckConstraint(
            f"last_error_class IN ({_CHECKOUT_ATTEMPT_ERROR_CLASS_SQL})",
            name="ck_billing_checkout_attempt_last_error_class",
        ),
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
    next_attempt_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    quarantined_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'received'"))
    environment: Mapped[str | None] = mapped_column(Text, nullable=True)
    seller_account: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "environment",
            "seller_account",
            "provider_event_id",
            name="uq_billing_webhook_inbox_provider_namespace_event",
        ),
        Index("idx_billing_webhook_inbox_reclaim", "status", "processed_at"),
        Index("idx_billing_webhook_inbox_pending", "status", "next_attempt_at"),
        CheckConstraint(
            "environment IS NULL OR environment IN ('sandbox', 'live')",
            name="ck_billing_webhook_inbox_environment",
        ),
    )


_KNOWN_ITEM_KIND_SQL = "'inbox', 'projection'"
_RECOVERY_KIND_SQL = "'subscriptions', 'ambiguous_checkouts'"
_QUARANTINE_STATUS_SQL = "'open', 'retry_pending', 'exhausted', 'resolved'"
_ITEM_PROGRESS_STATUS_SQL = "'completed', 'quarantined'"


class BillingKnownItemLease(Base):
    """Fenced per-item lease for known inbox events and projections.

    Operator-scope; not a tenant row. Caller commits the claim before vendor I/O.
    """

    __tablename__ = "billing_known_item_lease"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    environment: Mapped[str] = mapped_column(Text, primary_key=True)
    seller_account: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    remote_id: Mapped[str] = mapped_column(Text, primary_key=True)
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(f"kind IN ({_KNOWN_ITEM_KIND_SQL})", name="ck_billing_known_item_lease_kind"),
        CheckConstraint("environment IN ('sandbox', 'live')", name="ck_billing_known_item_lease_environment"),
        CheckConstraint("provider IN ('polar', 'fake')", name="ck_billing_known_item_lease_provider"),
        CheckConstraint("fence >= 0", name="ck_billing_known_item_lease_fence_nonnegative"),
        CheckConstraint(
            "length(remote_id) > 0 AND length(remote_id) <= 128",
            name="ck_billing_known_item_lease_remote_id",
        ),
        Index("idx_billing_known_item_lease_until", "lease_until", "kind"),
    )


class BillingReconciliationCursor(Base):
    """Seller-wide durable cursor/lease. Operator-scope; not a tenant row."""

    __tablename__ = "billing_reconciliation_cursor"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    environment: Mapped[str] = mapped_column(Text, primary_key=True)
    seller_account: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    last_progress_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    exhausted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_failure_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(f"kind IN ({_RECOVERY_KIND_SQL})", name="ck_billing_reconciliation_cursor_kind"),
        CheckConstraint("environment IN ('sandbox', 'live')", name="ck_billing_reconciliation_cursor_environment"),
        CheckConstraint("provider IN ('polar', 'fake')", name="ck_billing_reconciliation_cursor_provider"),
        CheckConstraint("fence >= 0", name="ck_billing_reconciliation_cursor_fence_nonnegative"),
        CheckConstraint("failure_count >= 0", name="ck_billing_reconciliation_cursor_failure_count"),
        CheckConstraint(
            "cursor IS NULL OR (length(cursor) > 0 AND length(cursor) <= 256)",
            name="ck_billing_reconciliation_cursor_cursor_bound",
        ),
        Index("idx_billing_reconciliation_cursor_lease", "lease_until", "kind"),
    )


class BillingReconciliationQuarantine(Base):
    """Durable per-item quarantine for untrusted vendor identities."""

    __tablename__ = "billing_reconciliation_quarantine"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[str] = mapped_column(Text, nullable=False)
    seller_account: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    remote_id: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    operator_identity: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(_json_col(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "environment",
            "seller_account",
            "kind",
            "remote_id",
            name="uq_billing_reconciliation_quarantine_remote",
        ),
        CheckConstraint(f"kind IN ({_RECOVERY_KIND_SQL})", name="ck_billing_reconciliation_quarantine_kind"),
        CheckConstraint(
            f"status IN ({_QUARANTINE_STATUS_SQL})",
            name="ck_billing_reconciliation_quarantine_status",
        ),
        CheckConstraint("environment IN ('sandbox', 'live')", name="ck_billing_reconciliation_quarantine_environment"),
        CheckConstraint("provider IN ('polar', 'fake')", name="ck_billing_reconciliation_quarantine_provider"),
        CheckConstraint("attempt_count >= 1", name="ck_billing_reconciliation_quarantine_attempt_count"),
        CheckConstraint("fence >= 1", name="ck_billing_reconciliation_quarantine_fence"),
        CheckConstraint(
            "length(remote_id) > 0 AND length(remote_id) <= 128",
            name="ck_billing_reconciliation_quarantine_remote_id",
        ),
        Index("idx_billing_reconciliation_quarantine_retry", "status", "next_retry_at"),
    )


class BillingReconciliationItemProgress(Base):
    """Idempotent per-item progress so a repeated page cannot skip unprocessed ids."""

    __tablename__ = "billing_reconciliation_item_progress"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    environment: Mapped[str] = mapped_column(Text, primary_key=True)
    seller_account: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    remote_id: Mapped[str] = mapped_column(Text, primary_key=True)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(f"kind IN ({_RECOVERY_KIND_SQL})", name="ck_billing_reconciliation_item_progress_kind"),
        CheckConstraint(
            f"status IN ({_ITEM_PROGRESS_STATUS_SQL})",
            name="ck_billing_reconciliation_item_progress_status",
        ),
        CheckConstraint(
            "environment IN ('sandbox', 'live')", name="ck_billing_reconciliation_item_progress_environment"
        ),
        CheckConstraint("provider IN ('polar', 'fake')", name="ck_billing_reconciliation_item_progress_provider"),
        CheckConstraint(
            "length(remote_id) > 0 AND length(remote_id) <= 128",
            name="ck_billing_reconciliation_item_progress_remote_id",
        ),
        CheckConstraint("fence >= 1", name="ck_billing_reconciliation_item_progress_fence"),
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


class TenantKeyIdempotency(Base):
    __tablename__ = "tenant_key_idempotency"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "operation",
            "idempotency_key",
            name="uq_tenant_key_idempotency_replay",
        ),
        Index("idx_tenant_key_idempotency_reclaim", "created_at"),
    )


class PortalTenantInvitation(Base):
    __tablename__ = "portal_tenant_invitation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    invited_email: Mapped[str] = mapped_column(Text, nullable=False)
    # WHY: only the digest is persisted, so a database read cannot mint a usable token.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    accepted_by_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portal_identity.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    tenant: Mapped[Tenant | None] = relationship()

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_portal_tenant_invitation_token_hash"),
        Index("idx_portal_tenant_invitation_reclaim", "expires_at", "accepted_at"),
        CheckConstraint(
            "accepted_at IS NULL OR tenant_id IS NOT NULL",
            name="ck_portal_tenant_invitation_accepted_requires_tenant",
        ),
    )


__all__ = [
    "ApiKeyRotationHistory",
    "BillingCheckoutAttempt",
    "BillingKnownItemLease",
    "BillingReconciliationCursor",
    "BillingReconciliationItemProgress",
    "BillingReconciliationQuarantine",
    "BillingSubscriptionProjection",
    "BillingWebhookInbox",
    "CHECKOUT_ATTEMPT_ACTIVE_STATUSES",
    "CheckoutAttemptErrorClass",
    "CheckoutAttemptStatus",
    "GlobalUsageAdmissionState",
    "PortalIdentity",
    "PortalTenantInvitation",
    "TenantEntitlement",
    "TenantKeyIdempotency",
    "UsageReservation",
]
