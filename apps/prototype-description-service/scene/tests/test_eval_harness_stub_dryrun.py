"""VLM-6 S2: bake-off client dry-run against a real-socket stub VLM server.

Loopback only — no GPU, no weights, no off-box network. The stub is the
transport; `bakeoff.main` is the unchanged client under test.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from scripts.eval_harness import bakeoff
from scripts.eval_harness.stub_vlm_server import serve_in_thread


def _tiny_png(red: int, green: int, blue: int) -> bytes:
    """1x1 RGB PNG via stdlib only (no fixture bytes on this VM)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00" + bytes((red, green, blue))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _write_stub_corpus(tmp_path: Path) -> tuple[Path, Path]:
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    entries: list[dict[str, Any]] = []
    for index in range(3):
        png = _tiny_png(index * 40, 80, 200 - index * 20)
        rel = f"img-{index + 1}.png"
        (images_dir / rel).write_bytes(png)
        entries.append(
            {
                "path": rel,
                "sha256": hashlib.sha256(png).hexdigest(),
                "media_id": index + 1,
                "face_count": 0,
                "present_identities": [],
                "context_pack": {"title": f"stub scene {index + 1}"},
                "must_right": ["Stub Person"],
                "easy_wrong": [],
                "policy": {"recognition_enabled": False},
                "base_caption": "",
                "provenance": {
                    "source": "fixture",
                    "license": "fixture",
                    "publishable": False,
                },
            }
        )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "annotation_mode": "roster_only",
                "roster": ["Stub Person"],
                "entries": entries,
            }
        )
        + "\n"
    )
    return manifest_path, images_dir


def _captions(record: dict[str, Any]) -> list[str]:
    return [item["describe"]["alt_text_draft"] for item in record["items"]]


@pytest.fixture
def live_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_EVAL_LIVE", "1")


def test_serve_in_thread_returns_reachable_base_url() -> None:
    """Cheaper CLI check: serve_in_thread binds an ephemeral port and answers /health."""
    server, base_url = serve_in_thread("127.0.0.1", 0, model_id="stub")
    try:
        with urlopen(f"{base_url}/health", timeout=2) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read())
        assert payload == {"status": "ok"}
        with pytest.raises(HTTPError, match="404") as err:
            urlopen(f"{base_url}/no-such-route", timeout=2)
        assert err.value.code == 404
        unknown = json.loads(err.value.read())
        assert "error" in unknown
    finally:
        server.shutdown()
        server.server_close()


def test_models_readiness_route_returns_model_id() -> None:
    server, base_url = serve_in_thread("127.0.0.1", 0, model_id="stub-ready")
    try:
        with urlopen(f"{base_url}/v1/models", timeout=2) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read())
        assert payload["object"] == "list"
        assert payload["data"][0]["id"] == "stub-ready"
    finally:
        server.shutdown()
        server.server_close()


def test_bakeoff_main_dry_run_writes_scoreable_record(
    tmp_path: Path, live_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, images_dir = _write_stub_corpus(tmp_path)
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(images_dir))
    out_path = tmp_path / "run.json"
    server, base_url = serve_in_thread("127.0.0.1", 0, model_id="stub", latency_ms=20)
    try:
        bakeoff.main(
            [
                "--endpoint",
                base_url,
                "--model-id",
                "stub",
                "--manifest",
                str(manifest_path),
                "--out",
                str(out_path),
                "--timeout",
                "10",
            ]
        )
    finally:
        server.shutdown()
        server.server_close()

    assert out_path.is_file()
    record = json.loads(out_path.read_text())
    assert record["provenance"]["base_url"] == base_url
    assert len(record["items"]) == 3
    for item in record["items"]:
        assert item["error"] is None
        describe = item["describe"]
        caption = describe["alt_text_draft"]
        assert isinstance(caption, str) and caption.strip()
        assert isinstance(item["latency_s"], (int, float)) and item["latency_s"] > 0
        passes = describe.get("passes")
        if isinstance(passes, list):
            for pass_row in passes:
                assert isinstance(pass_row["latency_s"], (int, float)) and pass_row["latency_s"] > 0
                usage = pass_row.get("usage")
                if usage is not None:
                    assert isinstance(usage["prompt_tokens"], int)
                    assert isinstance(usage["completion_tokens"], int)
                    assert isinstance(usage["total_tokens"], int)
        tokens = describe["tokens"]
        assert isinstance(tokens["prompt_tokens"], int)
        assert isinstance(tokens["completion_tokens"], int)
        assert isinstance(tokens["total_tokens"], int)


def test_dry_run_captions_are_deterministic(tmp_path: Path, live_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path, images_dir = _write_stub_corpus(tmp_path)
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(images_dir))
    server, base_url = serve_in_thread("127.0.0.1", 0, model_id="stub")
    try:
        outs = [tmp_path / "run-a.json", tmp_path / "run-b.json"]
        for out_path in outs:
            bakeoff.main(
                [
                    "--endpoint",
                    base_url,
                    "--model-id",
                    "stub",
                    "--manifest",
                    str(manifest_path),
                    "--out",
                    str(out_path),
                    "--timeout",
                    "10",
                ]
            )
        first = json.loads(outs[0].read_text())
        second = json.loads(outs[1].read_text())
        assert _captions(first) == _captions(second)
        assert all(caption.strip() for caption in _captions(first))
    finally:
        server.shutdown()
        server.server_close()


def test_fail_every_trips_bounded_stall_and_writes_aborted_record(
    tmp_path: Path, live_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, images_dir = _write_stub_corpus(tmp_path)
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(images_dir))
    out_path = tmp_path / "run-stall.json"
    aborted_path = out_path.with_name(out_path.stem + "-aborted.json")
    server, base_url = serve_in_thread("127.0.0.1", 0, model_id="stub", fail_every=1)
    try:
        with pytest.raises(SystemExit, match="BoundedStallError") as exc_info:
            bakeoff.main(
                [
                    "--endpoint",
                    base_url,
                    "--model-id",
                    "stub",
                    "--manifest",
                    str(manifest_path),
                    "--out",
                    str(out_path),
                    "--stall-limit",
                    "1",
                    "--timeout",
                    "5",
                ]
            )
    finally:
        server.shutdown()
        server.server_close()

    assert "BoundedStallError" in str(exc_info.value)
    assert aborted_path.is_file()
    record = json.loads(aborted_path.read_text())
    assert record["aborted"] is True
    assert record["items"]
    assert record["items"][0]["error"]
    assert not out_path.exists()
