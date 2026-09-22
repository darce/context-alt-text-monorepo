"""The portal security policy forbids cross-tenant reads or writes, returning a secret twice, charging during beta, or reviving a revoked key; only an authenticated principal may resolve or mutate its own tenant, only an explicit paid transition may authorize billing, and providers may report state but never grant access by redirect alone. Missing entitlement state is fail-safe: it means zero allowance, never unlimited access, and revoked or expired states remain closed until an authoritative grant replaces them."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable
from uuid import UUID


class PortalIdentityStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class EntitlementStatus(StrEnum):
    BETA_ACTIVE = "beta_active"
    PAID_ACTIVE = "paid_active"
    PAST_DUE = "past_due"
    EXPIRED = "expired"
    REVOKED = "revoked"


class UsageReservationStatus(StrEnum):
    RESERVED = "reserved"
    COMMITTED = "committed"
    RELEASED = "released"
    EXPIRED = "expired"


class BillingSubscriptionStatus(StrEnum):
    NONE = "none"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    REFUND_HOLD = "refund_hold"


class WebhookInboxStatus(StrEnum):
    RECEIVED = "received"
    PROCESSED = "processed"
    FAILED = "failed"
    DISCARDED = "discarded"


class ReconciliationKind(StrEnum):
    """Durable cursor kinds owned by C0. Known-inbox leases are a separate contract."""

    SUBSCRIPTIONS = "subscriptions"
    AMBIGUOUS_CHECKOUTS = "ambiguous_checkouts"


class EnumerationObservationReason(StrEnum):
    SELLER_MISMATCH = "seller_mismatch"
    ENVIRONMENT_MISMATCH = "environment_mismatch"
    TENANT_UNPARSEABLE = "tenant_unparseable"
    EMAIL_IDENTITY_REJECTED = "email_identity_rejected"
    MALFORMED_ITEM = "malformed_item"
    MISSING_REMOTE_ID = "missing_remote_id"


class QuarantineStatus(StrEnum):
    OPEN = "open"
    RETRY_PENDING = "retry_pending"
    EXHAUSTED = "exhausted"
    RESOLVED = "resolved"


# A missing entitlement row is closed by construction rather than interpreted as unlimited.
DEFAULT_ALLOWANCE_JOBS: Final[int] = 0
DEFAULT_ENTITLEMENT_STATUS: Final[EntitlementStatus] = EntitlementStatus.EXPIRED

# Singleton global admission row. Missing/invalid config is fail-closed 503, never unlimited.
GLOBAL_USAGE_ADMISSION_STATE_ID: Final[str] = "global"
DEFAULT_GLOBAL_DAILY_COST_LIMIT: Final[int] = 10_000
DEFAULT_GLOBAL_INFLIGHT_LIMIT: Final[int] = 1_000
DEFAULT_GLOBAL_QUEUE_LIMIT: Final[int] = 1_000
DEFAULT_GLOBAL_QUEUE_BYTE_LIMIT: Final[int] = 256 * 1024 * 1024
DEFAULT_GLOBAL_CONFIG_VERSION: Final[str] = "v1"
DEFAULT_GLOBAL_FENCE_EPOCH: Final[int] = 1

# C0 recovery bounds. R1 consumes these; C0 does not run the worker.
RECONCILIATION_PAGE_LIMIT: Final[int] = 50
RECONCILIATION_MAX_PAGES_PER_RUN: Final[int] = 20
RECONCILIATION_DEFAULT_LEASE_SECONDS: Final[int] = 30
RECONCILIATION_PROVIDER_TIMEOUT_SECONDS: Final[float] = 8.0
RECONCILIATION_MAX_REMOTE_ID_LENGTH: Final[int] = 128
RECONCILIATION_MAX_CURSOR_LENGTH: Final[int] = 256
RECONCILIATION_MAX_OWNER_LENGTH: Final[int] = 128
RECONCILIATION_MAX_FAILURE_CLASS_LENGTH: Final[int] = 64
RECONCILIATION_MAX_OPERATOR_REASON_LENGTH: Final[int] = 256
RECONCILIATION_MAX_OBSERVATION_DETAIL_KEYS: Final[int] = 8
RECONCILIATION_MAX_OBSERVATION_DETAIL_VALUE_LENGTH: Final[int] = 128


@dataclass(frozen=True, slots=True)
class PortalPrincipal:
    tenant_id: UUID
    issuer: str
    subject: str
    email: str | None


@dataclass(frozen=True, slots=True)
class EntitlementSnapshot:
    tenant_id: UUID
    status: EntitlementStatus
    allowance_jobs: int
    used_jobs: int
    period_start: datetime
    period_end: datetime
    grace_until: datetime | None


@dataclass(frozen=True, slots=True)
class UsageTicket:
    """Retry-stable admission ticket.

    Published positional fields stay ``reservation_id``, ``tenant_id``,
    ``idempotency_key``, and ``cost_units``. G1 adds operation identity, the
    pre-bound job id, and the settlement fence; defaults keep existing
    constructors valid until G2/G3 pass the new fields.
    """

    reservation_id: UUID
    tenant_id: UUID
    idempotency_key: str
    cost_units: int
    operation_id: str = ""
    request_fingerprint: str = ""
    job_id: str | None = None
    fence_token: str = ""


@dataclass(frozen=True, slots=True)
class BillingState:
    """Authoritative provider billing state for one tenant.

    ``provider_customer_id`` is optional only for :attr:`BillingSubscriptionStatus.NONE`,
    which is the derived state of a tenant that has no projection row at all.
    Every persistable status carries a customer id, because
    ``billing_subscription_projection.provider_customer_id`` is ``NOT NULL`` and
    a row only exists because a provider event created it ([rg-005]).
    """

    tenant_id: UUID
    status: BillingSubscriptionStatus
    provider_customer_id: str | None
    current_period_end: datetime | None
    past_due_since: datetime | None
    provider_subscription_id: str | None = None
    event_position: datetime | None = None

    def __post_init__(self) -> None:
        if self.status is not BillingSubscriptionStatus.NONE and not self.provider_customer_id:
            raise ValueError(f"provider_customer_id is required for billing status {self.status.value}")


@runtime_checkable
class PortalIdentityService(Protocol):
    async def resolve_principal(self, issuer: str, subject: str) -> PortalPrincipal | None:
        """Resolve only the tenant owned by the verified issuer/subject pair."""
        ...

    async def claim_tenant(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        invitation_token: str,
    ) -> PortalPrincipal:
        """Atomically redeem one single-use invitation into one owned tenant."""
        ...


@runtime_checkable
class TenantEntitlementService(Protocol):
    async def snapshot(self, tenant_id: UUID) -> EntitlementSnapshot:
        """Return zero allowance when no current entitlement authorizes work."""
        ...

    async def grant_beta(
        self,
        tenant_id: UUID,
        *,
        allowance_jobs: int,
        allowance_version: str,
        period_start: datetime,
        period_end: datetime,
        source: str,
    ) -> EntitlementSnapshot:
        """Grant beta work only through an audited tenant-bound entitlement mutation."""
        ...

    async def apply_billing_state(self, tenant_id: UUID, state: BillingState) -> EntitlementSnapshot:
        """Apply authoritative billing state without converting beta usage into arrears."""
        ...


@runtime_checkable
class UsageAdmissionService(Protocol):
    async def reserve(
        self,
        tenant_id: UUID,
        *,
        idempotency_key: str,
        job_id: str | None,
        cost_units: int,
    ) -> UsageTicket:
        """Atomically reserve tenant allowance once and reject overspend under contention.

        Compatible published signature. The G1 implementation also accepts
        ``operation_id``, ``request_fingerprint``, and ``queue_bytes`` and
        exposes ``commit_fenced`` / ``release_fenced`` for worker settlement.
        """
        ...

    async def commit(self, ticket: UsageTicket) -> None:
        """Settle one reservation idempotently so retries cannot double-charge usage."""
        ...

    async def release(self, ticket: UsageTicket) -> None:
        """Release an admitted reservation only when the costly job did not run."""
        ...


@dataclass(frozen=True, slots=True)
class CheckoutSession:
    """Hosted checkout identity returned by a provider adapter."""

    url: str
    provider_checkout_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or not self.url:
            raise ValueError("checkout url is required")
        if not isinstance(self.provider_checkout_id, str) or not self.provider_checkout_id:
            raise ValueError("provider_checkout_id is required")


@dataclass(frozen=True, slots=True)
class EnumerationObservation:
    """Bounded, non-secret observation for one untrusted vendor item.

    ``remote_id`` is a vendor identifier or a deterministic digest. Details never
    copy the vendor payload, email, or secrets.
    """

    reason: EnumerationObservationReason
    remote_id: str
    details: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.reason, EnumerationObservationReason):
            raise ValueError("observation reason must be EnumerationObservationReason")
        if not isinstance(self.remote_id, str) or not self.remote_id:
            raise ValueError("observation remote_id is required")
        if len(self.remote_id) > RECONCILIATION_MAX_REMOTE_ID_LENGTH:
            raise ValueError("observation remote_id exceeds the bounded identifier length")
        if not isinstance(self.details, Mapping):
            raise ValueError("observation details must be a mapping")
        if len(self.details) > RECONCILIATION_MAX_OBSERVATION_DETAIL_KEYS:
            raise ValueError("observation details exceed the bounded key count")
        normalized: dict[str, str] = {}
        for key, value in self.details.items():
            if not isinstance(key, str) or not key or not isinstance(value, str):
                raise ValueError("observation details must be string keys and values")
            if len(value) > RECONCILIATION_MAX_OBSERVATION_DETAIL_VALUE_LENGTH:
                raise ValueError("observation detail value exceeds the bounded length")
            normalized[key] = value
        object.__setattr__(self, "details", normalized)


@dataclass(frozen=True, slots=True)
class EnumerationPage:
    """One bounded page of provider subscriptions with an opaque continuation cursor.

    Existing constructors ``EnumerationPage(items, next_cursor, exhausted)`` stay
    valid. Invalid vendor items are exposed on ``observations`` rather than dropped.
    """

    items: tuple[BillingState, ...]
    next_cursor: str | None
    exhausted: bool
    observations: tuple[EnumerationObservation, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconciliationCursorKey:
    """Seller-wide cursor identity. This is not a tenant and must not be used as one."""

    provider: str
    environment: str
    seller_account: str
    kind: ReconciliationKind

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider is required")
        if self.environment not in {"sandbox", "live"}:
            raise ValueError("environment must be sandbox or live")
        if not isinstance(self.seller_account, str) or not self.seller_account.strip():
            raise ValueError("seller_account is required")
        if not isinstance(self.kind, ReconciliationKind):
            raise ValueError("kind must be a ReconciliationKind")
        object.__setattr__(self, "provider", self.provider.strip())
        object.__setattr__(self, "seller_account", self.seller_account.strip())


@dataclass(frozen=True, slots=True)
class ReconciliationLease:
    """Fenced cursor ownership returned after a short acquire transaction.

    Caller must commit the acquire transaction before any vendor I/O. ``fence`` is
    a monotonically increasing generation; lease expiry timestamps are not a fence.
    """

    key: ReconciliationCursorKey
    owner: str
    fence: int
    lease_until: datetime
    cursor: str | None
    last_progress_at: datetime | None
    exhausted: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.key, ReconciliationCursorKey):
            raise ValueError("lease key is required")
        if not isinstance(self.owner, str) or not self.owner.strip():
            raise ValueError("lease owner is required")
        if not isinstance(self.fence, int) or isinstance(self.fence, bool) or self.fence < 1:
            raise ValueError("lease fence must be a positive integer")
        if not isinstance(self.lease_until, datetime) or self.lease_until.tzinfo is None:
            raise ValueError("lease_until must be a timezone-aware datetime")
        if self.cursor is not None and (not isinstance(self.cursor, str) or not self.cursor):
            raise ValueError("cursor must be opaque text when present")
        if self.cursor is not None and len(self.cursor) > RECONCILIATION_MAX_CURSOR_LENGTH:
            raise ValueError("cursor exceeds the bounded length")
        object.__setattr__(self, "owner", self.owner.strip())


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """Durable per-item quarantine. Audited retry cannot invent a tenant or paid state."""

    key: ReconciliationCursorKey
    remote_id: str
    reason: EnumerationObservationReason
    status: QuarantineStatus
    attempt_count: int
    fence: int
    next_retry_at: datetime | None = None
    operator_identity: str | None = None
    operator_reason: str | None = None


class ReconciliationLeaseConflictError(Exception):
    """The caller no longer owns the cursor: expired, stolen, or stale fence."""


class ReconciliationCursorAdvanceError(Exception):
    """Advancing the cursor would skip an unprocessed page item."""


class ReconciliationQuarantineConflictError(Exception):
    """Quarantine mutation was rejected (missing row, fence, or illegal retry)."""


@runtime_checkable
class BillingProvider(Protocol):
    async def create_checkout_session(
        self,
        *,
        tenant_id: UUID,
        plan_code: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
        attempt_id: UUID,
    ) -> CheckoutSession:
        """Create a server-selected checkout session bound to one tenant and catalog plan."""
        ...

    async def create_portal_session(self, *, tenant_id: UUID, return_url: str) -> str:
        """Create a hosted billing session only for the tenant's mapped customer."""
        ...

    async def retrieve_state(
        self,
        *,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        request_timeout: float,
    ) -> BillingState:
        """Read authoritative provider state for the reconciliation worker."""
        ...

    async def retrieve_checkout(
        self,
        *,
        provider_checkout_id: str,
        request_timeout: float,
    ) -> Mapping[str, object]:
        """Read one checkout session so an ambiguous attempt can be recovered."""
        ...

    async def enumerate_subscriptions(
        self,
        *,
        cursor: str | None,
        limit: int,
        request_timeout: float,
    ) -> EnumerationPage:
        """Read one bounded page of provider subscriptions for orphan recovery."""
        ...

    async def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        """Accept webhook processing only after full-header raw-body signature verification."""
        ...

    async def parse_event(self, raw_body: bytes) -> Mapping[str, object]:
        """Normalize a verified provider payload without granting access from its arrival alone."""
        ...


@runtime_checkable
class BillingReconciliationRepository(Protocol):
    """C0 persistence boundary. Caller owns the transaction and commits before vendor I/O."""

    async def acquire_lease(
        self,
        key: ReconciliationCursorKey,
        *,
        owner: str,
        lease_ttl: timedelta,
        now: datetime,
    ) -> ReconciliationLease | None:
        """Acquire or steal an expired lease in a short transaction. No vendor I/O."""
        ...

    async def heartbeat(
        self,
        lease: ReconciliationLease,
        *,
        now: datetime,
        lease_ttl: timedelta,
    ) -> ReconciliationLease:
        """Extend lease expiry under the current fence. Rejects stolen/expired/old-generation leases."""
        ...

    async def complete_item(
        self,
        lease: ReconciliationLease,
        *,
        remote_id: str,
        now: datetime,
    ) -> None:
        """Idempotent per-item progress under the current fence."""
        ...

    async def quarantine_item(
        self,
        lease: ReconciliationLease,
        *,
        observation: EnumerationObservation,
        now: datetime,
    ) -> QuarantineRecord:
        """Persist a bounded quarantine observation and mark the item progressed."""
        ...

    async def advance_cursor(
        self,
        lease: ReconciliationLease,
        *,
        next_cursor: str | None,
        exhausted: bool,
        page_remote_ids: tuple[str, ...],
        now: datetime,
    ) -> ReconciliationLease:
        """Advance the opaque cursor only after every page remote id has progressed."""
        ...

    async def record_page_failure(
        self,
        lease: ReconciliationLease,
        *,
        failure_class: str,
        now: datetime,
    ) -> ReconciliationLease:
        """Record bounded page failure metadata without treating the run as progress."""
        ...

    async def audited_retry(
        self,
        lease: ReconciliationLease,
        *,
        remote_id: str,
        operator_identity: str,
        operator_reason: str,
        now: datetime,
    ) -> QuarantineRecord:
        """Requeue one quarantined item. Cannot manufacture a tenant or grant paid state."""
        ...

    async def get_quarantine(
        self,
        key: ReconciliationCursorKey,
        remote_id: str,
    ) -> QuarantineRecord | None:
        """Read one quarantine row in the seller-wide namespace."""
        ...


__all__ = [
    "DEFAULT_ALLOWANCE_JOBS",
    "DEFAULT_ENTITLEMENT_STATUS",
    "DEFAULT_GLOBAL_CONFIG_VERSION",
    "DEFAULT_GLOBAL_DAILY_COST_LIMIT",
    "DEFAULT_GLOBAL_FENCE_EPOCH",
    "DEFAULT_GLOBAL_INFLIGHT_LIMIT",
    "DEFAULT_GLOBAL_QUEUE_BYTE_LIMIT",
    "DEFAULT_GLOBAL_QUEUE_LIMIT",
    "GLOBAL_USAGE_ADMISSION_STATE_ID",
    "RECONCILIATION_DEFAULT_LEASE_SECONDS",
    "RECONCILIATION_MAX_CURSOR_LENGTH",
    "RECONCILIATION_MAX_FAILURE_CLASS_LENGTH",
    "RECONCILIATION_MAX_OBSERVATION_DETAIL_KEYS",
    "RECONCILIATION_MAX_OBSERVATION_DETAIL_VALUE_LENGTH",
    "RECONCILIATION_MAX_OPERATOR_REASON_LENGTH",
    "RECONCILIATION_MAX_OWNER_LENGTH",
    "RECONCILIATION_MAX_PAGES_PER_RUN",
    "RECONCILIATION_MAX_REMOTE_ID_LENGTH",
    "RECONCILIATION_PAGE_LIMIT",
    "RECONCILIATION_PROVIDER_TIMEOUT_SECONDS",
    "BillingProvider",
    "BillingReconciliationRepository",
    "BillingState",
    "BillingSubscriptionStatus",
    "CheckoutSession",
    "EntitlementSnapshot",
    "EntitlementStatus",
    "EnumerationObservation",
    "EnumerationObservationReason",
    "EnumerationPage",
    "PortalIdentityService",
    "PortalIdentityStatus",
    "PortalPrincipal",
    "TenantEntitlementService",
    "UsageAdmissionService",
    "UsageReservationStatus",
    "UsageTicket",
    "WebhookInboxStatus",
    "QuarantineRecord",
    "QuarantineStatus",
    "ReconciliationCursorAdvanceError",
    "ReconciliationCursorKey",
    "ReconciliationKind",
    "ReconciliationLease",
    "ReconciliationLeaseConflictError",
    "ReconciliationQuarantineConflictError",
]
