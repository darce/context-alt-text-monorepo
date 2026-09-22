"""C0 orphan, ambiguous-checkout, and audited-retry helpers for the R1 worker."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from recognition.domain.portal_contracts import (
    RECONCILIATION_DEFAULT_LEASE_SECONDS,
    RECONCILIATION_MAX_PAGES_PER_RUN,
    RECONCILIATION_PAGE_LIMIT,
    BillingState,
    EnumerationObservation,
    EnumerationObservationReason,
    EnumerationPage,
    ReconciliationCursorKey,
    ReconciliationKind,
    ReconciliationLease,
    ReconciliationLeaseConflictError,
)

_N1_METHODS = (
    "list_known_projections",
    "claim_reconcile_item",
    "lock_reconcile_item",
    "finish_reconcile_item",
)


class UnsupportedRepositoryError(RuntimeError):
    """Raised when the billing repository cannot fence known inbox/projection work."""


class _LocalWorkLease:
    __slots__ = (
        "provider",
        "environment",
        "seller_account",
        "kind",
        "remote_id",
        "owner",
        "fence",
        "lease_until",
    )

    def __init__(
        self,
        *,
        provider: str,
        environment: str,
        seller_account: str,
        kind: str,
        remote_id: str,
        owner: str,
        fence: int,
        lease_until: datetime,
    ) -> None:
        self.provider = provider
        self.environment = environment
        self.seller_account = seller_account
        self.kind = kind
        self.remote_id = remote_id
        self.owner = owner
        self.fence = fence
        self.lease_until = lease_until


def work_lease_type() -> type:
    try:
        from recognition.domain.billing_work_lease import BillingWorkLease

        return BillingWorkLease
    except ImportError:
        return _LocalWorkLease


def repository_supports_n1(repository: object) -> bool:
    return all(callable(getattr(repository, name, None)) for name in _N1_METHODS)


def require_n1_repository(repository: object) -> None:
    missing = [name for name in _N1_METHODS if not callable(getattr(repository, name, None))]
    if missing:
        raise UnsupportedRepositoryError(
            "billing repository is missing fenced N1 methods "
            f"{missing}; refusing unfenced reconciliation"
        )


def provider_code(provider: object) -> str:
    explicit = getattr(provider, "provider_name", None) or getattr(provider, "provider", None)
    if explicit in {"polar", "fake"}:
        return explicit
    name = type(provider).__name__.lower()
    if "polar" in name:
        return "polar"
    return "fake"


def configured_namespace(
    provider: object,
    *,
    environment: str | None = None,
    seller_account: str | None = None,
) -> tuple[str, str]:
    resolved_environment = environment or _read_environment(provider)
    resolved_seller = seller_account or _read_seller_account(provider)
    if resolved_environment not in {"sandbox", "live"}:
        raise ValueError("provider environment must be sandbox or live")
    if not isinstance(resolved_seller, str) or not resolved_seller.strip():
        raise ValueError("provider seller_account is required")
    return resolved_environment, resolved_seller.strip()


def cursor_key(
    provider: object,
    kind: ReconciliationKind,
    *,
    environment: str | None = None,
    seller_account: str | None = None,
) -> ReconciliationCursorKey:
    env, seller = configured_namespace(provider, environment=environment, seller_account=seller_account)
    return ReconciliationCursorKey(
        provider=provider_code(provider),
        environment=env,
        seller_account=seller,
        kind=kind,
    )


def lease_ttl() -> timedelta:
    return timedelta(seconds=RECONCILIATION_DEFAULT_LEASE_SECONDS)


def reconcile_event_id(remote_id: str, event_position: datetime) -> str:
    return f"reconcile:{remote_id}:{event_position.isoformat()}"


def remote_id_from_state(state: BillingState) -> str:
    if isinstance(state.provider_subscription_id, str) and state.provider_subscription_id:
        return state.provider_subscription_id
    if isinstance(state.provider_customer_id, str) and state.provider_customer_id:
        return state.provider_customer_id
    raise ValueError("enumerated item is missing a remote id")


async def maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def _read_environment(provider: object) -> str | None:
    value = getattr(provider, "environment", None)
    return value() if callable(value) else value


def _read_seller_account(provider: object) -> str | None:
    value = getattr(provider, "seller_account", None)
    if value is None:
        value = getattr(provider, "_seller_account", None)
    return value() if callable(value) else value


def projection_in_namespace(projection: object | None, environment: str, seller_account: str) -> bool:
    if projection is None:
        return False
    stored_env = _object_value(projection, "environment")
    stored_seller = _object_value(projection, "seller_account")
    return stored_env == environment and stored_seller == seller_account


def projection_is_legacy_null(projection: object | None) -> bool:
    if projection is None:
        return False
    return _object_value(projection, "environment") is None or _object_value(projection, "seller_account") is None


def _object_value(value: object, name: str) -> object | None:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def checkout_is_paid_status(status: object) -> bool:
    if not isinstance(status, str):
        return False
    return status.lower() in {"confirmed", "succeeded", "complete", "paid"}


def checkout_subscription_id(payload: Mapping[str, object]) -> str | None:
    nested = payload.get("subscription")
    for value in (
        payload.get("subscription_id"),
        payload.get("provider_subscription_id"),
        nested.get("id") if isinstance(nested, Mapping) else None,
    ):
        if isinstance(value, str) and value:
            return value
    return None


def checkout_customer_id(payload: Mapping[str, object]) -> str | None:
    nested = payload.get("customer")
    for value in (
        payload.get("customer_id"),
        payload.get("provider_customer_id"),
        nested.get("id") if isinstance(nested, Mapping) else None,
    ):
        if isinstance(value, str) and value:
            return value
    return None


__all__ = [
    "RECONCILIATION_MAX_PAGES_PER_RUN",
    "RECONCILIATION_PAGE_LIMIT",
    "UnsupportedRepositoryError",
    "checkout_customer_id",
    "checkout_is_paid_status",
    "checkout_subscription_id",
    "configured_namespace",
    "cursor_key",
    "lease_ttl",
    "maybe_await",
    "projection_in_namespace",
    "projection_is_legacy_null",
    "provider_code",
    "reconcile_event_id",
    "remote_id_from_state",
    "repository_supports_n1",
    "require_n1_repository",
    "work_lease_type",
    "EnumerationObservation",
    "EnumerationPage",
    "ReconciliationKind",
    "ReconciliationLease",
    "ReconciliationLeaseConflictError",
]
