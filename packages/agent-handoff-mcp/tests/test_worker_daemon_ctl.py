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
    assert status["last_event"] is None


def test_daemon_status_reads_lock_and_last_event(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "worker-backend-domain.lock").write_text(json.dumps({"pid": 1234}))
    (tmp_path / "worker-backend-domain.jsonl").write_text(
        json.dumps({"event": "poll_sleep", "interval": 30}) + "\n"
    )
    with mock.patch.object(mod, "_ps_info", return_value={"pid": 1234, "stat": "S", "command": "python"}):
        status = mod.daemon_status(state_dir=tmp_path, log_dir=tmp_path, lane_id="backend-domain")
    assert status["lock"]["pid"] == 1234
    assert status["process"]["pid"] == 1234
    assert status["last_event"]["event"] == "poll_sleep"


def test_daemon_status_marks_stale_lock(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "worker-backend-domain.lock").write_text(json.dumps({"pid": 1234}))
    with mock.patch.object(mod, "_ps_info", return_value=None):
        status = mod.daemon_status(state_dir=tmp_path, log_dir=tmp_path, lane_id="backend-domain")
    assert status["stale_lock"] is True


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
