"""Persistence for the portal's verified issuer/subject identity binding."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import secrets
from collections.abc import Awaitable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PortalIdentity
from db.tenant_context import disable_rls_bypass, enable_rls_bypass
from recognition.domain.portal_contracts import PortalIdentityStatus

_DEFAULT_DB_TIMEOUT_S = 5.0
_CLAIM_REFUSAL_MESSAGE = "portal identity claim was refused"
logger = logging.getLogger(__name__)


class PortalIdentityClaimRefused(ValueError):  # noqa: N818 - domain refusal names the rejected operation
    """The portal identity claim was refused without disclosing the reason."""


async def _with_timeout[T](operation: Awaitable[T], timeout_s: float) -> T:
    """Bound one request-scoped database operation."""
    return await asyncio.wait_for(operation, timeout=timeout_s)


def _validate_identity_part(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    if not isinstance(email, str):
        raise ValueError("email must be a string or None")
    cleaned = email.strip().lower()
    return cleaned or None


def _hash_invitation_token(invitation_token: str) -> str:
    return hashlib.sha256(invitation_token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _invitation_model():
    from db.models import PortalTenantInvitation

    return PortalTenantInvitation


class SqlAlchemyPortalIdentityRepository:
    """Store and resolve portal identities with an injected async session."""

    def __init__(self, session: AsyncSession, *, timeout_s: float = _DEFAULT_DB_TIMEOUT_S) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._session = session
        self._timeout_s = timeout_s

    @property
    def session(self) -> AsyncSession:
        return self._session

    @contextlib.asynccontextmanager
    async def _pre_auth_rls_bypass(self):
        # WHY: issuer/subject resolution and invitation redemption establish the tenant,
        # so FORCE RLS cannot require a tenant context before either operation runs.
        try:
            await _with_timeout(enable_rls_bypass(self._session), self._timeout_s)
            yield
        except BaseException:
            try:
                await _with_timeout(disable_rls_bypass(self._session), self._timeout_s)
            except Exception:  # noqa: BLE001 - preserve the original lookup/claim failure
                logger.warning("portal identity RLS context reset failed")
            raise
        else:
            await _with_timeout(disable_rls_bypass(self._session), self._timeout_s)

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
        async with self._pre_auth_rls_bypass():
            result = await _with_timeout(self._session.execute(stmt), self._timeout_s)
        return result.scalar_one_or_none()

    async def claim(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        invitation_token: str,
    ) -> PortalIdentity:
        """Redeem one hashed invitation and insert its tenant-bound identity atomically."""
        _validate_identity_part("issuer", issuer)
        _validate_identity_part("subject", subject)
        if not isinstance(invitation_token, str) or not invitation_token.strip():
            raise PortalIdentityClaimRefused(_CLAIM_REFUSAL_MESSAGE)
        normalized_email = _normalize_email(email)
        token_hash = _hash_invitation_token(invitation_token)
        invitation_model = _invitation_model()
        now = datetime.now(UTC)

        async with self._pre_auth_rls_bypass():
            statement = select(invitation_model).where(invitation_model.token_hash == token_hash).limit(1)
            result = await _with_timeout(self._session.execute(statement), self._timeout_s)
            invitation = result.scalar_one_or_none()
            if invitation is None:
                raise PortalIdentityClaimRefused(_CLAIM_REFUSAL_MESSAGE)

            stored_hash = str(getattr(invitation, "token_hash", ""))
            if not secrets.compare_digest(
                stored_hash.encode("ascii", errors="ignore"),
                token_hash.encode("ascii"),
            ):
                raise PortalIdentityClaimRefused(_CLAIM_REFUSAL_MESSAGE)
            if getattr(invitation, "accepted_at", None) is not None:
                raise PortalIdentityClaimRefused(_CLAIM_REFUSAL_MESSAGE)
            try:
                expires_at = _as_utc(invitation.expires_at)
            except (AttributeError, TypeError, ValueError):
                raise PortalIdentityClaimRefused(_CLAIM_REFUSAL_MESSAGE) from None
            if expires_at <= now or normalized_email is None:
                raise PortalIdentityClaimRefused(_CLAIM_REFUSAL_MESSAGE)
            try:
                invited_email = _normalize_email(getattr(invitation, "invited_email", None))
            except ValueError:
                raise PortalIdentityClaimRefused(_CLAIM_REFUSAL_MESSAGE) from None
            if invited_email != normalized_email:
                raise PortalIdentityClaimRefused(_CLAIM_REFUSAL_MESSAGE)
            try:
                tenant_id = invitation.tenant_id if isinstance(invitation.tenant_id, UUID) else UUID(str(invitation.tenant_id))
            except (AttributeError, TypeError, ValueError):
                raise PortalIdentityClaimRefused(_CLAIM_REFUSAL_MESSAGE) from None

            identity = PortalIdentity(
                id=uuid4(),
                tenant_id=tenant_id,
                issuer=issuer,
                subject=subject,
                email=normalized_email,
                status=PortalIdentityStatus.ACTIVE,
            )
            self._session.add(identity)
            try:
                await _with_timeout(self._session.flush(), self._timeout_s)
            except IntegrityError as exc:
                await self._rollback_after_failure()
                raise PortalIdentityClaimRefused(_CLAIM_REFUSAL_MESSAGE) from exc
            except Exception:
                await self._rollback_after_failure()
                raise

            accepted_at = datetime.now(UTC)
            acceptance = (
                update(invitation_model)
                .where(
                    invitation_model.id == invitation.id,
                    invitation_model.token_hash == token_hash,
                    invitation_model.accepted_at.is_(None),
                    invitation_model.expires_at > accepted_at,
                    invitation_model.invited_email == normalized_email,
                )
                .values(
                    accepted_at=accepted_at,
                    accepted_by_identity_id=identity.id,
                )
            )
            try:
                update_result = await _with_timeout(self._session.execute(acceptance), self._timeout_s)
            except Exception:
                await self._rollback_after_failure()
                raise
            if getattr(update_result, "rowcount", 0) != 1:
                await self._rollback_after_failure()
                raise PortalIdentityClaimRefused(_CLAIM_REFUSAL_MESSAGE)

            invitation.accepted_at = accepted_at
            invitation.accepted_by_identity_id = identity.id
            return identity

    async def _rollback_after_failure(self) -> None:
        try:
            await _with_timeout(self._session.rollback(), self._timeout_s)
        except Exception:  # noqa: BLE001 - never replace the original database failure
            logger.warning("portal identity rollback failed; preserving the original error")


__all__ = [
    "PortalIdentityClaimRefused",
    "SqlAlchemyPortalIdentityRepository",
]
