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
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_handoff_mcp.orchestration.ace_metrics import (
    _archive_rate,
    _contract_co_change_signal,
    _ctx7_adoption,
    _handoff_memory,
    _phase_timing,
    _planning_drift,
    _process_health,
    _slice_review_adoption,
    _sparkline,
    _stale_artifact_metrics,
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
        assert snapshot["process_health"]["data_available"] is False
        assert snapshot["handoff_memory"]["data_available"] is False
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
            "fts5_retrieval", "lane_health", "process_health", "handoff_memory",
            "planning_drift", "stale_artifact_rate", "archive_rate", "ctx7_adoption",
            "phase_timing", "slice_review_adoption", "ace_documentation",
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
            "process_health": {
                "data_available": False,
                "reopened_finding_rate": {"value": None, "reopened_findings": 0, "total_findings": 0},
                "finding_resolution_velocity_hours": {"median_hours": None, "resolved_findings": 0},
                "handoff_decision_completeness": {"value": None, "structured_decisions": 0, "total_decisions": 0},
                "contract_co_change_signal": {
                    "data_available": False,
                    "recent_commits_scanned": 0,
                    "boundary_touching_commits": 0,
                    "boundary_commits_with_contract_co_change": 0,
                    "value": None,
                },
            },
            "handoff_memory": {
                "data_available": False,
                "hot_state_size_bytes": 0,
                "total_decisions": 0,
                "total_findings": 0,
                "artifact_source_count": 0,
            },
            "planning_drift": {
                "data_available": False,
                "window_days": 30,
                "total": 0,
                "terminal": 0,
                "drift": None,
            },
            "stale_artifact_rate": {
                "data_available": False,
                "window_days": 30,
                "total": 0,
                "stale_count": 0,
                "stale_rate": 0.0,
            },
            "archive_rate": {
                "data_available": False,
                "window_days": 30,
                "total_archives": 0,
                "in_window": 0,
                "mean_interval_hours": None,
            },
            "ctx7_adoption": {
                "data_available": False,
                "decisions_with_ctx7": 0,
                "unique_library_ids": 0,
                "reuse_ratio": None,
                "library_ids": [],
            },
            "phase_timing": {
                "data_available": False,
                "exec": {"count": 0, "total": 0.0, "mean": 0.0, "max": 0.0},
                "review": {"count": 0, "total": 0.0, "mean": 0.0, "max": 0.0},
            },
            "slice_review_adoption": {
                "data_available": False,
                "total_reviews": 0,
                "packet_backed_reviews": 0,
                "branch_diff_fallback_reviews": 0,
                "planning_reviews": 0,
                "branch_reviews": 0,
                "packet_backed_adoption_rate": None,
                "branch_diff_fallback_rate": None,
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
            "## Process Health",
            "## Handoff Memory",
            "## Planning Drift",
            "## Artifact Staleness",
            "## Archive Cadence",
            "## ctx7 Adoption",
            "## Phase Timing",
            "## Slice Review Adoption",
            "## Documentation Fitness",
        ]:
            assert section in md, f"Missing section: {section}"

    def test_slice_review_adoption_missing_data_sentinel(self) -> None:
        md = render_markdown(self._base_snapshot())
        assert "No review-complete events recorded with scope-source metadata yet" in md


class TestDerivedMetrics:
    def _write_handoff_db(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        db_path = state_dir / "handoff.db"
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE plan_cursors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    plan_item_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    lane_id TEXT,
                    mcp_action_id INTEGER,
                    worker_message_id INTEGER,
                    source_heading TEXT,
                    summary TEXT NOT NULL,
                    dispatch_count INTEGER NOT NULL DEFAULT 0,
                    dispatched_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE task_archives (
                    task_ref TEXT PRIMARY KEY,
                    archived_at TEXT NOT NULL,
                    archived_by TEXT,
                    archived_branch TEXT,
                    archived_commit_sha TEXT,
                    notes TEXT,
                    snapshot_json TEXT NOT NULL
                );
                CREATE TABLE decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    rationale TEXT
                );
                """
            )
            conn.executemany(
                """
                INSERT INTO plan_cursors (task_ref, plan_item_id, state, summary, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    ("task-1", "slice-1", "completed", "done", "2026-03-20 00:00:00"),
                    ("task-1", "slice-2", "skipped", "skip", "2026-03-21 00:00:00"),
                    ("task-1", "slice-3", "dispatched", "still active", "2026-03-22 00:00:00"),
                    ("task-1", "slice-4", "escalated", "needs help", "2026-03-23 00:00:00"),
                ],
            )
            conn.executemany(
                """
                INSERT INTO task_archives (task_ref, archived_at, snapshot_json)
                VALUES (?, ?, ?)
                """,
                [
                    ("arch-1", "2026-03-01 00:00:00", "{}"),
                    ("arch-2", "2026-03-10 00:00:00", "{}"),
                    ("arch-3", "2026-03-20 00:00:00", "{}"),
                ],
            )
            conn.executemany(
                "INSERT INTO decisions (task_ref, rationale) VALUES (?, ?)",
                [
                    ("task-1", "ctx7 library id: /vercel/next.js\nUsed current docs."),
                    ("task-1", "ctx7 library id: /vercel/next.js\nctx7 library id: /openai/openai"),
                    ("task-1", "plain prose decision"),
                ],
            )

    def _write_artifacts_db(self, state_dir: Path) -> None:
        db_path = state_dir / "mcp-artifacts.db"
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE artifact_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    lane_id TEXT,
                    app_root TEXT,
                    source_kind TEXT NOT NULL,
                    source_label TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT,
                    summary TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.executemany(
                """
                INSERT INTO artifact_sources (
                    task_ref, lane_id, app_root, source_kind, source_label, content_type,
                    content_hash, metadata_json, summary, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("task-1", None, None, "log", "recent", "text/plain", "h1", None, None, "2026-03-20 00:00:00", "2026-03-24 00:00:00"),
                    ("task-1", None, None, "log", "stale", "text/plain", "h2", None, None, "2026-02-01 00:00:00", "2026-02-15 00:00:00"),
                ],
            )

    def test_planning_drift_uses_terminal_ratio(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state_dir = tmp_path / ".task-state"
        self._write_handoff_db(state_dir)
        monkeypatch.setattr(
            "agent_handoff_mcp.orchestration.ace_metrics._window_start",
            lambda days=30: datetime(2026, 3, 1, tzinfo=timezone.utc),
        )

        result = _planning_drift("task-1", state_dir)

        assert result["data_available"] is True
        assert result["total"] == 4
        assert result["terminal"] == 2
        assert result["drift"] == 0.5

    def test_stale_artifact_metrics_counts_old_sources(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state_dir = tmp_path / ".task-state"
        state_dir.mkdir(parents=True, exist_ok=True)
        self._write_artifacts_db(state_dir)
        monkeypatch.setattr(
            "agent_handoff_mcp.orchestration.ace_metrics._window_start",
            lambda days=30: datetime(2026, 3, 1, tzinfo=timezone.utc),
        )

        result = _stale_artifact_metrics(state_dir)

        assert result["data_available"] is True
        assert result["total"] == 2
        assert result["stale_count"] == 1
        assert result["stale_rate"] == 0.5

    def test_archive_rate_uses_repo_wide_archive_history(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state_dir = tmp_path / ".task-state"
        self._write_handoff_db(state_dir)
        monkeypatch.setattr(
            "agent_handoff_mcp.orchestration.ace_metrics._window_start",
            lambda days=30: datetime(2026, 3, 5, tzinfo=timezone.utc),
        )

        result = _archive_rate(state_dir)

        assert result["data_available"] is True
        assert result["total_archives"] == 3
        assert result["in_window"] == 2
        assert result["mean_interval_hours"] == 228.0

    def test_ctx7_adoption_tracks_decisions_and_unique_library_ids(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".task-state"
        self._write_handoff_db(state_dir)

        result = _ctx7_adoption("task-1", state_dir)

        assert result["data_available"] is True
        assert result["decisions_with_ctx7"] == 2
        assert result["unique_library_ids"] == 2
        assert result["reuse_ratio"] == 1.5
        assert result["library_ids"] == ["/openai/openai", "/vercel/next.js"]

    def test_slice_review_adoption_counts_packet_and_fallback_reviews(self) -> None:
        result = _slice_review_adoption(
            [
                {"event": "review_complete", "scope_source": "slice_packet", "review_kind": "planning"},
                {"event": "review_complete", "scope_source": "slice_packet", "review_kind": "branch"},
                {"event": "review_complete", "scope_source": "branch_diff", "review_kind": "branch"},
                {"event": "exec_complete", "exec_seconds": 3.0},
            ]
        )

        assert result["data_available"] is True
        assert result["total_reviews"] == 3
        assert result["packet_backed_reviews"] == 2
        assert result["branch_diff_fallback_reviews"] == 1
        assert result["planning_reviews"] == 1
        assert result["branch_reviews"] == 2
        assert result["packet_backed_adoption_rate"] == 0.667
        assert result["branch_diff_fallback_rate"] == 0.333


class TestProcessHealth:
    def _write_handoff_db(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        db_path = state_dir / "handoff.db"
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE review_findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    reopen_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE TABLE decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    rationale TEXT
                );
                """
            )
            conn.executemany(
                """
                INSERT INTO review_findings (task_ref, reopen_count, status, created_at, resolved_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    ("task-1", 1, "fixed", "2026-03-01 00:00:00", "2026-03-01 12:00:00"),
                    ("task-1", 0, "fixed", "2026-03-02 00:00:00", "2026-03-03 00:00:00"),
                    ("task-1", 0, "deferred", "2026-03-03 00:00:00", "2026-03-08 00:00:00"),
                    ("task-1", 0, "open", "2026-03-04 00:00:00", None),
                ],
            )
            conn.executemany(
                "INSERT INTO decisions (task_ref, rationale) VALUES (?, ?)",
                [
                    (
                        "task-1",
                        "\n".join(
                            [
                                "## Changes",
                                "- landed",
                                "## Verification",
                                "- passed",
                                "## Schema / Contract Changes",
                                "- none.",
                                "## Open Threads",
                                "- none.",
                            ]
                        ),
                    ),
                    ("task-1", "plain prose decision"),
                ],
            )

    def _init_git_repo(self, repo_root: Path) -> None:
        subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Codex"], cwd=repo_root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=repo_root, check=True, capture_output=True, text=True)

    def _commit_file(self, repo_root: Path, path: str, content: str, message: str) -> None:
        file_path = repo_root / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", path], cwd=repo_root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", message], cwd=repo_root, check=True, capture_output=True, text=True)

    def test_process_health_aggregates_handoff_metrics(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".task-state"
        self._write_handoff_db(state_dir)

        result = _process_health("task-1", state_dir, tmp_path)

        assert result["data_available"] is True
        assert result["reopened_finding_rate"]["reopened_findings"] == 1
        assert result["reopened_finding_rate"]["total_findings"] == 4
        assert result["reopened_finding_rate"]["value"] == 0.25
        assert result["finding_resolution_velocity_hours"]["resolved_findings"] == 2
        assert result["finding_resolution_velocity_hours"]["median_hours"] == 18.0
        assert result["handoff_decision_completeness"]["structured_decisions"] == 1
        assert result["handoff_decision_completeness"]["total_decisions"] == 2
        assert result["handoff_decision_completeness"]["value"] == 0.5

    def test_process_health_zero_findings_leaves_rate_unavailable(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".task-state"
        state_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(state_dir / "handoff.db") as conn:
            conn.executescript(
                """
                CREATE TABLE review_findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    reopen_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE TABLE decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    rationale TEXT
                );
                """
            )

        result = _process_health("task-1", state_dir, tmp_path)

        assert result["reopened_finding_rate"]["value"] is None
        assert result["reopened_finding_rate"]["total_findings"] == 0
        assert result["finding_resolution_velocity_hours"]["resolved_findings"] == 0

    def test_process_health_ignores_non_fixed_and_malformed_resolution_timestamps(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".task-state"
        self._write_handoff_db(state_dir)
        with sqlite3.connect(state_dir / "handoff.db") as conn:
            conn.execute(
                """
                INSERT INTO review_findings (task_ref, reopen_count, status, created_at, resolved_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("task-1", 0, "fixed", "not-a-date", "2026-03-09 00:00:00"),
            )
            conn.execute(
                """
                INSERT INTO review_findings (task_ref, reopen_count, status, created_at, resolved_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("task-1", 0, "wontfix", "2026-03-10 00:00:00", "2026-03-11 00:00:00"),
            )

        result = _process_health("task-1", state_dir, tmp_path)

        assert result["finding_resolution_velocity_hours"]["resolved_findings"] == 2
        assert result["finding_resolution_velocity_hours"]["median_hours"] == 18.0

    def test_process_health_empty_rationale_is_not_structured(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".task-state"
        self._write_handoff_db(state_dir)
        with sqlite3.connect(state_dir / "handoff.db") as conn:
            conn.execute("INSERT INTO decisions (task_ref, rationale) VALUES (?, ?)", ("task-1", ""))

        result = _process_health("task-1", state_dir, tmp_path)

        assert result["handoff_decision_completeness"]["structured_decisions"] == 1
        assert result["handoff_decision_completeness"]["total_decisions"] == 3
        assert result["handoff_decision_completeness"]["value"] == pytest.approx(0.333, abs=0.001)

    def test_contract_co_change_signal_uses_review_ready_prefixes(self, tmp_path: Path) -> None:
        self._init_git_repo(tmp_path)
        self._commit_file(
            tmp_path,
            "README.md",
            "seed\n",
            "seed",
        )
        self._commit_file(
            tmp_path,
            "apps/example/service.py",
            "print('boundary only')\n",
            "boundary only",
        )
        file_path = tmp_path / "apps/example/service.py"
        file_path.write_text("print('boundary with contract')\n", encoding="utf-8")
        contract_path = tmp_path / "docs/agentic/contracts/example.md"
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.write_text("contract\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "apps/example/service.py", "docs/agentic/contracts/example.md"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "commit", "-m", "boundary with contract"], cwd=tmp_path, check=True, capture_output=True, text=True)

        result = _contract_co_change_signal(tmp_path, commit_limit=10)

        assert result["data_available"] is True
        assert result["boundary_touching_commits"] == 2
        assert result["boundary_commits_with_contract_co_change"] == 1
        assert result["value"] == 0.5


class TestHandoffMemory:
    def _write_handoff_db(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        db_path = state_dir / "handoff.db"
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE handoff_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    task_ref TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT,
                    updated_branch TEXT,
                    updated_commit_sha TEXT
                );
                CREATE TABLE decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    lane_id TEXT,
                    session TEXT NOT NULL DEFAULT 'test',
                    decision TEXT NOT NULL DEFAULT '',
                    rationale TEXT,
                    agent TEXT,
                    branch TEXT,
                    commit_sha TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE blockers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    lane_id TEXT,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    agent TEXT,
                    branch TEXT,
                    commit_sha TEXT,
                    resolved_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE verified_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    lane_id TEXT,
                    command TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    exit_code INTEGER,
                    result TEXT,
                    session TEXT NOT NULL,
                    agent TEXT,
                    branch TEXT,
                    commit_sha TEXT,
                    verified_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE review_findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    lane_id TEXT,
                    finding_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    line_start INTEGER,
                    line_end INTEGER,
                    description TEXT NOT NULL,
                    fix TEXT,
                    status TEXT NOT NULL,
                    review_mode TEXT,
                    session TEXT NOT NULL,
                    agent TEXT,
                    branch TEXT,
                    commit_sha TEXT,
                    resolution_notes TEXT,
                    reopen_count INTEGER NOT NULL DEFAULT 0,
                    last_reopen_reason TEXT,
                    last_reopened_at TEXT,
                    resolved_at TEXT,
                    verification_evidence TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE next_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    lane_id TEXT,
                    action TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 100,
                    status TEXT NOT NULL,
                    agent TEXT,
                    branch TEXT,
                    commit_sha TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE worktree_lanes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    lane_id TEXT NOT NULL,
                    title TEXT,
                    objective TEXT,
                    worktree_path TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    owner_agent TEXT,
                    model TEXT,
                    backend TEXT,
                    reasoning_effort TEXT,
                    status TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE worker_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    lane_id TEXT NOT NULL,
                    session TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    changed_files_json TEXT NOT NULL DEFAULT '[]',
                    test_commands_json TEXT NOT NULL DEFAULT '[]',
                    blockers_json TEXT NOT NULL DEFAULT '[]',
                    merge_ready INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'submitted',
                    agent TEXT,
                    branch TEXT,
                    commit_sha TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE lane_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    lane_id TEXT NOT NULL,
                    session TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    subject TEXT,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    payload_json TEXT,
                    agent TEXT,
                    branch TEXT,
                    commit_sha TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE plan_cursors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_ref TEXT NOT NULL,
                    plan_item_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    lane_id TEXT,
                    mcp_action_id INTEGER,
                    worker_message_id INTEGER,
                    source_heading TEXT,
                    summary TEXT NOT NULL,
                    dispatch_count INTEGER NOT NULL DEFAULT 0,
                    dispatched_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
            conn.execute(
                """
                INSERT INTO handoff_state (
                    id, task_ref, objective, status, revision, updated_at
                ) VALUES (1, 'task-1', 'Test objective', 'in_progress', 1, '2026-03-01 00:00:00')
                """
            )
            conn.execute(
                "INSERT INTO decisions (task_ref, session, decision, rationale) VALUES ('task-1', 'test', 'd1', 'decision body')"
            )
            conn.execute(
                "INSERT INTO review_findings (task_ref, finding_id, severity, file_path, description, status, session) VALUES ('task-1', 'F-1', 'medium', 'a.py', 'desc', 'open', 'test')"
            )
            conn.execute(
                "INSERT INTO verified_tests (task_ref, command, passed, session) VALUES ('task-1', 'pytest', 1, 'test')"
            )

    def _write_artifacts_db(self, state_dir: Path) -> None:
        db_path = state_dir / "mcp-artifacts.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE artifact_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_label TEXT NOT NULL
                )
                """
            )
            conn.execute("INSERT INTO artifact_sources (source_label) VALUES ('a')")

    def test_handoff_memory_collects_hot_state_and_artifact_counts(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".task-state"
        self._write_handoff_db(state_dir)
        self._write_artifacts_db(state_dir)

        result = _handoff_memory("task-1", state_dir, tmp_path)

        assert result["data_available"] is True
        assert result["hot_state_size_bytes"] > 0
        assert result["total_decisions"] == 1
        assert result["total_findings"] == 1
        assert result["artifact_source_count"] == 1

    def test_handoff_memory_handles_missing_artifacts_db(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".task-state"
        self._write_handoff_db(state_dir)

        result = _handoff_memory("task-1", state_dir, tmp_path)

        assert result["data_available"] is True
        assert result["hot_state_size_bytes"] > 0
        assert result["artifact_source_count"] == 0

    def test_handoff_memory_uses_requested_task_scope_when_active_task_differs(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".task-state"
        self._write_handoff_db(state_dir)
        with sqlite3.connect(state_dir / "handoff.db") as conn:
            conn.execute("UPDATE handoff_state SET task_ref = 'other-task' WHERE id = 1")

        result = _handoff_memory("task-1", state_dir, tmp_path)

        assert result["data_available"] is True
        assert result["hot_state_size_bytes"] > 0
        assert result["total_decisions"] == 1
        assert result["total_findings"] == 1

    def test_handoff_memory_returns_zero_counts_for_unknown_task(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".task-state"
        self._write_handoff_db(state_dir)

        result = _handoff_memory("missing-task", state_dir, tmp_path)

        assert result["data_available"] is True
        assert result["hot_state_size_bytes"] > 0
        assert result["total_decisions"] == 0
        assert result["total_findings"] == 0

    def test_handoff_memory_returns_defaults_when_handoff_db_missing(self, tmp_path: Path) -> None:
        result = _handoff_memory("task-1", tmp_path / ".task-state", tmp_path)

        assert result == {
            "data_available": False,
            "hot_state_size_bytes": 0,
            "total_decisions": 0,
            "total_findings": 0,
            "artifact_source_count": 0,
        }


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
                "process_health": {"reopened_finding_rate": {"value": 0.1 * i}},
                "handoff_memory": {"hot_state_size_bytes": 1000 * i},
            }
            for i, t in enumerate([100, 200, 300], start=1)
        ]
        metrics.write_text(
            "\n".join(json.dumps(s) for s in snapshots) + "\n",
            encoding="utf-8",
        )
        result = render_sparklines(tmp_path, "demo")
        assert "Snapshots**: 3" in result
        assert "Token Burn" in result
        assert "Reopened Finding Rate" in result
        assert "Hot-State Size (bytes)" in result

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
