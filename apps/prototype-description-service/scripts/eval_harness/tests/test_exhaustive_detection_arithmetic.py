"""S2R3-12 — exhaustive detection arithmetic through the live score path.

Refusal coverage is dense; these pins exercise detection_pr via
score_run_record so a regression in the counted path cannot hide.
"""

from __future__ import annotations

import pytest

from scripts.eval_harness.manifest import ManifestError, ScoreInvariant
from scripts.eval_harness.report import score_face_run_record, score_run_record
from scripts.eval_harness.schema import DocKind


def _record(pred_faces: int, *, path: str = "mock_images/alice.jpg") -> dict:
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
                "path": path,
                "describe": {"alt_text_draft": "A photo.", "visual_facts": {"objects": []}},
                "identities": [],
                "face_count": pred_faces,
                "error": None,
            }
        ],
    }


def _boxes(n: int) -> list[dict]:
    return [{"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2, "name": None} for _ in range(n)]


def _exhaustive_entry(labeled_faces: int, *, path: str = "mock_images/alice.jpg") -> dict:
    return {
        "path": path,
        "media_id": 1,
        "face_count": labeled_faces,
        "present_identities": [],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": _boxes(labeled_faces),
        "annotation_mode": "exhaustive",
    }


def _det(pred: int, labeled: int) -> dict:
    scored = score_run_record(
        _record(pred),
        [_exhaustive_entry(labeled)],
        annotation_mode="exhaustive",
    )
    det = scored["faces"]["detection"]
    assert det.get("refused") is not True
    return det


def test_exhaustive_detection_correct_match() -> None:
    """1 predicted, 1 labeled: tp=1 fp=0 fn=0 p=1 r=1."""
    det = _det(1, 1)
    assert det["tp"] == 1
    assert det["fp"] == 0
    assert det["fn"] == 0
    assert det["precision"] == 1.0
    assert det["recall"] == 1.0


def test_exhaustive_detection_false_positive() -> None:
    """2 predicted, 1 labeled: tp=1 fp=1 fn=0 p=0.5 r=1."""
    det = _det(2, 1)
    assert det["tp"] == 1
    assert det["fp"] == 1
    assert det["fn"] == 0
    assert det["precision"] == pytest.approx(0.5)
    assert det["recall"] == 1.0


def test_exhaustive_detection_false_negative() -> None:
    """0 predicted, 1 labeled: tp=0 fp=0 fn=1 p=None r=0."""
    det = _det(0, 1)
    assert det["tp"] == 0
    assert det["fp"] == 0
    assert det["fn"] == 1
    assert det["precision"] is None
    assert det["recall"] == 0.0


def test_exhaustive_detection_exact_match() -> None:
    """2 predicted, 2 labeled: tp=2 fp=0 fn=0 p=1 r=1."""
    det = _det(2, 2)
    assert det["tp"] == 2
    assert det["fp"] == 0
    assert det["fn"] == 0
    assert det["precision"] == 1.0
    assert det["recall"] == 1.0


def _uncovered_exhaustive_entry(*, face_count: int, n_boxes: int) -> dict:
    return {
        "path": "mock_images/group.jpg",
        "media_id": 1,
        "face_count": face_count,
        "present_identities": [],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": _boxes(n_boxes),
        "annotation_mode": "exhaustive",
    }


def test_exhaustive_stamp_without_box_coverage_refuses_detection() -> None:
    """S2R4-04: exhaustive + face_count=5 + 1 box is not a coverage witness."""
    scored = score_run_record(
        _record(2, path="mock_images/group.jpg"),
        [_uncovered_exhaustive_entry(face_count=5, n_boxes=1)],
        annotation_mode="exhaustive",
    )
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REFUSES_UNCOVERED_FACE_COUNT
    assert det["precision"] is None
    assert det["recall"] is None
    assert det["tp"] is None
    # The dishonest count-based score this stamp used to publish.
    assert det["precision"] != 1.0
    assert det["recall"] != 0.4
    assert det["tp"] != 2


def test_exhaustive_extra_boxes_beyond_face_count_refuses_detection() -> None:
    """Inverse hole: face_count=1 with 2 boxes is not a witness either."""
    scored = score_run_record(
        _record(1, path="mock_images/group.jpg"),
        [_uncovered_exhaustive_entry(face_count=1, n_boxes=2)],
        annotation_mode="exhaustive",
    )
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REFUSES_UNCOVERED_FACE_COUNT
    assert det["precision"] is None
    assert det["recall"] is None
    assert det["precision"] != 1.0
    assert det["recall"] != 1.0


def test_score_face_run_record_raises_on_uncovered_exhaustive() -> None:
    """Face path fail-closes: an uncovered exhaustive stamp is not exhaustive."""
    manifest = {
        "annotation_mode": "exhaustive",
        "roster": [],
        "entries": [_uncovered_exhaustive_entry(face_count=5, n_boxes=1)],
    }
    face_run = {
        "schema": "acx-eval/v1",
        "kind": DocKind.FACE_RUN_RECORD.value,
        "provenance": {"manifest_sha256": "m" * 64, "head_sha": "0" * 40, "leg": "candidate"},
        "items": [],
    }
    with pytest.raises(ManifestError) as exc_info:
        score_face_run_record(face_run, manifest)
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REFUSES_UNCOVERED_FACE_COUNT
