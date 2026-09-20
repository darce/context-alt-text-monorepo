"""Application service for tenant-bound portal identity claims."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PortalIdentity
from recognition.domain.portal_contracts import PortalIdentityService as PortalIdentityServiceProtocol
from recognition.domain.portal_contracts import PortalIdentityStatus, PortalPrincipal
from recognition.infrastructure.repositories.portal_identity_repository import (
    PortalIdentityClaimRefused,
    SqlAlchemyPortalIdentityRepository,
)

_DEFAULT_DB_TIMEOUT_S = 5.0


class _PortalIdentityRepository(Protocol):
    async def get_by_issuer_subject(self, issuer: str, subject: str) -> PortalIdentity | None: ...

    async def claim(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        tenant_id: UUID,
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


def _is_active(identity: PortalIdentity) -> bool:
    try:
        return PortalIdentityStatus(identity.status) is PortalIdentityStatus.ACTIVE
    except (TypeError, ValueError):
        return False


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
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if repository is not None and session is not None:
            raise ValueError("provide repository or session, not both")
        candidate = session if session is not None else repository
        if candidate is None:
            raise ValueError("a repository or session is required")
        self._timeout_s = timeout_s
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
        tenant_id: UUID | None = None,
    ) -> PortalPrincipal:
        """Atomically insert one active identity without transferring ownership."""
        _validate_identity_part("issuer", issuer)
        _validate_identity_part("subject", subject)
        _validate_email(email)
        if tenant_id is None:
            raise PortalIdentityClaimRefused("tenant_id is required to claim an existing tenant")
        if not isinstance(tenant_id, UUID):
            raise ValueError("tenant_id must be a UUID")
        try:
            identity = await _with_timeout(
                self._repository.claim(
                    issuer=issuer,
                    subject=subject,
                    email=email,
                    tenant_id=tenant_id,
                ),
                self._timeout_s,
            )
        except PortalIdentityClaimRefused:
            raise
        except IntegrityError as exc:
            raise PortalIdentityClaimRefused("portal identity claim was refused") from exc
        return _principal_from_identity(identity)


__all__ = [
    "PortalIdentityClaimRefused",
    "PortalIdentityServiceProtocol",
    "SqlAlchemyPortalIdentityService",
]
