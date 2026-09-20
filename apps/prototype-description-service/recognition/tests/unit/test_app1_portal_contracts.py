"""Pure contract tests for the APP-1 portal foundation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from recognition.domain.portal_contracts import (
    DEFAULT_ALLOWANCE_JOBS,
    DEFAULT_ENTITLEMENT_STATUS,
    BillingProvider,
    BillingState,
    BillingSubscriptionStatus,
    EntitlementSnapshot,
    EntitlementStatus,
    PortalIdentityService,
    PortalIdentityStatus,
    PortalPrincipal,
    TenantEntitlementService,
    UsageAdmissionService,
    UsageReservationStatus,
    UsageTicket,
    WebhookInboxStatus,
)


@pytest.mark.parametrize(
    "enum_type",
    [
        PortalIdentityStatus,
        EntitlementStatus,
        UsageReservationStatus,
        BillingSubscriptionStatus,
        WebhookInboxStatus,
    ],
)
def test_status_enum_values_round_trip_as_strings(enum_type) -> None:
    for member in enum_type:
        assert enum_type(str(member)) is member
        assert str(member) == member.value


def test_boundary_dataclasses_are_frozen() -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)
    values = [
        PortalPrincipal(tenant_id, "issuer", "subject", "person@example.test"),
        EntitlementSnapshot(
            tenant_id,
            EntitlementStatus.BETA_ACTIVE,
            allowance_jobs=10,
            used_jobs=0,
            period_start=now,
            period_end=now,
            grace_until=None,
        ),
        UsageTicket(uuid4(), tenant_id, "request-1", 1),
        BillingState(tenant_id, BillingSubscriptionStatus.NONE, None, None, None),
    ]

    for value in values:
        assert is_dataclass(value)
        with pytest.raises(FrozenInstanceError):
            value.tenant_id = UUID(int=0)


class _PortalIdentityStub:
    async def resolve_principal(self, issuer: str, subject: str) -> PortalPrincipal | None:
        return None

    async def claim_tenant(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        tenant_id: UUID | None = None,
    ) -> PortalPrincipal:
        return PortalPrincipal(tenant_id or uuid4(), issuer, subject, email)


class _TenantEntitlementStub:
    async def snapshot(self, tenant_id: UUID) -> EntitlementSnapshot:
        now = datetime.now(UTC)
        return EntitlementSnapshot(tenant_id, DEFAULT_ENTITLEMENT_STATUS, 0, 0, now, now, None)

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
        return EntitlementSnapshot(
            tenant_id,
            EntitlementStatus.BETA_ACTIVE,
            allowance_jobs,
            0,
            period_start,
            period_end,
            None,
        )

    async def apply_billing_state(self, tenant_id: UUID, state: BillingState) -> EntitlementSnapshot:
        now = datetime.now(UTC)
        return EntitlementSnapshot(tenant_id, EntitlementStatus.EXPIRED, 0, 0, now, now, None)


class _UsageAdmissionStub:
    async def reserve(
        self,
        tenant_id: UUID,
        *,
        idempotency_key: str,
        job_id: str | None,
        cost_units: int,
    ) -> UsageTicket:
        return UsageTicket(uuid4(), tenant_id, idempotency_key, cost_units)

    async def commit(self, ticket: UsageTicket) -> None:
        return None

    async def release(self, ticket: UsageTicket) -> None:
        return None


class _BillingProviderStub:
    async def create_checkout_session(
        self,
        *,
        tenant_id: UUID,
        plan_code: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        return success_url

    async def create_portal_session(self, *, tenant_id: UUID, return_url: str) -> str:
        return return_url

    async def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        return bool(raw_body and signature)

    async def parse_event(self, raw_body: bytes) -> dict[str, object]:
        return {"raw_body": raw_body}


@pytest.mark.parametrize(
    ("protocol", "stub"),
    [
        (PortalIdentityService, _PortalIdentityStub()),
        (TenantEntitlementService, _TenantEntitlementStub()),
        (UsageAdmissionService, _UsageAdmissionStub()),
        (BillingProvider, _BillingProviderStub()),
    ],
)
def test_protocols_are_runtime_checkable(protocol, stub) -> None:
    assert protocol._is_runtime_protocol is True
    assert isinstance(stub, protocol)


def test_stub_omitting_a_required_method_fails_structural_check() -> None:
    class MissingParseEvent:
        async def create_checkout_session(self, **kwargs) -> str:
            return ""

        async def create_portal_session(self, **kwargs) -> str:
            return ""

        async def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
            return True

    assert not isinstance(MissingParseEvent(), BillingProvider)


def test_missing_entitlement_is_fail_safe_zero_allowance() -> None:
    assert DEFAULT_ALLOWANCE_JOBS == 0
    assert DEFAULT_ENTITLEMENT_STATUS is EntitlementStatus.EXPIRED


def test_billing_state_requires_customer_for_persistable_status() -> None:
    """A non-``none`` status must carry the customer id the projection requires."""
    tenant_id = uuid4()
    for status in (
        BillingSubscriptionStatus.ACTIVE,
        BillingSubscriptionStatus.PAST_DUE,
        BillingSubscriptionStatus.CANCELED,
        BillingSubscriptionStatus.REFUND_HOLD,
    ):
        with pytest.raises(ValueError, match="provider_customer_id is required"):
            BillingState(tenant_id, status, None, None, None)

    # The derived "no projection row" state stays representable.
    assert BillingState(tenant_id, BillingSubscriptionStatus.NONE, None, None, None).provider_customer_id is None


def test_usage_and_billing_tables_reject_out_of_enum_and_non_positive_writes() -> None:
    """Direct DB writes cannot bypass the service-layer guards ([sr-007], [COST-10])."""
    from db.models.portal_billing import BillingSubscriptionProjection, UsageReservation

    reservation_checks = {
        c.name: str(c.sqltext) for c in UsageReservation.__table__.constraints if hasattr(c, "sqltext")
    }
    assert "ck_usage_reservation_cost_units_positive" in reservation_checks
    assert "cost_units > 0" in reservation_checks["ck_usage_reservation_cost_units_positive"]

    reservation_statuses = reservation_checks["ck_usage_reservation_status"]
    for member in UsageReservationStatus:
        assert f"'{member.value}'" in reservation_statuses

    projection_checks = {
        c.name: str(c.sqltext) for c in BillingSubscriptionProjection.__table__.constraints if hasattr(c, "sqltext")
    }
    projection_statuses = projection_checks["ck_billing_subscription_projection_status"]
    for member in BillingSubscriptionStatus:
        assert f"'{member.value}'" in projection_statuses
