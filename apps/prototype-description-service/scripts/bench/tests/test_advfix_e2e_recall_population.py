"""Operational failures stay in end-to-end recall populations."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.bench.driver import init_run_dir
from scripts.bench.score_report import score_head_to_head
from scripts.bench.stack_pair import load_stack_pair
from scripts.bench.tests.conftest import valid_pair_dict, write_pair
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
IDENTIFICATION_RECALL = "identification_recall@frame_e2e/label_map_primary"


def test_terminal_analyze_failures_are_e2e_recall_misses(
    tmp_path: Path, monkeypatch
) -> None:
    from scripts.bench import score_report as score_mod

    media_ids = list(range(1, 101))
    entries = [
        _entry_with_session(mid, f"capture-{mid}")
        for mid in media_ids
    ]
    manifest = _write_manifest(tmp_path / "manifest.json", entries)
    pair = load_stack_pair(
        write_pair(
            tmp_path / "pair.yaml",
            valid_pair_dict(
                accepted_set_floor=0.90,
                secondary_endpoints=[
                    "detection_precision@frame_e2e/label_map_primary",
                    IDENTIFICATION_RECALL,
                    "identification_precision@frame_e2e/label_map_primary",
                ],
            ),
        )
    )
    run_dir = tmp_path / "run"
    init_run_dir(run_dir, pair, manifest)

    successful_ids = media_ids[:90]
    failed_ids = set(media_ids[90:])
    for stack_id in (A_STACK, B_STACK):
        _write_leg(
            run_dir,
            stack_id,
            [_pred(mid) for mid in successful_ids],
            media_ids,
        )
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

    series_lengths: list[tuple[int, int]] = []
    original_bootstrap = score_mod.bootstrap_paired_delta

    def record_population(a, b, *args, **kwargs):
        if kwargs.get("cell") == IDENTIFICATION_RECALL:
            series_lengths.append((len(a), len(b)))
        return original_bootstrap(a, b, *args, **kwargs)

    monkeypatch.setattr(score_mod, "bootstrap_paired_delta", record_population)
    score_head_to_head(run_dir)

    for endpoint in (PRIMARY, IDENTIFICATION_RECALL):
        recall_cells = _cells(run_dir, endpoint)
        assert len(recall_cells) == 2
        assert {cell["value"] for cell in recall_cells} == {0.90}
        assert {cell["true_positives"] for cell in recall_cells} == {90}
        assert {cell["false_negatives"] for cell in recall_cells} == {10}
    assert series_lengths == [(100, 100)]
    primary_cells = _cells(run_dir, PRIMARY)
    assert {cell["tier"] for cell in primary_cells} == {"CONFIRMATORY"}
    frames = json.loads((run_dir / "score" / "frames.json").read_text())
    assert frames["accepted_set_size"] == frames["resolved_floor_count"] == 90


def _entry_with_session(media_id: int, session_id: str) -> dict:
    from scripts.bench.tests.conftest import golden_entry

    return golden_entry(
        media_id,
        face_count=1,
        present_identities=["Alice Q"],
        face_boxes=[_box(capture_session_id=session_id)],
    )
