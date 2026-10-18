"""S2R5-14 — exit-3 operator text must print the scorer's invariant.

Several distinct invariants produce exit 3. A single hardcoded cause
and remedy is wrong for half of them.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path


_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[5]
_HELPER = _REPO_ROOT / "scripts" / "eval_refusal_message.py"
_WRAPPER = _REPO_ROOT / "scripts" / "eval-captions.sh"
_A10 = (
    _REPO_ROOT / "infra" / "oci" / "incidents" / "a10-distractor-cells.sh",
    _REPO_ROOT / "infra" / "oci" / "incidents" / "a10-interleave-646.sh",
    _REPO_ROOT / "infra" / "oci" / "incidents" / "a10-onbox-bench.sh",
)
_OLD_SINGLE_CAUSE = "Add per-face boxes"


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "eval_refusal_message_under_test", _HELPER
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_report_json_prints_each_invariant_and_its_remedy() -> None:
    helper = _load_helper()
    payload = {
        "faces": {
            "detection": {
                "refused": True,
                "invariant": "detection_refuses_roster_only",
            },
            "identification": {
                "refused": True,
                "invariant": "identification_refuses_unboxed_identity_claims",
            },
        }
    }
    pairs = helper.invariants_from_report(payload)
    assert pairs == [
        ("detection", "detection_refuses_roster_only"),
        ("identification", "identification_refuses_unboxed_identity_claims"),
    ]
    message = helper.format_refusal_message(pairs)
    assert "detection: detection_refuses_roster_only" in message
    assert "identification: identification_refuses_unboxed_identity_claims" in message
    assert "annotation_mode is roster_only" in message
    assert "per-face box lineage" in message
    # A single hardcoded boxes+exhaustive line is not the message.
    assert "Add per-face boxes, or re-run" not in message


def test_empty_observations_does_not_get_roster_only_remedy() -> None:
    helper = _load_helper()
    message = helper.format_refusal_message(
        [("detection", "detection_refuses_empty_observations")]
    )
    assert "detection: detection_refuses_empty_observations" in message
    assert "zero scorable detection observations" in message
    assert "annotation_mode is roster_only" not in message
    assert "Add per-face boxes" not in message


def test_gate_line_is_parsed_when_report_is_absent() -> None:
    helper = _load_helper()
    text = (
        "score gate failed: refused metric(s) ("
        "detection=detection_refuses_mixed_annotation_mode, "
        "identification=identification_refuses_empty_observations); "
        "pass --allow-refused"
    )
    pairs = helper.invariants_from_text(text)
    assert pairs == [
        ("detection", "detection_refuses_mixed_annotation_mode"),
        ("identification", "identification_refuses_empty_observations"),
    ]


def test_unknown_invariant_does_not_invent_a_cause() -> None:
    helper = _load_helper()
    message = helper.format_refusal_message(
        [("detection", "detection_refuses_something_new")]
    )
    assert "detection: detection_refuses_something_new" in message
    assert "No single in-tree remediating edit is assumed" in message


def test_cli_reads_report_file(tmp_path: Path) -> None:
    report = tmp_path / "run-report.json"
    report.write_text(
        json.dumps(
            {
                "faces": {
                    "detection": {
                        "refused": True,
                        "invariant": "detection_refuses_uncovered_face_count",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(_HELPER), "--report", str(report)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "detection_refuses_uncovered_face_count" in proc.stderr
    assert "face_count is not covered by boxes" in proc.stderr


def test_wrapper_on_exit_3_does_not_print_single_cause(tmp_path: Path) -> None:
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    uv = stub_dir / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        "echo 'score gate failed: refused metric(s) "
        "(detection=detection_refuses_roster_only, "
        "identification=identification_refuses_unboxed_identity_claims); "
        "pass --allow-refused' >&2\n"
        "exit 3\n",
        encoding="utf-8",
    )
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = os.environ.copy()
    env["PATH"] = f"{stub_dir}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 3, combined
    assert "detection: detection_refuses_roster_only" in combined
    assert "identification: identification_refuses_unboxed_identity_claims" in combined
    assert "Add per-face boxes, or re-run" not in combined


def test_a10_scripts_do_not_hardcode_a_single_cause() -> None:
    for path in _A10:
        text = path.read_text(encoding="utf-8")
        assert _OLD_SINGLE_CAUSE not in text, path
        assert "eval_refusal_message.py" in text, path
        assert "roster_only / unboxed claims" not in text, path
