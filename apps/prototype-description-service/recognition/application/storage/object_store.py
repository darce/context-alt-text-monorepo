"""ObjectStore protocol — the storage seam for analyze image bytes.

The recognition pipeline used to fetch image bytes by HTTP GET against URLs
the plugin passed in; that path breaks for any WordPress install that is not
publicly resolvable from the hosted Alt Context API (LocalWP, intranet,
behind a WAF). E15-11 replaces it with a multipart-direct transport whose
backend writes inbound image parts through this protocol.

Implementations are bound to a single tenant at construction time and must
refuse any cross-tenant ``open(...)`` request — see
``FilesystemObjectStore`` for the canonical filesystem-backed reference.
"""

from __future__ import annotations

from typing import BinaryIO, Protocol, runtime_checkable


class ObjectStoreError(Exception):
    """Raised by ObjectStore implementations on contract violations.

    Covers per-blob tenant-binding refusals, path-traversal rejections, and
    URI-scheme mismatches. The HTTP layer maps this to 4xx responses; the
    detector treats it as a fetch failure for that media item.
    """


@runtime_checkable
class ObjectStore(Protocol):
    """Storage seam for inbound image bytes.

    The filesystem implementation lands in Slice A (E15-11). An OCI Object
    Storage implementation reuses the same protocol in Slice B (E15-12).
    """

    def put(self, *, job_id: str, media_id: str, data: bytes) -> str:
        """Store bytes for ``media_id`` under ``job_id`` and return an opaque URI.

        Implementations namespace storage by the tenant the store was bound to
        at construction time so a request authenticated as tenant T can only
        ever write under T's prefix.
        """
        ...

    def open(self, uri: str) -> BinaryIO:
        """Resolve a URI returned by :meth:`put` and return its byte stream.

        Must refuse URIs that resolve outside the bound tenant's prefix even
        if the path string is otherwise well-formed.
        """
        ...

    def cleanup(self, *, job_id: str) -> None:
        """Best-effort removal of every blob written under ``job_id``.

        Idempotent: a missing job directory must not raise. Called from both
        the success and the failure path of the scan worker so that no scan
        leaves residue on disk.
        """
        ...
