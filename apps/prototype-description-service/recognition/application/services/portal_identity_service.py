"""Application service for tenant-bound portal identity claims."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PortalIdentity
from db.tenant_context import set_tenant_context
from recognition.domain.portal_contracts import PortalIdentityService as PortalIdentityServiceProtocol
from recognition.domain.portal_contracts import PortalIdentityStatus, PortalPrincipal
from recognition.infrastructure.repositories.portal_identity_repository import (
    PortalIdentityClaimError,
    PortalIdentityClaimRecord,
    PortalIdentityClaimRefused,
    SqlAlchemyPortalIdentityRepository,
)
from recognition.shared.db.dialect import is_postgres

_DEFAULT_DB_TIMEOUT_S = 5.0
_BETA_ALLOWANCE_JOBS = 10
_BETA_ALLOWANCE_VERSION = "beta-v1"
_BETA_PERIOD_DAYS = 30
_BETA_GRANT_SOURCE = "portal.onboarding.claim"
_CLAIM_AUDIT_EVENT = "portal.identity.claim"
_CLAIM_AUDIT_ACTOR = "portal-identity-service"
_CLAIM_AUDIT_SCOPE = "portal.identity"


class _PortalIdentityRepository(Protocol):
    async def get_by_issuer_subject(self, issuer: str, subject: str) -> PortalIdentity | None: ...

    async def claim(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        invitation_token: str,
    ) -> PortalIdentity: ...


async def _with_timeout[T](operation: Awaitable[T], timeout_s: float) -> T:
    """Bound one repository call so a request cannot wait indefinitely."""
    return await asyncio.wait_for(operation, timeout=timeout_s)


def _validate_identity_part(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _validate_email(email: str | None) -> None:
    if email is not None and not isinstance(email, str):
        raise ValueError("email must be a string or None")


def _validate_invitation_token(invitation_token: str) -> None:
    if not isinstance(invitation_token, str) or not invitation_token.strip():
        raise PortalIdentityClaimRefused("portal identity claim was refused")


def _is_active(identity: PortalIdentity) -> bool:
    try:
        return PortalIdentityStatus(identity.status) is PortalIdentityStatus.ACTIVE
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True, slots=True)
class PortalClaimOutcome:
    """HTTP-facing claim result whose replay flag is decided in the same transaction."""

    principal: PortalPrincipal
    replayed: bool


def _principal_from_identity(identity: PortalIdentity) -> PortalPrincipal:
    if not _is_active(identity):
        raise PortalIdentityClaimRefused("portal identity is not active")
    try:
        tenant_id = identity.tenant_id if isinstance(identity.tenant_id, UUID) else UUID(str(identity.tenant_id))
    except (AttributeError, TypeError, ValueError) as exc:
        raise PortalIdentityClaimRefused("portal identity has no valid tenant owner") from exc
    return PortalPrincipal(
        tenant_id=tenant_id,
        issuer=identity.issuer,
        subject=identity.subject,
        email=identity.email,
    )


class SqlAlchemyPortalIdentityService:
    """Implement ``PortalIdentityService`` over a request-scoped repository."""

    def __init__(
        self,
        repository: _PortalIdentityRepository | AsyncSession | None = None,
        *,
        session: AsyncSession | None = None,
        timeout_s: float = _DEFAULT_DB_TIMEOUT_S,
        beta_grant: Callable[..., Awaitable[object]] | None = None,
        audit_service: object | None = None,
        entitlement_service: object | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if repository is not None and session is not None:
            raise ValueError("provide repository or session, not both")
        candidate = session if session is not None else repository
        if candidate is None:
            raise ValueError("a repository or session is required")
        self._timeout_s = timeout_s
        self._beta_grant = beta_grant
        self._audit_service = audit_service
        self._entitlement_service = entitlement_service
        self._clock = clock or (lambda: datetime.now(UTC))
        if callable(getattr(candidate, "claim", None)) and callable(getattr(candidate, "get_by_issuer_subject", None)):
            self._repository: _PortalIdentityRepository = candidate  # type: ignore[assignment]
        else:
            self._repository = SqlAlchemyPortalIdentityRepository(candidate, timeout_s=timeout_s)  # type: ignore[arg-type]

    async def resolve_principal(self, issuer: str, subject: str) -> PortalPrincipal | None:
        """Resolve only the active tenant owned by this exact issuer/subject pair."""
        _validate_identity_part("issuer", issuer)
        _validate_identity_part("subject", subject)
        identity = await _with_timeout(
            self._repository.get_by_issuer_subject(issuer, subject),
            self._timeout_s,
        )
        if identity is None or not _is_active(identity):
            return None
        try:
            return _principal_from_identity(identity)
        except PortalIdentityClaimRefused:
            return None

    async def claim_tenant(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        invitation_token: str,
    ) -> PortalPrincipal:
        """Atomically redeem one invitation into one active tenant identity."""
        _validate_identity_part("issuer", issuer)
        _validate_identity_part("subject", subject)
        _validate_email(email)
        _validate_invitation_token(invitation_token)
        try:
            identity = await _with_timeout(
                self._repository.claim(
                    issuer=issuer,
                    subject=subject,
                    email=email,
                    invitation_token=invitation_token,
                ),
                self._timeout_s,
            )
        except PortalIdentityClaimRefused:
            raise
        except IntegrityError as exc:
            raise PortalIdentityClaimRefused("portal identity claim was refused") from exc
        return _principal_from_identity(identity)

    async def claim_onboarding(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        invitation_token: str,
    ) -> PortalClaimOutcome:
        """Atomically redeem or replay one invitation and grant beta once."""
        _validate_identity_part("issuer", issuer)
        _validate_identity_part("subject", subject)
        _validate_email(email)
        if not isinstance(invitation_token, str) or not invitation_token.strip():
            raise PortalIdentityClaimError("invalid_claim_request")
        claimer = getattr(self._repository, "claim_onboarding", None)
        if not callable(claimer):
            raise PortalIdentityClaimError("portal_identity_unavailable")
        try:
            record = await _with_timeout(
                claimer(
                    issuer=issuer,
                    subject=subject,
                    email=email,
                    invitation_token=invitation_token,
                ),
                self._timeout_s,
            )
        except PortalIdentityClaimError:
            raise
        except PortalIdentityClaimRefused:
            raise
        except TimeoutError as exc:
            await self._rollback()
            raise PortalIdentityClaimError("portal_identity_unavailable") from exc
        except IntegrityError as exc:
            raise PortalIdentityClaimError("not_admitted") from exc
        if not isinstance(record, PortalIdentityClaimRecord):
            raise PortalIdentityClaimError("portal_identity_unavailable")
        principal = _principal_from_identity(record.identity)
        if record.replayed:
            return PortalClaimOutcome(principal=principal, replayed=True)
        try:
            await self._complete_first_claim(principal)
        except PortalIdentityClaimError:
            raise
        except Exception as exc:
            await self._rollback()
            raise PortalIdentityClaimError("portal_identity_unavailable") from exc
        return PortalClaimOutcome(principal=principal, replayed=False)

    async def _complete_first_claim(self, principal: PortalPrincipal) -> None:
        session = getattr(self._repository, "session", None)
        try:
            postgres = session is not None and is_postgres(session)
        except Exception:
            postgres = False
        if postgres:
            await set_tenant_context(session, principal.tenant_id)
        now = self._clock()
        grant = self._beta_grant
        if grant is None and self._entitlement_service is not None:
            grant = getattr(self._entitlement_service, "grant_beta", None)
        if grant is None and session is not None:
            from recognition.application.services.tenant_entitlement_service import TenantEntitlementService

            grant = TenantEntitlementService(session).grant_beta
        if not callable(grant):
            raise PortalIdentityClaimError("portal_identity_unavailable")
        await grant(
            principal.tenant_id,
            allowance_jobs=_BETA_ALLOWANCE_JOBS,
            allowance_version=_BETA_ALLOWANCE_VERSION,
            period_start=now,
            period_end=now + timedelta(days=_BETA_PERIOD_DAYS),
            source=_BETA_GRANT_SOURCE,
        )
        audit = self._audit_service
        if audit is None and session is not None:
            from recognition.application.services.audit_service import AuditService

            audit = AuditService()
        recorder = getattr(audit, "record_event", None)
        if not callable(recorder):
            raise PortalIdentityClaimError("portal_identity_unavailable")
        await recorder(
            session,
            tenant_id=str(principal.tenant_id),
            event_type=_CLAIM_AUDIT_EVENT,
            actor=_CLAIM_AUDIT_ACTOR,
            scope=_CLAIM_AUDIT_SCOPE,
            payload={
                "issuer": principal.issuer,
                "subject": principal.subject,
                "replayed": False,
            },
        )

    async def _rollback(self) -> None:
        session = getattr(self._repository, "session", None)
        rollback = getattr(session, "rollback", None)
        if not callable(rollback):
            rollback = getattr(self._repository, "_rollback_after_failure", None)
        if callable(rollback):
            await rollback()


__all__ = [
    "PortalClaimOutcome",
    "PortalIdentityClaimError",
    "PortalIdentityClaimRefused",
    "PortalIdentityServiceProtocol",
    "SqlAlchemyPortalIdentityService",
]
