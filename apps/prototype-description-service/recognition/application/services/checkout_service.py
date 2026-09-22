"""Durable checkout orchestration over a committed attempt row and typed provider.

Intent is persisted and committed before any vendor call (DDIA atomic intent;
Release It: no lock held across I/O). Ambiguous outcomes stay pending until
reconciliation; retries must not mint a second vendor mutation.
"""

from __future__ import annotations

import inspect
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn
from uuid import UUID

from db.models.portal_billing import (
    BillingCheckoutAttempt,
    CheckoutAttemptErrorClass,
    CheckoutAttemptStatus,
)
from recognition.domain.portal_contracts import BillingProvider, CheckoutSession
from recognition.infrastructure.billing.polar_provider import (
    CheckoutAmbiguityError,
    PaymentsDisabledError,
    PolarRequestError,
)
from recognition.infrastructure.repositories.checkout_attempt_repository import (
    BeginCheckoutAttemptResult,
    CheckoutAttemptActiveConflictError,
    CheckoutAttemptFingerprintConflictError,
    CheckoutAttemptRepository,
)

_ALLOWED_PROVIDERS = frozenset({"polar", "fake"})
_ALLOWED_ENVIRONMENTS = frozenset({"sandbox", "live"})
_RESUME_PROVIDER = frozenset({CheckoutAttemptStatus.CREATED})
_REFUSE_VENDOR = frozenset({CheckoutAttemptStatus.PROVIDER_REQUESTED, CheckoutAttemptStatus.AMBIGUOUS})
_REPLAY_STATUSES = frozenset(
    {
        CheckoutAttemptStatus.PENDING,
        CheckoutAttemptStatus.SUCCEEDED,
        CheckoutAttemptStatus.EXPIRED,
        CheckoutAttemptStatus.CANCELED,
        CheckoutAttemptStatus.FAILED,
    }
)


class CheckoutServiceError(Exception):
    """Base refusal from the checkout application service."""


class CheckoutPaymentsDisabledError(CheckoutServiceError):
    """Paid checkout is disabled; no attempt row or vendor call is allowed."""


class CheckoutAmbiguousError(CheckoutServiceError):
    """Vendor outcome is unknown; reconcile before creating another checkout."""

    def __init__(self, attempt_id: UUID) -> None:
        self.attempt_id = attempt_id
        super().__init__("checkout outcome is ambiguous; reconcile before a new vendor mutation")


class CheckoutConflictError(CheckoutServiceError):
    """The request conflicts with a durable tenant-scoped attempt."""


class CheckoutFingerprintConflictError(CheckoutConflictError):
    """The client idempotency key was reused with a different canonical fingerprint."""


class CheckoutActiveConflictError(CheckoutConflictError):
    """Another open attempt already exists for this tenant, seller, and plan."""


class InvalidCheckoutRequestError(ValueError):
    """The caller supplied an invalid checkout request."""


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    """Application result consumed by the later HTTP checkout lane."""

    attempt_id: UUID
    checkout_url: str | None
    status: CheckoutAttemptStatus
    replayed: bool


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidCheckoutRequestError(f"{name} must be a non-empty string")
    return value.strip()


def _require_uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise InvalidCheckoutRequestError(f"{name} must be a UUID")
    return value


def _status_of(value: str) -> CheckoutAttemptStatus:
    try:
        return CheckoutAttemptStatus(value)
    except ValueError as exc:
        raise InvalidCheckoutRequestError("checkout attempt status is invalid") from exc


def _is_rejected_provider_error(exc: BaseException) -> bool:
    # HTTP 200 missing id/url or a non-object body raises ValueError after Polar POST.
    if isinstance(exc, (CheckoutAmbiguityError, TimeoutError, ConnectionError, OSError, ValueError)):
        return False
    if isinstance(exc, PaymentsDisabledError):
        return True
    if isinstance(exc, PolarRequestError):
        return exc.status_code < 500
    return False


async def _await_maybe(result: object) -> None:
    if inspect.isawaitable(result):
        await result


class CheckoutService:
    """Persist a checkout attempt, then call the billing provider exactly once."""

    def __init__(
        self,
        repository: CheckoutAttemptRepository,
        provider: BillingProvider,
        *,
        payments_enabled: bool = False,
        provider_name: str = "fake",
        environment: str = "sandbox",
        seller_account: str,
        idempotency_key_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(payments_enabled, bool):
            raise InvalidCheckoutRequestError("payments_enabled must be a boolean")
        normalized_provider = _text("provider_name", provider_name)
        if normalized_provider not in _ALLOWED_PROVIDERS:
            raise InvalidCheckoutRequestError("provider_name must be polar or fake")
        normalized_environment = _text("environment", environment)
        if normalized_environment not in _ALLOWED_ENVIRONMENTS:
            raise InvalidCheckoutRequestError("environment must be sandbox or live")
        self._repository = repository
        self._provider = provider
        self._payments_enabled = payments_enabled
        self._provider_name = normalized_provider
        self._environment = normalized_environment
        self._seller_account = _text("seller_account", seller_account)
        self._idempotency_key_factory = idempotency_key_factory or (lambda: secrets.token_urlsafe(32))

    @staticmethod
    def fingerprint(
        *,
        tenant_id: UUID,
        plan_code: str,
        success_url: str,
        cancel_url: str,
        environment: str,
        seller_account: str,
    ) -> str:
        """Canonical JSON of tenant, plan, URLs, environment, and seller (spec §5.1)."""
        payload = {
            "cancel_url": cancel_url,
            "environment": environment,
            "plan_code": plan_code,
            "seller_account": seller_account,
            "success_url": success_url,
            "tenant_id": str(tenant_id),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    async def create_checkout(
        self,
        *,
        tenant_id: UUID,
        plan_code: str,
        success_url: str,
        cancel_url: str,
        client_idempotency_key: str,
    ) -> CheckoutResult:
        """Create or replay one tenant-scoped checkout without holding a DB lock on I/O."""
        self._require_payments_enabled()
        tenant_id = _require_uuid("tenant_id", tenant_id)
        plan_code = _text("plan_code", plan_code)
        success_url = _text("success_url", success_url)
        cancel_url = _text("cancel_url", cancel_url)
        client_key = _text("client_idempotency_key", client_idempotency_key)
        fingerprint = self.fingerprint(
            tenant_id=tenant_id,
            plan_code=plan_code,
            success_url=success_url,
            cancel_url=cancel_url,
            environment=self._environment,
            seller_account=self._seller_account,
        )
        begun = await self._begin_attempt(tenant_id, plan_code, client_key, fingerprint)
        await self._commit()
        if begun.replayed:
            return await self._resume_existing(begun.attempt, plan_code, success_url, cancel_url)
        return await self._request_provider(
            begun.attempt,
            plan_code=plan_code,
            success_url=success_url,
            cancel_url=cancel_url,
            replayed=False,
        )

    def _require_payments_enabled(self) -> None:
        if not self._payments_enabled:
            raise CheckoutPaymentsDisabledError("payments are disabled")

    async def _begin_attempt(
        self,
        tenant_id: UUID,
        plan_code: str,
        client_key: str,
        fingerprint: str,
    ) -> BeginCheckoutAttemptResult:
        try:
            return await self._repository.begin_attempt(
                tenant_id=tenant_id,
                provider=self._provider_name,
                environment=self._environment,
                seller_account=self._seller_account,
                plan_code=plan_code,
                idempotency_key=_text("idempotency_key", self._idempotency_key_factory()),
                client_idempotency_key=client_key,
                request_fingerprint=fingerprint,
            )
        except CheckoutAttemptFingerprintConflictError as exc:
            raise CheckoutFingerprintConflictError(
                "idempotency key was already used for a different checkout request"
            ) from exc
        except CheckoutAttemptActiveConflictError as exc:
            raise CheckoutActiveConflictError(
                "an open checkout attempt already exists for this tenant, seller, and plan"
            ) from exc

    async def _resume_existing(
        self,
        attempt: BillingCheckoutAttempt,
        plan_code: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        status = _status_of(attempt.status)
        if status in _RESUME_PROVIDER:
            return await self._request_provider(
                attempt,
                plan_code=plan_code,
                success_url=success_url,
                cancel_url=cancel_url,
                replayed=True,
            )
        if status in _REFUSE_VENDOR or (status is CheckoutAttemptStatus.PENDING and not attempt.checkout_url):
            raise CheckoutAmbiguousError(attempt.id)
        if status in _REPLAY_STATUSES:
            return _result_from(attempt, replayed=True)
        raise CheckoutAmbiguousError(attempt.id)

    async def _request_provider(
        self,
        attempt: BillingCheckoutAttempt,
        *,
        plan_code: str,
        success_url: str,
        cancel_url: str,
        replayed: bool,
    ) -> CheckoutResult:
        await self._repository.mark_provider_requested(attempt.tenant_id, attempt.id)
        await self._commit()
        try:
            session = await self._create_provider_session(
                tenant_id=attempt.tenant_id,
                plan_code=plan_code,
                success_url=success_url,
                cancel_url=cancel_url,
                idempotency_key=attempt.idempotency_key,
                attempt_id=attempt.id,
            )
        except Exception as exc:
            await self._record_provider_failure(attempt.tenant_id, attempt.id, exc)
        row = await self._repository.record_provider_checkout(
            attempt.tenant_id,
            attempt.id,
            provider_checkout_id=session.provider_checkout_id,
            checkout_url=session.url,
        )
        await self._commit()
        return _result_from(row, replayed=replayed)

    async def _create_provider_session(
        self,
        *,
        tenant_id: UUID,
        plan_code: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
        attempt_id: UUID,
    ) -> CheckoutSession:
        return await self._provider.create_checkout_session(
            tenant_id=tenant_id,
            plan_code=plan_code,
            success_url=success_url,
            cancel_url=cancel_url,
            idempotency_key=idempotency_key,
            attempt_id=attempt_id,
        )

    async def _record_provider_failure(self, tenant_id: UUID, attempt_id: UUID, exc: BaseException) -> NoReturn:
        if _is_rejected_provider_error(exc):
            await self._repository.mark_terminal(
                tenant_id,
                attempt_id,
                status=CheckoutAttemptStatus.FAILED,
                last_error_class=CheckoutAttemptErrorClass.REJECTED,
            )
            await self._commit()
            if isinstance(exc, PaymentsDisabledError):
                raise CheckoutPaymentsDisabledError("payments are disabled") from exc
            raise exc
        await self._repository.mark_ambiguous(tenant_id, attempt_id)
        await self._commit()
        raise CheckoutAmbiguousError(attempt_id) from exc

    async def _commit(self) -> None:
        await _await_maybe(self._repository.session.commit())


def _result_from(attempt: BillingCheckoutAttempt, *, replayed: bool) -> CheckoutResult:
    return CheckoutResult(
        attempt_id=attempt.id,
        checkout_url=attempt.checkout_url,
        status=_status_of(attempt.status),
        replayed=replayed,
    )


SqlAlchemyCheckoutService = CheckoutService

__all__ = [
    "CheckoutActiveConflictError",
    "CheckoutAmbiguousError",
    "CheckoutConflictError",
    "CheckoutFingerprintConflictError",
    "CheckoutPaymentsDisabledError",
    "CheckoutResult",
    "CheckoutService",
    "CheckoutServiceError",
    "InvalidCheckoutRequestError",
    "SqlAlchemyCheckoutService",
]
