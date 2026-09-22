"""Persistence for the portal's verified issuer/subject identity binding."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import secrets
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PortalIdentity, Tenant
from db.tenant_context import disable_rls_bypass, enable_rls_bypass
from recognition.domain.portal_contracts import PortalIdentityStatus

_DEFAULT_DB_TIMEOUT_S = 5.0
_CLAIM_REFUSAL_MESSAGE = "portal identity claim was refused"
logger = logging.getLogger(__name__)


class PortalIdentityClaimRefused(ValueError):  # noqa: N818 - domain refusal names the rejected operation
    """The portal identity claim was refused without disclosing the reason."""


class PortalIdentityClaimError(PortalIdentityClaimRefused):
    """A typed claim refusal that keeps the public message opaque."""

    def __init__(self, code: str) -> None:
        super().__init__(_CLAIM_REFUSAL_MESSAGE)
        self.code = code


@dataclass(frozen=True, slots=True)
class PortalIdentityClaimRecord:
    """Durable invitation redemption result produced inside the claim transaction."""

    identity: PortalIdentity
    replayed: bool


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


def _as_uuid(value: object, *, code: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        raise PortalIdentityClaimError(code) from None


def _optional_uuid(value: object, *, code: str) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _as_uuid(value, code=code)


def _claim_site_url(tenant_id: UUID) -> str:
    return f"https://portal.invalid/tenants/{tenant_id}"


def _canonical_email_clause(invitation_model: type, normalized_email: str):
    return func.lower(func.trim(invitation_model.invited_email)) == normalized_email


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
                tenant_id = (
                    invitation.tenant_id if isinstance(invitation.tenant_id, UUID) else UUID(str(invitation.tenant_id))
                )
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
                    _canonical_email_clause(invitation_model, normalized_email),
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

    async def claim_onboarding(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        invitation_token: str,
    ) -> PortalIdentityClaimRecord:
        """Redeem or replay one invitation under a locked invitation row."""
        _validate_identity_part("issuer", issuer)
        _validate_identity_part("subject", subject)
        if not isinstance(invitation_token, str) or not invitation_token.strip():
            raise PortalIdentityClaimError("invalid_claim_request")
        normalized_email = _normalize_email(email)
        token_hash = _hash_invitation_token(invitation_token)
        invitation_model = _invitation_model()
        now = datetime.now(UTC)

        async with self._pre_auth_rls_bypass():
            invitation = await self._lock_invitation(invitation_model, token_hash)
            if invitation is None:
                raise PortalIdentityClaimError("not_admitted")
            stored_hash = str(getattr(invitation, "token_hash", ""))
            if not secrets.compare_digest(
                stored_hash.encode("ascii", errors="ignore"),
                token_hash.encode("ascii"),
            ):
                raise PortalIdentityClaimError("not_admitted")
            try:
                expires_at = _as_utc(invitation.expires_at)
            except (AttributeError, TypeError, ValueError):
                raise PortalIdentityClaimError("not_admitted") from None
            if expires_at <= now or normalized_email is None:
                raise PortalIdentityClaimError("not_admitted")
            try:
                invited_email = _normalize_email(getattr(invitation, "invited_email", None))
            except ValueError:
                raise PortalIdentityClaimError("not_admitted") from None
            if invited_email != normalized_email:
                raise PortalIdentityClaimError("not_admitted")
            invitation_tenant_id = _optional_uuid(getattr(invitation, "tenant_id", None), code="not_admitted")
            claimant = await self._lock_identity_by_issuer_subject(issuer, subject)
            if claimant is not None and claimant.issuer == issuer and claimant.subject == subject:
                claimant_tenant = _as_uuid(claimant.tenant_id, code="identity_already_bound")
                if invitation_tenant_id is not None and invitation_tenant_id != claimant_tenant:
                    raise PortalIdentityClaimError("identity_already_bound")
                if getattr(invitation, "accepted_at", None) is not None:
                    return await self._replay_accepted_invitation(
                        invitation,
                        issuer=issuer,
                        subject=subject,
                        tenant_id=claimant_tenant,
                        claimant=claimant,
                    )
                return await self._accept_current_for_identity(
                    invitation_model,
                    invitation,
                    token_hash=token_hash,
                    normalized_email=normalized_email,
                    identity=claimant,
                    tenant_id=claimant_tenant,
                )

            if getattr(invitation, "accepted_at", None) is not None:
                if invitation_tenant_id is None:
                    raise PortalIdentityClaimError("invitation_consumed")
                return await self._replay_accepted_invitation(
                    invitation,
                    issuer=issuer,
                    subject=subject,
                    tenant_id=invitation_tenant_id,
                    claimant=claimant,
                )

            tenant_id = invitation_tenant_id
            identity: PortalIdentity | None = None
            try:
                begin_nested = getattr(self._session, "begin_nested", None)
                if callable(begin_nested):
                    async with begin_nested():
                        tenant_id, identity = await self._insert_claim_identity(
                            tenant_id=tenant_id,
                            issuer=issuer,
                            subject=subject,
                            email=normalized_email,
                        )
                else:
                    tenant_id, identity = await self._insert_claim_identity(
                        tenant_id=tenant_id,
                        issuer=issuer,
                        subject=subject,
                        email=normalized_email,
                    )
            except IntegrityError:
                raced = await self._lock_identity_by_issuer_subject(issuer, subject)
                if raced is not None and raced.issuer == issuer and raced.subject == subject:
                    raced_tenant = _as_uuid(raced.tenant_id, code="identity_already_bound")
                    if invitation_tenant_id is not None and invitation_tenant_id != raced_tenant:
                        raise PortalIdentityClaimError("identity_already_bound") from None
                    return await self._accept_current_for_identity(
                        invitation_model,
                        invitation,
                        token_hash=token_hash,
                        normalized_email=normalized_email,
                        identity=raced,
                        tenant_id=raced_tenant,
                    )
                if invitation_tenant_id is not None:
                    tenant_owner = await self._lock_identity_by_tenant(invitation_tenant_id)
                    if tenant_owner is not None:
                        if tenant_owner.issuer == issuer and tenant_owner.subject == subject:
                            return await self._accept_current_for_identity(
                                invitation_model,
                                invitation,
                                token_hash=token_hash,
                                normalized_email=normalized_email,
                                identity=tenant_owner,
                                tenant_id=invitation_tenant_id,
                            )
                        raise PortalIdentityClaimError("invitation_consumed") from None
                raise PortalIdentityClaimError("not_admitted") from None
            except Exception:
                await self._rollback_after_failure()
                raise

            if identity is None or tenant_id is None:
                await self._rollback_after_failure()
                raise PortalIdentityClaimError("not_admitted")
            accepted_at = await self._accept_invitation(
                invitation_model,
                invitation,
                token_hash=token_hash,
                normalized_email=normalized_email,
                identity_id=identity.id,
                tenant_id=tenant_id,
            )
            if accepted_at is None:
                await self._rollback_after_failure()
                raise PortalIdentityClaimError("invitation_consumed")
            invitation.accepted_at = accepted_at
            invitation.accepted_by_identity_id = identity.id
            invitation.tenant_id = tenant_id
            return PortalIdentityClaimRecord(identity=identity, replayed=False)

    async def _insert_claim_identity(
        self,
        *,
        tenant_id: UUID | None,
        issuer: str,
        subject: str,
        email: str,
    ) -> tuple[UUID, PortalIdentity]:
        if tenant_id is None:
            tenant_id = uuid4()
            self._session.add(Tenant(id=tenant_id, site_url=_claim_site_url(tenant_id)))
        identity = PortalIdentity(
            id=uuid4(),
            tenant_id=tenant_id,
            issuer=issuer,
            subject=subject,
            email=email,
            status=PortalIdentityStatus.ACTIVE,
        )
        self._session.add(identity)
        await _with_timeout(self._session.flush(), self._timeout_s)
        return tenant_id, identity

    async def _accept_current_for_identity(
        self,
        invitation_model: type,
        invitation: object,
        *,
        token_hash: str,
        normalized_email: str,
        identity: PortalIdentity,
        tenant_id: UUID,
    ) -> PortalIdentityClaimRecord:
        accepted_at = await self._accept_invitation(
            invitation_model,
            invitation,
            token_hash=token_hash,
            normalized_email=normalized_email,
            identity_id=identity.id,
            tenant_id=tenant_id,
        )
        if accepted_at is None:
            return await self._replay_accepted_invitation(
                invitation,
                issuer=identity.issuer,
                subject=identity.subject,
                tenant_id=tenant_id,
                claimant=identity,
            )
        invitation.accepted_at = accepted_at
        invitation.accepted_by_identity_id = identity.id
        invitation.tenant_id = tenant_id
        return PortalIdentityClaimRecord(identity=identity, replayed=True)

    async def _lock_invitation(self, invitation_model: type, token_hash: str) -> object | None:
        statement = select(invitation_model).where(invitation_model.token_hash == token_hash).limit(1).with_for_update()
        result = await _with_timeout(self._session.execute(statement), self._timeout_s)
        return result.scalar_one_or_none()

    async def _lock_identity_by_issuer_subject(self, issuer: str, subject: str) -> PortalIdentity | None:
        statement = (
            select(PortalIdentity)
            .where(PortalIdentity.issuer == issuer, PortalIdentity.subject == subject)
            .limit(1)
            .with_for_update()
        )
        result = await _with_timeout(self._session.execute(statement), self._timeout_s)
        return result.scalar_one_or_none()

    async def _lock_identity_by_id(self, identity_id: object) -> PortalIdentity | None:
        statement = select(PortalIdentity).where(PortalIdentity.id == identity_id).limit(1).with_for_update()
        result = await _with_timeout(self._session.execute(statement), self._timeout_s)
        return result.scalar_one_or_none()

    async def _lock_identity_by_tenant(self, tenant_id: UUID) -> PortalIdentity | None:
        statement = select(PortalIdentity).where(PortalIdentity.tenant_id == tenant_id).limit(1).with_for_update()
        result = await _with_timeout(self._session.execute(statement), self._timeout_s)
        return result.scalar_one_or_none()

    async def _replay_accepted_invitation(
        self,
        invitation: object,
        *,
        issuer: str,
        subject: str,
        tenant_id: UUID,
        claimant: PortalIdentity | None,
    ) -> PortalIdentityClaimRecord:
        owner = claimant if claimant is not None and claimant.issuer == issuer and claimant.subject == subject else None
        if owner is None:
            accepted_id = getattr(invitation, "accepted_by_identity_id", None)
            if accepted_id is not None:
                owner = await self._lock_identity_by_id(accepted_id)
            if owner is None:
                owner = await self._lock_identity_by_tenant(tenant_id)
        if owner is None:
            raise PortalIdentityClaimError("invitation_consumed")
        owner_tenant = _as_uuid(owner.tenant_id, code="invitation_consumed")
        if owner.issuer == issuer and owner.subject == subject:
            if owner_tenant != tenant_id:
                raise PortalIdentityClaimError("identity_already_bound")
            return PortalIdentityClaimRecord(identity=owner, replayed=True)
        raise PortalIdentityClaimError("invitation_consumed")

    async def _accept_invitation(
        self,
        invitation_model: type,
        invitation: object,
        *,
        token_hash: str,
        normalized_email: str,
        identity_id: object,
        tenant_id: UUID,
    ) -> datetime | None:
        accepted_at = datetime.now(UTC)
        acceptance = (
            update(invitation_model)
            .where(
                invitation_model.id == invitation.id,
                invitation_model.token_hash == token_hash,
                invitation_model.accepted_at.is_(None),
                invitation_model.expires_at > accepted_at,
                _canonical_email_clause(invitation_model, normalized_email),
            )
            .values(
                accepted_at=accepted_at,
                accepted_by_identity_id=identity_id,
                tenant_id=tenant_id,
            )
        )
        try:
            update_result = await _with_timeout(self._session.execute(acceptance), self._timeout_s)
        except Exception:
            await self._rollback_after_failure()
            raise
        if getattr(update_result, "rowcount", 0) != 1:
            return None
        return accepted_at

    async def _rollback_after_failure(self) -> None:
        try:
            await _with_timeout(self._session.rollback(), self._timeout_s)
        except Exception:  # noqa: BLE001 - never replace the original database failure
            logger.warning("portal identity rollback failed; preserving the original error")


__all__ = [
    "PortalIdentityClaimError",
    "PortalIdentityClaimRecord",
    "PortalIdentityClaimRefused",
    "SqlAlchemyPortalIdentityRepository",
]
