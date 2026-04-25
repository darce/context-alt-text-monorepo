"""Filesystem-backed ObjectStore implementation.

Stores bytes under ``<root>/<tenant_id>/<job_id>/<media_id>.bin`` and binds
each instance to a single tenant. The path layout is the per-blob
tenant-binding enforcement: ``open(uri)`` resolves the URI to an absolute
path and refuses anything that does not fall under the bound tenant's
prefix, defeating both cross-tenant lookups and ``..``-style traversal
escapes embedded in a hand-crafted ``blob_uri``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO

from .object_store import ObjectStoreError

_FILE_SCHEME = "file://"


def _validate_path_segment(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ObjectStoreError(f"{label} must be a non-empty string")
    if "/" in value or "\\" in value or "\x00" in value:
        raise ObjectStoreError(f"{label} must not contain path separators or null bytes")
    if value in {".", ".."}:
        raise ObjectStoreError(f"{label} must not be a relative path component")
    return value


class FilesystemObjectStore:
    """ObjectStore writing blobs to a per-tenant per-job filesystem tree.

    Construction binds the instance to a tenant id; every read or write
    happens under ``<root>/<tenant_id>/...``. The class deliberately avoids
    sharing state across tenants — request-scoped DI hands out a fresh
    instance bound to ``auth.tenant_claim`` (see
    ``recognition.interface_adapters.http.deps.object_store``).
    """

    def __init__(self, *, root: Path, tenant_id: str) -> None:
        _validate_path_segment(tenant_id, label="tenant_id")
        self._root = Path(root).resolve()
        self._tenant_id = tenant_id
        self._tenant_root = (self._root / tenant_id).resolve()

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def root(self) -> Path:
        return self._root

    def put(self, *, job_id: str, media_id: str, data: bytes) -> str:
        _validate_path_segment(job_id, label="job_id")
        _validate_path_segment(media_id, label="media_id")
        if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
            raise ObjectStoreError("data must be non-empty bytes")

        job_dir = self._tenant_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        target = job_dir / f"{media_id}.bin"
        target.write_bytes(bytes(data))
        return f"{_FILE_SCHEME}{target}"

    def open(self, uri: str) -> BinaryIO:
        if not isinstance(uri, str) or not uri.startswith(_FILE_SCHEME):
            raise ObjectStoreError("uri must use the file:// scheme")
        raw_path = uri[len(_FILE_SCHEME) :]
        if not raw_path:
            raise ObjectStoreError("uri must include a path")
        try:
            resolved = Path(raw_path).resolve()
        except OSError as exc:
            raise ObjectStoreError(f"uri path could not be resolved: {exc}") from exc

        # Per-blob tenant binding: the resolved path must live under THIS
        # store's tenant prefix. A different tenant's URI, or a hand-crafted
        # path that traverses out of blob_root, fails this check.
        try:
            resolved.relative_to(self._tenant_root)
        except ValueError as exc:
            raise ObjectStoreError("uri resolves outside the bound tenant prefix") from exc

        if not resolved.is_file():
            raise ObjectStoreError("uri does not resolve to a file")

        return resolved.open("rb")

    def cleanup(self, *, job_id: str) -> None:
        try:
            _validate_path_segment(job_id, label="job_id")
        except ObjectStoreError:
            # Cleanup is best-effort; an invalid job_id can never have
            # produced a directory in the first place.
            return
        job_dir = self._tenant_root / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
