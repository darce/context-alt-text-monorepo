"""Remote media resolving to RFC1918 is refused unless allow_private_source."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.bench.corpus import _is_non_public, reset_media_host_pins, resolve_media_bytes
from scripts.bench.stack_pair import BenchError
from scripts.eval_harness.manifest import EntryPolicy, GoldenEntry

_JPEG = b"jpeg-bytes"
_JPEG_SHA = hashlib.sha256(_JPEG).hexdigest()


def _entry(*, sha256: str | None = None) -> GoldenEntry:
    return GoldenEntry(
        path="remote.jpg",
        sha256=sha256 or _JPEG_SHA,
        media_id=1,
        face_count=0,
        present_identities=[],
        must_right=[],
        easy_wrong=[],
        policy=EntryPolicy(recognition_enabled=True),
        base_caption="",
    )


def test_rfc1918_without_override_refused(tmp_path: Path) -> None:
    reset_media_host_pins()
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
    reset_media_host_pins()
    url_map = tmp_path / "urls.json"
    url_map.write_text('{"remote.jpg": "https://media.example.com/remote.jpg"}', encoding="utf-8")

    def resolver(_host: str) -> list[str]:
        return ["10.0.0.5"]

    def fetcher(_url: str, _addrs: set[str]) -> bytes:
        return _JPEG

    data = resolve_media_bytes(
        _entry(),
        images_dir=tmp_path / "missing",
        url_map_path=url_map,
        allow_private_source=True,
        resolver=resolver,
        fetcher=fetcher,
    )
    assert data == _JPEG


def test_cgnat_without_override_refused(tmp_path: Path) -> None:
    reset_media_host_pins()
    url_map = tmp_path / "urls.json"
    url_map.write_text('{"remote.jpg": "https://media.example.com/remote.jpg"}', encoding="utf-8")

    def resolver(_host: str) -> list[str]:
        return ["100.64.1.1"]

    with pytest.raises(BenchError) as exc:
        resolve_media_bytes(
            _entry(),
            images_dir=tmp_path / "missing",
            url_map_path=url_map,
            allow_private_source=False,
            resolver=resolver,
        )
    assert exc.value.code == "media_unresolvable"
    assert _is_non_public("100.64.1.1") is True
    assert _is_non_public("8.8.8.8") is False


def test_remote_sha256_mismatch_refused(tmp_path: Path) -> None:
    reset_media_host_pins()
    url_map = tmp_path / "urls.json"
    url_map.write_text('{"remote.jpg": "https://media.example.com/remote.jpg"}', encoding="utf-8")

    def resolver(_host: str) -> list[str]:
        return ["8.8.8.8"]

    def fetcher(_url: str, _addrs: set[str]) -> bytes:
        return b"not-the-bytes"

    with pytest.raises(BenchError) as exc:
        resolve_media_bytes(
            _entry(),
            images_dir=tmp_path / "missing",
            url_map_path=url_map,
            allow_private_source=True,
            resolver=resolver,
            fetcher=fetcher,
        )
    assert exc.value.code == "media_unresolvable"


def test_redirect_to_rfc1918_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_media_host_pins()
    url_map = tmp_path / "urls.json"
    url_map.write_text('{"remote.jpg": "https://media.example.com/remote.jpg"}', encoding="utf-8")
    seen: list[str] = []

    def fake_get(host: str, port: int, path: str, pinned_ip: str):
        seen.append(pinned_ip)
        if pinned_ip == "8.8.8.8":
            return 302, {"location": "https://evil.example/meta"}, b""
        raise AssertionError("must not connect to unpinned/private hop")

    def resolver(host: str) -> list[str]:
        return ["169.254.169.254"] if host == "evil.example" else ["8.8.8.8"]

    monkeypatch.setattr("scripts.bench.corpus._https_get_pinned", fake_get)
    with pytest.raises(BenchError) as exc:
        resolve_media_bytes(
            _entry(),
            images_dir=tmp_path / "missing",
            url_map_path=url_map,
            allow_private_source=False,
            resolver=resolver,
        )
    assert exc.value.code == "media_unresolvable"
    assert seen == ["8.8.8.8"]
