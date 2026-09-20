"""Signed Polar webhook intake and bounded local billing projection."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Final, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError

from recognition.domain.portal_contracts import BillingProvider, BillingSubscriptionStatus
from recognition.infrastructure.billing.polar_provider import _billing_status as _provider_billing_status
from recognition.infrastructure.repositories.billing_repository import BillingRepository

logger = logging.getLogger(__name__)

POLAR_PROVIDER: Final[str] = "polar"
# WHY: the request stream is consumed incrementally so a peer cannot make this
# endpoint allocate an unbounded body before signature verification.
MAX_WEBHOOK_BODY_BYTES: Final[int] = 1_048_576
WEBHOOK_PERSIST_TIMEOUT_SECONDS: Final[float] = 2.0
WEBHOOK_PROJECTION_TIMEOUT_SECONDS: Final[float] = 1.0

_SIGNATURE_HEADERS: Final[tuple[str, ...]] = (
    "webhook-signature",
    "x-polar-signature",
    "polar-signature",
    "x-webhook-signature",
)

_EVENT_STATUS: Final[dict[str, BillingSubscriptionStatus]] = {
    "subscription.active": BillingSubscriptionStatus.ACTIVE,
    "subscription.created": BillingSubscriptionStatus.ACTIVE,
    "subscription.renewed": BillingSubscriptionStatus.ACTIVE,
    "subscription.trialing": BillingSubscriptionStatus.ACTIVE,
    "subscription.past_due": BillingSubscriptionStatus.PAST_DUE,
    "subscription.payment_failed": BillingSubscriptionStatus.PAST_DUE,
    "subscription.unpaid": BillingSubscriptionStatus.PAST_DUE,
    "subscription.canceled": BillingSubscriptionStatus.CANCELED,
    "subscription.cancelled": BillingSubscriptionStatus.CANCELED,
    "subscription.ended": BillingSubscriptionStatus.CANCELED,
    "subscription.refunded": BillingSubscriptionStatus.REFUND_HOLD,
    "order.refunded": BillingSubscriptionStatus.REFUND_HOLD,
    "refund.created": BillingSubscriptionStatus.REFUND_HOLD,
}

router = APIRouter(prefix="/billing", tags=["billing"])


async def get_billing_provider(request: Request) -> BillingProvider:
    """Resolve the injected provider without reading a secret in the router.

    The later application composition lane installs the provider on app state
    or overrides this dependency.  Keeping the default fail-closed makes an
    accidentally mounted endpoint unavailable instead of silently accepting
    unsigned events.
    """
    provider = getattr(request.app.state, "billing_provider", None)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing provider unavailable")
    return cast(BillingProvider, provider)


async def get_billing_repository(request: Request) -> BillingRepository:
    """Resolve the injected durable inbox repository from application state."""
    repository = getattr(request.app.state, "billing_repository", None)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing repository unavailable")
    return cast(BillingRepository, repository)


async def _commit_billing_transaction(repository: BillingRepository) -> None:
    try:
        await repository.session.commit()
    except Exception as exc:
        logger.exception("Failed to commit Polar webhook")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook persistence unavailable",
        ) from exc


@router.post("/webhooks/polar", status_code=status.HTTP_202_ACCEPTED)
async def receive_polar_webhook(
    request: Request,
    provider: BillingProvider = Depends(get_billing_provider),
    repository: BillingRepository = Depends(get_billing_repository),
) -> Response:
    """Verify, durably enqueue, and acknowledge one Polar webhook.

    The provider adapter owns constant-time signature comparison.  This
    boundary passes it the exact bytes read from the request stream and only
    asks it to parse after verification succeeds.  Projection is deliberately
    a second operation and is bounded; a timeout leaves the received inbox row
    available to a later worker instead of making the provider redeliver it.
    """
    signature = _signature_from_request(request)
    if not signature:
        raise _invalid_signature()

    raw_body = await _read_bounded_body(request)

    try:
        signature_verified = await provider.verify_webhook(raw_body, signature)
    except Exception:
        logger.warning("Polar webhook signature verification failed")
        signature_verified = False
    if signature_verified is not True:
        raise _invalid_signature()

    try:
        parsed = await provider.parse_event(raw_body)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload") from exc
    if not isinstance(parsed, Mapping):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")

    payload = cast(Mapping[str, object], parsed)
    event_id = _event_id(payload, raw_body)
    event_type = _required_text(payload, "type")

    try:
        async with asyncio.timeout(WEBHOOK_PERSIST_TIMEOUT_SECONDS):
            inserted = await repository.record_webhook(
                provider=POLAR_PROVIDER,
                provider_event_id=event_id,
                event_type=event_type,
                signature_verified=True,
                payload=payload,
            )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook persistence unavailable",
            headers={"Retry-After": "1"},
        ) from exc
    except IntegrityError as exc:
        # WHY: BillingRepository normally catches the unique-conflict itself;
        # this guard keeps injected repositories idempotent without a pre-read.
        try:
            existing = await repository.get_webhook(provider=POLAR_PROVIDER, provider_event_id=event_id)
        except Exception as lookup_exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Webhook persistence unavailable",
            ) from lookup_exc
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Webhook persistence unavailable",
            ) from exc
        inserted = False
    except Exception as exc:
        logger.exception("Failed to persist Polar webhook")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook persistence unavailable",
        ) from exc

    if inserted is not True:
        try:
            projected = await _duplicate_projection_is_ready(
                repository,
                provider_event_id=event_id,
                event_type=event_type,
                payload=payload,
            )
        except Exception:
            logger.exception("Failed to check the existing Polar webhook projection")
            projected = False
        if projected is not True:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Webhook projection unavailable",
                headers={"Retry-After": "1"},
            )
        await _commit_billing_transaction(repository)
        return _accepted_response()

    projected = await _project_and_mark(
        repository,
        provider_event_id=event_id,
        event_type=event_type,
        payload=payload,
    )
    if projected is not True:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook projection unavailable",
            headers={"Retry-After": "1"},
        )
    await _commit_billing_transaction(repository)
    return _accepted_response()


async def _duplicate_projection_is_ready(
    repository: BillingRepository,
    *,
    provider_event_id: str,
    event_type: str,
    payload: Mapping[str, object],
) -> bool:
    projection = _projection_arguments(payload, event_type)
    if projection is None:
        return True
    get_projection = getattr(repository, "get_projection", None)
    if not callable(get_projection):
        return True
    current = await get_projection(cast(UUID, projection["tenant_id"]), provider=POLAR_PROVIDER)
    if current is not None:
        if isinstance(current, Mapping):
            current_event_id = current.get("last_event_id", current.get("provider_event_id"))
        else:
            current_event_id = getattr(current, "last_event_id", None)
            if current_event_id is None:
                current_event_id = getattr(current, "provider_event_id", None)
        if current_event_id == provider_event_id:
            return True
    return await _project_and_mark(
        repository,
        provider_event_id=provider_event_id,
        event_type=event_type,
        payload=payload,
    )


async def _project_and_mark(
    repository: BillingRepository,
    *,
    provider_event_id: str,
    event_type: str,
    payload: Mapping[str, object],
) -> bool:
    """Project one inbox event while leaving entitlement work to the worker."""
    projection = _projection_arguments(payload, event_type)
    if projection is None:
        logger.warning("Polar webhook was not projected; inbox row remains pending")
        return True

    if projection["provider_subscription_id"] is None and not _is_subscription_event(event_type):
        try:
            projection["provider_subscription_id"] = await _existing_provider_subscription_id(
                repository,
                cast(UUID, projection["tenant_id"]),
            )
        except Exception:
            logger.exception("Failed to read the existing Polar subscription pointer; inbox row remains pending")
            return False

    try:
        bound_customer_id = await _existing_provider_customer_id(
            repository,
            cast(UUID, projection["tenant_id"]),
        )
    except Exception:
        logger.exception("Failed to read the existing Polar customer binding; inbox row remains pending")
        return False
    # WHY: the HMAC proves the delivery channel, not the authority of the payload's
    # tenant_id. Mirror the reconciler's binding check so a customer cannot be
    # repointed at another tenant's projection through webhook metadata alone.
    if bound_customer_id is not None and bound_customer_id != cast(str, projection["provider_customer_id"]).strip():
        logger.error("Polar webhook customer does not match the tenant's bound customer; inbox row remains pending")
        return False

    try:
        async with asyncio.timeout(WEBHOOK_PROJECTION_TIMEOUT_SECONDS):
            applied = await repository.upsert_projection(
                tenant_id=projection["tenant_id"],
                provider=POLAR_PROVIDER,
                provider_customer_id=projection["provider_customer_id"],
                provider_subscription_id=projection["provider_subscription_id"],
                status=projection["status"],
                current_period_end=projection["current_period_end"],
                past_due_since=projection["past_due_since"],
                provider_event_id=provider_event_id,
                event_position=projection["event_position"],
            )
    except TimeoutError:
        logger.warning("Polar webhook projection timed out; inbox row remains pending")
        return False
    except Exception:
        logger.exception("Failed to project Polar webhook; inbox row remains pending")
        return False

    # WHY: repository ordering under its row lock makes False an observable
    # duplicate/older-event skip rather than a state regression.
    if applied is not True:
        logger.warning("Polar webhook projection did not apply; inbox row remains pending")
        return False
    return True


async def _read_bounded_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > MAX_WEBHOOK_BODY_BYTES:
            raise _body_too_large()

    body = bytearray()
    try:
        async for chunk in request.stream():
            if not isinstance(chunk, bytes):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook body")
            if len(body) + len(chunk) > MAX_WEBHOOK_BODY_BYTES:
                raise _body_too_large()
            body.extend(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook body") from exc
    return bytes(body)


def _signature_from_request(request: Request) -> str | None:
    for header_name in _SIGNATURE_HEADERS:
        value = request.headers.get(header_name)
        if value:
            return value
    return None


def _event_id(payload: Mapping[str, object], raw_body: bytes) -> str:
    value = payload.get("id")
    if isinstance(value, str) and value:
        return value
    # WHY: a content digest is the documented deterministic fallback for a
    # verified fixture without an event id; arrival time/random UUID are not.
    return hashlib.sha256(raw_body).hexdigest()


def _required_text(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")
    return value


def _projection_arguments(payload: Mapping[str, object], event_type: str) -> dict[str, object] | None:
    status_value = _status_for_event(payload, event_type)
    if status_value is None:
        return None

    data = payload.get("data")
    if not isinstance(data, Mapping):
        return None
    tenant_id = _tenant_id(payload, data)
    provider_customer_id = _provider_customer_id(data)
    provider_subscription_id = _provider_subscription_id(data)
    event_position = payload.get("timestamp")
    if tenant_id is None or provider_customer_id is None:
        return None
    if _is_subscription_event(event_type) and provider_subscription_id is None:
        return None
    if not isinstance(event_position, str) or not event_position:
        return None

    current_period_end = _optional_datetime(data.get("current_period_end"))
    past_due_since = _optional_datetime(data.get("past_due_since"))
    if status_value is BillingSubscriptionStatus.PAST_DUE and past_due_since is None:
        # WHY: provider timestamp is the only documented event-time fallback;
        # local receipt time would change provider ordering semantics.
        past_due_since = _optional_datetime(event_position)

    return {
        "tenant_id": tenant_id,
        "provider_customer_id": provider_customer_id,
        "provider_subscription_id": provider_subscription_id,
        "status": status_value,
        "current_period_end": current_period_end,
        "past_due_since": past_due_since,
        "event_position": event_position,
    }


def _status_for_event(payload: Mapping[str, object], event_type: str) -> BillingSubscriptionStatus | None:
    status_value = _EVENT_STATUS.get(event_type)
    if status_value is not None:
        return status_value
    if event_type != "subscription.updated":
        return None
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return None
    provider_status = data.get("status")
    if not isinstance(provider_status, str):
        logger.warning("Polar webhook subscription.updated is missing a subscription status")
        return None
    try:
        return _provider_billing_status(provider_status)
    except ValueError:
        logger.warning("Polar webhook has an unmapped subscription status: %s", provider_status)
        return None


def _is_subscription_event(event_type: str) -> bool:
    return event_type.startswith("subscription.")


def _tenant_id(payload: Mapping[str, object], data: Mapping[str, object]) -> UUID | None:
    """Read the provider's explicit tenant reference, never a customer guess."""
    candidates: list[object] = [payload.get("tenant_id"), data.get("tenant_id"), data.get("external_customer_id")]
    for metadata_source in (data.get("metadata"), data.get("customer_metadata")):
        if isinstance(metadata_source, Mapping):
            candidates.append(metadata_source.get("tenant_id"))
    customer = data.get("customer")
    if isinstance(customer, Mapping):
        candidates.extend((customer.get("tenant_id"), customer.get("external_id")))
    for candidate in candidates:
        if isinstance(candidate, UUID):
            return candidate
        if isinstance(candidate, str) and candidate:
            try:
                return UUID(candidate)
            except ValueError:
                continue
    return None


def _provider_customer_id(data: Mapping[str, object]) -> str | None:
    for field in ("customer_id", "provider_customer_id"):
        value = data.get(field)
        if isinstance(value, str) and value:
            return value
    customer = data.get("customer")
    if isinstance(customer, Mapping):
        value = customer.get("id")
        if isinstance(value, str) and value:
            return value
    return None


def _provider_subscription_id(data: Mapping[str, object]) -> str | None:
    for field in ("provider_subscription_id", "subscription_id"):
        value = data.get(field)
        if isinstance(value, str) and value:
            return value
    return None


async def _existing_provider_customer_id(repository: BillingRepository, tenant_id: UUID) -> str | None:
    projection = await repository.get_projection(tenant_id, provider=POLAR_PROVIDER)
    if projection is None:
        return None
    if isinstance(projection, Mapping):
        value = projection.get("provider_customer_id")
    else:
        value = getattr(projection, "provider_customer_id", None)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("existing provider customer id is invalid")
    return value.strip()


async def _existing_provider_subscription_id(repository: BillingRepository, tenant_id: UUID) -> str | None:
    projection = await repository.get_projection(tenant_id, provider=POLAR_PROVIDER)
    if projection is None:
        return None
    if isinstance(projection, Mapping):
        value = projection.get("provider_subscription_id")
    else:
        value = getattr(projection, "provider_subscription_id", None)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("existing provider subscription id is invalid")
    return value


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _invalid_signature() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")


def _body_too_large() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail="Webhook body exceeds the configured size limit",
    )


def _accepted_response() -> Response:
    return Response(status_code=status.HTTP_202_ACCEPTED)


__all__ = [
    "MAX_WEBHOOK_BODY_BYTES",
    "POLAR_PROVIDER",
    "WEBHOOK_PERSIST_TIMEOUT_SECONDS",
    "WEBHOOK_PROJECTION_TIMEOUT_SECONDS",
    "get_billing_provider",
    "get_billing_repository",
    "receive_polar_webhook",
    "router",
]
