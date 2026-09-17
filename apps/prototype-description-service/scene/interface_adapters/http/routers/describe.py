"""POST /scene/describe/multipart — one-image synchronous seeded description (E19-1 S5).

Reuses recognition's auth + optional-session deps and the multipart ``request``
envelope + single ``image_<media_id>`` part contract, but runs synchronously
(the seeded adapter is instant) and reads the image bytes directly — no
ObjectStore staging, which is the S9 ``local_cpu`` async path. Mounted at
``/scene`` in api/main.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import FormData, UploadFile

from db.models.scene import DescribeDemandLease, DescribeOperation
from db.tenant_context import enable_rls_bypass, require_tenant_record, set_tenant_context
from recognition.infrastructure.repositories.audit_repository import AuditRepository
from recognition.interface_adapters.http.deps import (
    get_optional_session,
    require_write_access,
)
from recognition.interface_adapters.http.deps.demo_quota import maybe_consume_demo_quota
from recognition.interface_adapters.http.middleware.metrics import get_default_metrics
from recognition.shared.db.dialect import is_postgres
from scene.application.describe_async_worker import run_async_describe_job
from scene.application.describe_load import dump_load_snapshot
from scene.application.describe_operation_repository import DescribeOperationRepository
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.description_repository import ImageDescriptionRepository
from scene.application.gpu_intent import IntentAction, read_gpu_intent, resolve_gpu_intent_path
from scene.application.gpu_state import (
    GPU_STATE_FUTURE_SKEW_SECONDS,
    GpuState,
    read_gpu_state,
    resolve_gpu_state_path,
    resolve_gpu_state_stale_seconds,
)
from scene.application.hashing import compute_context_hash, compute_image_hash
from scene.application.naming_preview_service import (
    faces_for_naming_preview as _faces_for_naming_preview,
)
from scene.application.naming_preview_service import (
    load_fusion_naming_inputs as _load_fusion_naming_inputs,
)
from scene.application.naming_preview_service import (
    naming_preview as _naming_preview,
)
from scene.application.settings.vlm import VlmSettings
from scene.application.visual_facts_service import (
    AdapterAttemptTiming,
    VisualFactsService,
    VisualFactsServiceResult,
)
from scene.config.settings import DescriptionSettings
from scene.domain.describe_run import (
    DemandLeaseState,
    DescribeJobStatus,
    OperationExpiredError,
    OperationMismatchError,
    RunKind,
    describe_job_error,
    describe_job_status,
    utc_observation,
)
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.provider.hosted_provider_adapter import HostedProviderError
from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteAdapterError
from scene.infrastructure.vlm.unavailable_adapter import DescriptionAdapterUnavailableError
from scene.interface_adapters.http.deps import (
    get_async_gpu_description_adapter,
    get_cpu_description_adapter,
    get_description_adapter,
    get_gpu_description_adapter,
)
from scene.interface_adapters.http.schemas.requests import DescribeImageEnvelope
from scene.interface_adapters.http.schemas.responses import (
    DescribeJobResult,
    DescribeOperationErrorDetail,
    DescribeTiming,
    MultipartDescribeResponse,
    UnavailableReason,
)

router = APIRouter(tags=["describe"])

_logger = logging.getLogger(__name__)

_IMAGE_KEY_PREFIX = "image_"
# Defaults match the former volatile store (256 MiB retained / 1000 jobs).
_DEFAULT_MAX_PENDING_JOBS = 1000
_DEFAULT_MAX_RETAINED_IMAGE_BYTES = 256 * 1024 * 1024
_PUBLIC_RETRY_AFTER_CEILING = 120
_DEFAULT_LEASE_SECONDS = 180.0
_MAX_LEASE_REASON = "lease_cap"
_UNTIMED = DescribeTiming(
    queue_ms=None,
    ramp_up_ms=None,
    processing_ms=None,
    startup_ms=None,
    server_elapsed_ms=None,
)


class AsyncAdmissionGate:
    """Process-local byte-budget + job-count gate for async single-run jobs.

    Reservations are held only for the lifetime of an in-process enqueue/worker
    task and are never derived from DB rows — counter starts at 0 on every boot
    (design (b) / [RES-04], [RES-14], [CON-16]).
    """

    def __init__(
        self,
        *,
        max_jobs: int = _DEFAULT_MAX_PENDING_JOBS,
        max_retained_image_bytes: int = _DEFAULT_MAX_RETAINED_IMAGE_BYTES,
    ) -> None:
        self._max_jobs = max_jobs
        self._max_retained_image_bytes = max_retained_image_bytes
        self._job_count = 0
        self._retained_image_bytes = 0
        self._lock = Lock()

    def try_acquire(self, image_len: int) -> str | None:
        """Reserve a slot. Returns ``None`` on success, else a wire-stable 503 detail.

        Callers treat a non-``None`` return as refusal (equivalent to ``False``) and
        surface it as HTTP 503. Detail strings match the deleted store's
        ``RuntimeError`` texts so existing 503 assertions stay textually intact.
        """
        with self._lock:
            if self._job_count >= self._max_jobs:
                return "describe job queue is full"
            if self._retained_image_bytes + image_len > self._max_retained_image_bytes:
                return "describe job store image byte budget exceeded"
            self._job_count += 1
            self._retained_image_bytes += image_len
            return None

    def release(self, image_len: int) -> None:
        with self._lock:
            self._job_count = max(0, self._job_count - 1)
            self._retained_image_bytes = max(0, self._retained_image_bytes - image_len)


def _async_admission_gate() -> AsyncAdmissionGate:
    max_jobs = int(os.environ.get("ACX_ASYNC_MAX_PENDING_JOBS", str(_DEFAULT_MAX_PENDING_JOBS)))
    max_bytes = int(os.environ.get("ACX_ASYNC_MAX_RETAINED_IMAGE_BYTES", str(_DEFAULT_MAX_RETAINED_IMAGE_BYTES)))
    return AsyncAdmissionGate(max_jobs=max_jobs, max_retained_image_bytes=max_bytes)


_ASYNC_ADMISSION = _async_admission_gate()


def worker_session_factory(session) -> async_sessionmaker[AsyncSession]:
    """Own an independent session factory for background/stream work.

    Mirrors analyze.py: derive from the request session's bind for the
    SQLite/test path, else fall back to the process-wide Postgres factory so
    worker commits use their own connection/transaction.
    """
    if session is not None and getattr(session, "bind", None) is not None and not is_postgres(session):
        return async_sessionmaker(bind=session.bind, expire_on_commit=False)
    from db.session import async_session_factory

    return async_session_factory


@dataclass(frozen=True)
class ValidatedDescribeMultipart:
    envelope: DescribeImageEnvelope
    tenant_uuid: uuid.UUID
    image_bytes: bytes
    context: dict[str, Any] | None
    operation_id: str | None


class _DescriptionAuditSink:
    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    async def record(self, *, tenant_id: uuid.UUID, event_type: str, payload: dict) -> None:
        await self._repository.create_event(
            tenant_id=str(tenant_id),
            event_type=event_type,
            actor="scene.describe",
            scope="media",
            payload=payload,
        )


class _BackgroundDescriptionAuditSink:
    """Audit sink that opens its own AsyncSession per write (VLMFIX-S1-01).

    FastAPI closes yield-dependency sessions after the response and before
    BackgroundTasks run, so the request-scoped session cannot be reused here.
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def record(self, *, tenant_id: uuid.UUID, event_type: str, payload: dict) -> None:
        async with self._session_factory() as session:
            await set_tenant_context(session, tenant_id)
            repository = AuditRepository(session)
            await repository.create_event(
                tenant_id=str(tenant_id),
                event_type=event_type,
                actor="scene.describe",
                scope="media",
                payload=payload,
            )
            await session.commit()


class _DescriptionMetricsSink:
    def __init__(self) -> None:
        self._metrics = get_default_metrics()

    def record_request(self, *, adapter: str, result: str) -> None:
        self._metrics.description_requests_total.labels(adapter=adapter, result=result).inc()

    def record_cache_hit(self, *, adapter: str) -> None:
        self._metrics.description_cache_hits_total.labels(adapter=adapter).inc()

    def observe_readiness_wait(self, *, adapter: str, seconds: float) -> None:
        self._metrics.description_readiness_wait_seconds.labels(adapter=adapter).observe(seconds)

    def observe_adapter_duration(self, *, adapter: str, duration_seconds: float) -> None:
        self._metrics.description_adapter_duration_seconds.labels(adapter=adapter).observe(duration_seconds)


def _read_request_part(raw) -> dict:
    if raw is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "multipart submission must include a 'request' JSON part")
    if isinstance(raw, UploadFile):
        body = raw.file.read()
    elif isinstance(raw, (bytes, bytearray)):
        body = bytes(raw)
    else:
        body = str(raw).encode("utf-8")
    try:
        envelope = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'request' part is not valid JSON: {exc}") from exc
    if not isinstance(envelope, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "'request' part must decode to a JSON object")
    return envelope


def _generation_timeout_seconds(settings: DescriptionSettings, adapter) -> float:
    if adapter.kind is DescriptionAdapterKind.LOCAL_CPU:
        return VlmSettings().inference_timeout_seconds
    return settings.generation_timeout_seconds


def _lease_seconds() -> float:
    raw = os.environ.get("ACX_DESCRIBE_LEASE_SECONDS")
    if raw is None or raw == "":
        seconds = _DEFAULT_LEASE_SECONDS
    else:
        try:
            seconds = float(raw)
        except ValueError as exc:
            raise RuntimeError(f"ACX_DESCRIBE_LEASE_SECONDS={raw!r} is not a number") from exc
    if not math.isfinite(seconds) or seconds <= _PUBLIC_RETRY_AFTER_CEILING:
        raise RuntimeError(
            "ACX_DESCRIBE_LEASE_SECONDS must be finite and greater than the "
            f"{_PUBLIC_RETRY_AFTER_CEILING}s Retry-After ceiling"
        )
    return seconds


def _optional_operation_id(form: FormData) -> str | None:
    if "operation_id" not in form:
        return None
    raw = form.get("operation_id")
    if isinstance(raw, UploadFile):
        body = raw.file.read()
        text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
    elif isinstance(raw, (bytes, bytearray)):
        text = bytes(raw).decode("utf-8")
    else:
        text = str(raw)
    stripped = text.strip()
    if not stripped or len(stripped) > 128:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "operation_id must be a non-empty string of at most 128 characters",
        )
    return stripped


def _multipart_request_digest(*, media_id: int, image_bytes: bytes, context: Mapping[str, Any] | None) -> str:
    canonical = json.dumps(
        {
            "media_id": int(media_id),
            "image_hash": compute_image_hash(image_bytes),
            "context_hash": compute_context_hash(context),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _LifecycleHoldHTTPException(HTTPException):
    """Readiness-gate 503 that must keep the demand lease for retry."""


_MULTIPART_TYPED_ERROR_CODES = frozenset(
    {
        "description_service_starting",
        "description_service_unavailable",
        "description_service_error",
        "operation_mismatch",
        "operation_expired",
    }
)


def _typed_describe_error(
    *,
    status_code: int,
    code: str,
    message: str,
    timing: DescribeTiming,
    operation_id: str | None = None,
    startup_id: str | None = None,
    warmup_eta_seconds: float | None = None,
    startup_budget_seconds: float | None = None,
    reason: UnavailableReason | None = None,
    lifecycle_reason: str | None = None,
    retry_after: int | None = None,
    preserve_lease: bool = False,
) -> HTTPException:
    if code == "description_service_starting" and startup_budget_seconds is None:
        startup_budget_seconds = DescriptionSettings().gpu_warmup_timeout_seconds
    if code == "description_service_unavailable" and reason is None:
        reason = UnavailableReason.STATE_MISSING
    detail = DescribeOperationErrorDetail(
        code=code,
        message=message,
        operation_id=operation_id,
        startup_id=startup_id,
        timing=timing,
        warmup_eta_seconds=warmup_eta_seconds,
        startup_budget_seconds=startup_budget_seconds,
        reason=reason,
        lifecycle_reason=lifecycle_reason,
    ).model_dump(mode="json")
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    exc_cls = _LifecycleHoldHTTPException if preserve_lease else HTTPException
    return exc_cls(status_code=status_code, detail=detail, headers=headers)


def _http_exception_code(detail: Any) -> str | None:
    if not isinstance(detail, dict):
        return None
    code = detail.get("code")
    return code if isinstance(code, str) else None


def _http_exception_message(detail: Any, *, fallback: str) -> str:
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message:
            return message
    if isinstance(detail, str) and detail:
        return detail
    return fallback


def _retry_after_header(exc: HTTPException) -> int | None:
    if not exc.headers:
        return None
    raw = exc.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value


def _plain_typed_error_missing_operation_fields(exc: HTTPException) -> bool:
    """True when a post-accept typed-error code lacks the multipart envelope."""
    if isinstance(exc, _LifecycleHoldHTTPException):
        return False
    detail = exc.detail
    code = _http_exception_code(detail)
    if code not in _MULTIPART_TYPED_ERROR_CODES:
        return False
    if not isinstance(detail, dict):
        return True
    return any(key not in detail for key in ("operation_id", "startup_id", "timing"))


def _rebuild_post_accept_typed_error(
    exc: HTTPException,
    *,
    op,
    server_start: float,
) -> HTTPException:
    detail = exc.detail
    code = _http_exception_code(detail)
    if code not in _MULTIPART_TYPED_ERROR_CODES:
        return exc
    warmup_eta_seconds = None
    startup_budget_seconds = None
    reason = None
    lifecycle_reason = None
    retry_after = None
    if isinstance(detail, dict) and code == "description_service_starting":
        eta = detail.get("warmup_eta_seconds")
        if isinstance(eta, (int, float)) and not isinstance(eta, bool) and math.isfinite(eta):
            warmup_eta_seconds = float(eta)
        budget = detail.get("startup_budget_seconds")
        if isinstance(budget, (int, float)) and not isinstance(budget, bool) and math.isfinite(budget) and budget > 0:
            startup_budget_seconds = float(budget)
        retry_after = _retry_after_header(exc)
    elif isinstance(detail, dict) and code == "description_service_unavailable":
        raw_reason = detail.get("reason")
        if isinstance(raw_reason, str):
            try:
                reason = UnavailableReason(raw_reason)
            except ValueError:
                reason = None
        raw_lifecycle = detail.get("lifecycle_reason")
        if isinstance(raw_lifecycle, str) and raw_lifecycle.strip():
            lifecycle_reason = raw_lifecycle
    return _typed_describe_error(
        status_code=exc.status_code,
        code=code,
        message=_http_exception_message(detail, fallback="Description service error"),
        operation_id=op.operation_id,
        startup_id=op.startup_id,
        timing=_untimed_with_elapsed(_elapsed_ms(server_start)),
        warmup_eta_seconds=warmup_eta_seconds,
        startup_budget_seconds=startup_budget_seconds,
        reason=reason,
        lifecycle_reason=lifecycle_reason,
        retry_after=retry_after,
    )


def _load_gpu_snapshot_payload() -> dict[str, Any] | None:
    path = Path(resolve_gpu_state_path())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _gpu_snapshot_fields(payload: dict[str, Any] | None = None) -> tuple[str | None, float | None]:
    if payload is None:
        payload = _load_gpu_snapshot_payload()
    if payload is None:
        return None, None
    instance_id = payload.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id.strip() or len(instance_id) > 128:
        instance_id = None
    else:
        instance_id = instance_id.strip()
    since = payload.get("since")
    if isinstance(since, bool) or not isinstance(since, (int, float)) or not math.isfinite(since):
        since = None
    return instance_id, since


def _max_lease_reached(payload: dict[str, Any] | None = None) -> bool:
    if payload is None:
        payload = _load_gpu_snapshot_payload()
    return isinstance(payload, dict) and payload.get("last_transition_reason") == _MAX_LEASE_REASON


def _snapshot_written_at_valid(payload: dict[str, Any]) -> bool:
    written_at = payload.get("written_at")
    return not isinstance(written_at, bool) and isinstance(written_at, (int, float)) and math.isfinite(written_at)


def _snapshot_is_stale(payload: dict[str, Any], *, now: float) -> bool:
    written_at = payload.get("written_at")
    if not _snapshot_written_at_valid(payload):
        return False
    written_at_f = float(written_at)
    if written_at_f - now > GPU_STATE_FUTURE_SKEW_SECONDS:
        return True
    return now - written_at_f > resolve_gpu_state_stale_seconds()


def _lifecycle_reason_from_snapshot(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    reason = payload.get("reason")
    if isinstance(reason, str) and reason.strip():
        return reason
    return None


def _unavailable_from_gpu_gate(
    *,
    now: datetime,
    settings: DescriptionSettings,
    state: GpuState,
    payload: dict[str, Any] | None,
) -> tuple[UnavailableReason | None, str | None]:
    if _stop_requested(now=now):
        return UnavailableReason.OPERATOR_STOP, None
    if not settings.gpu_endpoint_url:
        return UnavailableReason.ENDPOINT_UNCONFIGURED, None
    if payload is None:
        return UnavailableReason.STATE_MISSING, None
    if not _snapshot_written_at_valid(payload):
        return UnavailableReason.STATE_MISSING, None
    if _snapshot_is_stale(payload, now=now.timestamp()):
        return UnavailableReason.STATE_STALE, None
    if state is GpuState.DEGRADED:
        return UnavailableReason.DEGRADED, _lifecycle_reason_from_snapshot(payload)
    if state is GpuState.UNKNOWN:
        return UnavailableReason.STATE_MISSING, None
    if _max_lease_reached(payload):
        return UnavailableReason.DEGRADED, None
    return None, None


def _stop_requested(*, now: datetime) -> bool:
    intent = read_gpu_intent(resolve_gpu_intent_path())
    return intent is not None and intent.action is IntentAction.STOP and utc_observation(intent.expires_at) > now


def _retry_after_seconds(eta: float | None) -> int:
    if eta is None or not math.isfinite(eta) or eta <= 0:
        return 15
    return min(_PUBLIC_RETRY_AFTER_CEILING, max(1, int(math.ceil(eta))))


def _warmup_eta_seconds(*, state: GpuState, since: float | None, now: float, warmup_timeout: float) -> float | None:
    if state is GpuState.STOPPED:
        return warmup_timeout
    if state in (GpuState.STARTING, GpuState.WARMING) and since is not None:
        return max(0.0, warmup_timeout - max(0.0, now - since))
    return None


def _untimed_with_elapsed(server_elapsed_ms: float | None) -> DescribeTiming:
    return DescribeTiming(
        queue_ms=None,
        ramp_up_ms=None,
        processing_ms=None,
        startup_ms=None,
        server_elapsed_ms=server_elapsed_ms,
    )


class _PreflightMissCacheRepository(ImageDescriptionRepository):
    """Skip VisualFactsService's first cache read after a GPU preflight miss.

    Only the pre-compute lookup is suppressed. Later ``get_by_cache_key`` calls
    (duplicate-key recovery in ``insert_or_get_existing``) delegate.
    """

    def __init__(self, inner: ImageDescriptionRepository) -> None:
        session = getattr(inner, "_session", None)
        if session is not None:
            super().__init__(session)
        else:
            self._session = None  # type: ignore[assignment]
        self._inner = inner
        self._preflight_miss_consumed = False

    async def get_by_cache_key(self, **kwargs: Any) -> Any:
        if not self._preflight_miss_consumed:
            self._preflight_miss_consumed = True
            return None
        return await self._inner.get_by_cache_key(**kwargs)


async def _validated_describe_multipart_submission(
    *,
    form: FormData,
    auth,
    settings: DescriptionSettings,
) -> ValidatedDescribeMultipart | Response:
    try:
        envelope = DescribeImageEnvelope.model_validate(_read_request_part(form.get("request")))
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid 'request' envelope: {exc.errors()}"
        ) from exc

    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if auth_tenant and auth_tenant != envelope.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant mismatch between auth and request envelope")

    # E20-FUSION decorative/eligibility gate — server backstop; WP is primary skip.
    # Ordered AFTER auth/tenant validation (S3A-05) but before any inference and
    # image byte validation, so decorative images never spend GPU/CPU on
    # description. Logged so a misbehaving WP client that POSTs decorative
    # images at volume stays observable.
    if envelope.decorative:
        _logger.info(
            "decorative image skipped: tenant_id=%s media_id=%s",
            envelope.tenant_id,
            envelope.media_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    image_parts = [(k, v) for k, v in form.multi_items() if k.startswith(_IMAGE_KEY_PREFIX)]
    if len(image_parts) != 1:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"exactly one image_<media_id> part is required; got {len(image_parts)}",
        )
    key, value = image_parts[0]
    if not isinstance(value, UploadFile):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"form key '{key}' must be a file upload")
    if key[len(_IMAGE_KEY_PREFIX) :] != str(envelope.media_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"image part key '{key}' must be the canonical 'image_{envelope.media_id}'",
        )

    image_bytes = await _read_validated_image_upload(value=value, key=key, settings=settings)
    context = (
        envelope.context_pack.model_dump(exclude_none=True) if envelope.context_pack is not None else envelope.context
    )
    return ValidatedDescribeMultipart(
        envelope=envelope,
        tenant_uuid=uuid.UUID(envelope.tenant_id),
        image_bytes=image_bytes,
        context=context,
        operation_id=_optional_operation_id(form),
    )


async def _read_validated_image_upload(
    *,
    value: UploadFile,
    key: str,
    settings: DescriptionSettings,
) -> bytes:
    content_type = value.content_type or ""
    if content_type not in settings.allowed_description_mime_types:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"unsupported image content-type '{content_type}'")
    image_bytes = await value.read()
    if not image_bytes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"image part '{key}' is empty")
    if len(image_bytes) > settings.max_description_image_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"image exceeds the description size cap ({settings.max_description_image_bytes} bytes)",
        )
    return image_bytes


def _job_result_from_item(*, run_id: uuid.UUID, item) -> DescribeJobResult:
    """Project a single-run item row into the unchanged ``DescribeJobResult`` wire shape."""
    status = describe_job_status(item)
    tier = getattr(item, "tier", None)
    return DescribeJobResult(
        job_id=str(run_id),
        status=status.value,
        tier=tier,
        result_generation=int(getattr(item, "result_generation", 0) or 0),
        visual_facts=getattr(item, "visual_facts", None),
        error=describe_job_error(item),
    )


_TERMINAL_POLL_STATUSES = frozenset(
    {
        DescribeJobStatus.FINAL,
        DescribeJobStatus.DEGRADED,
        DescribeJobStatus.FAILED,
    }
)


async def _rescope(session: AsyncSession | None, tenant_uuid: uuid.UUID) -> None:
    if session is not None:
        await set_tenant_context(session, tenant_uuid)


async def _commit_and_rescope(session: AsyncSession | None, tenant_uuid: uuid.UUID) -> None:
    if session is None:
        return
    await session.commit()
    await set_tenant_context(session, tenant_uuid)


def _operation_repo(session: AsyncSession) -> DescribeOperationRepository:
    return DescribeOperationRepository(session, lease_seconds=_lease_seconds())


def _elapsed_ms(start: float) -> float:
    return max(0.0, (time.perf_counter() - start) * 1000)


def _timing_from_operation(
    *, op, processing_ms: float | None, server_elapsed_ms: float | None, cached: bool
) -> DescribeTiming:
    if cached:
        return DescribeTiming(
            queue_ms=None,
            ramp_up_ms=0,
            processing_ms=0,
            startup_ms=None,
            server_elapsed_ms=server_elapsed_ms,
        )
    ramp_up = 0 if op is None else op.ramp_up_ms
    startup_ms = None if op is None else op.startup_ms
    queue_ms = None if op is None else op.queue_ms
    return DescribeTiming(
        queue_ms=queue_ms,
        ramp_up_ms=ramp_up,
        processing_ms=processing_ms,
        startup_ms=startup_ms,
        server_elapsed_ms=server_elapsed_ms,
    )


async def _cached_gpu_description_row(
    *,
    repository: ImageDescriptionRepository | None,
    tenant_uuid: uuid.UUID,
    image_bytes: bytes,
    context: Mapping[str, Any] | None,
    adapter,
    server_start: float,
):
    """Look up the GPU description cache before accepting a demand lease."""
    if repository is None:
        return None
    try:
        return await repository.get_by_cache_key(
            tenant_id=tenant_uuid,
            image_hash=compute_image_hash(image_bytes),
            adapter=adapter.kind.value,
            model_id=adapter.model_id,
            model_version=adapter.model_version,
            prompt_or_task_version=adapter.prompt_or_task_version,
            context_hash=compute_context_hash(context),
        )
    except HTTPException:
        raise
    except Exception:
        _logger.error("gpu description cache lookup failed", exc_info=True)
        raise _typed_describe_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="description_service_unavailable",
            message="Description service is unavailable",
            operation_id=None,
            startup_id=None,
            timing=_untimed_with_elapsed(_elapsed_ms(server_start)),
            reason=UnavailableReason.STATE_MISSING,
        )


async def _accept_operation(
    *,
    session: AsyncSession | None,
    tenant_uuid: uuid.UUID,
    digest: str,
    operation_id: str | None,
    gpu_compute: bool,
    server_start: float,
) -> tuple[Any, str | None]:
    if session is None:
        if gpu_compute:
            raise _typed_describe_error(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="description_service_unavailable",
                message="Description service is unavailable",
                timing=_untimed_with_elapsed(_elapsed_ms(server_start)),
                operation_id=None,
                startup_id=None,
                reason=UnavailableReason.STATE_MISSING,
            )
        # CPU/hosted/default stay usable without demand when the DB is down.
        return None, None
    repo = _operation_repo(session)
    try:
        op = await repo.accept(tenant_id=tenant_uuid, request_digest=digest, operation_id=operation_id)
        if not gpu_compute:
            await repo.observe_ready(tenant_id=tenant_uuid, operation_id=op.operation_id)
            await repo.complete(tenant_id=tenant_uuid, operation_id=op.operation_id)
        await _commit_and_rescope(session, tenant_uuid)
        return op, op.operation_id
    except OperationMismatchError as exc:
        raise _typed_describe_error(
            status_code=status.HTTP_409_CONFLICT,
            code=OperationMismatchError.code,
            message=str(exc) or "operation does not match this tenant and request",
            operation_id=None,
            startup_id=None,
            timing=_untimed_with_elapsed(_elapsed_ms(server_start)),
        ) from exc
    except OperationExpiredError as exc:
        # get_optional_session skips commit on HTTPException; persist rejection first.
        await _commit_and_rescope(session, tenant_uuid)
        raise _typed_describe_error(
            status_code=status.HTTP_410_GONE,
            code=OperationExpiredError.code,
            message=str(exc) or "operation expired; start a new operation",
            operation_id=operation_id,
            startup_id=None,
            timing=_untimed_with_elapsed(_elapsed_ms(server_start)),
        ) from exc
    except HTTPException:
        raise
    except Exception:
        await session.rollback()
        await set_tenant_context(session, tenant_uuid)
        if gpu_compute:
            _logger.error("operation accept failed", exc_info=True)
        else:
            _logger.warning(
                "non-GPU operation persistence skipped; failing closed without a durable operation",
                exc_info=True,
            )
        raise _typed_describe_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="description_service_unavailable",
            message="Description service is unavailable",
            operation_id=None,
            startup_id=None,
            timing=_untimed_with_elapsed(_elapsed_ms(server_start)),
            reason=UnavailableReason.STATE_MISSING,
        )


async def _ensure_gpu_ready(
    *,
    session: AsyncSession,
    tenant_uuid: uuid.UUID,
    op,
    settings: DescriptionSettings,
    session_factory: async_sessionmaker[AsyncSession] | None,
    server_start: float,
) -> None:
    now = datetime.now(UTC)
    payload = _load_gpu_snapshot_payload()
    state = read_gpu_state(now=now.timestamp())
    instance_id, since = _gpu_snapshot_fields(payload)
    reason, lifecycle_reason = _unavailable_from_gpu_gate(
        now=now,
        settings=settings,
        state=state,
        payload=payload,
    )
    blocked = reason is not None
    waiting = state in (GpuState.STOPPED, GpuState.STARTING, GpuState.WARMING)
    repo = _operation_repo(session)
    # Warm READY arrivals must not join a startup; only waits through
    # STARTING/WARMING (or STOPPED auto-start) carry startup_id + ramp_up_ms.
    if instance_id is not None and not blocked and waiting:
        started_at = datetime.fromtimestamp(since, tz=UTC) if since is not None else None
        try:
            op = await repo.associate_startup(
                tenant_id=tenant_uuid,
                operation_id=op.operation_id,
                startup_id=instance_id,
                started_at=started_at,
                now=now,
            )
        except ValueError:
            _logger.debug("startup association skipped", exc_info=True)
        await _commit_and_rescope(session, tenant_uuid)
    timing = _untimed_with_elapsed(_elapsed_ms(server_start))
    startup_id = op.startup_id
    if blocked:
        await dump_load_snapshot(session_factory)
        raise _typed_describe_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="description_service_unavailable",
            message="Description service is unavailable",
            operation_id=op.operation_id,
            startup_id=startup_id,
            timing=timing,
            reason=reason,
            lifecycle_reason=lifecycle_reason,
            preserve_lease=True,
        )
    if state in (GpuState.STOPPED, GpuState.STARTING, GpuState.WARMING):
        eta = _warmup_eta_seconds(
            state=state,
            since=since,
            now=now.timestamp(),
            warmup_timeout=settings.gpu_warmup_timeout_seconds,
        )
        await dump_load_snapshot(session_factory)
        raise _typed_describe_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="description_service_starting",
            message="Description service is starting",
            operation_id=op.operation_id,
            startup_id=startup_id,
            timing=timing,
            warmup_eta_seconds=eta,
            startup_budget_seconds=settings.gpu_warmup_timeout_seconds,
            retry_after=_retry_after_seconds(eta),
            preserve_lease=True,
        )
    if state is GpuState.READY:
        await repo.observe_ready(tenant_id=tenant_uuid, operation_id=op.operation_id, now=now)
        await _commit_and_rescope(session, tenant_uuid)
        await dump_load_snapshot(session_factory)
        return
    await dump_load_snapshot(session_factory)
    raise _typed_describe_error(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="description_service_unavailable",
        message="Description service is unavailable",
        operation_id=op.operation_id,
        startup_id=startup_id,
        timing=timing,
        reason=UnavailableReason.STATE_MISSING,
        preserve_lease=True,
    )


async def _complete_operation(
    *,
    session: AsyncSession | None,
    tenant_uuid: uuid.UUID,
    op,
    processing_ms: float | None,
    server_elapsed_ms: float | None,
    gpu_compute: bool,
    cached: bool,
) -> Any:
    if session is None or op is None:
        return op
    repo = _operation_repo(session)
    try:
        if op.first_ready_at is None:
            # Cache hits never wait on GPU ready; still terminalize the lease.
            await repo.observe_ready(tenant_id=tenant_uuid, operation_id=op.operation_id)
        completed = await repo.complete(
            tenant_id=tenant_uuid,
            operation_id=op.operation_id,
            processing_ms=0 if cached else processing_ms,
            server_elapsed_ms=server_elapsed_ms,
        )
        await _commit_and_rescope(session, tenant_uuid)
        return completed
    except HTTPException:
        raise
    except Exception:
        operation_id = op.operation_id
        startup_id = op.startup_id
        _logger.error("operation complete failed operation_id=%s", operation_id, exc_info=True)
        await session.rollback()
        await set_tenant_context(session, tenant_uuid)
        raise _typed_describe_error(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="description_service_error",
            message="Description service error",
            operation_id=operation_id,
            startup_id=startup_id,
            timing=_untimed_with_elapsed(server_elapsed_ms),
        )


def _preserves_demand_lease(exc: HTTPException) -> bool:
    """Keep demand only for the readiness gate's own lifecycle 503."""
    return isinstance(exc, _LifecycleHoldHTTPException) and exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


async def _release_unready_operation(
    *,
    session: AsyncSession,
    tenant_uuid: uuid.UUID,
    op,
    server_elapsed_ms: float | None,
    caller_ready: bool,
) -> None:
    """Release demand without fabricating a readiness observation.

    Re-reads the operation row and lease together under row locks. If this
    request never observed ready but a concurrent writer did, leave the lease
    active so the ready request can finish (CON-02).
    """
    now = datetime.now(UTC)
    identity = sa_inspect(op).identity
    if identity is None:
        return
    locked = await session.get(
        DescribeOperation,
        identity,
        populate_existing=True,
        with_for_update=True,
    )
    lease = await session.get(
        DescribeDemandLease,
        identity,
        populate_existing=True,
        with_for_update=True,
    )
    if locked is None or lease is None or lease.state != DemandLeaseState.ACTIVE:
        return
    if not caller_ready and locked.first_ready_at is not None:
        return
    lease.state = DemandLeaseState.COMPLETED
    locked.completed_at = now
    if server_elapsed_ms is not None:
        locked.server_elapsed_ms = server_elapsed_ms
    await _commit_and_rescope(session, tenant_uuid)


async def _terminalize_accepted_operation(
    *,
    session: AsyncSession | None,
    tenant_uuid: uuid.UUID,
    op,
    server_elapsed_ms: float | None,
    gpu_compute: bool,
    caller_ready: bool,
) -> None:
    del gpu_compute
    if session is None or op is None:
        return
    operation_id = sa_inspect(op).identity[1] if sa_inspect(op).identity is not None else "?"
    try:
        await _release_unready_operation(
            session=session,
            tenant_uuid=tenant_uuid,
            op=op,
            server_elapsed_ms=server_elapsed_ms,
            caller_ready=caller_ready,
        )
    except Exception:
        _logger.error("failed to terminalize operation_id=%s", operation_id, exc_info=True)


async def _response_from_cached_row(
    *,
    service: VisualFactsService,
    cached_row,
    server_start: float,
    media_id: int,
    context: Mapping[str, Any] | None,
    confirmed_faces,
    naming_policy,
    tenant_uuid: uuid.UUID,
) -> VisualFactsServiceResult:
    cache_response = service._cache_hit_response(
        cached_row,
        start=server_start,
        media_id=media_id,
        context=context,
        confirmed_faces=confirmed_faces,
        naming_policy=naming_policy,
    )
    await service._record_cache_hit(
        tenant_id=tenant_uuid,
        media_id=media_id,
        image_hash=cached_row.image_hash,
    )
    return VisualFactsServiceResult(
        **cache_response.model_dump(),
        attempt_timing=AdapterAttemptTiming(processing_ms=0),
    )


@router.post(
    "/describe/multipart",
    response_model=MultipartDescribeResponse,
    responses={204: {"description": "Decorative image skipped; no description generated."}},
)
async def describe_image_multipart(
    request: Request,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
    adapter=Depends(get_description_adapter),
) -> MultipartDescribeResponse | Response:
    server_start = time.perf_counter()
    form = await request.form()
    settings = DescriptionSettings()
    submission = await _validated_describe_multipart_submission(form=form, auth=auth, settings=settings)
    # E20-FUSION decorative gate short-circuits validation with a 204 Response.
    # Zero-compute: do not charge demo quota (DS2B-PM-S2-01).
    if isinstance(submission, Response):
        return submission
    envelope = submission.envelope
    image_bytes = submission.image_bytes
    tenant_uuid = submission.tenant_uuid
    repository = None
    audit_sink = None
    tenant_record = None
    if session is not None:
        # RLS: scope the session to the tenant before any read/write on
        # image_descriptions — both the cache SELECT (USING) and the INSERT
        # (WITH CHECK) filter on app.current_tenant. Mirrors the tenant-scoped
        # recognition routes (e.g. clusters.py).
        await set_tenant_context(session, tenant_uuid)
        # Surface an unprovisioned tenant as the structured 403, not an FK 500.
        tenant_record = await require_tenant_record(session, tenant_uuid)
        repository = ImageDescriptionRepository(session)
        audit_sink = _DescriptionAuditSink(AuditRepository(session))
    # Faces + policy once: Stage-2 fusion needs them for identity attach
    # provenance; Stage-3 naming preview reuses the same inputs (E20-FUSION-S3-BR-01).
    confirmed_faces, naming_policy = await _load_fusion_naming_inputs(
        session=session,
        tenant=tenant_record,
        tenant_uuid=tenant_uuid,
        media_id=envelope.media_id,
        image_bytes=image_bytes,
    )
    if envelope.tier == "gpu":
        effective_adapter = get_gpu_description_adapter()
    elif envelope.tier == "cpu":
        effective_adapter = get_cpu_description_adapter()
    else:
        effective_adapter = adapter
    gpu_compute = effective_adapter.kind is DescriptionAdapterKind.GPU
    digest = _multipart_request_digest(media_id=envelope.media_id, image_bytes=image_bytes, context=submission.context)
    cached_row = None
    op = None
    if gpu_compute:
        cached_row = await _cached_gpu_description_row(
            repository=repository,
            tenant_uuid=tenant_uuid,
            image_bytes=image_bytes,
            context=submission.context,
            adapter=effective_adapter,
            server_start=server_start,
        )
    op, operation_id = await _accept_operation(
        session=session,
        tenant_uuid=tenant_uuid,
        digest=digest,
        operation_id=submission.operation_id,
        gpu_compute=gpu_compute,
        server_start=server_start,
    )
    session_factory = worker_session_factory(session) if session is not None else None
    effective_timeout = _generation_timeout_seconds(settings, effective_adapter)
    describe_repository = repository
    if gpu_compute and cached_row is None and repository is not None:
        describe_repository = _PreflightMissCacheRepository(repository)
    service = VisualFactsService(
        adapter=effective_adapter,
        repository=describe_repository,
        audit_sink=audit_sink,
        metrics=_DescriptionMetricsSink(),
        generation_timeout_seconds=effective_timeout,
        profile=settings.profile,
    )

    async def _charge_demo_quota() -> None:
        # Durable consume at real-compute dispatch; cache hits never call this.
        await maybe_consume_demo_quota(auth, session, units=1)
        await _rescope(session, tenant_uuid)

    observed_ready_here = False

    async def _before_compute() -> None:
        nonlocal observed_ready_here
        if gpu_compute:
            if session is None or op is None:
                raise _typed_describe_error(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    code="description_service_unavailable",
                    message="Description service is unavailable",
                    operation_id=None,
                    startup_id=None,
                    timing=_untimed_with_elapsed(_elapsed_ms(server_start)),
                    reason=UnavailableReason.STATE_MISSING,
                )
            await _ensure_gpu_ready(
                session=session,
                tenant_uuid=tenant_uuid,
                op=op,
                settings=settings,
                session_factory=session_factory,
                server_start=server_start,
            )
            observed_ready_here = True
        await _charge_demo_quota()

    terminalized = False

    async def _cleanup_accepted() -> None:
        nonlocal terminalized
        if terminalized:
            return
        await _terminalize_accepted_operation(
            session=session,
            tenant_uuid=tenant_uuid,
            op=op,
            server_elapsed_ms=_elapsed_ms(server_start),
            gpu_compute=gpu_compute,
            caller_ready=observed_ready_here,
        )
        terminalized = True

    try:
        if cached_row is not None:
            response = await _response_from_cached_row(
                service=service,
                cached_row=cached_row,
                server_start=server_start,
                media_id=envelope.media_id,
                context=submission.context,
                confirmed_faces=confirmed_faces,
                naming_policy=naming_policy,
                tenant_uuid=tenant_uuid,
            )
        else:
            response = await service.describe(
                tenant_id=tenant_uuid,
                media_id=envelope.media_id,
                image_bytes=image_bytes,
                context=submission.context,
                confirmed_faces=confirmed_faces,
                naming_policy=naming_policy,
                before_compute=_before_compute,
            )
        # HARM-02: derive positional naming from the Stage-2 decision — identities
        # whose fact was dropped must not be named by the fallback.
        preview_faces = _faces_for_naming_preview(confirmed_faces, service.last_attachments, service.last_phrase_boxes)
        named_draft, naming_provenance = await _naming_preview(
            session=session,
            tenant=tenant_record,
            tenant_uuid=tenant_uuid,
            media_id=envelope.media_id,
            image_bytes=image_bytes,
            generic_draft=response.alt_text_draft,
            # Adapter output on generation; restored from the cached row on cache
            # hits — both paths yield the same named draft (E19-4A-S4-BR-03).
            phrase_boxes=service.last_phrase_boxes,
            confirmed_faces=preview_faces,
            naming_policy=naming_policy,
        )
        response = response.model_copy(
            update={
                "generic_draft": response.alt_text_draft,
                "named_draft": named_draft,
                "naming_provenance": naming_provenance,
            }
        )
        server_elapsed_ms = _elapsed_ms(server_start)
        processing_ms = response.attempt_timing.processing_ms
        try:
            completed = await _complete_operation(
                session=session,
                tenant_uuid=tenant_uuid,
                op=op,
                processing_ms=processing_ms,
                server_elapsed_ms=server_elapsed_ms,
                gpu_compute=gpu_compute,
                cached=response.cached,
            )
            terminalized = True
        except HTTPException:
            await _cleanup_accepted()
            raise
        if session is not None:
            await session.commit()
        if completed is not None and completed.ramp_up_ms is not None:
            service.record_readiness_wait(completed.ramp_up_ms)
        elif not gpu_compute or response.cached:
            service.record_readiness_wait(0)
        startup_id = None if completed is None else completed.startup_id
        if response.cached:
            startup_id = None
        timing = _timing_from_operation(
            op=completed,
            processing_ms=processing_ms,
            server_elapsed_ms=server_elapsed_ms,
            cached=response.cached,
        )
        dumped = response.model_dump(exclude={"operation_id", "startup_id", "timing", "attempt_timing"})
        accepted = completed if completed is not None else op
        if accepted is None:
            # CPU/hosted with no session: compute still runs, but there is no
            # durable DescribeOperation to advertise.
            if gpu_compute:
                raise RuntimeError("gpu describe succeeded without an accepted operation")
            return MultipartDescribeResponse(
                **dumped,
                startup_id=startup_id,
                timing=timing,
            )
        return MultipartDescribeResponse(
            **dumped,
            operation_id=accepted.operation_id,
            startup_id=startup_id,
            timing=timing,
        )
    except HTTPException as exc:
        if not _preserves_demand_lease(exc):
            await _cleanup_accepted()
        if op is not None and _plain_typed_error_missing_operation_fields(exc):
            raise _rebuild_post_accept_typed_error(exc, op=op, server_start=server_start) from exc
        raise
    except TimeoutError as exc:
        await _cleanup_accepted()
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT,
            f"description generation exceeded {effective_timeout}s",
        ) from exc
    except DescriptionAdapterUnavailableError as exc:
        await _cleanup_accepted()
        if gpu_compute:
            adapter_reason = (
                UnavailableReason.ENDPOINT_UNCONFIGURED
                if not settings.gpu_endpoint_url
                else UnavailableReason.ENDPOINT_NOT_PRIVATE
            )
            raise _typed_describe_error(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="description_service_unavailable",
                message=str(exc),
                operation_id=operation_id,
                startup_id=None if op is None else op.startup_id,
                timing=_untimed_with_elapsed(_elapsed_ms(server_start)),
                reason=adapter_reason,
            ) from exc
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except (GpuRemoteAdapterError, HostedProviderError) as exc:
        processing_ms = getattr(getattr(exc, "attempt_timing", None), "processing_ms", None)
        server_elapsed_ms = _elapsed_ms(server_start)
        if gpu_compute:
            try:
                completed = await _complete_operation(
                    session=session,
                    tenant_uuid=tenant_uuid,
                    op=op,
                    processing_ms=processing_ms,
                    server_elapsed_ms=server_elapsed_ms,
                    gpu_compute=True,
                    cached=False,
                )
                terminalized = True
            except HTTPException:
                await _cleanup_accepted()
                raise
            timing = _timing_from_operation(
                op=completed,
                processing_ms=processing_ms,
                server_elapsed_ms=server_elapsed_ms,
                cached=False,
            )
            raise _typed_describe_error(
                status_code=status.HTTP_502_BAD_GATEWAY,
                code="description_service_error",
                message=str(exc),
                operation_id=operation_id,
                startup_id=None if completed is None else completed.startup_id,
                timing=timing,
            ) from exc
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except Exception as exc:
        await _cleanup_accepted()
        raise _typed_describe_error(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="description_service_error",
            message="Description service error",
            operation_id=operation_id,
            startup_id=None if op is None else op.startup_id,
            timing=_untimed_with_elapsed(_elapsed_ms(server_start)),
        ) from exc


async def _with_bypass_session(session_factory: async_sessionmaker[AsyncSession], op):
    """Run ``op(session)`` on a dedicated short-lived RLS-bypassed session."""
    async with session_factory() as bypass_session:
        await enable_rls_bypass(bypass_session)
        result = await op(bypass_session)
        await bypass_session.commit()
        return result


async def _maybe_purge_expired_single_runs(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Opportunistic retention sweep on a dedicated bypass session (design (d))."""
    try:

        async def _purge(session) -> None:
            await DescribeRunRepository(session).purge_expired_single_runs()

        await _with_bypass_session(session_factory, _purge)
    except Exception:  # noqa: BLE001 - purge is best-effort at enqueue
        _logger.debug("purge_expired_single_runs failed", exc_info=True)


@router.post(
    "/describe/async",
    response_model=DescribeJobResult,
    responses={204: {"description": "Decorative image skipped; no description enqueued."}},
)
async def enqueue_describe_image(
    background_tasks: BackgroundTasks,
    request: Request,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
    cpu_adapter=Depends(get_description_adapter),
    # Async GPU-final tier: the only place the N-pass ensemble may run (VLM4-RA-BR-02).
    gpu_adapter=Depends(get_async_gpu_description_adapter),
) -> DescribeJobResult | Response:
    form = await request.form()
    settings = DescriptionSettings()
    submission = await _validated_describe_multipart_submission(form=form, auth=auth, settings=settings)
    # Decorative / zero-compute short-circuit: never charge (DS2B-PM-S2-01).
    if isinstance(submission, Response):
        return submission
    # VLMFIX-S1-06 / design (f): empty claim always 400 (env bypass deleted).
    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if not auth_tenant:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "tenant claim required")
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database session unavailable")

    await set_tenant_context(session, submission.tenant_uuid)
    await require_tenant_record(session, submission.tenant_uuid)
    # Charge when real async compute is about to be enqueued (durable).
    await maybe_consume_demo_quota(auth, session, units=1)
    await set_tenant_context(session, submission.tenant_uuid)

    image_len = len(submission.image_bytes)
    refusal = _ASYNC_ADMISSION.try_acquire(image_len)
    if refusal is not None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, refusal)

    session_factory = worker_session_factory(session)
    audit_sink = _BackgroundDescriptionAuditSink(session_factory)
    metrics = _DescriptionMetricsSink()
    try:
        repo = DescribeRunRepository(session)
        run_id = await repo.create_single_run(
            tenant_id=submission.tenant_uuid,
            media_id=submission.envelope.media_id,
            image_bytes=submission.image_bytes,
            created_by_user_id=getattr(auth, "user_id", None),
        )
        await session.commit()
    except HTTPException:
        _ASYNC_ADMISSION.release(image_len)
        raise
    except Exception as exc:
        # Paired release on any create/commit failure [RES-04]; surface 500 not 200.
        _ASYNC_ADMISSION.release(image_len)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "describe job enqueue failed",
        ) from exc

    await _maybe_purge_expired_single_runs(session_factory)
    await dump_load_snapshot(session_factory)

    background_tasks.add_task(
        _run_async_describe_job_and_release,
        tenant_id=submission.tenant_uuid,
        run_id=run_id,
        session_factory=session_factory,
        cpu_adapter=cpu_adapter,
        gpu_adapter=gpu_adapter,
        # One provisional pass + however many GPU-final passes the adapter
        # makes (ensemble: n_views; raw: 1 -> preserves the original 2x budget)
        # so N-view jobs cannot time out by construction (VLM4-RC-BR-01) [RES-02].
        job_timeout_seconds=settings.generation_timeout_seconds * (1 + getattr(gpu_adapter, "n_passes", 1)),
        audit_sink=audit_sink,
        metrics=metrics,
        context=submission.context,
        image_len=image_len,
    )

    item = await repo.get_single_run_item(tenant_id=submission.tenant_uuid, run_id=run_id)
    if item is None:  # pragma: no cover - defensive only
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "describe job was not persisted")
    return _job_result_from_item(run_id=run_id, item=item)


async def _run_async_describe_job_and_release(
    *,
    image_len: int,
    session_factory: async_sessionmaker[AsyncSession],
    **kwargs,
) -> None:
    try:
        await run_async_describe_job(session_factory=session_factory, **kwargs)
    except Exception:  # noqa: BLE001 - never leak reservation; log and finish
        _logger.exception(
            "async describe job failed tenant_id=%s run_id=%s",
            kwargs.get("tenant_id"),
            kwargs.get("run_id"),
        )
    finally:
        _ASYNC_ADMISSION.release(image_len)
        await dump_load_snapshot(session_factory)


@router.get("/describe/jobs/{job_id}", response_model=DescribeJobResult)
async def get_describe_job(
    job_id: str,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
) -> DescribeJobResult:
    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if not auth_tenant:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "tenant claim required")
    try:
        run_id = uuid.UUID(job_id)
        tenant_id = uuid.UUID(auth_tenant)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe job not found") from exc
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database session unavailable")

    await set_tenant_context(session, tenant_id)
    repo = DescribeRunRepository(session)
    run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
    if run is None or run.run_kind != RunKind.SINGLE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe job not found")
    item = await repo.get_single_run_item(tenant_id=tenant_id, run_id=run_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe job not found")

    result = _job_result_from_item(run_id=run_id, item=item)
    if describe_job_status(item) in _TERMINAL_POLL_STATUSES:
        await dump_load_snapshot(worker_session_factory(session))
    return result
