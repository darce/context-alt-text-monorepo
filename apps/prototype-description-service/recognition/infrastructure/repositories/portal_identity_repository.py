"""Persistence for the portal's verified issuer/subject identity binding."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PortalIdentity
from recognition.domain.portal_contracts import PortalIdentityStatus

_DEFAULT_DB_TIMEOUT_S = 5.0


class PortalIdentityClaimRefused(ValueError):  # noqa: N818 - domain refusal names the rejected operation
    """The database rejected an identity claim because ownership is taken."""


async def _with_timeout[T](operation: Awaitable[T], timeout_s: float) -> T:
    """Bound one request-scoped database operation."""
    return await asyncio.wait_for(operation, timeout=timeout_s)


def _validate_identity_part(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


class SqlAlchemyPortalIdentityRepository:
    """Store and resolve portal identities with an injected async session."""

    def __init__(self, session: AsyncSession, *, timeout_s: float = _DEFAULT_DB_TIMEOUT_S) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._session = session
        self._timeout_s = timeout_s

    async def get_by_issuer_subject(self, issuer: str, subject: str) -> PortalIdentity | None:
        """Return the active row owned by exactly this verified pair."""
        _validate_identity_part("issuer", issuer)
        _validate_identity_part("subject", subject)
        stmt: Select[tuple[PortalIdentity]] = (
            select(PortalIdentity)
            .where(
                PortalIdentity.issuer == issuer,
                PortalIdentity.subject == subject,
                PortalIdentity.status == PortalIdentityStatus.ACTIVE,
            )
            .limit(1)
        )
        result = await _with_timeout(self._session.execute(stmt), self._timeout_s)
        return result.scalar_one_or_none()

    async def claim(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        tenant_id: UUID,
    ) -> PortalIdentity:
        """Insert one active binding and let both unique constraints arbitrate races.

        There is intentionally no lookup before this insert. The unique
        ``(issuer, subject)`` and ``tenant_id`` constraints are the concurrency
        control and prevent an existing owner from being transferred.
        """
        _validate_identity_part("issuer", issuer)
        _validate_identity_part("subject", subject)
        if not isinstance(tenant_id, UUID):
            raise ValueError("tenant_id must be a UUID")
        if email is not None and not isinstance(email, str):
            raise ValueError("email must be a string or None")

        identity = PortalIdentity(
            tenant_id=tenant_id,
            issuer=issuer,
            subject=subject,
            email=email,
            status=PortalIdentityStatus.ACTIVE,
        )
        self._session.add(identity)
        try:
            await _with_timeout(self._session.flush(), self._timeout_s)
        except IntegrityError as exc:
            try:
                await _with_timeout(self._session.rollback(), self._timeout_s)
            except Exception as rollback_error:  # noqa: BLE001 - preserve the domain refusal on cleanup failure
                raise PortalIdentityClaimRefused("portal identity claim was refused") from rollback_error
            raise PortalIdentityClaimRefused("portal identity claim was refused") from exc
        return identity


__all__ = [
    "PortalIdentityClaimRefused",
    "SqlAlchemyPortalIdentityRepository",
]
