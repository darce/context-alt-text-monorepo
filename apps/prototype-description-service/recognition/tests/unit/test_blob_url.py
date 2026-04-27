"""Unit tests for the file:// blob URI rewriter.

Covers the pure function that converts a ``file://<root>/<tenant>/<job>/<media>.bin``
URI into a same-origin relative path served by
``recognition.interface_adapters.http.routers.blobs``.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from recognition.interface_adapters.http.blob_url import BlobUrl, rewrite_blob_uri_to_path


class _Probe(BaseModel):
    """Minimal model exercising the BlobUrl AfterValidator."""

    url: BlobUrl = None


@pytest.mark.parametrize(
    "uri,expected",
    [
        (
            "file:///var/lib/acx-blobs/c0ce73dc-1c66-56a4-ae32-6eb966810988/c3a43c28-4c91-4ecf-8edb-bc0466793807/6726.bin",
            "/recognition/blobs/c3a43c28-4c91-4ecf-8edb-bc0466793807/6726",
        ),
        # Older /tmp/ root
        (
            "file:///tmp/acx-recognition-blobs/tenant-x/job-y/123.bin",
            "/recognition/blobs/job-y/123",
        ),
    ],
)
def test_rewrites_file_uri_to_relative_blob_path(uri: str, expected: str) -> None:
    assert rewrite_blob_uri_to_path(uri) == expected


def test_passes_through_none() -> None:
    assert rewrite_blob_uri_to_path(None) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/wp-content/uploads/foo.jpg",
        "http://localhost:10010/wp-content/uploads/bar.png",
    ],
)
def test_passes_through_http_urls_unchanged(url: str) -> None:
    """Legacy MediaItem.media_url carries http(s) URLs that must not be rewritten."""
    assert rewrite_blob_uri_to_path(url) == url


@pytest.mark.parametrize(
    "uri",
    [
        "file://",  # empty path
        "file:///single-segment.bin",  # < 3 segments
        "file:///a/b",  # missing .bin
        "file:///a/b/c.txt",  # wrong suffix
        "file:///a/b/.bin",  # empty media_id
    ],
)
def test_returns_none_for_malformed_file_uris(uri: str) -> None:
    assert rewrite_blob_uri_to_path(uri) is None


def test_blob_url_annotated_alias_applies_in_pydantic_model() -> None:
    """The Annotated alias triggers the rewriter on field assignment."""
    probe = _Probe(url="file:///root/tenant-a/job-b/9.bin")
    assert probe.url == "/recognition/blobs/job-b/9"


def test_blob_url_annotated_alias_passes_http_through() -> None:
    probe = _Probe(url="https://example.com/x.jpg")
    assert probe.url == "https://example.com/x.jpg"
