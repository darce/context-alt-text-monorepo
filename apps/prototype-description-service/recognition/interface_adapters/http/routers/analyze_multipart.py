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

from collections.abc import Iterable

from fastapi import HTTPException, status
from starlette.datastructures import FormData, UploadFile

from recognition.application.storage import ObjectStore, ObjectStoreError
from recognition.interface_adapters.http.schemas.requests import MediaItem

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
