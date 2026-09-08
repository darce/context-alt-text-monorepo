"""W19F1: operator-path emission at cli.py construction sites (not {exc} tails).

Spawn the real CLI under a C parent with latin-1 0xe9 argv. café UTF-8 is
forbidden here: os.fsencode recovers it and the undecodable: marker never
fires. Evidence bytes: path-text \\xe9 = 5c786539; surrogate leak \\udce9 =
5c7564636539.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.eval_harness._pathtext import (
    _UNDECODABLE_PATH_PREFIX,
    _printable_message,
    _printable_path,
)
from scripts.eval_harness.cli import SCORE_GATE_PREFIX_REFUSE_OVERWRITE
from scene.tests.test_eval_harness_cli import (
    _assert_child_ascii_locale,
    _c_locale_child_env,
    _clean_score_manifest_and_record,
)
from scene.tests.test_eval_harness_cli_stdio import _enforce_surrogate_argv_marker

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_CAFE_LATIN1 = b"caf\xe9"
_SURROGATE_LEAK = b"\\udc"
_BACKSLASH_XE9 = b"\\xe9"  # 5c786539
_UNDECODABLE = _UNDECODABLE_PATH_PREFIX.encode("ascii")


def _run_python_bytes(
    script: bytes,
    argv: list[bytes] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    _assert_child_ascii_locale()
    _enforce_surrogate_argv_marker(argv)
    env = _c_locale_child_env()
    env["PYTHONWARNINGS"] = "ignore"
    return subprocess.run(
        [os.fsencode(sys.executable), b"-c", script, *(argv or [])],
        cwd=os.fsencode(_SERVICE_ROOT),
        env=env,
        capture_output=True,
    )


def test_run_python_bytes_rejects_unmarked_utf8_argv() -> None:
    """The C-locale child helper must enforce the surrogate-argv marker contract."""
    with pytest.raises(pytest.fail.Exception, match="requires_surrogate_argv"):
        _run_python_bytes(b"pass", [b"caf\xc3\xa9.json"])


def _run_cli_bytes(
    argv: list[bytes],
    *,
    setup: bytes = b"",
) -> subprocess.CompletedProcess[bytes]:
    code = setup + b"import sys; from scripts.eval_harness.cli import main; main(sys.argv[1:])"
    return _run_python_bytes(code, argv)


def _latin1_named(tmp_path: Path, stem: bytes, suffix: bytes = b".json") -> bytes:
    return os.fsencode(tmp_path) + b"/" + stem + b"-" + _CAFE_LATIN1 + suffix


def _write_bytes(path_b: bytes, payload: bytes) -> bytes:
    os.makedirs(os.path.dirname(path_b), exist_ok=True)
    with open(path_b, "wb") as fh:
        fh.write(payload)
    return path_b


def _documented_round_trip(rendered: str) -> bytes:
    """Exactly the _printable_path / README round-trip recipe (rg-006)."""
    if rendered.startswith(_UNDECODABLE_PATH_PREFIX):
        body = rendered[len(_UNDECODABLE_PATH_PREFIX) :]
        return body.encode("ascii").decode("unicode_escape").encode("latin-1")
    if rendered.startswith("\\") and rendered.lstrip("\\").startswith(_UNDECODABLE_PATH_PREFIX):
        return rendered[1:].encode("utf-8")
    return rendered.encode("utf-8")


def _first_undecodable_token(payload: bytes) -> str:
    text = payload.decode("ascii", errors="replace")
    start = text.find(_UNDECODABLE_PATH_PREFIX)
    assert start >= 0, f"missing undecodable: marker in {payload!r} hex={payload.hex()}"
    token = text[start:]
    for sep in (" ", ")", ";", ",", "\n"):
        token = token.split(sep, 1)[0]
    return token.rstrip(":")


def _assert_pathtext_slot(payload: bytes, original: bytes) -> None:
    assert _SURROGATE_LEAK not in payload, f"surrogate leak hex={payload.hex()}"
    assert _BACKSLASH_XE9 in payload, f"missing \\\\xe9 hex={payload.hex()}"
    token = _first_undecodable_token(payload)
    assert token.startswith(_UNDECODABLE_PATH_PREFIX), token
    assert _documented_round_trip(token) == original, (token, original)


def _score_with_latin1_ignore_list(
    tmp_path: Path,
    ignore_payload: bytes,
) -> tuple[subprocess.CompletedProcess[bytes], bytes]:
    man, rec = _clean_score_manifest_and_record(tmp_path, stem="run-w19-ignore")
    dest_dir = os.fsencode(tmp_path) + b"/" + _CAFE_LATIN1
    os.makedirs(dest_dir, exist_ok=True)
    rec_b = dest_dir + b"/run.json"
    with open(rec_b, "wb") as fh:
        fh.write(Path(rec).read_bytes())
    ignore_b = dest_dir + b"/ignore-list.json"
    with open(ignore_b, "wb") as fh:
        fh.write(ignore_payload)
    proc = _run_cli_bytes(
        [
            b"score",
            b"--manifest",
            os.fsencode(man),
            b"--run-record",
            rec_b,
        ]
    )
    return proc, ignore_b


# ---------------------------------------------------------------------------
# Characterization: routing str(OSError) through the encoder is a no-op
# ---------------------------------------------------------------------------


def test_oserror_str_flattens_surrogate_so_reencoding_is_noop() -> None:
    """VLM6-RV14-Q1-01 / RV15-Q1-02 / RV16-B-03: {exc} is already ASCII."""
    filename = os.fsdecode(_CAFE_LATIN1 + b".json")
    rendered = str(OSError(2, "No such file or directory", filename))
    assert r"\udce9" in rendered
    assert not any(0xDC00 <= ord(c) <= 0xDCFF for c in rendered)
    assert _printable_path(rendered) == rendered
    assert _printable_message(rendered) == rendered
    encoded = _printable_path(filename)
    assert encoded.startswith(_UNDECODABLE_PATH_PREFIX)
    assert "\\xe9" in encoded
    assert encoded.encode("utf-8").hex().find("5c786539") >= 0


# ---------------------------------------------------------------------------
# VLM6-RV18-02 — compare load (cli.py baseline + candidate construction)
# ---------------------------------------------------------------------------


def test_compare_missing_latin1_baseline_stderr_uses_undecodable_prefix(
    tmp_path: Path,
) -> None:
    """MUT cli.py compare baseline load — drop _printable_path(baseline_path) -> \\udc."""
    missing = _latin1_named(tmp_path, b"baseline")
    candidate = _write_bytes(_latin1_named(tmp_path, b"candidate-ascii").replace(_CAFE_LATIN1, b"ascii"), b"{}\n")
    proc = _run_cli_bytes(
        [b"compare", b"--baseline", missing, b"--candidate", candidate]
    )
    assert proc.returncode != 0
    assert b"compare: failed to load report JSON:" in proc.stderr, proc.stderr.hex()
    _assert_pathtext_slot(proc.stderr, missing)
    assert candidate not in proc.stderr


def test_compare_missing_latin1_candidate_stderr_uses_undecodable_prefix(
    tmp_path: Path,
) -> None:
    """MUT cli.py compare candidate load — drop _printable_path(candidate_path) -> \\udc."""
    baseline = _write_bytes(_latin1_named(tmp_path, b"baseline-ascii").replace(_CAFE_LATIN1, b"ascii"), b"{}\n")
    missing = _latin1_named(tmp_path, b"candidate")
    proc = _run_cli_bytes(
        [b"compare", b"--baseline", baseline, b"--candidate", missing]
    )
    assert proc.returncode != 0
    assert b"compare: failed to load report JSON:" in proc.stderr, proc.stderr.hex()
    _assert_pathtext_slot(proc.stderr, missing)
    assert baseline not in proc.stderr


# ---------------------------------------------------------------------------
# VLM6-RV18-03 — _load_ignore_list construction (cli.py:804 / :806 / :811)
# ---------------------------------------------------------------------------


def test_ignore_list_malformed_json_latin1_dir_stderr_uses_undecodable_prefix(
    tmp_path: Path,
) -> None:
    """MUT cli.py:804 — unwrap _printable_path(path) on malformed JSON -> no marker."""
    proc, ignore_b = _score_with_latin1_ignore_list(tmp_path, b"{not json")
    assert proc.returncode != 0
    assert b"unreadable or malformed JSON" in proc.stderr, proc.stderr.hex()
    _assert_pathtext_slot(proc.stderr, ignore_b)


def test_ignore_list_non_object_latin1_dir_stderr_uses_undecodable_prefix(
    tmp_path: Path,
) -> None:
    """MUT cli.py:806 — unwrap _printable_path(path) on non-object JSON -> no marker."""
    proc, ignore_b = _score_with_latin1_ignore_list(tmp_path, b"[]\n")
    assert proc.returncode != 0
    assert b"must contain a JSON object" in proc.stderr, proc.stderr.hex()
    _assert_pathtext_slot(proc.stderr, ignore_b)


def test_ignore_list_wrong_names_shape_latin1_dir_stderr_uses_undecodable_prefix(
    tmp_path: Path,
) -> None:
    """MUT cli.py:811 — unwrap _printable_path(path) on wrong_names shape -> no marker."""
    proc, ignore_b = _score_with_latin1_ignore_list(tmp_path, b'{"wrong_names": "nope"}\n')
    assert proc.returncode != 0
    assert b"'wrong_names' must be a list" in proc.stderr, proc.stderr.hex()
    _assert_pathtext_slot(proc.stderr, ignore_b)


# ---------------------------------------------------------------------------
# VLM6-RV18-03 — generic main() handler (cli.py:3211)
# ---------------------------------------------------------------------------


def test_generic_handler_encodes_unmarked_surrogate_without_udc_leak(
    tmp_path: Path,
) -> None:
    """MUT cli.py:3211 — raw {exc} (no _printable_exc) -> \\udce9 on stderr.

    Construction sites 804/806/811 already mark the path, so they cannot kill
    this arm. Inject ManifestError with the raw argv path (no encoder).
    """
    missing = _latin1_named(tmp_path, b"injected")
    man = tmp_path / "man.json"
    man.write_text("{}", encoding="utf-8")
    setup = b"""
from scripts.eval_harness import cli as _cli
from scripts.eval_harness.manifest import ManifestError
def _boom(args):
    raise ManifestError(args.run_record)
_cli._cmd_score = _boom
"""
    proc = _run_cli_bytes(
        [
            b"score",
            b"--manifest",
            os.fsencode(man),
            b"--run-record",
            missing,
        ],
        setup=setup,
    )
    assert proc.returncode != 0
    assert proc.stderr.startswith(b"ManifestError:"), proc.stderr.hex()
    assert _SURROGATE_LEAK not in proc.stderr, proc.stderr.hex()
    assert _BACKSLASH_XE9 in proc.stderr, proc.stderr.hex()
    # Message encoder, not path-slot encoder (API-11): no whole-payload marker.
    line = proc.stderr.splitlines()[0]
    assert not line.startswith(_UNDECODABLE), line
    assert not line.startswith(b"\\" + _UNDECODABLE), line


# ---------------------------------------------------------------------------
# VLM6-RV18-12 — _refuse_report_overwrite listed paths (cli.py:1551)
# ---------------------------------------------------------------------------


def test_refuse_overwrite_latin1_listed_path_uses_undecodable_prefix(
    tmp_path: Path,
) -> None:
    """MUT cli.py:1551 — join(str(p)) without _printable_path -> \\xe9, no marker."""
    man, rec = _clean_score_manifest_and_record(tmp_path, stem="run-w19-refuse")
    parent = tmp_path / "docs" / "tasks" / "vlm"
    parent.mkdir(parents=True)
    record_b = os.fsencode(parent) + b"/bakeoff-results-" + _CAFE_LATIN1 + b".json"
    report_b = os.fsencode(parent) + b"/bakeoff-results-" + _CAFE_LATIN1 + b"-report.json"
    with open(record_b, "wb") as fh:
        fh.write(Path(rec).read_bytes())
    _write_bytes(report_b, b"{}\n")
    proc = _run_cli_bytes(
        [
            b"score",
            b"--manifest",
            os.fsencode(man),
            b"--run-record",
            record_b,
        ]
    )
    assert proc.returncode != 0
    assert SCORE_GATE_PREFIX_REFUSE_OVERWRITE.encode("ascii") in proc.stderr, proc.stderr.hex()
    _assert_pathtext_slot(proc.stderr, report_b)
