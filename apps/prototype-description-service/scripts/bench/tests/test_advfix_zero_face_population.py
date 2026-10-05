"""An exhaustive zero-face negative remains in end-to-end detection scoring."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.bench.driver import init_run_dir
from scripts.bench.score_report import score_head_to_head
from scripts.bench.stack_pair import load_stack_pair
from scripts.bench.tests.conftest import golden_entry, valid_pair_dict, write_pair
from scripts.bench.tests.test_score_head_to_head import (
    A_STACK,
    B_STACK,
    _box,
    _cells,
    _pred,
    _write_leg,
    _write_manifest,
)

PRIMARY = "detection_recall@frame_e2e/label_map_primary"
PRECISION = "detection_precision@frame_e2e/label_map_primary"


def test_zero_face_negative_keeps_full_detection_population(
    tmp_path: Path,
) -> None:
    media_ids = list(range(1, 102))
    positive_ids = media_ids[:100]
    negative_id = media_ids[-1]
    entries = [_entry_with_session(mid, f"capture-{mid}") for mid in positive_ids]
    entries.append(
        golden_entry(
            negative_id,
            face_count=0,
            present_identities=[],
            face_boxes=[],
        )
    )
    manifest = _write_manifest(tmp_path / "manifest.json", entries)
    pair = load_stack_pair(
        write_pair(
            tmp_path / "pair.yaml",
            valid_pair_dict(
                accepted_set_floor=0.90,
                secondary_endpoints=[PRECISION],
            ),
        )
    )
    run_dir = tmp_path / "run"
    init_run_dir(run_dir, pair, manifest)

    successful_ids = positive_ids[:90]
    failed_ids = set(positive_ids[90:])
    predictions = [_pred(mid) for mid in successful_ids] + [_pred(negative_id)]
    for stack_id in (A_STACK, B_STACK):
        _write_leg(run_dir, stack_id, predictions, media_ids)
        items_path = run_dir / "legs" / stack_id / "items.jsonl"
        records = [json.loads(line) for line in items_path.read_text().splitlines()]
        for mid in failed_ids:
            analyze = next(
                row
                for row in records
                if row.get("manifest_media_id") == mid and row.get("phase") == "analyze"
            )
            records.remove(analyze)
            records.append(
                {
                    **analyze,
                    "stack_media_id": None,
                    "phase": "analyze",
                    "outcome": "failed",
                    "attempt": 2,
                    "error_code": "analyze_failed",
                }
            )
        items_path.write_text(
            "\n".join(json.dumps(row) for row in records) + "\n",
            encoding="utf-8",
        )

    score_head_to_head(run_dir)

    recall_cells = _cells(run_dir, PRIMARY)
    precision_cells = _cells(run_dir, PRECISION)
    assert {cell["value"] for cell in recall_cells} == {0.90}
    assert {cell["true_positives"] for cell in recall_cells} == {90}
    assert {cell["false_negatives"] for cell in recall_cells} == {10}
    assert {cell["value"] for cell in precision_cells} == {90 / 91}
    assert {cell["true_positives"] for cell in precision_cells} == {90}
    assert {cell["false_positives"] for cell in precision_cells} == {1}

    frames = json.loads((run_dir / "score" / "frames.json").read_text())
    assert frames["accepted_set_size"] == frames["resolved_floor_count"] == 91
    assert frames["detection_scoring_set_size"] == 91
    assert {cell["tier"] for cell in recall_cells} == {"CONFIRMATORY"}
    attrition = json.loads((run_dir / "score" / "attrition.json").read_text())
    assert attrition["post_accept_exclusions"] == []


def _entry_with_session(media_id: int, session_id: str) -> dict:
    return golden_entry(
        media_id,
        face_count=1,
        present_identities=["Alice Q"],
        face_boxes=[_box(capture_session_id=session_id)],
    )
