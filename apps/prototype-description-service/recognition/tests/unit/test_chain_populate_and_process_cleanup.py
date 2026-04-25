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
async def test_chain_populate_and_process_cleans_blobs_on_success(
    tmp_path: Path,
) -> None:
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

    assert not job_dir.exists(), "successful chain_populate_and_process must remove per-job blob dir"


@pytest.mark.asyncio
async def test_chain_populate_and_process_cleans_blobs_when_populate_raises(
    tmp_path: Path,
) -> None:
    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    blob_root = tmp_path / "blobs"

    store = FilesystemObjectStore(root=blob_root, tenant_id=tenant_id)
    store.put(job_id=job_id, media_id="1", data=PNG_BYTES)
    job_dir = blob_root / tenant_id / job_id

    class _RaisingQueue:
        async def populate_scan_job_items(self, **_kwargs) -> int:
            raise RuntimeError("simulated failure during populate")

    def factory(t: str) -> FilesystemObjectStore:
        return FilesystemObjectStore(root=blob_root, tenant_id=t)

    with pytest.raises(RuntimeError, match="simulated failure"):
        await chain_populate_and_process(
            tenant_id=tenant_id,
            job_id=job_id,
            media_items=[(1, f"file://{job_dir}/1.bin")],
            media_ids=["1"],
            media_sources=[f"file://{job_dir}/1.bin"],
            scan_queue=_RaisingQueue(),
            inline_processing=False,
            object_store_factory=factory,
        )

    assert not job_dir.exists(), (
        "failed chain_populate_and_process must still remove per-job blob dir "
        "so the worker is not left with orphans it cannot find"
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
