"""FIR-11 Slice 2 R6 — CLI exit-gate pins (S2R5-02 / 05 / 12 / 13).

These drive the shipped ``cli.main`` entry points. A gate that re-scores
instead of reading the published report, or that treats any consent as
every consent, must go red here.
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


def _named_box(name: str) -> dict[str, Any]:
    return {
        "x": 0.5,
        "y": 0.4,
        "w": 0.2,
        "h": 0.3,
        "name": name,
        "source": "operator",
        "lineage": _LINEAGE,
    }


def _manifest_doc(*, mode: str, boxed: bool) -> dict[str, Any]:
    return {
        "manifest_version": 3,
        "annotation_mode": mode,
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
                "face_boxes": [_named_box("Alice Example")] if boxed else [],
            }
        ],
    }


def _run_record(*, face_count: int = 3) -> dict[str, Any]:
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
                "face_count": face_count,
                "error": None,
            }
        ],
    }


def _write_score_inputs(
    tmp_path: Path, *, mode: str, boxed: bool, record: dict[str, Any] | None = None
) -> tuple[Path, Path]:
    man_path = tmp_path / f"{mode}.json"
    man_path.write_text(json.dumps(_manifest_doc(mode=mode, boxed=boxed)), encoding="utf-8")
    rec_path = tmp_path / "run.json"
    rec_path.write_text(json.dumps(record if record is not None else _run_record()), encoding="utf-8")
    return man_path, rec_path


# ---------------------------------------------------------------------------
# S2R5-13 — gate must read the published report, not a second score call
# ---------------------------------------------------------------------------


def _wrap_published_detection(
    build_reports, *, refused: bool, invariant: str = "published-only-refusal"
):
    """Rewrite only the published honesty field; a real rescore is untouched."""

    def _wrapped(*args: Any, **kwargs: Any) -> tuple[str, str]:
        json_doc, md_doc = build_reports(*args, **kwargs)
        parsed = json.loads(json_doc)
        if refused:
            parsed["faces"]["detection"] = {
                "refused": True,
                "invariant": invariant,
                "precision": None,
                "recall": None,
                "tp": None,
                "fp": None,
                "fn": None,
            }
        else:
            parsed["faces"]["detection"] = {
                "precision": 1.0,
                "recall": 1.0,
                "tp": 1,
                "fp": 0,
                "fn": 0,
            }
        return json.dumps(parsed, indent=2, sort_keys=True) + "\n", md_doc

    return _wrapped


def test_score_gate_exits_3_when_published_report_is_refused_even_if_rescore_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2R5-13 case A: published refused + real rescore clean → exit 3.

    Exhaustive boxed GT makes ``score_run_record`` clean. The wrap stamps
    refusal only onto the published JSON. Gating a second score call
    (any name) exits 0 — the pre-fix hole.
    """
    import scripts.eval_harness.cli as cli_mod

    man_path, rec_path = _write_score_inputs(tmp_path, mode="exhaustive", boxed=True)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(
        cli_mod,
        "build_reports",
        _wrap_published_detection(cli_mod.build_reports, refused=True),
    )
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score", "--manifest", str(man_path), "--run-record", str(rec_path)])
    assert exc.value.code == 3
    published = json.loads(rec_path.with_name("run-report.json").read_text(encoding="utf-8"))
    assert published["faces"]["detection"]["refused"] is True
    assert published["faces"]["detection"]["invariant"] == "published-only-refusal"


def test_score_gate_exits_0_when_published_report_is_clean_even_if_rescore_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2R5-13 case B: published clean + real rescore refused → exit 0.

    roster_only makes ``score_run_record`` refuse detection. The wrap
    stamps a clean detection only onto the published JSON. OR-ing the
    two objects, or gating the rescore, exits 3 and dies here.
    """
    import scripts.eval_harness.cli as cli_mod

    man_path, rec_path = _write_score_inputs(tmp_path, mode="roster_only", boxed=True)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(
        cli_mod,
        "build_reports",
        _wrap_published_detection(cli_mod.build_reports, refused=False),
    )
    cli_mod.main(["score", "--manifest", str(man_path), "--run-record", str(rec_path)])
    published = json.loads(rec_path.with_name("run-report.json").read_text(encoding="utf-8"))
    assert published["faces"]["detection"].get("refused") is not True
