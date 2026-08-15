"""S2R3-08 — identification P/R refuses unboxed identity claims.

An entry can load with present_identities and empty face_boxes (roster_only
allows that). Identification must not treat those names as labeled GT.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.face_metrics import IDENTIFICATION_UNBOXED_INVARIANT
from scripts.eval_harness.manifest import AnnotationMode, load_manifest
from scripts.eval_harness.report import (
    IDENTIFICATION_REFUSED_EXPLANATION,
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


def _record(identities: list[str], *, face_count: int = 1, media_id: int = 1, path: str = "mock_images/alice.jpg") -> dict:
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
                "media_id": media_id,
                "path": path,
                "describe": {"alt_text_draft": "A photo.", "visual_facts": {"objects": []}},
                "identities": identities,
                "face_count": face_count,
                "error": None,
            }
        ],
    }


def _unboxed_alice() -> dict:
    return {
        "path": "mock_images/alice.jpg",
        "media_id": 1,
        "face_count": 1,
        "present_identities": ["Alice Example"],
        "must_right": ["Alice Example"],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [],
        "annotation_mode": "roster_only",
    }


def _named_box(name: str) -> dict:
    return {
        "x": 0.5,
        "y": 0.4,
        "w": 0.2,
        "h": 0.3,
        "name": name,
        "source": "operator",
        "lineage": _LINEAGE,
    }


def _boxed_alice() -> dict:
    entry = _unboxed_alice()
    entry["face_boxes"] = [_named_box("Alice Example")]
    return entry


def _assert_identification_refused(ident: dict) -> None:
    assert ident["refused"] is True
    assert ident["invariant"] == IDENTIFICATION_UNBOXED_INVARIANT
    assert ident["precision"] is None
    assert ident["recall"] is None
    assert ident["macro_precision"] is None
    assert ident["macro_recall"] is None
    assert ident["true_rejections"] is None
    assert ident["wrong_names"] is None


def test_unboxed_claim_loads_as_roster_only(tmp_path: Path) -> None:
    """Load stays legal — the defect is scoring, not the roster_only schema."""
    doc = {
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
                "face_boxes": [],
            }
        ],
    }
    path = tmp_path / "unboxed.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    manifest = load_manifest(str(path))
    assert manifest.annotation_mode is AnnotationMode.ROSTER_ONLY
    assert manifest.entries[0].present_identities == ["Alice Example"]
    assert manifest.entries[0].face_boxes == []


def test_unboxed_correct_name_refuses_identification() -> None:
    """Correct name on an unboxed claim must not yield p=1 r=1 tp=1."""
    scored = score_run_record(_record(["Alice Example"]), [_unboxed_alice()])
    ident = scored["faces"]["identification"]
    _assert_identification_refused(ident)
    assert ident.get("tp") not in (1,)


def test_unboxed_wrong_name_refuses_identification() -> None:
    """Wrong name on an unboxed claim must not emit a scored wrong_names row."""
    scored = score_run_record(_record(["Bob Example"]), [_unboxed_alice()])
    ident = scored["faces"]["identification"]
    _assert_identification_refused(ident)
    assert ident["wrong_names"] != [["mock_images/alice.jpg", "Bob Example"]]


def test_unboxed_miss_refuses_identification() -> None:
    """A miss on an unboxed claim must not yield recall=0 / fn=1."""
    scored = score_run_record(_record([]), [_unboxed_alice()])
    ident = scored["faces"]["identification"]
    _assert_identification_refused(ident)
    assert ident["recall"] is not False
    assert ident.get("fn") not in (1,)


def test_mixed_boxed_and_unboxed_refuses_whole_identification() -> None:
    """Must not drop the unboxed entry and score the boxed sibling as p=1 r=1."""
    boxed = _boxed_alice()
    unboxed = {
        "path": "mock_images/bob.jpg",
        "media_id": 2,
        "face_count": 1,
        "present_identities": ["Bob Example"],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [],
        "annotation_mode": "roster_only",
    }
    record = _record(["Alice Example"])
    record["items"].append(
        {
            "media_id": 2,
            "path": "mock_images/bob.jpg",
            "describe": {"alt_text_draft": "A photo.", "visual_facts": {"objects": []}},
            "identities": [],
            "face_count": 1,
            "error": None,
        }
    )
    scored = score_run_record(record, [boxed, unboxed])
    ident = scored["faces"]["identification"]
    _assert_identification_refused(ident)
    # Dropping Bob from the denominator would leave Alice as a perfect score.
    assert ident["precision"] != 1.0
    assert ident["recall"] != 1.0


def test_boxed_identity_still_scores_identification() -> None:
    """Positive pair: a named box is identification GT and P/R is computed."""
    scored = score_run_record(_record(["Alice Example"]), [_boxed_alice()])
    ident = scored["faces"]["identification"]
    assert ident.get("refused") is not True
    assert ident["precision"] == 1.0
    assert ident["recall"] == 1.0
    assert ident["wrong_names"] == []


def test_markdown_names_refused_identification() -> None:
    _json_doc, md = build_reports(_record(["Alice Example"]), [_unboxed_alice()])
    assert f"- REFUSED ({IDENTIFICATION_UNBOXED_INVARIANT}):" in md
    assert "per-face box lineage" in md
    assert IDENTIFICATION_REFUSED_EXPLANATION in md
    face_id = md.split("## Face identification")[1]
    assert "micro precision:" not in face_id
