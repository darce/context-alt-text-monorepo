"""Unit tests for the filesystem ObjectStore implementation (E15-11 Slice 1).

Covers the storage-seam contract: put/open/cleanup semantics, the per-blob
tenant-binding invariant (the active store cannot resolve URIs outside its
tenant prefix), and path-traversal rejection on the inputs that flow from
HTTP request bodies into filesystem paths.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from recognition.application.storage import (
    FilesystemObjectStore,
    ObjectStore,
    ObjectStoreError,
)


def _tenant() -> str:
    return str(uuid.uuid4())


def _job() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def blob_root(tmp_path: Path) -> Path:
    root = tmp_path / "blobs"
    root.mkdir()
    return root


def test_filesystem_object_store_satisfies_protocol(blob_root: Path) -> None:
    store: ObjectStore = FilesystemObjectStore(root=blob_root, tenant_id=_tenant())
    assert hasattr(store, "put")
    assert hasattr(store, "open")
    assert hasattr(store, "cleanup")


def test_put_then_open_round_trip(blob_root: Path) -> None:
    tenant_id, job_id = _tenant(), _job()
    store = FilesystemObjectStore(root=blob_root, tenant_id=tenant_id)
    payload = b"\x89PNG\r\n\x1a\nfake-image-bytes"

    uri = store.put(job_id=job_id, media_id="42", data=payload)

    assert uri.startswith("file://")
    with store.open(uri) as fh:
        assert fh.read() == payload


def test_put_uri_path_layout_is_tenant_scoped(blob_root: Path) -> None:
    tenant_id, job_id = _tenant(), _job()
    store = FilesystemObjectStore(root=blob_root, tenant_id=tenant_id)

    uri = store.put(job_id=job_id, media_id="7", data=b"x")

    expected_path = blob_root / tenant_id / job_id / "7.bin"
    assert uri == f"file://{expected_path}"
    assert expected_path.is_file()


def test_cleanup_removes_per_job_directory(blob_root: Path) -> None:
    tenant_id, job_id = _tenant(), _job()
    store = FilesystemObjectStore(root=blob_root, tenant_id=tenant_id)
    store.put(job_id=job_id, media_id="1", data=b"a")
    store.put(job_id=job_id, media_id="2", data=b"b")
    job_dir = blob_root / tenant_id / job_id
    assert job_dir.is_dir()

    store.cleanup(job_id=job_id)

    assert not job_dir.exists()


def test_cleanup_is_idempotent_when_job_dir_missing(blob_root: Path) -> None:
    store = FilesystemObjectStore(root=blob_root, tenant_id=_tenant())
    store.cleanup(job_id=_job())  # must not raise


def test_cleanup_only_touches_its_own_job(blob_root: Path) -> None:
    tenant_id = _tenant()
    store = FilesystemObjectStore(root=blob_root, tenant_id=tenant_id)
    job_a, job_b = _job(), _job()
    store.put(job_id=job_a, media_id="1", data=b"a")
    store.put(job_id=job_b, media_id="1", data=b"b")

    store.cleanup(job_id=job_a)

    assert not (blob_root / tenant_id / job_a).exists()
    assert (blob_root / tenant_id / job_b / "1.bin").is_file()


def test_open_rejects_uri_outside_active_tenant_prefix(blob_root: Path) -> None:
    """Threat (b)+(c): a URI whose tenant prefix differs from the bound tenant
    must be refused — even if the attacker's path is well-formed and the file
    exists. This is the core per-blob tenant-binding invariant."""
    tenant_a, tenant_b, job_id = _tenant(), _tenant(), _job()
    store_b = FilesystemObjectStore(root=blob_root, tenant_id=tenant_b)
    foreign_uri = store_b.put(job_id=job_id, media_id="1", data=b"secret")

    store_a = FilesystemObjectStore(root=blob_root, tenant_id=tenant_a)
    with pytest.raises(ObjectStoreError):
        store_a.open(foreign_uri)


def test_open_rejects_uri_outside_blob_root(blob_root: Path, tmp_path: Path) -> None:
    """A hand-crafted URI pointing outside the configured blob_root must be
    rejected to defend against ``..``-style traversal escapes from a malicious
    blob_uri payload."""
    tenant_id = _tenant()
    store = FilesystemObjectStore(root=blob_root, tenant_id=tenant_id)
    sibling = tmp_path / "elsewhere.bin"
    sibling.write_bytes(b"not-allowed")
    bad_uri = f"file://{sibling}"

    with pytest.raises(ObjectStoreError):
        store.open(bad_uri)


def test_open_rejects_non_file_scheme(blob_root: Path) -> None:
    store = FilesystemObjectStore(root=blob_root, tenant_id=_tenant())
    with pytest.raises(ObjectStoreError):
        store.open("https://example.com/secret.png")


@pytest.mark.parametrize("bad_id", ["..", "../escape", "a/b", "a\x00b", ""])
def test_put_rejects_traversal_or_invalid_media_id(blob_root: Path, bad_id: str) -> None:
    store = FilesystemObjectStore(root=blob_root, tenant_id=_tenant())
    with pytest.raises(ObjectStoreError):
        store.put(job_id=_job(), media_id=bad_id, data=b"x")


@pytest.mark.parametrize("bad_id", ["..", "../escape", "a/b", "a\x00b", ""])
def test_put_rejects_traversal_or_invalid_job_id(blob_root: Path, bad_id: str) -> None:
    store = FilesystemObjectStore(root=blob_root, tenant_id=_tenant())
    with pytest.raises(ObjectStoreError):
        store.put(job_id=bad_id, media_id="1", data=b"x")


def test_put_rejects_empty_payload(blob_root: Path) -> None:
    store = FilesystemObjectStore(root=blob_root, tenant_id=_tenant())
    with pytest.raises(ObjectStoreError):
        store.put(job_id=_job(), media_id="1", data=b"")


def test_constructor_rejects_invalid_tenant_id(blob_root: Path) -> None:
    """Tenant id flows from auth.tenant_claim into a path segment; reject any
    value that could escape the tenant subdir."""
    for bad in ["..", "a/b", "", "a\x00b"]:
        with pytest.raises(ObjectStoreError):
            FilesystemObjectStore(root=blob_root, tenant_id=bad)
