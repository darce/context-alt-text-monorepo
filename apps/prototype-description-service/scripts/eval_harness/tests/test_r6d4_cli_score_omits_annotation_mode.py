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
        "roster": ["Alice Example"],
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
                "easy_wrong": [],
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
                "identities": ["Alice Example"],
                "face_count": 3,
                "error": None,
            }
        ],
    }


def test_cmd_score_does_not_pass_annotation_mode_kwarg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Call-shape pin: neither build_reports call may name annotation_mode."""
    import scripts.eval_harness.cli as cli_mod

    seen: list[dict[str, Any]] = []
    real = cli_mod.build_reports

    def wrapped(*args: Any, **kwargs: Any) -> tuple[str, str]:
        seen.append(dict(kwargs))
        return real(*args, **kwargs)

    man_path = tmp_path / "golden.json"
    rec_path = tmp_path / "run.json"
    man_path.write_text(json.dumps(_manifest_doc()), encoding="utf-8")
    rec_path.write_text(json.dumps(_run_record()), encoding="utf-8")
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(cli_mod, "build_reports", wrapped)
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(
            [
                "score",
                "--manifest",
                str(man_path),
                "--run-record",
                str(rec_path),
                "--check-determinism",
            ]
        )
    assert exc.value.code == 3
    assert seen, "build_reports was never called"
    assert len(seen) == 2, "determinism re-score must also omit the kwarg"
    for kwargs in seen:
        assert "annotation_mode" not in kwargs
