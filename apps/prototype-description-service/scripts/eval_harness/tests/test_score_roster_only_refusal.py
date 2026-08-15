"""FIR-11 Slice 2 R1 — in-tree roster_only detection refusal (S2-01 / S2-02).

The live flatten path used to drop annotation_mode, so score_run_record's
default scored roster_only detection as if it were exhaustive. These tests
drive the real flatteners (fusion_runner, CLI score) and go red if the
refusal is removed or made opt-in again.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.fusion_runner import manifest_entries_as_dicts
from scripts.eval_harness.manifest import AnnotationMode, load_manifest
from scripts.eval_harness.report import (
    DETECTION_REFUSED_EXPLANATION,
    ReportError,
    build_reports,
    score_run_record,
)

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

# Overshoot: 3 predicted vs 1 labeled. Scored → precision=0.333 fp=2.
# Refused → precision is None, refused=True.
_OVERSHOOT_RECORD = {
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

EXHAUSTIVE_DETECTION = {"tp": 1, "fp": 2, "fn": 0, "precision": 1 / 3, "recall": 1.0}


def _manifest_doc(mode: str) -> dict:
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


def _write_manifest(tmp_path: Path, mode: str) -> Path:
    path = tmp_path / f"{mode}.json"
    path.write_text(json.dumps(_manifest_doc(mode)), encoding="utf-8")
    return path


def test_fusion_flatten_stamps_annotation_mode(tmp_path: Path) -> None:
    manifest = load_manifest(str(_write_manifest(tmp_path, "roster_only")))
    entries = manifest_entries_as_dicts(manifest)
    assert entries[0]["annotation_mode"] == "roster_only"


def test_fusion_runner_build_reports_refuses_roster_only_detection(tmp_path: Path) -> None:
    """Real in-tree entry: disk roster_only → flatten → build_reports (no kwarg).

    Goes red if the refusal is removed or if flatten drops annotation_mode.
    """
    manifest = load_manifest(str(_write_manifest(tmp_path, "roster_only")))
    entries = manifest_entries_as_dicts(manifest)
    json_doc, _md = build_reports(_OVERSHOOT_RECORD, entries)
    det = json.loads(json_doc)["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == "detection_refuses_roster_only"
    assert det["precision"] is None
    assert det["fp"] is None


def test_score_run_record_without_mode_or_stamp_refuses() -> None:
    """A caller that forgets the mode must refuse, never score."""
    entries = [
        {
            "path": "mock_images/alice.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": ["Alice Example"],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
        }
    ]
    scored = score_run_record(_OVERSHOOT_RECORD, entries)
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == "detection_requires_annotation_mode"
    assert det["precision"] is None
    assert det["fp"] is None


def test_exhaustive_fusion_flatten_detection_unchanged(tmp_path: Path) -> None:
    """Exhaustive P/R through the same flatten path matches the pre-fix pin."""
    manifest = load_manifest(str(_write_manifest(tmp_path, "exhaustive")))
    entries = manifest_entries_as_dicts(manifest)
    json_doc, _md = build_reports(_OVERSHOOT_RECORD, entries)
    det = json.loads(json_doc)["faces"]["detection"]
    assert det.get("refused") is not True
    assert det["tp"] == EXHAUSTIVE_DETECTION["tp"]
    assert det["fp"] == EXHAUSTIVE_DETECTION["fp"]
    assert det["fn"] == EXHAUSTIVE_DETECTION["fn"]
    assert det["precision"] == pytest.approx(EXHAUSTIVE_DETECTION["precision"])
    assert det["recall"] == pytest.approx(EXHAUSTIVE_DETECTION["recall"])


def test_cli_score_refuses_roster_only_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI score stamps entries and omits the kwarg (S2R2-10 omission branch).

    Exit stays 0: caption/identification still scored; refusal is the correct
    detection outcome for roster_only, not a failed run. The one-liner must
    name the refusal so a stdout/CI check cannot treat it as a clean score.
    """
    import scripts.eval_harness.cli as cli_mod

    man_path = _write_manifest(tmp_path, "roster_only")
    record_path = tmp_path / "run.json"
    record_path.write_text(json.dumps(_OVERSHOOT_RECORD), encoding="utf-8")
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    cli_mod.main(["score", "--manifest", str(man_path), "--run-record", str(record_path)])
    report = json.loads(record_path.with_name("run-report.json").read_text(encoding="utf-8"))
    det = report["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == "detection_refuses_roster_only"
    assert det["precision"] is None
    md = record_path.with_name("run-report.md").read_text(encoding="utf-8")
    refused_line = f"- REFUSED (detection_refuses_roster_only): {DETECTION_REFUSED_EXPLANATION}"
    assert refused_line in md
    captured = capsys.readouterr()
    assert "detection=REFUSED(detection_refuses_roster_only)" in captured.out


def _stamped(mode: str) -> list[dict]:
    return [
        {
            "path": "mock_images/alice.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": ["Alice Example"],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "annotation_mode": mode,
        }
    ]


def test_explicit_exhaustive_cannot_widen_roster_only_stamp() -> None:
    """S2R2-01: explicit exhaustive + roster_only stamp refuses (data wins)."""
    scored = score_run_record(
        _OVERSHOOT_RECORD,
        _stamped("roster_only"),
        annotation_mode=AnnotationMode.EXHAUSTIVE,
    )
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == "detection_refuses_roster_only"
    assert det["precision"] is None
    assert det["fp"] is None


def test_stamped_roster_only_without_kwarg_refuses() -> None:
    """S2R2-10: stamp is load-bearing when the explicit kwarg is omitted."""
    scored = score_run_record(_OVERSHOOT_RECORD, _stamped("roster_only"))
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == "detection_refuses_roster_only"
    assert det["precision"] is None


def test_partial_stamp_does_not_promote_to_unstamped_siblings() -> None:
    """S2R2-03: one exhaustive stamp must not cover an unstamped overshoot."""
    entries = [
        {
            "path": "mock_images/alice.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": ["Alice Example"],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "annotation_mode": "exhaustive",
        },
        {
            "path": "mock_images/other.jpg",
            "media_id": 99,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
        },
    ]
    scored = score_run_record(_OVERSHOOT_RECORD, entries)
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == "detection_requires_annotation_mode"
    assert det["precision"] is None


def test_unrecognised_mode_has_own_invariant() -> None:
    """S2R2-12: a typo is not reported as an omitted mode."""
    scored = score_run_record(
        _OVERSHOOT_RECORD,
        _stamped("exhaustive"),
        annotation_mode="exhaustve",
    )
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == "detection_unrecognised_annotation_mode"
    assert det["precision"] is None


def test_mixed_stamps_still_fail_loud_with_explicit_exhaustive() -> None:
    """S2R2-01: explicit must not suppress the mixed-stamp guard."""
    entries = [
        {**_stamped("exhaustive")[0], "media_id": 1},
        {
            "path": "mock_images/other.jpg",
            "media_id": 99,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "annotation_mode": "roster_only",
        },
    ]
    with pytest.raises(ReportError, match="mixed annotation_mode"):
        score_run_record(_OVERSHOOT_RECORD, entries, annotation_mode="exhaustive")


def test_markdown_names_refused_detection() -> None:
    """S2R2-09: the human-readable refusal line is pinned, not only the JSON."""
    manifest_entries = _stamped("roster_only")
    _json_doc, md = build_reports(_OVERSHOOT_RECORD, manifest_entries)
    assert f"- REFUSED (detection_refuses_roster_only): {DETECTION_REFUSED_EXPLANATION}" in md
    assert "precision: null" not in md.split("## Face detection")[1].split("## Face identification")[0]
