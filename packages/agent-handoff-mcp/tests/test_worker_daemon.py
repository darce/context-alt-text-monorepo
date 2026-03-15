"""Tests for scripts/mcp/worker_daemon.py -- autonomous worker loop."""
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

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "worker_daemon.py"
SCRIPT_DIR = REPO_ROOT / "scripts" / "mcp"


def _load_module():
    spec = importlib.util.spec_from_file_location("worker_daemon", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load worker_daemon module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# WorkerLock
# ---------------------------------------------------------------------------


def test_worker_lock_acquires(tmp_path: Path) -> None:
    mod = _load_module()
    lock = mod.WorkerLock("test-lane", tmp_path)
    assert lock.acquire() is True
    lock.release()


def test_worker_lock_second_instance_fails(tmp_path: Path) -> None:
    mod = _load_module()
    lock1 = mod.WorkerLock("test-lane", tmp_path)
    assert lock1.acquire() is True

    lock2 = mod.WorkerLock("test-lane", tmp_path)
    assert lock2.acquire() is False

    lock1.release()


def test_worker_lock_different_lanes_independent(tmp_path: Path) -> None:
    mod = _load_module()
    lock_a = mod.WorkerLock("lane-a", tmp_path)
    lock_b = mod.WorkerLock("lane-b", tmp_path)
    assert lock_a.acquire() is True
    assert lock_b.acquire() is True
    lock_a.release()
    lock_b.release()


def test_worker_lock_reacquirable_after_release(tmp_path: Path) -> None:
    mod = _load_module()
    lock = mod.WorkerLock("test-lane", tmp_path)
    assert lock.acquire() is True
    lock.release()
    lock2 = mod.WorkerLock("test-lane", tmp_path)
    assert lock2.acquire() is True
    lock2.release()


def test_worker_lock_release_before_acquire_is_safe(tmp_path: Path) -> None:
    mod = _load_module()
    lock = mod.WorkerLock("test-lane", tmp_path)
    lock.release()


# ---------------------------------------------------------------------------
# JSONL logger
# ---------------------------------------------------------------------------


def test_log_creates_jsonl_file(tmp_path: Path) -> None:
    mod = _load_module()
    mod._log("test-lane", tmp_path, "INFO", "test_event", extra_key="value")

    log_file = tmp_path / "worker-test-lane.jsonl"
    assert log_file.exists()
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["lane"] == "test-lane"
    assert entry["level"] == "INFO"
    assert entry["event"] == "test_event"
    assert entry["extra_key"] == "value"
    assert "ts" in entry


def test_log_appends_multiple_entries(tmp_path: Path) -> None:
    mod = _load_module()
    mod._log("test-lane", tmp_path, "INFO", "event1")
    mod._log("test-lane", tmp_path, "WARNING", "event2")

    log_file = tmp_path / "worker-test-lane.jsonl"
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# has_actionable_work
# ---------------------------------------------------------------------------


def test_has_actionable_work_true_when_exit_0(tmp_path: Path) -> None:
    mod = _load_module()
    fake = mock.Mock()
    fake.returncode = 0

    with mock.patch("subprocess.run", return_value=fake):
        assert mod.has_actionable_work(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="lane",
            worktree_path=tmp_path,
        ) is True


def test_has_actionable_work_false_when_exit_3(tmp_path: Path) -> None:
    mod = _load_module()
    fake = mock.Mock()
    fake.returncode = 3

    with mock.patch("subprocess.run", return_value=fake):
        assert mod.has_actionable_work(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="lane",
            worktree_path=tmp_path,
        ) is False


def test_has_actionable_work_raises_on_error(tmp_path: Path) -> None:
    mod = _load_module()
    fake = mock.Mock()
    fake.returncode = 1
    fake.stderr = "MCP connection refused"

    with mock.patch("subprocess.run", return_value=fake):
        with pytest.raises(RuntimeError, match="lane_prompt.py --check failed"):
            mod.has_actionable_work(
                orchestrator_root=REPO_ROOT,
                task_ref="task",
                lane_id="lane",
                worktree_path=tmp_path,
            )


# ---------------------------------------------------------------------------
# _run_lane_check
# ---------------------------------------------------------------------------


def test_run_lane_check_returns_true_on_success(tmp_path: Path) -> None:
    mod = _load_module()
    fake = mock.Mock()
    fake.returncode = 0

    with mock.patch("subprocess.run", return_value=fake):
        assert mod._run_lane_check(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="lane",
            worktree_path=tmp_path,
        ) is True


def test_run_lane_check_returns_false_on_failure(tmp_path: Path) -> None:
    mod = _load_module()
    fake = mock.Mock()
    fake.returncode = 1

    with mock.patch("subprocess.run", return_value=fake):
        assert mod._run_lane_check(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="lane",
            worktree_path=tmp_path,
        ) is False


# ---------------------------------------------------------------------------
# _load_result / _patch_result
# ---------------------------------------------------------------------------


def test_load_result(tmp_path: Path) -> None:
    mod = _load_module()
    f = tmp_path / "result.json"
    f.write_text(json.dumps({"handoff_action": "merge_ready", "summary": "done"}))
    data = mod._load_result(f)
    assert data["handoff_action"] == "merge_ready"


def test_patch_result(tmp_path: Path) -> None:
    mod = _load_module()
    f = tmp_path / "result.json"
    f.write_text(json.dumps({"handoff_action": "merge_ready", "summary": "done"}))
    mod._patch_result(f, {"handoff_action": "needs_guidance", "blockers": ["failed"]})
    data = json.loads(f.read_text())
    assert data["handoff_action"] == "needs_guidance"
    assert data["blockers"] == ["failed"]
    assert data["summary"] == "done"  # preserved


# ---------------------------------------------------------------------------
# _run_final_handoff subprocess call shape
# ---------------------------------------------------------------------------


def test_run_final_handoff_invokes_lane_result(tmp_path: Path) -> None:
    mod = _load_module()
    result_file = tmp_path / "result.json"
    result_file.write_text("{}")

    fake = mock.Mock()
    fake.returncode = 0

    with mock.patch("subprocess.run", return_value=fake) as mock_run:
        rc = mod._run_final_handoff(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="lane",
            session="task-lane",
            worktree_path=tmp_path,
            result_path=result_file,
        )

    assert rc == 0
    cmd = mock_run.call_args[0][0]
    assert "lane_result.py" in cmd[1]
    assert "handoff" in cmd


# ---------------------------------------------------------------------------
# worker_loop -- single_pass with no work
# ---------------------------------------------------------------------------


def test_worker_loop_single_pass_no_work(tmp_path: Path) -> None:
    mod = _load_module()
    # Ensure SCRIPT_DIR is importable
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    with mock.patch.object(mod, "has_actionable_work", return_value=False):
        rc = mod.worker_loop(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="test-lane",
            session="task-test-lane",
            worktree_path=tmp_path,
            single_pass=True,
            dry_run=True,
        )

    assert rc == 0


# ---------------------------------------------------------------------------
# worker_loop -- single_pass poll error
# ---------------------------------------------------------------------------


def test_worker_loop_single_pass_poll_error(tmp_path: Path) -> None:
    mod = _load_module()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    with mock.patch.object(
        mod,
        "has_actionable_work",
        side_effect=RuntimeError("poll failure"),
    ):
        rc = mod.worker_loop(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="test-lane",
            session="task-test-lane",
            worktree_path=tmp_path,
            single_pass=True,
            dry_run=True,
        )

    assert rc == 1


# ---------------------------------------------------------------------------
# worker_loop -- single_pass needs_guidance
# ---------------------------------------------------------------------------


def test_worker_loop_single_pass_needs_guidance(tmp_path: Path) -> None:
    mod = _load_module()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    result_dir = tmp_path / "results"
    result_dir.mkdir()
    result_file = result_dir / "result.json"
    result_file.write_text(json.dumps({
        "handoff_action": "needs_guidance",
        "summary": "Blocked on permissions.",
        "details": "Cannot access resource.",
        "tests_run": [],
        "blockers": ["No access."],
    }))

    with (
        mock.patch.object(mod, "has_actionable_work", return_value=True),
        mock.patch("lane_exec.find_codex", return_value="/usr/bin/codex"),
        mock.patch("lane_exec.run_lane_exec", return_value=result_file),
        mock.patch.object(mod, "_run_final_handoff", return_value=0) as mock_handoff,
    ):
        rc = mod.worker_loop(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="test-lane",
            session="task-test-lane",
            worktree_path=tmp_path,
            single_pass=True,
            dry_run=True,
        )

    assert rc == 0
    mock_handoff.assert_called_once()


# ---------------------------------------------------------------------------
# worker_loop -- single_pass converged review
# ---------------------------------------------------------------------------


def test_worker_loop_single_pass_converged(tmp_path: Path) -> None:
    mod = _load_module()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    result_dir = tmp_path / "results"
    result_dir.mkdir()
    result_file = result_dir / "result.json"
    result_file.write_text(json.dumps({
        "handoff_action": "merge_ready",
        "summary": "Feature implemented.",
        "details": "Implemented the router.",
        "tests_run": ["make test"],
        "blockers": [],
    }))

    review_result: dict[str, Any] = {
        "findings": [],
        "summary": "No serious issues.",
        "converged": True,
        "changed_files": ["src/foo.py"],
        "stack_guides": [],
    }

    with (
        mock.patch.object(mod, "has_actionable_work", return_value=True),
        mock.patch("lane_exec.find_codex", return_value="/usr/bin/codex"),
        mock.patch("lane_exec.run_lane_exec", return_value=result_file),
        mock.patch("review_runner.run_review", return_value=review_result),
        mock.patch("review_runner.findings_converged", return_value=True),
        mock.patch.object(mod, "_run_final_handoff", return_value=0) as mock_handoff,
    ):
        rc = mod.worker_loop(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="test-lane",
            session="task-test-lane",
            worktree_path=tmp_path,
            single_pass=True,
            dry_run=True,
        )

    assert rc == 0
    mock_handoff.assert_called_once()


# ---------------------------------------------------------------------------
# worker_loop -- review exhausted
# ---------------------------------------------------------------------------


def test_worker_loop_review_exhausted(tmp_path: Path) -> None:
    mod = _load_module()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    result_dir = tmp_path / "results"
    result_dir.mkdir()
    result_file = result_dir / "result.json"

    def reset_result(*args: Any, **kwargs: Any) -> Path:
        """Reset the result file for each call."""
        result_file.write_text(json.dumps({
            "handoff_action": "merge_ready",
            "summary": "Attempt.",
            "details": "Still has issues.",
            "tests_run": [],
            "blockers": [],
        }))
        return result_file

    non_converged_review: dict[str, Any] = {
        "findings": [
            {"severity": "high", "category": "GAP", "file_path": "x.py", "description": "Missing."}
        ],
        "summary": "Issues remain.",
        "converged": False,
        "changed_files": ["x.py"],
        "stack_guides": [],
    }

    with (
        mock.patch.object(mod, "has_actionable_work", return_value=True),
        mock.patch("lane_exec.find_codex", return_value="/usr/bin/codex"),
        mock.patch("lane_exec.run_lane_exec", side_effect=reset_result),
        mock.patch("lane_exec.build_fix_prompt", return_value="fix prompt"),
        mock.patch("review_runner.run_review", return_value=non_converged_review),
        mock.patch("review_runner.findings_converged", return_value=False),
        mock.patch.object(mod, "_run_final_handoff", return_value=0) as mock_handoff,
        mock.patch("subprocess.run") as mock_subprocess,
    ):
        # Mock subprocess for the base prompt re-render in fix cycles
        mock_subprocess.return_value = mock.Mock(returncode=0, stdout="base prompt")

        rc = mod.worker_loop(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="test-lane",
            session="task-test-lane",
            worktree_path=tmp_path,
            max_review_cycles=2,
            single_pass=True,
            dry_run=True,
        )

    # Should have called handoff (blocked due to exhaustion)
    mock_handoff.assert_called_once()
    # The result should be patched to needs_guidance
    data = json.loads(result_file.read_text())
    assert data["handoff_action"] == "needs_guidance"
    assert any("converge" in b.lower() for b in data.get("blockers", []))


def test_worker_loop_logs_fix_prompt_failure(tmp_path: Path) -> None:
    mod = _load_module()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    result_file = tmp_path / "result.json"

    def reset_result(*args: Any, **kwargs: Any) -> Path:
        result_file.write_text(json.dumps({
            "handoff_action": "merge_ready",
            "summary": "Attempt.",
            "details": "Still has issues.",
            "tests_run": [],
            "blockers": [],
        }))
        return result_file

    non_converged_review: dict[str, Any] = {
        "findings": [
            {"severity": "high", "category": "GAP", "file_path": "x.py", "description": "Missing."}
        ],
        "summary": "Issues remain.",
        "converged": False,
        "changed_files": ["x.py"],
        "stack_guides": [],
    }

    with (
        mock.patch.object(mod, "has_actionable_work", return_value=True),
        mock.patch("lane_exec.find_codex", return_value="/usr/bin/codex"),
        mock.patch("lane_exec.run_lane_exec", side_effect=reset_result),
        mock.patch("review_runner.run_review", return_value=non_converged_review),
        mock.patch("review_runner.findings_converged", return_value=False),
        mock.patch.object(mod, "_run_final_handoff", return_value=0),
        mock.patch.object(mod, "_log") as mock_log,
        mock.patch("subprocess.run", return_value=mock.Mock(returncode=1, stderr="prompt render failed")),
    ):
        mod.worker_loop(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="test-lane",
            session="task-test-lane",
            worktree_path=tmp_path,
            max_review_cycles=2,
            single_pass=True,
            dry_run=True,
        )

    assert any(call.args[3] == "fix_prompt_failed" for call in mock_log.call_args_list)


# ---------------------------------------------------------------------------
# _pythonpath_env
# ---------------------------------------------------------------------------


def test_pythonpath_env() -> None:
    mod = _load_module()
    env = mod.pythonpath_env(REPO_ROOT)
    expected = str(REPO_ROOT / "packages" / "agent-handoff-mcp" / "src")
    assert expected in env["PYTHONPATH"]
