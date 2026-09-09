"""Bounded pinned HTTPS fallback: bytes, absolute deadline, always-close.

EVALLAND-ASTRA-FINAL-20260909-01. Limit rationale: golden-corpus and
WordPress-scaled JPEGs are typically well under 5 MiB, so 8 MiB is a
conservative explicit cap above those photos and below unbounded dumps
([DATA-13] [RES-02]). One 30s monotonic budget covers the whole redirect
chain ([API-04] Latency: end-to-end deadlines).
"""

from __future__ import annotations

import hashlib
import ssl
from pathlib import Path

import pytest

from scripts.bench import corpus as corpus_mod
from scripts.bench.corpus import reset_media_host_pins, resolve_media_bytes
from scripts.bench.stack_pair import BenchError
from scripts.eval_harness.manifest import EntryPolicy, GoldenEntry

_JPEG = b"jpeg-bytes"
_JPEG_SHA = hashlib.sha256(_JPEG).hexdigest()

# Production values this slice must publish and enforce.
_REMOTE_MAX_BYTES = 8 * 1024 * 1024
_REMOTE_DEADLINE_S = 30.0


class _Clock:
    def __init__(self, t: float = 1_000.0) -> None:
        self.t = t

    def monotonic(self) -> float:
        return self.t


class _FakeSock:
    def __init__(self) -> None:
        self.closed = False
        self.timeouts: list[object] = []

    def settimeout(self, timeout: object) -> None:
        self.timeouts.append(timeout)

    def close(self) -> None:
        self.closed = True


def _entry() -> GoldenEntry:
    return GoldenEntry(
        path="remote.jpg",
        sha256=_JPEG_SHA,
        media_id=1,
        face_count=0,
        present_identities=[],
        must_right=[],
        easy_wrong=[],
        policy=EntryPolicy(recognition_enabled=True),
        base_caption="",
    )


def _install_https(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response_for,
    request_error: BaseException | None = None,
    response_error: BaseException | None = None,
    wrap_error: BaseException | None = None,
    clock: _Clock | None = None,
) -> dict[str, list]:
    probe: dict[str, list] = {
        "conns": [],
        "connect_timeouts": [],
        "connects": [],
        "socks": [],
        "sni": [],
        "hosts": [],
        "reads": [],
        "read1s": [],
    }
    if clock is not None:
        monkeypatch.setattr(corpus_mod, "time", clock, raising=False)

    class FakeHTTPS:
        def __init__(self, host: str, port: int = 443, timeout: float | None = None, context=None) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout
            self.sock = None
            probe["conns"].append(self)
            self.closed = False

        def request(self, method: str, path: str, headers: dict | None = None) -> None:
            probe["hosts"].append((self.host, headers or {}))
            if self.sock is None:
                self.connect()
            if request_error is not None:
                raise request_error

        def getresponse(self):
            if response_error is not None:
                raise response_error
            status, headers, body = response_for(self.host)
            payload = bytearray(body)

            class _Resp:
                def __init__(self) -> None:
                    self.status = status
                    self._body = payload

                def read(self, amt: int | None = None) -> bytes:
                    probe["reads"].append(amt)
                    if amt is None or amt < 0:
                        data = bytes(self._body)
                        self._body.clear()
                        return data
                    return self.read1(amt)

                def read1(self, n: int = -1) -> bytes:
                    probe["read1s"].append(n)
                    if not self._body:
                        return b""
                    take = len(self._body) if n is None or n < 0 else min(n, len(self._body))
                    chunk = bytes(self._body[:take])
                    del self._body[:take]
                    return chunk

                def getheaders(self) -> list:
                    return headers

            return _Resp()

        def close(self) -> None:
            self.closed = True

    def fake_create_connection(address: tuple, timeout: object = None):
        probe["connects"].append(address)
        probe["connect_timeouts"].append(timeout)
        sock = _FakeSock()
        probe["socks"].append(sock)
        return sock

    def fake_wrap(self, sock, server_hostname=None):
        probe["sni"].append(server_hostname)
        if wrap_error is not None:
            raise wrap_error
        return sock

    monkeypatch.setattr(corpus_mod, "HTTPSConnection", FakeHTTPS)
    monkeypatch.setattr(corpus_mod.socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(corpus_mod.ssl.SSLContext, "wrap_socket", fake_wrap)
    return probe


def test_published_remote_fetch_limits_match_corpus_rationale() -> None:
    assert corpus_mod.REMOTE_FETCH_MAX_BYTES == _REMOTE_MAX_BYTES
    assert corpus_mod.REMOTE_FETCH_DEADLINE_S == _REMOTE_DEADLINE_S


def test_declared_content_length_oversize_is_rejected_without_body_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _install_https(
        monkeypatch,
        response_for=lambda _host: (200, [("Content-Length", str(_REMOTE_MAX_BYTES + 1))], b""),
    )
    with pytest.raises(BenchError) as exc:
        corpus_mod._https_get_pinned("media.example.com", 443, "/x", "203.0.113.10")
    assert exc.value.code == "media_resource_failed"
    assert "content-length" in str(exc.value).lower() or "exceeds" in str(exc.value).lower()
    assert probe["reads"] == []
    assert probe["read1s"] == []
    assert probe["conns"] and probe["conns"][0].closed is True


def test_absent_content_length_oversize_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    oversize = b"x" * (_REMOTE_MAX_BYTES + 1)
    probe = _install_https(monkeypatch, response_for=lambda _host: (200, [], oversize))
    with pytest.raises(BenchError) as exc:
        corpus_mod._https_get_pinned("media.example.com", 443, "/x", "203.0.113.10")
    assert exc.value.code == "media_resource_failed"
    assert probe["conns"] and probe["conns"][0].closed is True


def test_lying_content_length_understates_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    oversize = b"x" * (_REMOTE_MAX_BYTES + 1)
    probe = _install_https(
        monkeypatch,
        response_for=lambda _host: (200, [("Content-Length", "4")], oversize),
    )
    with pytest.raises(BenchError) as exc:
        corpus_mod._https_get_pinned("media.example.com", 443, "/x", "203.0.113.10")
    assert exc.value.code == "media_resource_failed"
    assert probe["conns"] and probe["conns"][0].closed is True


def test_trickle_within_single_read_hits_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    probe = _install_https(
        monkeypatch,
        response_for=lambda _host: (200, [], b"abcdefgh"),
        clock=clock,
    )
    # Replace response body reader with a trickle clock after install.
    conns: list = probe["conns"]

    class TrickleHTTPS:
        def __init__(self, host: str, port: int = 443, timeout: float | None = None, context=None) -> None:
            self.host = host
            self.port = port
            self.sock = None
            self.closed = False
            conns.append(self)

        def request(self, method: str, path: str, headers: dict | None = None) -> None:
            if self.sock is None:
                self.connect()

        def getresponse(self):
            class _Resp:
                status = 200

                def read(self, amt: int | None = None) -> bytes:
                    if amt is None or amt < 0 or amt > 16:
                        clock.t += _REMOTE_DEADLINE_S + 1
                        raise AssertionError("unbounded/large read() allows trickle-stall; use read1")
                    return self.read1(amt)

                def read1(self, n: int = -1) -> bytes:
                    clock.t += 20.0
                    return b"x"

                def getheaders(self) -> list:
                    return []

            return _Resp()

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(corpus_mod, "HTTPSConnection", TrickleHTTPS)
    with pytest.raises(BenchError) as exc:
        corpus_mod._https_get_pinned("media.example.com", 443, "/x", "203.0.113.10")
    assert exc.value.code == "media_resource_failed"
    assert "deadline" in str(exc.value).lower()
    assert conns and conns[-1].closed is True


def test_request_failure_still_closes_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _install_https(
        monkeypatch,
        response_for=lambda _host: (200, [], _JPEG),
        request_error=OSError("send failed"),
    )
    with pytest.raises(OSError, match="send failed"):
        corpus_mod._https_get_pinned("media.example.com", 443, "/x", "203.0.113.10")
    assert probe["conns"] and probe["conns"][0].closed is True


def test_headers_failure_still_closes_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _install_https(
        monkeypatch,
        response_for=lambda _host: (200, [], _JPEG),
        response_error=OSError("headers failed"),
    )
    with pytest.raises(OSError, match="headers failed"):
        corpus_mod._https_get_pinned("media.example.com", 443, "/x", "203.0.113.10")
    assert probe["conns"] and probe["conns"][0].closed is True


def test_body_read_failure_still_closes_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _install_https(monkeypatch, response_for=lambda _host: (200, [], _JPEG))

    class BoomHTTPS:
        def __init__(self, host: str, port: int = 443, timeout: float | None = None, context=None) -> None:
            self.host = host
            self.port = port
            self.sock = None
            self.closed = False
            probe["conns"].append(self)

        def request(self, method: str, path: str, headers: dict | None = None) -> None:
            if self.sock is None:
                self.connect()

        def getresponse(self):
            class _Resp:
                status = 200

                def read(self, amt: int | None = None) -> bytes:
                    raise OSError("read failed")

                def read1(self, n: int = -1) -> bytes:
                    raise OSError("read failed")

                def getheaders(self) -> list:
                    return []

            return _Resp()

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(corpus_mod, "HTTPSConnection", BoomHTTPS)
    with pytest.raises(OSError, match="read failed"):
        corpus_mod._https_get_pinned("media.example.com", 443, "/x", "203.0.113.10")
    assert probe["conns"] and probe["conns"][-1].closed is True


def test_tls_wrap_failure_closes_raw_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _install_https(
        monkeypatch,
        response_for=lambda _host: (200, [], _JPEG),
        wrap_error=ssl.SSLError("wrap failed"),
    )
    with pytest.raises(ssl.SSLError, match="wrap failed"):
        corpus_mod._https_get_pinned("media.example.com", 443, "/x", "203.0.113.10")
    assert probe["socks"] and probe["socks"][0].closed is True
    assert probe["conns"] and probe["conns"][0].closed is True


def test_under_limit_body_preserves_pin_sni_and_host(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _install_https(
        monkeypatch,
        response_for=lambda _host: (200, [("Content-Length", str(len(_JPEG)))], _JPEG),
    )
    status, headers, body = corpus_mod._https_get_pinned("media.example.com", 443, "/x", "203.0.113.10")
    assert status == 200
    assert body == _JPEG
    assert headers.get("content-length") == str(len(_JPEG))
    assert probe["connects"] == [("203.0.113.10", 443)]
    assert probe["sni"] == ["media.example.com"]
    assert probe["hosts"] == [("media.example.com", {"Host": "media.example.com"})]
    assert probe["conns"] and probe["conns"][0].closed is True


def test_redirect_propagates_remaining_deadline_without_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_media_host_pins()
    clock = _Clock()
    url_map = tmp_path / "urls.json"
    url_map.write_text('{"remote.jpg": "https://media.example.com/remote.jpg"}', encoding="utf-8")

    def response_for(host: str):
        if host == "media.example.com":
            clock.t += 20.0
            return 302, [("Location", "https://cdn.example.com/meta")], b""
        return 200, [("Content-Length", str(len(_JPEG)))], _JPEG

    probe = _install_https(monkeypatch, response_for=response_for, clock=clock)
    data = resolve_media_bytes(
        _entry(),
        images_dir=tmp_path / "missing",
        url_map_path=url_map,
        allow_private_source=True,
        resolver=lambda host: ["203.0.113.20"] if host == "cdn.example.com" else ["203.0.113.10"],
    )
    assert data == _JPEG
    assert probe["connect_timeouts"] == [pytest.approx(_REMOTE_DEADLINE_S), pytest.approx(10.0)]
    assert probe["connect_timeouts"][1] < probe["connect_timeouts"][0]
    assert probe["connect_timeouts"][1] < 1.0 or probe["connect_timeouts"][1] == pytest.approx(10.0)


def test_redirect_does_not_connect_when_deadline_already_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_media_host_pins()
    clock = _Clock()
    url_map = tmp_path / "urls.json"
    url_map.write_text('{"remote.jpg": "https://media.example.com/remote.jpg"}', encoding="utf-8")

    def response_for(host: str):
        if host == "media.example.com":
            clock.t += _REMOTE_DEADLINE_S
            return 302, [("Location", "https://cdn.example.com/meta")], b""
        raise AssertionError("second hop must not be fetched after deadline")

    probe = _install_https(monkeypatch, response_for=response_for, clock=clock)
    with pytest.raises(BenchError) as exc:
        resolve_media_bytes(
            _entry(),
            images_dir=tmp_path / "missing",
            url_map_path=url_map,
            allow_private_source=True,
            resolver=lambda host: ["203.0.113.20"] if host == "cdn.example.com" else ["203.0.113.10"],
        )
    assert exc.value.code == "media_resource_failed"
    assert "deadline" in str(exc.value).lower()
    assert probe["connects"] == [("203.0.113.10", 443)]
    assert probe["conns"] and all(conn.closed for conn in probe["conns"])
