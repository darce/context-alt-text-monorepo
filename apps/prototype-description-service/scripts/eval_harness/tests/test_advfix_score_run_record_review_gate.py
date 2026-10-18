"""Default report API must require review evidence for strict GT (PROV-01)."""

import pytest

from scripts.eval_harness import report
from scripts.eval_harness.manifest import GoldenManifest, ManifestError

_IMAGE_PATH = "mock_images/alice.jpg"


def _manifest(*, reviewed: bool) -> tuple[dict, list[dict]]:
    box = {
        "x": 0.5,
        "y": 0.4,
        "w": 0.2,
        "h": 0.3,
        "name": "Alice Example",
        "source": "operator",
        "lineage": {
            "labeler_id": "operator-1",
            "batch_id": "blind-review-gate",
            "capture_session_id": "real-session-1",
            "pass_index": 0,
            "labeled_at": "2026-08-14T00:00:00Z",
            "tool_version": "test",
            "saw_machine_proposals": False,
            "label_source": "operator_blind",
            "decision": "named",
            "confidence": "high",
            "arbitration_of": None,
        },
    }
    adjudication_records = []
    if reviewed:
        box["adjudication_source"] = "human_adjudicated:review-1"
        adjudication_records.append(
            {
                "record_id": "review-1",
                "media_id": 1,
                "box_index": 0,
                "reviewer_id": "operator-2",
                "reviewer_kind": "human",
                "review_method": "independent_blind_review",
                "decision": "confirmed",
                "reviewed_at": "2026-08-15T00:00:00Z",
            }
        )
    entry = {
        "path": _IMAGE_PATH,
        "sha256": "a" * 64,
        "media_id": 1,
        "face_count": 1,
        "present_identities": ["Alice Example"],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [box],
    }
    full_manifest = GoldenManifest.model_validate(
        {
            "manifest_version": 3,
            "annotation_mode": "exhaustive",
            "iou_threshold": 0.5,
            "roster": ["Alice Example"],
            "entries": [entry],
            "adjudication_records": adjudication_records,
        }
    ).model_dump()
    score_entry = {**entry, "annotation_mode": "exhaustive"}
    return full_manifest, [score_entry]


def _run_record() -> dict:
    return {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "https://api.example.com",
            "head_sha": "0" * 40,
            "started_at": "2026-08-14T00:00:00Z",
        },
        "items": [
            {
                "media_id": 1,
                "path": _IMAGE_PATH,
                "describe": {
                    "alt_text_draft": "Alice Example stands by a pool.",
                    "visual_facts": {"objects": ["person", "pool"]},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "prompt_version": "v1",
                    "prompt_sha256": "f" * 64,
                    "cached": False,
                },
                "identities": [{"name": "Alice Example", "unpositioned": True}],
                "detection_boxes": [{"x": 40.0, "y": 25.0, "width": 20.0, "height": 30.0}],
                "face_count": 1,
                "image_width": 100,
                "image_height": 100,
                "error": None,
            }
        ],
    }



def test_supplied_manifest_requires_confirmed_review() -> None:
    manifest, entries = _manifest(reviewed=False)
    with pytest.raises(ManifestError) as exc_info:
        report.score_run_record(_run_record(), entries, run_manifest=manifest)
    assert exc_info.value.invariant == "adjudication_record_required"


def test_default_score_api_requires_confirmed_review() -> None:
    _manifest_without_review, entries = _manifest(reviewed=False)
    with pytest.raises(ManifestError) as exc_info:
        report.score_run_record(_run_record(), entries)
    assert exc_info.value.invariant == "adjudication_record_required"


def test_default_build_reports_api_requires_confirmed_review() -> None:
    _manifest_without_review, entries = _manifest(reviewed=False)
    with pytest.raises(ManifestError) as exc_info:
        report.build_reports(_run_record(), entries)
    assert exc_info.value.invariant == "adjudication_record_required"


def test_supplied_manifest_accepts_confirmed_review() -> None:
    manifest, entries = _manifest(reviewed=True)
    result = report.score_run_record(_run_record(), entries, run_manifest=manifest)
    assert result["faces"]["detection"]["tp"] == 1


def test_review_only_manifest_accepts_confirmed_review() -> None:
    manifest, entries = _manifest(reviewed=True)
    result = report.score_run_record(_run_record(), entries, review_manifest=manifest)
    assert result["faces"]["detection"]["tp"] == 1
