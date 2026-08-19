"""VLM6-RV16-L-01: determinism-path interpolations must go through _printable_path.

Lane MF owns this file. Do not edit test_eval_harness_cli.py /
test_eval_harness_cli_stdio.py / test_eval_harness_cli_stdout.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.eval_harness.cli import _UNDECODABLE_PATH_PREFIX

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


def _c_locale_child_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _ASCII_PARENT_KEYS:
        env.pop(key, None)
    env.update(_ASCII_LOCALE_ENV)
    extra = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SERVICE_ROOT) + (os.pathsep + extra if extra else "")
    return env


def _run_check(report_path: bytes, body: bytes, artifact_dir: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            os.fsencode(sys.executable),
            b"-c",
            _CHECK_SCRIPT,
            report_path,
            body,
            artifact_dir,
        ],
        cwd=os.fsencode(_SERVICE_ROOT),
        env=_c_locale_child_env(),
        capture_output=True,
    )


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
