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
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import ValidationError
from starlette.datastructures import FormData, UploadFile

from db.tenant_context import require_tenant_record, set_tenant_context
from recognition.infrastructure.repositories.audit_repository import AuditRepository
from recognition.interface_adapters.http.deps import (
    get_optional_session,
    require_write_access,
)
from recognition.interface_adapters.http.middleware.metrics import get_default_metrics
from scene.application.describe_jobs import DescribeJob, DescribeJobStatus, InMemoryDescribeJobStore
from scene.application.description_repository import ImageDescriptionRepository
from scene.application.description_worker import run_describe_job
from scene.application.fusion.reconcile import (
    Attachment,
    AttachmentDecision,
    FactSource,
)
from scene.application.identity_merge import (
    NamingPolicy,
    NamingProvenance,
    NamingSkipReason,
    load_confirmed_faces,
    load_suppressed_roster_ids,
    merge_identities,
)
from scene.application.settings.vlm import VlmSettings
from scene.application.visual_facts_service import VisualFactsService
from scene.config.settings import DescriptionSettings
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.provider.hosted_provider_adapter import HostedProviderError
from scene.infrastructure.vlm.unavailable_adapter import DescriptionAdapterUnavailableError
from scene.interface_adapters.http.deps import (
    get_cpu_description_adapter,
    get_description_adapter,
    get_gpu_description_adapter,
)
from scene.interface_adapters.http.schemas.requests import DescribeImageEnvelope
from scene.interface_adapters.http.schemas.responses import DescribeJobResult, VisualFactsResponse
from scene.interface_adapters.http.schemas.responses import (
    InjectedName as InjectedNameModel,
)
from scene.interface_adapters.http.schemas.responses import (
    NamingProvenance as NamingProvenanceModel,
)

router = APIRouter(tags=["describe"])

_logger = logging.getLogger(__name__)

_IMAGE_KEY_PREFIX = "image_"
_DEFAULT_MAX_JOBS = 1000
# Independent of job-count capacity: bound resident image payload so a burst of
# max-size uploads hits 503 before process OOM (VLMRP-S4-07). Count-cap alone
# still allows ~max_jobs * max_image_bytes (~25 GiB at defaults).
_MAX_RETAINED_IMAGE_SLOTS = 8


def _async_job_store() -> InMemoryDescribeJobStore:
    settings = DescriptionSettings()
    return InMemoryDescribeJobStore(
        max_jobs=_DEFAULT_MAX_JOBS,
        max_retained_image_bytes=_MAX_RETAINED_IMAGE_SLOTS * settings.max_description_image_bytes,
    )


_ASYNC_JOBS = _async_job_store()


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


def _image_dimensions(image_bytes: bytes) -> tuple[int, int] | None:
    from io import BytesIO

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(image_bytes)) as img:
            return img.size
    except (UnidentifiedImageError, OSError):
        return None


def _provenance_model(provenance) -> NamingProvenanceModel:
    return NamingProvenanceModel(
        injected_names=[
            InjectedNameModel(
                name=n.name,
                cluster_id=str(n.cluster_id),
                roster_id=str(n.roster_id) if n.roster_id is not None else None,
                detection_confidence=n.detection_confidence,
            )
            for n in provenance.injected_names
        ],
        naming_allowed=provenance.naming_allowed,
        reason=str(provenance.reason) if provenance.reason is not None else None,
        mode=str(provenance.mode) if provenance.mode is not None else None,
    )


async def _load_fusion_naming_inputs(
    *,
    session,
    tenant,
    tenant_uuid: uuid.UUID,
    media_id: int,
    image_bytes: bytes,
) -> tuple[list, NamingPolicy | None]:
    """Load detector faces + naming policy once for fusion Stage-2 and naming preview."""
    if session is None or tenant is None:
        return [], None
    dims = _image_dimensions(image_bytes)
    if dims is None:
        return [], None
    try:
        faces = await load_confirmed_faces(
            session,
            tenant_id=tenant_uuid,
            media_id=media_id,
            image_width=dims[0],
            image_height=dims[1],
        )
        policy = NamingPolicy(
            agreement_enabled=tenant.naming_agreement_enabled,
            suppressed_roster_ids=await load_suppressed_roster_ids(session, tenant_id=tenant_uuid),
        )
        return list(faces), policy
    except Exception:  # noqa: BLE001 - fusion degrades without faces; naming has its own guard
        _logger.exception("failed loading faces/policy for media_id=%s; fusion uses empty faces", media_id)
        return [], None


async def _naming_preview(
    *,
    session,
    tenant,
    tenant_uuid: uuid.UUID,
    media_id: int,
    image_bytes: bytes,
    generic_draft: str,
    phrase_boxes,
    confirmed_faces=None,
    naming_policy: NamingPolicy | None = None,
) -> tuple[str, NamingProvenanceModel]:
    """Compute the named preview draft (E19-4a). Draft-only — never writes alt text.

    ``phrase_boxes`` are the caption-grounding boxes (S4) — adapter output on
    generation, restored from the persisted cache row on hits. Empty for
    adapters without grounding, where naming degrades to the positional
    fallback when eligible.

    When ``confirmed_faces`` / ``naming_policy`` are provided (shared with
    Stage-2 fusion), they are reused so faces are not double-loaded.
    """
    if session is None or tenant is None:
        return generic_draft, _provenance_model(
            NamingProvenance(naming_allowed=False, reason=NamingSkipReason.DB_UNAVAILABLE)
        )
    try:
        if confirmed_faces is None or naming_policy is None:
            dims = _image_dimensions(image_bytes)
            if dims is None:
                return generic_draft, _provenance_model(
                    NamingProvenance(naming_allowed=False, reason=NamingSkipReason.IMAGE_UNREADABLE)
                )
            faces = await load_confirmed_faces(
                session,
                tenant_id=tenant_uuid,
                media_id=media_id,
                image_width=dims[0],
                image_height=dims[1],
            )
            policy = NamingPolicy(
                agreement_enabled=tenant.naming_agreement_enabled,
                suppressed_roster_ids=await load_suppressed_roster_ids(session, tenant_id=tenant_uuid),
            )
        else:
            # Preloaded path: still require readable image for naming eligibility.
            if _image_dimensions(image_bytes) is None:
                return generic_draft, _provenance_model(
                    NamingProvenance(naming_allowed=False, reason=NamingSkipReason.IMAGE_UNREADABLE)
                )
            faces = confirmed_faces
            policy = naming_policy
        result = merge_identities(
            caption=generic_draft,
            phrase_boxes=list(phrase_boxes),
            confirmed_faces=faces,
            policy=policy,
        )
        return result.named_draft, _provenance_model(result.provenance)
    except Exception:  # noqa: BLE001 - preview must never break the core describe response
        _logger.exception("naming preview failed for media_id=%s; degrading to generic draft", media_id)
        return generic_draft, _provenance_model(
            NamingProvenance(naming_allowed=False, reason=NamingSkipReason.MERGE_ERROR)
        )


def _faces_for_naming_preview(
    confirmed_faces: list,
    attachments: tuple[Attachment, ...],
    phrase_boxes,
) -> list:
    """HARM-02: keep Stage-3 positional naming consistent with Stage-2 drops.

    With no phrase boxes, ``merge_identities`` falls back to positional naming
    of every eligible face — including identities whose ContextPack fact
    Stage-2 just dropped, which would make ``named_draft`` contradict
    ``attachment_provenance``. Stage-2 is the single decision point: faces
    whose identity fact was dropped never reach the positional fallback.
    Grounded mode (boxes present) already mirrors Stage-2's own merge, so it
    is left untouched.
    """
    if phrase_boxes or not attachments or not confirmed_faces:
        return confirmed_faces
    # fact_id formats are canonical in reconcile._identity_fact_id:
    # "identity:cluster:<id>" / "identity:id:<id>" / "identity:<idx>:<name>".
    dropped: set[tuple[str, str]] = set()
    for a in attachments:
        if a.fact_source is FactSource.IDENTITY and a.decision is AttachmentDecision.DROPPED:
            parts = a.fact_id.split(":", 2)
            if len(parts) == 3 and parts[1] in ("cluster", "id"):
                dropped.add((parts[1], parts[2]))
    if not dropped:
        return confirmed_faces
    return [
        f
        for f in confirmed_faces
        if ("cluster", str(f.cluster_id)) not in dropped and ("id", str(f.identity_id)) not in dropped
    ]


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


def _job_result(job: DescribeJob) -> DescribeJobResult:
    return DescribeJobResult(
        job_id=job.job_id,
        status=job.status.value,
        tier=job.tier,
        result_generation=job.result_generation,
        visual_facts=job.visual_facts,
        error=job.error,
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
    try:
        response = await service.describe(
            tenant_id=tenant_uuid,
            media_id=envelope.media_id,
            image_bytes=image_bytes,
            context=submission.context,
            confirmed_faces=confirmed_faces,
            naming_policy=naming_policy,
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


def _maybe_dump_describe_load() -> None:
    """Best-effort write of job-store load for the GPU idle reaper (VLMFIX-S2-01)."""
    import os
    from pathlib import Path as _Path

    path = os.environ.get("ACX_DESCRIBE_LOAD_PATH", "/run/acx/describe-load.json")
    try:
        _ASYNC_JOBS.write_load_snapshot(_Path(path))
    except OSError:
        _logger.debug("describe load snapshot write failed path=%s", path, exc_info=True)


@router.post("/describe/async", response_model=DescribeJobResult)
async def enqueue_describe_image(
    background_tasks: BackgroundTasks,
    request: Request,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
    cpu_adapter=Depends(get_description_adapter),
    gpu_adapter=Depends(get_gpu_description_adapter),
) -> DescribeJobResult:
    form = await request.form()
    settings = DescriptionSettings()
    submission = await _validated_describe_multipart_submission(form=form, auth=auth, settings=settings)
    # VLMFIX-S1-06: async jobs are poll-fetched by tenant claim; empty claim
    # would enqueue unfetchable work. Require claim unless admin opt-in.
    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if not auth_tenant and os.environ.get("ACX_ASYNC_ALLOW_EMPTY_TENANT_CLAIM") != "1":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "tenant claim required")
    if session is not None:
        await set_tenant_context(session, submission.tenant_uuid)
        await require_tenant_record(session, submission.tenant_uuid)
    audit_sink = None
    if session is not None:
        # Own session factory — request-scoped session is closed before BackgroundTasks (S1-01).
        from db.session import async_session_factory

        audit_sink = _BackgroundDescriptionAuditSink(async_session_factory)
    metrics = _DescriptionMetricsSink()
    try:
        job = _ASYNC_JOBS.enqueue(
            tenant_id=submission.tenant_uuid,
            media_id=submission.envelope.media_id,
            image_bytes=submission.image_bytes,
            context=submission.context,
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    _maybe_dump_describe_load()
    background_tasks.add_task(
        _run_describe_job_and_dump_load,
        store=_ASYNC_JOBS,
        job_id=job.job_id,
        cpu_adapter=cpu_adapter,
        gpu_adapter=gpu_adapter,
        job_timeout_seconds=settings.generation_timeout_seconds * 2,
        audit_sink=audit_sink,
        metrics=metrics,
    )
    if session is not None:
        await session.commit()
    return _job_result(job)


async def _run_describe_job_and_dump_load(**kwargs) -> None:
    try:
        await run_describe_job(**kwargs)
    finally:
        _maybe_dump_describe_load()


@router.get("/describe/jobs/{job_id}", response_model=DescribeJobResult)
async def get_describe_job(job_id: str, auth=Depends(require_write_access)) -> DescribeJobResult:
    job = _ASYNC_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe job not found")
    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if not auth_tenant:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "tenant claim required")
    if auth_tenant != str(job.tenant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe job not found")
    if job.status in {DescribeJobStatus.FINAL, DescribeJobStatus.DEGRADED, DescribeJobStatus.FAILED}:
        fetched = _ASYNC_JOBS.mark_result_fetched(job_id)
        if fetched is None:
            # Evicted between get() and mark (S1-05) — surface 404 not 500.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "describe job not found")
        job = fetched
        _maybe_dump_describe_load()
    return _job_result(job)
