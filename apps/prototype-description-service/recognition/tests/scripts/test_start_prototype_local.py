"""Regression tests for scripts/start_prototype_local.sh stop behavior."""

from __future__ import annotations

import os
import pathlib
import shlex
import subprocess
import textwrap

APP_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT_PATH = APP_ROOT / "scripts" / "start_prototype_local.sh"


def _run_bash_harness(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ},
        check=False,
    )


def test_stop_service_cleans_only_project_local_uvicorn_processes(tmp_path: pathlib.Path) -> None:
    kill_log = tmp_path / "kill.log"
    worker_log = tmp_path / "logs" / "scan_worker.log"
    script = textwrap.dedent(
        f"""
        set -euo pipefail
        source {shlex.quote(str(SCRIPT_PATH))}
        load_env() {{ :; }}
        sleep() {{ :; }}
        send_signal() {{
          printf '%s %s\\n' "$1" "$2" >> {shlex.quote(str(kill_log))}
          return 0
        }}
        lsof() {{ return 0; }}
        ps() {{
          printf '%s\n' \
            '9000 /opt/python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir {APP_ROOT}' \
            '9001 /opt/python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /tmp/other-worktree/apps/prototype-description-service'
        }}
        SCAN_WORKER_LOG={shlex.quote(str(worker_log))}
        stop_service
        """
    )

    result = _run_bash_harness(script)

    assert result.returncode == 0, result.stderr
    kill_calls = kill_log.read_text()
    assert "TERM 9000" in kill_calls
    assert "TERM 9001" not in kill_calls
    assert "Cleaning up project-local uvicorn PID(s): 9000" in result.stderr


def test_stop_service_creates_worker_log_dir_before_logging(tmp_path: pathlib.Path) -> None:
    kill_log = tmp_path / "kill.log"
    worker_log = tmp_path / "missing" / "nested" / "scan_worker.log"
    script = textwrap.dedent(
        f"""
        set -euo pipefail
        source {shlex.quote(str(SCRIPT_PATH))}
        load_env() {{ :; }}
        sleep() {{ :; }}
        send_signal() {{
          printf '%s %s\\n' "$1" "$2" >> {shlex.quote(str(kill_log))}
          return 0
        }}
        lsof() {{ return 0; }}
        ps() {{
          printf '%s\n' '7000 /opt/python {APP_ROOT}/recognition/worker/scan_worker.py'
        }}
        SCAN_WORKER_LOG={shlex.quote(str(worker_log))}
        stop_service
        """
    )

    result = _run_bash_harness(script)

    assert result.returncode == 0, result.stderr
    assert worker_log.exists()
    assert "Stopping scan worker PID(s): 7000" in worker_log.read_text()
    assert "TERM 7000" in kill_log.read_text()
