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

from scene.tests.test_eval_harness_cli import (
    _assert_child_ascii_locale,
    _c_locale_child_env,
)
from scripts.eval_harness.cli import (
    _UNDECODABLE_PATH_PREFIX,
    _printable_path,
    _reconfigure_stdio,
    _stdio_encoding_guard,
)

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_CAFE_UTF8 = b"caf\xc3\xa9"
_CAFE_LATIN1 = b"caf\xe9"  # lone 0xe9 — invalid UTF-8 on every host
_SURROGATE_LEAK = b"\\udc"
_BACKSLASHREPLACE_LIE = b"\\xe9"


_CURRENT_REQUEST: pytest.FixtureRequest | None = None


def _argv_has_utf8_non_ascii(argv: list[bytes] | None) -> bool:
    if not argv:
        return False
    for part in argv:
        try:
            text = part.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if any(ord(ch) > 127 for ch in text):
            return True
    return False


def _enforce_surrogate_argv_marker(argv: list[bytes] | None) -> None:
    """FAIL unmarked C-locale café-argv children (C-01 / sr-001 / PRINCIPLE 10)."""
    if not _argv_has_utf8_non_ascii(argv):
        return
    req = _CURRENT_REQUEST
    name = req.node.name if req is not None else "<no-pytest-request>"
    marked = (
        req is not None
        and req.node.get_closest_marker("requires_surrogate_argv") is not None
    )
    if marked:
        return
    pytest.fail(
        f"{name}: C-locale child with UTF-8 non-ASCII argv requires "
        "@pytest.mark.requires_surrogate_argv (AGT-06 / PRINCIPLE 10); "
        "a name substring is not a gate (sr-001)"
    )


def apply_surrogate_argv_gate(request: pytest.FixtureRequest) -> None:
    """Fixture-time Darwin skip bound to the marker, not a test name (C-01)."""
    global _CURRENT_REQUEST
    _CURRENT_REQUEST = request
    if request.node.get_closest_marker("requires_surrogate_argv") is None:
        return
    if _host_can_produce_surrogate_escaped_argv():
        return
    pytest.skip(_SURROGATE_ARGV_SKIP)


def _run_python_bytes(
    script: bytes,
    argv: list[bytes] | None = None,
    *,
    cwd: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    _assert_child_ascii_locale()
    _enforce_surrogate_argv_marker(argv)
    env = _c_locale_child_env()
    # load_manifest may warn with the raw argv path (manifest.py; not this lane).
    env["PYTHONWARNINGS"] = "ignore"
    return subprocess.run(
        [os.fsencode(sys.executable), b"-c", script, *(argv or [])],
        cwd=cwd if cwd is not None else os.fsencode(_SERVICE_ROOT),
        env=env,
        capture_output=True,
    )


def _run_cli_bytes(
    argv: list[bytes],
    *,
    setup: bytes = b"",
    cwd: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    code = setup + b"import sys; from scripts.eval_harness.cli import main; main(sys.argv[1:])"
    return _run_python_bytes(code, argv, cwd=cwd)


_SURROGATE_ARGV_SKIP = (
    "host C-locale child does not produce PEP 383 surrogate-escaped argv "
    "(measured: valid-UTF-8 café bytes arrive as clean unicode, not surrogates); "
    "product _printable_path café-from-C-locale recovery is untested "
    "(AGT-06 / VLM6-RV15-L-01)"
)
_SURROGATE_ARGV_PROBE: bool | None = None


def _host_can_produce_surrogate_escaped_argv() -> bool:
    """Measure whether a C-locale child receives café UTF-8 as PEP 383 surrogates.

    Darwin hard-wires getfilesystemencoding() to utf-8, so café arrives clean.
    Do not branch on sys.platform — probe a real child argv (AGT-06).
    """
    global _SURROGATE_ARGV_PROBE
    if _SURROGATE_ARGV_PROBE is None:
        script = (
            b"import sys;"
            b"p=sys.argv[1];"
            b"sys.stdout.buffer.write("
            b"b'1' if any(0xDC00 <= ord(c) <= 0xDCFF for c in p) else b'0')"
        )
        proc = _run_python_bytes(script, [_CAFE_UTF8])
        _SURROGATE_ARGV_PROBE = proc.returncode == 0 and proc.stdout == b"1"
    return _SURROGATE_ARGV_PROBE


@pytest.fixture(autouse=True)
def _skip_c_parent_when_host_cannot_surrogate_escape_argv(
    request: pytest.FixtureRequest,
) -> None:
    apply_surrogate_argv_gate(request)


def _documented_round_trip(rendered: str) -> bytes:
    """Exactly the ``_printable_path`` / README round-trip recipe (rg-006)."""
    if rendered.startswith(_UNDECODABLE_PATH_PREFIX):
        body = rendered[len(_UNDECODABLE_PATH_PREFIX) :]
        return body.encode("ascii").decode("unicode_escape").encode("latin-1")
    if rendered.startswith("\\") and rendered.lstrip("\\").startswith(_UNDECODABLE_PATH_PREFIX):
        return rendered[1:].encode("utf-8")
    return rendered.encode("utf-8")


def _cafe_named(tmp_path: Path, stem: bytes, suffix: bytes = b".json") -> bytes:
    return os.fsencode(tmp_path) + b"/" + stem + b"-" + _CAFE_UTF8 + suffix


_TINY_SPLIT_PAYLOAD = {
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

# load_manifest uses read_text; this only trips the post-load Path.read_bytes hash pin.
_INJECT_MANIFEST_READ_OSERROR = b"""
from pathlib import Path as _InjectPath
import sys as _inject_sys
_inject_orig = _InjectPath.read_bytes
_inject_target = _InjectPath(_inject_sys.argv[_inject_sys.argv.index("--manifest") + 1]).resolve()
def _inject_boom(self, *args, **kwargs):
    if _InjectPath(self).resolve() == _inject_target:
        raise OSError("injected")
    return _inject_orig(self, *args, **kwargs)
_InjectPath.read_bytes = _inject_boom
"""

_RUN_SCORE_GATE_SCRIPT = b"""
import sys
from argparse import Namespace
from scripts.eval_harness import cli as _cli

_cli._reconfigure_stdio()

def _fake_fetch(args):
    return list(sys.argv[1:])

def _fake_score(args):
    raise _cli.ScoreGateError("score must-right failures gate: synthetic")

_cli._cmd_fetch = _fake_fetch
_cli._cmd_score = _fake_score
_cli._cmd_run(Namespace(check_determinism=False, provider=None, audience="local"))
"""


def _tiny_split_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "split-man.json"
    path.write_text(json.dumps(_TINY_SPLIT_PAYLOAD), encoding="utf-8")
    return path


def _tiny_split_manifest_bytes(dest: bytes) -> bytes:
    with open(dest, "wb") as fh:
        fh.write(json.dumps(_TINY_SPLIT_PAYLOAD).encode("utf-8"))
    return dest


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


@pytest.mark.requires_surrogate_argv
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


@pytest.mark.requires_surrogate_argv
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


@pytest.mark.requires_surrogate_argv
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


@pytest.mark.requires_surrogate_argv
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


@pytest.mark.requires_surrogate_argv
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


@pytest.mark.requires_surrogate_argv
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


# ---------------------------------------------------------------------------
# MA — VLM6-RV15-Q2-03: mutation-kill the seven surviving _printable_path sites
# ---------------------------------------------------------------------------


@pytest.mark.requires_surrogate_argv
def test_run_score_gate_non_ascii_record_stderr_is_utf8_under_c_parent(tmp_path: Path) -> None:
    """MUT 2011: unwrap _printable_path(record_path) on RUN_RECORD stderr -> red."""
    cafe_rec = _cafe_named(tmp_path, b"rec")
    proc = _run_python_bytes(_RUN_SCORE_GATE_SCRIPT, [cafe_rec])
    assert proc.returncode != 0
    rec_line = next(ln for ln in proc.stderr.splitlines() if b"run score gate failed:" in ln)
    assert _CAFE_UTF8 in rec_line
    assert _SURROGATE_LEAK not in proc.stderr


@pytest.mark.requires_surrogate_argv
def test_draw_check_missing_non_ascii_sealed_split_stderr_is_utf8_under_c_parent(
    tmp_path: Path,
) -> None:
    """MUT 2724: unwrap _printable_path(out) on sealed-unreadable -> red."""
    man = _tiny_split_manifest(tmp_path)
    missing = _cafe_named(tmp_path, b"missing")
    proc = _run_cli_bytes(_draw_argv(man, missing, extra=[b"--check"]))
    assert proc.returncode == 2
    assert b"draw-eval-split: sealed split not found/unreadable: " in proc.stderr
    assert _CAFE_UTF8 in proc.stderr
    assert _SURROGATE_LEAK not in proc.stderr


@pytest.mark.requires_surrogate_argv
def test_draw_check_non_object_non_ascii_sealed_split_stderr_is_utf8_under_c_parent(
    tmp_path: Path,
) -> None:
    """MUT 2730: unwrap _printable_path(out) on sealed-not-object -> red."""
    man = _tiny_split_manifest(tmp_path)
    out_b = _cafe_named(tmp_path, b"split")
    with open(out_b, "wb") as fh:
        fh.write(b"[]\n")
    proc = _run_cli_bytes(_draw_argv(man, out_b, extra=[b"--check"]))
    assert proc.returncode == 2
    assert b"draw-eval-split: sealed split is not a JSON object: " in proc.stderr
    assert _CAFE_UTF8 in proc.stderr
    assert _SURROGATE_LEAK not in proc.stderr


@pytest.mark.requires_surrogate_argv
def test_draw_check_cannot_read_non_ascii_manifest_stderr_is_utf8_under_c_parent(
    tmp_path: Path,
) -> None:
    """MUT 2738: unwrap _printable_path(args.manifest) on check cannot-read -> red."""
    man_b = _tiny_split_manifest_bytes(_cafe_named(tmp_path, b"man"))
    out = tmp_path / "sealed.json"
    out.write_text('{"ok": true}\n', encoding="utf-8")
    argv = _draw_argv(tmp_path / "unused.json", os.fsencode(out), extra=[b"--check"])
    argv[argv.index(b"--manifest") + 1] = man_b
    proc = _run_cli_bytes(argv, setup=_INJECT_MANIFEST_READ_OSERROR)
    assert proc.returncode == 2
    line = next(ln for ln in proc.stderr.splitlines() if b"cannot read manifest:" in ln)
    assert _CAFE_UTF8 in line
    assert _SURROGATE_LEAK not in proc.stderr


@pytest.mark.requires_surrogate_argv
def test_draw_refuse_overwrite_non_ascii_sealed_split_stderr_is_utf8_under_c_parent(
    tmp_path: Path,
) -> None:
    """MUT 2760: unwrap _printable_path(out) on overwrite refuse -> red."""
    man = _tiny_split_manifest(tmp_path)
    out_b = _cafe_named(tmp_path, b"split")
    with open(out_b, "wb") as fh:
        fh.write(b"{}\n")
    proc = _run_cli_bytes(_draw_argv(man, out_b))
    assert proc.returncode == 3
    assert b"refusing to overwrite sealed split " in proc.stderr
    assert _CAFE_UTF8 in proc.stderr
    assert _SURROGATE_LEAK not in proc.stderr


@pytest.mark.requires_surrogate_argv
def test_draw_cannot_read_non_ascii_manifest_stderr_is_utf8_under_c_parent(
    tmp_path: Path,
) -> None:
    """MUT 2768: unwrap _printable_path(args.manifest) on draw cannot-read -> red."""
    man_b = _tiny_split_manifest_bytes(_cafe_named(tmp_path, b"man"))
    out_b = os.fsencode(tmp_path / "split.json")
    argv = _draw_argv(tmp_path / "unused.json", out_b)
    man_idx = argv.index(b"--manifest")
    argv[man_idx + 1] = man_b
    proc = _run_cli_bytes(argv, setup=_INJECT_MANIFEST_READ_OSERROR)
    assert proc.returncode == 2
    line = next(ln for ln in proc.stderr.splitlines() if b"cannot read manifest:" in ln)
    assert _CAFE_UTF8 in line
    assert _SURROGATE_LEAK not in proc.stderr
    assert not (tmp_path / "split.json").exists()


@pytest.mark.requires_surrogate_argv
def test_draw_cannot_write_non_ascii_sealed_split_stderr_is_utf8_under_c_parent(
    tmp_path: Path,
) -> None:
    """MUT 2787: unwrap _printable_path(out) on cannot-write -> red."""
    man = _tiny_split_manifest(tmp_path)
    out_b = _cafe_named(tmp_path, b"split", suffix=b"")
    os.mkdir(out_b)
    proc = _run_cli_bytes(_draw_argv(man, out_b, extra=[b"--force"]))
    assert proc.returncode == 2
    prefix = b"draw-eval-split: cannot write sealed split: "
    line = next(ln for ln in proc.stderr.splitlines() if prefix in ln)
    rest = line.split(prefix, 1)[1]
    path_part = rest.split(b": ", 1)[0]
    assert _CAFE_UTF8 in path_part
    assert _SURROGATE_LEAK not in proc.stderr


# ---------------------------------------------------------------------------
# MA — VLM6-RV15-L-04: gate_failures accumulator must use _printable_path
# ---------------------------------------------------------------------------


@pytest.mark.requires_surrogate_argv
def test_run_score_gate_summary_non_ascii_record_is_utf8_under_c_parent(tmp_path: Path) -> None:
    """MUT L-04: raw record_path in gate_failures.append -> summary leaks / no café."""
    ascii_rec = os.fsencode(tmp_path / "rec-ascii.json")
    cafe_rec = _cafe_named(tmp_path, b"rec")
    proc = _run_python_bytes(_RUN_SCORE_GATE_SCRIPT, [ascii_rec, cafe_rec])
    assert proc.returncode != 0
    summary = next(ln for ln in proc.stderr.splitlines() if b"run score gates failed:" in ln)
    assert _CAFE_UTF8 in summary
    assert _SURROGATE_LEAK not in proc.stderr


# ---------------------------------------------------------------------------
# MA — VLM6-RV15-Q1-02: {exc} tail must not leak surrogates (2786 write-split)
# ---------------------------------------------------------------------------


@pytest.mark.requires_surrogate_argv
def test_draw_cannot_write_non_ascii_exc_tail_has_no_surrogate_under_c_parent(
    tmp_path: Path,
) -> None:
    """MUT Q1-02: raw {exc} (OSError filename) on cannot-write -> \\udc leak."""
    man = _tiny_split_manifest(tmp_path)
    out_b = _cafe_named(tmp_path, b"split", suffix=b"")
    os.mkdir(out_b)
    proc = _run_cli_bytes(_draw_argv(man, out_b, extra=[b"--force"]))
    assert proc.returncode == 2
    assert b"cannot write sealed split:" in proc.stderr
    assert _SURROGATE_LEAK not in proc.stderr
    assert _CAFE_UTF8 in proc.stderr


# ---------------------------------------------------------------------------
# MC — VLM6-RV15-Q2-01 / L-02: invertible doubling + out-of-band marker
# ---------------------------------------------------------------------------

_Q2_01_RAW = b"a\\b-caf\xe9.json"
_Q2_01_SURROGATE = "a\\b-caf\udce9.json"
_L02_MARKED_NAME = b"undecodable:xyz.json"
_SCORE_UNREADABLE_PREFIX = b"score: run record not found/unreadable: "


def test_printable_path_backslash_and_undecodable_byte_round_trips() -> None:
    """Q2-01: MUT_drop_doubling must go red — \\\\ and \\xHH stay invertible."""
    rendered = _printable_path(_Q2_01_SURROGATE)
    assert _documented_round_trip(rendered) == _Q2_01_RAW


def test_printable_path_marker_and_undecodable_differ_on_cli_stderr(tmp_path: Path) -> None:
    """L-02: real undecodable: name and a fallback path must not alias (TEST-15)."""
    cwd_b = os.fsencode(tmp_path)
    (tmp_path / "man.json").write_text("{}", encoding="utf-8")
    for name in (_L02_MARKED_NAME, _Q2_01_RAW):
        with open(cwd_b + b"/" + name, "wb") as fh:
            fh.write(b"not-json")

    def _stderr_path(name: bytes) -> bytes:
        proc = _run_cli_bytes(
            [b"score", b"--manifest", b"man.json", b"--run-record", name],
            cwd=cwd_b,
        )
        assert proc.returncode == 2, proc.stderr
        line = next(ln for ln in proc.stderr.splitlines() if _SCORE_UNREADABLE_PREFIX in ln)
        return line.split(_SCORE_UNREADABLE_PREFIX, 1)[1]

    marked = _stderr_path(_L02_MARKED_NAME)
    undec = _stderr_path(_Q2_01_RAW)
    assert marked != undec
    assert marked == b"\\" + _L02_MARKED_NAME
    assert _documented_round_trip(marked.decode("ascii")) == _L02_MARKED_NAME
    assert _documented_round_trip(undec.decode("ascii")) == _Q2_01_RAW


# ---------------------------------------------------------------------------
# ME — VLM6-RV15-Q2-04: imported C-locale helpers, no decorative fork
# ---------------------------------------------------------------------------


def test_stdio_module_uses_imported_c_locale_helpers() -> None:
    """Q2-04 / TEST-15: no private C-locale env fork (sr-001)."""
    import scene.tests.test_eval_harness_cli as cli_mod
    import scene.tests.test_eval_harness_cli_stdio as stdio

    assert stdio._c_locale_child_env is cli_mod._c_locale_child_env
    assert stdio._assert_child_ascii_locale is cli_mod._assert_child_ascii_locale
    assert not hasattr(stdio, "_ASCII_LOCALE_ENV")
    assert not hasattr(stdio, "_ASCII_PARENT_KEYS")


def test_run_python_bytes_invokes_imported_assert_child_ascii_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q2-04: every child process is gated by imported _assert_child_ascii_locale."""
    calls: list[int] = []

    def _spy() -> None:
        calls.append(1)

    monkeypatch.setattr(sys.modules[__name__], "_assert_child_ascii_locale", _spy)
    proc = _run_python_bytes(b"import sys; sys.stdout.buffer.write(b'ok')")
    assert calls == [1], "child runner never called imported _assert_child_ascii_locale (Q2-04)"
    assert proc.returncode == 0
    assert proc.stdout == b"ok"


# ---------------------------------------------------------------------------
# ME — VLM6-RV15-L-01: host-independent 0xe9 oracle + named residual gap
# ---------------------------------------------------------------------------


def test_printable_path_latin1_byte_uses_undecodable_fallback() -> None:
    """L-01: lone 0xe9 hits _printable_path fallback on every host (TEST-15)."""
    text = os.fsdecode(_CAFE_LATIN1 + b".json")
    out = _printable_path(text)
    assert out.startswith(_UNDECODABLE_PATH_PREFIX)
    assert "\\xe9" in out
    assert _documented_round_trip(out) == _CAFE_LATIN1 + b".json"


def test_score_missing_latin1_run_record_stderr_uses_undecodable_prefix(
    tmp_path: Path,
) -> None:
    """L-01: 0xe9 CLI argv exercises undecodable: even when fs encoding is utf-8."""
    man = tmp_path / "man.json"
    man.write_text("{}", encoding="utf-8")
    missing = os.fsencode(tmp_path) + b"/missing-" + _CAFE_LATIN1 + b".json"
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
    line = next(ln for ln in proc.stderr.splitlines() if _SCORE_UNREADABLE_PREFIX in ln)
    rendered = line.split(_SCORE_UNREADABLE_PREFIX, 1)[1]
    assert rendered.startswith(_UNDECODABLE_PATH_PREFIX.encode("ascii"))
    assert b"\\xe9" in rendered
    assert _documented_round_trip(rendered.decode("ascii")) == missing


# ---------------------------------------------------------------------------
# Lane B — VLM6-RV16-C-01: marker gate, not a name substring (PRINCIPLE 10)
# ---------------------------------------------------------------------------


def test_c01_autouse_does_not_key_on_under_c_parent_substring() -> None:
    """C-01 / PRINCIPLE 10: a rename must not drop the Darwin skip."""
    src = Path(__file__).read_text(encoding="utf-8")
    start = src.index("def apply_surrogate_argv_gate")
    end = src.index("\ndef ", start + 1)
    body = src[start:end]
    assert "under_c_parent" not in body
    assert "requires_surrogate_argv" in body
    assert "@pytest.mark.requires_surrogate_argv" in src


def test_c01_requires_surrogate_argv_marker_registered(pytestconfig: pytest.Config) -> None:
    """C-01: the marker is a real registered pytest marker, not a comment."""
    markers = pytestconfig.getini("markers")
    assert any(str(m).startswith("requires_surrogate_argv") for m in markers), markers


def test_c01_under_c_parent_tests_carry_the_marker() -> None:
    """C-01: every leftover *_under_c_parent name is also explicitly marked."""
    this = sys.modules[__name__]
    missing: list[str] = []
    for name, obj in list(this.__dict__.items()):
        if not name.startswith("test_") or name.startswith("test_c01_"):
            continue
        if "under_c_parent" not in name:
            continue
        marks = getattr(obj, "pytestmark", [])
        if not isinstance(marks, list):
            marks = [marks]
        if not any(getattr(m, "name", None) == "requires_surrogate_argv" for m in marks):
            missing.append(name)
    assert missing == []


def test_c01_unmarked_utf8_cafe_argv_fails_enforcement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 16 rename: unmarked café argv must FAIL, not pass (sr-001)."""

    class _Node:
        name = "test_score_missing_non_ascii_run_record_stderr_is_utf8_c_locale"

        def get_closest_marker(self, name: str) -> object | None:
            return None

    class _Req:
        node = _Node()

    monkeypatch.setattr(sys.modules[__name__], "_CURRENT_REQUEST", _Req())
    with pytest.raises(pytest.fail.Exception, match="requires_surrogate_argv"):
        _enforce_surrogate_argv_marker([b"score", b"caf\xc3\xa9.json"])


def test_c01_marked_rename_skips_when_probe_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 16: force probe False + rename; marker still SKIPS (AGT-06)."""

    class _Node:
        name = "test_score_missing_non_ascii_run_record_stderr_is_utf8_c_locale"

        def get_closest_marker(self, name: str) -> object | None:
            return object() if name == "requires_surrogate_argv" else None

    class _Req:
        node = _Node()

    monkeypatch.setattr(
        sys.modules[__name__],
        "_host_can_produce_surrogate_escaped_argv",
        lambda: False,
    )
    with pytest.raises(pytest.skip.Exception, match="PEP 383"):
        apply_surrogate_argv_gate(_Req())  # type: ignore[arg-type]
