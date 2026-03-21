"""Tests for scripts/mcp/worker_daemon.py -- autonomous worker loop."""
from __future__ import annotations

import importlib.util
import json
import sys
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


def test_log_rotates_when_file_exceeds_limit(tmp_path: Path) -> None:
    mod = _load_module()
    log_file = tmp_path / "worker-test-lane.jsonl"
    log_file.write_text("x" * mod._MAX_LOG_BYTES)

    mod._log("test-lane", tmp_path, "INFO", "rotated")

    rotated = tmp_path / "worker-test-lane.jsonl.1"
    assert rotated.exists()
    assert rotated.read_text() == "x" * mod._MAX_LOG_BYTES
    entry = json.loads(log_file.read_text().strip())
    assert entry["event"] == "rotated"


def test_pythonpath_env_sets_lane_tempdir_and_backend_pyenv() -> None:
    mod = _load_module()
    env = mod.pythonpath_env(
        REPO_ROOT,
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="backend-domain",
    )
    assert env["PYENV_VERSION"] == "description-service"
    assert env["TMPDIR"].endswith("/.task-state/tmp/backend-domain")
    assert env["TMP"] == env["TMPDIR"]
    assert env["TEMP"] == env["TMPDIR"]


def test_resolve_reasoning_effort_auto_prefers_high_for_backend_lane() -> None:
    fake_lane_manifest = mock.Mock()
    fake_lane_manifest.get_lane_config.return_value = {
        "objective": "Implement schema and repository changes.",
        "owned_paths": ["apps/prototype-description-service/db/**"],
        "test_commands": ["PYENV_VERSION=description-service pytest recognition/tests/unit/"],
    }

    from scripts.mcp._env import resolve_auto_reasoning_effort

    with mock.patch.dict(sys.modules, {"lane_manifest": fake_lane_manifest}):
        effort, reasons = resolve_auto_reasoning_effort(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="backend-domain",
            requested="auto",
            cycle=0,
            prompt_override=None,
        )

    assert effort == "high"
    assert any("backend" in reason.lower() or "infra" in reason.lower() for reason in reasons)


def test_resolve_reasoning_effort_auto_prefers_low_for_docs_only_lane() -> None:
    fake_lane_manifest = mock.Mock()
    fake_lane_manifest.get_lane_config.return_value = {
        "objective": "Update task-plan docs.",
        "owned_paths": ["docs/tasks/**"],
        "test_commands": [],
    }

    from scripts.mcp._env import resolve_auto_reasoning_effort

    with mock.patch.dict(sys.modules, {"lane_manifest": fake_lane_manifest}):
        effort, reasons = resolve_auto_reasoning_effort(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="docs",
            requested="auto",
            cycle=0,
            prompt_override=None,
        )

    assert effort == "low"
    assert any("docs-only scope" in reason for reason in reasons)


def test_resolve_reasoning_effort_auto_prefers_medium_for_wp_proxy() -> None:
    fake_lane_manifest = mock.Mock()
    fake_lane_manifest.get_lane_config.return_value = {
        "objective": "WordPress proxy, sync-projection, and PHP unit-test slice.",
        "owned_paths": ["apps/prototype-wp-alt-context/src/**", "apps/prototype-wp-alt-context/tests/Unit/**"],
        "test_commands": ["cd apps/prototype-wp-alt-context && vendor/bin/phpunit"],
    }

    from scripts.mcp._env import resolve_auto_reasoning_effort

    with mock.patch.dict(sys.modules, {"lane_manifest": fake_lane_manifest}):
        effort, reasons = resolve_auto_reasoning_effort(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="wp-proxy",
            requested="auto",
            cycle=0,
            prompt_override=None,
        )

    assert effort == "medium"
    assert any("application-layer" in reason for reason in reasons)


def test_apply_backend_runtime_hints_sets_codex_model() -> None:
    from scripts.mcp._env import apply_backend_runtime_hints

    env: dict[str, str] = {}
    apply_backend_runtime_hints(env, model="gpt-5.4-mini", reasoning_effort="medium")
    assert env["CODEX_MODEL"] == "gpt-5.4-mini"
    assert env["CODEX_REASONING_EFFORT"] == "medium"


def test_apply_backend_runtime_hints_model_does_not_overwrite_existing() -> None:
    from scripts.mcp._env import apply_backend_runtime_hints

    env: dict[str, str] = {"CODEX_MODEL": "gpt-5.3-codex"}
    apply_backend_runtime_hints(env, model="gpt-5.4-mini")
    # setdefault should preserve the existing value
    assert env["CODEX_MODEL"] == "gpt-5.3-codex"


def test_subagent_adapter_injects_model_into_env() -> None:
    """CodexSubagentAdapter.execute() must inject CODEX_MODEL into env."""
    from scripts.mcp.adapters.codex_subagent import CodexSubagentAdapter

    captured_env: dict[str, str] = {}

    def fake_runner(prompt: str, schema: dict, cwd: str, env: dict | None = None, **kw: object) -> str:
        if env:
            captured_env.update(env)
        return '{"handoff_action": "merge_ready", "summary": "ok"}'

    adapter = CodexSubagentAdapter(runner=fake_runner, name="test")
    adapter.execute(
        prompt="hello",
        schema={},
        worktree_path=Path("/tmp/fake"),
        model="gpt-5.4-mini",
        env={"PYTHONPATH": "/foo"},
    )

    assert captured_env.get("CODEX_MODEL") == "gpt-5.4-mini"


def test_resolve_reasoning_effort_manifest_override() -> None:
    fake_lane_manifest = mock.Mock()
    fake_lane_manifest.get_lane_config.return_value = {
        "objective": "Backend schema changes.",
        "owned_paths": ["apps/prototype-description-service/db/**"],
        "test_commands": [],
        "preferred_reasoning_effort": "low",
    }

    from scripts.mcp._env import resolve_auto_reasoning_effort

    with mock.patch.dict(sys.modules, {"lane_manifest": fake_lane_manifest}):
        effort, reasons = resolve_auto_reasoning_effort(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="backend-domain",
            requested="auto",
            cycle=0,
            prompt_override=None,
        )

    assert effort == "low"
    assert any("manifest" in reason for reason in reasons)


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


def test_has_actionable_work_false_when_exit_4(tmp_path: Path) -> None:
    mod = _load_module()
    fake = mock.Mock()
    fake.returncode = 4

    with mock.patch("subprocess.run", return_value=fake):
        assert mod.has_actionable_work(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="lane",
            worktree_path=tmp_path,
        ) is False


def test_poll_lane_state_waiting_when_exit_4(tmp_path: Path) -> None:
    mod = _load_module()
    fake = mock.Mock()
    fake.returncode = 4

    with mock.patch("subprocess.run", return_value=fake):
        assert mod.poll_lane_state(
            orchestrator_root=REPO_ROOT,
            task_ref="task",
            lane_id="lane",
            worktree_path=tmp_path,
        ) == "waiting"


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


def test_read_worker_status_tolerates_invalid_bytes(tmp_path: Path) -> None:
    mod = _load_module()
    status_dir = tmp_path / ".task-state"
    status_dir.mkdir()
    status_path = status_dir / "worker-test-lane.status.json"
    status_path.write_bytes(b"{\xff}")

    assert mod._read_worker_status(status_dir, "test-lane") is None


def test_record_observability_persists_latest_and_history(tmp_path: Path) -> None:
    mod = _load_module()
    orchestrator_root = tmp_path
    (orchestrator_root / ".task-state").mkdir()
    (orchestrator_root / "logs" / "worker-daemon").mkdir(parents=True)

    first = mod._record_observability(
        orchestrator_root=orchestrator_root,
        task_ref="task",
        lane_id="test-lane",
        session="task-test-lane",
        cycle=0,
        phase="execution",
        backend="codex-subagent",
        requested_reasoning_effort="auto",
        effective_reasoning_effort="high",
        telemetry={
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "token_usage": {
                "last": {"cached_input_tokens": 1, "input_tokens": 2, "output_tokens": 3, "reasoning_output_tokens": 4, "total_tokens": 5},
                "total": {"cached_input_tokens": 10, "input_tokens": 20, "output_tokens": 30, "reasoning_output_tokens": 40, "total_tokens": 50},
                "model_context_window": 200000,
            },
        },
        state="executing",
        summary="Execution telemetry captured.",
    )
    second = mod._record_observability(
        orchestrator_root=orchestrator_root,
        task_ref="task",
        lane_id="test-lane",
        session="task-test-lane",
        cycle=0,
        phase="review",
        backend="codex-subagent",
        requested_reasoning_effort="auto",
        effective_reasoning_effort="high",
        telemetry={
            "thread_id": "thread-2",
            "turn_id": "turn-2",
            "token_usage": {
                "last": {"cached_input_tokens": 2, "input_tokens": 3, "output_tokens": 4, "reasoning_output_tokens": 5, "total_tokens": 6},
                "total": {"cached_input_tokens": 11, "input_tokens": 21, "output_tokens": 31, "reasoning_output_tokens": 41, "total_tokens": 51},
                "model_context_window": 200000,
            },
        },
        state="reviewing",
        summary="Review telemetry captured.",
    )

    assert first["token_usage_totals"]["total_tokens"] == 50
    assert second["token_usage_totals"]["reasoning_output_tokens"] == 41

    status = mod._read_worker_status(orchestrator_root / ".task-state", "test-lane")
    assert status is not None
    observability = status["observability"]
    assert observability["latest"]["phase"] == "review"
    assert observability["by_phase"]["execution"]["turn_id"] == "turn-1"
    assert observability["by_phase"]["review"]["turn_id"] == "turn-2"
    assert len(observability["history"]) == 2

    log_path = orchestrator_root / "logs" / "worker-daemon" / "worker-test-lane.jsonl"
    lines = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    observed = [line for line in lines if line.get("event") == "subagent_turn_observed"]
    assert len(observed) == 2
    assert observed[-1]["effective_reasoning_effort"] == "high"
    assert observed[-1]["token_usage"]["total"]["reasoning_output_tokens"] == 41
    assert observed[-1]["token_usage_totals"]["total_tokens"] == 51


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

    with mock.patch.object(mod, "poll_lane_state", return_value="idle"):
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


def test_worker_loop_logs_dormant_transition_once(tmp_path: Path) -> None:
    mod = _load_module()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    with (
        mock.patch.object(mod, "poll_lane_state", side_effect=["idle", "idle", KeyboardInterrupt()]),
        mock.patch.object(mod, "_log") as mock_log,
        mock.patch("time.sleep", return_value=None),
    ):
        with pytest.raises(KeyboardInterrupt):
            mod.worker_loop(
                orchestrator_root=REPO_ROOT,
                task_ref="task",
                lane_id="test-lane",
                session="task-test-lane",
                worktree_path=tmp_path,
                single_pass=False,
                dry_run=True,
            )

    dormant_calls = [call for call in mock_log.call_args_list if call.args[3] == "dormant_entered"]
    assert len(dormant_calls) == 1


def test_worker_loop_logs_wake_transition_before_work(tmp_path: Path) -> None:
    mod = _load_module()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps({
        "handoff_action": "needs_guidance",
        "summary": "Blocked on permissions.",
        "details": "Cannot access resource.",
        "tests_run": [],
        "blockers": ["No access."],
    }))

    with (
        mock.patch.object(mod, "poll_lane_state", side_effect=["waiting", "actionable", KeyboardInterrupt()]),
        mock.patch("lane_exec.run_lane_exec", return_value=result_file),
        mock.patch.object(mod, "_run_final_handoff", return_value=0),
        mock.patch.object(mod, "_log") as mock_log,
        mock.patch("time.sleep", return_value=None),
    ):
        with pytest.raises(KeyboardInterrupt):
            mod.worker_loop(
                orchestrator_root=REPO_ROOT,
                task_ref="task",
                lane_id="test-lane",
                session="task-test-lane",
                worktree_path=tmp_path,
                single_pass=False,
                dry_run=True,
            )

    events = [call.args[3] for call in mock_log.call_args_list]
    assert "dormant_entered" in events
    assert "dormant_exited" in events


# ---------------------------------------------------------------------------
# worker_loop -- single_pass poll error
# ---------------------------------------------------------------------------


def test_worker_loop_single_pass_poll_error(tmp_path: Path) -> None:
    mod = _load_module()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    with mock.patch.object(
        mod,
        "poll_lane_state",
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
        mock.patch.object(mod, "poll_lane_state", return_value="actionable"),
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
    assert not result_file.exists()


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
        mock.patch.object(mod, "poll_lane_state", return_value="actionable"),
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
    assert not result_file.exists()


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
        mock.patch.object(mod, "poll_lane_state", return_value="actionable"),
        mock.patch("lane_exec.run_lane_exec", side_effect=reset_result),
        mock.patch("lane_exec.build_fix_prompt", return_value="fix prompt"),
        mock.patch("review_runner.run_review", return_value=non_converged_review),
        mock.patch("review_runner.findings_converged", return_value=False),
        mock.patch.object(mod, "_run_final_handoff", return_value=0) as mock_handoff,
        mock.patch.object(mod, "_patch_result") as mock_patch_result,
        mock.patch.object(mod, "_cleanup_result_file") as mock_cleanup,
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

    assert rc == 0
    # Should have called handoff (blocked due to exhaustion)
    mock_handoff.assert_called_once()
    mock_patch_result.assert_called_once()
    patched_path, patched_overrides = mock_patch_result.call_args.args
    assert patched_path == result_file
    assert patched_overrides["handoff_action"] == "needs_guidance"
    assert any("converge" in b.lower() for b in patched_overrides.get("blockers", []))
    mock_cleanup.assert_called_once_with(result_file)


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
        mock.patch.object(mod, "poll_lane_state", return_value="actionable"),
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


def test_worker_loop_persists_handoff_failure_without_rerunning_assignment(tmp_path: Path) -> None:
    mod = _load_module()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    result_file = tmp_path / "result.json"
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
        mock.patch.object(mod, "poll_lane_state", return_value="actionable"),
        mock.patch("lane_exec.run_lane_exec", return_value=result_file) as mock_exec,
        mock.patch("review_runner.run_review", return_value=review_result),
        mock.patch("review_runner.findings_converged", return_value=True),
        mock.patch.object(mod, "_run_final_handoff", return_value=1),
        mock.patch("time.sleep", side_effect=[None, KeyboardInterrupt()]),
    ):
        with pytest.raises(KeyboardInterrupt):
            mod.worker_loop(
                orchestrator_root=tmp_path,
                task_ref="task",
                lane_id="test-lane",
                session="task-test-lane",
                worktree_path=tmp_path,
                single_pass=False,
                dry_run=True,
            )

    assert mock_exec.call_count == 1
    status_payload = json.loads((tmp_path / ".task-state" / "worker-test-lane.status.json").read_text())
    assert status_payload["state"] == "handoff_failed"
    assert status_payload["failure_stage"] == "final_handoff"
    assert status_payload["result_path"] == str(result_file)


def test_worker_loop_retries_persisted_handoff_failure_without_reexecuting(tmp_path: Path) -> None:
    mod = _load_module()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    status_dir = tmp_path / ".task-state"
    status_dir.mkdir(exist_ok=True)
    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps({
        "handoff_action": "merge_ready",
        "summary": "Feature implemented.",
    }))
    (status_dir / "worker-test-lane.status.json").write_text(
        json.dumps(
            {
                "lane_id": "test-lane",
                "task_ref": "task",
                "session": "task-test-lane",
                "state": "handoff_failed",
                "summary": "Retry me.",
                "result_path": str(result_file),
            }
        )
    )

    with (
        mock.patch("lane_exec.run_lane_exec") as mock_exec,
        mock.patch.object(mod, "_run_final_handoff", return_value=0) as mock_handoff,
    ):
        rc = mod.worker_loop(
            orchestrator_root=tmp_path,
            task_ref="task",
            lane_id="test-lane",
            session="task-test-lane",
            worktree_path=tmp_path,
            single_pass=True,
            dry_run=True,
        )

    assert rc == 0
    mock_exec.assert_not_called()
    mock_handoff.assert_called_once()
    assert not result_file.exists()
    status_payload = json.loads((status_dir / "worker-test-lane.status.json").read_text())
    assert status_payload["state"] == "waiting_for_orchestrator"
    assert "result_path" not in status_payload


def test_worker_loop_subagent_backend_skips_find_codex_and_threads_backend(tmp_path: Path) -> None:
    mod = _load_module()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    result_file = tmp_path / "result.json"
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
        mock.patch.object(mod, "poll_lane_state", return_value="actionable"),
        mock.patch("lane_exec.run_lane_exec", return_value=result_file) as mock_run_lane_exec,
        mock.patch("review_runner.run_review", return_value=review_result) as mock_run_review,
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
            backend="codex-subagent",
            dry_run=True,
        )

    assert rc == 0
    assert mock_run_lane_exec.call_args.kwargs["backend"] == "codex-subagent"
    assert mock_run_lane_exec.call_args.kwargs["reasoning_effort"] is None
    assert mock_run_review.call_args.kwargs["backend"] == "codex-subagent"
    assert mock_run_review.call_args.kwargs["reasoning_effort"] is None
    mock_handoff.assert_called_once()


# ---------------------------------------------------------------------------
# _pythonpath_env
# ---------------------------------------------------------------------------


def test_pythonpath_env() -> None:
    mod = _load_module()
    env = mod.pythonpath_env(REPO_ROOT)
    expected_mcp = str(REPO_ROOT / "packages" / "agent-handoff-mcp" / "src")
    expected_bridge = str(REPO_ROOT / "packages" / "codex-subagent-bridge" / "src")
    assert expected_mcp in env["PYTHONPATH"]
    assert expected_bridge in env["PYTHONPATH"]
