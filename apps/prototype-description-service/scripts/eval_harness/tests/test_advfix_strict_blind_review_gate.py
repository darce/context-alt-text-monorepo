from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from scripts.eval_harness.manifest import GoldenManifest, ManifestError, load_manifest
from scripts.eval_harness import report


_IMAGE_PATH = "mock_images/alice.jpg"


def test_manifest_hash_date_hook_rejects_other_types() -> None:
    from scripts.eval_harness.face_bakeoff import _manifest_json_default

    assert _manifest_json_default(date(2026, 8, 15)) == "2026-08-15"
    with pytest.raises(TypeError, match="object is not JSON serializable"):
        _manifest_json_default(object())


def test_manifest_hash_preserves_existing_serialization() -> None:
    from scripts.eval_harness import cli, face_bakeoff

    manifest_doc, _ = _manifest(reviewed=False)
    manifest = GoldenManifest.model_validate(manifest_doc)
    expected = hashlib.sha256(json.dumps(manifest.model_dump(), sort_keys=True).encode()).hexdigest()

    assert cli._manifest_sha(manifest) == expected
    assert face_bakeoff._manifest_sha(manifest) == expected


def test_manifest_hash_with_confirmed_review_is_stable_across_loads(tmp_path: Path) -> None:
    from scripts.eval_harness import cli, face_bakeoff

    manifest_doc, _ = _manifest(reviewed=True)
    manifest_doc["entries"][0]["provenance"] = {"source": "fixture", "license": "fixture"}
    path = tmp_path / "reviewed.json"
    manifest = GoldenManifest.model_validate(manifest_doc)
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    first = load_manifest(str(path), metadata_only=True, skip_hash_verification=True, hash_skip_reason="hash regression")
    second = load_manifest(str(path), metadata_only=True, skip_hash_verification=True, hash_skip_reason="hash regression")
    assert isinstance(first.adjudication_records[0].reviewed_at, datetime)

    expected = hashlib.sha256(
        json.dumps(first.model_dump(), sort_keys=True, default=lambda value: value.isoformat()).encode()
    ).hexdigest()
    assert cli._manifest_sha(first) == cli._manifest_sha(second) == expected
    assert face_bakeoff._manifest_sha(first) == face_bakeoff._manifest_sha(second) == expected


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


def _face_run_record() -> dict:
    return {
        "schema": "acx-eval/v1",
        "kind": "face_run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "head_sha": "0" * 40,
            "started_at": "2026-08-14T00:00:00Z",
            "leg": "candidate",
            "model_id": "test-face-model",
            "embedding_dim": 8,
        },
        "items": [
            {
                "media_id": 1,
                "path": _IMAGE_PATH,
                "model_id": "test-face-model",
                "embedding_dim": 8,
                "image_size": [100, 100],
                "faces": [
                    {
                        "bbox_px": [40.0, 25.0, 20.0, 30.0],
                        "landmarks_px": [[0.0, 0.0]] * 5,
                        "embedding": [1.0] + [0.0] * 7,
                        "det_score": 0.95,
                    }
                ],
            }
        ],
    }


def test_strict_scoring_rejects_unreviewed_box_before_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    run_manifest, entries = _manifest(reviewed=False)

    def metric_must_not_run(*_args: object, **_kwargs: object) -> None:
        pytest.fail("a metric ran before the confirmed blind-review gate")

    monkeypatch.setattr(report, "score_caption", metric_must_not_run)
    monkeypatch.setattr(report, "detection_pr_strict", metric_must_not_run)
    monkeypatch.setattr(report, "identification_pr", metric_must_not_run)

    with pytest.raises(ManifestError, match="confirmed independent blind review") as exc_info:
        report.score_run_record(_run_record(), entries, run_manifest=run_manifest)

    assert exc_info.value.invariant == "adjudication_record_required"


def test_strict_scoring_accepts_confirmed_second_human_review() -> None:
    run_manifest, entries = _manifest(reviewed=True)

    scored = report.score_run_record(_run_record(), entries, run_manifest=run_manifest)

    assert scored["faces"]["detection"]["tp"] == 1


def test_strict_face_scoring_rejects_unreviewed_box_before_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    run_manifest_doc, _entries = _manifest(reviewed=False)
    run_manifest = GoldenManifest.model_validate(run_manifest_doc)

    def metric_must_not_run(*_args: object, **_kwargs: object) -> None:
        pytest.fail("a face metric ran before the confirmed blind-review gate")

    monkeypatch.setattr(report, "score_face_assignment", metric_must_not_run)

    with pytest.raises(ManifestError, match="confirmed independent blind review") as exc_info:
        report.score_face_run_record(_face_run_record(), run_manifest)

    assert exc_info.value.invariant == "adjudication_record_required"


def test_strict_face_scoring_accepts_confirmed_second_human_review() -> None:
    run_manifest_doc, _entries = _manifest(reviewed=True)
    run_manifest = GoldenManifest.model_validate(run_manifest_doc)

    scored = report.score_face_run_record(_face_run_record(), run_manifest)

    assert scored["detection"]["tp"] == 1
    assert scored["detection"]["precision"] == 1.0
    full_identification = scored["slices"]["full_corpus_identification"]
    assert full_identification["precision"] is not None
    assert full_identification["recall"] is not None
