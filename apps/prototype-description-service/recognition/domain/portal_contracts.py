"""The portal security policy forbids cross-tenant reads or writes, returning a secret twice, charging during beta, or reviving a revoked key; only an authenticated principal may resolve or mutate its own tenant, only an explicit paid transition may authorize billing, and providers may report state but never grant access by redirect alone. Missing entitlement state is fail-safe: it means zero allowance, never unlimited access, and revoked or expired states remain closed until an authoritative grant replaces them."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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


# A missing entitlement row is closed by construction rather than interpreted as unlimited.
DEFAULT_ALLOWANCE_JOBS: Final[int] = 0
DEFAULT_ENTITLEMENT_STATUS: Final[EntitlementStatus] = EntitlementStatus.EXPIRED


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
    reservation_id: UUID
    tenant_id: UUID
    idempotency_key: str
    cost_units: int


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
        """Atomically reserve tenant allowance once and reject overspend under contention."""
        ...

    async def commit(self, ticket: UsageTicket) -> None:
        """Settle one reservation idempotently so retries cannot double-charge usage."""
        ...

    async def release(self, ticket: UsageTicket) -> None:
        """Release an admitted reservation only when the costly job did not run."""
        ...


@runtime_checkable
class BillingProvider(Protocol):
    async def create_checkout_session(
        self,
        *,
        tenant_id: UUID,
        plan_code: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
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
    ) -> object:
        """Read authoritative provider state for the reconciliation worker."""
        ...

    async def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        """Accept webhook processing only after exact raw-body signature verification."""
        ...

    async def parse_event(self, raw_body: bytes) -> Mapping[str, object]:
        """Normalize a verified provider payload without granting access from its arrival alone."""
        ...


__all__ = [
    "DEFAULT_ALLOWANCE_JOBS",
    "DEFAULT_ENTITLEMENT_STATUS",
    "BillingProvider",
    "BillingState",
    "BillingSubscriptionStatus",
    "EntitlementSnapshot",
    "EntitlementStatus",
    "PortalIdentityService",
    "PortalIdentityStatus",
    "PortalPrincipal",
    "TenantEntitlementService",
    "UsageAdmissionService",
    "UsageReservationStatus",
    "UsageTicket",
    "WebhookInboxStatus",
]
