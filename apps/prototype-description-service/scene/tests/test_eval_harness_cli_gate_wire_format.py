"""VLM6-RV16-L-02 / L-03 / RV15-L-05 / W17-A-01: gate wire format + encoder pins.

Do not add tests to test_eval_harness_cli*.py.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scene.tests.test_eval_harness_cli import (
    _assert_child_ascii_locale,
    _c_locale_child_env,
    _manifest,
)
from scene.tests.test_eval_harness_cli_stdio import (
    _enforce_surrogate_argv_marker,
    apply_surrogate_argv_gate,
)
from scripts.eval_harness.cli import (
    _UNDECODABLE_PATH_PREFIX,
    SCORE_GATE_PREFIX_ABORTED_RECORD,
    SCORE_GATE_PREFIX_RUN_RECORD,
    SCORE_GATE_PREFIX_RUN_SUMMARY,
    ScoreGateError,
    fetch_run_record,
    _printable_exc,
    _printable_message,
    _printable_path,
    _score_gate_fail,
)
from scripts.eval_harness.report import ScoreVerdict

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_README_PATH = _SERVICE_ROOT / "scripts" / "eval_harness" / "README.md"
_CAFE_LATIN1 = b"caf\xe9"
_SURROGATE_LEAK = b"\\udc"
_BACKSLASHREPLACE_XE9 = b"\\xe9"
_CLI_PATH = _SERVICE_ROOT / "scripts" / "eval_harness" / "cli.py"
# Absolute ScoreGateError wire (VLM6-RV18-01). Raise ScoreGateError with a
# raw latin-1 surrogate and pin the path marker added at the exception
# boundary (`sys.exit(_printable_exc(exc))`, cli.py:3350; run unwraps at
# :2015/:2018).
_GATE_WIRE = b"score aborted-record gate: see undecodable:/tmp/run-caf\\xe9.json"
_STANDALONE_RAW_GATE = b"""
from scripts.eval_harness import cli as _cli
def boom(args):
    raise _cli.ScoreGateError("score aborted-record gate: see /tmp/run-caf\\udce9.json")
_cli._cmd_score = boom
_cli.main(["score", "--run-record", "x.json", "--manifest", "m.json"])
"""
_STANDALONE_RAW_MANIFEST_ERROR = b"""
from scripts.eval_harness import cli as _cli
def boom(args):
    raise _cli.ManifestError("cannot read /tmp/main-caf\\udce9.json")
_cli._cmd_score = boom
_cli.main(["score", "--run-record", "x.json", "--manifest", "m.json"])
"""
_RUN_WRAP_RAW_GATE = b"""
from argparse import Namespace
from scripts.eval_harness import cli as _cli
def fake_fetch(args):
    return ["r.json"]
def boom(args):
    raise _cli.ScoreGateError("score aborted-record gate: see /tmp/run-caf\\udce9.json")
_cli._cmd_fetch = fake_fetch
_cli._cmd_score = boom
_cli._cmd_run(Namespace(check_determinism=False, provider=None, audience="local"))
"""
_SCORE_UNREADABLE_PREFIX = b"score: run record not found/unreadable: "
_EXPECT_MARKER = b"matches --expect-report "
_README_PATH_TEXT_SNIPPETS = (
    "score: run record not found/unreadable: <path-text>",
    "matches --expect-report <path-text>",
    "`<path-text>` is UTF-8 filename bytes",
)


@pytest.fixture(autouse=True)
def _surrogate_argv_gate(request: pytest.FixtureRequest) -> None:
    apply_surrogate_argv_gate(request)


def _run_python_bytes(
    script: bytes,
    argv: list[bytes] | None = None,
    *,
    cwd: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    _assert_child_ascii_locale()
    _enforce_surrogate_argv_marker(argv)
    env = _c_locale_child_env()
    env["PYTHONWARNINGS"] = "ignore"
    return subprocess.run(
        [os.fsencode(sys.executable), b"-c", script, *(argv or [])],
        cwd=cwd if cwd is not None else os.fsencode(_SERVICE_ROOT),
        env=env,
        capture_output=True,
    )


def _latin1_named(tmp_path: Path, stem: bytes, suffix: bytes = b".json") -> bytes:
    return os.fsencode(tmp_path) + b"/" + stem + b"-" + _CAFE_LATIN1 + suffix


def _write_bytes(path_b: bytes, payload: bytes) -> bytes:
    os.makedirs(os.path.dirname(path_b), exist_ok=True)
    with open(path_b, "wb") as fh:
        fh.write(payload)
    return path_b


def _gate_sentence_with_latin1_slot() -> str:
    return f"{SCORE_GATE_PREFIX_ABORTED_RECORD} see /tmp/run-caf\udce9.json"


# ---------------------------------------------------------------------------
# VLM6-RV16-L-02 — marker must not apply to a whole gate sentence (API-11)
# ---------------------------------------------------------------------------


def test_score_gate_fail_does_not_mark_whole_sentence_for_latin1_slot() -> None:
    """TEST-06/TEST-15: latin-1 0xe9 in a sentence must not prefix undecodable:."""
    with pytest.raises(ScoreGateError) as cap:
        _score_gate_fail(_gate_sentence_with_latin1_slot())
    rendered = str(cap.value)
    assert not rendered.startswith(_UNDECODABLE_PATH_PREFIX), rendered
    assert not rendered.startswith("\\" + _UNDECODABLE_PATH_PREFIX), rendered
    assert rendered.startswith(SCORE_GATE_PREFIX_ABORTED_RECORD), rendered
    assert "\\xe9" in rendered
    assert "\udce9" not in rendered


def test_score_gate_fail_keeps_path_slot_marker_inside_sentence() -> None:
    """Call-site path slot stays a path; the sentence is not a filename.

    Absolute wire pins (VLM6-W18-F2-01). Pre-encoded-only input is a no-op
    for both encoders, so a second raw-surrogate sentence is required to
    kill ``_score_gate_fail`` swapping to ``_printable_path``.
    """
    slot = _printable_path("run-caf\udce9.json")
    assert slot == f"{_UNDECODABLE_PATH_PREFIX}run-caf\\xe9.json", slot
    with pytest.raises(ScoreGateError) as cap:
        _score_gate_fail(f"{SCORE_GATE_PREFIX_ABORTED_RECORD} see {slot}")
    assert str(cap.value) == f"{SCORE_GATE_PREFIX_ABORTED_RECORD} see {slot}"

    with pytest.raises(ScoreGateError) as cap_raw:
        _score_gate_fail(f"{SCORE_GATE_PREFIX_ABORTED_RECORD} see run-caf\udce9.json")
    raw_expected = f"{SCORE_GATE_PREFIX_ABORTED_RECORD} see {_UNDECODABLE_PATH_PREFIX}run-caf\\xe9.json"
    assert str(cap_raw.value) == raw_expected
    assert not str(cap_raw.value).startswith(_UNDECODABLE_PATH_PREFIX)


def test_printable_message_is_idempotent_and_non_marking() -> None:
    """Idempotence is the L-02/L-03 property (API-11)."""
    raw = _gate_sentence_with_latin1_slot()
    once = _printable_message(raw)
    assert once == _printable_message(once)
    assert not once.startswith(_UNDECODABLE_PATH_PREFIX), once
    assert "\\xe9" in once
    marked_path = _printable_path("run-caf\udce9.json")
    mixed = f"{SCORE_GATE_PREFIX_ABORTED_RECORD} see {marked_path}"
    assert _printable_message(mixed) == mixed


def test_score_gate_fail_uses_message_encoder_not_path_encoder() -> None:
    """MUT: `_score_gate_fail` calling `_printable_path` must go red (TEST-15)."""
    tree = ast.parse(_CLI_PATH.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_score_gate_fail")
    names = [n.id for n in ast.walk(fn) if isinstance(n, ast.Name)]
    assert "_printable_message" in names, names
    assert "_printable_path" not in names, names


def test_score_gate_fail_json_path_slots_go_through_printable_path() -> None:
    """MUT: a raw `{json_path}` inside `_score_gate_fail` must go red (TEST-15).

    A wrapped call sitting next to a raw interpolation is still a leak
    (VLM6-RV18-09). Every ``json_path`` Name in the first arg must be an
    argument of ``_printable_path(...)`` — existence of one wrap is not enough.
    """
    tree = ast.parse(_CLI_PATH.read_text(encoding="utf-8"))
    offenders: list[str] = []

    def _call_name(func: ast.AST) -> str | None:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node.func) != "_score_gate_fail":
            continue
        if not node.args:
            continue
        arg = node.args[0]
        wrapped_ids: set[int] = set()
        for inner in ast.walk(arg):
            if not isinstance(inner, ast.Call) or _call_name(inner.func) != "_printable_path":
                continue
            for a in inner.args:
                if isinstance(a, ast.Name) and a.id == "json_path":
                    wrapped_ids.add(id(a))
        for n in ast.walk(arg):
            if isinstance(n, ast.Name) and n.id == "json_path" and id(n) not in wrapped_ids:
                offenders.append(f"L{node.lineno}")
                break
    assert not offenders, f"_score_gate_fail interpolates json_path without _printable_path: {offenders}"


# ---------------------------------------------------------------------------
# VLM6-RV16-L-03 — run wrapper must not invert the decoder (API-11 / rg-006)
# ---------------------------------------------------------------------------


def test_printable_exc_does_not_reescape_already_marked_gate_message() -> None:
    """Encoding an already-encoded message must not prepend a backslash."""
    already = "undecodable:score aborted-record gate: see /tmp/run-caf\\xe9.json"
    out = _printable_exc(ScoreGateError(already))
    assert out == already
    assert not out.startswith("\\undecodable:"), out


def test_printable_exc_oserror_preserves_both_path_fields_once() -> None:
    """OSError tails encode source and destination without repr double-escaping."""
    source = "/tmp/source-" + chr(0xDCE9) + ".bin"
    destination = "/tmp/destination-" + chr(0xDCE9) + ".bin"
    out = _printable_exc(OSError(18, "Invalid cross-device link", source, None, destination))
    assert "Invalid cross-device link: undecodable:/tmp/source-\\xe9.bin" in out
    assert " -> undecodable:/tmp/destination-\\xe9.bin" in out
    assert not any(0xDC00 <= ord(char) <= 0xDFFF for char in out)
    assert "\\\\xe9" not in out


def test_printable_exc_marks_embedded_non_oserror_path_once() -> None:
    """Every undecodable path in an exception sentence uses the path wire."""
    path = "/tmp/manifest-caf" + chr(0xDCE9) + ".json"
    out = _printable_exc(RuntimeError(f"cannot read {path}"))
    assert out == "cannot read undecodable:/tmp/manifest-caf\\xe9.json"
    assert not out.startswith(_UNDECODABLE_PATH_PREFIX)
    assert "\\udce9" not in out
    assert "\\\\xe9" not in out


def test_fetch_item_oserror_tail_uses_printable_exception_encoder(tmp_path: Path) -> None:
    """CLI item isolation must apply the same path-text boundary as stderr."""
    images = tmp_path / "mock_images"
    images.mkdir()
    (images / "img-1.jpg").write_bytes(b"x")

    class _PathErrorClient:
        def describe(self, **kwargs: Any) -> dict[str, Any]:
            raise PermissionError(13, "Permission denied", "/tmp/item-" + chr(0xDCE9) + ".jpg")

    record = fetch_run_record(_manifest(1), str(tmp_path), _PathErrorClient(), head_sha="f" * 40)
    error = record["items"][0]["error"]
    assert "PermissionError: Permission denied: undecodable:/tmp/item-\\xe9.jpg" in error
    assert not any(0xDC00 <= ord(char) <= 0xDFFF for char in error)
    assert "\\\\xe9" not in error


def test_standalone_score_gate_error_exit_pins_absolute_latin1_wire() -> None:
    """MUT cli.py:3350 ``sys.exit(_printable_exc(exc))`` -> ``str(exc)`` (W22V1-F4).

    Raises a raw ``ScoreGateError`` through ``cli.main`` so the production
    exception handler, rather than a formatter-only helper, is exercised.
    The embedded path marker distinguishes both a raw ``str(exc)`` mutation
    and the old unmarked message encoder.
    """
    proc = _run_python_bytes(_STANDALONE_RAW_GATE)
    assert proc.returncode != 0
    payload = proc.stderr.strip()
    assert payload == _GATE_WIRE, proc.stderr
    assert _SURROGATE_LEAK not in payload
    assert _BACKSLASHREPLACE_XE9 in payload


def test_main_score_gate_handler_calls_printable_exception_encoder() -> None:
    """The main score-gate handler must preserve the path-aware boundary."""
    tree = ast.parse(_CLI_PATH.read_text(encoding="utf-8"))
    handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and isinstance(node.type, ast.Name)
        and node.type.id == "ScoreGateError"
    ]
    assert handlers, "cli.main lost its ScoreGateError handler"
    calls = [
        node
        for handler in handlers
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_printable_exc"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "exc"
    ]
    assert calls, "ScoreGateError exits must route through _printable_exc(exc)"


def test_main_manifest_error_handler_encodes_embedded_path() -> None:
    """A generic manifest error path must reach the path-aware boundary."""
    proc = _run_python_bytes(_STANDALONE_RAW_MANIFEST_ERROR)
    assert proc.returncode != 0
    assert proc.stderr.strip() == b"ManifestError: cannot read undecodable:/tmp/main-caf\\xe9.json"
    assert _SURROGATE_LEAK not in proc.stderr
    assert b"/tmp/main-caf\\xe9.json" in proc.stderr


def test_run_wrapper_print_pins_absolute_latin1_gate_payload() -> None:
    """MUT cli.py:2018 unwrap ``_printable_exc(exc)`` -> ``str(exc)`` (VLM6-W18-F2-02)."""
    proc = _run_python_bytes(_RUN_WRAP_RAW_GATE)
    assert proc.returncode != 0
    rec_lines = [
        ln
        for ln in proc.stderr.splitlines()
        if ln.startswith(SCORE_GATE_PREFIX_RUN_RECORD.encode("ascii"))
    ]
    assert rec_lines, proc.stderr
    expected = SCORE_GATE_PREFIX_RUN_RECORD.encode("ascii") + b" r.json: " + _GATE_WIRE
    assert rec_lines[0] == expected, rec_lines[0]
    assert _SURROGATE_LEAK not in rec_lines[0]


def test_run_wrapper_summary_pins_absolute_latin1_gate_payload() -> None:
    """MUT cli.py:2015 unwrap ``_printable_exc(exc)`` -> ``str(exc)`` (VLM6-W18-F2-02)."""
    proc = _run_python_bytes(_RUN_WRAP_RAW_GATE)
    assert proc.returncode != 0
    sum_lines = [
        ln
        for ln in proc.stderr.splitlines()
        if ln.startswith(SCORE_GATE_PREFIX_RUN_SUMMARY.encode("ascii"))
    ]
    assert sum_lines, proc.stderr
    expected = (
        SCORE_GATE_PREFIX_RUN_SUMMARY.encode("ascii")
        + b" 1 record(s): r.json: "
        + _GATE_WIRE
    )
    assert sum_lines[0] == expected, sum_lines[0]
    assert _SURROGATE_LEAK not in sum_lines[0]


# ---------------------------------------------------------------------------
# VLM6-RV15-L-05 — four stdout path prints, latin-1 kill per site
# ---------------------------------------------------------------------------

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

_FETCH_ABORT_CHILD = b"""
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

def _abort(*a, **k):
    raise _cli.BoundedStallError(
        "stall /tmp/fetch-caf\\udce9.jpg",
        {"schema": "acx-eval/v1", "items": [], "provenance": {}, "aborted": True},
    )

_cli.fetch_run_record = _abort
_cli.prune_out_dir = lambda *a, **k: []
_cli.main(["fetch", "--manifest", "unused.json", "--keep", "1"])
"""

_FACE_LEG = b"""
import sys
from pathlib import Path
from scripts.eval_harness import cli as _cli

_cli.OUT_DIR = Path(sys.argv[1])
_cli._images_dir = lambda: "/tmp"
_cli.load_manifest = lambda *a, **k: object()
_cli._build_face_leg = lambda leg: _cli._FaceLegBundle(
    detector=object(),
    aligner=object(),
    embedder=type("E", (), {"embedding_dim": 128})(),
    model_id="t",
    leg_mode=None,
    cache_detector=None,
)
_cli.build_occlusion_twin_pairs = lambda *a, **k: ({}, {"n_pairs": 0, "errors": []})
_cli.validate_face_run_record = lambda r: r
_cli.prune_out_dir = lambda *a, **k: []
"""

_FACE_SUCCESS_CHILD = _FACE_LEG + b"""
_cli.walk_face_run_record = lambda *a, **k: {"items": [], "provenance": {}}
_cli.main(["face-bakeoff", "--manifest", "unused.json", "--keep", "1"])
"""

_FACE_ABORT_CHILD = _FACE_LEG + b"""
def _stall(*a, **k):
    raise _cli.FaceBoundedStallError("stall", {"aborted": True, "items": []})
_cli.walk_face_run_record = _stall
_cli.main(["face-bakeoff", "--manifest", "unused.json", "--keep", "1"])
"""

_FACE_ABORT_EXCEPTION_CHILD = _FACE_LEG + b"""
def _stall(*a, **k):
    raise _cli.FaceBoundedStallError("stall /tmp/face-caf\\udce9.jpg", {"aborted": True, "items": []})
_cli.walk_face_run_record = _stall
_cli.main(["face-bakeoff", "--manifest", "unused.json", "--keep", "1"])
"""


def _assert_latin1_path_line(printed: bytes) -> None:
    """Pin the documented <path-text> form of a latin-1 0xe9 path slot.

    Rejects double-escaped ``\\\\xe9``, body-lost ``undecodable:\\xe9``,
    marker mid-sentence, surrogate leak, and raw 0xe9 (VLM6-RV18-10).
    The slot itself must *start* with the fallback prefix.
    """
    prefix = _UNDECODABLE_PATH_PREFIX.encode("ascii")
    assert printed.startswith(prefix), printed
    assert b"caf" + _BACKSLASHREPLACE_XE9 in printed, printed
    assert b"\\\\xe9" not in printed, printed
    assert _SURROGATE_LEAK not in printed, printed
    assert _CAFE_LATIN1 not in printed, printed
    assert printed.endswith(b".json"), printed
    body = printed[len(prefix) :].decode("ascii")
    recovered = body.encode("ascii").decode("unicode_escape").encode("latin-1")
    assert b"caf\xe9" in recovered, recovered


def test_fetch_record_path_stdout_prints_latin1_via_printable_path(tmp_path: Path) -> None:
    """MUT cli.py fetch print(record_path) — unwrap _printable_path -> red."""
    out_dir = _latin1_named(tmp_path, b"out", suffix=b"")
    os.makedirs(out_dir, exist_ok=True)
    proc = _run_python_bytes(_FETCH_CHILD, [out_dir])
    assert proc.returncode == 0, proc.stderr
    path_lines = [ln for ln in proc.stdout.splitlines() if ln]
    assert path_lines, proc.stdout
    _assert_latin1_path_line(path_lines[0])


def test_fetch_abort_exception_tail_is_printable(tmp_path: Path) -> None:
    """Fetch stall errors encode free-text paths before SystemExit renders them."""
    proc = _run_python_bytes(_FETCH_ABORT_CHILD, [os.fsencode(tmp_path / "out")])
    assert proc.returncode != 0
    assert b"BoundedStallError: stall undecodable:/tmp/fetch-caf\\xe9.jpg" in proc.stderr
    assert _SURROGATE_LEAK not in proc.stderr
    assert b"\\\\xe9" not in proc.stderr


def test_face_bakeoff_abort_path_stdout_prints_latin1_via_printable_path(tmp_path: Path) -> None:
    """MUT cli.py face-run aborted print(path) — unwrap _printable_path -> red."""
    out_dir = _latin1_named(tmp_path, b"face-abort", suffix=b"")
    os.makedirs(out_dir, exist_ok=True)
    proc = _run_python_bytes(_FACE_ABORT_CHILD, [out_dir])
    assert proc.returncode != 0
    path_lines = [ln for ln in proc.stdout.splitlines() if ln]
    assert path_lines, proc.stdout
    _assert_latin1_path_line(path_lines[0])


def test_face_bakeoff_abort_exception_tail_is_printable(tmp_path: Path) -> None:
    """The production ``cli.main`` face-bakeoff handler encodes path tails."""
    proc = _run_python_bytes(_FACE_ABORT_EXCEPTION_CHILD, [os.fsencode(tmp_path / "out")])
    assert proc.returncode != 0
    assert b"FaceBoundedStallError: stall undecodable:/tmp/face-caf\\xe9.jpg" in proc.stderr
    assert _SURROGATE_LEAK not in proc.stderr
    assert b"\\\\xe9" not in proc.stderr


def test_face_bakeoff_success_path_stdout_prints_latin1_via_printable_path(tmp_path: Path) -> None:
    """MUT cli.py face-run success print(path) — unwrap _printable_path -> red."""
    out_dir = _latin1_named(tmp_path, b"face-ok", suffix=b"")
    os.makedirs(out_dir, exist_ok=True)
    proc = _run_python_bytes(_FACE_SUCCESS_CHILD, [out_dir])
    assert proc.returncode == 0, proc.stderr
    path_lines = [
        ln
        for ln in proc.stdout.splitlines()
        if _UNDECODABLE_PATH_PREFIX.encode("ascii") in ln or ln.endswith(b".json")
    ]
    assert path_lines, proc.stdout
    _assert_latin1_path_line(path_lines[0])


def _adoption_compare_report() -> dict[str, Any]:
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


def test_compare_meet_or_beat_pass_line_prints_latin1_via_printable_path(tmp_path: Path) -> None:
    """MUT cli.py compare PASS line — unwrap either _printable_path -> red."""
    body = json.dumps(_adoption_compare_report()).encode("utf-8")
    baseline = _write_bytes(_latin1_named(tmp_path, b"baseline"), body)
    candidate = _write_bytes(_latin1_named(tmp_path, b"candidate"), body)
    proc = _run_python_bytes(
        b"import sys; from scripts.eval_harness.cli import main; main(sys.argv[1:])",
        [b"compare", b"--baseline", baseline, b"--candidate", candidate],
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(b"compare meet-or-beat: PASS ")]
    assert len(lines) == 1, proc.stdout
    line = lines[0]
    _, rest = line.split(b"candidate=", 1)
    cand_text, base_text = rest.split(b" baseline=", 1)
    _assert_latin1_path_line(cand_text)
    _assert_latin1_path_line(base_text)


# ---------------------------------------------------------------------------
# VLM6-W17-A-01 — pin the two unpinned encoder behaviours (TEST-15 / OBS-08)
# ---------------------------------------------------------------------------


def test_reconfigure_stdio_error_mode_is_backslashreplace_under_c_parent() -> None:
    """MUT cli.py `_reconfigure_stdio` errors='backslashreplace' -> 'surrogateescape'.

    Wrapped path prints stay green under that mutation (already ASCII). This
    oracle reads the handler back and emits an unwrapped latin-1 surrogate so
    the stream error mode is actually exercised.
    """
    script = b"""
import json
import sys
from scripts.eval_harness.cli import _reconfigure_stdio
_reconfigure_stdio()
sys.stdout.buffer.write(
    b"MODE "
    + json.dumps({"out": sys.stdout.errors, "err": sys.stderr.errors}).encode("ascii")
    + b"\\n"
)
sys.stdout.buffer.flush()
print("RAW caf\\udce9", flush=True)
"""
    proc = _run_python_bytes(script)
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln]
    mode_line = next(ln for ln in lines if ln.startswith(b"MODE "))
    payload = json.loads(mode_line[5:].decode("ascii"))
    assert payload["out"] == "backslashreplace", payload
    assert payload["err"] == "backslashreplace", payload
    raw_line = next(ln for ln in lines if ln.startswith(b"RAW "))
    assert _SURROGATE_LEAK in raw_line, raw_line
    assert b"\xe9" not in raw_line, raw_line
    assert _CAFE_LATIN1 not in raw_line, raw_line


def test_printable_message_fallback_backslashreplace_bytes() -> None:
    """MUT `_printable_message` errors='backslashreplace' -> 'surrogateescape'.

    Byte-level kill test. café never enters the fallback (fsencode + utf-8
    succeeds). A lone latin-1 0xe9 must emit `\\xHH`, no raw 0xe9, no `\\udc`.
    Control: the same mutation on `_printable_path` must leave this green.
    """
    text = os.fsdecode(_CAFE_LATIN1)
    out = _printable_message(text)
    wire = out.encode("utf-8", errors="surrogateescape")
    assert _BACKSLASHREPLACE_XE9 in wire, wire
    assert b"\xe9" not in wire, wire
    assert _CAFE_LATIN1 not in wire, wire
    assert _SURROGATE_LEAK not in wire, wire
    assert not out.startswith(_UNDECODABLE_PATH_PREFIX), out


# ---------------------------------------------------------------------------
# VLM6-RV18-10 — latin-1 path-line predicate must reject forged escape forms
# ---------------------------------------------------------------------------

_FORGED_LATIN1_PATH_LINES = (
    b"undecodable:caf\\\\xe9.json",
    b"undecodable:\\xe9",
    b"see undecodable:foo \\xe9 bar",
)


@pytest.mark.parametrize("forged", _FORGED_LATIN1_PATH_LINES)
def test_latin1_path_line_predicate_rejects_wrong_escape_forms(forged: bytes) -> None:
    """OLD predicate accepted all three forgeries (VLM6-RV18-10)."""
    with pytest.raises(AssertionError):
        _assert_latin1_path_line(forged)


# ---------------------------------------------------------------------------
# VLM6-RV18-11 — README <path-text> contract rows must match live CLI
# ---------------------------------------------------------------------------


def test_readme_path_text_contract_rows_match_live_cli(tmp_path: Path) -> None:
    """MUT README ``<path-text>`` -> ``<path>`` must go red (rg-006 / RV18-11)."""
    readme = _README_PATH.read_text(encoding="utf-8")
    missing = [snip for snip in _README_PATH_TEXT_SNIPPETS if snip not in readme]
    assert not missing, f"README lost <path-text> contract row(s): {missing}"
    assert re.search(r"matches --expect-report <path>(?!-text>)", readme) is None, readme
    assert re.search(r"run record not found/unreadable: <path>(?!-text>)", readme) is None, readme

    man = tmp_path / "man.json"
    man.write_text("{}", encoding="utf-8")
    missing_rec = _latin1_named(tmp_path, b"missing")
    score_proc = _run_python_bytes(
        b"import sys; from scripts.eval_harness.cli import main; main(sys.argv[1:])",
        [b"score", b"--manifest", os.fsencode(man), b"--run-record", missing_rec],
    )
    assert score_proc.returncode == 2, score_proc.stderr
    unread = next(
        ln for ln in score_proc.stderr.splitlines() if ln.startswith(_SCORE_UNREADABLE_PREFIX)
    )
    unread_path = unread[len(_SCORE_UNREADABLE_PREFIX) :]
    _assert_latin1_path_line(unread_path)
    assert unread == _SCORE_UNREADABLE_PREFIX + unread_path

    expect = _latin1_named(tmp_path, b"anchor")
    _write_bytes(expect, b"{}")
    expect_proc = _run_python_bytes(
        b"""
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
""",
        [expect, b"{}", os.fsencode(tmp_path)],
    )
    assert expect_proc.returncode == 0, expect_proc.stderr
    expect_line = next(ln for ln in expect_proc.stdout.splitlines() if _EXPECT_MARKER in ln)
    expect_path = expect_line.split(_EXPECT_MARKER, 1)[1]
    _assert_latin1_path_line(expect_path)


# ---------------------------------------------------------------------------
# VLM6-RV18-08 — spawn helper must enforce the canonical surrogate-argv marker
# ---------------------------------------------------------------------------


def test_gate_wire_spawn_uses_canonical_surrogate_argv_enforcer() -> None:
    import scene.tests.test_eval_harness_cli_stdio as stdio

    assert _enforce_surrogate_argv_marker is stdio._enforce_surrogate_argv_marker


def test_run_python_bytes_invokes_enforce_surrogate_argv_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[bytes] | None] = []

    def _spy(argv: list[bytes] | None) -> None:
        calls.append(argv)

    monkeypatch.setattr(sys.modules[__name__], "_enforce_surrogate_argv_marker", _spy)
    proc = _run_python_bytes(b"import sys; sys.stdout.buffer.write(b'ok')", [b"x"])
    assert proc.returncode == 0, proc.stderr
    assert calls == [[b"x"]]


def test_run_python_bytes_rejects_unmarked_utf8_cafe_argv() -> None:
    with pytest.raises(pytest.fail.Exception, match="requires_surrogate_argv"):
        _run_python_bytes(b"pass", [b"caf\xc3\xa9.json"])
