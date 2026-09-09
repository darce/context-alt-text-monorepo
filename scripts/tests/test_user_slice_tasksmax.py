from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/vm/install-user-slice-tasksmax.sh"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _run_installer(
    tmp_path: Path, *, reload_exit: int = 0, tasks_max: str = "4096"
) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "systemctl.log"
    _write_executable(
        fake_bin / "systemctl",
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$TASKSMAX_SYSTEMCTL_LOG"
case "$*" in
  "--user daemon-reload") exit "$TASKSMAX_RELOAD_EXIT" ;;
  "--user show user-"*" --property=TasksMax --value") printf '%s\\n' "$TASKSMAX_VALUE" ;;
  *) echo "unexpected systemctl invocation: $*" >&2; exit 99 ;;
esac
""",
    )
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "TASKSMAX_SYSTEMCTL_LOG": str(log),
        "TASKSMAX_RELOAD_EXIT": str(reload_exit),
        "TASKSMAX_VALUE": tasks_max,
    }
    return subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True, check=False)


def test_user_slice_tasksmax_dropin_is_applied_and_verified(tmp_path: Path) -> None:
    completed = _run_installer(tmp_path)

    assert completed.returncode == 0, completed.stderr
    uid = os.getuid()
    dropin = tmp_path / "config/systemd/user" / f"user-{uid}.slice.d/tasksmax.conf"
    assert dropin.read_text(encoding="utf-8") == "[Slice]\nTasksMax=4096\n"
    calls = (tmp_path / "systemctl.log").read_text(encoding="utf-8").splitlines()
    assert calls == ["--user daemon-reload", f"--user show user-{uid}.slice --property=TasksMax --value"]
    assert "applied" in completed.stdout


def test_user_slice_tasksmax_fails_when_manager_cannot_reload(tmp_path: Path) -> None:
    completed = _run_installer(tmp_path, reload_exit=1)

    assert completed.returncode != 0
    assert "daemon-reload failed" in completed.stderr
    assert "applied" not in completed.stdout


def test_user_slice_tasksmax_fails_when_active_value_does_not_match(tmp_path: Path) -> None:
    completed = _run_installer(tmp_path, tasks_max="512")

    assert completed.returncode != 0
    assert "active TasksMax is 512, expected 4096" in completed.stderr
