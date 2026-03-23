"""Tests for ace_metrics.py: snapshot aggregation, sparklines, and phase timing.

Covers:
- _sparkline: empty list, single-value, multi-value normalization
- _phase_timing: aggregation from exec_complete/review_complete events
- build_snapshot: zero-data graceful handling; token_burn + phase_timing wired
- render_markdown: Phase Timing section present; missing data produces sentinel text
- render_sparklines: reads metrics.jsonl; handles missing file; task_ref filter
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_handoff_mcp.orchestration.ace_metrics import (
    _phase_timing,
    _sparkline,
    _token_burn,
    build_snapshot,
    render_markdown,
    render_sparklines,
)


# ---------------------------------------------------------------------------
# _sparkline
# ---------------------------------------------------------------------------

class TestSparkline:
    def test_empty_returns_empty_string(self) -> None:
        assert _sparkline([]) == ""

    def test_single_value_returns_one_char(self) -> None:
        result = _sparkline([42.0])
        assert len(result) == 1

    def test_uniform_values_all_same_char(self) -> None:
        result = _sparkline([10.0, 10.0, 10.0])
        assert len(result) == 3
        assert len(set(result)) == 1  # all identical

    def test_ascending_values_produce_ascending_chars(self) -> None:
        result = _sparkline([0.0, 25.0, 50.0, 75.0, 100.0])
        # Each subsequent char should be >= the previous (ascending series)
        for i in range(len(result) - 1):
            assert result[i] <= result[i + 1], f"chars not ascending at index {i}"

    def test_output_length_matches_input_length(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        assert len(_sparkline(values)) == len(values)


# ---------------------------------------------------------------------------
# _phase_timing
# ---------------------------------------------------------------------------

class TestPhaseTiming:
    def test_no_events_returns_zero_data(self) -> None:
        result = _phase_timing([])
        assert result["data_available"] is False
        assert result["exec"]["count"] == 0
        assert result["review"]["count"] == 0

    def test_exec_complete_aggregated(self) -> None:
        events = [
            {"event": "exec_complete", "exec_seconds": 5.0},
            {"event": "exec_complete", "exec_seconds": 3.0},
        ]
        result = _phase_timing(events)
        assert result["data_available"] is True
        exec_s = result["exec"]
        assert exec_s["count"] == 2
        assert exec_s["total"] == 8.0
        assert exec_s["mean"] == 4.0
        assert exec_s["max"] == 5.0

    def test_review_complete_aggregated(self) -> None:
        events = [
            {"event": "review_complete", "review_seconds": 10.0},
            {"event": "review_complete", "review_seconds": 20.0},
        ]
        result = _phase_timing(events)
        assert result["data_available"] is True
        rev_s = result["review"]
        assert rev_s["count"] == 2
        assert rev_s["total"] == 30.0
        assert rev_s["mean"] == 15.0
        assert rev_s["max"] == 20.0

    def test_events_without_timing_field_ignored(self) -> None:
        events = [
            {"event": "exec_complete"},  # no exec_seconds key
            {"event": "exec_complete", "exec_seconds": None},  # None value
            {"event": "exec_complete", "exec_seconds": 7.0},
        ]
        result = _phase_timing(events)
        assert result["exec"]["count"] == 1
        assert result["exec"]["total"] == 7.0

    def test_mixed_exec_and_review_events(self) -> None:
        events = [
            {"event": "exec_complete", "exec_seconds": 2.0},
            {"event": "review_complete", "review_seconds": 8.0},
            {"event": "exec_complete", "exec_seconds": 4.0},
        ]
        result = _phase_timing(events)
        assert result["exec"]["count"] == 2
        assert result["review"]["count"] == 1


# ---------------------------------------------------------------------------
# build_snapshot: graceful zero-data handling
# ---------------------------------------------------------------------------

class TestBuildSnapshotZeroData:
    def test_missing_logs_dir_produces_false_flags(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        logs_dir = tmp_path / "nonexistent_logs"
        snapshot = build_snapshot(
            task_ref="test-task",
            state_dir=state_dir,
            logs_dir=logs_dir,
            instruction_files=[],
        )
        assert snapshot["token_burn"]["data_available"] is False
        assert snapshot["context_pressure"]["data_available"] is False
        assert snapshot["lane_health"]["data_available"] is False
        assert snapshot["phase_timing"]["data_available"] is False

    def test_snapshot_has_required_top_level_keys(self, tmp_path: Path) -> None:
        snapshot = build_snapshot(
            task_ref="test-task",
            state_dir=tmp_path / "state",
            logs_dir=tmp_path / "logs",
            instruction_files=[],
        )
        required_keys = {
            "timestamp", "task_ref", "token_burn", "context_pressure",
            "fts5_retrieval", "lane_health", "phase_timing", "ace_documentation",
        }
        assert required_keys.issubset(snapshot.keys())

    def test_snapshot_task_ref_preserved(self, tmp_path: Path) -> None:
        snapshot = build_snapshot(
            task_ref="my-task-ref",
            state_dir=tmp_path,
            logs_dir=tmp_path,
            instruction_files=[],
        )
        assert snapshot["task_ref"] == "my-task-ref"

    def test_worker_events_populate_phase_timing(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "logs"
        worker_dir = logs_dir / "worker-daemon"
        worker_dir.mkdir(parents=True)
        events = [
            {"event": "exec_complete", "exec_seconds": 3.5},
            {"event": "review_complete", "review_seconds": 6.0, "converged": True},
        ]
        worker_log = worker_dir / "worker-frontend.jsonl"
        worker_log.write_text(
            "\n".join(json.dumps(e) for e in events) + "\n",
            encoding="utf-8",
        )
        snapshot = build_snapshot(
            task_ref="t",
            state_dir=tmp_path / "state",
            logs_dir=logs_dir,
            instruction_files=[],
        )
        assert snapshot["phase_timing"]["data_available"] is True
        assert snapshot["phase_timing"]["exec"]["count"] == 1
        assert snapshot["phase_timing"]["review"]["count"] == 1


# ---------------------------------------------------------------------------
# render_markdown: Phase Timing section
# ---------------------------------------------------------------------------

class TestRenderMarkdown:
    def _base_snapshot(self) -> dict:
        return {
            "task_ref": "test",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "token_burn": {
                "data_available": False,
                "total_tokens": 0,
                "by_lane": {},
                "converged_cycles": 0,
                "total_review_cycles": 0,
                "tokens_per_converged_cycle": None,
            },
            "context_pressure": {
                "data_available": False,
                "latest_pressure": "normal",
                "elevated_cycle_ratio": 0.0,
                "high_cycle_ratio": 0.0,
            },
            "fts5_retrieval": {
                "data_available": False,
                "artifact_sources_indexed": 0,
                "artifact_chunks_fts_count": 0,
                "handoff_record_counts": {
                    "decisions": 0, "findings": 0, "blockers": 0, "actions": 0,
                },
            },
            "lane_health": {
                "data_available": False,
                "total_scope_violations": 0,
                "max_exhaustion_streak": 0,
                "convergence_rate": 0.0,
            },
            "phase_timing": {
                "data_available": False,
                "exec": {"count": 0, "total": 0.0, "mean": 0.0, "max": 0.0},
                "review": {"count": 0, "total": 0.0, "mean": 0.0, "max": 0.0},
            },
            "ace_documentation": {
                "data_available": False,
                "total_strategy_bullets": 0,
                "pruning_candidates": 0,
                "pruning_candidate_ids": [],
                "total_helpful": 0,
                "total_harmful": 0,
                "instruction_file_lines": 0,
            },
        }

    def test_phase_timing_section_present(self) -> None:
        md = render_markdown(self._base_snapshot())
        assert "## Phase Timing" in md

    def test_phase_timing_missing_data_sentinel(self) -> None:
        md = render_markdown(self._base_snapshot())
        assert "No exec/review timing data recorded yet" in md

    def test_phase_timing_with_data_shows_numbers(self) -> None:
        snap = self._base_snapshot()
        snap["phase_timing"] = {
            "data_available": True,
            "exec": {"count": 2, "total": 8.0, "mean": 4.0, "max": 5.0},
            "review": {"count": 1, "total": 10.0, "mean": 10.0, "max": 10.0},
        }
        md = render_markdown(snap)
        assert "Exec cycles: 2" in md
        assert "Review cycles: 1" in md

    def test_sections_all_present(self) -> None:
        md = render_markdown(self._base_snapshot())
        for section in [
            "## Token Efficiency",
            "## Context Pressure",
            "## Retrieval Activity",
            "## Lane Stability",
            "## Phase Timing",
            "## Documentation Fitness",
        ]:
            assert section in md, f"Missing section: {section}"


# ---------------------------------------------------------------------------
# render_sparklines
# ---------------------------------------------------------------------------

class TestRenderSparklines:
    def test_missing_metrics_file_returns_message(self, tmp_path: Path) -> None:
        result = render_sparklines(tmp_path, "any-task")
        assert "No metrics history found" in result

    def test_no_matching_task_ref_returns_message(self, tmp_path: Path) -> None:
        metrics = tmp_path / "metrics.jsonl"
        metrics.write_text(
            json.dumps({"task_ref": "other-task", "token_burn": {"total_tokens": 0}}) + "\n",
            encoding="utf-8",
        )
        result = render_sparklines(tmp_path, "my-task")
        assert "No snapshots found" in result

    def test_renders_trend_output_for_matching_task(self, tmp_path: Path) -> None:
        metrics = tmp_path / "metrics.jsonl"
        snapshots = [
            {
                "task_ref": "demo",
                "token_burn": {"total_tokens": t, "data_available": True,
                               "by_lane": {}, "converged_cycles": 0,
                               "total_review_cycles": 0, "tokens_per_converged_cycle": None},
                "context_pressure": {"data_available": False, "latest_pressure": "normal",
                                     "elevated_cycle_ratio": 0.0, "high_cycle_ratio": 0.0},
                "phase_timing": {"data_available": False,
                                 "exec": {"mean": 0.0}, "review": {"mean": 0.0}},
                "lane_health": {"convergence_rate": 0.0, "data_available": False},
            }
            for t in [100, 200, 300]
        ]
        metrics.write_text(
            "\n".join(json.dumps(s) for s in snapshots) + "\n",
            encoding="utf-8",
        )
        result = render_sparklines(tmp_path, "demo")
        assert "Snapshots**: 3" in result
        assert "Token Burn" in result

    def test_empty_task_ref_matches_all_snapshots(self, tmp_path: Path) -> None:
        metrics = tmp_path / "metrics.jsonl"
        metrics.write_text(
            json.dumps({"task_ref": "task-a", "token_burn": {"total_tokens": 50},
                        "context_pressure": {"latest_pressure": "normal"},
                        "phase_timing": {"exec": {"mean": 0.0}, "review": {"mean": 0.0}},
                        "lane_health": {"convergence_rate": 0.0}}) + "\n" +
            json.dumps({"task_ref": "task-b", "token_burn": {"total_tokens": 100},
                        "context_pressure": {"latest_pressure": "normal"},
                        "phase_timing": {"exec": {"mean": 0.0}, "review": {"mean": 0.0}},
                        "lane_health": {"convergence_rate": 0.0}}) + "\n",
            encoding="utf-8",
        )
        result = render_sparklines(tmp_path, "unknown")
        assert "Snapshots**: 2" in result
