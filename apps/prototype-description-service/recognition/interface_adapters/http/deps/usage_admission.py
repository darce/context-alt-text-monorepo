"""HTTP dependencies and transaction boundary for billable analyze work."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.params import Depends as DependsMarker
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.usage_admission_service import (
    AllowanceExceededError,
    GlobalUsageLimitExceededError,
    UsageAdmissionStoppedError,
    UsageAdmissionTimeoutError,
    UsageAdmissionUnavailableError,
    UsageFingerprintConflictError,
)
from recognition.domain.portal_contracts import UsageAdmissionService, UsageTicket
from recognition.interface_adapters.http.deps.session import get_optional_session, get_session

logger = logging.getLogger(__name__)
_RESERVATION_TIMEOUT_RETRY_AFTER_S = 5


def _is_usage_service(value: object) -> bool:
    return all(callable(getattr(value, method_name, None)) for method_name in ("reserve", "commit", "release"))


def get_usage_admission_service(
    request: Request,
    session: AsyncSession | None = Depends(get_optional_session),
) -> UsageAdmissionService | None:
    """Resolve the optional request-scoped usage service installed by portal composition."""
    configured = getattr(request.app.state, "usage_admission_service", None)
    if configured is None:
        return None
    if _is_usage_service(configured):
        return cast(UsageAdmissionService, configured)
    if isinstance(session, DependsMarker):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage admission unavailable",
        )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage admission unavailable",
        )
    if not callable(configured):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage admission unavailable",
        )
    service = configured(session)
    if not _is_usage_service(service):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage admission unavailable",
        )
    return cast(UsageAdmissionService, service)


async def get_required_usage_admission_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> UsageAdmissionService:
    """Resolve required admission in the route's transaction and fail closed if absent."""
    configured = getattr(request.app.state, "usage_admission_service", None)
    if configured is None:
        raise _admission_unavailable("usage_admission_unavailable")
    if _is_usage_service(configured):
        return cast(UsageAdmissionService, configured)
    if isinstance(session, DependsMarker):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage admission unavailable",
        )
    if session is None or not callable(configured):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage admission unavailable",
        )
    service = configured(session)
    if not _is_usage_service(service):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage admission unavailable",
        )
    return cast(UsageAdmissionService, service)


def build_usage_idempotency_key(
    tenant_id: object,
    media_ids: Sequence[object],
    media_sources: Sequence[object],
) -> str:
    """Build a retry-stable key from the tenant, canonical media IDs, and source digest."""
    if len(media_ids) != len(media_sources):
        raise ValueError("media_ids and media_sources must have the same length")

    canonical_items = sorted(
        (str(media_id), str(media_source)) for media_id, media_source in zip(media_ids, media_sources, strict=True)
    )
    source_payload = json.dumps([source for _media_id, source in canonical_items], separators=(",", ":"))
    source_digest = hashlib.sha256(source_payload.encode("utf-8")).hexdigest()
    fingerprint = {
        "tenant_id": str(tenant_id),
        "media_ids": [media_id for media_id, _source in canonical_items],
        "media_sources_sha256": source_digest,
    }
    return hashlib.sha256(json.dumps(fingerprint, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_usage_operation_id(tenant_id: object, *, route: str, idempotency_keys: Sequence[object]) -> str:
    """Build a bounded, retry-stable operation ID from the client's idempotency keys."""
    identity = {
        "tenant_id": str(tenant_id),
        "route": route,
        "idempotency_keys": [str(key) for key in idempotency_keys],
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_usage_request_fingerprint(tenant_id: object, *, route: str, payload: object) -> str:
    """Fingerprint the normalized request body under its authenticated tenant and route."""
    canonical = json.dumps(
        {"tenant_id": str(tenant_id), "route": route, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _retry_after_seconds(period_end: object) -> int | None:
    if isinstance(period_end, str):
        try:
            period_end = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(period_end, datetime):
        return None
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=UTC)
    return max(0, math.ceil((period_end - datetime.now(tz=UTC)).total_seconds()))


def _allowance_exhausted(exc: AllowanceExceededError) -> HTTPException:
    headers: dict[str, str] = {}
    retry_after = _retry_after_seconds(getattr(exc, "period_end", None))
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={"error": "allowance_exhausted"},
        headers=headers or None,
    )


def _admission_unavailable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": detail},
    )


def _reservation_timeout() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "reservation_timeout"},
        headers={"Retry-After": str(_RESERVATION_TIMEOUT_RETRY_AFTER_S)},
    )


async def _rollback_usage_transaction(service: object) -> None:
    repository = getattr(service, "_repository", None)
    session = getattr(repository, "_session", None) if repository is not None else None
    if session is None:
        session = getattr(service, "_session", None)
    rollback = getattr(session, "rollback", None)
    if not callable(rollback):
        return
    result = rollback()
    if hasattr(result, "__await__"):
        await result


@asynccontextmanager
async def admit_usage(
    service: UsageAdmissionService | None,
    *,
    tenant_id,
    idempotency_key: str,
    job_id: str | None,
    cost_units: int,
    operation_id: str | None = None,
    request_fingerprint: str | None = None,
    queue_bytes: int = 0,
) -> AsyncIterator[UsageTicket | None]:
    """Reserve before dispatch and leave HTTP 202 as RESERVED.

    Handler success is not terminal settlement. Queue refusal and dispatch
    exceptions release once. G2/G3 call ``commit_fenced`` / ``release_fenced``.
    """
    # Direct unit callers may invoke a FastAPI route without resolving its
    # Depends default.  The real dependency has already validated the service
    # shape before this helper runs, so an unresolved default is the disabled
    # path just like an absent app-state service.
    if service is None or not _is_usage_service(service):
        yield None
        return

    try:
        ticket = await service.reserve(
            tenant_id,
            idempotency_key=idempotency_key,
            job_id=job_id,
            cost_units=cost_units,
            operation_id=operation_id,
            request_fingerprint=request_fingerprint,
            queue_bytes=queue_bytes,
        )
    except AllowanceExceededError as exc:
        raise _allowance_exhausted(exc) from exc
    except UsageFingerprintConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "usage_fingerprint_conflict"},
        ) from exc
    except UsageAdmissionStoppedError as exc:
        raise _admission_unavailable("usage_admission_stopped") from exc
    except GlobalUsageLimitExceededError as exc:
        raise _admission_unavailable("usage_admission_limited") from exc
    except UsageAdmissionUnavailableError as exc:
        raise _admission_unavailable("usage_admission_unavailable") from exc
    except UsageAdmissionTimeoutError as exc:
        try:
            await _rollback_usage_transaction(service)
        except BaseException:
            logger.exception(
                "Usage reservation timeout rollback failed",
                extra={"tenant_id": str(tenant_id)},
            )
        raise _reservation_timeout() from exc

    try:
        yield ticket
    except BaseException:
        try:
            await service.release(ticket)
        except BaseException:
            logger.exception("Usage reservation release failed", extra={"tenant_id": str(tenant_id)})
        raise
    # HTTP 202 / handler return stays RESERVED. Workers own terminal settlement.


__all__ = [
    "admit_usage",
    "build_usage_idempotency_key",
    "build_usage_operation_id",
    "build_usage_request_fingerprint",
    "get_usage_admission_service",
    "get_required_usage_admission_service",
]
