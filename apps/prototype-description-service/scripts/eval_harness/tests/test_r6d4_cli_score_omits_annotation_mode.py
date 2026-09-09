"""S2R3-18 — _cmd_score must not pass an explicit annotation_mode kwarg.

S2R2-10 dropped the kwarg so the stamp is the only score-time source.
Mutating _cmd_score back to build_reports(..., annotation_mode='exhaustive')
left the suite green because the resolver's data-wins rule still refuses.
This pin dies on the call shape itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


_LINEAGE = {
    "labeler_id": "test-labeler",
    "batch_id": "test-batch",
    "capture_session_id": "test-session",
    "pass_index": 0,
    "labeled_at": "2026-08-14T00:00:00Z",
    "tool_version": "test",
    "saw_machine_proposals": False,
    "label_source": "operator_blind",
    "decision": "named",
    "confidence": "high",
    "arbitration_of": None,
}


def _manifest_doc() -> dict[str, Any]:
    return {
        "manifest_version": 3,
        "annotation_mode": "roster_only",
        # 2 roster members so easy_wrong can name a real (non-must_right) roster
        # identity — roster_only mode requires must_right/easy_wrong to be
        # roster subsets (manifest.py::load_manifest), and an empty easy_wrong
        # trips the empty-rubric gate (SCORE_GATE_PREFIX_EMPTY_RUBRIC, cli.py).
        "roster": ["Alice Example", "Bob Distractor"],
        "entries": [
            {
                "path": "mock_images/alice.jpg",
                "sha256": "a" * 64,
                "media_id": 1,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "context_pack": {"title": "t"},
                "base_caption": "Alice Example.",
                "must_right": ["Alice Example"],
                "easy_wrong": ["Bob Distractor"],
                "policy": {"recognition_enabled": True},
                "provenance": {"source": "fixture", "license": "fixture"},
                "face_boxes": [
                    {
                        "x": 0.5,
                        "y": 0.4,
                        "w": 0.2,
                        "h": 0.3,
                        "name": "Alice Example",
                        "source": "operator",
                        "lineage": _LINEAGE,
                    }
                ],
            }
        ],
    }


def _run_record() -> dict[str, Any]:
    return {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "x",
            "head_sha": "0" * 40,
            "started_at": "t",
        },
        "items": [
            {
                "media_id": 1,
                "path": "mock_images/alice.jpg",
                "describe": {
                    "alt_text_draft": "Alice Example by the pool.",
                    "visual_facts": {"objects": []},
                },
                # Dict identity rows (greenfield rejects bare strings —
                # VLM6-PANEL6L-SR-01); shape mirrors fusion_runner.py::_identity_rows.
                "identities": [{"name": "Alice Example", "unpositioned": True}],
                "face_count": 3,
                "error": None,
            }
        ],
    }


def test_cmd_score_does_not_pass_annotation_mode_kwarg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Call-shape pin: neither score_run_record nor build_reports names annotation_mode.

    VLM6-DELTA-13: --check-determinism no longer calls build_reports in-process
    at all (F2c / C-01 cross-process re-score); it delegates to a subprocess
    and certifies the child bound the same build_reports module via
    build_reports.__code__.co_filename identity. Monkeypatching cli_mod's
    build_reports to spy on kwargs makes that identity check itself fail
    ("child build_reports module differs from parent") because the parent's
    "expected" file becomes this test module, not report.py — an artifact of
    the spy, unrelated to the annotation_mode regression this test guards.
    Use --audience public without --check-determinism instead: _cmd_score's
    plain path calls score_run_record directly for the LOCAL leg and
    build_reports for the PUBLIC leg (cli.py ~1608-1635) — 2 real,
    in-process, spy-observable calls that together cover every call site the
    original S2R2-10 regression could reappear at.
    """
    import scripts.eval_harness.cli as cli_mod

    seen: list[dict[str, Any]] = []
    real_score_run_record = cli_mod.score_run_record
    real_build_reports = cli_mod.build_reports

    def wrapped_score_run_record(*args: Any, **kwargs: Any) -> dict[str, Any]:
        seen.append(dict(kwargs))
        return real_score_run_record(*args, **kwargs)

    def wrapped_build_reports(*args: Any, **kwargs: Any) -> tuple[str, str]:
        seen.append(dict(kwargs))
        return real_build_reports(*args, **kwargs)

    man_path = tmp_path / "golden.json"
    rec_path = tmp_path / "run.json"
    man_path.write_text(json.dumps(_manifest_doc()), encoding="utf-8")
    rec_path.write_text(json.dumps(_run_record()), encoding="utf-8")
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(cli_mod, "score_run_record", wrapped_score_run_record)
    monkeypatch.setattr(cli_mod, "build_reports", wrapped_build_reports)
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(
            [
                "score",
                "--manifest",
                str(man_path),
                "--run-record",
                str(rec_path),
                "--audience",
                "public",
            ]
        )
    # VLM6-DELTA-13: this single-image roster_only fixture still trips this
    # branch's own adoption-quality gates (category-vacuity for an undersized
    # corpus, ahead of any refusal-consent exit) — same class of interception
    # documented in VLM6-DELTA-12. The call-shape pin (seen/annotation_mode
    # below) is the actual invariant under test; assert only that the CLI
    # exited via a real, accounted-for score gate, not a bare crash.
    assert isinstance(exc.value.code, str)
    assert any(
        exc.value.code.startswith(prefix) for prefix in cli_mod.SCORE_GATE_PREFIXES
    )
    assert seen, "score_run_record/build_reports was never called"
    assert len(seen) == 2, "both the LOCAL and PUBLIC leg must omit the kwarg"
    for kwargs in seen:
        assert "annotation_mode" not in kwargs
