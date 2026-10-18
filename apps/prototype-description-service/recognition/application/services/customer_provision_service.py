"""Concierge customer provision (AP-7).

Mints a real (non-demo) tenant + API key via the shared ``mint_api_key`` helper —
no parallel key store, no demo expiry/quota. Idempotent on normalized email.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Tenant
from recognition.application.services.api_key_admin_service import mint_api_key
from recognition.application.services.audit_service import AuditService
from recognition.config.security import RateLimitTier

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Commercial plan slug → rate-limit tier on the minted key (no separate plan engine).
_PLAN_TO_TIER: dict[str, RateLimitTier] = {
    "free": RateLimitTier.STANDARD,
    "pro": RateLimitTier.PRO,
    "enterprise": RateLimitTier.ENTERPRISE,
}

_ADMIN_ACTOR = "operator:provision-customer"
_ADMIN_SCOPE = "admin.customer_provision"
_EVENT_TYPE = "customer.provision"


@dataclass(frozen=True)
class ProvisionResult:
    """Outcome of a provision attempt.

    ``raw_key`` is set only on first mint; idempotent re-runs never re-emit it.
    """

    status: str  # "created" | "existing"
    tenant_id: uuid.UUID
    email: str
    plan: str
    label: str | None
    raw_key: str | None
    key_id: uuid.UUID | None


def normalize_email(email: str) -> str:
    """Lowercase + strip; raise ValueError on empty/invalid shape."""
    normalized = (email or "").strip().lower()
    if not normalized or not _EMAIL_RE.match(normalized):
        raise ValueError(f"invalid email: {email!r}")
    if len(normalized) > 240:
        raise ValueError("email too long for customer site_url binding")
    return normalized


def normalize_plan(plan: str | None) -> str:
    """Accept free|pro|enterprise (case-insensitive); default pro."""
    resolved = (plan or "pro").strip().lower()
    if resolved not in _PLAN_TO_TIER:
        raise ValueError(f"unknown plan {plan!r}; expected one of {sorted(_PLAN_TO_TIER)}")
    return resolved


def customer_site_url(email: str) -> str:
    """Stable unique site_url for a concierge customer (not a public website URL)."""
    return f"mailto:{normalize_email(email)}"


def plan_to_tier(plan: str) -> RateLimitTier:
    return _PLAN_TO_TIER[normalize_plan(plan)]


async def provision_customer(
    session: AsyncSession,
    *,
    email: str,
    plan: str = "pro",
    label: str | None = None,
    audit: AuditService | None = None,
) -> ProvisionResult:
    """Create tenant + first non-expiring key, or return the existing tenant for email.

    Idempotency key: ``tenants.primary_contact_email`` (unique). Re-runs do not
    mint a second key and never re-print a raw secret.
    """
    normalized_email = normalize_email(email)
    resolved_plan = normalize_plan(plan)
    display_name = (label or "").strip() or None
    tier = plan_to_tier(resolved_plan)
    site_url = customer_site_url(normalized_email)

    def _existing(tenant: Tenant) -> ProvisionResult:
        return ProvisionResult(
            status="existing",
            tenant_id=tenant.id,
            email=normalized_email,
            plan=tenant.plan or resolved_plan,
            label=tenant.display_name,
            raw_key=None,
            key_id=None,
        )

    async def _reselect() -> Tenant | None:
        return (
            await session.execute(select(Tenant).where(Tenant.primary_contact_email == normalized_email))
        ).scalar_one_or_none()

    existing = await _reselect()
    if existing is not None:
        return _existing(existing)

    tenant_id = uuid.uuid4()
    tenant = Tenant(
        id=tenant_id,
        site_url=site_url,
        primary_contact_email=normalized_email,
        display_name=display_name,
        plan=resolved_plan,
    )
    session.add(tenant)
    try:
        await session.flush()
    except IntegrityError:
        # A concurrent run won the unique-email race. The contract is idempotent on
        # email, so converge to the existing tenant instead of surfacing a crash.
        await session.rollback()
        raced = await _reselect()
        if raced is None:
            raise
        return _existing(raced)

    # No expires_in_days → permanent customer key (demo path is the one that sets expiry).
    record, raw = await mint_api_key(session, tenant_id=tenant_id, tier=tier, expires_in_days=None)

    audit_service = audit or AuditService()
    await audit_service.record_event(
        session,
        tenant_id=str(tenant_id),
        event_type=_EVENT_TYPE,
        actor=_ADMIN_ACTOR,
        scope=_ADMIN_SCOPE,
        payload={
            "email": normalized_email,
            "plan": resolved_plan,
            "label": display_name,
            "key_id": str(record.id),
            "tier": tier.value,
            # Never include raw key in audit payload.
        },
    )
    await session.commit()
    await session.refresh(tenant)

    return ProvisionResult(
        status="created",
        tenant_id=tenant.id,
        email=normalized_email,
        plan=resolved_plan,
        label=display_name,
        raw_key=raw,
        key_id=record.id,
    )


__all__ = [
    "ProvisionResult",
    "customer_site_url",
    "normalize_email",
    "normalize_plan",
    "plan_to_tier",
    "provision_customer",
]
