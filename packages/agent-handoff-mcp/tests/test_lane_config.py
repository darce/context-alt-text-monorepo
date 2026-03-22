"""Tests for scripts/mcp/lane_config.py task resolution helpers."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATION_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_handoff_mcp" / "orchestration"
SCRIPT_PATH = ORCHESTRATION_DIR / "lane_config.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("lane_config", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load lane_config module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_task_choice_prefers_explicit_supported_task() -> None:
    mod = _load_module()
    with mock.patch.object(mod, "list_task_refs", return_value=["phase-5", "phase-6"]):
        resolved = mod.resolve_task_choice(
            explicit_task="phase-6",
            active_task="daemon-9",
            sole_task="",
            lane_id=None,
            branch="feature/x",
            worktree_path=None,
            orchestrator_root=None,
        )
    assert resolved == "phase-6"


def test_resolve_task_choice_prefers_unique_lane_manifest_over_unsupported_active_task() -> None:
    mod = _load_module()
    with (
        mock.patch.object(mod, "list_task_refs", return_value=["phase-5"]),
        mock.patch.object(mod, "infer_task_from_branch_or_worktree", return_value=""),
        mock.patch.object(mod, "list_lanes", side_effect=lambda task_ref: ["backend-http", "frontend"] if task_ref == "phase-5" else []),
    ):
        resolved = mod.resolve_task_choice(
            explicit_task="",
            active_task="daemon-9",
            sole_task="phase-5",
            lane_id="backend-http",
            branch="feature/x",
            worktree_path=None,
            orchestrator_root=None,
    )
    assert resolved == "phase-5"


def test_resolve_task_choice_preserves_orchestrator_root_priority() -> None:
    mod = _load_module()
    with (
        mock.patch.object(mod, "list_task_refs", return_value=["phase-5"]),
        mock.patch.object(mod, "infer_task_from_branch_or_worktree", return_value="phase-5"),
    ):
        resolved = mod.resolve_task_choice(
            explicit_task="",
            active_task="",
            sole_task="phase-5",
            lane_id=None,
            branch="feature/6.0.2-retention-export",
            worktree_path=None,
            orchestrator_root=None,
            in_orchestrator_root=True,
        )
    assert resolved == "phase-5"


def test_recent_manifest_task_refs_orders_recent_activity_first(tmp_path: Path) -> None:
    mod = _load_module()
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir(parents=True)
    db_path = state_dir / "handoff.db"

    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE handoff_state (task_ref TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE decisions (task_ref TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE blockers (task_ref TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE next_actions (task_ref TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE verified_tests (task_ref TEXT, verified_at TEXT)")
        conn.execute("CREATE TABLE review_findings (task_ref TEXT, updated_at TEXT, resolved_at TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE worktree_lanes (task_ref TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE worker_reports (task_ref TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE lane_messages (task_ref TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO handoff_state VALUES (?, ?)", ("phase-older", "2026-03-17 10:00:00"))
        conn.execute("INSERT INTO handoff_state VALUES (?, ?)", ("phase-newer", "2026-03-18 10:00:00"))

    with mock.patch.object(mod, "list_task_refs", return_value=["phase-older", "phase-newer"]):
        ordered = mod._recent_manifest_task_refs(str(tmp_path), lane_id=None)

    assert ordered[:2] == ["phase-newer", "phase-older"]


def test_task_activity_labels_reads_last_activity_from_sqlite(tmp_path: Path) -> None:
    mod = _load_module()
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir(parents=True)
    db_path = state_dir / "handoff.db"

    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE handoff_state (task_ref TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE decisions (task_ref TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE blockers (task_ref TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE next_actions (task_ref TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE verified_tests (task_ref TEXT, verified_at TEXT)")
        conn.execute("CREATE TABLE review_findings (task_ref TEXT, updated_at TEXT, resolved_at TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE worktree_lanes (task_ref TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE worker_reports (task_ref TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE lane_messages (task_ref TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO handoff_state VALUES (?, ?)", ("phase-5", "2026-03-18 12:00:00"))

    labels = mod._task_activity_labels(str(tmp_path), ["phase-5"])
    assert labels == {"phase-5": "2026-03-18 12:00:00"}


def test_choose_task_interactively_returns_empty_when_not_tty() -> None:
    mod = _load_module()
    with (
        mock.patch.object(mod, "resolve_task_choice", return_value=""),
        mock.patch.object(mod, "_recent_manifest_task_refs", return_value=["phase-5", "phase-6"]),
        mock.patch.object(mod.sys.stdin, "isatty", return_value=False),
    ):
        chosen = mod.choose_task_interactively(
            explicit_task="",
            active_task="",
            sole_task="",
            lane_id="backend-http",
            branch="feature/x",
            worktree_path=None,
            orchestrator_root=None,
        )
    assert chosen == ""
