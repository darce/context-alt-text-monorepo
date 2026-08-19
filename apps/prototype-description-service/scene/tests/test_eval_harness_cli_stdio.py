"""VLM-6 fix wave 14 / Lane KA — cli.py path emission + stdio lifetime.

All new assertions live here. test_eval_harness_cli.py is owned by lane KB.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.eval_harness.cli import (
    _printable_path,
    _reconfigure_stdio,
    _stdio_encoding_guard,
)

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_ASCII_LOCALE_ENV = {
    "LC_ALL": "C",
    "LANG": "C",
    "PYTHONUTF8": "0",
    "PYTHONCOERCECLOCALE": "0",
}
_ASCII_PARENT_KEYS = (
    "LC_ALL",
    "LANG",
    "LC_CTYPE",
    "LC_MESSAGES",
    "LANGUAGE",
    "PYTHONUTF8",
    "PYTHONCOERCECLOCALE",
)
_CAFE_UTF8 = b"caf\xc3\xa9"
_SURROGATE_LEAK = b"\\udc"
_BACKSLASHREPLACE_LIE = b"\\xe9"


def _c_locale_child_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _ASCII_PARENT_KEYS:
        env.pop(key, None)
    env.update(_ASCII_LOCALE_ENV)
    env["PYTHONIOENCODING"] = "ascii"
    extra = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SERVICE_ROOT) + (os.pathsep + extra if extra else "")
    return env


def _run_cli_bytes(argv: list[bytes]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            os.fsencode(sys.executable),
            b"-c",
            b"import sys; from scripts.eval_harness.cli import main; main(sys.argv[1:])",
            *argv,
        ],
        cwd=os.fsencode(_SERVICE_ROOT),
        env=_c_locale_child_env(),
        capture_output=True,
    )


def _tiny_split_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "split-man.json"
    path.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "annotation_mode": "roster_only",
                "roster": ["Alice", "Bob"],
                "entries": [
                    {
                        "path": "alice.jpg",
                        "sha256": "a" * 64,
                        "media_id": 1,
                        "face_count": 1,
                        "present_identities": ["Alice"],
                        "must_right": ["Alice"],
                        "easy_wrong": [],
                        "policy": {"recognition_enabled": False},
                        "base_caption": "",
                        "provenance": {"source": "fixture", "license": "fixture"},
                    },
                    {
                        "path": "bob.jpg",
                        "sha256": "b" * 64,
                        "media_id": 2,
                        "face_count": 1,
                        "present_identities": ["Bob"],
                        "must_right": ["Bob"],
                        "easy_wrong": [],
                        "policy": {"recognition_enabled": False},
                        "base_caption": "",
                        "provenance": {"source": "fixture", "license": "fixture"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _draw_argv(manifest: Path, out: bytes, *, extra: list[bytes] | None = None) -> list[bytes]:
    argv = [
        b"draw-eval-split",
        b"--manifest",
        os.fsencode(manifest),
        b"--out",
        out,
        b"--seed",
        b"alpha",
        b"--held-out-fraction",
        b"0.5",
        b"--draw-timestamp",
        b"2026-08-18T00:00:00Z",
        b"--partition-provenance",
        b"ka-stdio-fixture",
        b"--exposure-note",
        b"fixture exposure",
    ]
    if extra:
        argv.extend(extra)
    return argv


# ---------------------------------------------------------------------------
# KA-1 — VLM6-RV14-Q1-01 / OBS-08: fail-closed stderr through _printable_path
# ---------------------------------------------------------------------------


def test_score_missing_non_ascii_run_record_stderr_is_utf8_under_c_parent(tmp_path: Path) -> None:
    """score: missing café record prints real UTF-8 path bytes on stderr."""
    man = tmp_path / "man.json"
    man.write_text("{}", encoding="utf-8")
    missing = os.fsencode(tmp_path) + b"/missing-" + _CAFE_UTF8 + b".json"
    proc = _run_cli_bytes(
        [
            b"score",
            b"--manifest",
            os.fsencode(man),
            b"--run-record",
            missing,
        ]
    )
    assert proc.returncode == 2
    assert b"score: run record not found/unreadable: " in proc.stderr
    assert b"missing-" + _CAFE_UTF8 + b".json" in proc.stderr
    assert _SURROGATE_LEAK not in proc.stderr


def test_score_face_missing_non_ascii_run_record_stderr_is_utf8_under_c_parent(
    tmp_path: Path,
) -> None:
    """score-face: missing café record prints real UTF-8 path bytes on stderr."""
    man = tmp_path / "man.json"
    man.write_text("{}", encoding="utf-8")
    missing = os.fsencode(tmp_path) + b"/missing-" + _CAFE_UTF8 + b".json"
    proc = _run_cli_bytes(
        [
            b"score-face",
            b"--manifest",
            os.fsencode(man),
            b"--run-record",
            missing,
        ]
    )
    assert proc.returncode == 2
    assert b"score-face: run record not found/unreadable: " in proc.stderr
    assert b"missing-" + _CAFE_UTF8 + b".json" in proc.stderr
    assert _SURROGATE_LEAK not in proc.stderr


def test_draw_eval_split_missing_non_ascii_exposure_stderr_is_utf8_under_c_parent(
    tmp_path: Path,
) -> None:
    """draw-eval-split: missing café exposure file prints real UTF-8 path bytes."""
    man = _tiny_split_manifest(tmp_path)
    out = os.fsencode(tmp_path / "split.json")
    missing = os.fsencode(tmp_path) + b"/notes-" + _CAFE_UTF8 + b".txt"
    proc = _run_cli_bytes(
        _draw_argv(
            man,
            out,
            extra=[b"--exposure-file", missing],
        )
    )
    assert proc.returncode == 2
    assert b"draw-eval-split: exposure file not found/unreadable: " in proc.stderr
    assert b"notes-" + _CAFE_UTF8 + b".txt" in proc.stderr
    assert _SURROGATE_LEAK not in proc.stderr


# ---------------------------------------------------------------------------
# KA-2 — VLM6-RV14-Q2-03/04/05: pin the three unpinned stdout prints
# ---------------------------------------------------------------------------


def test_score_face_stdout_prints_printable_non_ascii_md_path(tmp_path: Path) -> None:
    """MUT b: print(md_path) without _printable_path must go red (TEST-15)."""
    from scene.tests.test_eval_harness_cli import _valid_face_manifest_and_record

    record, manifest = _valid_face_manifest_and_record()
    rec_b = os.fsencode(tmp_path) + b"/face-" + _CAFE_UTF8 + b".json"
    man = tmp_path / "man.json"
    man.write_text(json.dumps(manifest), encoding="utf-8")
    with open(rec_b, "wb") as fh:
        fh.write(json.dumps(record).encode("utf-8"))
    proc = _run_cli_bytes(
        [
            b"score-face",
            b"--manifest",
            os.fsencode(man),
            b"--run-record",
            rec_b,
        ]
    )
    assert proc.returncode == 0, proc.stderr
    expected = b"face-" + _CAFE_UTF8 + b"-face-report.md"
    first = proc.stdout.splitlines()[0]
    assert first.endswith(os.fsencode(expected))
    assert _BACKSLASHREPLACE_LIE not in proc.stdout


def test_draw_eval_split_stdout_prints_printable_non_ascii_out_path(tmp_path: Path) -> None:
    """MUT c: print(out) without _printable_path must go red (TEST-15)."""
    man = _tiny_split_manifest(tmp_path)
    out_b = os.fsencode(tmp_path) + b"/split-" + _CAFE_UTF8 + b".json"
    proc = _run_cli_bytes(_draw_argv(man, out_b))
    assert proc.returncode == 0, proc.stderr
    expected = b"split-" + _CAFE_UTF8 + b".json"
    first = proc.stdout.splitlines()[0]
    assert first.endswith(os.fsencode(expected))
    assert _BACKSLASHREPLACE_LIE not in proc.stdout


def test_score_audience_public_stdout_prints_printable_non_ascii_public_md(
    tmp_path: Path,
) -> None:
    """MUT d: print(public_md_path) without _printable_path must go red (TEST-15)."""
    from scene.tests.test_eval_harness_cli import _clean_score_manifest_and_record

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path, stem="run-src")
    rec_b = os.fsencode(tmp_path) + b"/run-" + _CAFE_UTF8 + b".json"
    with open(rec_b, "wb") as fh:
        fh.write(record_path.read_bytes())
    proc = _run_cli_bytes(
        [
            b"score",
            b"--manifest",
            os.fsencode(manifest_path),
            b"--run-record",
            rec_b,
            b"--audience",
            b"public",
        ]
    )
    assert proc.returncode == 0, proc.stderr
    expected = b"run-" + _CAFE_UTF8 + b"-report.public.md"
    first = proc.stdout.splitlines()[0]
    assert first.endswith(os.fsencode(expected))
    assert _BACKSLASHREPLACE_LIE not in proc.stdout


# ---------------------------------------------------------------------------
# KA-3 / KA-4 — VLM6-RV14-L-03 / Q2-06: fallback honesty + internals
# ---------------------------------------------------------------------------


def test_printable_path_fast_path_is_byte_identical_and_skips_fsencode(monkeypatch: pytest.MonkeyPatch) -> None:
    """MUT f: always-fsencode fallback must go red — fast path is identity."""
    calls: list[object] = []
    real = os.fsencode

    def spy(value: str | bytes | os.PathLike[str]) -> bytes:
        calls.append(value)
        return real(value)

    monkeypatch.setattr(os, "fsencode", spy)
    assert _printable_path("ascii-ok.md") == "ascii-ok.md"
    assert _printable_path("caf\u00e9.md") == "caf\u00e9.md"
    assert calls == []


def test_printable_path_fallback_uses_backslashreplace_not_replace() -> None:
    """MUT g: errors='replace' must go red — fallback keeps \\xHH."""
    out = _printable_path("run-caf\udce9-report.md")
    assert "\\xe9" in out
    assert "\ufffd" not in out


def test_printable_path_literal_xe9_and_undecodable_byte_differ_on_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OBS-08 / L-03: literal \\xe9 and a lone undecodable byte are not aliases."""
    buf = io.BytesIO()
    wrapper = io.TextIOWrapper(buf, encoding="utf-8", errors="backslashreplace", newline="")
    monkeypatch.setattr(sys, "stdout", wrapper)
    print(_printable_path("run-caf\\xe9-report.md"), flush=True)
    print(_printable_path("run-caf\udce9-report.md"), flush=True)
    wrapper.flush()
    raw = buf.getvalue()
    lines = raw.splitlines()
    assert len(lines) == 2
    assert lines[0] != lines[1]
    assert lines[0] == b"run-caf\\xe9-report.md"
    assert b"\\xe9" in lines[1]
    assert lines[1] != b"run-caf\\xe9-report.md"


# ---------------------------------------------------------------------------
# KA-5 — VLM6-RV14-Q2-07 / OBS-04: do not swallow unexpected reconfigure errors
# ---------------------------------------------------------------------------


def test_reconfigure_stdio_propagates_non_oserror_valueerror(monkeypatch: pytest.MonkeyPatch) -> None:
    """MUT n: bare except Exception must go red — RuntimeError propagates."""

    def explode(*, encoding: str, errors: str) -> None:
        raise RuntimeError("not an OSError or ValueError")

    fake = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict", newline="")
    fake.reconfigure = explode  # type: ignore[method-assign]
    monkeypatch.setattr(sys, "stdout", fake)
    with pytest.raises(RuntimeError, match="not an OSError or ValueError"):
        _reconfigure_stdio()


# ---------------------------------------------------------------------------
# KA-6 — VLM6-RV14-L-05 / TEST-15: restore process-global stdio codecs
# ---------------------------------------------------------------------------


def test_stdio_encoding_guard_restores_after_reconfigure(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-process _reconfigure_stdio must not leak utf-8 into the next test."""
    fake_out = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="surrogateescape", newline="")
    fake_err = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="surrogateescape", newline="")
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stderr", fake_err)
    before = (sys.stdout.encoding, sys.stdout.errors, sys.stderr.encoding, sys.stderr.errors)
    with _stdio_encoding_guard():
        _reconfigure_stdio()
        assert sys.stdout.encoding.lower() in {"utf-8", "utf8"}
        assert sys.stdout.errors == "backslashreplace"
    after = (sys.stdout.encoding, sys.stdout.errors, sys.stderr.encoding, sys.stderr.errors)
    assert after == before


def test_reconfigure_stdio_still_zero_arg_and_sets_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    """HARD COMPAT: _reconfigure_stdio() stays zero-arg with current effect."""
    fake_out = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict", newline="")
    fake_err = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict", newline="")
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stderr", fake_err)
    with _stdio_encoding_guard():
        _reconfigure_stdio()
        assert fake_out.encoding.lower() in {"utf-8", "utf8"}
        assert fake_err.encoding.lower() in {"utf-8", "utf8"}
        assert fake_out.errors == "backslashreplace"
        assert fake_err.errors == "backslashreplace"
