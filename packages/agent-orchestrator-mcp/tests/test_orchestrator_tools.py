from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from agent_orchestrator_mcp import api

REPO_ROOT = Path(__file__).resolve().parents[3]


def _parse(payload: str | dict) -> dict:
    """AHMCP-10 dict-return migration: handler returns are dicts now;
    only fall back to json.loads when something legitimately hands us a
    string (e.g. CLI stdout capture)."""
    if not isinstance(payload, dict):
        payload = json.loads(payload)
    if isinstance(payload, dict) and payload.get("schema_version") == 2:
        data = payload.get("data")
        scope = payload.get("scope")
        flat = dict(payload)
        if isinstance(data, dict):
            flat.update(data)
        if "task_ref" not in flat and isinstance(scope, dict) and scope.get("task_ref"):
            flat["task_ref"] = scope["task_ref"]
        return flat
    return payload


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
        mock.patch.object(
            api,
            "_orchestrator_paths",
            return_value={
                "workspace_root": REPO_ROOT,
                "state_dir": tmp_path / ".task-state",
                "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
                "pause_path": tmp_path / ".task-state" / "daemon-paused",
                "log_dir": tmp_path / "logs" / "daemon",
                "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
                "script_path": script_path,
            },
        ),
        mock.patch.object(api, "_import_orchestration_module") as mock_import_module,
        mock.patch.object(api.subprocess, "Popen", return_value=proc) as mock_popen,
    ):
        fake_registry = mock.Mock()
        fake_registry.validate_backend.return_value = "codex-subagent"
        mock_import_module.return_value = fake_registry
        payload = _parse(
            api.manage_orchestrator(
                operation="start",
                task_ref="daemon-8",
                backend="codex-subagent",
                poll_interval=15,
            )
        )

    assert payload["ok"] is True
    assert payload["pid"] == 43210
    assert payload["backend"] == "codex-subagent"
    assert payload["worker_start_mode"] == "mcp"
    assert payload["worker_reasoning_effort"] == "auto"
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
        json.dumps({"event": "daemon_start", "task_ref": "daemon-8"})
        + "\n"
        + json.dumps({"event": "cycle_end", "task_ref": "daemon-8"})
        + "\n"
    )

    fake_module = mock.Mock()
    fake_module.daemon_status.return_value = {
        "paused": False,
        "lock": {"held": True, "pid": 1234},
        "last_cycle": {"event": "cycle_end"},
        "last_verify": None,
    }

    with (
        mock.patch.object(api, "_import_orchestration_module", return_value=fake_module),
        mock.patch.object(
            api,
            "_orchestrator_paths",
            return_value={
                "workspace_root": tmp_path,
                "state_dir": tmp_path / ".task-state",
                "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
                "pause_path": tmp_path / ".task-state" / "daemon-paused",
                "log_dir": log_dir,
                "log_path": log_path,
                "script_path": REPO_ROOT / "scripts" / "mcp" / "orchestrator_daemon.py",
            },
        ),
        mock.patch.object(api, "_pid_is_running", return_value=True),
    ):
        payload = _parse(api.manage_orchestrator(operation="status"))

    assert payload["ok"] is True
    assert payload["running"] is True
    assert payload["pid"] == 1234
    assert payload["task_ref"] == "daemon-8"
    assert payload["cycle_count"] == 1


def test_worker_start_returns_pid_and_paths(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-subagent"
    fake_lane_manifest = mock.Mock()
    fake_lane_manifest.get_lane_config.return_value = {
        "worktree_path": str(tmp_path / "backend-domain"),
    }
    fake_ctl = mock.Mock()
    fake_ctl.daemon_start.return_value = {"ok": True, "pid": 6789, "lock_path": "/tmp/lock", "log_path": "/tmp/log"}
    (tmp_path / "backend-domain").mkdir()

    def _import(name: str):
        if name == "backend_registry":
            return fake_registry
        if name == "lane_manifest":
            return fake_lane_manifest
        if name == "worker_daemon_ctl":
            return fake_ctl
        raise AssertionError(name)

    with mock.patch.object(api, "_import_orchestration_module", side_effect=_import):
        payload = _parse(api.manage_worker(task_ref="daemon-10", lane_id="backend-domain", action="start"))

    assert payload["ok"] is True
    assert payload["pid"] == 6789
    kwargs = fake_ctl.daemon_start.call_args.kwargs
    assert kwargs["task_ref"] == "daemon-10"
    assert kwargs["lane_id"] == "backend-domain"
    assert kwargs["backend"] == "codex-subagent"
    assert kwargs["session_mode"] == "fresh_turn"
    assert kwargs["reasoning_effort"] == "inherit"


def test_worker_start_uses_runtime_state_dir(tmp_path: Path) -> None:
    custom_state_dir = tmp_path / "custom-state"
    api.configure_runtime(
        api.RuntimeConfig.for_workspace(
            tmp_path,
            state_dir=custom_state_dir,
            current_task_path=tmp_path / "CURRENT_TASK.md",
            exports_dir=custom_state_dir / "exports",
        )
    )
    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-subagent"
    fake_lane_manifest = mock.Mock()
    fake_lane_manifest.get_lane_config.return_value = {
        "worktree_path": str(tmp_path / "backend-domain"),
    }
    fake_ctl = mock.Mock()
    fake_ctl.daemon_start.return_value = {"ok": True, "pid": 6789}
    (tmp_path / "backend-domain").mkdir()

    def _import(name: str):
        if name == "backend_registry":
            return fake_registry
        if name == "lane_manifest":
            return fake_lane_manifest
        if name == "worker_daemon_ctl":
            return fake_ctl
        raise AssertionError(name)

    with mock.patch.object(api, "_import_orchestration_module", side_effect=_import):
        payload = _parse(api.manage_worker(task_ref="daemon-10", lane_id="backend-domain", action="start"))

    assert payload["ok"] is True
    assert fake_ctl.daemon_start.call_args.kwargs["state_dir"] == custom_state_dir


def test_worker_start_passes_shared_lane_session_mode(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-subagent"
    fake_lane_manifest = mock.Mock()
    fake_lane_manifest.get_lane_config.return_value = {
        "worktree_path": str(tmp_path / "frontend"),
    }
    fake_ctl = mock.Mock()
    fake_ctl.daemon_start.return_value = {"ok": True, "pid": 6789}
    (tmp_path / "frontend").mkdir()

    def _import(name: str):
        if name == "backend_registry":
            return fake_registry
        if name == "lane_manifest":
            return fake_lane_manifest
        if name == "worker_daemon_ctl":
            return fake_ctl
        raise AssertionError(name)

    with mock.patch.object(api, "_import_orchestration_module", side_effect=_import):
        payload = _parse(
            api.manage_worker(
                task_ref="daemon-10",
                lane_id="frontend",
                action="start",
                session_mode="shared_lane",
            )
        )

    assert payload["ok"] is True
    assert fake_ctl.daemon_start.call_args.kwargs["session_mode"] == "shared_lane"


def test_worker_start_passes_reasoning_effort(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-subagent"
    fake_lane_manifest = mock.Mock()
    fake_lane_manifest.get_lane_config.return_value = {
        "worktree_path": str(tmp_path / "frontend"),
    }
    fake_ctl = mock.Mock()
    fake_ctl.daemon_start.return_value = {"ok": True, "pid": 6789}
    (tmp_path / "frontend").mkdir()

    def _import(name: str):
        if name == "backend_registry":
            return fake_registry
        if name == "lane_manifest":
            return fake_lane_manifest
        if name == "worker_daemon_ctl":
            return fake_ctl
        raise AssertionError(name)

    with mock.patch.object(api, "_import_orchestration_module", side_effect=_import):
        payload = _parse(
            api.manage_worker(
                task_ref="daemon-10",
                lane_id="frontend",
                action="start",
                reasoning_effort="xhigh",
            )
        )

    assert payload["ok"] is True
    assert fake_ctl.daemon_start.call_args.kwargs["reasoning_effort"] == "xhigh"


def test_worker_status_delegates_to_control_module(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_ctl = mock.Mock()
    fake_ctl.daemon_status.return_value = {"lane_id": "frontend", "process": None}

    with mock.patch.object(api, "_import_orchestration_module", return_value=fake_ctl):
        payload = _parse(api.manage_worker(task_ref="daemon-10", lane_id="frontend", action="status"))

    assert payload["ok"] is True
    assert payload["running"] is False
    assert payload["lane_id"] == "frontend"
    fake_ctl.daemon_status.assert_called_once()


def test_worker_event_history_delegates_to_control_module(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_ctl = mock.Mock()
    fake_ctl.daemon_event_history.return_value = {
        "lane_id": "frontend",
        "process": None,
        "events": [{"event": "subagent_turn_observed"}],
        "returned": 1,
    }

    with mock.patch.object(api, "_import_orchestration_module", return_value=fake_ctl):
        payload = _parse(
            api.manage_worker(
                task_ref="daemon-10",
                lane_id="frontend",
                action="event_history",
                limit=10,
                event_name="subagent_turn_observed",
            )
        )

    assert payload["ok"] is True
    assert payload["returned"] == 1
    assert payload["events"][0]["event"] == "subagent_turn_observed"
    fake_ctl.daemon_event_history.assert_called_once()


def test_worker_stop_delegates_force_flag(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_ctl = mock.Mock()
    fake_ctl.daemon_stop.return_value = {"ok": True, "signaled": [1234]}

    with mock.patch.object(api, "_import_orchestration_module", return_value=fake_ctl):
        payload = _parse(api.manage_worker(task_ref="daemon-10", lane_id="frontend", action="stop", force=True))

    assert payload["ok"] is True
    assert payload["signaled"] == [1234]
    assert fake_ctl.daemon_stop.call_args.kwargs["force"] is True


def test_worker_start_all_aggregates_lane_results(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_manifest = mock.Mock()
    fake_manifest.merge_order.return_value = ["backend-domain", "frontend"]
    fake_manifest.list_lanes.return_value = ["backend-domain", "frontend"]
    fake_orchestrator_lanes = mock.Mock()
    fake_orchestrator_lanes._lane_has_capacity.return_value = True

    with (
        mock.patch.object(api, "_import_orchestration_module", side_effect=[fake_manifest, fake_orchestrator_lanes]),
        mock.patch.object(
            api,
            "worker_start",
            side_effect=[
                json.dumps({"ok": True, "lane_id": "backend-domain"}),
                json.dumps({"ok": True, "lane_id": "frontend"}),
            ],
        ),
    ):
        payload = _parse(api.manage_worker(task_ref="daemon-10", action="start_all"))

    assert payload["ok"] is True
    assert [item["lane_id"] for item in payload["results"]] == ["backend-domain", "frontend"]
    assert fake_orchestrator_lanes._lane_has_capacity.call_args_list[0].args == ("daemon-10", "backend-domain")


def test_worker_start_all_isolates_per_lane_exceptions(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_manifest = mock.Mock()
    fake_manifest.merge_order.return_value = ["backend-domain", "frontend"]
    fake_manifest.list_lanes.return_value = ["backend-domain", "frontend"]
    fake_orchestrator_lanes = mock.Mock()
    fake_orchestrator_lanes._lane_has_capacity.return_value = True

    with (
        mock.patch.object(api, "_import_orchestration_module", side_effect=[fake_manifest, fake_orchestrator_lanes]),
        mock.patch.object(
            api,
            "worker_start",
            side_effect=[
                json.dumps({"ok": True, "lane_id": "backend-domain"}),
                RuntimeError("boom"),
            ],
        ),
    ):
        payload = _parse(api.manage_worker(task_ref="daemon-10", action="start_all"))

    assert payload["ok"] is False
    assert payload["results"][0]["ok"] is True
    assert payload["results"][1]["ok"] is False
    assert payload["results"][1]["lane_id"] == "frontend"
    assert "boom" in payload["results"][1]["error"]


def test_worker_start_all_skips_lanes_with_unresolved_upstream_dependencies(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_manifest = mock.Mock()
    fake_manifest.merge_order.return_value = ["backend-domain", "frontend", "docs"]
    fake_manifest.list_lanes.return_value = ["backend-domain", "frontend", "docs"]
    fake_orchestrator_lanes = mock.Mock()
    fake_orchestrator_lanes._lane_has_capacity.side_effect = [False, False, True]

    with (
        mock.patch.object(api, "_import_orchestration_module", side_effect=[fake_manifest, fake_orchestrator_lanes]),
        mock.patch.object(
            api, "worker_start", return_value=json.dumps({"ok": True, "lane_id": "backend-domain"})
        ) as mock_worker_start,
    ):
        payload = _parse(api.manage_worker(task_ref="daemon-10", action="start_all", session_mode="shared_lane"))

    assert payload["ok"] is True
    assert payload["session_mode"] == "shared_lane"
    assert payload["results"][0] == {"ok": True, "lane_id": "backend-domain"}
    assert payload["results"][1]["skipped"] is True
    assert payload["results"][1]["reason"] == "unresolved_upstream_dependencies"
    assert payload["results"][1]["blocked_by"] == ["backend-domain"]
    assert payload["results"][2]["skipped"] is True
    assert payload["results"][2]["blocked_by"] == ["backend-domain"]
    mock_worker_start.assert_called_once_with(
        task_ref="daemon-10",
        lane_id="backend-domain",
        backend="codex-subagent",
        poll_interval=30,
        single_pass=False,
        session_mode="shared_lane",
        reasoning_effort="inherit",
        model=None,
    )


def test_worker_resume_delegates_to_control_module(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_ctl = mock.Mock()
    fake_ctl.daemon_resume.return_value = {"ok": True, "signaled": [2222]}

    with mock.patch.object(api, "_import_orchestration_module", return_value=fake_ctl):
        payload = _parse(api.manage_worker(task_ref="daemon-10", lane_id="frontend", action="resume"))

    assert payload["ok"] is True
    assert payload["signaled"] == [2222]
    fake_ctl.daemon_resume.assert_called_once()


def test_manage_worker_requires_lane_id_for_lane_actions(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)

    payload = _parse(api.manage_worker(task_ref="daemon-10", action="status"))

    assert payload["ok"] is False
    assert "requires lane_id" in payload["error"]


def test_manage_worker_rejects_unknown_action(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)

    payload = _parse(api.manage_worker(task_ref="daemon-10", lane_id="frontend", action="dance"))

    assert payload["ok"] is False
    assert "Valid values: start, stop, resume, status, event_history, start_all." in payload["error"]


def test_orchestrator_pause_and_resume_delegate_to_daemon_module(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_module = mock.Mock()

    with (
        mock.patch.object(api, "_import_orchestration_module", return_value=fake_module),
        mock.patch.object(
            api,
            "_orchestrator_paths",
            return_value={
                "workspace_root": tmp_path,
                "state_dir": tmp_path / ".task-state",
                "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
                "pause_path": tmp_path / ".task-state" / "daemon-paused",
                "log_dir": tmp_path / "logs" / "daemon",
                "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
                "script_path": REPO_ROOT / "scripts" / "mcp" / "orchestrator_daemon.py",
            },
        ),
    ):
        paused = _parse(api.manage_orchestrator(operation="pause"))
        resumed = _parse(api.manage_orchestrator(operation="resume"))

    assert paused["ok"] is True
    assert paused["paused"] is True
    assert resumed["ok"] is True
    assert resumed["paused"] is False
    fake_module.daemon_pause.assert_called_once()
    fake_module.daemon_resume.assert_called_once()


def test_orchestrator_stop_returns_not_running_when_no_pid(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)

    with (
        mock.patch.object(
            api,
            "_orchestrator_paths",
            return_value={
                "workspace_root": tmp_path,
                "state_dir": tmp_path / ".task-state",
                "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
                "pause_path": tmp_path / ".task-state" / "daemon-paused",
                "log_dir": tmp_path / "logs" / "daemon",
                "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
                "script_path": REPO_ROOT / "scripts" / "mcp" / "orchestrator_daemon.py",
            },
        ),
        mock.patch.object(api, "_read_lock_pid", return_value=None),
    ):
        payload = _parse(api.manage_orchestrator(operation="stop"))

    assert payload["ok"] is True
    assert payload["running"] is False
    assert payload["pid"] is None


def test_run_structured_turn_rejects_cli_backend(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-cli"
    fake_registry.get_backend_spec.return_value = mock.Mock(kind="cli")

    with mock.patch.object(api, "_import_orchestration_module", return_value=fake_registry):
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

    with (
        mock.patch.object(api, "_import_orchestration_module", return_value=fake_registry),
        mock.patch.object(api.subprocess, "Popen") as mock_popen,
    ):
        payload = _parse(api.manage_orchestrator(operation="start", task_ref="daemon-8", backend="bad"))

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

    with mock.patch.object(api, "_import_orchestration_module", return_value=fake_registry):
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

    with (
        mock.patch.object(api, "_import_orchestration_module", return_value=fake_registry),
        mock.patch.object(api.concurrent.futures, "ThreadPoolExecutor", return_value=FakeExecutor()),
    ):
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
        mock.patch.object(
            api,
            "_orchestrator_paths",
            return_value={
                "workspace_root": REPO_ROOT,
                "state_dir": tmp_path / ".task-state",
                "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
                "pause_path": tmp_path / ".task-state" / "daemon-paused",
                "log_dir": tmp_path / "logs" / "daemon",
                "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
                "script_path": script_path,
            },
        ),
        mock.patch.object(api, "_import_orchestration_module", return_value=fake_registry),
        mock.patch.object(api.subprocess, "run", return_value=completed) as mock_run,
    ):
        payload = _parse(
            api.manage_orchestrator(
                operation="single_cycle",
                task_ref="daemon-8",
                backend="codex-cli",
                dry_run=True,
            )
        )

    assert payload["ok"] is True
    assert payload["exit_code"] == 0
    assert payload["backend"] == "codex-cli"
    assert payload["dry_run"] is True
    assert payload["worker_start_mode"] == "mcp"
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
        mock.patch.object(
            api,
            "_orchestrator_paths",
            return_value={
                "workspace_root": REPO_ROOT,
                "state_dir": tmp_path / ".task-state",
                "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
                "pause_path": tmp_path / ".task-state" / "daemon-paused",
                "log_dir": tmp_path / "logs" / "daemon",
                "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
                "script_path": script_path,
            },
        ),
        mock.patch.object(api, "_import_orchestration_module", return_value=fake_registry),
        mock.patch.object(api.subprocess, "run", return_value=completed),
    ):
        payload = _parse(api.manage_orchestrator(operation="single_cycle", task_ref="daemon-8"))

    assert payload["ok"] is False
    assert payload["exit_code"] == 1
    assert "some error" in payload["stderr"]


def test_orchestrator_single_cycle_handles_timeout(tmp_path: Path) -> None:
    _configure_runtime(tmp_path)
    script_path = REPO_ROOT / "scripts" / "mcp" / "orchestrator_daemon.py"
    fake_registry = mock.Mock()
    fake_registry.validate_backend.return_value = "codex-cli"

    with (
        mock.patch.object(
            api,
            "_orchestrator_paths",
            return_value={
                "workspace_root": REPO_ROOT,
                "state_dir": tmp_path / ".task-state",
                "lock_path": tmp_path / ".task-state" / "orchestrator.lock",
                "pause_path": tmp_path / ".task-state" / "daemon-paused",
                "log_dir": tmp_path / "logs" / "daemon",
                "log_path": tmp_path / "logs" / "daemon" / "orchestrator.jsonl",
                "script_path": script_path,
            },
        ),
        mock.patch.object(api, "_import_orchestration_module", return_value=fake_registry),
        mock.patch.object(api.subprocess, "run", side_effect=api.subprocess.TimeoutExpired(cmd=[], timeout=1)),
    ):
        payload = _parse(
            api.manage_orchestrator(
                operation="single_cycle",
                task_ref="daemon-8",
                timeout_seconds=1.0,
            )
        )

    assert payload["ok"] is False
    assert "timed out" in payload["error"]


def test_runtime_pythonpath_only_requires_local_bridge_source() -> None:
    parts = api._runtime_pythonpath().split(":")
    expected_bridge = str(REPO_ROOT / "packages" / "codex-subagent-bridge" / "src")

    assert expected_bridge in parts
    assert Path(expected_bridge).exists()
    assert str(REPO_ROOT / "packages" / "agent-handoff-mcp" / "src") not in parts
    assert str(REPO_ROOT / "packages" / "agent-orchestrator-mcp" / "src") not in parts
    assert all("/packages/packages/" not in part for part in parts)


def test_daemon_runtime_env_does_not_inject_handoff_source_path(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/existing/pythonpath")
    env = api._daemon_runtime_env()

    assert str(REPO_ROOT / "packages" / "codex-subagent-bridge" / "src") in env["PYTHONPATH"]
    assert "/existing/pythonpath" in env["PYTHONPATH"]
    assert str(REPO_ROOT / "packages" / "agent-handoff-mcp" / "src") not in env["PYTHONPATH"]
    assert str(REPO_ROOT / "packages" / "agent-orchestrator-mcp" / "src") not in env["PYTHONPATH"]


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
        mock.patch.object(api, "_import_orchestration_module", side_effect=import_selector),
        mock.patch.object(api, "_pid_is_running", return_value=False),
        mock.patch.object(api.subprocess, "Popen", return_value=proc_mock),
    ):
        # Step 1: Start
        started = _parse(api.manage_orchestrator(operation="start", task_ref="e2e-test", backend="codex-cli"))
        assert started["ok"] is True
        assert started["pid"] == 99999

    # Step 2: Status (daemon now "running")
    with (
        mock.patch.object(api, "_orchestrator_paths", return_value=paths),
        mock.patch.object(api, "_import_orchestration_module", side_effect=import_selector),
        mock.patch.object(api, "_pid_is_running", return_value=True),
    ):
        status = _parse(api.manage_orchestrator(operation="status"))
        assert status["ok"] is True
        assert status["running"] is True

    # Step 3: Pause
    with (
        mock.patch.object(api, "_orchestrator_paths", return_value=paths),
        mock.patch.object(api, "_import_orchestration_module", side_effect=import_selector),
    ):
        paused = _parse(api.manage_orchestrator(operation="pause"))
        assert paused["ok"] is True
        assert paused["paused"] is True

    # Step 4: Resume
    with (
        mock.patch.object(api, "_orchestrator_paths", return_value=paths),
        mock.patch.object(api, "_import_orchestration_module", side_effect=import_selector),
    ):
        resumed = _parse(api.manage_orchestrator(operation="resume"))
        assert resumed["ok"] is True
        assert resumed["paused"] is False

    # Step 5: Single cycle
    completed = mock.Mock(returncode=0, stderr="")
    with (
        mock.patch.object(api, "_orchestrator_paths", return_value=paths),
        mock.patch.object(api, "_import_orchestration_module", side_effect=import_selector),
        mock.patch.object(api.subprocess, "run", return_value=completed),
    ):
        cycle = _parse(
            api.manage_orchestrator(
                operation="single_cycle",
                task_ref="e2e-test",
                backend="codex-cli",
                dry_run=True,
            )
        )
        assert cycle["ok"] is True
        assert cycle["exit_code"] == 0

    # Step 6: Stop
    with (
        mock.patch.object(api, "_orchestrator_paths", return_value=paths),
        mock.patch.object(api, "_read_lock_pid", return_value=99999),
        mock.patch.object(api, "_pid_is_running", side_effect=[True, False]),
        mock.patch("os.kill") as mock_kill,
    ):
        stopped = _parse(api.manage_orchestrator(operation="stop"))
        assert stopped["ok"] is True
        assert stopped["running"] is False
        mock_kill.assert_called_once()
