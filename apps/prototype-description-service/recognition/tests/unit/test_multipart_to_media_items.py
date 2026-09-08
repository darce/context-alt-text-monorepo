"""Tests for the multipart-to-MediaItem helper (E15-11 Slice 1.4a).

The multipart variant of /recognition/analyze receives one image part per
media_id; this helper converts a parsed Starlette FormData into a list of
MediaItems with blob_uri populated via the request-scoped ObjectStore. The
helper owns MIME validation, empty-part rejection, and key-shape parsing
so the route handler stays focused on transport concerns.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.datastructures import FormData, Headers, UploadFile

from recognition.application.storage import FilesystemObjectStore, ObjectStoreError
from recognition.interface_adapters.http.routers.analyze_multipart import (
    multipart_to_media_items,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes-for-tests"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIFfake-jpeg"


def _upload(filename: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=io.BytesIO(content),
        headers=None,
        size=len(content),
        # Starlette UploadFile reads content_type from headers; we patch.
    )


def _form(*pairs: tuple[str, UploadFile]) -> FormData:
    # FormData accepts an iterable of (key, value) pairs.
    return FormData(pairs)


@pytest.fixture
def store(tmp_path: Path) -> FilesystemObjectStore:
    root = tmp_path / "blobs"
    root.mkdir()
    return FilesystemObjectStore(root=root, tenant_id=str(uuid.uuid4()))


def _put_content_type(upload: UploadFile, content_type: str) -> UploadFile:
    upload.headers = Headers({"content-type": content_type})
    return upload


def _stored_files(store: FilesystemObjectStore) -> list[Path]:
    return [path for path in store.root.rglob("*") if path.is_file()]


def test_helper_round_trips_one_image_part(store: FilesystemObjectStore) -> None:
    job_id = str(uuid.uuid4())
    upload = _put_content_type(_upload("a.png", PNG_BYTES, "image/png"), "image/png")
    form = _form(("image_42", upload))

    items = multipart_to_media_items(form_data=form, object_store=store, job_id=job_id)

    assert len(items) == 1
    item = items[0]
    assert item.media_id == 42
    assert item.media_url is None
    assert item.blob_uri is not None and item.blob_uri.startswith("file://")
    with store.open(item.blob_uri) as fh:
        assert fh.read() == PNG_BYTES


def test_helper_handles_multiple_parts_in_order(store: FilesystemObjectStore) -> None:
    job_id = str(uuid.uuid4())
    form = _form(
        ("image_1", _put_content_type(_upload("a.png", PNG_BYTES, "image/png"), "image/png")),
        ("image_2", _put_content_type(_upload("b.jpg", JPEG_BYTES, "image/jpeg"), "image/jpeg")),
    )

    items = multipart_to_media_items(form_data=form, object_store=store, job_id=job_id)

    assert [it.media_id for it in items] == [1, 2]


def test_helper_skips_non_image_keys(store: FilesystemObjectStore) -> None:
    """Form fields whose key does not start with ``image_`` are metadata
    fields (e.g. the ``request`` JSON envelope) and must not be uploaded
    or treated as images."""
    job_id = str(uuid.uuid4())
    form = _form(
        ("request", _put_content_type(_upload("r", b'{"tenant_id":"x"}', "application/json"), "application/json")),
        ("image_5", _put_content_type(_upload("a.png", PNG_BYTES, "image/png"), "image/png")),
    )

    items = multipart_to_media_items(form_data=form, object_store=store, job_id=job_id)

    assert [it.media_id for it in items] == [5]


def test_helper_rejects_unsupported_mime(store: FilesystemObjectStore) -> None:
    job_id = str(uuid.uuid4())
    form = _form(
        ("image_1", _put_content_type(_upload("a.gif", b"GIF89a-fake", "image/gif"), "image/gif")),
    )

    with pytest.raises(HTTPException) as excinfo:
        multipart_to_media_items(form_data=form, object_store=store, job_id=job_id)
    assert excinfo.value.status_code == 415


def test_helper_rejects_empty_part(store: FilesystemObjectStore) -> None:
    job_id = str(uuid.uuid4())
    form = _form(
        ("image_1", _put_content_type(_upload("a.png", b"", "image/png"), "image/png")),
    )

    with pytest.raises(HTTPException) as excinfo:
        multipart_to_media_items(form_data=form, object_store=store, job_id=job_id)
    assert excinfo.value.status_code == 422


def test_helper_rejects_non_integer_media_id(store: FilesystemObjectStore) -> None:
    job_id = str(uuid.uuid4())
    form = _form(
        ("image_not-an-int", _put_content_type(_upload("a.png", PNG_BYTES, "image/png"), "image/png")),
    )

    with pytest.raises(HTTPException) as excinfo:
        multipart_to_media_items(form_data=form, object_store=store, job_id=job_id)
    assert excinfo.value.status_code == 400


@pytest.mark.parametrize(
    ("second_key", "second_upload", "expected_status"),
    [
        (
            "image_not-an-int",
            _put_content_type(_upload("b.png", PNG_BYTES, "image/png"), "image/png"),
            400,
        ),
        (
            "image_2",
            _put_content_type(_upload("b.gif", b"GIF89a-fake", "image/gif"), "image/gif"),
            415,
        ),
        (
            "image_2",
            _put_content_type(_upload("b.png", b"", "image/png"), "image/png"),
            422,
        ),
    ],
    ids=["invalid-key", "unsupported-mime", "empty-data"],
)
def test_helper_validates_every_part_before_writing(
    store: FilesystemObjectStore,
    second_key: str,
    second_upload: UploadFile,
    expected_status: int,
) -> None:
    form = _form(
        ("image_1", _put_content_type(_upload("a.png", PNG_BYTES, "image/png"), "image/png")),
        (second_key, second_upload),
    )

    with pytest.raises(HTTPException) as excinfo:
        multipart_to_media_items(form_data=form, object_store=store, job_id="validate-first")

    assert excinfo.value.status_code == expected_status
    assert _stored_files(store) == []


def test_helper_read_failure_before_write_leaves_no_orphan(store: FilesystemObjectStore) -> None:
    class _UnreadableFile(io.BytesIO):
        def read(self, *_args, **_kwargs):
            raise OSError("read failed for /private/spool/upload.tmp")

    unreadable = UploadFile(filename="b.png", file=_UnreadableFile(PNG_BYTES))
    unreadable.headers = Headers({"content-type": "image/png"})
    form = _form(
        ("image_1", _put_content_type(_upload("a.png", PNG_BYTES, "image/png"), "image/png")),
        ("image_2", unreadable),
    )

    with pytest.raises(OSError, match="read failed"):
        multipart_to_media_items(form_data=form, object_store=store, job_id="unreadable")

    assert _stored_files(store) == []


def test_helper_rejects_duplicate_media_id_before_writing(store: FilesystemObjectStore) -> None:
    form = _form(
        ("image_7", _put_content_type(_upload("a.png", PNG_BYTES, "image/png"), "image/png")),
        ("image_07", _put_content_type(_upload("b.jpg", JPEG_BYTES, "image/jpeg"), "image/jpeg")),
    )

    with pytest.raises(HTTPException) as excinfo:
        multipart_to_media_items(form_data=form, object_store=store, job_id="duplicates")

    assert excinfo.value.status_code == 400
    assert "duplicate" in str(excinfo.value.detail).lower()
    assert _stored_files(store) == []


def test_helper_rejects_more_than_five_images_before_writing(store: FilesystemObjectStore) -> None:
    form = _form(
        *(
            (
                f"image_{media_id}",
                _put_content_type(_upload(f"{media_id}.png", PNG_BYTES, "image/png"), "image/png"),
            )
            for media_id in range(1, 7)
        )
    )

    with pytest.raises(HTTPException) as excinfo:
        multipart_to_media_items(form_data=form, object_store=store, job_id="too-many")

    assert excinfo.value.status_code == 400
    assert _stored_files(store) == []


def test_helper_returns_empty_list_when_no_image_parts(store: FilesystemObjectStore) -> None:
    """An empty result tells the route handler to raise 422 for itself; the
    helper does not opine on whether zero parts is meaningful."""
    job_id = str(uuid.uuid4())
    form = _form(
        ("request", _put_content_type(_upload("r", b"{}", "application/json"), "application/json")),
    )
    items = multipart_to_media_items(form_data=form, object_store=store, job_id=job_id)
    assert items == []


def test_storage_failure_after_first_write_cleans_up_all_parts(store: FilesystemObjectStore) -> None:
    secret_path = "/srv/private/blobs/tenant-secret/image.png"
    driver_error = f"permission denied writing {secret_path}"

    class FailingObjectStore:
        def __init__(self) -> None:
            self.put_calls = 0

        def put(self, *, job_id: str, media_id: str, data: bytes) -> str:
            self.put_calls += 1
            if self.put_calls == 2:
                raise ObjectStoreError(driver_error)
            return store.put(job_id=job_id, media_id=media_id, data=data)

        def cleanup(self, *, job_id: str) -> None:
            store.cleanup(job_id=job_id)

    form = _form(
        ("image_41", _put_content_type(_upload("a.png", PNG_BYTES, "image/png"), "image/png")),
        ("image_42", _put_content_type(_upload("b.png", PNG_BYTES, "image/png"), "image/png")),
    )

    with pytest.raises(ObjectStoreError, match="permission denied"):
        multipart_to_media_items(form_data=form, object_store=FailingObjectStore(), job_id="job-test")

    assert _stored_files(store) == []
