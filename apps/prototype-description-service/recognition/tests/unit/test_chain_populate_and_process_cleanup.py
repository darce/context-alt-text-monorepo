"""chain_populate_and_process must invoke ObjectStore.cleanup (E15-11 S1.6).

The multipart upload route writes per-job blobs through the ObjectStore.
On both the success and the failure paths of the scheduled background
task, those blobs must be removed via object_store_factory(tenant_id)
.cleanup(job_id=...) so a completed scan does not leave residue on disk
and a failed scan does not leak orphans.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from recognition.application.storage import FilesystemObjectStore
from recognition.application.tasks.scan import chain_populate_and_process

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes"


class _StubScanQueue:
    """Just enough to satisfy populate_scan_job_items_async's contract."""

    async def populate_scan_job_items(self, **_kwargs) -> int:
        return 0


@pytest.mark.asyncio
async def test_chain_populate_and_process_does_not_clean_when_async_worker_path(
    tmp_path: Path,
) -> None:
    """E15-11-BR-07: when ``inline_processing=False`` (the production async-
    worker configuration) ``chain_populate_and_process`` must NOT clean
    up the per-job blob directory — the external scan_worker has not yet
    consumed the queued items, and pre-empting cleanup would turn every
    multipart job into a guaranteed missing-blob failure.
    """
    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    blob_root = tmp_path / "blobs"

    # Plant a per-job blob the way the multipart route would have.
    store = FilesystemObjectStore(root=blob_root, tenant_id=tenant_id)
    store.put(job_id=job_id, media_id="1", data=PNG_BYTES)
    job_dir = blob_root / tenant_id / job_id
    assert job_dir.is_dir(), "fixture sanity check"

    def factory(t: str) -> FilesystemObjectStore:
        return FilesystemObjectStore(root=blob_root, tenant_id=t)

    await chain_populate_and_process(
        tenant_id=tenant_id,
        job_id=job_id,
        media_items=[(1, f"file://{job_dir}/1.bin")],
        media_ids=["1"],
        media_sources=[f"file://{job_dir}/1.bin"],
        scan_queue=_StubScanQueue(),
        inline_processing=False,
        object_store_factory=factory,
    )

    assert job_dir.is_dir(), (
        "async-worker path: blobs must remain on disk until the worker "
        "consumes them. Cleanup happens worker-side after the last item."
    )


@pytest.mark.asyncio
async def test_chain_populate_and_process_cleans_when_inline_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``inline_processing=True`` the helper consumes the blobs in the
    same call (process_scan_job_inline runs synchronously); cleanup at
    the end of that call IS safe and required."""
    from recognition.application.tasks import scan as scan_module

    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    blob_root = tmp_path / "blobs"

    store = FilesystemObjectStore(root=blob_root, tenant_id=tenant_id)
    store.put(job_id=job_id, media_id="1", data=PNG_BYTES)
    job_dir = blob_root / tenant_id / job_id
    assert job_dir.is_dir()

    async def _noop_inline(**_kwargs):
        return None

    monkeypatch.setattr(scan_module, "process_scan_job_inline", _noop_inline)

    def factory(t: str) -> FilesystemObjectStore:
        return FilesystemObjectStore(root=blob_root, tenant_id=t)

    await chain_populate_and_process(
        tenant_id=tenant_id,
        job_id=job_id,
        media_items=[(1, f"file://{job_dir}/1.bin")],
        media_ids=["1"],
        media_sources=[f"file://{job_dir}/1.bin"],
        scan_queue=_StubScanQueue(),
        inline_processing=True,
        object_store_factory=factory,
    )

    assert not job_dir.exists(), "inline path: blobs were consumed in this call, so cleanup must run"


@pytest.mark.asyncio
async def test_chain_populate_and_process_cleans_when_inline_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inline path failure must still clean up — the bytes were already
    handed to the inline processor; if it raised mid-stream those bytes
    are no longer needed and must not leak."""
    from recognition.application.tasks import scan as scan_module

    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    blob_root = tmp_path / "blobs"

    store = FilesystemObjectStore(root=blob_root, tenant_id=tenant_id)
    store.put(job_id=job_id, media_id="1", data=PNG_BYTES)
    job_dir = blob_root / tenant_id / job_id

    async def _raising_inline(**_kwargs):
        raise RuntimeError("simulated inline failure")

    monkeypatch.setattr(scan_module, "process_scan_job_inline", _raising_inline)

    def factory(t: str) -> FilesystemObjectStore:
        return FilesystemObjectStore(root=blob_root, tenant_id=t)

    with pytest.raises(RuntimeError, match="simulated inline failure"):
        await chain_populate_and_process(
            tenant_id=tenant_id,
            job_id=job_id,
            media_items=[(1, f"file://{job_dir}/1.bin")],
            media_ids=["1"],
            media_sources=[f"file://{job_dir}/1.bin"],
            scan_queue=_StubScanQueue(),
            inline_processing=True,
            object_store_factory=factory,
        )

    assert not job_dir.exists(), (
        "inline failure must still trigger cleanup: bytes were consumed by "
        "the failing inline processor and the directory is no longer needed"
    )


@pytest.mark.asyncio
async def test_chain_populate_and_process_no_factory_keeps_legacy_behaviour(
    tmp_path: Path,
) -> None:
    """JSON callers (legacy URL transport) do not provide a factory; cleanup
    must be a no-op rather than an attribute error."""
    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    await chain_populate_and_process(
        tenant_id=tenant_id,
        job_id=job_id,
        media_items=[(1, "https://example.com/x.jpg")],
        media_ids=["1"],
        media_sources=["https://example.com/x.jpg"],
        scan_queue=_StubScanQueue(),
        inline_processing=False,
        # object_store_factory deliberately omitted
    )
