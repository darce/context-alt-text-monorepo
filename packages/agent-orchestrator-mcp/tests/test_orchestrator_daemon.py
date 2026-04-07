"""Tests for scripts/mcp/orchestrator_daemon.py -- orchestrator loop."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from agent_handoff_mcp.config import RuntimeConfig

from agent_orchestrator_mcp import api as mcp_api

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATION_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_orchestrator_mcp" / "orchestration"
SCRIPT_PATH = ORCHESTRATION_DIR / "orchestrator_daemon.py"
SCRIPT_DIR = ORCHESTRATION_DIR


def _load_module():
    spec = importlib.util.spec_from_file_location("orchestrator_daemon", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load orchestrator_daemon module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# OrchestratorLock
# ---------------------------------------------------------------------------


def test_lock_acquires(tmp_path: Path) -> None:
    mod = _load_module()
    lock = mod.OrchestratorLock(tmp_path)
    assert lock.acquire() is True
    lock.release()


def test_lock_second_instance_fails(tmp_path: Path) -> None:
    mod = _load_module()
    lock1 = mod.OrchestratorLock(tmp_path)
    assert lock1.acquire() is True

    lock2 = mod.OrchestratorLock(tmp_path)
    assert lock2.acquire() is False

    lock1.release()


def test_lock_release_allows_reacquire(tmp_path: Path) -> None:
    mod = _load_module()
    lock1 = mod.OrchestratorLock(tmp_path)
    assert lock1.acquire() is True
    lock1.release()

    lock2 = mod.OrchestratorLock(tmp_path)
    assert lock2.acquire() is True
    lock2.release()


def test_lock_writes_pid(tmp_path: Path) -> None:
    mod = _load_module()
    lock = mod.OrchestratorLock(tmp_path)
    assert lock.acquire() is True
    lock_data = json.loads((tmp_path / "orchestrator.lock").read_text())
    assert lock_data["pid"] == os.getpid()
    lock.release()


# ---------------------------------------------------------------------------
# Pause / Resume
# ---------------------------------------------------------------------------


def test_pause_creates_sentinel(tmp_path: Path) -> None:
    mod = _load_module()
    mod.daemon_pause(tmp_path)
    assert mod._is_paused(tmp_path) is True


def test_resume_removes_sentinel(tmp_path: Path) -> None:
    mod = _load_module()
    mod.daemon_pause(tmp_path)
    mod.daemon_resume(tmp_path)
    assert mod._is_paused(tmp_path) is False


def test_resume_noop_when_not_paused(tmp_path: Path) -> None:
    mod = _load_module()
    mod.daemon_resume(tmp_path)
    assert mod._is_paused(tmp_path) is False


def test_is_paused_false_by_default(tmp_path: Path) -> None:
    mod = _load_module()
    assert mod._is_paused(tmp_path) is False


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def test_log_creates_jsonl_entry(tmp_path: Path) -> None:
    mod = _load_module()
    mod._log(tmp_path, "INFO", "test_event", extra_key="val")
    log_path = tmp_path / "orchestrator.jsonl"
    assert log_path.exists()
    entry = json.loads(log_path.read_text().strip())
    assert entry["event"] == "test_event"
    assert entry["level"] == "INFO"
    assert entry["extra_key"] == "val"
    assert "ts" in entry


def test_log_appends(tmp_path: Path) -> None:
    mod = _load_module()
    mod._log(tmp_path, "INFO", "first")
    mod._log(tmp_path, "INFO", "second")
    lines = (tmp_path / "orchestrator.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# _sort_by_manifest_merge_order
# ---------------------------------------------------------------------------


def test_sort_by_merge_order() -> None:
    mod = _load_module()
    order = ["backend-domain", "backend-http", "wp-proxy", "frontend"]
    ready = ["frontend", "backend-domain"]
    assert mod._sort_by_manifest_merge_order(ready, order) == ["backend-domain", "frontend"]


def test_sort_unknown_lanes_last() -> None:
    mod = _load_module()
    order = ["a", "b"]
    ready = ["c", "a"]
    result = mod._sort_by_manifest_merge_order(ready, order)
    assert result[0] == "a"
    assert result[1] == "c"


# ---------------------------------------------------------------------------
# daemon_status
# ---------------------------------------------------------------------------


def test_daemon_status_empty(tmp_path: Path) -> None:
    mod = _load_module()
    status = mod.daemon_status(tmp_path, tmp_path)
    assert status["mode"] == "singleton"
    assert status["state_dir"] == str(tmp_path)
    assert status["log_dir"] == str(tmp_path)
    assert status["lock"]["held"] is False
    assert status["paused"] is False
    assert status["last_cycle"] is None
    assert status["last_verify"] is None


def test_daemon_status_with_log(tmp_path: Path) -> None:
    mod = _load_module()
    log_path = tmp_path / "orchestrator.jsonl"
    log_path.write_text(
        json.dumps({"event": "cycle_end", "intaked": ["a"]})
        + "\n"
        + json.dumps({"event": "verify_complete", "lane": "a", "passed": True})
        + "\n"
    )
    status = mod.daemon_status(tmp_path, tmp_path)
    assert status["last_cycle"]["event"] == "cycle_end"
    assert status["last_verify"]["event"] == "verify_complete"


def test_daemon_status_paused(tmp_path: Path) -> None:
    mod = _load_module()
    mod.daemon_pause(tmp_path)
    status = mod.daemon_status(tmp_path, tmp_path)
    assert status["paused"] is True


# ---------------------------------------------------------------------------
# _run_handoff_dispatch
# ---------------------------------------------------------------------------


def test_run_handoff_dispatch_success(tmp_path: Path) -> None:
    mod = _load_module()
    dispatch_output = json.dumps({"ok": True, "dispatched": {}})
    with mock.patch.object(mod.subprocess, "run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0, stdout=dispatch_output, stderr="")
        result = mod._run_handoff_dispatch(tmp_path, "test-task")
    assert result["ok"] is True


def test_run_handoff_dispatch_failure(tmp_path: Path) -> None:
    mod = _load_module()
    with mock.patch.object(mod.subprocess, "run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="error")
        with pytest.raises(RuntimeError, match="review_dispatch.py failed"):
            mod._run_handoff_dispatch(tmp_path, "test-task")


def test_run_handoff_dispatch_dry_run(tmp_path: Path) -> None:
    mod = _load_module()
    dispatch_output = json.dumps({"ok": True, "dry_run": True})
    with mock.patch.object(mod.subprocess, "run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0, stdout=dispatch_output, stderr="")
        mod._run_handoff_dispatch(tmp_path, "test-task", dry_run=True)
    call_args = mock_run.call_args[0][0]
    assert "--dry-run" in call_args


# ---------------------------------------------------------------------------
# _poll_merge_ready_lanes
# ---------------------------------------------------------------------------
def test_poll_merge_ready_lanes_direct(tmp_path: Path) -> None:
    """Test the actual logic with a patched import."""
    mod = _load_module()

    call_count = {"n": 0}
    responses = [
        json.dumps({"ok": True, "reports": [{"merge_ready": 1}]}),
        json.dumps({"ok": True, "reports": [{"merge_ready": 0}]}),
    ]

    def fake_list(task_ref=None, lane_id=None, limit=1):
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx]

    with mock.patch("agent_orchestrator_mcp.lanes.list_worker_reports", side_effect=fake_list):
        with mock.patch.object(mod, "_lane_has_unmerged_commits", return_value=True):
            result = mod._poll_merge_ready_lanes(tmp_path, "test-task", ["a", "b"])
    assert result == ["a"]


def test_poll_skips_already_merged_lane(tmp_path: Path) -> None:
    """A merge-ready report without unmerged commits should be skipped."""
    mod = _load_module()

    with mock.patch(
        "agent_orchestrator_mcp.lanes.list_worker_reports",
        return_value=json.dumps({"ok": True, "reports": [{"merge_ready": 1}]}),
    ):
        with mock.patch.object(mod, "_lane_has_unmerged_commits", return_value=False):
            result = mod._poll_merge_ready_lanes(tmp_path, "test-task", ["a"])
    assert result == []


# ---------------------------------------------------------------------------
# _lane_has_unmerged_commits
# ---------------------------------------------------------------------------


def test_lane_has_unmerged_commits_yes(tmp_path: Path) -> None:
    mod = _load_module()
    mock_manifest = mock.MagicMock()
    mock_manifest.get_lane_config.return_value = {"branch": "codex/task-a", "worktree_path": "/tmp/wt"}
    with mock.patch.dict(sys.modules, {"lane_manifest": mock_manifest}):
        with mock.patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="abc1234 some commit\n")
            assert mod._lane_has_unmerged_commits(tmp_path, "task", "a") is True


def test_lane_has_unmerged_commits_no(tmp_path: Path) -> None:
    mod = _load_module()
    mock_manifest = mock.MagicMock()
    mock_manifest.get_lane_config.return_value = {"branch": "codex/task-a", "worktree_path": "/tmp/wt"}
    with mock.patch.dict(sys.modules, {"lane_manifest": mock_manifest}):
        with mock.patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="")
            assert mod._lane_has_unmerged_commits(tmp_path, "task", "a") is False


def test_lane_has_unmerged_commits_no_config(tmp_path: Path) -> None:
    mod = _load_module()
    mock_manifest = mock.MagicMock()
    mock_manifest.get_lane_config.return_value = None
    with mock.patch.dict(sys.modules, {"lane_manifest": mock_manifest}):
        assert mod._lane_has_unmerged_commits(tmp_path, "task", "a") is False


# ---------------------------------------------------------------------------
# _resolve_lane_worktree
# ---------------------------------------------------------------------------


def test_resolve_lane_worktree_found(tmp_path: Path) -> None:
    mod = _load_module()
    mock_manifest = mock.MagicMock()
    mock_manifest.get_lane_config.return_value = {"worktree_path": str(tmp_path / "wt")}
    with mock.patch.dict(sys.modules, {"lane_manifest": mock_manifest}):
        result = mod._resolve_lane_worktree(tmp_path, "task", "a")
    assert result == tmp_path / "wt"


def test_resolve_lane_worktree_none(tmp_path: Path) -> None:
    mod = _load_module()
    mock_manifest = mock.MagicMock()
    mock_manifest.get_lane_config.return_value = None
    with mock.patch.dict(sys.modules, {"lane_manifest": mock_manifest}):
        assert mod._resolve_lane_worktree(tmp_path, "task", "a") is None


# ---------------------------------------------------------------------------
# _intake_lane
# ---------------------------------------------------------------------------


def test_intake_lane_success(tmp_path: Path) -> None:
    mod = _load_module()
    with mock.patch.object(mod.subprocess, "run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0)
        assert mod._intake_lane(tmp_path, "test-task", "lane-a") is True
    call_args = mock_run.call_args[0][0]
    assert "lane-intake" in call_args
    assert "TASK=test-task" in call_args
    assert "LANE=lane-a" in call_args


# ---------------------------------------------------------------------------
# _refresh_downstream
# ---------------------------------------------------------------------------


def test_refresh_downstream_all_success(tmp_path: Path) -> None:
    mod = _load_module()
    with mock.patch.object(mod.subprocess, "run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0)
        results = mod._refresh_downstream(tmp_path, "t", "a", ["b", "c"])
    assert results == [("b", True), ("c", True)]
    assert mock_run.call_count == 2


def test_refresh_downstream_partial_failure(tmp_path: Path) -> None:
    mod = _load_module()
    with mock.patch.object(mod.subprocess, "run") as mock_run:
        mock_run.side_effect = [
            mock.Mock(returncode=0),
            mock.Mock(returncode=1),
        ]
        results = mod._refresh_downstream(tmp_path, "t", "a", ["b", "c"])
    assert results == [("b", True), ("c", False)]


def test_refresh_downstream_empty(tmp_path: Path) -> None:
    mod = _load_module()
    with mock.patch.object(mod.subprocess, "run") as mock_run:
        results = mod._refresh_downstream(tmp_path, "t", "a", [])
    assert results == []
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# _run_cross_lane_verify
# ---------------------------------------------------------------------------


def test_cross_lane_verify_success(tmp_path: Path) -> None:
    mod = _load_module()
    lane_wt = tmp_path / "lane-a-wt"
    lane_wt.mkdir()
    with mock.patch.object(mod, "_resolve_lane_worktree", return_value=lane_wt):
        with mock.patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            assert mod._run_cross_lane_verify(tmp_path, "t", "a") is True
    assert mock_run.call_args[1]["cwd"] == lane_wt


def test_cross_lane_verify_failure(tmp_path: Path) -> None:
    mod = _load_module()
    lane_wt = tmp_path / "lane-a-wt"
    lane_wt.mkdir()
    with mock.patch.object(mod, "_resolve_lane_worktree", return_value=lane_wt):
        with mock.patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1)
            assert mod._run_cross_lane_verify(tmp_path, "t", "a") is False


def test_cross_lane_verify_no_worktree(tmp_path: Path) -> None:
    mod = _load_module()
    with mock.patch.object(mod, "_resolve_lane_worktree", return_value=None):
        assert mod._run_cross_lane_verify(tmp_path, "t", "a") is False


def test_cross_lane_verify_dry_run(tmp_path: Path) -> None:
    mod = _load_module()
    assert mod._run_cross_lane_verify(tmp_path, "t", "a", dry_run=True) is True


# ---------------------------------------------------------------------------
# orchestrator_loop -- single-pass
# ---------------------------------------------------------------------------


def _make_mock_runtime():
    """Create mock MCP runtime objects."""
    mock_config = mock.MagicMock()
    mock_config.for_workspace = mock.MagicMock(return_value=mock_config)
    return mock_config


def _make_mock_ahm(*, ready_to_close: bool = False) -> mock.MagicMock:
    mock_ahm = mock.MagicMock()
    mock_ahm.RuntimeConfig.for_workspace.return_value = mock.MagicMock()
    mock_ahm.configure_runtime = mock.MagicMock()
    mock_ahm.record_decision.return_value = json.dumps({"ok": True})
    mock_ahm.record_test_result.return_value = json.dumps({"ok": True})
    mock_ahm.handoff_close_check.return_value = json.dumps({"ok": True, "ready_to_close": ready_to_close})
    mock_ahm.list_lane_messages.return_value = json.dumps({"ok": True, "messages": []})
    mock_ahm.list_worktree_lanes.return_value = json.dumps({"ok": True, "lanes": []})
    mock_ahm.get_lane_activity.return_value = json.dumps({"ok": True, "lane": {}, "actions": []})
    mock_ahm.update_lane_message.return_value = json.dumps({"ok": True})
    mock_ahm.record_lane_message.return_value = json.dumps({"ok": True})
    mock_ahm.upsert_worktree_lane.return_value = json.dumps({"ok": True})
    mock_ahm.update_next_actions.return_value = json.dumps({"ok": True})
    mock_ahm.worker_status.return_value = json.dumps(
        {"ok": True, "running": False, "worker_state": "stopped", "attention_required": False}
    )
    mock_ahm.worker_start.return_value = json.dumps({"ok": True, "pid": 1234})
    return mock_ahm


def _configure_real_runtime(tmp_path: Path, task_ref: str) -> RuntimeConfig:
    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=tmp_path / ".task-state",
        current_task_path=tmp_path / "CURRENT_TASK.md",
        exports_dir=tmp_path / ".task-state" / "exports",
    )
    mcp_api.configure_runtime(runtime)
    json.loads(mcp_api.set_handoff_state(task_ref=task_ref, objective="daemon integration", status="in_progress"))
    return runtime


def test_single_pass_no_ready_lanes(tmp_path: Path) -> None:
    mod = _load_module()
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir()

    mock_ahm = _make_mock_ahm()
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["a", "b"]
    mock_manifest.downstream_lanes.return_value = []

    dispatch_output = json.dumps({"ok": True})

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout=dispatch_output, stderr="")
            result = mod.orchestrator_loop(
                orchestrator_root=tmp_path,
                task_ref="test-task",
                single_pass=True,
            )
    assert result == 0


def test_single_pass_dispatches_from_task_plan(tmp_path: Path) -> None:
    mod = _load_module()
    _configure_real_runtime(tmp_path, "phase-5-retention-export-and-audit-controls")
    plan_path = tmp_path / "docs" / "tasks" / "demo-task-plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("## Phase 1: Backend\n- [ ] Implement backend slice\n")
    json.loads(
        mcp_api.upsert_worktree_lane(
            lane_id="backend-domain",
            worktree_path=str(tmp_path / "backend-domain"),
            branch="codex/p5-backend-domain",
            status="active",
            objective="domain work",
        )
    )

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["backend-domain"]
    mock_manifest.downstream_lanes.return_value = []
    mock_manifest.task_plan_path.return_value = str(plan_path)
    mock_manifest.load_manifest.return_value = {
        "task_ref": "phase-5-retention-export-and-audit-controls",
        "lanes": {"backend-domain": {}},
        "heading_to_lane": {"Phase 1: Backend": "backend-domain"},
        "plan_routing_hints": [],
    }

    dispatch_output = json.dumps({"ok": True})

    with mock.patch.dict(sys.modules, {"lane_manifest": mock_manifest}):
        with mock.patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout=dispatch_output, stderr="")
            result = mod.orchestrator_loop(
                orchestrator_root=tmp_path,
                task_ref="phase-5-retention-export-and-audit-controls",
                single_pass=True,
            )

    assert result == 0
    messages = json.loads(
        mcp_api.list_lane_messages(
            task_ref="phase-5-retention-export-and-audit-controls",
            lane_id="backend-domain",
            status="open",
        )
    )["messages"]
    assert len(messages) == 1
    assert messages[0]["direction"] == "orchestrator_to_worker"
    assert "[plan:phase-1::phase-1-backend::checklist_1]" in messages[0]["message"]

    state = json.loads(
        mcp_api.get_handoff_state(
            task_ref="phase-5-retention-export-and-audit-controls",
            verbose=True,
        )
    )
    assert any("[plan:phase-1::phase-1-backend::checklist_1]" in row["action"] for row in state["actions_pending"])
    cursors = json.loads(
        mcp_api.list_plan_cursors(
            task_ref="phase-5-retention-export-and-audit-controls",
            state="dispatched",
        )
    )["cursors"]
    assert len(cursors) == 1
    assert cursors[0]["lane_id"] == "backend-domain"


def test_single_pass_dispatches_next_eligible_task_plan_item(tmp_path: Path) -> None:
    mod = _load_module()
    _configure_real_runtime(tmp_path, "phase-5-retention-export-and-audit-controls")
    plan_path = tmp_path / "docs" / "tasks" / "demo-task-plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("## Phase 1: Backend\n- [ ] Implement backend slice\n- [ ] Verify backend slice\n")
    json.loads(
        mcp_api.upsert_worktree_lane(
            lane_id="backend-domain",
            worktree_path=str(tmp_path / "backend-domain"),
            branch="codex/p5-backend-domain",
            status="active",
            objective="domain work",
        )
    )

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["backend-domain"]
    mock_manifest.downstream_lanes.return_value = []
    mock_manifest.task_plan_path.return_value = str(plan_path)
    mock_manifest.load_manifest.return_value = {
        "task_ref": "phase-5-retention-export-and-audit-controls",
        "lanes": {"backend-domain": {}},
        "heading_to_lane": {"Phase 1: Backend": "backend-domain"},
        "plan_routing_hints": [],
    }

    dispatch_output = json.dumps({"ok": True})
    with mock.patch.dict(sys.modules, {"lane_manifest": mock_manifest}):
        with mock.patch.object(
            mod.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=dispatch_output, stderr="")
        ):
            assert (
                mod.orchestrator_loop(
                    orchestrator_root=tmp_path,
                    task_ref="phase-5-retention-export-and-audit-controls",
                    single_pass=True,
                )
                == 0
            )

            first_cursor = json.loads(
                mcp_api.list_plan_cursors(
                    task_ref="phase-5-retention-export-and-audit-controls",
                    state="dispatched",
                )
            )["cursors"]
            assert len(first_cursor) == 1
            assert first_cursor[0]["plan_item_id"] == "phase-1::phase-1-backend::checklist_1"

            first_actions = json.loads(
                mcp_api.list_next_actions(
                    task_ref="phase-5-retention-export-and-audit-controls",
                    status="pending",
                    limit=20,
                )
            )["actions"]
            assert len(first_actions) == 1
            json.loads(
                mcp_api.update_next_actions(
                    operation="update",
                    action_id=int(first_actions[0]["id"]),
                    status="done",
                )
            )

            first_messages = json.loads(
                mcp_api.list_lane_messages(
                    task_ref="phase-5-retention-export-and-audit-controls",
                    lane_id="backend-domain",
                    status="open",
                )
            )["messages"]
            assert len(first_messages) == 1
            json.loads(mcp_api.update_lane_message(int(first_messages[0]["id"]), "closed"))

            json.loads(
                mcp_api.upsert_plan_cursor(
                    task_ref="phase-5-retention-export-and-audit-controls",
                    plan_item_id="phase-1::phase-1-backend::checklist_1",
                    state="completed",
                    lane_id="backend-domain",
                )
            )

            assert (
                mod.orchestrator_loop(
                    orchestrator_root=tmp_path,
                    task_ref="phase-5-retention-export-and-audit-controls",
                    single_pass=True,
                )
                == 0
            )

    cursors = json.loads(
        mcp_api.list_plan_cursors(
            task_ref="phase-5-retention-export-and-audit-controls",
            state="dispatched",
        )
    )["cursors"]
    dispatched_ids = {row["plan_item_id"] for row in cursors}
    assert "phase-1::phase-1-backend::checklist_2" in dispatched_ids


def test_single_pass_dispatches_only_one_plan_item_per_cycle(tmp_path: Path) -> None:
    mod = _load_module()
    _configure_real_runtime(tmp_path, "phase-5-retention-export-and-audit-controls")
    plan_path = tmp_path / "docs" / "tasks" / "demo-task-plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("## Phase 1: Backend\n- [ ] Implement backend slice\n- [ ] Verify backend slice\n")
    json.loads(
        mcp_api.upsert_worktree_lane(
            lane_id="backend-domain",
            worktree_path=str(tmp_path / "backend-domain"),
            branch="codex/p5-backend-domain",
            status="active",
            objective="domain work",
        )
    )

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["backend-domain"]
    mock_manifest.downstream_lanes.return_value = []
    mock_manifest.task_plan_path.return_value = str(plan_path)
    mock_manifest.load_manifest.return_value = {
        "task_ref": "phase-5-retention-export-and-audit-controls",
        "lanes": {"backend-domain": {}},
        "heading_to_lane": {"Phase 1: Backend": "backend-domain"},
        "plan_routing_hints": [],
    }

    dispatch_output = json.dumps({"ok": True})
    with mock.patch.dict(sys.modules, {"lane_manifest": mock_manifest}):
        with mock.patch.object(
            mod.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=dispatch_output, stderr="")
        ):
            assert (
                mod.orchestrator_loop(
                    orchestrator_root=tmp_path,
                    task_ref="phase-5-retention-export-and-audit-controls",
                    single_pass=True,
                )
                == 0
            )

    cursors = json.loads(
        mcp_api.list_plan_cursors(
            task_ref="phase-5-retention-export-and-audit-controls",
            state="dispatched",
        )
    )["cursors"]
    assert len(cursors) == 1
    assert cursors[0]["plan_item_id"] == "phase-1::phase-1-backend::checklist_1"


def test_single_pass_prefers_upstream_lane_over_document_order(tmp_path: Path) -> None:
    mod = _load_module()
    _configure_real_runtime(tmp_path, "phase-5-retention-export-and-audit-controls")
    plan_path = tmp_path / "docs" / "tasks" / "dependency-plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        "## Phase 3: Backend HTTP\n"
        "- [ ] Implement HTTP slice\n"
        "## Phase 1: Backend Domain\n"
        "- [ ] Implement domain slice\n"
    )
    json.loads(
        mcp_api.upsert_worktree_lane(
            lane_id="backend-domain",
            worktree_path=str(tmp_path / "backend-domain"),
            branch="codex/p5-backend-domain",
            status="active",
            objective="domain work",
        )
    )
    json.loads(
        mcp_api.upsert_worktree_lane(
            lane_id="backend-http",
            worktree_path=str(tmp_path / "backend-http"),
            branch="codex/p5-backend-http",
            status="active",
            objective="http work",
        )
    )

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["backend-domain", "backend-http"]
    mock_manifest.downstream_lanes.return_value = []
    mock_manifest.task_plan_path.return_value = str(plan_path)
    mock_manifest.load_manifest.return_value = {
        "task_ref": "phase-5-retention-export-and-audit-controls",
        "merge_order": ["backend-domain", "backend-http"],
        "lanes": {"backend-domain": {}, "backend-http": {}},
        "heading_to_lane": {
            "Phase 1: Backend Domain": "backend-domain",
            "Phase 3: Backend HTTP": "backend-http",
        },
        "plan_routing_hints": [],
    }

    dispatch_output = json.dumps({"ok": True})
    with mock.patch.dict(sys.modules, {"lane_manifest": mock_manifest}):
        with mock.patch.object(
            mod.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=dispatch_output, stderr="")
        ):
            assert (
                mod.orchestrator_loop(
                    orchestrator_root=tmp_path,
                    task_ref="phase-5-retention-export-and-audit-controls",
                    single_pass=True,
                )
                == 0
            )

    cursors = json.loads(
        mcp_api.list_plan_cursors(
            task_ref="phase-5-retention-export-and-audit-controls",
            state="dispatched",
        )
    )["cursors"]
    assert len(cursors) == 1
    assert cursors[0]["lane_id"] == "backend-domain"
    assert cursors[0]["plan_item_id"] == "phase-1::phase-1-backend-domain::checklist_1"


def test_dispatch_plan_item_result_exposes_lane_field(tmp_path: Path) -> None:
    mod = _load_module()
    result = mod._dispatch_plan_item(
        "test-task",
        lane_id="backend-domain",
        plan_item_id="phase-1::backend::checklist_1",
        summary="Implement backend slice",
        heading="Phase 1: Backend",
        resolved_plan=tmp_path / "task-plan.md",
        dry_run=True,
    )
    assert result.get("lane_id") == "backend-domain"


def test_resolve_task_ref_prefers_explicit_value(tmp_path: Path) -> None:
    mod = _load_module()
    assert mod._resolve_task_ref(tmp_path, "explicit-task") == "explicit-task"


def test_resolve_task_ref_falls_back_to_active_task(tmp_path: Path) -> None:
    mod = _load_module()
    mock_ahm = mock.MagicMock()
    mock_ahm.RuntimeConfig.for_workspace.return_value = mock.MagicMock()
    mock_ahm.configure_runtime.return_value = None
    mock_ahm.get_handoff_state.return_value = json.dumps({"ok": True, "task_ref": "active-task"})
    mock_manifest = mock.MagicMock()
    mock_manifest.list_manifest_tasks.return_value = ["active-task", "other-task"]
    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        assert mod._resolve_task_ref(tmp_path, None) == "active-task"
    mock_ahm.get_handoff_state.assert_called_once_with(sections="identity")


def test_resolve_task_ref_accepts_identity_only_payload(tmp_path: Path) -> None:
    mod = _load_module()
    mock_ahm = mock.MagicMock()
    mock_ahm.RuntimeConfig.for_workspace.return_value = mock.MagicMock()
    mock_ahm.configure_runtime.return_value = None
    mock_ahm.get_handoff_state.return_value = json.dumps({"ok": True, "task_ref": "identity-task"})
    mock_manifest = mock.MagicMock()
    mock_manifest.list_manifest_tasks.return_value = ["identity-task", "other-task"]
    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        assert mod._resolve_task_ref(tmp_path, None) == "identity-task"
    mock_ahm.get_handoff_state.assert_called_once_with(sections="identity")


def test_resolve_task_ref_falls_back_to_sole_manifest(tmp_path: Path) -> None:
    mod = _load_module()
    mock_ahm = mock.MagicMock()
    mock_ahm.RuntimeConfig.for_workspace.return_value = mock.MagicMock()
    mock_ahm.configure_runtime.return_value = None
    mock_ahm.get_handoff_state.return_value = json.dumps({"ok": True, "task_ref": ""})
    mock_manifest = mock.MagicMock()
    mock_manifest.list_manifest_tasks.return_value = ["only-task"]
    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        assert mod._resolve_task_ref(tmp_path, None) == "only-task"


def test_resolve_task_ref_falls_back_when_identity_payload_omits_task_ref(tmp_path: Path) -> None:
    mod = _load_module()
    mock_ahm = mock.MagicMock()
    mock_ahm.RuntimeConfig.for_workspace.return_value = mock.MagicMock()
    mock_ahm.configure_runtime.return_value = None
    mock_ahm.get_handoff_state.return_value = json.dumps({"ok": True, "active": {"task_ref": "nested-only"}})
    mock_manifest = mock.MagicMock()
    mock_manifest.list_manifest_tasks.return_value = ["only-task"]
    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        assert mod._resolve_task_ref(tmp_path, None) == "only-task"
    mock_ahm.get_handoff_state.assert_called_once_with(sections="identity")


def test_resolve_task_ref_errors_when_ambiguous(tmp_path: Path) -> None:
    mod = _load_module()
    mock_ahm = mock.MagicMock()
    mock_ahm.RuntimeConfig.for_workspace.return_value = mock.MagicMock()
    mock_ahm.configure_runtime.return_value = None
    mock_ahm.get_handoff_state.return_value = json.dumps({"ok": True, "task_ref": ""})
    mock_manifest = mock.MagicMock()
    mock_manifest.list_manifest_tasks.return_value = ["task-a", "task-b"]
    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with pytest.raises(RuntimeError, match="Available manifests: task-a, task-b"):
            mod._resolve_task_ref(tmp_path, None)


def test_parse_args_run_accepts_optional_task_ref_and_backend() -> None:
    mod = _load_module()
    argv = [
        "orchestrator_daemon.py",
        "run",
        "--orchestrator-root",
        "/tmp/orchestrator-root",
        "--backend",
        "codex-subagent",
        "--worker-start-mode",
        "manual",
        "--single-pass",
    ]
    with mock.patch.object(sys, "argv", argv):
        args = mod._parse_args()
    assert args.command == "run"
    assert args.task_ref is None
    assert args.backend == "codex-subagent"
    assert args.worker_start_mode == "manual"
    assert args.single_pass is True


def test_main_run_errors_clearly_when_task_inference_is_ambiguous(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load_module()
    args = mock.Mock(
        command="run",
        orchestrator_root=str(tmp_path),
        task_ref=None,
        poll_interval=60,
        single_pass=True,
        backend="codex-cli",
        dry_run=True,
        state_dir=None,
    )
    with mock.patch.object(mod, "_parse_args", return_value=args):
        with mock.patch.object(
            mod, "_resolve_task_ref", side_effect=RuntimeError("Available manifests: task-a, task-b")
        ):
            assert mod.main() == 1
    captured = capsys.readouterr()
    assert "Available manifests: task-a, task-b" in captured.err


def test_main_run_threads_backend_to_orchestrator_loop(tmp_path: Path) -> None:
    mod = _load_module()
    args = mock.Mock(
        command="run",
        orchestrator_root=str(tmp_path),
        task_ref=None,
        poll_interval=15,
        single_pass=True,
        backend="codex-subagent",
        worker_start_mode="manual",
        worker_reasoning_effort="auto",
        model=None,
        dry_run=True,
        state_dir=None,
    )
    mock_lock = mock.Mock()
    mock_lock.acquire.return_value = True
    with mock.patch.object(mod, "_parse_args", return_value=args):
        with mock.patch.object(mod, "_resolve_task_ref", return_value="resolved-task"):
            with mock.patch.object(mod, "OrchestratorLock", return_value=mock_lock):
                with mock.patch.object(mod, "orchestrator_loop", return_value=0) as mock_loop:
                    assert mod.main() == 0
    mock_loop.assert_called_once_with(
        orchestrator_root=tmp_path.resolve(),
        task_ref="resolved-task",
        poll_interval=15,
        single_pass=True,
        backend="codex-subagent",
        worker_start_mode="manual",
        worker_reasoning_effort="auto",
        model=None,
        dry_run=True,
        state_dir=tmp_path.resolve() / ".task-state",
    )
    mock_lock.release.assert_called_once()


def test_single_pass_autostarts_actionable_worker_via_mcp(tmp_path: Path) -> None:
    mod = _load_module()
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir()
    lane_wt = tmp_path / "backend-domain"
    lane_wt.mkdir()

    mock_ahm = _make_mock_ahm()
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})
    mock_ahm.worker_status.return_value = json.dumps(
        {
            "ok": True,
            "lane_id": "backend-domain",
            "running": False,
            "worker_state": "stopped",
            "attention_required": False,
        }
    )
    mock_ahm.worker_start.return_value = json.dumps({"ok": True, "pid": 1234, "lane_id": "backend-domain"})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["backend-domain"]
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod, "_resolve_lane_worktree", return_value=lane_wt):
            with mock.patch("worker_daemon.poll_lane_state", return_value="actionable"):
                with mock.patch.object(
                    mod.subprocess,
                    "run",
                    return_value=mock.Mock(returncode=0, stdout=json.dumps({"ok": True}), stderr=""),
                ):
                    with mock.patch(
                        "agent_orchestrator_mcp.api.worker_status",
                        return_value=json.dumps(
                            {
                                "ok": True,
                                "lane_id": "backend-domain",
                                "running": False,
                                "worker_state": "stopped",
                                "attention_required": False,
                            }
                        ),
                    ):
                        with mock.patch(
                            "agent_orchestrator_mcp.api.worker_start",
                            return_value=json.dumps({"ok": True, "pid": 1234, "lane_id": "backend-domain"}),
                        ) as mock_start:
                            result = mod.orchestrator_loop(
                                orchestrator_root=tmp_path,
                                task_ref="test-task",
                                single_pass=True,
                                backend="codex-subagent",
                            )

    assert result == 0
    mock_start.assert_called_once()


def test_single_pass_running_worker_prevents_plan_stall(tmp_path: Path) -> None:
    mod = _load_module()
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir()
    lane_wt = tmp_path / "backend-domain"
    lane_wt.mkdir()

    mock_ahm = _make_mock_ahm()
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})
    mock_ahm.worker_status.return_value = json.dumps(
        {
            "ok": True,
            "lane_id": "backend-domain",
            "running": True,
            "worker_state": "executing",
            "attention_required": False,
        }
    )

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["backend-domain"]
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod, "_resolve_lane_worktree", return_value=lane_wt):
            with mock.patch("worker_daemon.poll_lane_state", return_value="actionable"):
                with mock.patch.object(
                    mod,
                    "_remaining_plan_work",
                    return_value=[{"plan_item_id": "p1", "cursor_state": "", "lane_id": "backend-domain"}],
                ):
                    with mock.patch.object(
                        mod.subprocess,
                        "run",
                        return_value=mock.Mock(returncode=0, stdout=json.dumps({"ok": True}), stderr=""),
                    ):
                        with mock.patch(
                            "agent_orchestrator_mcp.api.worker_status",
                            return_value=json.dumps(
                                {
                                    "ok": True,
                                    "lane_id": "backend-domain",
                                    "running": True,
                                    "worker_state": "executing",
                                    "attention_required": False,
                                }
                            ),
                        ):
                            with mock.patch("agent_orchestrator_mcp.api.worker_start") as mock_start:
                                result = mod.orchestrator_loop(
                                    orchestrator_root=tmp_path,
                                    task_ref="test-task",
                                    single_pass=True,
                                    backend="codex-subagent",
                                )

    assert result == 0
    mock_start.assert_not_called()


def test_single_pass_manual_worker_mode_skips_mcp_autostart(tmp_path: Path) -> None:
    mod = _load_module()
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir()
    lane_wt = tmp_path / "backend-domain"
    lane_wt.mkdir()

    mock_ahm = _make_mock_ahm()
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})
    mock_ahm.worker_status.return_value = json.dumps(
        {
            "ok": True,
            "lane_id": "backend-domain",
            "running": False,
            "worker_state": "stopped",
            "attention_required": False,
        }
    )

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["backend-domain"]
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod, "_resolve_lane_worktree", return_value=lane_wt):
            with mock.patch("worker_daemon.poll_lane_state", return_value="actionable"):
                with mock.patch.object(
                    mod.subprocess,
                    "run",
                    return_value=mock.Mock(returncode=0, stdout=json.dumps({"ok": True}), stderr=""),
                ):
                    with mock.patch(
                        "agent_orchestrator_mcp.api.worker_status",
                        return_value=json.dumps(
                            {
                                "ok": True,
                                "lane_id": "backend-domain",
                                "running": False,
                                "worker_state": "stopped",
                                "attention_required": False,
                            }
                        ),
                    ):
                        with mock.patch("agent_orchestrator_mcp.api.worker_start") as mock_start:
                            result = mod.orchestrator_loop(
                                orchestrator_root=tmp_path,
                                task_ref="test-task",
                                single_pass=True,
                                backend="codex-subagent",
                                worker_start_mode="manual",
                            )

    assert result == 0
    mock_start.assert_not_called()


def test_single_pass_logs_lanes_discovered(tmp_path: Path) -> None:
    mod = _load_module()
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir()

    mock_ahm = _make_mock_ahm()
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["backend-domain", "backend-http"]
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod, "_log") as mock_log:
            with mock.patch.object(
                mod.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=json.dumps({"ok": True}), stderr="")
            ):
                result = mod.orchestrator_loop(
                    orchestrator_root=tmp_path,
                    task_ref="test-task",
                    single_pass=True,
                )
    assert result == 0
    assert any(
        call.args[2] == "manifest_loaded" and call.kwargs.get("merge_order") == ["backend-domain", "backend-http"]
        for call in mock_log.call_args_list
    )


def test_single_pass_intakes_ready_lane(tmp_path: Path) -> None:
    mod = _load_module()
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir()

    mock_ahm = _make_mock_ahm()
    mock_ahm.record_lane_brief.return_value = json.dumps({"ok": True})
    mock_ahm.list_worker_reports.side_effect = [
        json.dumps({"ok": True, "reports": [{"merge_ready": 1}]}),
        json.dumps({"ok": True, "reports": []}),
        json.dumps(
            {
                "ok": True,
                "reports": [
                    {
                        "merge_ready": 1,
                        "summary": "lane a merged cleanly",
                        "changed_files": ["apps/prototype-description-service/export_service.py"],
                        "test_commands": ["pytest recognition/tests/unit/test_export_service.py"],
                    }
                ],
            }
        ),
    ]

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["a", "b"]
    mock_manifest.downstream_lanes.return_value = ["b"]

    dispatch_output = json.dumps({"ok": True})
    intake_calls: list[list[str]] = []

    def capture_run(cmd, **kwargs):
        if isinstance(cmd, list):
            intake_calls.append(cmd)
        return mock.Mock(returncode=0, stdout=dispatch_output, stderr="")

    lane_wt = tmp_path / "lane-a-wt"
    lane_wt.mkdir()

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod, "_lane_has_unmerged_commits", return_value=True):
            with mock.patch.object(mod, "_resolve_lane_worktree", return_value=lane_wt):
                with mock.patch.object(mod.subprocess, "run", side_effect=capture_run):
                    result = mod.orchestrator_loop(
                        orchestrator_root=tmp_path,
                        task_ref="test-task",
                        single_pass=True,
                    )
    assert result == 0
    # Should have called subprocess for: dispatch, intake(a), refresh(b), verify(a)
    make_targets = [c for c in intake_calls if isinstance(c, list) and len(c) > 1 and c[0] == "make"]
    target_names = [c[1] for c in make_targets]
    assert "lane-intake" in target_names
    assert "lane-refresh" in target_names
    assert "lane-check" in target_names


def test_single_pass_paused_exits_cleanly(tmp_path: Path) -> None:
    mod = _load_module()
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir()
    mod.daemon_pause(state_dir)

    mock_ahm = _make_mock_ahm()

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = []
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        result = mod.orchestrator_loop(
            orchestrator_root=tmp_path,
            task_ref="test-task",
            single_pass=True,
        )
    assert result == 0


def test_single_pass_dry_run_skips_recording(tmp_path: Path) -> None:
    mod = _load_module()
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir()

    mock_ahm = _make_mock_ahm()
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": [{"merge_ready": 1}]})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["a"]
    mock_manifest.downstream_lanes.return_value = []

    dispatch_output = json.dumps({"ok": True})

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod, "_lane_has_unmerged_commits", return_value=True):
            with mock.patch.object(mod.subprocess, "run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0, stdout=dispatch_output, stderr="")
                result = mod.orchestrator_loop(
                    orchestrator_root=tmp_path,
                    task_ref="test-task",
                    single_pass=True,
                    dry_run=True,
                )
    assert result == 0
    mock_ahm.record_decision.assert_not_called()
    mock_ahm.record_test_result.assert_not_called()


def test_single_pass_dispatch_failure_continues(tmp_path: Path) -> None:
    """Repeated dispatch failure should fail the single pass."""
    mod = _load_module()
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir()

    mock_ahm = _make_mock_ahm()
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["a"]
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod.subprocess, "run") as mock_run:
            # Dispatch fails
            mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="dispatch error")
            result = mod.orchestrator_loop(
                orchestrator_root=tmp_path,
                task_ref="test-task",
                single_pass=True,
            )
    assert result == 1


def test_intake_failure_skips_refresh_and_verify(tmp_path: Path) -> None:
    mod = _load_module()
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir()

    mock_ahm = _make_mock_ahm()
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": [{"merge_ready": 1}]})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["a"]
    mock_manifest.downstream_lanes.return_value = ["b"]

    dispatch_output = json.dumps({"ok": True})
    all_calls: list[list[str]] = []

    def capture_run(cmd, **kwargs):
        if isinstance(cmd, list):
            all_calls.append(cmd)
            if len(cmd) > 1 and cmd[1] == "lane-intake":
                return mock.Mock(returncode=1, stdout="", stderr="")
        return mock.Mock(returncode=0, stdout=dispatch_output, stderr="")

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod, "_lane_has_unmerged_commits", return_value=True):
            with mock.patch.object(mod.subprocess, "run", side_effect=capture_run):
                result = mod.orchestrator_loop(
                    orchestrator_root=tmp_path,
                    task_ref="test-task",
                    single_pass=True,
                )
    assert result == 0
    make_targets = [c[1] for c in all_calls if isinstance(c, list) and len(c) > 1 and c[0] == "make"]
    assert "lane-intake" in make_targets
    assert "lane-refresh" not in make_targets
    assert "lane-check" not in make_targets


def test_list_open_worker_guidance_filters_client_side() -> None:
    mod = _load_module()
    mock_ahm = mock.MagicMock()
    mock_ahm.list_lane_messages.return_value = json.dumps(
        {
            "ok": True,
            "messages": [
                {"id": 1, "direction": "worker_to_orchestrator", "lane_id": "frontend"},
                {"id": 2, "direction": "orchestrator_to_worker", "lane_id": "frontend"},
            ],
        }
    )
    with mock.patch.dict(sys.modules, {"agent_handoff_mcp": mock_ahm, "agent_orchestrator_mcp.lanes": mock_ahm}):
        rows = mod._list_open_worker_guidance("task")
    assert [row["id"] for row in rows] == [1]


def test_dedupe_worker_guidance_messages_keeps_newest_per_lane() -> None:
    mod = _load_module()
    rows = mod._dedupe_worker_guidance_messages(
        [
            {"id": 1, "lane_id": "frontend", "created_at": "2026-03-16 10:00:00"},
            {"id": 2, "lane_id": "frontend", "created_at": "2026-03-16 11:00:00"},
            {"id": 3, "lane_id": "backend", "created_at": "2026-03-16 09:00:00"},
        ]
    )
    assert sorted((row["lane_id"], row["id"]) for row in rows) == [
        ("backend", 3),
        ("frontend", 2),
    ]


def test_list_open_dispatch_messages_filters_client_side() -> None:
    mod = _load_module()
    mock_ahm = mock.MagicMock()
    mock_ahm.list_lane_messages.return_value = json.dumps(
        {
            "ok": True,
            "messages": [
                {"id": 1, "direction": "worker_to_orchestrator", "lane_id": "frontend"},
                {"id": 2, "direction": "orchestrator_to_worker", "lane_id": "frontend"},
            ],
        }
    )
    with mock.patch.dict(sys.modules, {"agent_handoff_mcp": mock_ahm, "agent_orchestrator_mcp.lanes": mock_ahm}):
        rows = mod._list_open_dispatch_messages("task", "frontend")
    assert [row["id"] for row in rows] == [2]


def test_latest_lane_report_prefers_matching_session() -> None:
    mod = _load_module()
    mock_ahm = mock.MagicMock()
    mock_ahm.list_worker_reports.return_value = json.dumps(
        {
            "ok": True,
            "reports": [
                {"id": 1, "session": "other"},
                {"id": 2, "session": "wanted"},
            ],
        }
    )
    with mock.patch.dict(sys.modules, {"agent_handoff_mcp": mock_ahm, "agent_orchestrator_mcp.lanes": mock_ahm}):
        report = mod._latest_lane_report("task", "lane", session="wanted")
    assert report["id"] == 2


def test_resolve_next_assignment_prefers_pending_action() -> None:
    mod = _load_module()
    activity = {
        "lane": {"objective": "fallback objective"},
        "actions": [
            {"id": 2, "status": "pending", "priority": 5, "action": "Later action"},
            {"id": 1, "status": "pending", "priority": 1, "action": "First action"},
        ],
    }
    assignment = mod._resolve_next_assignment(
        "phase-5-retention-export-and-audit-controls",
        "backend-domain",
        activity,
        "remaining backend-domain implementation target",
    )
    assert assignment == ("backend-domain next assignment", "First action")


def test_classify_guidance_review_for_already_resolved_lane() -> None:
    mod = _load_module()
    resolution = mod._classify_guidance(
        task_ref="phase-5-retention-export-and-audit-controls",
        worker_message={
            "id": 10,
            "lane_id": "backend-http",
            "message": "No code changes were warranted because the assigned retention wiring appears already resolved and now needs orchestrator review.",
        },
        latest_report={"id": 20, "summary": "already resolved"},
        activity={"lane": {"objective": "http work"}, "actions": []},
        open_dispatches=[{"id": 30}],
    )
    assert resolution.kind == "review"
    assert resolution.close_dispatch_ids == (30,)


def test_classify_guidance_env_blocker() -> None:
    mod = _load_module()
    resolution = mod._classify_guidance(
        task_ref="phase-5-retention-export-and-audit-controls",
        worker_message={
            "id": 12,
            "lane_id": "frontend",
            "message": "Filesystem sandbox is read-only and there is no writable temp directory.",
        },
        latest_report={"id": 22, "summary": "blocked by read-only sandbox"},
        activity={"lane": {"objective": "frontend work"}, "actions": []},
        open_dispatches=[],
    )
    assert resolution.kind == "blocked"


def test_classify_guidance_phase5_backend_domain_redispatch() -> None:
    mod = _load_module()
    resolution = mod._classify_guidance(
        task_ref="phase-5-retention-export-and-audit-controls",
        worker_message={
            "id": 11,
            "lane_id": "backend-domain",
            "message": "The remaining backend-domain implementation target is snapshot provenance/disposed-row filtering in cluster_repository.py.",
        },
        latest_report={"id": 21, "summary": "remaining backend-domain implementation target"},
        activity={"lane": {"objective": "domain work"}, "actions": []},
        open_dispatches=[],
    )
    assert resolution.kind == "redispatch"
    assert resolution.dispatch_subject == "backend-domain snapshot provenance and disposal"


def test_resolve_next_assignment_uses_manifest_guidance_fallbacks() -> None:
    mod = _load_module()
    assignment = mod._resolve_next_assignment(
        "phase-5-retention-export-and-audit-controls",
        "backend-domain",
        {"lane": {"objective": "domain work"}, "actions": []},
        "The remaining backend-domain implementation target is snapshot_generation_id stamping in cluster_repository.py.",
    )
    assert assignment == (
        "backend-domain snapshot provenance and disposal",
        "Implement the backend-domain snapshot provenance/disposal slice in apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py and related backend-domain-owned tests/services. Add snapshot_generation_id stamping/return for get_snapshot(), exclude disposed rows from snapshot reads, and keep HTTP analyze.py changes out of this lane.",
    )


def test_apply_guidance_resolution_closes_messages_and_records_dispatch(tmp_path: Path) -> None:
    mod = _load_module()
    resolution = mod.GuidanceResolution(
        kind="redispatch",
        lane_id="backend-domain",
        worker_message_id=10,
        decision="d",
        rationale="r",
        lane_status="active",
        lane_notes="n",
        dispatch_subject="subject",
        dispatch_message="message",
        close_dispatch_ids=(20, 21),
    )
    mock_ahm = mock.MagicMock()
    mock_ahm.list_worktree_lanes.return_value = json.dumps(
        {
            "ok": True,
            "lanes": [
                {
                    "lane_id": "backend-domain",
                    "worktree_path": str(tmp_path / "wt"),
                    "branch": "codex/p5-backend-domain",
                    "title": "Backend Domain",
                    "objective": "domain",
                    "owner_agent": "codex",
                }
            ],
        }
    )
    mock_ahm.update_lane_message.return_value = json.dumps({"ok": True})
    mock_ahm.upsert_worktree_lane.return_value = json.dumps({"ok": True})
    mock_ahm.record_lane_message.return_value = json.dumps({"ok": True})
    mock_ahm.record_decision.return_value = json.dumps({"ok": True})
    with mock.patch.dict(sys.modules, {"agent_handoff_mcp": mock_ahm, "agent_orchestrator_mcp.lanes": mock_ahm}):
        mod._apply_guidance_resolution(
            task_ref="phase-5-retention-export-and-audit-controls",
            orchestrator_root=tmp_path,
            resolution=resolution,
            dry_run=False,
        )
    assert mock_ahm.update_lane_message.call_args_list[0].args == (10, "closed")
    assert mock_ahm.update_lane_message.call_args_list[1].args == (20, "closed")
    assert mock_ahm.update_lane_message.call_args_list[2].args == (21, "closed")
    mock_ahm.record_lane_message.assert_called_once()
    mock_ahm.record_decision.assert_called_once()


def test_apply_guidance_resolution_review_completes_pending_actions(tmp_path: Path) -> None:
    mod = _load_module()
    resolution = mod.GuidanceResolution(
        kind="review",
        lane_id="backend-http",
        worker_message_id=10,
        decision="d",
        rationale="r",
        lane_status="review",
        lane_notes="n",
        close_dispatch_ids=(20,),
    )
    mock_ahm = mock.MagicMock()
    mock_ahm.list_worktree_lanes.return_value = json.dumps(
        {
            "ok": True,
            "lanes": [
                {
                    "lane_id": "backend-http",
                    "worktree_path": str(tmp_path / "wt"),
                    "branch": "codex/p5-backend-http",
                    "title": "Backend HTTP",
                    "objective": "http",
                    "owner_agent": "codex",
                }
            ],
        }
    )
    mock_ahm.get_lane_activity.return_value = json.dumps(
        {
            "ok": True,
            "lane": {"objective": "http"},
            "actions": [{"id": 7, "status": "pending", "priority": 1, "action": "Fix already-resolved wiring"}],
        }
    )
    mock_ahm.update_lane_message.return_value = json.dumps({"ok": True})
    mock_ahm.upsert_worktree_lane.return_value = json.dumps({"ok": True})
    mock_ahm.record_decision.return_value = json.dumps({"ok": True})
    with mock.patch.dict(sys.modules, {"agent_handoff_mcp": mock_ahm, "agent_orchestrator_mcp.lanes": mock_ahm}):
        mod._apply_guidance_resolution(
            task_ref="phase-5-retention-export-and-audit-controls",
            orchestrator_root=tmp_path,
            resolution=resolution,
            dry_run=False,
        )
    mock_ahm.update_next_actions.assert_called_once_with(operation="update", action_id=7, status="done")


def test_resolve_guidance_cycle_integration_redispatch(tmp_path: Path) -> None:
    mod = _load_module()
    _configure_real_runtime(tmp_path, "phase-5-retention-export-and-audit-controls")
    json.loads(
        mcp_api.upsert_worktree_lane(
            lane_id="backend-domain",
            worktree_path=str(tmp_path / "backend-domain"),
            branch="codex/p5-backend-domain",
            status="active",
            objective="domain work",
        )
    )
    json.loads(
        mcp_api.record_lane_message(
            lane_id="backend-domain",
            session="lane-session",
            direction="orchestrator_to_worker",
            subject="old assignment",
            message="stale work",
            status="open",
        )
    )
    json.loads(
        mcp_api.record_lane_message(
            lane_id="backend-domain",
            session="lane-session",
            direction="worker_to_orchestrator",
            subject="backend-domain needs guidance",
            message="The remaining backend-domain implementation target is snapshot_generation_id stamping in cluster_repository.py.",
            status="open",
        )
    )
    json.loads(
        mcp_api.record_worker_report(
            lane_id="backend-domain",
            session="lane-session",
            summary="remaining backend-domain implementation target",
            status="blocked",
        )
    )

    results = mod._resolve_guidance_cycle(tmp_path, "phase-5-retention-export-and-audit-controls")

    assert [row.kind for row in results] == ["redispatch"]
    messages = json.loads(
        mcp_api.list_lane_messages(
            task_ref="phase-5-retention-export-and-audit-controls", lane_id="backend-domain", status="open"
        )
    )["messages"]
    assert len(messages) == 1
    assert messages[0]["direction"] == "orchestrator_to_worker"
    assert messages[0]["subject"] == "backend-domain snapshot provenance and disposal"


def test_resolve_guidance_cycle_integration_review_closes_dispatch(tmp_path: Path) -> None:
    mod = _load_module()
    _configure_real_runtime(tmp_path, "phase-5-retention-export-and-audit-controls")
    json.loads(
        mcp_api.upsert_worktree_lane(
            lane_id="backend-http",
            worktree_path=str(tmp_path / "backend-http"),
            branch="codex/p5-backend-http",
            status="active",
            objective="http work",
        )
    )
    json.loads(
        mcp_api.record_lane_message(
            lane_id="backend-http",
            session="lane-session",
            direction="orchestrator_to_worker",
            subject="old assignment",
            message="stale work",
            status="open",
        )
    )
    json.loads(
        mcp_api.record_lane_message(
            lane_id="backend-http",
            session="lane-session",
            direction="worker_to_orchestrator",
            subject="backend-http needs guidance",
            message="No code changes were warranted because the assigned retention wiring appears already resolved.",
            status="open",
        )
    )
    json.loads(
        mcp_api.record_worker_report(
            lane_id="backend-http",
            session="lane-session",
            summary="already resolved",
            status="blocked",
        )
    )
    results = mod._resolve_guidance_cycle(tmp_path, "phase-5-retention-export-and-audit-controls")

    assert [row.kind for row in results] == ["review"]
    messages = json.loads(
        mcp_api.list_lane_messages(
            task_ref="phase-5-retention-export-and-audit-controls", lane_id="backend-http", status="open"
        )
    )["messages"]
    assert messages == []
    lanes = json.loads(
        mcp_api.list_worktree_lanes(task_ref="phase-5-retention-export-and-audit-controls", status="all")
    )["lanes"]
    lane_row = next(row for row in lanes if row["lane_id"] == "backend-http")
    assert lane_row["status"] == "review"


def test_resolve_guidance_cycle_dedupes_duplicate_lane_messages(tmp_path: Path) -> None:
    mod = _load_module()
    _configure_real_runtime(tmp_path, "phase-5-retention-export-and-audit-controls")
    json.loads(
        mcp_api.upsert_worktree_lane(
            lane_id="backend-domain",
            worktree_path=str(tmp_path / "backend-domain"),
            branch="codex/p5-backend-domain",
            status="active",
            objective="domain work",
        )
    )
    json.loads(
        mcp_api.record_lane_message(
            lane_id="backend-domain",
            session="lane-session-old",
            direction="worker_to_orchestrator",
            subject="backend-domain needs guidance",
            message="Old duplicate guidance",
            status="open",
        )
    )
    json.loads(
        mcp_api.record_lane_message(
            lane_id="backend-domain",
            session="lane-session-new",
            direction="worker_to_orchestrator",
            subject="backend-domain needs guidance",
            message="The remaining backend-domain implementation target is snapshot_generation_id stamping in cluster_repository.py.",
            status="open",
        )
    )
    json.loads(
        mcp_api.record_worker_report(
            lane_id="backend-domain",
            session="lane-session-new",
            summary="remaining backend-domain implementation target",
            status="blocked",
        )
    )

    results = mod._resolve_guidance_cycle(tmp_path, "phase-5-retention-export-and-audit-controls")

    assert [row.kind for row in results] == ["redispatch"]
    messages = json.loads(
        mcp_api.list_lane_messages(
            task_ref="phase-5-retention-export-and-audit-controls",
            lane_id="backend-domain",
            status="open",
        )
    )["messages"]
    assert len(messages) == 2
    directions = sorted(row["direction"] for row in messages)
    assert directions == ["orchestrator_to_worker", "worker_to_orchestrator"]


def test_single_pass_guidance_review_closes_message(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / ".task-state").mkdir()
    mock_ahm = _make_mock_ahm()
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})
    mock_ahm.list_lane_messages.side_effect = [
        json.dumps(
            {
                "ok": True,
                "messages": [
                    {
                        "id": 10,
                        "lane_id": "backend-http",
                        "direction": "worker_to_orchestrator",
                        "session": "s",
                        "message": "No code changes were warranted because the assigned retention wiring appears already resolved.",
                    }
                ],
            }
        ),
        json.dumps(
            {
                "ok": True,
                "messages": [
                    {
                        "id": 30,
                        "lane_id": "backend-http",
                        "direction": "orchestrator_to_worker",
                    }
                ],
            }
        ),
    ]
    mock_ahm.list_worktree_lanes.return_value = json.dumps(
        {"ok": True, "lanes": [{"lane_id": "backend-http", "worktree_path": str(tmp_path / "wt"), "branch": "codex/x"}]}
    )
    mock_ahm.get_lane_activity.return_value = json.dumps({"ok": True, "lane": {"objective": "http"}, "actions": []})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = []
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout=json.dumps({"ok": True}), stderr="")
            result = mod.orchestrator_loop(
                orchestrator_root=tmp_path,
                task_ref="phase-5-retention-export-and-audit-controls",
                single_pass=True,
            )
    assert result == 0
    mock_ahm.update_lane_message.assert_any_call(10, "closed", task_ref="phase-5-retention-export-and-audit-controls")
    mock_ahm.upsert_worktree_lane.assert_called()


def test_single_pass_guidance_blocked_fallback_returns_error(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / ".task-state").mkdir()
    mock_ahm = _make_mock_ahm()
    mock_ahm.list_lane_messages.return_value = json.dumps(
        {
            "ok": True,
            "messages": [
                {
                    "id": 10,
                    "lane_id": "unknown-lane",
                    "direction": "worker_to_orchestrator",
                    "session": "s",
                    "message": "Need a decision.",
                }
            ],
        }
    )
    mock_ahm.list_worktree_lanes.return_value = json.dumps(
        {"ok": True, "lanes": [{"lane_id": "frontend", "worktree_path": str(tmp_path / "wt"), "branch": "codex/x"}]}
    )
    mock_ahm.get_lane_activity.return_value = json.dumps({"ok": True, "lane": {"objective": ""}, "actions": []})
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = []
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout=json.dumps({"ok": True}), stderr="")
            result = mod.orchestrator_loop(
                orchestrator_root=tmp_path,
                task_ref="phase-5-retention-export-and-audit-controls",
                single_pass=True,
            )
    assert result == 1


def test_long_running_guidance_stall_exits_after_threshold(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / ".task-state").mkdir()
    fatal = mod.GuidanceResolution(
        kind="fatal_error",
        lane_id="frontend",
        worker_message_id=10,
        error="cannot classify",
    )
    mock_ahm = _make_mock_ahm()
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = []
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod, "_run_handoff_dispatch", return_value={"ok": True}):
            with mock.patch.object(mod, "_resolve_guidance_cycle", side_effect=[[fatal], [fatal], [fatal]]):
                with mock.patch.object(mod, "_poll_merge_ready_lanes", return_value=[]):
                    with mock.patch.object(mod.time, "sleep", return_value=None):
                        result = mod.orchestrator_loop(
                            orchestrator_root=tmp_path,
                            task_ref="phase-5-retention-export-and-audit-controls",
                            single_pass=False,
                            poll_interval=0,
                        )
    assert result == 1


def test_long_running_runtime_failure_exits_after_threshold(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / ".task-state").mkdir()
    mock_ahm = _make_mock_ahm()
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = []
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod, "_run_handoff_dispatch", return_value={"ok": True}):
            with mock.patch.object(mod, "_resolve_guidance_cycle", side_effect=RuntimeError("transient MCP error")):
                with mock.patch.object(mod.time, "sleep", return_value=None):
                    result = mod.orchestrator_loop(
                        orchestrator_root=tmp_path,
                        task_ref="phase-5-retention-export-and-audit-controls",
                        single_pass=False,
                        poll_interval=0,
                    )
    assert result == 1


def test_single_pass_ready_to_close_exits_success(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / ".task-state").mkdir()
    mock_ahm = _make_mock_ahm(ready_to_close=True)
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = []
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod.subprocess, "run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout=json.dumps({"ok": True}), stderr="")
            result = mod.orchestrator_loop(
                orchestrator_root=tmp_path,
                task_ref="phase-5-retention-export-and-audit-controls",
                single_pass=True,
            )
    assert result == 0


def test_single_pass_ready_to_close_with_remaining_plan_work_returns_error(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / ".task-state").mkdir()
    mock_ahm = _make_mock_ahm(ready_to_close=True)
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = []
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(
            mod,
            "_remaining_plan_work",
            return_value=[{"plan_item_id": "p1", "cursor_state": "", "lane_id": "backend-domain"}],
        ):
            with mock.patch.object(mod.subprocess, "run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0, stdout=json.dumps({"ok": True}), stderr="")
                result = mod.orchestrator_loop(
                    orchestrator_root=tmp_path,
                    task_ref="phase-5-retention-export-and-audit-controls",
                    single_pass=True,
                )
    assert result == 1


def test_long_running_plan_stall_exits_after_threshold(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / ".task-state").mkdir()
    mock_ahm = _make_mock_ahm(ready_to_close=False)
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = []
    mock_manifest.downstream_lanes.return_value = []

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod, "_run_handoff_dispatch", return_value={"ok": True}):
            with mock.patch.object(mod, "_resolve_guidance_cycle", return_value=[]):
                with mock.patch.object(mod, "_dispatch_from_task_plan", return_value=None):
                    with mock.patch.object(mod, "_poll_merge_ready_lanes", return_value=[]):
                        with mock.patch.object(
                            mod,
                            "_remaining_plan_work",
                            return_value=[{"plan_item_id": "p1", "cursor_state": "", "lane_id": "backend-domain"}],
                        ):
                            with mock.patch.object(mod.time, "sleep", return_value=None):
                                result = mod.orchestrator_loop(
                                    orchestrator_root=tmp_path,
                                    task_ref="phase-5-retention-export-and-audit-controls",
                                    single_pass=False,
                                    poll_interval=0,
                                )
    assert result == 1


# ---------------------------------------------------------------------------
# lane_manifest.downstream_lanes accessor
# ---------------------------------------------------------------------------


def test_downstream_lanes_accessor() -> None:
    """Verify the downstream_lanes function reads from the manifest."""
    manifest_mod_path = ORCHESTRATION_DIR / "lane_manifest.py"
    spec = importlib.util.spec_from_file_location("lane_manifest", manifest_mod_path)
    assert spec is not None and spec.loader is not None
    manifest_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manifest_mod)

    task_ref = "phase-5-retention-export-and-audit-controls"
    deps = manifest_mod.downstream_lanes(task_ref, "backend-domain")
    assert deps == ["backend-http", "wp-proxy", "frontend"]


def test_downstream_lanes_empty() -> None:
    manifest_mod_path = ORCHESTRATION_DIR / "lane_manifest.py"
    spec = importlib.util.spec_from_file_location("lane_manifest", manifest_mod_path)
    assert spec is not None and spec.loader is not None
    manifest_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manifest_mod)

    task_ref = "phase-5-retention-export-and-audit-controls"
    deps = manifest_mod.downstream_lanes(task_ref, "frontend")
    assert deps == []


def test_downstream_lanes_unknown_lane() -> None:
    manifest_mod_path = ORCHESTRATION_DIR / "lane_manifest.py"
    spec = importlib.util.spec_from_file_location("lane_manifest", manifest_mod_path)
    assert spec is not None and spec.loader is not None
    manifest_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manifest_mod)

    task_ref = "phase-5-retention-export-and-audit-controls"
    deps = manifest_mod.downstream_lanes(task_ref, "nonexistent-lane")
    assert deps == []


# ---------------------------------------------------------------------------
# attention stall tracking
# ---------------------------------------------------------------------------


def test_lane_work_in_flight_excludes_stale_attention_lanes() -> None:
    """Stale attention_required lanes should not count as work in flight."""
    mod = _load_module()
    rows = [
        {"lane_id": "frontend", "action": "skip", "reason": "attention_required"},
        {"lane_id": "backend-domain", "action": "skip", "reason": "attention_required"},
    ]
    # Without stale set, attention_required counts as in-flight
    assert mod._lane_work_in_flight(rows) is True

    # With all lanes marked stale, nothing is in-flight
    assert mod._lane_work_in_flight(rows, stale_attention_lanes={"frontend", "backend-domain"}) is False

    # With only one stale, the other still counts
    assert mod._lane_work_in_flight(rows, stale_attention_lanes={"frontend"}) is True


def test_lane_work_in_flight_stale_does_not_affect_running() -> None:
    """Running workers are never suppressed by the stale set."""
    mod = _load_module()
    rows = [
        {"lane_id": "frontend", "action": "skip", "reason": "attention_required"},
        {"lane_id": "backend-domain", "running": True},
    ]
    assert mod._lane_work_in_flight(rows, stale_attention_lanes={"frontend"}) is True


def test_long_running_attention_stall_triggers_plan_stall(tmp_path: Path) -> None:
    """After ATTENTION_STALL_THRESHOLD cycles, stale attention lanes no longer
    suppress the plan stall detector, causing the loop to eventually exit."""
    mod = _load_module()
    (tmp_path / ".task-state").mkdir()
    mock_ahm = _make_mock_ahm(ready_to_close=False)
    mock_ahm.list_worker_reports.return_value = json.dumps({"ok": True, "reports": []})

    mock_manifest = mock.MagicMock()
    mock_manifest.merge_order.return_value = ["frontend"]
    mock_manifest.downstream_lanes.return_value = []

    attention_row = {
        "lane_id": "frontend",
        "action": "skip",
        "reason": "attention_required",
        "worker_state": "attention_required",
    }

    with mock.patch.dict(
        sys.modules,
        {
            "agent_handoff_mcp": mock_ahm,
            "agent_orchestrator_mcp.lanes": mock_ahm,
            "agent_orchestrator_mcp.api": mock_ahm,
            "lane_manifest": mock_manifest,
        },
    ):
        with mock.patch.object(mod, "_run_handoff_dispatch", return_value={"ok": True}):
            with mock.patch.object(mod, "_resolve_guidance_cycle", return_value=[]):
                with mock.patch.object(mod, "_ensure_lane_workers", return_value=[attention_row]):
                    with mock.patch.object(mod, "_poll_merge_ready_lanes", return_value=[]):
                        with mock.patch.object(
                            mod,
                            "_remaining_plan_work",
                            return_value=[{"plan_item_id": "p1", "cursor_state": "", "lane_id": "frontend"}],
                        ):
                            with mock.patch.object(mod, "_dispatch_from_task_plan", return_value=None):
                                with mock.patch.object(mod.time, "sleep", return_value=None):
                                    result = mod.orchestrator_loop(
                                        orchestrator_root=tmp_path,
                                        task_ref="phase-5-retention-export-and-audit-controls",
                                        single_pass=False,
                                        poll_interval=0,
                                    )
    # Should exit with error (plan stall after attention stall threshold exceeded)
    assert result == 1
