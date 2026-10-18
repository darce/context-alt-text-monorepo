"""ScanService.process_media_item must resolve file:// blob URIs (E15-11 Slice 1.5).

After the multipart route writes uploaded image bytes through
ObjectStore.put under <tenant>/<job_id>/<media_id>.bin, the scan worker
needs to read those bytes from disk via the same per-tenant ObjectStore
seam (which enforces cross-tenant refusal at open()) and pass the bytes
to the detector. Legacy URL transport (http://, https://) keeps passing
the URL string to the detector unchanged.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from pathlib import Path

import pytest

from recognition.application.embedding.detector import (
    FaceDetection,
    FaceDetectorProtocol,
)
from recognition.application.scan.service import ScanService
from recognition.application.storage import (
    FilesystemObjectStore,
    ObjectStore,
    ObjectStoreError,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes"


class _SpyDetector(FaceDetectorProtocol):
    def __init__(self) -> None:
        self.received_sources: list[bytes | str] = []

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        for source in sources:
            self.received_sources.append(source)
        return []


class _FakeSession:
    """Just enough of an AsyncSession for process_media_item to no-op the
    DB side. _persist_identities is exercised by other tests; here we only
    need the detector-source plumbing."""

    async def execute(self, _stmt):
        return _ResultEmpty()

    def add_all(self, _rows):
        return None

    async def flush(self):
        return None


class _ResultEmpty:
    def scalars(self):
        return self

    def all(self):
        return []


@pytest.mark.asyncio
async def test_process_media_item_resolves_blob_uri_via_object_store(
    tmp_path: Path,
) -> None:
    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    store = FilesystemObjectStore(root=tmp_path / "blobs", tenant_id=tenant_id)
    blob_uri = store.put(job_id=job_id, media_id="42", data=PNG_BYTES)

    detector = _SpyDetector()

    def store_factory(t: str) -> ObjectStore:
        assert t == tenant_id, "factory must be invoked with the active tenant"
        return store

    service = ScanService(
        session=_FakeSession(),
        detector=detector,
        object_store_factory=store_factory,
    )

    await service.process_media_item(
        tenant_id=tenant_id,
        media_id=42,
        media_url=blob_uri,
    )

    assert detector.received_sources == [PNG_BYTES], (
        "blob_uri sources must be resolved to raw bytes via ObjectStore.open"
    )


@pytest.mark.asyncio
async def test_process_media_item_passes_http_url_string_unchanged(
    tmp_path: Path,
) -> None:
    detector = _SpyDetector()
    service = ScanService(
        session=_FakeSession(),
        detector=detector,
        object_store_factory=lambda _t: FilesystemObjectStore(root=tmp_path / "blobs", tenant_id=str(uuid.uuid4())),
    )
    url = "https://example.com/x.jpg"

    await service.process_media_item(
        tenant_id=str(uuid.uuid4()),
        media_id=1,
        media_url=url,
    )

    assert detector.received_sources == [url], "Legacy URL transport must continue to pass the URL string to detector"


@pytest.mark.asyncio
async def test_process_media_item_refuses_cross_tenant_blob_uri(
    tmp_path: Path,
) -> None:
    """Threat (b)/(c) from the task plan: detector receives a blob_uri whose
    tenant prefix differs from the active tenant; the per-tenant ObjectStore
    refuses to open it. ScanService must propagate / convert that refusal,
    not silently fetch via HTTP or skip."""
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    blob_root = tmp_path / "blobs"
    store_b = FilesystemObjectStore(root=blob_root, tenant_id=tenant_b)
    foreign_uri = store_b.put(job_id=job_id, media_id="1", data=PNG_BYTES)

    detector = _SpyDetector()
    service = ScanService(
        session=_FakeSession(),
        detector=detector,
        object_store_factory=lambda t: FilesystemObjectStore(root=blob_root, tenant_id=t),
    )

    with pytest.raises(ObjectStoreError):
        await service.process_media_item(
            tenant_id=tenant_a,
            media_id=1,
            media_url=foreign_uri,
        )
    assert detector.received_sources == [], "detector must not receive any source when tenant binding refuses"


@pytest.mark.asyncio
async def test_process_media_item_without_factory_keeps_legacy_behavior(
    tmp_path: Path,
) -> None:
    """If no object_store_factory is configured (legacy callers), the source
    is passed through unchanged — including file:// URIs (which the
    detector already logs and skips). Required for backward compat with
    existing JSON callers and the existing scan_worker constructor."""
    detector = _SpyDetector()
    service = ScanService(session=_FakeSession(), detector=detector)
    url = "file:///some/path.bin"

    await service.process_media_item(tenant_id=str(uuid.uuid4()), media_id=1, media_url=url)
    assert detector.received_sources == [url]
