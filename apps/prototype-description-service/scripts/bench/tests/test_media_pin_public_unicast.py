"""Remote media resolving to RFC1918 is refused unless allow_private_source."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.bench.corpus import resolve_media_bytes
from scripts.bench.stack_pair import BenchError
from scripts.eval_harness.manifest import EntryPolicy, GoldenEntry


def _entry() -> GoldenEntry:
    return GoldenEntry(
        path="remote.jpg",
        sha256="a" * 64,
        media_id=1,
        face_count=0,
        present_identities=[],
        must_right=[],
        easy_wrong=[],
        policy=EntryPolicy(recognition_enabled=True),
        base_caption="",
    )


def test_rfc1918_without_override_refused(tmp_path: Path) -> None:
    url_map = tmp_path / "urls.json"
    url_map.write_text('{"remote.jpg": "https://media.example.com/remote.jpg"}', encoding="utf-8")

    def resolver(_host: str) -> list[str]:
        return ["10.0.0.5"]

    with pytest.raises(BenchError) as exc:
        resolve_media_bytes(
            _entry(),
            images_dir=tmp_path / "missing",
            url_map_path=url_map,
            allow_private_source=False,
            resolver=resolver,
        )
    assert exc.value.code == "media_unresolvable"


def test_rfc1918_allowed_with_override(tmp_path: Path) -> None:
    url_map = tmp_path / "urls.json"
    url_map.write_text('{"remote.jpg": "https://media.example.com/remote.jpg"}', encoding="utf-8")

    def resolver(_host: str) -> list[str]:
        return ["10.0.0.5"]

    def fetcher(_url: str, _addrs: set[str]) -> bytes:
        return b"jpeg-bytes"

    data = resolve_media_bytes(
        _entry(),
        images_dir=tmp_path / "missing",
        url_map_path=url_map,
        allow_private_source=True,
        resolver=resolver,
        fetcher=fetcher,
    )
    assert data == b"jpeg-bytes"
