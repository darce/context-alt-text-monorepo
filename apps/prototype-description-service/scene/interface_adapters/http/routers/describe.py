"""POST /scene/describe/multipart — one-image synchronous seeded description (E19-1 S5).

Reuses recognition's auth + optional-session deps and the multipart ``request``
envelope + single ``image_<media_id>`` part contract, but runs synchronously
(the seeded adapter is instant) and reads the image bytes directly — no
ObjectStore staging, which is the S9 ``local_cpu`` async path. Mounted at
``/scene`` in api/main.py.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from threading import Lock
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import FormData, UploadFile

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
from scene.application.describe_load import load_snapshot, resolve_load_path, write_load_snapshot
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.description_repository import ImageDescriptionRepository
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
from scene.application.visual_facts_service import VisualFactsService
from scene.config.settings import DescriptionSettings
from scene.domain.describe_run import (
    DescribeJobStatus,
    RunKind,
    describe_job_error,
    describe_job_status,
)
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.provider.hosted_provider_adapter import HostedProviderError
from scene.infrastructure.vlm.unavailable_adapter import DescriptionAdapterUnavailableError
from scene.interface_adapters.http.deps import (
    get_async_gpu_description_adapter,
    get_cpu_description_adapter,
    get_description_adapter,
    get_gpu_description_adapter,
)
from scene.interface_adapters.http.schemas.requests import DescribeImageEnvelope
from scene.interface_adapters.http.schemas.responses import DescribeJobResult, VisualFactsResponse

router = APIRouter(tags=["describe"])

_logger = logging.getLogger(__name__)

_IMAGE_KEY_PREFIX = "image_"
# Defaults match the former volatile store (256 MiB retained / 1000 jobs).
_DEFAULT_MAX_PENDING_JOBS = 1000
_DEFAULT_MAX_RETAINED_IMAGE_BYTES = 256 * 1024 * 1024


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


@router.post(
    "/describe/multipart",
    response_model=VisualFactsResponse,
    responses={204: {"description": "Decorative image skipped; no description generated."}},
)
async def describe_image_multipart(
    request: Request,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
    adapter=Depends(get_description_adapter),
) -> VisualFactsResponse | Response:
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
    effective_timeout = _generation_timeout_seconds(settings, effective_adapter)
    service = VisualFactsService(
        adapter=effective_adapter,
        repository=repository,
        audit_sink=audit_sink,
        metrics=_DescriptionMetricsSink(),
        generation_timeout_seconds=effective_timeout,
        profile=settings.profile,
    )

    async def _charge_demo_quota() -> None:
        # Durable consume at real-compute dispatch; cache hits never call this.
        await maybe_consume_demo_quota(auth, session, units=1)
        if session is not None:
            # Commit ends SET LOCAL tenant context; re-scope for cache/persist.
            await set_tenant_context(session, tenant_uuid)

    try:
        response = await service.describe(
            tenant_id=tenant_uuid,
            media_id=envelope.media_id,
            image_bytes=image_bytes,
            context=submission.context,
            confirmed_faces=confirmed_faces,
            naming_policy=naming_policy,
            before_compute=_charge_demo_quota,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT,
            f"description generation exceeded {effective_timeout}s",
        ) from exc
    except DescriptionAdapterUnavailableError as exc:
        # A deferred/stub profile (florence_large, gpu_phi4) or a missing [vlm]
        # extra: surface an actionable 503 instead of an opaque 500.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except HostedProviderError as exc:
        # Upstream hosted-provider fault (key missing, provider 5xx/timeout,
        # malformed body): 502 keeps the fail-closed contract actionable.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
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
    if session is not None:
        await session.commit()
    return response


async def _with_bypass_session(session_factory: async_sessionmaker[AsyncSession], op):
    """Run ``op(session)`` on a dedicated short-lived RLS-bypassed session."""
    async with session_factory() as bypass_session:
        await enable_rls_bypass(bypass_session)
        result = await op(bypass_session)
        await bypass_session.commit()
        return result


async def _maybe_dump_describe_load(session_factory: async_sessionmaker[AsyncSession] | None) -> None:
    """Best-effort DB-derived load write for the GPU idle reaper (VLMFIX-S2-01)."""
    if session_factory is None:
        return
    path = resolve_load_path()
    try:

        async def _write(session) -> None:
            snap = await load_snapshot(session)
            write_load_snapshot(snap, path)

        await _with_bypass_session(session_factory, _write)
    except Exception:  # noqa: BLE001 - reaper snapshot is best-effort
        _logger.debug("describe load snapshot write failed path=%s", path, exc_info=True)


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
    await _maybe_dump_describe_load(session_factory)

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
        await _maybe_dump_describe_load(session_factory)


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
        await _maybe_dump_describe_load(worker_session_factory(session))
    return result
