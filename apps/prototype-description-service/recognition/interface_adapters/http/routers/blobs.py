"""Tenant-scoped blob serving for multipart-uploaded images.

The multipart upload route stores image bytes via the request-scoped
``ObjectStore`` and persists ``file://<root>/<tenant>/<job>/<media>.bin``
URIs in the DB. The browser cannot fetch ``file://`` URLs, so this
router exposes them as same-origin HTTPS resources at
``GET /recognition/blobs/{job_id}/{media_id}``.

Tenant binding: the tenant is *always* taken from the validated auth
context (``auth.tenant_claim``). Admin keys with no tenant claim are
rejected with 403 — there is no admin override here. The
``FilesystemObjectStore`` is constructed bound to that tenant; its own
``open()`` enforces that the resolved on-disk path falls under the
tenant prefix, so a tenant-scoped key cannot read another tenant's
blobs even if it constructs a hand-crafted URL.

The matching wire format is produced by
``recognition.interface_adapters.http.blob_url.BlobUrl``, which rewrites
file URIs to ``/recognition/blobs/<job>/<media>`` at response
serialization. The two pieces are deliberately independent: the writer
is a Pydantic AfterValidator that needs no FastAPI context, the reader
is a single FastAPI route.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from PIL import Image, UnidentifiedImageError

from recognition.application.storage import ObjectStoreError
from recognition.config.settings import RecognitionSettings
from recognition.interface_adapters.http.blob_url import FACE_THUMB_MAX_COMPONENT
from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
from recognition.interface_adapters.http.deps.object_store import (
    ObjectStoreFactory,
    _settings_default,
    get_object_store_factory_for_request,
)

router = APIRouter()

_DISALLOWED_SEGMENT_CHARS = ("/", "\\", "\x00", "..")


def _validate_segment(value: str, *, label: str) -> None:
    """Reject path segments that could escape the tenant prefix.

    FastAPI's path-param parsing already rejects raw `/`, but defense in
    depth here keeps the failure mode a clean 400 instead of leaking an
    ``ObjectStoreError`` from the filesystem layer below.
    """
    if not value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{label} must not be empty")
    if value in {".", ".."}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{label} must not be a path component")
    for bad in _DISALLOWED_SEGMENT_CHARS:
        if bad in value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{label} contains illegal characters")


_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
)


def _sniff_media_type(data: bytes) -> str:
    """Return a best-guess MIME type based on the first bytes of ``data``."""
    for prefix, mime in _MAGIC:
        if data.startswith(prefix):
            return mime
    return "application/octet-stream"


@router.get("/blobs/{job_id}/{media_id}")
async def serve_blob(
    job_id: str,
    media_id: str,
    auth: AuthContext = Depends(require_auth),
    store_factory: ObjectStoreFactory = Depends(get_object_store_factory_for_request),
    settings: RecognitionSettings = Depends(_settings_default),
) -> Response:
    """Stream a tenant-scoped multipart-uploaded blob.

    Returns the raw bytes with a sniffed image MIME type so the browser
    can render it via ``<img src>``. 403 when the auth key has no tenant
    claim; 404 when the blob does not exist or the resolved path falls
    outside the tenant prefix.
    """
    if not auth.tenant_claim:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="blob serving requires a tenant-scoped API key",
        )

    _validate_segment(job_id, label="job_id")
    _validate_segment(media_id, label="media_id")

    store = store_factory(auth.tenant_claim)
    blob_uri = f"file://{settings.blob_root}/{auth.tenant_claim}/{job_id}/{media_id}.bin"
    try:
        with store.open(blob_uri) as fh:
            data = fh.read()
    except ObjectStoreError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return Response(content=data, media_type=_sniff_media_type(data))


@router.get("/face-thumbs/{job_id}/{media_id}")
async def serve_face_thumb(
    job_id: str,
    media_id: str,
    # Importing the shared bound from blob_url.py keeps the backend reader
    # aligned with the backend emitter, contract doc, and WP signer.
    x: int = Query(..., ge=0, le=FACE_THUMB_MAX_COMPONENT),
    y: int = Query(..., ge=0, le=FACE_THUMB_MAX_COMPONENT),
    width: int = Query(..., gt=0, le=FACE_THUMB_MAX_COMPONENT),
    height: int = Query(..., gt=0, le=FACE_THUMB_MAX_COMPONENT),
    auth: AuthContext = Depends(require_auth),
    store_factory: ObjectStoreFactory = Depends(get_object_store_factory_for_request),
    settings: RecognitionSettings = Depends(_settings_default),
) -> Response:
    """Stream a cropped face thumbnail from a tenant-scoped blob."""
    if not auth.tenant_claim:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="face thumbnail serving requires a tenant-scoped API key",
        )

    _validate_segment(job_id, label="job_id")
    _validate_segment(media_id, label="media_id")

    store = store_factory(auth.tenant_claim)
    blob_uri = f"file://{settings.blob_root}/{auth.tenant_claim}/{job_id}/{media_id}.bin"
    try:
        with store.open(blob_uri) as fh:
            data = fh.read()
    except ObjectStoreError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="blob is not a supported image",
        ) from exc

    left = min(x, image.width)
    top = min(y, image.height)
    right = min(x + width, image.width)
    bottom = min(y + height, image.height)
    if right <= left or bottom <= top:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="face crop is outside image bounds",
        )

    output = io.BytesIO()
    image.crop((left, top, right, bottom)).save(output, format="JPEG", quality=85)
    return Response(content=output.getvalue(), media_type="image/jpeg")


__all__ = ["router"]
