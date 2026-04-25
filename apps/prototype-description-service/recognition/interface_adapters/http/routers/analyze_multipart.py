"""Multipart variant of POST /recognition/analyze (E15-11).

Slice 1.4a only ships the pure ``multipart_to_media_items`` helper that
parses a Starlette ``FormData`` into ``MediaItem`` instances with their
``blob_uri`` populated via the request-scoped ``ObjectStore``. The route
handler that wires the helper into FastAPI lands in Slice 1.4b.

Form-key contract:

- ``request`` (optional) — JSON-encoded request envelope (tenant_id +
  metadata). Reserved here; consumed by the route handler in 1.4b.
- ``image_<media_id>`` — one upload per image. ``<media_id>`` must parse
  as an integer; the part's ``content-type`` must be one of the allowed
  image MIME types.

Anything that doesn't match the ``image_`` prefix is left to the route
handler to interpret. The helper is deliberately ignorant of the JSON
envelope so it can be tested in isolation.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from starlette.datastructures import FormData, UploadFile

from recognition.application.storage import ObjectStore, ObjectStoreError
from recognition.domain.job import JobType
from recognition.interface_adapters.http.dependencies import (
    get_optional_session,
    get_scan_queue_service_factory,
    get_scan_queue_service_optional,
    require_write_access,
)
from recognition.interface_adapters.http.deps.object_store import (
    get_object_store_for_request,
)
from recognition.interface_adapters.http.schemas.requests import MediaItem
from recognition.interface_adapters.http.schemas.responses import (
    JobProgressResponse,
    JobStatusResponse,
)

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_MIME_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/png", "image/webp"})
_IMAGE_KEY_PREFIX = "image_"


def multipart_to_media_items(
    *,
    form_data: FormData,
    object_store: ObjectStore,
    job_id: str,
    allowed_mime_types: Iterable[str] | None = None,
) -> list[MediaItem]:
    """Convert image parts in ``form_data`` to ``MediaItem``s with blob_uri.

    The helper iterates ``form_data`` in the order returned by Starlette's
    parser, persists each image part through ``object_store.put`` under
    ``job_id``, and returns one ``MediaItem`` per part. Non-image keys
    (e.g. the ``request`` JSON envelope) are ignored so the route handler
    can consume them separately.

    Raises:
        HTTPException: 415 for an unsupported MIME type, 422 for a
            zero-byte image part, 400 for a key whose ``media_id``
            suffix is not a valid integer, and 500 for an unexpected
            ``ObjectStoreError`` (which generally indicates an
            out-of-band misconfiguration since the helper validated the
            inputs first).
    """
    allowed = frozenset(allowed_mime_types) if allowed_mime_types is not None else _DEFAULT_ALLOWED_MIME_TYPES

    items: list[MediaItem] = []
    for key, value in form_data.multi_items():
        if not key.startswith(_IMAGE_KEY_PREFIX):
            continue
        if not isinstance(value, UploadFile):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"form key '{key}' must be a file upload, not a string",
            )

        media_id_str = key[len(_IMAGE_KEY_PREFIX) :]
        try:
            media_id = int(media_id_str)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"form key '{key}' has a non-integer media_id suffix '{media_id_str}'"),
            ) from exc

        content_type = value.content_type or ""
        if content_type not in allowed:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"image part '{key}' has unsupported content-type '{content_type}'; allowed: {sorted(allowed)}"
                ),
            )

        data = value.file.read()
        if not data:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"image part '{key}' is empty",
            )

        try:
            blob_uri = object_store.put(job_id=job_id, media_id=str(media_id), data=data)
        except ObjectStoreError as exc:
            # The helper's validation should have prevented this; surface
            # as 500 so it shows up in logs rather than masquerading as a
            # client error.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"failed to store image part '{key}': {exc}",
            ) from exc

        items.append(MediaItem(media_id=media_id, blob_uri=blob_uri))

    return items


# -----------------------------------------------------------------------------
# Route handler (Slice 1.4d)
# -----------------------------------------------------------------------------


router = APIRouter(tags=["analyze"])


def _extract_request_envelope(form_data: FormData) -> dict:
    """Pull the JSON ``request`` part out of the multipart form."""
    raw = form_data.get("request")
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "multipart submission must include a 'request' part with a "
                "JSON envelope (at minimum {'tenant_id': '<uuid>'})"
            ),
        )
    if isinstance(raw, UploadFile):
        body = raw.file.read()
    elif isinstance(raw, (bytes, bytearray)):
        body = bytes(raw)
    elif isinstance(raw, str):
        body = raw.encode("utf-8")
    else:  # pragma: no cover - Starlette never returns other types
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported 'request' part type",
        )
    try:
        envelope = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'request' part is not valid JSON: {exc}",
        ) from exc
    if not isinstance(envelope, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'request' part must decode to a JSON object",
        )
    return envelope


@router.post(
    "/analyze/multipart",
    response_model=JobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_media_multipart(
    request: Request,
    background_tasks: BackgroundTasks,  # noqa: ARG001 - reserved for S1.4e dispatch wiring
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
    scan_queue=Depends(get_scan_queue_service_optional),
    object_store=Depends(get_object_store_for_request),
) -> JobStatusResponse:
    """Multipart variant of /recognition/analyze for inline image upload.

    Form contract:

    - ``request`` part: JSON envelope, currently ``{"tenant_id": <uuid>}``.
    - ``image_<media_id>`` parts: one upload per image.

    Each image part is written through the request-scoped ``ObjectStore``
    under ``<blob_root>/<auth.tenant_claim>/<job_id>/<media_id>.bin``;
    the resulting ``blob_uri`` is attached to the queued ``MediaItem``s.
    The job_id is pre-generated and persisted via
    ``scan_queue.create_scan_job_record(job_id=...)`` so the on-disk
    layout matches the DB row.

    Background-task scheduling is wired in Slice 1.4e; this slice closes
    the upload + job-record path so the route is callable end to end
    without spinning up the worker.
    """
    pre_generated_job_id = uuid.uuid4()

    form_data = await request.form()
    envelope = _extract_request_envelope(form_data)

    tenant_id_raw = envelope.get("tenant_id")
    if not tenant_id_raw or not isinstance(tenant_id_raw, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'request' JSON must include a non-empty 'tenant_id' string",
        )
    try:
        tenant_uuid = uuid.UUID(tenant_id_raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'tenant_id' must be a UUID: {exc}",
        ) from exc

    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if auth_tenant and auth_tenant != tenant_id_raw:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant mismatch between auth and request envelope",
        )

    media_items_list = multipart_to_media_items(
        form_data=form_data,
        object_store=object_store,
        job_id=str(pre_generated_job_id),
    )
    if not media_items_list:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=("multipart submission must include at least one image_<media_id> part"),
        )

    if scan_queue is None:
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable",
            )
        scan_queue = get_scan_queue_service_factory(session)

    persisted_job_id = await scan_queue.create_scan_job_record(
        tenant_id=tenant_uuid,
        total=len(media_items_list),
        job_id=pre_generated_job_id,
        created_by_user_id=getattr(auth, "user_id", None),
    )

    if session is not None:
        await session.commit()

    progress = JobProgressResponse(
        completed=0,
        total=len(media_items_list),
        phase="queued",
        images_processed=0,
        faces_found=0,
    )
    return JobStatusResponse(
        id=str(persisted_job_id),
        type=JobType.ANALYZE.value,
        status="pending",
        progress=progress,
        started_at=datetime.now(tz=UTC),
        finished_at=None,
        message=f"Queueing 0/{len(media_items_list)} items",
    )
