"""VLM6-RV15-L-05: stdout path lines must print through `_printable_path`.

Lane MD owns this file. Independent of `test_eval_harness_cli_stdio.py`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scene.tests.test_eval_harness_cli_stdio import (
    _assert_child_ascii_locale,
    _c_locale_child_env,
    _enforce_surrogate_argv_marker,
    apply_surrogate_argv_gate,
)
from scripts.eval_harness.report import ScoreVerdict

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_CAFE_UTF8 = b"caf\xc3\xa9"
_SURROGATE_LEAK = b"\\udc"

_FETCH_CHILD = b"""
import sys
from pathlib import Path
from scripts.eval_harness import cli as _cli

_cli.OUT_DIR = Path(sys.argv[1])
_cli._require_live_env = lambda: ("http://x", "k", "t")
_cli._images_dir = lambda: "/tmp"
_cli.load_manifest = lambda *a, **k: object()

class _FakeClient:
    def close(self) -> None:
        return None

_cli.RemoteSceneClient = lambda **k: _FakeClient()
_cli.fetch_run_record = lambda *a, **k: {"schema": "acx-eval/v1", "items": [], "provenance": {}}
_cli.prune_out_dir = lambda *a, **k: []
_cli.main(["fetch", "--manifest", "unused.json", "--keep", "1"])
"""


@pytest.fixture(autouse=True)
def _surrogate_argv_gate(request: pytest.FixtureRequest) -> None:
    apply_surrogate_argv_gate(request)


def _run_python_bytes(script: bytes, argv: list[bytes] | None = None) -> subprocess.CompletedProcess[bytes]:
    _assert_child_ascii_locale()
    _enforce_surrogate_argv_marker(argv)
    return subprocess.run(
        [os.fsencode(sys.executable), b"-c", script, *(argv or [])],
        cwd=os.fsencode(_SERVICE_ROOT),
        env=_c_locale_child_env(),
        capture_output=True,
    )


def _run_cli_bytes(argv: list[bytes]) -> subprocess.CompletedProcess[bytes]:
    code = b"import sys; from scripts.eval_harness.cli import main; main(sys.argv[1:])"
    return _run_python_bytes(code, argv)


def _cafe_named(tmp_path: Path, stem: bytes, suffix: bytes = b".json") -> bytes:
    return os.fsencode(tmp_path) + b"/" + stem + b"-" + _CAFE_UTF8 + suffix


def _write_bytes(path_b: bytes, payload: bytes) -> bytes:
    os.makedirs(os.path.dirname(path_b), exist_ok=True)
    with open(path_b, "wb") as fh:
        fh.write(payload)
    return path_b


def _adoption_compare_report() -> dict[str, Any]:
    """Non-vacuous Golden-100 caption report; equal candidate/baseline meets-or-beats."""
    return {
        "schema": "acx-eval/v1",
        "kind": "report",
        "eval_mode": "standard",
        "provenance": {
            "score_manifest_sha256": "aa" * 32,
            "manifest_sha256": "aa" * 32,
            "manifest_matches_fetch": True,
            "prompt_variant": "v3_weave",
            "two_pass": True,
            "dual_length": False,
            "face_gate": True,
            "head_sha": "0" * 40,
        },
        "counts": {"total": 100, "scored": 100, "failed": 0},
        "corpus": {"manifest_entries": 100, "media_id_missing": 0, "media_id_extra": 0},
        "caption": {
            "insertion_rate": 0.10,
            "mean_gated_score": 0.50,
            "must_right_failed_images": 0,
            "must_right_defined_images": 90,
            "easy_wrong_defined_images": 80,
        },
        "hallucination": {
            "fabricated_fact_rate": 0.05,
            "fabricated_fact_rate_trapped": 0.10,
            "images_with_traps": 20,
            "trap_instances": 20,
            "fabricated_instances": 1,
        },
        "placement": {
            "accuracy": 0.85,
            "claims": 40,
            "correct": 34,
            "wrong": 6,
            "abstained": 0,
            "images_scored": 100,
        },
        "faces": {
            "detection": {"precision": 0.90, "recall": 0.88, "tp": 80, "fp": 9, "fn": 11},
            "identification": {
                "precision": 0.92,
                "recall": 0.91,
                "evaluated_images": 90,
                "wrong_names": [],
                "ignored_wrong_names": [],
                "positional": {
                    "position_accuracy": 0.80,
                    "exact_order_rate": 0.70,
                    "compared_images": 50,
                    "position_total": 100,
                    "position_hits": 80,
                    "excluded_images": [],
                },
            },
            "identity_ordering": {
                "positional_images": 50,
                "degraded_images": 0,
                "degraded_paths": [],
            },
        },
        "verdict": {
            "verdict": ScoreVerdict.PASS.value,
            "wrong_name_rate": 0.0,
            "rubric_gate": "enforce",
            "reasons": [],
        },
    }


@pytest.mark.requires_surrogate_argv
def test_compare_meet_or_beat_pass_line_prints_utf8_paths(tmp_path: Path) -> None:
    """MUT cli.py:2652 — unwrap either `_printable_path` on the PASS line -> red."""
    body = json.dumps(_adoption_compare_report()).encode("utf-8")
    baseline = _write_bytes(_cafe_named(tmp_path, b"baseline"), body)
    candidate = _write_bytes(_cafe_named(tmp_path, b"candidate"), body)
    proc = _run_cli_bytes([b"compare", b"--baseline", baseline, b"--candidate", candidate])
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(b"compare meet-or-beat: PASS ")]
    assert len(lines) == 1, proc.stdout
    line = lines[0]
    assert b"candidate=" in line and b" baseline=" in line
    _, rest = line.split(b"candidate=", 1)
    cand_text, base_text = rest.split(b" baseline=", 1)
    assert _CAFE_UTF8 in cand_text, cand_text
    assert _CAFE_UTF8 in base_text, base_text
    assert _SURROGATE_LEAK not in cand_text, cand_text
    assert _SURROGATE_LEAK not in base_text, base_text


@pytest.mark.requires_surrogate_argv
def test_fetch_record_path_stdout_prints_utf8(tmp_path: Path) -> None:
    """MUT cli.py:955 — unwrap `print(_printable_path(record_path))` -> red."""
    out_dir = _cafe_named(tmp_path, b"out", suffix=b"")
    os.makedirs(out_dir, exist_ok=True)
    proc = _run_python_bytes(_FETCH_CHILD, [out_dir])
    assert proc.returncode == 0, proc.stderr
    path_lines = [ln for ln in proc.stdout.splitlines() if ln]
    assert path_lines, proc.stdout
    printed = path_lines[0]
    assert _CAFE_UTF8 in printed, printed
    assert _SURROGATE_LEAK not in printed, printed
    assert _SURROGATE_LEAK not in proc.stdout


def test_stdout_module_uses_imported_c_locale_helpers() -> None:
    """C-02 / TEST-15: no private C-locale env fork (sr-001)."""
    import scene.tests.test_eval_harness_cli_stdio as stdio
    import scene.tests.test_eval_harness_cli_stdout as stdout

    assert stdout._c_locale_child_env is stdio._c_locale_child_env
    assert stdout._assert_child_ascii_locale is stdio._assert_child_ascii_locale
    assert not hasattr(stdout, "_ASCII_LOCALE_ENV")
    assert not hasattr(stdout, "_ASCII_PARENT_KEYS")


def test_run_python_bytes_invokes_imported_assert_child_ascii_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-02: every stdout child process is gated by imported _assert_child_ascii_locale."""
    calls: list[int] = []

    def _spy() -> None:
        calls.append(1)

    monkeypatch.setattr(sys.modules[__name__], "_assert_child_ascii_locale", _spy)
    proc = _run_python_bytes(b"import sys; sys.stdout.buffer.write(b'ok')")
    assert calls == [1], "child runner never called imported _assert_child_ascii_locale (C-02)"
    assert proc.returncode == 0
    assert proc.stdout == b"ok"
