"""POST /scene/describe/multipart — one-image synchronous seeded description (E19-1 S5).

Reuses recognition's auth + optional-session deps and the multipart ``request``
envelope + single ``image_<media_id>`` part contract, but runs synchronously
(the seeded adapter is instant) and reads the image bytes directly — no
ObjectStore staging, which is the S9 ``local_cpu`` async path. Mounted at
``/scene`` in api/main.py.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from db.tenant_context import set_tenant_context
from recognition.interface_adapters.http.dependencies import (
    get_optional_session,
    require_write_access,
)
from scene.application.description_repository import ImageDescriptionRepository
from scene.application.visual_facts_service import VisualFactsService
from scene.config.settings import DescriptionSettings
from scene.interface_adapters.http.deps import get_description_adapter
from scene.interface_adapters.http.schemas.requests import DescribeImageEnvelope
from scene.interface_adapters.http.schemas.responses import VisualFactsResponse

router = APIRouter(tags=["describe"])

_IMAGE_KEY_PREFIX = "image_"


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
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"invalid 'request' envelope: {exc.errors()}") from exc

    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if auth_tenant and auth_tenant != envelope.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant mismatch between auth and request envelope")

    image_parts = [(k, v) for k, v in form.multi_items() if k.startswith(_IMAGE_KEY_PREFIX)]
    if len(image_parts) != 1:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"exactly one image_<media_id> part is required; got {len(image_parts)}",
        )
    key, value = image_parts[0]
    if not isinstance(value, UploadFile):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"form key '{key}' must be a file upload")
    try:
        part_media_id = int(key[len(_IMAGE_KEY_PREFIX) :])
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"form key '{key}' has a non-integer media_id suffix"
        ) from exc
    if part_media_id != envelope.media_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"media_id {envelope.media_id} does not match image part suffix {part_media_id}",
        )

    settings = DescriptionSettings()
    content_type = value.content_type or ""
    if content_type not in settings.allowed_description_mime_types:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"unsupported image content-type '{content_type}'"
        )
    image_bytes = await value.read()
    if not image_bytes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"image part '{key}' is empty")

    repository = None
    if session is not None:
        # RLS: scope the session to the tenant before any read/write on
        # image_descriptions — both the cache SELECT (USING) and the INSERT
        # (WITH CHECK) filter on app.current_tenant. Mirrors the tenant-scoped
        # recognition routes (e.g. clusters.py).
        await set_tenant_context(session, uuid.UUID(envelope.tenant_id))
        repository = ImageDescriptionRepository(session)
    service = VisualFactsService(adapter=adapter, repository=repository)
    response = await service.describe(
        tenant_id=uuid.UUID(envelope.tenant_id),
        media_id=envelope.media_id,
        image_bytes=image_bytes,
        context=envelope.context,
    )
    if session is not None and not response.cached:
        await session.commit()
    return response
