"""VLM6-RV16-B-05 / B-03: manifest.py operator-path emission must use printable paths.

Lane C owns this file. Do not edit test_eval_harness_cli.py / cli.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = (
    _SERVICE_ROOT
    / "scripts"
    / "eval_harness"
    / "tests"
    / "fixtures"
    / "provenanced_min.json"
)
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
_UNDECODABLE = b"undecodable:"
_SURROGATE_LEAK = b"\\udc"
_CAFE_LATIN1 = b"caf\xe9"
_SURROGATE_ARGV_SKIP = (
    "host C-locale child does not produce PEP 383 surrogate-escaped argv "
    "for latin-1 0xe9 (measured: byte arrives as clean unicode, not surrogates); "
    "product manifest printable-path latin-1 recovery is untested "
    "(AGT-06 / VLM6-RV16-B-05)"
)
_SURROGATE_ARGV_PROBE: bool | None = None

_LOAD_METADATA_ONLY = b"""
import os, sys, warnings
warnings.simplefilter("always")
os.environ.pop("GOLDEN_IMAGES_DIR", None)
from scripts.eval_harness.manifest import load_manifest
load_manifest(
    sys.argv[1],
    skip_hash_verification=True,
    hash_skip_reason="probe",
    metadata_only=True,
)
"""
_LOAD_SKIP_HASH = b"""
import os, sys, warnings
warnings.simplefilter("always")
os.environ.pop("GOLDEN_IMAGES_DIR", None)
from scripts.eval_harness.manifest import load_manifest
load_manifest(sys.argv[1], skip_hash_verification=True, hash_skip_reason="probe")
"""
_LOAD_MISSING = b"""
import sys
from scripts.eval_harness.manifest import ManifestError, load_manifest
try:
    load_manifest(sys.argv[1])
except ManifestError as exc:
    print(str(exc), file=sys.stderr)
"""


def _c_locale_child_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _ASCII_PARENT_KEYS:
        env.pop(key, None)
    env.update(_ASCII_LOCALE_ENV)
    extra = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SERVICE_ROOT) + (os.pathsep + extra if extra else "")
    env["PYTHONWARNINGS"] = "always"
    env.pop("GOLDEN_IMAGES_DIR", None)
    return env


def _run_c_child(script: bytes, argv: list[bytes]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [os.fsencode(sys.executable), b"-c", script, *argv],
        cwd=os.fsencode(_SERVICE_ROOT),
        env=_c_locale_child_env(),
        capture_output=True,
    )


def _host_can_produce_latin1_surrogate_argv() -> bool:
    """Measure whether a C-locale child receives 0xe9 as a PEP 383 surrogate.

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
        proc = _run_c_child(script, [_CAFE_LATIN1])
        _SURROGATE_ARGV_PROBE = proc.returncode == 0 and proc.stdout == b"1"
    return _SURROGATE_ARGV_PROBE


@pytest.fixture(autouse=True)
def _skip_when_host_cannot_surrogate_escape_latin1() -> None:
    if _host_can_produce_latin1_surrogate_argv():
        return
    pytest.skip(_SURROGATE_ARGV_SKIP)


def _latin1_cafe_dir(tmp_path: Path) -> bytes:
    dir_b = os.fsencode(tmp_path) + b"/latin1-" + _CAFE_LATIN1
    os.mkdir(dir_b)
    return dir_b


def _write_latin1_manifest(tmp_path: Path) -> bytes:
    man_b = _latin1_cafe_dir(tmp_path) + b"/man-" + _CAFE_LATIN1 + b".json"
    with open(man_b, "wb") as fh:
        fh.write(_FIXTURE.read_bytes())
    return man_b


def _assert_printable_stderr(stderr: bytes) -> None:
    """OBS-08 / TEST-15: operator path on C-locale stderr is printable bytes."""
    assert _SURROGATE_LEAK not in stderr, stderr
    assert _UNDECODABLE in stderr, stderr
    assert b"\xe9" not in stderr, stderr
    assert b"\\xe9" in stderr, stderr


def test_hash_skip_warning_metadata_only_latin1_path_is_printable(tmp_path: Path) -> None:
    """MUT manifest.py:1300 — raw {path} in HashVerificationSkippedWarning leaks \\udc."""
    man_b = _write_latin1_manifest(tmp_path)
    proc = _run_c_child(_LOAD_METADATA_ONLY, [man_b])
    assert proc.returncode == 0, proc.stderr
    _assert_printable_stderr(proc.stderr)


def test_hash_skip_warning_skip_hash_latin1_path_is_printable(tmp_path: Path) -> None:
    """MUT manifest.py:1323 — raw {path} in HashVerificationSkippedWarning leaks \\udc."""
    man_b = _write_latin1_manifest(tmp_path)
    proc = _run_c_child(_LOAD_SKIP_HASH, [man_b])
    assert proc.returncode == 0, proc.stderr
    _assert_printable_stderr(proc.stderr)


def test_missing_manifest_error_latin1_path_is_printable(tmp_path: Path) -> None:
    """MUT manifest.py:1159 — raw {manifest_path} in ManifestError leaks \\udc."""
    missing_b = _latin1_cafe_dir(tmp_path) + b"/missing-" + _CAFE_LATIN1 + b".json"
    proc = _run_c_child(_LOAD_MISSING, [missing_b])
    assert proc.returncode == 0, proc.stderr
    assert b"golden manifest not found:" in proc.stderr, proc.stderr
    _assert_printable_stderr(proc.stderr)
