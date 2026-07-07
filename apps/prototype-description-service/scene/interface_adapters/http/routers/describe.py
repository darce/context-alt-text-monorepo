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
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from db.tenant_context import require_tenant_record, set_tenant_context
from recognition.infrastructure.repositories.audit_repository import AuditRepository
from recognition.interface_adapters.http.deps import (
    get_optional_session,
    require_write_access,
)
from recognition.interface_adapters.http.middleware.metrics import get_default_metrics
from scene.application.description_repository import ImageDescriptionRepository
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
from scene.interface_adapters.http.deps import get_description_adapter
from scene.interface_adapters.http.schemas.requests import DescribeImageEnvelope
from scene.interface_adapters.http.schemas.responses import (
    InjectedName as InjectedNameModel,
)
from scene.interface_adapters.http.schemas.responses import (
    NamingProvenance as NamingProvenanceModel,
)
from scene.interface_adapters.http.schemas.responses import VisualFactsResponse

router = APIRouter(tags=["describe"])

_logger = logging.getLogger(__name__)

_IMAGE_KEY_PREFIX = "image_"


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


async def _naming_preview(
    *,
    session,
    tenant,
    tenant_uuid: uuid.UUID,
    media_id: int,
    image_bytes: bytes,
    generic_draft: str,
    phrase_boxes,
) -> tuple[str, NamingProvenanceModel]:
    """Compute the named preview draft (E19-4a). Draft-only — never writes alt text.

    ``phrase_boxes`` are the caption-grounding boxes (S4) — adapter output on
    generation, restored from the persisted cache row on hits. Empty for
    adapters without grounding, where naming degrades to the positional
    fallback when eligible.
    """
    if session is None or tenant is None:
        return generic_draft, _provenance_model(
            NamingProvenance(naming_allowed=False, reason=NamingSkipReason.DB_UNAVAILABLE)
        )
    try:
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


def _generation_timeout_seconds(settings: DescriptionSettings, adapter) -> float:
    if adapter.kind is DescriptionAdapterKind.LOCAL_CPU:
        return VlmSettings().inference_timeout_seconds
    return settings.generation_timeout_seconds


@router.post("/describe/multipart", response_model=VisualFactsResponse)
async def describe_image_multipart(
    request: Request,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
    adapter=Depends(get_description_adapter),
) -> VisualFactsResponse:
    form = await request.form()

    try:
        envelope = DescribeImageEnvelope.model_validate(_read_request_part(form.get("request")))
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid 'request' envelope: {exc.errors()}"
        ) from exc

    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if auth_tenant and auth_tenant != envelope.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant mismatch between auth and request envelope")

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

    settings = DescriptionSettings()
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

    tenant_uuid = uuid.UUID(envelope.tenant_id)
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
    effective_timeout = _generation_timeout_seconds(settings, adapter)
    service = VisualFactsService(
        adapter=adapter,
        repository=repository,
        audit_sink=audit_sink,
        metrics=_DescriptionMetricsSink(),
        generation_timeout_seconds=effective_timeout,
    )
    try:
        response = await service.describe(
            tenant_id=tenant_uuid,
            media_id=envelope.media_id,
            image_bytes=image_bytes,
            context=envelope.context_pack.model_dump(exclude_none=True)
            if envelope.context_pack is not None
            else envelope.context,
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
