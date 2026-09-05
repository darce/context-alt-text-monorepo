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
import os
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import parse_options_header
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from db.tenant_context import require_tenant_record
from recognition.application.scan.capability import require_scan_dispatch_ready
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.storage import ObjectStore
from recognition.application.tasks.scan import chain_populate_and_process
from recognition.domain.job import JobPhase, JobStatus, JobType
from recognition.interface_adapters.http.deps import (
    get_optional_session,
    get_scan_queue_service_factory,
    get_scan_queue_service_optional,
    require_write_access,
)
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from recognition.interface_adapters.http.deps.object_store import (
    ObjectStoreFactory,
    get_object_store_factory_for_request,
)
from recognition.interface_adapters.http.middleware.correlation import (
    get_correlation_id,
)
from recognition.interface_adapters.http.schemas.requests import MediaItem
from recognition.interface_adapters.http.schemas.responses import (
    JobProgressResponse,
    JobStatusResponse,
)
from recognition.shared.db.dialect import is_postgres

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_MIME_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/png", "image/webp"})
_IMAGE_KEY_PREFIX = "image_"
_MAX_IMAGE_PARTS = 5
_MAX_MULTIPART_FILES = _MAX_IMAGE_PARTS + 1  # JSON request envelope may itself be an UploadFile.
_TOO_MANY_IMAGE_PARTS_DETAIL = f"multipart submission accepts at most {_MAX_IMAGE_PARTS} image parts"
_INVALID_MULTIPART_DETAIL = "invalid multipart form"


class _ClosingMultiPartParser(MultiPartParser):
    """Close partial upload spools for every parser failure, including disconnects."""

    _current_image_files = 0

    def on_headers_finished(self) -> None:
        """Reject an oversized image batch before allocating its next spool."""
        _disposition, options = parse_options_header(self._current_part.content_disposition)
        field_name = options.get(b"name")
        if (
            b"filename" in options
            and field_name is not None
            and field_name.startswith(_IMAGE_KEY_PREFIX.encode("ascii"))
        ):
            self._current_image_files += 1
            if self._current_image_files > _MAX_IMAGE_PARTS:
                raise MultiPartException(_TOO_MANY_IMAGE_PARTS_DETAIL)
        super().on_headers_finished()

    async def parse(self) -> FormData:
        parsed_form: FormData | None = None
        try:
            parsed_form = await super().parse()
            return parsed_form
        finally:
            # Starlette 0.52.1 closes these only for MultiPartException. Other
            # failures (including ClientDisconnect) can strand every spool, and
            # clean EOF can omit an unfinished UploadFile from the FormData that
            # the route later closes. Keep only files represented in a successful
            # parse; the parser still owns and closes every other allocation.
            retained_files = (
                tuple(value.file for _, value in parsed_form.multi_items() if isinstance(value, UploadFile))
                if parsed_form is not None
                else ()
            )
            for file in self._files_to_close_on_error:
                if not any(file is retained_file for retained_file in retained_files):
                    file.close()


async def _parse_multipart_form(request: Request) -> FormData:
    """Parse a bounded multipart form while retaining ownership of partial spools."""
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        return await request.form(max_files=_MAX_MULTIPART_FILES)

    parser = _ClosingMultiPartParser(
        request.headers,
        request.stream(),
        max_files=_MAX_MULTIPART_FILES,
    )
    try:
        return await parser.parse()
    except (MultiPartException, FormParserError) as exc:
        detail = exc.message if isinstance(exc, MultiPartException) else _INVALID_MULTIPART_DETAIL
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc


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
            suffix is not a valid integer, a duplicate ``media_id``, or
            a batch larger than five images.
        ObjectStoreError: Propagated after cleaning the job prefix so the
            shared exception handler can produce the standard opaque 500
            envelope and correlated server-side traceback.
    """
    allowed = frozenset(allowed_mime_types) if allowed_mime_types is not None else _DEFAULT_ALLOWED_MIME_TYPES

    validated_parts: list[tuple[int, bytes]] = []
    seen_media_ids: set[int] = set()
    for key, value in form_data.multi_items():
        if not key.startswith(_IMAGE_KEY_PREFIX):
            continue
        if len(validated_parts) >= _MAX_IMAGE_PARTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_TOO_MANY_IMAGE_PARTS_DETAIL,
            )
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

        if media_id in seen_media_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"duplicate image part for media_id '{media_id}'",
            )
        seen_media_ids.add(media_id)

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
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"image part '{key}' is empty",
            )

        validated_parts.append((media_id, data))

    items: list[MediaItem] = []
    try:
        for media_id, data in validated_parts:
            blob_uri = object_store.put(job_id=job_id, media_id=str(media_id), data=data)
            items.append(MediaItem(media_id=media_id, blob_uri=blob_uri))
    except Exception:
        try:
            object_store.cleanup(job_id=job_id)
        except Exception:
            logger.exception(
                "Failed to clean up multipart image writes",
                extra={
                    "correlation_id": get_correlation_id(),
                    "job_id": job_id,
                },
            )
        raise

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
    background_tasks: BackgroundTasks,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
    scan_queue=Depends(get_scan_queue_service_optional),
    object_store_factory: ObjectStoreFactory = Depends(get_object_store_factory_for_request),
    _demo_quota=Depends(enforce_demo_quota),
) -> JobStatusResponse:
    """Multipart variant of /recognition/analyze for inline image upload.

    Form contract:

    - ``request`` part: JSON envelope, currently ``{"tenant_id": <uuid>}``.
    - ``image_<media_id>`` parts: one upload per image.

    The ObjectStore is constructed from the request envelope's ``tenant_id``
    via ``object_store_factory`` AFTER the auth/envelope tenant-mismatch
    check has run. This lets admin keys (``auth.tenant_claim is None``)
    target any tenant while tenant-scoped keys remain pinned to their own
    tenant — a tenant-scoped key whose envelope claims a different tenant
    is rejected with 403 before any blob is written.

    Each image part is written through the resulting ``ObjectStore``
    under ``<blob_root>/<envelope.tenant_id>/<job_id>/<media_id>.bin``;
    the resulting ``blob_uri`` is attached to the queued ``MediaItem``s.
    The job_id is pre-generated and persisted via
    ``scan_queue.create_scan_job_record(job_id=...)`` so the on-disk
    layout matches the DB row.

    Failure path: blobs are written to ObjectStore BEFORE the scan job
    row is committed, so any error during persistence is followed by
    object_store.cleanup(job_id=...) to avoid leaking orphans the worker
    could never reach (no DB row would exist for cleanup-by-job_id).

    Dispatch: on success the route schedules
    ``chain_populate_and_process`` as a BackgroundTask, mirroring the JSON
    /recognition/analyze flow so the scan worker has queue items to claim.
    """
    form_data = await _parse_multipart_form(request)
    try:
        return await _analyze_media_multipart_form(
            form_data=form_data,
            background_tasks=background_tasks,
            auth=auth,
            session=session,
            scan_queue=scan_queue,
            object_store_factory=object_store_factory,
        )
    finally:
        await form_data.close()


async def _analyze_media_multipart_form(
    *,
    form_data: FormData,
    background_tasks: BackgroundTasks,
    auth,
    session,
    scan_queue,
    object_store_factory: ObjectStoreFactory,
) -> JobStatusResponse:
    """Validate, persist, and dispatch an already-parsed multipart request."""
    pre_generated_job_id = uuid.uuid4()
    envelope = _extract_request_envelope(form_data)

    tenant_id_raw = envelope.get("tenant_id")
    if not tenant_id_raw or not isinstance(tenant_id_raw, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="'request' JSON must include a non-empty 'tenant_id' string",
        )
    try:
        tenant_uuid = uuid.UUID(tenant_id_raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"'tenant_id' must be a UUID: {exc}",
        ) from exc

    # Normalize to the canonical UUID form once. uuid.UUID accepts uppercase /
    # mixed-case input but str() always returns lowercase canonical, which is
    # the form auth.tenant_claim carries (from the api_keys row) and the form
    # the BackgroundTask rebuilds the store with. Comparing against, binding
    # the store with, or logging the raw envelope string would cause off-by-
    # case mismatches: a 403 against a same-but-uppercase tenant claim, blobs
    # written under an uppercase prefix the rebuilt lowercase-bound store
    # cannot open or clean up, and split telemetry across two casings.
    canonical_tenant_id = str(tenant_uuid)

    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if auth_tenant and auth_tenant != canonical_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant mismatch between auth and request envelope",
        )

    inline_processing = os.environ.get("RECOGNITION_ASYNC_ANALYZE_INLINE", "0") == "1"
    if session is not None and hasattr(session, "execute") and is_postgres(session):
        await require_tenant_record(session, tenant_uuid)
        await require_scan_dispatch_ready(session, inline_processing=inline_processing)

    object_store = object_store_factory(canonical_tenant_id)

    media_items_list = multipart_to_media_items(
        form_data=form_data,
        object_store=object_store,
        job_id=str(pre_generated_job_id),
    )
    if not media_items_list:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=("multipart submission must include at least one image_<media_id> part"),
        )

    if scan_queue is None:
        if session is None:
            # Blobs were just written for this pre_generated_job_id; roll them
            # back so a misconfigured deployment does not leak orphans (BR-06).
            object_store.cleanup(job_id=str(pre_generated_job_id))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable",
            )
        scan_queue = get_scan_queue_service_factory(session)

    # BR-06: blobs are already on disk under the pre_generated_job_id path.
    # Any failure between here and the scheduled background task must roll
    # them back, otherwise the worker can never discover the orphans (no DB
    # row exists for cleanup-by-job_id to find later).
    persistence_committed = False
    try:
        persisted_job_id = await scan_queue.create_scan_job_record(
            tenant_id=tenant_uuid,
            total=len(media_items_list),
            job_id=pre_generated_job_id,
            created_by_user_id=getattr(auth, "user_id", None),
        )
        if session is not None:
            await session.commit()
        persistence_committed = True
    finally:
        if not persistence_committed:
            object_store.cleanup(job_id=str(pre_generated_job_id))

    # BR-05: schedule the populate + process pipeline so the scan worker has
    # queue items to claim. Mirror the JSON /analyze flow's dispatch shape.
    media_sources = [item.blob_uri for item in media_items_list]
    media_items_tuples: list[tuple[int, str]] = [(item.media_id, item.blob_uri) for item in media_items_list]
    media_ids = [str(item.media_id) for item in media_items_list]

    session_factory = None
    if session is not None and getattr(session, "bind", None) is not None and not is_postgres(session):
        session_factory = async_sessionmaker(bind=session.bind, expire_on_commit=False)

    # E15-11 S1.6 + BR-14: when the background task finishes (success or
    # failure), cleanup goes through the injected ObjectStore factory so the
    # route stays on the protocol surface — no FilesystemObjectStore-specific
    # attribute access leaks here. Slice B (OCI) swaps the factory via
    # app.dependency_overrides[get_object_store_factory_for_request] without
    # touching this route.
    background_tasks.add_task(
        chain_populate_and_process,
        tenant_id=str(tenant_uuid),
        job_id=str(persisted_job_id),
        media_items=media_items_tuples,
        media_ids=media_ids,
        media_sources=media_sources,
        scan_queue=scan_queue if not isinstance(scan_queue, ScanQueueService) else None,
        session_factory=session_factory,
        inline_processing=inline_processing,
        correlation_id=get_correlation_id(),
        object_store_factory=object_store_factory,
    )

    # E15-11 S3.1: structured single-line telemetry for the multipart route so
    # transport failures can be triaged without parsing FastAPI access logs.
    # Fields are intentionally non-PII: tenant id is already a UUID claim,
    # job id is freshly generated, parts_count + total_bytes describe shape
    # only. Format mirrors analyze.py's analyze_media_timing convention.
    # Read sizes back through ObjectStore.open since the helper has already
    # consumed the original UploadFile streams.
    total_bytes_dispatched = 0
    for item in media_items_list:
        try:
            with object_store.open(item.blob_uri) as fh:  # type: ignore[arg-type]
                total_bytes_dispatched += len(fh.read())
        except Exception:  # pragma: no cover - telemetry must never raise
            pass
    logger.info(
        "analyze_media_multipart_dispatch transport=multipart parts_count=%d total_bytes=%d tenant_id=%s job_id=%s",
        len(media_items_list),
        total_bytes_dispatched,
        canonical_tenant_id,
        persisted_job_id,
    )

    progress = JobProgressResponse(
        completed=0,
        total=len(media_items_list),
        phase=JobPhase.QUEUED,
        images_processed=0,
        faces_found=0,
    )
    return JobStatusResponse(
        id=str(persisted_job_id),
        type=JobType.ANALYZE.value,
        status=JobStatus.PENDING,
        progress=progress,
        started_at=datetime.now(tz=UTC),
        finished_at=None,
        message=f"Queueing 0/{len(media_items_list)} items",
    )
