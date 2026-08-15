"""S2R5-07 — exhaustive coverage must fail-closed when face_boxes is absent.

S2R4-04's pins only feed a PRESENT mismatched face_boxes list. The skip
`if "face_boxes" not in entry: continue` then left exhaustive + face_count=5
+ missing key + pred=2 publishing precision=1.0 recall=0.4 tp=2.
"""

from __future__ import annotations

import pytest

from scripts.eval_harness.face_metrics import require_exhaustive_box_coverage
from scripts.eval_harness.manifest import ManifestError, ScoreInvariant
from scripts.eval_harness.report import score_run_record


def _record(pred_faces: int, *, path: str = "mock_images/group.jpg") -> dict:
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


def _exhaustive_entry(*, face_count: int, face_boxes: object | None, include_key: bool) -> dict:
    entry = {
        "path": "mock_images/group.jpg",
        "media_id": 1,
        "face_count": face_count,
        "present_identities": [],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "annotation_mode": "exhaustive",
    }
    if include_key:
        entry["face_boxes"] = face_boxes
    return entry


def test_absent_face_boxes_key_refuses_exhaustive_detection() -> None:
    """S2R5-07: a missing key is not a coverage witness.

    The dishonest count-based score this stamp used to publish was
    precision=1.0 recall=0.4 tp=2 (pred=2 vs labeled face_count=5).
    """
    entry = _exhaustive_entry(face_count=5, face_boxes=None, include_key=False)
    assert "face_boxes" not in entry
    scored = score_run_record(
        _record(2),
        [entry],
        annotation_mode="exhaustive",
    )
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REFUSES_UNCOVERED_FACE_COUNT
    assert det["precision"] is None
    assert det["recall"] is None
    assert det["tp"] is None
    assert det["precision"] != 1.0
    assert det["recall"] != 0.4
    assert det["tp"] != 2


def test_require_exhaustive_box_coverage_raises_on_absent_key() -> None:
    """Helper-level pin: the skip `if key not in entry: continue` dies here."""
    entry = _exhaustive_entry(face_count=5, face_boxes=None, include_key=False)
    assert "face_boxes" not in entry
    with pytest.raises(ManifestError) as exc_info:
        require_exhaustive_box_coverage([entry])
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REFUSES_UNCOVERED_FACE_COUNT
    assert "face_count=5" in str(exc_info.value)


def test_absent_key_with_zero_face_count_is_covered() -> None:
    """0 faces and no box list is 0==0, not a hole."""
    entry = _exhaustive_entry(face_count=0, face_boxes=None, include_key=False)
    require_exhaustive_box_coverage([entry])


def test_empty_face_boxes_list_with_nonzero_count_refuses() -> None:
    """Present empty list is the same hole as an absent key."""
    entry = _exhaustive_entry(face_count=5, face_boxes=[], include_key=True)
    with pytest.raises(ManifestError) as exc_info:
        require_exhaustive_box_coverage([entry])
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REFUSES_UNCOVERED_FACE_COUNT
