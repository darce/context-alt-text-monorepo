"""Tests for the multipart-to-MediaItem helper (E15-11 Slice 1.4a).

The multipart variant of /recognition/analyze receives one image part per
media_id; this helper converts a parsed Starlette FormData into a list of
MediaItems with blob_uri populated via the request-scoped ObjectStore. The
helper owns MIME validation, empty-part rejection, and key-shape parsing
so the route handler stays focused on transport concerns.
"""

from __future__ import annotations

import io
import json
import logging
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.exception_handlers import http_exception_handler
from starlette.datastructures import FormData, Headers, UploadFile
from starlette.requests import Request

from recognition.application.storage import FilesystemObjectStore, ObjectStoreError
from recognition.interface_adapters.http.middleware.correlation import (
    CORRELATION_ID_HEADER,
    _correlation_id_var,
)
from recognition.interface_adapters.http.routers.analyze_multipart import (
    logger,
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


def test_helper_returns_empty_list_when_no_image_parts(store: FilesystemObjectStore) -> None:
    """An empty result tells the route handler to raise 422 for itself; the
    helper does not opine on whether zero parts is meaningful."""
    job_id = str(uuid.uuid4())
    form = _form(
        ("request", _put_content_type(_upload("r", b"{}", "application/json"), "application/json")),
    )
    items = multipart_to_media_items(form_data=form, object_store=store, job_id=job_id)
    assert items == []


@pytest.mark.asyncio
async def test_storage_failure_response_is_opaque_and_correlated(caplog: pytest.LogCaptureFixture) -> None:
    secret_path = "/srv/private/blobs/tenant-secret/image.png"
    driver_error = f"permission denied writing {secret_path}"
    correlation_id = "req-multipart-storage-failure"

    class FailingObjectStore:
        def put(self, *, job_id: str, media_id: str, data: bytes) -> str:
            raise ObjectStoreError(driver_error)

    form = _form(
        ("image_42", _put_content_type(_upload("a.png", PNG_BYTES, "image/png"), "image/png")),
    )
    token = _correlation_id_var.set(correlation_id)
    try:
        with caplog.at_level(logging.ERROR, logger=logger.name), pytest.raises(HTTPException) as excinfo:
            multipart_to_media_items(
                form_data=form,
                object_store=FailingObjectStore(),
                job_id="job-test",
            )
        request = Request({"type": "http", "method": "POST", "path": "/recognition/analyze/multipart"})
        response = await http_exception_handler(request, excinfo.value)
    finally:
        _correlation_id_var.reset(token)

    body_text = response.body.decode("utf-8")
    assert response.status_code == 500
    assert json.loads(body_text)["detail"] == "internal server error"
    assert driver_error not in body_text
    assert secret_path not in body_text
    assert response.headers[CORRELATION_ID_HEADER] == correlation_id

    records = [record for record in caplog.records if record.name == logger.name]
    assert len(records) == 1
    assert records[0].correlation_id == correlation_id
    assert records[0].exc_info is not None
    assert driver_error in str(records[0].exc_info[1])
