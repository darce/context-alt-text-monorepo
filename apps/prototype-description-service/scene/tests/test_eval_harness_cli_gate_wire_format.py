"""VLM6-RV16-L-02 / L-03 / RV15-L-05: gate wire format + stdout path wraps.

Lane A owns this module. Do not add tests to test_eval_harness_cli*.py.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scene.tests.test_eval_harness_cli import (
    _assert_child_ascii_locale,
    _c_locale_child_env,
)
from scripts.eval_harness.cli import (
    _UNDECODABLE_PATH_PREFIX,
    SCORE_GATE_PREFIX_ABORTED_RECORD,
    SCORE_GATE_PREFIX_RUN_RECORD,
    ScoreGateError,
    _printable_exc,
    _printable_message,
    _printable_path,
    _score_gate_fail,
)
from scripts.eval_harness.report import ScoreVerdict

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_CAFE_LATIN1 = b"caf\xe9"
_SURROGATE_LEAK = b"\\udc"
_BACKSLASHREPLACE_XE9 = b"\\xe9"
_CLI_PATH = _SERVICE_ROOT / "scripts" / "eval_harness" / "cli.py"


def _run_python_bytes(
    script: bytes,
    argv: list[bytes] | None = None,
    *,
    cwd: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    _assert_child_ascii_locale()
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
    """Call-site path slot stays a path; the sentence is not a filename."""
    slot = _printable_path("run-caf\udce9.json")
    assert slot.startswith(_UNDECODABLE_PATH_PREFIX), slot
    with pytest.raises(ScoreGateError) as cap:
        _score_gate_fail(f"{SCORE_GATE_PREFIX_ABORTED_RECORD} see {slot}")
    rendered = str(cap.value)
    assert rendered.startswith(SCORE_GATE_PREFIX_ABORTED_RECORD), rendered
    assert not rendered.startswith(_UNDECODABLE_PATH_PREFIX), rendered
    assert _UNDECODABLE_PATH_PREFIX in rendered
    assert "\\xe9" in rendered


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
    """MUT: a raw `{json_path}` inside `_score_gate_fail` must go red (TEST-15)."""
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
        json_names = [n for n in ast.walk(arg) if isinstance(n, ast.Name) and n.id == "json_path"]
        if not json_names:
            continue
        wrapped = False
        for inner in ast.walk(arg):
            if not isinstance(inner, ast.Call) or _call_name(inner.func) != "_printable_path":
                continue
            if any(isinstance(a, ast.Name) and a.id == "json_path" for a in inner.args):
                wrapped = True
                break
        if not wrapped:
            offenders.append(f"L{node.lineno}")
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


def test_run_and_standalone_handlers_emit_same_gate_payload_for_latin1() -> None:
    """cli.py:2010/2013 and 3245 must share one wire form (TEST-15 / rg-006)."""
    standalone = b"""
from scripts.eval_harness import cli as _cli
def boom(args):
    _cli._score_gate_fail("score aborted-record gate: see /tmp/run-caf\\udce9.json")
_cli._cmd_score = boom
_cli.main(["score", "--run-record", "x.json", "--manifest", "m.json"])
"""
    run_wrap = b"""
from argparse import Namespace
from scripts.eval_harness import cli as _cli
def fake_fetch(args):
    return ["r.json"]
def boom(args):
    _cli._score_gate_fail("score aborted-record gate: see /tmp/run-caf\\udce9.json")
_cli._cmd_fetch = fake_fetch
_cli._cmd_score = boom
_cli._cmd_run(Namespace(check_determinism=False, provider=None, audience="local"))
"""
    stand = _run_python_bytes(standalone)
    wrapped = _run_python_bytes(run_wrap)
    assert stand.returncode != 0 and wrapped.returncode != 0
    stand_payload = stand.stderr.strip()
    assert stand_payload.startswith(SCORE_GATE_PREFIX_ABORTED_RECORD.encode("ascii")), stand.stderr
    assert not stand_payload.startswith(_UNDECODABLE_PATH_PREFIX.encode("ascii")), stand.stderr
    assert not stand_payload.startswith(b"\\" + _UNDECODABLE_PATH_PREFIX.encode("ascii")), stand.stderr
    assert _BACKSLASHREPLACE_XE9 in stand_payload
    assert _SURROGATE_LEAK not in stand_payload
    rec_lines = [
        ln
        for ln in wrapped.stderr.splitlines()
        if ln.startswith(SCORE_GATE_PREFIX_RUN_RECORD.encode("ascii"))
    ]
    assert rec_lines, wrapped.stderr
    rec_payload = rec_lines[0].split(b"r.json: ", 1)[1]
    assert rec_payload == stand_payload, (rec_payload, stand_payload)


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


def _assert_latin1_path_line(printed: bytes) -> None:
    assert _UNDECODABLE_PATH_PREFIX.encode("ascii") in printed, printed
    assert _BACKSLASHREPLACE_XE9 in printed, printed
    assert _SURROGATE_LEAK not in printed, printed
    assert _CAFE_LATIN1 not in printed, printed


def test_fetch_record_path_stdout_prints_latin1_via_printable_path(tmp_path: Path) -> None:
    """MUT cli.py fetch print(record_path) — unwrap _printable_path -> red."""
    out_dir = _latin1_named(tmp_path, b"out", suffix=b"")
    os.makedirs(out_dir, exist_ok=True)
    proc = _run_python_bytes(_FETCH_CHILD, [out_dir])
    assert proc.returncode == 0, proc.stderr
    path_lines = [ln for ln in proc.stdout.splitlines() if ln]
    assert path_lines, proc.stdout
    _assert_latin1_path_line(path_lines[0])


def test_face_bakeoff_abort_path_stdout_prints_latin1_via_printable_path(tmp_path: Path) -> None:
    """MUT cli.py face-run aborted print(path) — unwrap _printable_path -> red."""
    out_dir = _latin1_named(tmp_path, b"face-abort", suffix=b"")
    os.makedirs(out_dir, exist_ok=True)
    proc = _run_python_bytes(_FACE_ABORT_CHILD, [out_dir])
    assert proc.returncode != 0
    path_lines = [ln for ln in proc.stdout.splitlines() if ln]
    assert path_lines, proc.stdout
    _assert_latin1_path_line(path_lines[0])


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
