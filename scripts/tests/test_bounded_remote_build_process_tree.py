from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/deploy/lib/bounded-remote-build.sh"


def _render_program() -> str:
    completed = subprocess.run(
        ["bash", "-c", 'source "$1"; bounded_remote_build_program', "bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_inner_watchdog_kills_process_group() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "acx_kill_tree" in source
    assert "acx_list_descendants" in source
    assert '"$acx_setsid" "$@" &' in source
    assert '"$@" &' in source
    assert 'kill -TERM -- "-$acx_pid"' in source
    assert 'kill -KILL -- "-$acx_pid"' in source


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_generated_watchdog_reaps_a_synthetic_descendant(tmp_path: Path) -> None:
    """Run the production watchdog against a real grandchild, not a reimplemented killer."""
    pidfile = tmp_path / "grandchild.pid"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)

    generated = _render_program()
    watchdog_prefix, separator, _ = generated.partition('if ! acx_run "Buildx capability probe"')
    assert separator, "generated program no longer exposes the actual watchdog before build setup"
    pid_arg = shlex.quote(str(pidfile))
    harness = (
        watchdog_prefix
        + f"""
set +e
acx_deadline_epoch=$(( $(date +%s) + 1 ))
acx_run "synthetic process-tree probe" sh -c 'sleep 300 & echo $! > {pid_arg}; wait'
rc=$?
set -e
test "$rc" -eq 124
test -s {pid_arg}
"""
    )
    completed = subprocess.run(
        [
            "bash",
            "-c",
            harness,
            "bash",
            "builder",
            "node",
            "unix:///var/run/docker.sock",
            "repo/image",
            "a" * 40,
            "",
            "9999999999",
            str(tmp_path),
        ],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    time.sleep(0.2)
    assert completed.returncode == 0, completed.stderr
    grandchild = int(pidfile.read_text(encoding="utf-8").strip())
    assert grandchild > 1
    assert not _pid_is_alive(grandchild), f"grandchild {grandchild} survived the production watchdog"


def test_generated_watchdog_reaps_a_grandchild_without_setsid(tmp_path: Path) -> None:
    """When setsid is hidden, the production killer must still walk descendants."""
    pidfile = tmp_path / "grandchild.pid"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    bash_bin = shutil.which("bash")
    assert bash_bin
    for command in ("awk", "date", "sleep", "kill", "ps", "pgrep", "sh"):
        target = shutil.which(command)
        assert target, command
        (fake_bin / command).symlink_to(target)
    (fake_bin / "bash").symlink_to(bash_bin)
    docker = fake_bin / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)

    generated = _render_program()
    watchdog_prefix, separator, _ = generated.partition('if ! acx_run "Buildx capability probe"')
    assert separator, "generated program no longer exposes the actual watchdog before build setup"
    pid_arg = shlex.quote(str(pidfile))
    harness = (
        watchdog_prefix
        + f"""
set +e
acx_deadline_epoch=$(( $(date +%s) + 1 ))
acx_run "synthetic process-tree probe" sh -c 'sleep 300 & echo $! > {pid_arg}; wait'
rc=$?
set -e
test "$rc" -eq 124
test -s {pid_arg}
"""
    )
    completed = subprocess.run(
        [
            bash_bin,
            "-c",
            harness,
            "bash",
            "builder",
            "node",
            "unix:///var/run/docker.sock",
            "repo/image",
            "a" * 40,
            "",
            "9999999999",
            str(tmp_path),
        ],
        env={"PATH": str(fake_bin)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    time.sleep(0.2)
    assert completed.returncode == 0, completed.stderr
    grandchild = int(pidfile.read_text(encoding="utf-8").strip())
    assert grandchild > 1
    assert not _pid_is_alive(grandchild), f"grandchild {grandchild} survived without setsid"
