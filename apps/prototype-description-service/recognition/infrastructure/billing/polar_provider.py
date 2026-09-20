"""Polar implementation of the portal billing provider boundary.

The module deliberately depends on an injected asynchronous HTTP client.  It does
not import Polar's SDK or create network clients: the application owns client
lifecycle, authentication, and transport policy.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Protocol, cast
from urllib.parse import quote, urlsplit
from uuid import UUID

from recognition.domain.portal_contracts import BillingState, BillingSubscriptionStatus


class AsyncHttpClient(Protocol):
    """Small HTTP surface needed by the adapter and easy to replace in tests."""

    async def post(
        self,
        url: str,
        *,
        json: Mapping[str, object],
        headers: Mapping[str, str],
        request_timeout: float,
    ) -> object:
        """Send one bounded POST request."""

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        request_timeout: float,
    ) -> object:
        """Send one bounded GET request."""


class PaymentsDisabledError(RuntimeError):
    """Raised when an operator has not enabled paid billing operations."""


class CheckoutAmbiguityError(RuntimeError):
    """Raised when checkout creation may have succeeded remotely."""


class PolarRequestError(RuntimeError):
    """Raised for a provider response that cannot be used as a state result."""

    def __init__(self, status_code: int, operation: str) -> None:
        self.status_code = status_code
        super().__init__(f"Polar {operation} request failed with HTTP {status_code}")


class PolarBillingProvider:
    """Use Polar's HTTP API while preserving the domain billing protocol.

    ``webhook_secret`` and ``product_ids`` are constructor inputs rather than
    environment reads.  ``access_token`` is optional because an injected client
    may already own authentication (for example, a transport wrapper in the
    application composition root).  Paid operations remain disabled unless the
    composition root explicitly enables them.
    """

    _MAX_VERIFIED_BODIES = 1024
    _MAX_WEBHOOK_BODY_BYTES = 1_048_576
    _DEFAULT_BASE_URL = "https://api.polar.sh"
    _CHECKOUTS_PATH = "/v1/checkouts/"
    _CUSTOMER_SESSIONS_PATH = "/v1/customer-sessions/"
    _SUBSCRIPTIONS_PATH = "/v1/subscriptions/"
    _CUSTOMERS_PATH = "/v1/customers/"
    _DEFAULT_WEBHOOK_TOLERANCE_SECONDS = 300.0

    def __init__(
        self,
        client: AsyncHttpClient,
        webhook_secret: str | None = None,
        *,
        access_token: str | None = None,
        api_token: str | None = None,
        product_ids: Mapping[str, str] | None = None,
        plan_products: Mapping[str, str] | None = None,
        products: Mapping[str, str] | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 10.0,
        request_timeout: float | None = None,
        timeout_seconds: float | None = None,
        payments_enabled: bool = False,
        environment: str = "sandbox",
        allowed_return_origins: Iterable[str] | None = None,
        webhook_tolerance_seconds: float = _DEFAULT_WEBHOOK_TOLERANCE_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(client.post):
            raise TypeError("client must provide an async post method")
        if not isinstance(webhook_secret, str) or not webhook_secret:
            raise ValueError("webhook_secret is required")
        if not isinstance(payments_enabled, bool):
            raise ValueError("payments_enabled must be a boolean")

        resolved_products = product_ids or plan_products or products
        if not isinstance(resolved_products, Mapping) or not resolved_products:
            raise ValueError("product_ids must contain at least one plan")
        normalized_products: dict[str, str] = {}
        for plan_code, product_id in resolved_products.items():
            if not isinstance(plan_code, str) or not plan_code:
                raise ValueError("plan codes must be non-empty strings")
            if not isinstance(product_id, str) or not product_id:
                raise ValueError("product IDs must be non-empty strings")
            normalized_products[plan_code] = product_id

        resolved_timeout = request_timeout if request_timeout is not None else timeout_seconds
        if resolved_timeout is None:
            resolved_timeout = timeout
        if isinstance(resolved_timeout, bool) or not isinstance(resolved_timeout, (int, float)):
            raise ValueError("timeout must be a positive number")
        if resolved_timeout <= 0 or not math.isfinite(float(resolved_timeout)):
            raise ValueError("timeout must be a positive number")

        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an absolute HTTP(S) URL")

        resolved_token = access_token if access_token is not None else api_token
        if resolved_token is not None and not isinstance(resolved_token, str):
            raise ValueError("access_token must be a string")

        normalized_environment = _normalize_environment(environment)
        normalized_origins: set[str] = set()
        if allowed_return_origins is not None:
            if isinstance(allowed_return_origins, str):
                raise ValueError("allowed_return_origins must be an iterable of origins")
            for origin in allowed_return_origins:
                normalized_origins.add(_normalize_origin(origin))

        if isinstance(webhook_tolerance_seconds, bool) or not isinstance(webhook_tolerance_seconds, (int, float)):
            raise ValueError("webhook_tolerance_seconds must be a non-negative number")
        if webhook_tolerance_seconds < 0 or not math.isfinite(float(webhook_tolerance_seconds)):
            raise ValueError("webhook_tolerance_seconds must be a non-negative number")
        if clock is not None and not callable(clock):
            raise ValueError("clock must be callable")

        self._client = client
        self._webhook_secret = webhook_secret.encode("utf-8")
        self._access_token = resolved_token
        self._product_ids = normalized_products
        self._base_url = base_url.rstrip("/")
        self._timeout = float(resolved_timeout)
        self._payments_enabled = payments_enabled
        self._environment = normalized_environment
        self._allowed_return_origins = frozenset(normalized_origins)
        self._webhook_tolerance_seconds = float(webhook_tolerance_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._verified_bodies: OrderedDict[bytes, None] = OrderedDict()

    @property
    def payments_enabled(self) -> bool:
        return self._payments_enabled

    @property
    def environment(self) -> str:
        return self._environment

    async def create_checkout_session(
        self,
        *,
        tenant_id: UUID,
        plan_code: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """Create a tenant-bound checkout session for an allowlisted plan."""
        self._require_payments_enabled()
        if not isinstance(tenant_id, UUID):
            raise ValueError("tenant_id must be a UUID")
        if not isinstance(plan_code, str) or not plan_code:
            raise ValueError("plan_code is required")
        product_id = self._product_ids.get(plan_code)
        if product_id is None:
            raise ValueError("plan_code is not configured")
        _validate_url("success_url", success_url, self._allowed_return_origins)
        _validate_url("cancel_url", cancel_url, self._allowed_return_origins)

        payload: dict[str, object] = {
            "products": [product_id],
            "metadata": {"tenant_id": str(tenant_id), "environment": self._environment},
            "success_url": success_url,
            "return_url": cancel_url,
        }
        idempotency_key = _checkout_idempotency_key(
            environment=self._environment,
            tenant_id=tenant_id,
            plan_code=plan_code,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        try:
            response = await self._post(
                self._CHECKOUTS_PATH,
                payload,
                extra_headers={"Idempotency-Key": idempotency_key},
            )
        except Exception as exc:
            if _is_ambiguous_error(exc):
                raise CheckoutAmbiguityError(
                    "Polar checkout creation outcome is ambiguous; retry with the same request"
                ) from exc
            raise
        return _response_url(response, "checkout")

    async def create_portal_session(self, *, tenant_id: UUID, return_url: str) -> str:
        """Create a hosted customer portal session for the mapped tenant."""
        self._require_payments_enabled()
        if not isinstance(tenant_id, UUID):
            raise ValueError("tenant_id must be a UUID")
        _validate_url("return_url", return_url, self._allowed_return_origins)

        response = await self._post(
            self._CUSTOMER_SESSIONS_PATH,
            {
                "external_customer_id": self._scope_identifier(str(tenant_id)),
                "return_url": return_url,
            },
        )
        return _response_url(response, "portal")

    async def retrieve_state(
        self,
        *,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        request_timeout: float,
    ) -> BillingState:
        """Read authoritative subscription state for reconciliation."""
        if not isinstance(provider_customer_id, str) or not provider_customer_id:
            raise ValueError("provider_customer_id is required")
        if provider_subscription_id is not None and (
            not isinstance(provider_subscription_id, str) or not provider_subscription_id
        ):
            raise ValueError("provider_subscription_id must be a non-empty string")
        if isinstance(request_timeout, bool) or not isinstance(request_timeout, (int, float)):
            raise ValueError("request_timeout must be a positive number")
        if request_timeout <= 0 or not math.isfinite(float(request_timeout)):
            raise ValueError("request_timeout must be a positive number")

        raw_customer_id = self._unscope_identifier(provider_customer_id)
        raw_subscription_id = (
            self._unscope_identifier(provider_subscription_id) if provider_subscription_id is not None else None
        )
        if raw_subscription_id is not None:
            path = f"{self._SUBSCRIPTIONS_PATH}{quote(raw_subscription_id, safe='')}"
        else:
            path = f"{self._CUSTOMERS_PATH}{quote(raw_customer_id, safe='')}"
        response = await self._get(path, request_timeout=float(request_timeout))
        return _billing_state_from_response(
            response,
            environment=self._environment,
            requested_customer_id=raw_customer_id,
            requested_subscription_id=raw_subscription_id,
        )

    async def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        """Verify a constant-time HMAC for a fresh, identified event body."""
        if not isinstance(raw_body, bytes) or not raw_body or len(raw_body) > self._MAX_WEBHOOK_BODY_BYTES:
            return False
        if not isinstance(signature, str) or not signature:
            return False

        token = _signature_token(signature)
        if token is None:
            return False

        digest = hmac.new(self._webhook_secret, raw_body, hashlib.sha256).digest()
        expected_values = (
            base64.b64encode(digest).decode("ascii"),
            digest.hex(),
        )
        valid = any(hmac.compare_digest(token, expected) for expected in expected_values)
        if not valid:
            return False

        try:
            decoded = _decode_json_object(raw_body)
            _validate_event_shape(decoded)
            event_time = _event_timestamp(decoded)
            now = self._clock()
            if (
                now.tzinfo is None
                or abs((now.astimezone(UTC) - event_time).total_seconds()) > self._webhook_tolerance_seconds
            ):
                return False
        except (TypeError, ValueError, OverflowError):
            return False

        body_key = hashlib.sha256(raw_body).digest()
        self._verified_bodies[body_key] = None
        self._verified_bodies.move_to_end(body_key)
        while len(self._verified_bodies) > self._MAX_VERIFIED_BODIES:
            self._verified_bodies.popitem(last=False)
        return True

    async def parse_event(self, raw_body: bytes) -> Mapping[str, object]:
        """Return a verified event with environment-scoped provider identifiers."""
        if not isinstance(raw_body, bytes) or not raw_body or len(raw_body) > self._MAX_WEBHOOK_BODY_BYTES:
            raise ValueError("raw_body must be non-empty bounded bytes")
        body_key = hashlib.sha256(raw_body).digest()
        if body_key not in self._verified_bodies:
            raise ValueError("webhook payload was not verified")

        decoded = _decode_json_object(raw_body)
        _validate_event_shape(decoded)
        return _scope_event_payload(decoded, self._environment)

    async def _post(
        self,
        path: str,
        payload: Mapping[str, object],
        *,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, object]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if extra_headers is not None:
            headers.update(extra_headers)
        response = await self._client.post(
            f"{self._base_url}{path}",
            json=payload,
            headers=headers,
            request_timeout=self._timeout,
        )
        return _response_json(response, "POST")

    async def _get(self, path: str, *, request_timeout: float) -> Mapping[str, object]:
        get_method = getattr(self._client, "get", None)
        if not callable(get_method):
            raise RuntimeError("Polar client does not provide a GET method")
        get = cast(Callable[..., Awaitable[object]], get_method)
        headers: dict[str, str] = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        response = await get(f"{self._base_url}{path}", headers=headers, request_timeout=request_timeout)
        return _response_json(response, "GET")

    def _require_payments_enabled(self) -> None:
        if not self._payments_enabled:
            raise PaymentsDisabledError("payments are disabled")

    def _scope_identifier(self, value: str) -> str:
        return _scope_identifier(value, self._environment)

    def _unscope_identifier(self, value: str) -> str:
        prefix = f"{self._environment}:"
        return value[len(prefix) :] if value.startswith(prefix) else value


def _normalize_environment(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) is None:
        raise ValueError("environment must be a non-empty identifier")
    return value.lower()


def _scope_identifier(value: str, environment: str) -> str:
    prefix = f"{environment}:"
    return value if value.startswith(prefix) else f"{prefix}{value}"


def _checkout_idempotency_key(
    *,
    environment: str,
    tenant_id: UUID,
    plan_code: str,
    success_url: str,
    cancel_url: str,
) -> str:
    request = json.dumps(
        {
            "cancel_url": cancel_url,
            "environment": environment,
            "plan_code": plan_code,
            "success_url": success_url,
            "tenant_id": str(tenant_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{environment}-{hashlib.sha256(request).hexdigest()}"


def _is_ambiguous_error(exc: Exception) -> bool:
    if isinstance(exc, PolarRequestError):
        return exc.status_code >= 500
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    error_name = type(exc).__name__.lower()
    return any(marker in error_name for marker in ("timeout", "connection", "reset", "network"))


def _signature_token(signature: str) -> str | None:
    """Accept one Polar value, with the optional version prefix, exactly."""
    if signature.startswith("v1,"):
        token = signature[3:]
        return token or None
    if "," in signature:
        return None
    return signature


def _decode_json_object(raw_body: bytes) -> dict[str, object]:
    try:
        decoded = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("webhook body is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("Polar webhook payload must be an object")
    return cast(dict[str, object], decoded)


def _validate_event_shape(payload: Mapping[str, object]) -> None:
    event_id = payload.get("id")
    event_type = payload.get("type")
    timestamp = payload.get("timestamp")
    data = payload.get("data")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("Polar webhook payload requires a non-empty id")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("Polar webhook payload requires a non-empty type")
    if timestamp is None:
        raise ValueError("Polar webhook payload requires a timestamp")
    _event_timestamp(payload)
    if not isinstance(data, Mapping):
        raise ValueError("Polar webhook payload requires an object data field")


def _event_timestamp(payload: Mapping[str, object]) -> datetime:
    value = payload.get("timestamp")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise ValueError("Polar webhook timestamp must be finite")
        return datetime.fromtimestamp(float(value), UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Polar webhook timestamp is invalid") from exc
        if parsed.tzinfo is None:
            raise ValueError("Polar webhook timestamp must include a timezone")
        return parsed.astimezone(UTC)
    raise ValueError("Polar webhook timestamp is invalid")


def _scope_event_payload(payload: Mapping[str, object], environment: str) -> Mapping[str, object]:
    scoped = dict(payload)
    event_id = payload.get("id")
    if isinstance(event_id, str):
        scoped["id"] = _scope_identifier(event_id, environment)

    raw_data = payload.get("data")
    if not isinstance(raw_data, Mapping):
        return cast(Mapping[str, object], scoped)
    data = dict(raw_data)
    for field in ("customer_id", "provider_customer_id", "subscription_id"):
        value = data.get(field)
        if isinstance(value, str):
            data[field] = _scope_identifier(value, environment)
    if isinstance(data.get("id"), str):
        data["id"] = _scope_identifier(cast(str, data["id"]), environment)
    for nested_name in ("customer", "subscription"):
        nested = data.get(nested_name)
        if not isinstance(nested, Mapping):
            continue
        nested_copy = dict(nested)
        if isinstance(nested_copy.get("id"), str):
            nested_copy["id"] = _scope_identifier(cast(str, nested_copy["id"]), environment)
        if nested_name == "customer" and isinstance(nested_copy.get("provider_customer_id"), str):
            nested_copy["provider_customer_id"] = _scope_identifier(
                cast(str, nested_copy["provider_customer_id"]), environment
            )
        data[nested_name] = nested_copy
    scoped["data"] = data
    return cast(Mapping[str, object], scoped)


def _response_json(response: object, operation: str) -> Mapping[str, object]:
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int) and not isinstance(status_code, bool) and status_code >= 400:
        raise PolarRequestError(status_code, operation)
    raise_for_status = getattr(response, "raise_for_status", None)
    if callable(raise_for_status):
        try:
            raise_for_status()
        except Exception as exc:
            if isinstance(status_code, int) and not isinstance(status_code, bool):
                raise PolarRequestError(status_code, operation) from exc
            raise
    body = getattr(response, "json", None)
    if not callable(body):
        raise ValueError("Polar response does not provide JSON")
    decoded = body()
    if not isinstance(decoded, Mapping):
        raise ValueError("Polar response JSON must be an object")
    return cast(Mapping[str, object], decoded)


def _billing_state_from_response(
    response: Mapping[str, object],
    *,
    environment: str,
    requested_customer_id: str,
    requested_subscription_id: str | None,
) -> BillingState:
    payload = _state_payload(response, requested_subscription_id)
    customer_id = _first_text(
        payload.get("provider_customer_id"),
        payload.get("customer_id"),
        _nested_value(payload.get("customer"), "id"),
        requested_customer_id,
    )
    if customer_id is None:
        raise ValueError("Polar state response is missing customer id")
    subscription_id = _first_text(
        payload.get("provider_subscription_id"),
        payload.get("subscription_id"),
        payload.get("id") if payload.get("type") != "customer" else None,
        _nested_value(payload.get("subscription"), "id"),
        requested_subscription_id,
    )
    status = _billing_status(
        _first_text(
            payload.get("status"),
            _nested_value(payload.get("subscription"), "status"),
        )
    )
    tenant_id = _tenant_id_from_payload(payload, environment)
    event_position = _required_datetime(
        _first_value(
            payload.get("event_position"),
            payload.get("updated_at"),
            payload.get("last_updated_at"),
            payload.get("modified_at"),
            payload.get("timestamp"),
            _nested_value(payload.get("subscription"), "updated_at"),
        ),
        "provider event position",
    )
    return BillingState(
        tenant_id=tenant_id,
        status=status,
        provider_customer_id=_scope_identifier(customer_id, environment),
        current_period_end=_optional_datetime(
            _first_value(
                payload.get("current_period_end"),
                _nested_value(payload.get("subscription"), "current_period_end"),
            ),
            "current_period_end",
        ),
        past_due_since=_optional_datetime(
            _first_value(
                payload.get("past_due_since"),
                _nested_value(payload.get("subscription"), "past_due_since"),
            ),
            "past_due_since",
        ),
        provider_subscription_id=(
            _scope_identifier(subscription_id, environment) if subscription_id is not None else None
        ),
        event_position=event_position,
    )


def _state_payload(response: Mapping[str, object], requested_subscription_id: str | None) -> Mapping[str, object]:
    data = response.get("data")
    if isinstance(data, Mapping):
        merged = dict(response)
        merged.update(data)
        response = cast(Mapping[str, object], merged)
    subscriptions = response.get("subscriptions")
    if isinstance(subscriptions, list):
        for item in subscriptions:
            if not isinstance(item, Mapping):
                continue
            item_id = _first_text(item.get("id"), item.get("subscription_id"))
            if requested_subscription_id is None or item_id == requested_subscription_id:
                merged_item = dict(response)
                merged_item.update(item)
                return cast(Mapping[str, object], merged_item)
    return response


def _billing_status(value: str | None) -> BillingSubscriptionStatus:
    if value is None:
        raise ValueError("Polar state response is missing subscription status")
    normalized = value.lower()
    statuses = {
        "active": BillingSubscriptionStatus.ACTIVE,
        "trialing": BillingSubscriptionStatus.ACTIVE,
        "past_due": BillingSubscriptionStatus.PAST_DUE,
        "unpaid": BillingSubscriptionStatus.PAST_DUE,
        "canceled": BillingSubscriptionStatus.CANCELED,
        "cancelled": BillingSubscriptionStatus.CANCELED,
        "ended": BillingSubscriptionStatus.CANCELED,
        "refunded": BillingSubscriptionStatus.REFUND_HOLD,
        "refund_hold": BillingSubscriptionStatus.REFUND_HOLD,
        "none": BillingSubscriptionStatus.NONE,
    }
    try:
        return statuses[normalized]
    except KeyError as exc:
        raise ValueError("Polar state response has an unknown subscription status") from exc


def _tenant_id_from_payload(payload: Mapping[str, object], environment: str) -> UUID:
    candidates: tuple[object, ...] = (
        payload.get("tenant_id"),
        _nested_value(payload.get("metadata"), "tenant_id"),
        _nested_value(payload.get("customer_metadata"), "tenant_id"),
        payload.get("external_customer_id"),
        payload.get("external_id"),
        _nested_value(payload.get("customer"), "tenant_id"),
        _nested_value(payload.get("customer"), "external_id"),
        _nested_value(payload.get("customer"), "external_customer_id"),
    )
    prefix = f"{environment}:"
    for value in candidates:
        if isinstance(value, UUID):
            return value
        if not isinstance(value, str) or not value:
            continue
        candidate = value[len(prefix) :] if value.startswith(prefix) else value
        try:
            return UUID(candidate)
        except ValueError:
            continue
    raise ValueError("Polar state response is missing tenant id")


def _first_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _first_value(*values: object) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


def _nested_value(value: object, name: str) -> object | None:
    if isinstance(value, Mapping):
        return value.get(name)
    return None


def _optional_datetime(value: object, name: str) -> datetime | None:
    if value is None:
        return None
    return _required_datetime(value, name)


def _required_datetime(value: object, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Polar {name} is invalid") from exc
    else:
        raise ValueError(f"Polar {name} is required")
    if parsed.tzinfo is None:
        raise ValueError(f"Polar {name} must include a timezone")
    return parsed.astimezone(UTC)


def _normalize_origin(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("allowlisted origins must be HTTP(S) URLs")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("allowlisted origins must be absolute HTTP(S) URLs")
    if parts.username is not None or parts.password is not None or parts.path or parts.query or parts.fragment:
        raise ValueError("allowlisted origins must contain only a scheme, host, and optional port")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("allowlisted origin port is invalid") from exc
    host = parts.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = (parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)
    return f"{parts.scheme}://{host}{'' if port is None or default_port else f':{port}'}"


def _validate_url(name: str, value: str, allowed_origins: Iterable[str] = ()) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"{name} must not contain credentials")
    try:
        origin = _normalize_origin(f"{parts.scheme}://{parts.netloc}")
    except ValueError as exc:
        raise ValueError(f"{name} must use a valid origin") from exc
    if origin not in allowed_origins:
        raise ValueError(f"{name} origin is not allowlisted")


def _response_url(response: Mapping[str, object], operation: str) -> str:
    url = response.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError(f"Polar {operation} response is missing url")
    return url


__all__ = [
    "AsyncHttpClient",
    "CheckoutAmbiguityError",
    "PaymentsDisabledError",
    "PolarBillingProvider",
    "PolarRequestError",
]
