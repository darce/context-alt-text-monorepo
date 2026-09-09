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
    assert "for acx_command in docker awk date sleep kill setsid; do" in source
    assert '"$acx_setsid" "$@" &' in source
    assert 'else\n    "$@" &' not in source
    assert 'kill -TERM -- "-$acx_pid"' in source
    assert 'kill -KILL -- "-$acx_pid"' in source


def test_generated_watchdog_reaps_a_synthetic_descendant(tmp_path: Path) -> None:
    """Exercise the watchdog emitted by bounded_remote_build_program itself."""
    marker = tmp_path / "descendant-lived"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)

    generated = _render_program()
    watchdog_prefix, separator, _ = generated.partition('if ! acx_run "Buildx capability probe"')
    assert separator, "generated program no longer exposes the actual watchdog before build setup"
    marker_arg = shlex.quote(str(marker))
    harness = (
        watchdog_prefix
        + f"""
set +e
acx_deadline_epoch=$(( $(date +%s) + 1 ))
acx_run "synthetic process-tree probe" bash -c 'trap "" TERM; (trap "" TERM; sleep 30; echo lived > {marker_arg}) & wait'
rc=$?
set -e
test "$rc" -eq 124
sleep 1
test ! -f {marker_arg}
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
    assert not marker.exists()


def test_generated_program_refuses_without_setsid(tmp_path: Path) -> None:
    generated = _render_program()
    bash_bin = shutil.which("bash")
    assert bash_bin
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for command in ("awk", "date", "sleep", "kill"):
        target = shutil.which(command)
        assert target
        (fake_bin / command).symlink_to(target)
    docker = fake_bin / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)

    completed = subprocess.run(
        [
            bash_bin,
            "-c",
            generated,
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
    )
    assert completed.returncode == 125
    assert "required command unavailable: setsid" in completed.stderr
