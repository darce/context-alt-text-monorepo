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
from collections import OrderedDict
from collections.abc import Mapping, MutableMapping
from typing import Protocol, cast
from uuid import UUID


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


class PolarBillingProvider:
    """Use Polar's HTTP API while preserving the domain billing protocol.

    ``webhook_secret`` and ``product_ids`` are constructor inputs rather than
    environment reads.  ``access_token`` is optional because an injected client
    may already own authentication (for example, a transport wrapper in the
    application composition root).

    The webhook method accepts the compact signature surface published by the
    domain protocol: a Polar HMAC over the exact raw body, optionally prefixed
    with ``v1,`` as Polar's signature header does.  Header-bound Standard
    Webhooks verification requires event-id and timestamp headers, which are not
    part of this protocol and therefore is intentionally outside this adapter.
    """

    _MAX_VERIFIED_BODIES = 1024
    _DEFAULT_BASE_URL = "https://api.polar.sh"
    _CHECKOUTS_PATH = "/v1/checkouts/"
    _CUSTOMER_SESSIONS_PATH = "/v1/customer-sessions/"

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
    ) -> None:
        if not callable(client.post):
            raise TypeError("client must provide an async post method")
        if not isinstance(webhook_secret, str) or not webhook_secret:
            raise ValueError("webhook_secret is required")

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
        if resolved_timeout <= 0:
            raise ValueError("timeout must be a positive number")

        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an absolute HTTP(S) URL")

        resolved_token = access_token if access_token is not None else api_token
        if resolved_token is not None and not isinstance(resolved_token, str):
            raise ValueError("access_token must be a string")

        self._client = client
        self._webhook_secret = webhook_secret.encode("utf-8")
        self._access_token = resolved_token
        self._product_ids = normalized_products
        self._base_url = base_url.rstrip("/")
        self._timeout = float(resolved_timeout)
        self._verified_bodies: MutableMapping[bytes, None] = OrderedDict()

    async def create_checkout_session(
        self,
        *,
        tenant_id: UUID,
        plan_code: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """Create a tenant-bound checkout session for an allowlisted plan."""
        if not isinstance(tenant_id, UUID):
            raise ValueError("tenant_id must be a UUID")
        if not isinstance(plan_code, str) or not plan_code:
            raise ValueError("plan_code is required")
        product_id = self._product_ids.get(plan_code)
        if product_id is None:
            raise ValueError("plan_code is not configured")
        _validate_url("success_url", success_url)
        _validate_url("cancel_url", cancel_url)

        response = await self._post(
            self._CHECKOUTS_PATH,
            {
                "products": [product_id],
                "metadata": {"tenant_id": str(tenant_id)},
                "success_url": success_url,
                "return_url": cancel_url,
            },
        )
        return _response_url(response, "checkout")

    async def create_portal_session(self, *, tenant_id: UUID, return_url: str) -> str:
        """Create a hosted customer portal session for the mapped tenant."""
        if not isinstance(tenant_id, UUID):
            raise ValueError("tenant_id must be a UUID")
        _validate_url("return_url", return_url)

        response = await self._post(
            self._CUSTOMER_SESSIONS_PATH,
            {
                "external_customer_id": str(tenant_id),
                "return_url": return_url,
            },
        )
        return _response_url(response, "portal")

    async def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        """Verify a signature over ``raw_body`` without parsing or re-encoding it."""
        if not isinstance(raw_body, bytes) or not raw_body:
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

        body_key = hashlib.sha256(raw_body).digest()
        self._verified_bodies[body_key] = None
        self._verified_bodies.move_to_end(body_key)
        while len(self._verified_bodies) > self._MAX_VERIFIED_BODIES:
            self._verified_bodies.popitem(last=False)
        return True

    async def parse_event(self, raw_body: bytes) -> Mapping[str, object]:
        """Return only the verified Polar event payload, with no local envelope."""
        if not isinstance(raw_body, bytes) or not raw_body:
            raise ValueError("raw_body must be non-empty bytes")
        body_key = hashlib.sha256(raw_body).digest()
        if body_key not in self._verified_bodies:
            raise ValueError("webhook payload was not verified")

        try:
            decoded = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("verified webhook body is not valid JSON") from exc

        if not isinstance(decoded, dict):
            raise ValueError("Polar webhook payload must be an object")
        _validate_event_shape(decoded)
        # Returning the provider object as parsed is deliberate: adding provider,
        # signature, receipt, or authorization fields would invent provenance.
        return cast(Mapping[str, object], decoded)

    async def _post(self, path: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        response = await self._client.post(
            f"{self._base_url}{path}",
            json=payload,
            headers=headers,
            timeout=self._timeout,
        )

        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and status_code >= 400:
            raise RuntimeError(f"Polar request failed with HTTP {status_code}")
        raise_for_status = getattr(response, "raise_for_status", None)
        if callable(raise_for_status):
            raise_for_status()
        body = getattr(response, "json", None)
        if not callable(body):
            raise ValueError("Polar response does not provide JSON")
        decoded = body()
        if not isinstance(decoded, Mapping):
            raise ValueError("Polar response JSON must be an object")
        return cast(Mapping[str, object], decoded)


def _signature_token(signature: str) -> str | None:
    """Accept one Polar value, with the optional version prefix, exactly."""
    if signature.startswith("v1,"):
        token = signature[3:]
        return token or None
    if "," in signature:
        return None
    return signature


def _validate_event_shape(payload: Mapping[str, object]) -> None:
    """Validate Polar's one documented raw shape; do not guess alternate envelopes."""
    event_type = payload.get("type")
    timestamp = payload.get("timestamp")
    data = payload.get("data")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("Polar webhook payload requires a non-empty type")
    if not isinstance(timestamp, str) or not timestamp:
        raise ValueError("Polar webhook payload requires a non-empty timestamp")
    if not isinstance(data, Mapping):
        raise ValueError("Polar webhook payload requires an object data field")


def _validate_url(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")


def _response_url(response: Mapping[str, object], operation: str) -> str:
    url = response.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError(f"Polar {operation} response is missing url")
    return url


__all__ = ["AsyncHttpClient", "PolarBillingProvider"]
