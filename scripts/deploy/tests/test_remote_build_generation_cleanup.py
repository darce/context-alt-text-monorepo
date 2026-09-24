"""Regressions for interrupted and stale remote build generation cleanup."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"
REPO_ROOT = SCRIPT.parents[2]
DEPLOY_SHA = "a" * 40


FAKE_SSH = r"""#!/usr/bin/env bash
set -euo pipefail
remote="${@: -1}"
printf '%s\n' "$remote" >>"${FAKE_SSH_LOG:?}"
if [[ "$remote" == find\ * && "${FAKE_FAIL_REAPER:-0}" == 1 ]]; then
  exit 1
fi
exit 0
"""


FAKE_RSYNC = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_RSYNC_LOG:?}"
exit 0
"""


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def remote_build(tmp_path: Path) -> dict[str, Path | str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    paths: dict[str, Path | str] = {
        "fake_bin": fake_bin,
        "remote_build_dir": tmp_path / "remote-build",
        "ssh_log": tmp_path / "ssh.log",
        "rsync_log": tmp_path / "rsync.log",
        "deadline_log": tmp_path / "deadline.log",
        "driver": tmp_path / "driver.sh",
    }
    _write_executable(fake_bin / "ssh", FAKE_SSH)
    _write_executable(fake_bin / "rsync", FAKE_RSYNC)
    return paths


def _driver_prelude() -> str:
    return f'''\\
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
preflight_ssh() {{ :; }}
preflight_remote_docker() {{ :; }}
preflight_rsync() {{ :; }}
assert_remote_build_free_space() {{ :; }}
recover_interrupted_cutover() {{ :; }}
pin_deploy_sha() {{ DEPLOY_SHA="{DEPLOY_SHA}"; }}
run_with_deadline() {{
  local deadline="$1" label="$2"
  shift 2
  printf '%s\\t%s\\t%s\\n' "$deadline" "$label" "$*" >>"${{FAKE_DEADLINE_LOG:?}}"
  "$@"
}}
'''


def _run_driver(
    remote_build: dict[str, Path | str],
    body: str,
    *,
    ttl: str = "360",
    fail_reaper: bool = False,
) -> subprocess.CompletedProcess[str]:
    driver = Path(remote_build["driver"])
    driver.write_text(_driver_prelude() + body)
    for key in ("ssh_log", "rsync_log", "deadline_log"):
        Path(remote_build[key]).unlink(missing_ok=True)
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{remote_build['fake_bin']}{os.pathsep}{env['PATH']}",
            "TMPDIR": str(Path(remote_build["driver"]).parent),
            "ACX_REMOTE_BUILD_DIR": str(remote_build["remote_build_dir"]),
            "ACX_REMOTE_BUILD_TIMEOUT": "30",
            "ACX_REMOTE_COMMAND_TIMEOUT": "10",
            "ACX_REMOTE_BUILD_GENERATION_TTL_MINUTES": ttl,
            "FAKE_FAIL_REAPER": "1" if fail_reaper else "0",
            "FAKE_SSH_LOG": str(remote_build["ssh_log"]),
            "FAKE_RSYNC_LOG": str(remote_build["rsync_log"]),
            "FAKE_DEADLINE_LOG": str(remote_build["deadline_log"]),
        }
    )
    return subprocess.run(
        ["bash", str(driver)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )


def _ssh_commands(remote_build: dict[str, Path | str]) -> list[str]:
    log_path = Path(remote_build["ssh_log"])
    return log_path.read_text().splitlines() if log_path.exists() else []


def _generation_rms(commands: list[str], remote_build_dir: Path) -> list[str]:
    prefix = f"{remote_build_dir}-"
    return [
        command
        for command in commands
        if command.startswith("rm -rf -- '") and prefix in command
    ]


def test_interrupt_after_rsync_removes_generation(remote_build: dict[str, Path | str]) -> None:
    driver_body = '''\\
trap deploy_interrupt_cleanup EXIT
trap 'deploy_interrupt_cleanup 129' HUP
trap 'deploy_interrupt_cleanup 130' INT
trap 'deploy_interrupt_cleanup 143' TERM
rsync() { kill -INT "$$"; }
do_build_remote dev
'''
    result = _run_driver(remote_build, driver_body)

    commands = _ssh_commands(remote_build)
    mkdir = next(command for command in commands if command.startswith("mkdir -p"))
    generation = re.search(r"'([^']+)'$", mkdir)
    assert generation, commands
    assert result.returncode == 130, result.stdout + result.stderr
    generation_rm = f"rm -rf -- '{generation.group(1)}'"
    assert generation_rm in commands


def test_normal_cleanup_clears_the_global(remote_build: dict[str, Path | str]) -> None:
    driver_body = '''\\
trap deploy_interrupt_cleanup EXIT
trap 'deploy_interrupt_cleanup 129' HUP
trap 'deploy_interrupt_cleanup 130' INT
trap 'deploy_interrupt_cleanup 143' TERM
do_build_remote dev
printf 'GENERATION=%s\\n' "${ACX_REMOTE_BUILD_GENERATION_DIR}"
'''
    result = _run_driver(remote_build, driver_body)

    commands = _ssh_commands(remote_build)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GENERATION=\n" in result.stdout
    assert len(_generation_rms(commands, Path(remote_build["remote_build_dir"]))) == 1


def test_reaper_targets_only_this_prefix(remote_build: dict[str, Path | str]) -> None:
    result = _run_driver(remote_build, "do_build_remote dev\n")

    commands = _ssh_commands(remote_build)
    reaper = next(command for command in commands if command.startswith("find "))
    mkdir_index = next(index for index, command in enumerate(commands) if command.startswith("mkdir -p"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "-mindepth 1 -maxdepth 1 -type d" in reaper
    assert "-name 'remote-build-*'" in reaper
    assert "-mmin +360" in reaper
    assert commands.index(reaper) < mkdir_index

    custom = _run_driver(remote_build, "do_build_remote dev\n", ttl="15")
    custom_reaper = next(command for command in _ssh_commands(remote_build) if command.startswith("find "))
    assert custom.returncode == 0, custom.stdout + custom.stderr
    assert "-mmin +15" in custom_reaper

    invalid = _run_driver(remote_build, "do_build_remote dev\n", ttl="0")
    invalid_commands = _ssh_commands(remote_build)
    assert invalid.returncode == 0, invalid.stdout + invalid.stderr
    assert not any(command.startswith("find ") for command in invalid_commands)
    assert any(command.startswith("mkdir -p") for command in invalid_commands)


def test_reaper_failure_does_not_fail_build(remote_build: dict[str, Path | str]) -> None:
    result = _run_driver(remote_build, "do_build_remote dev\n", fail_reaper=True)

    commands = _ssh_commands(remote_build)
    assert result.returncode == 0, result.stdout + result.stderr
    assert any(command.startswith("find ") for command in commands)
    assert any(command.startswith("mkdir -p") for command in commands)
    assert Path(remote_build["rsync_log"]).exists()
    assert "stale" in result.stderr.lower() or "reap" in result.stderr.lower()


def test_trap_refuses_foreign_directory(remote_build: dict[str, Path | str]) -> None:
    driver_body = '''\\
ACX_REMOTE_BUILD_GENERATION_DIR=/etc
deploy_interrupt_cleanup 130
'''
    result = _run_driver(remote_build, driver_body)

    assert result.returncode == 130
    assert not any(command.startswith("rm -rf") for command in _ssh_commands(remote_build))
