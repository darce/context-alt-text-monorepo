"""Subset manifests preserve the review evidence required by retained boxes."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.bench.driver import init_run_dir
from scripts.bench.score_report import (
    _subset_manifest,
    compute_accepted_set,
    score_head_to_head,
)
from scripts.bench.stack_pair import load_stack_pair
from scripts.bench.tests.conftest import golden_entry, valid_pair_dict, write_pair
from scripts.bench.tests.test_score_head_to_head import (
    A_STACK,
    B_STACK,
    _box,
    _pred,
    _write_leg,
)
from scripts.eval_harness.manifest import GoldenManifest


def _reviewed_manifest_payload() -> dict[str, object]:
    media_ids = [1, 2, 3]
    entries = []
    for media_id in media_ids:
        box = _box(capture_session_id=f"capture-{media_id}")
        box["adjudication_source"] = f"human_adjudicated:review-2026-{media_id}"
        entries.append(
            golden_entry(
                media_id,
                face_count=1,
                present_identities=["Alice Q"],
                face_boxes=[box],
            )
        )
    return {
        "manifest_version": 3,
        "annotation_mode": "exhaustive",
        "iou_threshold": 0.61,
        "roster": ["Alice Q"],
        "entries": entries,
        # Intentionally not entry order: subsets must preserve parent's order.
        "adjudication_records": [
            {
                "record_id": f"review-2026-{media_id}",
                "media_id": media_id,
                "box_index": 0,
                "reviewer_id": f"independent-reviewer-{media_id}",
                "reviewer_kind": "human",
                "review_method": "independent_blind_review",
                "decision": "confirmed",
                "reviewed_at": f"2026-08-{17 + media_id:02d}T12:30:00Z",
            }
            for media_id in reversed(media_ids)
        ],
    }


def _reviewed_run(tmp_path: Path) -> Path:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_reviewed_manifest_payload(), indent=2), encoding="utf-8"
    )
    pair = load_stack_pair(
        write_pair(
            tmp_path / "pair.yaml",
            valid_pair_dict(accepted_set_floor=0.5),
        )
    )
    run_dir = tmp_path / "run"
    init_run_dir(run_dir, pair, manifest_path)
    # Leave one reviewed manifest entry out of both stack rosters. The accepted
    # subset then needs only the two retained review records.
    retained_ids = [1, 2]
    predictions = [_pred(media_id) for media_id in retained_ids]
    for stack_id in (A_STACK, B_STACK):
        _write_leg(run_dir, stack_id, predictions, retained_ids)
    return run_dir


def test_subset_manifest_keeps_only_referenced_records_in_parent_order() -> None:
    manifest = GoldenManifest.model_validate(_reviewed_manifest_payload())

    subset = _subset_manifest(manifest, [manifest.entries[0], manifest.entries[1]])

    assert subset is not None
    assert [record.record_id for record in subset.adjudication_records] == [
        "review-2026-2",
        "review-2026-1",
    ]
    assert subset.iou_threshold == manifest.iou_threshold


def test_compute_accepted_set_scores_reviewed_subset(tmp_path: Path) -> None:
    accepted = compute_accepted_set(_reviewed_run(tmp_path))

    assert accepted.manifest_media_ids == [1, 2]
    assert accepted.accepted_set_size == 2


def test_score_head_to_head_scores_reviewed_manifest_subsets(tmp_path: Path) -> None:
    run_dir = _reviewed_run(tmp_path)

    report = score_head_to_head(run_dir)

    assert report.is_file()
    frames = json.loads((run_dir / "score" / "frames.json").read_text(encoding="utf-8"))
    assert frames["accepted_set_size"] == 2
    assert frames["manifest_entry_count"] == 3
