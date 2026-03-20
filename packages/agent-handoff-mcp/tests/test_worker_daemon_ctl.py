from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "worker_daemon_ctl.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("worker_daemon_ctl", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load worker_daemon_ctl module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_daemon_status_empty(tmp_path: Path) -> None:
    mod = _load_module()
    status = mod.daemon_status(state_dir=tmp_path, log_dir=tmp_path, lane_id="definitely-no-such-lane")
    assert status["lane_id"] == "definitely-no-such-lane"
    assert status["lock"]["held"] is False
    assert status["process"] is None
    assert status["worker_state"] == "stopped"
    assert status["last_event"] is None


def test_daemon_start_spawns_worker_when_not_running(tmp_path: Path) -> None:
    mod = _load_module()
    orchestrator_root = tmp_path / "repo"
    orchestrator_root.mkdir()
    proc = mock.Mock(pid=4567)
    with (
        mock.patch.object(mod, "daemon_status", return_value={"process": None}),
        mock.patch.object(mod.subprocess, "Popen", return_value=proc) as mock_popen,
    ):
        result = mod.daemon_start(
            orchestrator_root=orchestrator_root,
            state_dir=tmp_path,
            log_dir=tmp_path,
            task_ref="phase-5",
            lane_id="backend-domain",
            worktree_path=tmp_path / "lane",
            session="phase-5-backend-domain",
            python_executable="/usr/bin/python3",
            pythonpath="/tmp/pythonpath",
            backend="codex-subagent",
            poll_interval=15,
            single_pass=True,
        )
    assert result["ok"] is True
    assert result["pid"] == 4567
    cmd = mock_popen.call_args.args[0]
    assert "--task-ref" in cmd
    assert "phase-5" in cmd
    assert "--single-pass" in cmd
    assert mock_popen.call_args.kwargs["env"]["PYTHONPATH"] == "/tmp/pythonpath"


def test_daemon_start_refuses_second_running_worker(tmp_path: Path) -> None:
    mod = _load_module()
    with mock.patch.object(mod, "daemon_status", return_value={"process": {"pid": 9876}}):
        result = mod.daemon_start(
            orchestrator_root=tmp_path,
            state_dir=tmp_path,
            log_dir=tmp_path,
            task_ref="phase-5",
            lane_id="backend-domain",
            worktree_path=tmp_path / "lane",
            session="phase-5-backend-domain",
            python_executable="/usr/bin/python3",
        )
    assert result["ok"] is False
    assert result["pid"] == 9876


def test_daemon_status_reads_lock_and_last_event(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "worker-backend-domain.lock").write_text(json.dumps({"pid": 1234}))
    (tmp_path / "worker-backend-domain.status.json").write_text(
        json.dumps(
            {
                "state": "idle",
                "summary": "No work.",
                "observability": {"latest": {"phase": "execution", "turn_id": "turn-1"}},
            }
        )
    )
    (tmp_path / "worker-backend-domain.jsonl").write_text(
        json.dumps({"event": "poll_sleep", "interval": 30}) + "\n"
    )
    with mock.patch.object(mod, "_ps_info", return_value={"pid": 1234, "stat": "S", "command": "python"}):
        status = mod.daemon_status(state_dir=tmp_path, log_dir=tmp_path, lane_id="backend-domain")
    assert status["lock"]["pid"] == 1234
    assert status["process"]["pid"] == 1234
    assert status["worker_state"] == "idle"
    assert status["observability"]["latest"]["turn_id"] == "turn-1"
    assert status["last_event"]["event"] == "poll_sleep"


def test_daemon_status_marks_stale_lock(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "worker-backend-domain.lock").write_text(json.dumps({"pid": 1234}))
    with mock.patch.object(mod, "_ps_info", return_value=None):
        status = mod.daemon_status(state_dir=tmp_path, log_dir=tmp_path, lane_id="backend-domain")
    assert status["stale_lock"] is True
    assert status["attention_required"] is True


def test_daemon_status_falls_back_to_process_scan(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "worker-backend-domain.lock").write_text("")
    with (
        mock.patch.object(mod, "_ps_info", return_value=None),
        mock.patch.object(mod, "_find_worker_process", return_value={"pid": 2222, "pid_source": "process_scan"}),
    ):
        status = mod.daemon_status(
            state_dir=tmp_path,
            log_dir=tmp_path,
            lane_id="backend-domain",
            task_ref="phase-5",
        )
    assert status["process"]["pid"] == 2222
    assert status["process"]["pid_source"] == "process_scan"


def test_daemon_status_reports_handoff_failed_from_status_file(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "worker-backend-domain.status.json").write_text(
        json.dumps(
            {
                "state": "handoff_failed",
                "summary": "Final handoff failed.",
                "result_path": "/tmp/result.json",
            }
        )
    )
    status = mod.daemon_status(state_dir=tmp_path, log_dir=tmp_path, lane_id="backend-domain")
    assert status["worker_state"] == "handoff_failed"
    assert status["attention_required"] is True
    assert status["state_summary"] == "Final handoff failed."


def test_daemon_status_reports_paused_when_process_is_stopped(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "worker-backend-domain.lock").write_text(json.dumps({"pid": 1234}))
    with mock.patch.object(mod, "_ps_info", return_value={"pid": 1234, "stat": "T", "command": "python", "stopped": True}):
        status = mod.daemon_status(state_dir=tmp_path, log_dir=tmp_path, lane_id="backend-domain")
    assert status["worker_state"] == "paused"
    assert status["attention_required"] is False


def test_daemon_stop_signals_tree(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "worker-backend-domain.lock").write_text(json.dumps({"pid": 1234}))
    with (
        mock.patch.object(mod, "_ps_info", return_value={"pid": 1234, "stat": "S"}),
        mock.patch.object(mod, "_signal_tree", return_value=[2001, 1234]) as mock_signal,
    ):
        result = mod.daemon_stop(state_dir=tmp_path, log_dir=tmp_path, lane_id="backend-domain")
    assert result["ok"] is True
    mock_signal.assert_called_once()
    status_payload = json.loads((tmp_path / "worker-backend-domain.status.json").read_text())
    assert status_payload["state"] == "stopped"


def test_daemon_resume_signals_tree(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "worker-backend-domain.lock").write_text(json.dumps({"pid": 1234}))
    with (
        mock.patch.object(mod, "_ps_info", return_value={"pid": 1234, "stat": "T"}),
        mock.patch.object(mod, "_signal_tree", return_value=[2001, 1234]) as mock_signal,
    ):
        result = mod.daemon_resume(state_dir=tmp_path, log_dir=tmp_path, lane_id="backend-domain")
    assert result["ok"] is True
    mock_signal.assert_called_once()


def test_find_worker_process_prefers_python_over_shell() -> None:
    mod = _load_module()
    output = "\n".join([
        "111 /bin/sh -c python3 worker_daemon.py --task-ref phase-5 --lane-id backend-domain",
        "222 /Users/me/.pyenv/bin/python3 worker_daemon.py --task-ref phase-5 --lane-id backend-domain",
    ])
    with (
        mock.patch.object(mod.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=output)),
        mock.patch.object(mod, "_ps_info", return_value={"pid": 222, "stat": "S"}),
    ):
        result = mod._find_worker_process(task_ref="phase-5", lane_id="backend-domain")
    assert result is not None
    assert result["pid"] == 222


def test_daemon_event_history_reads_recent_filtered_events(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "worker-backend-domain.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "exec_start", "cycle": 0}),
                json.dumps(
                    {
                        "event": "subagent_turn_observed",
                        "cycle": 0,
                        "phase": "execution",
                        "requested_reasoning_effort": "auto",
                        "effective_reasoning_effort": "high",
                        "token_usage_totals": {"total_tokens": 50, "reasoning_output_tokens": 40},
                    }
                ),
                json.dumps(
                    {
                        "event": "subagent_turn_observed",
                        "cycle": 0,
                        "phase": "review",
                        "requested_reasoning_effort": "auto",
                        "effective_reasoning_effort": "medium",
                        "token_usage": {
                            "last": {
                                "cached_input_tokens": 1,
                                "input_tokens": 2,
                                "output_tokens": 3,
                                "reasoning_output_tokens": 4,
                                "total_tokens": 5,
                            },
                            "total": {
                                "cached_input_tokens": 10,
                                "input_tokens": 20,
                                "output_tokens": 30,
                                "reasoning_output_tokens": 41,
                                "total_tokens": 51,
                            },
                        },
                    }
                ),
            ]
        )
        + "\n"
    )

    history = mod.daemon_event_history(
        state_dir=tmp_path,
        log_dir=tmp_path,
        lane_id="backend-domain",
        task_ref="phase-5",
        limit=2,
        event_name="subagent_turn_observed",
    )

    assert history["returned"] == 2
    assert [item["phase"] for item in history["events"]] == ["review", "execution"]
    assert history["events"][0]["effective_reasoning_effort"] == "medium"
    assert history["events"][0]["token_usage"]["total"]["reasoning_output_tokens"] == 41
    assert history["events"][1]["token_usage_totals"]["total_tokens"] == 50
