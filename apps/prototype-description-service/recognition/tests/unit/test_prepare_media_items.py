"""Tests for analyze.py::_prepare_media_items source-field selection (E15-11-BR-01).

After MediaItem gained ``blob_uri`` (S1.2), the analyze route's input
normalizer must source the per-item value from whichever transport field is
populated. The legacy implementation read ``item.media_url`` unconditionally,
so a schema-valid blob-only request would be silently enqueued with the
literal string ``"None"`` — this regression test pins that fix.
"""

from __future__ import annotations

import uuid

from recognition.interface_adapters.http.routers.analyze import _prepare_media_items
from recognition.interface_adapters.http.schemas.requests import AnalyzeRequest, MediaItem


def _tenant() -> str:
    return str(uuid.uuid4())


def test_prepare_media_items_uses_media_url_when_set() -> None:
    request = AnalyzeRequest(
        tenant_id=_tenant(),
        media_items=[MediaItem(media_id=42, media_url="https://example.com/x.jpg")],
    )
    _ids, sources, items = _prepare_media_items(request)
    assert sources == ["https://example.com/x.jpg"]
    assert items == [(42, "https://example.com/x.jpg")]


def test_prepare_media_items_uses_blob_uri_when_set() -> None:
    blob = "file:///srv/blobs/t/j/42.bin"
    request = AnalyzeRequest(
        tenant_id=_tenant(),
        media_items=[MediaItem(media_id=42, blob_uri=blob)],
    )
    _ids, sources, items = _prepare_media_items(request)
    assert sources == [blob], "Blob-only MediaItem must surface the blob URI, not None or 'None'"
    assert items == [(42, blob)]


def test_prepare_media_items_mixes_url_and_blob_per_item() -> None:
    """Defense-in-depth: a single request may combine legacy URL items and
    multipart blob items if a future caller batches across transports."""
    blob = "file:///srv/blobs/t/j/2.bin"
    request = AnalyzeRequest(
        tenant_id=_tenant(),
        media_items=[
            MediaItem(media_id=1, media_url="https://example.com/1.jpg"),
            MediaItem(media_id=2, blob_uri=blob),
        ],
    )
    _ids, sources, items = _prepare_media_items(request)
    assert sources == ["https://example.com/1.jpg", blob]
    assert items == [(1, "https://example.com/1.jpg"), (2, blob)]
