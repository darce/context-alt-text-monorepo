"""Remote media resolving to RFC1918 is refused unless allow_private_source."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.bench.corpus import _is_non_public, reset_media_host_pins, resolve_media_bytes
from scripts.bench.stack_pair import BenchError
from scripts.eval_harness.manifest import EntryPolicy, GoldenEntry

_JPEG = b"jpeg-bytes"
_JPEG_SHA = hashlib.sha256(_JPEG).hexdigest()


def _entry(*, sha256: str | None = None) -> GoldenEntry:
    return _entry_at("remote.jpg", media_id=1, sha256=sha256)


def _entry_at(path: str, *, media_id: int, sha256: str | None = None) -> GoldenEntry:
    return GoldenEntry(
        path=path,
        sha256=sha256 or _JPEG_SHA,
        media_id=media_id,
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

    def fake_get(host: str, port: int, path: str, pinned_ip: str, **_kwargs):
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


def test_nat64_of_rfc1918_is_refused() -> None:
    assert _is_non_public("64:ff9b::10.0.0.1") is True
    assert _is_non_public("64:ff9b::8.8.8.8") is True


def test_https_get_pinned_connects_to_pinned_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.bench import corpus as corpus_mod

    connects: list[tuple[str, int]] = []

    class FakeHTTPS:
        def __init__(self, host: str, port: int = 443, timeout: float | None = None, context=None) -> None:
            self.host = host
            self.port = port
            self.sock = None

        def request(self, method: str, path: str, headers: dict | None = None) -> None:
            if self.sock is None:
                self.connect()

        def getresponse(self):
            class _Resp:
                status = 200
                _body = b"ok"

                def read(self, amt: int | None = None) -> bytes:
                    data, self._body = self._body, b""
                    return data

                def read1(self, n: int = -1) -> bytes:
                    if not self._body:
                        return b""
                    if n is None or n < 0:
                        return self.read()
                    chunk, self._body = self._body[:n], self._body[n:]
                    return chunk

                def getheaders(self) -> list:
                    return []

            return _Resp()

        def close(self) -> None:
            return None

    def fake_create_connection(address: tuple, timeout: object = None):
        connects.append(address)
        return object()

    monkeypatch.setattr(corpus_mod, "HTTPSConnection", FakeHTTPS)
    monkeypatch.setattr(corpus_mod.socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(corpus_mod.ssl.SSLContext, "wrap_socket", lambda self, sock, server_hostname=None: sock)
    status, _headers, body = corpus_mod._https_get_pinned("media.example.com", 443, "/x", "203.0.113.10")
    assert status == 200
    assert body == b"ok"
    assert connects == [("203.0.113.10", 443)]


def test_redirect_second_hop_connects_to_re_pinned_ip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Connect-level two-hop: second host is re-pinned, not reused from hop 1."""
    from scripts.bench import corpus as corpus_mod

    reset_media_host_pins()
    url_map = tmp_path / "urls.json"
    url_map.write_text('{"remote.jpg": "https://media.example.com/remote.jpg"}', encoding="utf-8")
    connects: list[tuple[str, int]] = []

    class FakeHTTPS:
        def __init__(self, host: str, port: int = 443, timeout: float | None = None, context=None) -> None:
            self.host = host
            self.port = port
            self.sock = None

        def request(self, method: str, path: str, headers: dict | None = None) -> None:
            if self.sock is None:
                self.connect()

        def getresponse(self):
            host = self.host

            class _Resp:
                def __init__(self) -> None:
                    if host == "media.example.com":
                        self.status = 302
                        self._headers = [("Location", "https://cdn.example.com/meta")]
                        self._body = b""
                    else:
                        self.status = 200
                        self._headers = []
                        self._body = _JPEG

                def read(self, amt: int | None = None) -> bytes:
                    data, self._body = self._body, b""
                    return data

                def read1(self, n: int = -1) -> bytes:
                    if not self._body:
                        return b""
                    if n is None or n < 0:
                        return self.read()
                    chunk, self._body = self._body[:n], self._body[n:]
                    return chunk

                def getheaders(self) -> list:
                    return self._headers

            return _Resp()

        def close(self) -> None:
            return None

    def fake_create_connection(address: tuple, timeout: object = None):
        connects.append(address)
        return object()

    def resolver(host: str) -> list[str]:
        return ["203.0.113.20"] if host == "cdn.example.com" else ["203.0.113.10"]

    monkeypatch.setattr(corpus_mod, "HTTPSConnection", FakeHTTPS)
    monkeypatch.setattr(corpus_mod.socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(corpus_mod.ssl.SSLContext, "wrap_socket", lambda self, sock, server_hostname=None: sock)
    data = resolve_media_bytes(
        _entry(),
        images_dir=tmp_path / "missing",
        url_map_path=url_map,
        allow_private_source=True,
        resolver=resolver,
    )
    assert data == _JPEG
    assert connects == [("203.0.113.10", 443), ("203.0.113.20", 443)]


def test_protocol_relative_redirect_is_re_pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_media_host_pins()
    url_map = tmp_path / "urls.json"
    url_map.write_text('{"remote.jpg": "https://media.example.com/remote.jpg"}', encoding="utf-8")
    seen_hosts: list[str] = []

    def fake_get(host: str, port: int, path: str, pinned_ip: str, **_kwargs):
        seen_hosts.append(host)
        if host == "media.example.com":
            return 302, {"location": "//cdn.example.com/meta"}, b""
        return 200, {}, _JPEG

    def resolver(host: str) -> list[str]:
        return ["203.0.113.20"] if host == "cdn.example.com" else ["203.0.113.10"]

    monkeypatch.setattr("scripts.bench.corpus._https_get_pinned", fake_get)
    data = resolve_media_bytes(
        _entry(),
        images_dir=tmp_path / "missing",
        url_map_path=url_map,
        allow_private_source=True,
        resolver=resolver,
    )
    assert data == _JPEG
    assert seen_hosts == ["media.example.com", "cdn.example.com"]


def test_http_redirect_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_media_host_pins()
    url_map = tmp_path / "urls.json"
    url_map.write_text('{"remote.jpg": "https://media.example.com/remote.jpg"}', encoding="utf-8")

    def fake_get(host: str, port: int, path: str, pinned_ip: str, **_kwargs):
        return 302, {"location": "http://evil.example/x"}, b""

    def resolver(_host: str) -> list[str]:
        return ["203.0.113.10"]

    monkeypatch.setattr("scripts.bench.corpus._https_get_pinned", fake_get)
    with pytest.raises(BenchError) as exc:
        resolve_media_bytes(
            _entry(),
            images_dir=tmp_path / "missing",
            url_map_path=url_map,
            allow_private_source=True,
            resolver=resolver,
        )
    assert exc.value.code == "media_unresolvable"


def test_multi_a_pin_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """sorted()[0] vs next(iter(set)) — ReverseIterSet makes the revert red on every hash seed."""
    reset_media_host_pins()
    url_map = tmp_path / "urls.json"
    url_map.write_text('{"remote.jpg": "https://media.example.com/remote.jpg"}', encoding="utf-8")
    pinned_seen: list[str] = []

    class ReverseIterSet(set):
        def __iter__(self):
            return iter(sorted(super().__iter__(), reverse=True))

    def reverse_pin(host: str, addresses: set[str]) -> set[str]:
        return ReverseIterSet(addresses)

    def fake_get(host: str, port: int, path: str, pinned_ip: str, **_kwargs):
        pinned_seen.append(pinned_ip)
        return 200, {}, _JPEG

    def resolver(_host: str) -> list[str]:
        return ["203.0.113.20", "203.0.113.10"]

    monkeypatch.setattr("scripts.bench.corpus.pin_media_hosts", reverse_pin)
    monkeypatch.setattr("scripts.bench.corpus._https_get_pinned", fake_get)
    resolve_media_bytes(
        _entry(),
        images_dir=tmp_path / "missing",
        url_map_path=url_map,
        allow_private_source=True,
        resolver=resolver,
    )
    assert pinned_seen == ["203.0.113.10"]


def test_pin_cache_first_wins_when_resolver_answer_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same host twice; second resolver answer must not win (FIR-8 R4-05)."""
    reset_media_host_pins()
    url_map = tmp_path / "urls.json"
    url_map.write_text(
        json.dumps(
            {
                "a.jpg": "https://media.example.com/a.jpg",
                "b.jpg": "https://media.example.com/b.jpg",
            }
        ),
        encoding="utf-8",
    )
    pinned_seen: list[str] = []
    n_resolve = 0

    def fake_get(host: str, port: int, path: str, pinned_ip: str, **_kwargs):
        pinned_seen.append(pinned_ip)
        return 200, {}, _JPEG

    def resolver(_host: str) -> list[str]:
        nonlocal n_resolve
        n_resolve += 1
        if n_resolve == 1:
            return ["203.0.113.10", "203.0.113.99"]
        return ["203.0.113.99"]

    monkeypatch.setattr("scripts.bench.corpus._https_get_pinned", fake_get)
    resolve_media_bytes(
        _entry_at("a.jpg", media_id=1),
        images_dir=tmp_path / "missing",
        url_map_path=url_map,
        allow_private_source=True,
        resolver=resolver,
    )
    resolve_media_bytes(
        _entry_at("b.jpg", media_id=2),
        images_dir=tmp_path / "missing",
        url_map_path=url_map,
        allow_private_source=True,
        resolver=resolver,
    )
    assert n_resolve == 2
    assert pinned_seen == ["203.0.113.10", "203.0.113.10"]
