"""S2R3-12 — exhaustive detection arithmetic through the live score path.

Refusal coverage is dense; these pins exercise detection_pr via
score_run_record so a regression in the counted path cannot hide.
"""

from __future__ import annotations

import pytest

from scripts.eval_harness.report import score_run_record


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


def _exhaustive_entry(labeled_faces: int, *, path: str = "mock_images/alice.jpg") -> dict:
    return {
        "path": path,
        "media_id": 1,
        "face_count": labeled_faces,
        "present_identities": [],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [],
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
