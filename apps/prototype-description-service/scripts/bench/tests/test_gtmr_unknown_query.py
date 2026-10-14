"""G4: unknown export observations must not masquerade as measured misses.

These score-path tests deliberately leave the production scorer unchanged.
The refusal API is not settled: either a query-specific BenchError or explicit
refused cells with null measurements satisfies the safety contract. Silently
dropping unknown items, or merely demoting numerical cells, does not.
Successful-empty observations and terminal pipeline failures have distinct
causes, but both remain misses in exhaustive end-to-end recall.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.bench.driver import init_run_dir
from scripts.bench.export_map import load_leg_exports
from scripts.bench.score_report import compute_accepted_set, score_head_to_head
from scripts.bench.stack_pair import BenchError, load_stack_pair
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

E2E_RECALL = (
    "detection_recall@frame_e2e/label_map_primary",
    "identification_recall@frame_e2e/label_map_primary",
)
MEDIA_IDS = list(range(1, 11))
TARGET = MEDIA_IDS[-1]
AFFECTED = [(A_STACK,), (A_STACK, B_STACK)]


def _run(tmp_path: Path, affected: tuple[str, ...], state: str) -> Path:
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [
            golden_entry(
                mid,
                face_count=1,
                present_identities=["Alice Q"],
                face_boxes=[_box(capture_session_id=f"capture-{mid}")],
            )
            for mid in MEDIA_IDS
        ],
    )
    pair = load_stack_pair(
        write_pair(
            tmp_path / "pair.yaml",
            valid_pair_dict(
                accepted_set_floor=0.90,
                # One unknown item on one leg must reach the metric consumer,
                # rather than failing the independent skew precondition.
                max_differential_attrition=0.10,
            ),
        )
    )
    run_dir = tmp_path / "run"
    init_run_dir(run_dir, pair, manifest)
    for stack in (A_STACK, B_STACK):
        predictions = [
            _pred(mid) for mid in MEDIA_IDS
            if stack not in affected or mid != TARGET
        ]
        _write_leg(run_dir, stack, predictions, MEDIA_IDS)
        if stack not in affected:
            continue
        export_dir = run_dir / "legs" / stack / "exports"
        results_path = export_dir / "media_identity_results.json"
        results = json.loads(results_path.read_text(encoding="utf-8"))
        target_result = next(row for row in results if row["media_id"] == TARGET)
        assert target_result == {
            "media_id": TARGET, "query_succeeded": True, "rows": []
        }
        if state == "failed_query":
            target_result["query_succeeded"] = False
        elif state in {"unqueried", "analyze_failed"}:
            results.remove(target_result)
        else:
            assert state == "successful_empty"
        results_path.write_text(json.dumps(results), encoding="utf-8")
        # Evidence is intentionally internally hashed: a digest error must not
        # hide the unknown-query regression.
        digest_path = export_dir / "export_sha256.json"
        digests = json.loads(digest_path.read_text(encoding="utf-8"))
        digests[results_path.name] = hashlib.sha256(results_path.read_bytes()).hexdigest()
        digest_path.write_text(json.dumps(digests), encoding="utf-8")
        if state == "analyze_failed":
            items_path = run_dir / "legs" / stack / "items.jsonl"
            records = [json.loads(line) for line in items_path.read_text().splitlines()]
            target_analyze = next(
                row for row in records
                if row["manifest_media_id"] == TARGET and row["phase"] == "analyze"
            )
            target_analyze.update(
                stack_media_id=None, outcome="failed", attempt=2,
                error_code="analyze_failed",
            )
            items_path.write_text(
                "\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8"
            )
        load_leg_exports(run_dir, stack)  # Verify every fixture digest before scoring.
    return run_dir


def _assert_refused(cells: list[dict], endpoint: str) -> None:
    for cell in cells:
        assert cell.get("refused") is True, (
            f"{endpoint} emitted a measurement for an unknown export observation: {cell}"
        )
        assert cell.get("reason"), "refusal must explain the unsupported observation"
        for key in ("value", "recall", "true_positives", "false_positives", "false_negatives"):
            assert cell.get(key) is None, f"refused cell still exposes measured {key}"


@pytest.mark.parametrize("affected", AFFECTED, ids=["one_leg", "both_legs"])
@pytest.mark.parametrize("state", ["failed_query", "unqueried"])
@pytest.mark.parametrize("endpoint", E2E_RECALL, ids=["detection", "identification"])
def test_unknown_query_cannot_emit_measured_e2e_recall(
    tmp_path: Path, affected: tuple[str, ...], state: str, endpoint: str
) -> None:
    run_dir = _run(tmp_path, affected, state)
    accepted = compute_accepted_set(run_dir)
    assert accepted.accepted_set_size == accepted.resolved_floor_count == 9
    assert TARGET not in accepted.manifest_media_ids
    assert accepted.attrition_join == 1
    assert accepted.attrition_ingest_analyze == 0
    assert accepted.zero_detection_media_count == 0
    for stack in affected:
        assert accepted.attrition_failures_by_media[TARGET][stack] == ["identity_query"]
        assert TARGET in accepted.join_by_stack[stack]  # Analyze actually succeeded.

    try:
        score_head_to_head(run_dir)
    except BenchError as exc:
        # No invented error-code contract; require a relevant refusal rather
        # than allowing an unrelated fixture/preflight failure to turn green.
        reason = f"{exc.code} {exc}".lower()
        assert "query" in reason or ("unknown" in reason and "export" in reason)
        frames_path = run_dir / "score" / "frames.json"
        if frames_path.exists():
            cells = _cells(run_dir, endpoint)
            _assert_refused([c for c in cells if c["stack_id"] in affected], endpoint)
    else:
        cells = _cells(run_dir, endpoint)
        affected_cells = [c for c in cells if c["stack_id"] in affected]
        assert {c["stack_id"] for c in affected_cells} == set(affected), (
            "unknown observations were silently omitted without a refusal"
        )
        _assert_refused(affected_cells, endpoint)


@pytest.mark.parametrize("affected", AFFECTED, ids=["one_leg", "both_legs"])
@pytest.mark.parametrize("state", ["successful_empty", "analyze_failed"])
def test_observed_empty_and_terminal_pipeline_failure_remain_e2e_misses(
    tmp_path: Path, affected: tuple[str, ...], state: str
) -> None:
    run_dir = _run(tmp_path, affected, state)
    accepted = compute_accepted_set(run_dir)
    if state == "successful_empty":
        assert accepted.accepted_set_size == 10
        assert TARGET in accepted.manifest_media_ids
        assert accepted.zero_detection_media_count == 1
        assert accepted.attrition_join == accepted.attrition_ingest_analyze == 0
    else:
        assert accepted.accepted_set_size == 9
        assert accepted.zero_detection_media_count == accepted.attrition_join == 0
        assert accepted.attrition_ingest_analyze == 1
        for stack in affected:
            assert accepted.attrition_failures_by_media[TARGET][stack] == ["analyze"]
            assert TARGET not in accepted.join_by_stack[stack]
    score_head_to_head(run_dir)
    for endpoint in E2E_RECALL:
        cells = _cells(run_dir, endpoint)
        assert {cell["stack_id"] for cell in cells} == {A_STACK, B_STACK}
        for cell in cells:
            missed = int(cell["stack_id"] in affected)
            assert not cell.get("refused", False)
            assert cell["true_positives"] == 10 - missed
            assert cell["false_positives"] == 0
            assert cell["false_negatives"] == missed
            assert cell["value"] == (10 - missed) / 10


def test_complete_successful_observations_are_healthy(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, (), "successful_empty")
    accepted = compute_accepted_set(run_dir)
    assert accepted.accepted_set_size == 10
    assert accepted.zero_detection_media_count == 0
    score_head_to_head(run_dir)
    for endpoint in E2E_RECALL:
        cells = _cells(run_dir, endpoint)
        assert {cell["stack_id"] for cell in cells} == {A_STACK, B_STACK}
        assert {cell["value"] for cell in cells} == {1.0}
        assert {cell["true_positives"] for cell in cells} == {10}
        assert {cell["false_negatives"] for cell in cells} == {0}
