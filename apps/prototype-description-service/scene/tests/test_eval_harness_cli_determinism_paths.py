"""VLM6-RV16-L-01: determinism-path interpolations must go through _printable_path.

Lane MF owns this file. Do not edit test_eval_harness_cli.py /
test_eval_harness_cli_stdio.py / test_eval_harness_cli_stdout.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scene.tests.test_eval_harness_cli_stdio import (
    _assert_child_ascii_locale,
    _c_locale_child_env,
    _enforce_surrogate_argv_marker,
    apply_surrogate_argv_gate,
)
from scripts.eval_harness.cli import _UNDECODABLE_PATH_PREFIX

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_SURROGATE_LEAK = b"\\udc"
_EXPECT_MARKER = b"matches --expect-report "

# True operator argv (C-locale child) so Path(sys.argv[1]) is the `resolved` site.
_CHECK_SCRIPT = b"""
import sys
from pathlib import Path
from scripts.eval_harness.cli import _check_expect_report, _reconfigure_stdio

_reconfigure_stdio()
_check_expect_report(
    sys.argv[2],
    Path(sys.argv[1]),
    label="score",
    regime="probe",
    artifact_dir=Path(sys.argv[3]),
)
"""


@pytest.fixture(autouse=True)
def _surrogate_argv_gate(request: pytest.FixtureRequest) -> None:
    apply_surrogate_argv_gate(request)


def _run_python_bytes(
    script: bytes,
    argv: list[bytes] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    _assert_child_ascii_locale()
    _enforce_surrogate_argv_marker(argv)
    return subprocess.run(
        [os.fsencode(sys.executable), b"-c", script, *(argv or [])],
        cwd=os.fsencode(_SERVICE_ROOT),
        env=_c_locale_child_env(),
        capture_output=True,
    )


def _run_check(report_path: bytes, body: bytes, artifact_dir: bytes) -> subprocess.CompletedProcess[bytes]:
    return _run_python_bytes(_CHECK_SCRIPT, [report_path, body, artifact_dir])


def _write_bytes(path_b: bytes, payload: bytes) -> bytes:
    os.makedirs(os.path.dirname(path_b), exist_ok=True)
    with open(path_b, "wb") as fh:
        fh.write(payload)
    return path_b


def _undecodable_cafe_report(tmp_path: Path, stem: bytes) -> bytes:
    return os.fsencode(tmp_path) + b"/" + stem + b"-caf\xe9-report.json"


def _literal_udce9_report(tmp_path: Path, stem: bytes) -> bytes:
    return os.fsencode(tmp_path) + b"/" + stem + b"-caf\\udce9-report.json"


def _documented_round_trip(rendered: str) -> bytes:
    """Exactly the ``_printable_path`` / README round-trip recipe (rg-006)."""
    if rendered.startswith(_UNDECODABLE_PATH_PREFIX):
        body = rendered[len(_UNDECODABLE_PATH_PREFIX) :]
        return body.encode("ascii").decode("unicode_escape").encode("latin-1")
    if rendered.startswith("\\") and rendered.lstrip("\\").startswith(_UNDECODABLE_PATH_PREFIX):
        return rendered[1:].encode("utf-8")
    return rendered.encode("utf-8")


def _emitted_expect_path(proc: subprocess.CompletedProcess[bytes]) -> bytes:
    line = next(ln for ln in proc.stdout.splitlines() if _EXPECT_MARKER in ln)
    return line.split(_EXPECT_MARKER, 1)[1]


def test_expect_report_surrogate_argv_emits_undecodable_not_udc(tmp_path: Path) -> None:
    """MUT cli.py:1311 — raw {resolved} on the match line leaks \\udc (TEST-15 / rg-006)."""
    raw = _undecodable_cafe_report(tmp_path, b"anchor")
    _write_bytes(raw, b"{}")
    proc = _run_check(raw, b"{}", os.fsencode(tmp_path))
    assert proc.returncode == 0, proc.stderr
    emitted = _emitted_expect_path(proc)
    assert _SURROGATE_LEAK not in emitted, emitted
    assert _UNDECODABLE_PATH_PREFIX.encode("ascii") in emitted, emitted
    assert _documented_round_trip(emitted.decode("ascii")) == raw


def test_expect_report_literal_udce9_and_undecodable_byte_differ(tmp_path: Path) -> None:
    """Aliasing: latin-1 0xe9 argv and a literal \\udce9 name must not share a wire form."""
    latin1 = _undecodable_cafe_report(tmp_path, b"alias")
    literal = _literal_udce9_report(tmp_path, b"alias")
    _write_bytes(latin1, b"{}")
    _write_bytes(literal, b"{}")
    latin1_proc = _run_check(latin1, b"{}", os.fsencode(tmp_path))
    literal_proc = _run_check(literal, b"{}", os.fsencode(tmp_path))
    assert latin1_proc.returncode == 0, latin1_proc.stderr
    assert literal_proc.returncode == 0, literal_proc.stderr
    latin1_text = _emitted_expect_path(latin1_proc)
    literal_text = _emitted_expect_path(literal_proc)
    assert latin1_text != literal_text, latin1_text
    assert _UNDECODABLE_PATH_PREFIX.encode("ascii") in latin1_text, latin1_text
    assert _SURROGATE_LEAK not in latin1_text, latin1_text
    assert _documented_round_trip(latin1_text.decode("ascii")) == latin1
    assert _documented_round_trip(literal_text.decode("ascii")) == literal


def test_determinism_module_uses_imported_c_locale_helpers() -> None:
    """C-02 / TEST-15: no private C-locale env fork (sr-001)."""
    import scene.tests.test_eval_harness_cli_determinism_paths as det
    import scene.tests.test_eval_harness_cli_stdio as stdio

    assert det._c_locale_child_env is stdio._c_locale_child_env
    assert det._assert_child_ascii_locale is stdio._assert_child_ascii_locale
    assert not hasattr(det, "_ASCII_LOCALE_ENV")
    assert not hasattr(det, "_ASCII_PARENT_KEYS")


def test_run_check_invokes_imported_assert_child_ascii_locale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """C-02: determinism child runner is gated by imported _assert_child_ascii_locale."""
    calls: list[int] = []

    def _spy() -> None:
        calls.append(1)

    monkeypatch.setattr(sys.modules[__name__], "_assert_child_ascii_locale", _spy)
    raw = _undecodable_cafe_report(tmp_path, b"assert-gate")
    _write_bytes(raw, b"{}")
    proc = _run_check(raw, b"{}", os.fsencode(tmp_path))
    assert calls == [1], "child runner never called imported _assert_child_ascii_locale (C-02)"
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# Lane B — VLM6-RV16-B-01: kill the six payload_path wraps (TEST-15)
# ---------------------------------------------------------------------------

_DET_PAYLOAD_DRIVER = b"""
import os
import sys
from pathlib import Path
from scripts.eval_harness.cli import _reconfigure_stdio, _run_determinism_children
from scripts.eval_harness.report import build_reports

_reconfigure_stdio()
tmpdir = sys.argv[1]
branch = sys.argv[2]
os.environ["TMPDIR"] = tmpdir
os.environ["TEMP"] = tmpdir
os.environ["TMP"] = tmpdir

_SCRIPTS = {
    "missing": "import sys; raise SystemExit(0)",
    "unreadable": "import sys; open(sys.argv[1], 'w').write('{}')",
    "unparseable": "import sys; open(sys.argv[1], 'w').write('not-json')",
    "keys": "import sys; open(sys.argv[1], 'w').write('{}')",
    "types": "import sys; open(sys.argv[1], 'w').write('{\\\"json\\\": 1, \\\"md\\\": 2}')",
    "provenance": "import sys; open(sys.argv[1], 'w').write('{\\\"json\\\": \\\"\\\", \\\"md\\\": \\\"\\\"}')",
}

if branch == "unreadable":
    def _boom(self, *args, **kwargs):
        raise OSError("injected-unreadable")
    Path.read_text = _boom  # type: ignore[method-assign]

_run_determinism_children(
    _SCRIPTS[branch],
    [],
    label="score",
    base_json="{}",
    base_md="",
    artifact_dir=Path(tmpdir),
    expected_build_reports_file=build_reports.__code__.co_filename,
)
sys.stdout.buffer.write(b"UNEXPECTED_PASS\\n")
"""

_PAYLOAD_BRANCHES = (
    ("missing", b"payload file missing"),
    ("unreadable", b"payload file unreadable"),
    ("unparseable", b"payload file unparseable"),
    ("keys", b"expected object with"),
    ("types", b"'json' and 'md' must be"),
    ("provenance", b"payload missing"),
)


@pytest.mark.parametrize("branch,needle", _PAYLOAD_BRANCHES, ids=[b for b, _ in _PAYLOAD_BRANCHES])
def test_determinism_payload_path_printable_under_latin1_tmpdir(
    tmp_path: Path, branch: str, needle: bytes
) -> None:
    """MUT cli.py:1144/1152/1160/1166/1174/1184 — unwrap _printable_path(payload_path) -> \\udc."""
    tmpdir_b = os.fsencode(tmp_path) + b"/tmpdir-caf\xe9"
    os.makedirs(tmpdir_b, exist_ok=True)
    proc = _run_python_bytes(_DET_PAYLOAD_DRIVER, [tmpdir_b, branch.encode("ascii")])
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert b"UNEXPECTED_PASS" not in proc.stdout
    blob = proc.stderr + proc.stdout
    assert needle in blob, blob
    assert _SURROGATE_LEAK not in blob, blob
    assert _UNDECODABLE_PATH_PREFIX.encode("ascii") in blob, blob
    assert b"\\xe9" in blob, blob
