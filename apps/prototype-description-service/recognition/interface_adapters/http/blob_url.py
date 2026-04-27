"""Blob-URI to public-URL rewriter for HTTP response surfaces.

The multipart upload route stores image bytes via ``FilesystemObjectStore``
and persists the resulting ``file://<root>/<tenant>/<job>/<media>.bin``
URI in the database (cluster representatives, identities, suggestions).
Returning that URI verbatim to a browser fails — `file://` URLs are
blocked by every modern browser as `Not allowed to load local resource`.

This module rewrites those URIs to a same-origin relative path served by
``recognition.interface_adapters.http.routers.blobs``. The rewriter is
deliberately origin-agnostic: it emits a path like
``/recognition/blobs/<job>/<media>`` so the browser resolves it against
the API's own scheme/host without us needing to know either.

Apply via the ``BlobUrl`` annotated type alias on response fields. The
DB stays as-is — the rewrite happens only at the HTTP boundary.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated

from pydantic import AfterValidator

_FILE_SCHEME = "file://"
_BLOB_SUFFIX = ".bin"


def rewrite_blob_uri_to_path(value: str | None) -> str | None:
    """Rewrite a file:// blob URI to the public blob-serving relative path.

    Pass-through behaviour:
    - ``None`` returns ``None``.
    - URIs not starting with ``file://`` (e.g. ``http(s)://`` from the
      legacy URL transport) return unchanged.

    On a ``file://`` URI the function expects the on-disk path produced
    by ``FilesystemObjectStore.put`` — the trailing three segments are
    ``<tenant>/<job>/<media>.bin``. The function returns
    ``/recognition/blobs/<job>/<media>``. The tenant prefix is dropped
    because the HTTP route resolves it from the auth context, not from
    the URL.

    Returns ``None`` for malformed file URIs (missing ``.bin`` suffix or
    fewer than three trailing segments) so the field renders as null
    instead of leaking a half-parsed path.
    """
    if value is None:
        return None
    if not value.startswith(_FILE_SCHEME):
        return value

    raw_path = value[len(_FILE_SCHEME) :]
    if not raw_path:
        return None

    parts = PurePosixPath(raw_path).parts
    if len(parts) < 3:
        return None
    media_filename = parts[-1]
    if not media_filename.endswith(_BLOB_SUFFIX):
        return None
    job_id = parts[-2]
    media_id = media_filename[: -len(_BLOB_SUFFIX)]
    if not job_id or not media_id:
        return None

    return f"/recognition/blobs/{job_id}/{media_id}"


BlobUrl = Annotated[str | None, AfterValidator(rewrite_blob_uri_to_path)]
"""Pydantic field type that rewrites file:// blob URIs to public blob paths.

Use on response model fields whose value originates from
``FilesystemObjectStore.put`` (representative ``media_url``,
``identity_media_url``, ``representative_media_url``, etc.). Replace
``str | None`` with ``BlobUrl`` and the rewrite happens automatically at
serialization. Non-``file://`` values pass through unchanged so the
legacy URL transport (``MediaItem.media_url`` carrying an ``http(s)://``
URL) still works.
"""


__all__ = ["BlobUrl", "rewrite_blob_uri_to_path"]
