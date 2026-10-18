"""Schema-level tests for MediaItem + AnalyzeRequest (E15-11 Slice 1).

The multipart transport does not carry a ``media_url`` for each part — it
carries opaque blob URIs minted by the ObjectStore. ``MediaItem`` therefore
needs an optional ``blob_uri`` field, and the request contract must enforce
that exactly one of {media_url, blob_uri} is supplied so neither transport
silently mis-routes.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from recognition.interface_adapters.http.schemas.requests import MediaItem


def test_media_item_accepts_media_url_alone() -> None:
    item = MediaItem(media_id=1, media_url="https://example.com/x.jpg")
    assert item.media_url == "https://example.com/x.jpg"
    assert item.blob_uri is None


def test_media_item_accepts_blob_uri_alone() -> None:
    item = MediaItem(media_id=1, blob_uri="file:///srv/blobs/t/j/1.bin")
    assert item.blob_uri == "file:///srv/blobs/t/j/1.bin"
    assert item.media_url is None


def test_media_item_rejects_both_url_and_blob_uri() -> None:
    with pytest.raises(ValidationError):
        MediaItem(
            media_id=1,
            media_url="https://example.com/x.jpg",
            blob_uri="file:///srv/blobs/t/j/1.bin",
        )


def test_media_item_rejects_neither_url_nor_blob_uri() -> None:
    with pytest.raises(ValidationError):
        MediaItem(media_id=1)
