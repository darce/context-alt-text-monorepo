from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from agent_handoff_mcp import api


REPO_ROOT = Path(__file__).resolve().parents[3]


def _parse(payload: str) -> dict:
    return json.loads(payload)


def _configure_runtime(tmp_path: Path) -> None:
    api.configure_runtime(
        api.RuntimeConfig.for_workspace(
            tmp_path,
            state_dir=tmp_path / ".task-state",
            current_task_path=tmp_path / "CURRENT_TASK.md",
            exports_dir=tmp_path / ".task-state" / "exports",
        )
    )


def test_orchestrator_start_returns_pid_and_lock_path(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    proc = mock.Mock(pid=43210)
    script_path = REPO_ROOT / "scripts" / "mcp" / "orchestrator_daemon.py"

    with (
        mock.patch.object(api, "_pid_is_running", return_value=False),
        mock.patch.object(api, "_orchestrator_paths", return_value={
            "workspace_root": REPO_ROOT,
            "state_dir": tmp_path / ".task-state",
            "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
            "pause_path": tmp_path / ".task-state" / "daemon-paused",
            "log_dir": tmp_path / "logs" / "daemon",
            "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
            "script_path": script_path,
        }),
        mock.patch.object(api, "_import_scripts_mcp_module") as mock_import_module,
        mock.patch.object(api.subprocess, "Popen", return_value=proc) as mock_popen,
    ):
        fake_registry = mock.Mock()
        fake_registry.validate_backend.return_value = "codex-subagent"
        mock_import_module.return_value = fake_registry
        payload = _parse(api.orchestrator_start(task_ref="daemon-8", backend="codex-subagent", poll_interval=15))

    assert payload["ok"] is True
    assert payload["pid"] == 43210
    assert payload["backend"] == "codex-subagent"
    assert payload["lock_path"].endswith("/.task-state/orchestrator.lock")
    cmd = mock_popen.call_args.args[0]
    assert "--task-ref" in cmd
    assert "daemon-8" in cmd


def test_orchestrator_status_reports_running_state(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    log_dir = tmp_path / "logs" / "daemon"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "orchestrator.jsonl"
    log_path.write_text(
        json.dumps({"event": "daemon_start", "task_ref": "daemon-8"}) + "\n"
        + json.dumps({"event": "cycle_end", "task_ref": "daemon-8"}) + "\n"
    )

    fake_module = mock.Mock()
    fake_module.daemon_status.return_value = {
        "paused": False,
        "lock": {"held": True, "pid": 1234},
        "last_cycle": {"event": "cycle_end"},
        "last_verify": None,
    }

    with mock.patch.object(api, "_import_scripts_mcp_module", return_value=fake_module), \
         mock.patch.object(api, "_orchestrator_paths", return_value={
             "workspace_root": tmp_path,
             "state_dir": tmp_path / ".task-state",
             "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
             "pause_path": tmp_path / ".task-state" / "daemon-paused",
             "log_dir": log_dir,
             "log_path": log_path,
             "script_path": REPO_ROOT / "scripts" / "mcp" / "orchestrator_daemon.py",
         }), \
         mock.patch.object(api, "_pid_is_running", return_value=True):
        payload = _parse(api.orchestrator_status())

    assert payload["ok"] is True
    assert payload["running"] is True
    assert payload["pid"] == 1234
    assert payload["task_ref"] == "daemon-8"
    assert payload["cycle_count"] == 1


def test_orchestrator_pause_and_resume_delegate_to_daemon_module(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_module = mock.Mock()

    with mock.patch.object(api, "_import_scripts_mcp_module", return_value=fake_module), \
         mock.patch.object(api, "_orchestrator_paths", return_value={
             "workspace_root": tmp_path,
             "state_dir": tmp_path / ".task-state",
             "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
             "pause_path": tmp_path / ".task-state" / "daemon-paused",
             "log_dir": tmp_path / "logs" / "daemon",
             "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
             "script_path": REPO_ROOT / "scripts" / "mcp" / "orchestrator_daemon.py",
         }):
        paused = _parse(api.orchestrator_pause())
        resumed = _parse(api.orchestrator_resume())

    assert paused["ok"] is True
    assert paused["paused"] is True
    assert resumed["ok"] is True
    assert resumed["paused"] is False
    fake_module.daemon_pause.assert_called_once()
    fake_module.daemon_resume.assert_called_once()


def test_orchestrator_stop_returns_not_running_when_no_pid(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)

    with mock.patch.object(api, "_orchestrator_paths", return_value={
        "workspace_root": tmp_path,
        "state_dir": tmp_path / ".task-state",
        "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
        "pause_path": tmp_path / ".task-state" / "daemon-paused",
        "log_dir": tmp_path / "logs" / "daemon",
        "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
        "script_path": REPO_ROOT / "scripts" / "mcp" / "orchestrator_daemon.py",
    }), mock.patch.object(api, "_read_lock_pid", return_value=None):
        payload = _parse(api.orchestrator_stop())

    assert payload["ok"] is True
    assert payload["running"] is False
    assert payload["pid"] is None


def test_run_structured_turn_rejects_cli_backend(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-cli"
    fake_registry.get_backend_spec.return_value = mock.Mock(kind="cli")

    with mock.patch.object(api, "_import_scripts_mcp_module", return_value=fake_registry):
        payload = _parse(
            api.run_structured_turn(
                prompt="hello",
                schema={"type": "object"},
                cwd=str(REPO_ROOT),
                backend="codex-cli",
            )
        )

    assert payload["ok"] is False
    assert "CLI backends are not supported" in payload["error"]


def test_orchestrator_start_rejects_invalid_backend_before_spawn(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_registry = mock.Mock()
    fake_registry.validate_backend.side_effect = RuntimeError("Unsupported execution backend 'bad'")

    with mock.patch.object(api, "_import_scripts_mcp_module", return_value=fake_registry), \
         mock.patch.object(api.subprocess, "Popen") as mock_popen:
        payload = _parse(api.orchestrator_start(task_ref="daemon-8", backend="bad"))

    assert payload["ok"] is False
    assert "Unsupported execution backend 'bad'" in payload["error"]
    mock_popen.assert_not_called()


def test_run_structured_turn_returns_bridge_payload(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    runner = mock.Mock(return_value={"summary": "ok"})
    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-subagent"
    fake_registry.get_backend_spec.return_value = mock.Mock(kind="bridge")
    fake_registry.resolve_bridge.return_value = runner

    with mock.patch.object(api, "_import_scripts_mcp_module", return_value=fake_registry):
        payload = _parse(
            api.run_structured_turn(
                prompt="hello",
                schema={"type": "object"},
                cwd=str(REPO_ROOT),
                backend="codex-subagent",
                env={"TMPDIR": "/tmp/test"},
            )
        )

    assert payload["ok"] is True
    assert payload["backend"] == "codex-subagent"
    assert payload["result"] == {"summary": "ok"}
    assert runner.call_args.kwargs["env"] == {"TMPDIR": "/tmp/test"}


def test_run_structured_turn_times_out(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-subagent"
    fake_registry.get_backend_spec.return_value = mock.Mock(kind="bridge")
    fake_registry.resolve_bridge.return_value = lambda **_: {"summary": "slow"}

    class FakeFuture:
        def result(self, timeout: float) -> dict:
            raise api.concurrent.futures.TimeoutError()

    class FakeExecutor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn):
            return FakeFuture()

    with mock.patch.object(api, "_import_scripts_mcp_module", return_value=fake_registry), \
         mock.patch.object(api.concurrent.futures, "ThreadPoolExecutor", return_value=FakeExecutor()):
        payload = _parse(
            api.run_structured_turn(
                prompt="hello",
                schema={"type": "object"},
                cwd=str(REPO_ROOT),
                backend="codex-subagent",
                timeout_seconds=0.1,
            )
        )

    assert payload["ok"] is False
    assert "timed out" in payload["error"]


def test_orchestrator_single_cycle_returns_exit_code(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    script_path = REPO_ROOT / "scripts" / "mcp" / "orchestrator_daemon.py"
    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-cli"
    completed = mock.Mock(returncode=0, stderr="")

    with (
        mock.patch.object(api, "_orchestrator_paths", return_value={
            "workspace_root": REPO_ROOT,
            "state_dir": tmp_path / ".task-state",
            "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
            "pause_path": tmp_path / ".task-state" / "daemon-paused",
            "log_dir": tmp_path / "logs" / "daemon",
            "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
            "script_path": script_path,
        }),
        mock.patch.object(api, "_import_scripts_mcp_module", return_value=fake_registry),
        mock.patch.object(api.subprocess, "run", return_value=completed) as mock_run,
    ):
        payload = _parse(api.orchestrator_single_cycle(
            task_ref="daemon-8", backend="codex-cli", dry_run=True,
        ))

    assert payload["ok"] is True
    assert payload["exit_code"] == 0
    assert payload["backend"] == "codex-cli"
    assert payload["dry_run"] is True
    cmd = mock_run.call_args.args[0]
    assert "--single-pass" in cmd
    assert "--dry-run" in cmd
    assert "--backend" in cmd


def test_orchestrator_single_cycle_reports_failure(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    script_path = REPO_ROOT / "scripts" / "mcp" / "orchestrator_daemon.py"
    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-cli"
    completed = mock.Mock(returncode=1, stderr="some error")

    with (
        mock.patch.object(api, "_orchestrator_paths", return_value={
            "workspace_root": REPO_ROOT,
            "state_dir": tmp_path / ".task-state",
            "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
            "pause_path": tmp_path / ".task-state" / "daemon-paused",
            "log_dir": tmp_path / "logs" / "daemon",
            "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
            "script_path": script_path,
        }),
        mock.patch.object(api, "_import_scripts_mcp_module", return_value=fake_registry),
        mock.patch.object(api.subprocess, "run", return_value=completed),
    ):
        payload = _parse(api.orchestrator_single_cycle(task_ref="daemon-8"))

    assert payload["ok"] is False
    assert payload["exit_code"] == 1
    assert "some error" in payload["stderr"]


def test_orchestrator_single_cycle_handles_timeout(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    script_path = REPO_ROOT / "scripts" / "mcp" / "orchestrator_daemon.py"
    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-cli"

    with (
        mock.patch.object(api, "_orchestrator_paths", return_value={
            "workspace_root": REPO_ROOT,
            "state_dir": tmp_path / ".task-state",
            "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
            "pause_path": tmp_path / ".task-state" / "daemon-paused",
            "log_dir": tmp_path / "logs" / "daemon",
            "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
            "script_path": script_path,
        }),
        mock.patch.object(api, "_import_scripts_mcp_module", return_value=fake_registry),
        mock.patch.object(api.subprocess, "run", side_effect=api.subprocess.TimeoutExpired(cmd=[], timeout=1)),
    ):
        payload = _parse(api.orchestrator_single_cycle(
            task_ref="daemon-8", timeout_seconds=1.0,
        ))

    assert payload["ok"] is False
    assert "timed out" in payload["error"]


def test_handoff_pythonpath_points_to_real_repo_sources() -> None:
    parts = api._handoff_pythonpath().split(":")
    expected_mcp = str(REPO_ROOT / "packages" / "agent-handoff-mcp" / "src")
    expected_bridge = str(REPO_ROOT / "packages" / "codex-subagent-bridge" / "src")

    assert expected_mcp in parts
    assert expected_bridge in parts
    assert Path(expected_mcp).exists()
    assert Path(expected_bridge).exists()
    assert all("/packages/packages/" not in part for part in parts)


def _mock_orchestrator_paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "workspace_root": REPO_ROOT,
        "state_dir": tmp_path / ".task-state",
        "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
        "pause_path": tmp_path / ".task-state" / "daemon-paused",
        "log_dir": tmp_path / "logs" / "daemon",
        "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
        "script_path": REPO_ROOT / "scripts" / "mcp" / "orchestrator_daemon.py",
    }


def test_e2e_orchestrator_lifecycle_through_mcp_tools(tmp_path: Path) -> None:
    """Opus-style e2e: start -> status -> pause -> resume -> single-cycle -> stop."""
    _configure_runtime(tmp_path)
    paths = _mock_orchestrator_paths(tmp_path)

    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-cli"
    fake_registry.get_backend_spec.return_value = mock.Mock(kind="cli")

    fake_daemon = mock.Mock()
    fake_daemon.daemon_status.return_value = {
        "paused": False,
        "lock": {"held": True, "pid": 99999},
        "last_cycle": {"event": "cycle_end", "task_ref": "e2e-test"},
        "last_verify": None,
    }

    def import_selector(name: str):
        if name == "backend_registry":
            return fake_registry
        if name == "orchestrator_daemon":
            return fake_daemon
        raise ImportError(name)

    proc_mock = mock.Mock(pid=99999)

    with (
        mock.patch.object(api, "_orchestrator_paths", return_value=paths),
        mock.patch.object(api, "_import_scripts_mcp_module", side_effect=import_selector),
        mock.patch.object(api, "_pid_is_running", return_value=False),
        mock.patch.object(api.subprocess, "Popen", return_value=proc_mock),
    ):
        # Step 1: Start
        started = _parse(api.orchestrator_start(task_ref="e2e-test", backend="codex-cli"))
        assert started["ok"] is True
        assert started["pid"] == 99999

    # Step 2: Status (daemon now "running")
    with (
        mock.patch.object(api, "_orchestrator_paths", return_value=paths),
        mock.patch.object(api, "_import_scripts_mcp_module", side_effect=import_selector),
        mock.patch.object(api, "_pid_is_running", return_value=True),
    ):
        status = _parse(api.orchestrator_status())
        assert status["ok"] is True
        assert status["running"] is True

    # Step 3: Pause
    with (
        mock.patch.object(api, "_orchestrator_paths", return_value=paths),
        mock.patch.object(api, "_import_scripts_mcp_module", side_effect=import_selector),
    ):
        paused = _parse(api.orchestrator_pause())
        assert paused["ok"] is True
        assert paused["paused"] is True

    # Step 4: Resume
    with (
        mock.patch.object(api, "_orchestrator_paths", return_value=paths),
        mock.patch.object(api, "_import_scripts_mcp_module", side_effect=import_selector),
    ):
        resumed = _parse(api.orchestrator_resume())
        assert resumed["ok"] is True
        assert resumed["paused"] is False

    # Step 5: Single cycle
    completed = mock.Mock(returncode=0, stderr="")
    with (
        mock.patch.object(api, "_orchestrator_paths", return_value=paths),
        mock.patch.object(api, "_import_scripts_mcp_module", side_effect=import_selector),
        mock.patch.object(api.subprocess, "run", return_value=completed),
    ):
        cycle = _parse(api.orchestrator_single_cycle(
            task_ref="e2e-test", backend="codex-cli", dry_run=True,
        ))
        assert cycle["ok"] is True
        assert cycle["exit_code"] == 0

    # Step 6: Stop
    with (
        mock.patch.object(api, "_orchestrator_paths", return_value=paths),
        mock.patch.object(api, "_read_lock_pid", return_value=99999),
        mock.patch.object(api, "_pid_is_running", side_effect=[True, False]),
        mock.patch("os.kill") as mock_kill,
    ):
        stopped = _parse(api.orchestrator_stop())
        assert stopped["ok"] is True
        assert stopped["running"] is False
        mock_kill.assert_called_once()
