"""Tenant-scoped persistence for durable billing checkout attempts.

Intent is committed locally before any provider call. This repository never
talks to Polar or another vendor; callers own the transaction boundary and
the network hop.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.portal_billing import (
    CHECKOUT_ATTEMPT_ACTIVE_STATUSES,
    BillingCheckoutAttempt,
    CheckoutAttemptErrorClass,
    CheckoutAttemptStatus,
)
from db.tenant_context import clear_tenant_context, set_tenant_context
from recognition.shared.db.dialect import is_sqlite

_ACTIVE_STATUS_VALUES = frozenset(status.value for status in CHECKOUT_ATTEMPT_ACTIVE_STATUSES)
_TERMINAL_STATUSES = frozenset(
    {
        CheckoutAttemptStatus.SUCCEEDED,
        CheckoutAttemptStatus.EXPIRED,
        CheckoutAttemptStatus.CANCELED,
        CheckoutAttemptStatus.FAILED,
    }
)
_ALLOWED_ENVIRONMENTS = frozenset({"sandbox", "live"})
_ALLOWED_PROVIDERS = frozenset({"polar", "fake"})


class CheckoutAttemptConflictError(Exception):
    """A checkout attempt write conflicted with durable tenant state."""


class CheckoutAttemptFingerprintConflictError(CheckoutAttemptConflictError):
    """The client idempotency key was reused with a different fingerprint."""


class CheckoutAttemptActiveConflictError(CheckoutAttemptConflictError):
    """The tenant already has an open attempt for this seller namespace and plan."""


class CheckoutAttemptProviderKeyReuseError(CheckoutAttemptConflictError):
    """A terminal purchase tried to reuse a provider idempotency key."""


class CheckoutAttemptNotFoundError(LookupError):
    """The tenant-scoped attempt row is not visible."""


@dataclass(frozen=True, slots=True)
class BeginCheckoutAttemptResult:
    attempt: BillingCheckoutAttempt
    replayed: bool


class CheckoutAttemptRepository:
    """Persist one durable checkout attempt without calling a billing provider."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def begin_attempt(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        environment: str,
        seller_account: str,
        plan_code: str,
        idempotency_key: str,
        client_idempotency_key: str,
        request_fingerprint: str,
    ) -> BeginCheckoutAttemptResult:
        """Insert ``created`` or replay the same tenant/key+fingerprint row."""
        _validate_uuid("tenant_id", tenant_id)
        normalized_provider = _validate_provider(provider)
        normalized_environment = _validate_environment(environment)
        normalized_seller = _validate_non_empty("seller_account", seller_account)
        normalized_plan = _validate_non_empty("plan_code", plan_code)
        normalized_provider_key = _validate_non_empty("idempotency_key", idempotency_key)
        normalized_client_key = _validate_non_empty("client_idempotency_key", client_idempotency_key)
        normalized_fingerprint = _validate_non_empty("request_fingerprint", request_fingerprint)

        async with self._tenant_context(tenant_id):
            existing = await self._get_by_client_key(
                tenant_id=tenant_id,
                provider=normalized_provider,
                environment=normalized_environment,
                seller_account=normalized_seller,
                client_idempotency_key=normalized_client_key,
            )
            if existing is not None:
                return _replay_or_conflict(existing, normalized_fingerprint)

            row = BillingCheckoutAttempt(
                tenant_id=tenant_id,
                provider=normalized_provider,
                environment=normalized_environment,
                seller_account=normalized_seller,
                plan_code=normalized_plan,
                idempotency_key=normalized_provider_key,
                client_idempotency_key=normalized_client_key,
                request_fingerprint=normalized_fingerprint,
                status=CheckoutAttemptStatus.CREATED.value,
                last_error_class=CheckoutAttemptErrorClass.NONE.value,
            )
            try:
                async with self._session.begin_nested():
                    self._session.add(row)
                    await self._session.flush()
            except IntegrityError:
                raced = await self._get_by_client_key(
                    tenant_id=tenant_id,
                    provider=normalized_provider,
                    environment=normalized_environment,
                    seller_account=normalized_seller,
                    client_idempotency_key=normalized_client_key,
                )
                if raced is not None:
                    return _replay_or_conflict(raced, normalized_fingerprint)
                active = await self._get_active(
                    tenant_id=tenant_id,
                    provider=normalized_provider,
                    environment=normalized_environment,
                    seller_account=normalized_seller,
                    plan_code=normalized_plan,
                )
                if active is not None:
                    raise CheckoutAttemptActiveConflictError(
                        "an open checkout attempt already exists for this tenant, seller, and plan"
                    ) from None
                provider_hit = await self._get_by_provider_key(
                    tenant_id=tenant_id,
                    provider=normalized_provider,
                    environment=normalized_environment,
                    seller_account=normalized_seller,
                    idempotency_key=normalized_provider_key,
                )
                if provider_hit is not None:
                    raise CheckoutAttemptProviderKeyReuseError(
                        "expired or canceled attempts must mint a new provider idempotency key"
                    ) from None
                raise
            return BeginCheckoutAttemptResult(attempt=row, replayed=False)

    async def get_attempt(self, tenant_id: UUID, attempt_id: UUID) -> BillingCheckoutAttempt | None:
        _validate_uuid("tenant_id", tenant_id)
        _validate_uuid("attempt_id", attempt_id)
        statement = (
            select(BillingCheckoutAttempt)
            .where(
                BillingCheckoutAttempt.tenant_id == tenant_id,
                BillingCheckoutAttempt.id == attempt_id,
            )
            .limit(1)
        )
        async with self._tenant_context(tenant_id):
            result = await self._session.execute(statement)
            return result.scalar_one_or_none()

    async def get_by_client_idempotency_key(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        environment: str,
        seller_account: str,
        client_idempotency_key: str,
    ) -> BillingCheckoutAttempt | None:
        _validate_uuid("tenant_id", tenant_id)
        async with self._tenant_context(tenant_id):
            return await self._get_by_client_key(
                tenant_id=tenant_id,
                provider=_validate_provider(provider),
                environment=_validate_environment(environment),
                seller_account=_validate_non_empty("seller_account", seller_account),
                client_idempotency_key=_validate_non_empty("client_idempotency_key", client_idempotency_key),
            )

    async def mark_provider_requested(self, tenant_id: UUID, attempt_id: UUID) -> BillingCheckoutAttempt:
        return await self._update_attempt(
            tenant_id,
            attempt_id,
            status=CheckoutAttemptStatus.PROVIDER_REQUESTED,
            last_error_class=CheckoutAttemptErrorClass.NONE,
        )

    async def record_provider_checkout(
        self,
        tenant_id: UUID,
        attempt_id: UUID,
        *,
        provider_checkout_id: str,
        checkout_url: str,
    ) -> BillingCheckoutAttempt:
        return await self._update_attempt(
            tenant_id,
            attempt_id,
            status=CheckoutAttemptStatus.PENDING,
            last_error_class=CheckoutAttemptErrorClass.NONE,
            provider_checkout_id=_validate_non_empty("provider_checkout_id", provider_checkout_id),
            checkout_url=_validate_non_empty("checkout_url", checkout_url),
        )

    async def mark_ambiguous(self, tenant_id: UUID, attempt_id: UUID) -> BillingCheckoutAttempt:
        return await self._update_attempt(
            tenant_id,
            attempt_id,
            status=CheckoutAttemptStatus.AMBIGUOUS,
            last_error_class=CheckoutAttemptErrorClass.AMBIGUOUS,
        )

    async def mark_terminal(
        self,
        tenant_id: UUID,
        attempt_id: UUID,
        *,
        status: CheckoutAttemptStatus | str,
        last_error_class: CheckoutAttemptErrorClass | str | None = None,
    ) -> BillingCheckoutAttempt:
        normalized_status = _coerce_status(status)
        if normalized_status not in _TERMINAL_STATUSES:
            raise ValueError("mark_terminal requires a terminal checkout attempt status")
        normalized_error = (
            CheckoutAttemptErrorClass.NONE if last_error_class is None else _coerce_error_class(last_error_class)
        )
        return await self._update_attempt(
            tenant_id,
            attempt_id,
            status=normalized_status,
            last_error_class=normalized_error,
        )

    async def _update_attempt(
        self,
        tenant_id: UUID,
        attempt_id: UUID,
        *,
        status: CheckoutAttemptStatus,
        last_error_class: CheckoutAttemptErrorClass,
        provider_checkout_id: str | None = None,
        checkout_url: str | None = None,
    ) -> BillingCheckoutAttempt:
        _validate_uuid("tenant_id", tenant_id)
        _validate_uuid("attempt_id", attempt_id)
        async with self._tenant_context(tenant_id):
            row = await self._get_by_id(tenant_id, attempt_id)
            if row is None:
                raise CheckoutAttemptNotFoundError("checkout attempt was not found for this tenant")
            row.status = status.value
            row.last_error_class = last_error_class.value
            if provider_checkout_id is not None:
                row.provider_checkout_id = provider_checkout_id
            if checkout_url is not None:
                row.checkout_url = checkout_url
            await self._session.flush()
            return row

    async def _get_by_id(self, tenant_id: UUID, attempt_id: UUID) -> BillingCheckoutAttempt | None:
        statement = (
            select(BillingCheckoutAttempt)
            .where(
                BillingCheckoutAttempt.tenant_id == tenant_id,
                BillingCheckoutAttempt.id == attempt_id,
            )
            .limit(1)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def _get_by_client_key(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        environment: str,
        seller_account: str,
        client_idempotency_key: str,
    ) -> BillingCheckoutAttempt | None:
        statement = (
            select(BillingCheckoutAttempt)
            .where(
                BillingCheckoutAttempt.tenant_id == tenant_id,
                BillingCheckoutAttempt.provider == provider,
                BillingCheckoutAttempt.environment == environment,
                BillingCheckoutAttempt.seller_account == seller_account,
                BillingCheckoutAttempt.client_idempotency_key == client_idempotency_key,
            )
            .limit(1)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def _get_by_provider_key(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        environment: str,
        seller_account: str,
        idempotency_key: str,
    ) -> BillingCheckoutAttempt | None:
        statement = (
            select(BillingCheckoutAttempt)
            .where(
                BillingCheckoutAttempt.tenant_id == tenant_id,
                BillingCheckoutAttempt.provider == provider,
                BillingCheckoutAttempt.environment == environment,
                BillingCheckoutAttempt.seller_account == seller_account,
                BillingCheckoutAttempt.idempotency_key == idempotency_key,
            )
            .limit(1)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def _get_active(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        environment: str,
        seller_account: str,
        plan_code: str,
    ) -> BillingCheckoutAttempt | None:
        statement = (
            select(BillingCheckoutAttempt)
            .where(
                BillingCheckoutAttempt.tenant_id == tenant_id,
                BillingCheckoutAttempt.provider == provider,
                BillingCheckoutAttempt.environment == environment,
                BillingCheckoutAttempt.seller_account == seller_account,
                BillingCheckoutAttempt.plan_code == plan_code,
                BillingCheckoutAttempt.status.in_(_ACTIVE_STATUS_VALUES),
            )
            .limit(1)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    @contextlib.asynccontextmanager
    async def _tenant_context(self, tenant_id: UUID) -> AsyncIterator[None]:
        if _is_sqlite_session(self._session):
            yield
            return
        try:
            await set_tenant_context(self._session, tenant_id)
            yield
        finally:
            await clear_tenant_context(self._session)


SqlAlchemyCheckoutAttemptRepository = CheckoutAttemptRepository


def _replay_or_conflict(
    existing: BillingCheckoutAttempt,
    request_fingerprint: str,
) -> BeginCheckoutAttemptResult:
    if existing.request_fingerprint != request_fingerprint:
        raise CheckoutAttemptFingerprintConflictError(
            "idempotency key was already used for a different checkout request"
        )
    return BeginCheckoutAttemptResult(attempt=existing, replayed=True)


def _validate_non_empty(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validate_uuid(name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{name} must be a UUID")


def _validate_environment(value: object) -> str:
    environment = _validate_non_empty("environment", value)
    if environment not in _ALLOWED_ENVIRONMENTS:
        raise ValueError("environment must be sandbox or live")
    return environment


def _validate_provider(value: object) -> str:
    provider = _validate_non_empty("provider", value)
    if provider not in _ALLOWED_PROVIDERS:
        raise ValueError("provider must be polar or fake")
    return provider


def _coerce_status(value: CheckoutAttemptStatus | str) -> CheckoutAttemptStatus:
    if isinstance(value, CheckoutAttemptStatus):
        return value
    try:
        return CheckoutAttemptStatus(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid checkout attempt status") from exc


def _coerce_error_class(value: CheckoutAttemptErrorClass | str) -> CheckoutAttemptErrorClass:
    if isinstance(value, CheckoutAttemptErrorClass):
        return value
    try:
        return CheckoutAttemptErrorClass(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid checkout attempt error class") from exc


def _is_sqlite_session(session: AsyncSession) -> bool:
    if is_sqlite(session):
        return True
    wrapped = getattr(session, "_session", None)
    return wrapped is not None and is_sqlite(wrapped)


__all__ = [
    "BeginCheckoutAttemptResult",
    "CheckoutAttemptActiveConflictError",
    "CheckoutAttemptConflictError",
    "CheckoutAttemptFingerprintConflictError",
    "CheckoutAttemptNotFoundError",
    "CheckoutAttemptProviderKeyReuseError",
    "CheckoutAttemptRepository",
    "SqlAlchemyCheckoutAttemptRepository",
]
