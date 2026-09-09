"""Focused fake-host regressions for the remote BuildKit bulkhead."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"
REPO_ROOT = SCRIPT.parents[2]


FAKE_DOCKER = r"""#!/usr/bin/env bash
set -euo pipefail

log_file="${FAKE_DOCKER_LOG:?}"
state_file="${FAKE_BUILDER_STATE:?}"
printf '%s\n' "$*" >>"$log_file"

command_name="${1:-}"
shift || true
if [[ "$command_name" == "info" ]]; then
  exit 0
fi
if [[ "$command_name" == "inspect" ]]; then
  if [[ "${FAKE_BUILDER_MODE:-}" == "limits" ]]; then
    printf '%s\n' '{"HostConfig":{"Memory":123,"MemorySwap":123,"CpuPeriod":100000,"CpuQuota":200000}}'
  else
    printf '%s\n' '{"HostConfig":{"Memory":6442450944,"MemorySwap":6442450944,"CpuPeriod":100000,"CpuQuota":200000}}'
  fi
  exit 0
fi
[[ "$command_name" == "buildx" ]] || exit 0

subcommand="${1:-}"
shift || true
case "$subcommand" in
  version)
    [[ "${FAKE_BUILDER_MODE:-}" != "unsupported" ]]
    ;;
  inspect)
    bootstrap=0
    for arg in "$@"; do
      [[ "$arg" == "--bootstrap" ]] && bootstrap=1
    done
    if [[ "${FAKE_BUILDER_MODE:-}" == "unsupported" ]]; then
      exit 127
    fi
    if [[ "${FAKE_BUILDER_MODE:-}" == "stable" && ! -f "$state_file" && "$bootstrap" == "0" ]]; then
      exit 1
    fi
    if [[ "${FAKE_BUILDER_MODE:-}" == "mismatch" ]]; then
      cat <<'INFO'
Name:      acx-deploy-builder-v1
Driver:    docker
Nodes:
Name:      acx-deploy-builder-v1-node
Endpoint:  unix:///var/run/docker.sock
Status:    running
INFO
      exit 0
    fi
    cat <<'INFO'
Name:      acx-deploy-builder-v1
Driver:    docker-container
Nodes:
Name:      acx-deploy-builder-v1-node
Endpoint:  unix:///var/run/docker.sock
Status:    running
INFO
    ;;
  create)
    touch "$state_file"
    ;;
  prune)
    ;;
  build)
    sleep "${FAKE_BUILD_SLEEP:-0}"
    touch "${FAKE_BUILD_RAN:?}"
    ;;
  *)
    exit 2
    ;;
esac
"""


FAKE_FLOCK = r"""#!/usr/bin/env bash
set -euo pipefail
wait_seconds=""
while [[ "${1:-}" == -* ]]; do
  if [[ "$1" == "-w" ]]; then
    wait_seconds="$2"
    shift 2
  else
    shift
  fi
done
lock_path="$1"
shift
printf 'wait=%s lock=%s command=%s\n' "$wait_seconds" "$lock_path" "$*" >>"${FAKE_FLOCK_LOG:?}"
"$@"
"""


FAKE_SSH = r"""#!/usr/bin/env bash
set -euo pipefail
remote="${@: -1}"
printf '%s\n' "$remote" >>"${FAKE_SSH_LOG:?}"
if [[ "$remote" == "echo ok" ]]; then
  exit 0
fi
if [[ "$remote" == *"docker info -f"* ]]; then
  printf '100\n'
  exit 0
fi
if [[ "$remote" == *"bash -s --"* || "$remote" == *"mkdir -p"* || "$remote" == *"rm -rf"* ]]; then
  bash -c "$remote"
  exit $?
fi
if [[ "$remote" == *"docker info"* ]]; then
  exit 0
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
def fake_remote_host(tmp_path: Path) -> dict[str, Path | str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "builder-created"
    build_ran = tmp_path / "build-ran"
    remote_build_dir = tmp_path / "remote-build"
    remote_build_dir.mkdir()
    paths = {
        "fake_bin": fake_bin,
        "state": state,
        "build_ran": build_ran,
        "remote_build_dir": remote_build_dir,
        "docker_log": tmp_path / "docker.log",
        "ssh_log": tmp_path / "ssh.log",
        "flock_log": tmp_path / "flock.log",
        "rsync_log": tmp_path / "rsync.log",
    }
    _write_executable(fake_bin / "docker", FAKE_DOCKER)
    _write_executable(fake_bin / "flock", FAKE_FLOCK)
    _write_executable(fake_bin / "ssh", FAKE_SSH)
    _write_executable(fake_bin / "rsync", FAKE_RSYNC)
    return paths


def _run_remote_build(
    fake_remote_host: dict[str, Path | str],
    mode: str,
    *,
    build_timeout: str = "30",
    build_sleep: str = "0",
) -> subprocess.CompletedProcess[str]:
    driver = Path(fake_remote_host["fake_bin"]).parent / "driver.sh"
    driver.write_text(
        f"""\
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
do_build_remote dev
"""
    )
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{fake_remote_host['fake_bin']}{os.pathsep}{env['PATH']}",
            "FAKE_BUILDER_MODE": mode,
            "FAKE_BUILD_SLEEP": build_sleep,
            "FAKE_BUILDER_STATE": str(fake_remote_host["state"]),
            "FAKE_BUILD_RAN": str(fake_remote_host["build_ran"]),
            "FAKE_DOCKER_LOG": str(fake_remote_host["docker_log"]),
            "FAKE_SSH_LOG": str(fake_remote_host["ssh_log"]),
            "FAKE_FLOCK_LOG": str(fake_remote_host["flock_log"]),
            "FAKE_RSYNC_LOG": str(fake_remote_host["rsync_log"]),
            "ACX_REMOTE_BUILD_DIR": str(fake_remote_host["remote_build_dir"]),
            "ACX_REMOTE_BUILD_TIMEOUT": build_timeout,
            "ACX_REMOTE_COMMAND_TIMEOUT": "10",
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


@pytest.mark.parametrize("mode", ["unsupported", "mismatch", "limits"])
def test_remote_build_refuses_unsupported_or_mismatched_builder(
    fake_remote_host: dict[str, Path | str], mode: str
) -> None:
    result = _run_remote_build(fake_remote_host, mode)

    assert result.returncode != 0, result.stdout + result.stderr
    docker_log = Path(fake_remote_host["docker_log"]).read_text()
    assert "buildx build" not in docker_log
    assert not Path(fake_remote_host["build_ran"]).exists()


def test_remote_build_reuses_limited_builder_and_loads_only_full_sha(
    fake_remote_host: dict[str, Path | str],
) -> None:
    first = _run_remote_build(fake_remote_host, "stable")
    second = _run_remote_build(fake_remote_host, "stable")
    combined = first.stdout + first.stderr + second.stdout + second.stderr
    assert first.returncode == 0, combined
    assert second.returncode == 0, combined

    docker_lines = Path(fake_remote_host["docker_log"]).read_text().splitlines()
    create_lines = [line for line in docker_lines if line.startswith("buildx create ")]
    build_lines = [line for line in docker_lines if line.startswith("buildx build ")]
    assert len(create_lines) == 1
    assert len(build_lines) == 2
    create = create_lines[0]
    assert "--name acx-deploy-builder-v1" in create
    assert "--node acx-deploy-builder-v1-node" in create
    assert "--driver docker-container" in create
    assert "--driver-opt memory=6g" in create
    assert "--driver-opt memory-swap=6g" in create
    assert "--driver-opt cpu-period=100000" in create
    assert "--driver-opt cpu-quota=200000" in create
    assert create.endswith("unix:///var/run/docker.sock")

    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    for build in build_lines:
        assert "--builder acx-deploy-builder-v1" in build
        assert "--load" in build
        assert f"-t iad.ocir.io/idu2kqqe2jxy/acx-backend:{sha}" in build
        assert ":dev" not in build
    assert "buildx use" not in "\n".join(docker_lines)

    flock_lines = Path(fake_remote_host["flock_log"]).read_text().splitlines()
    assert len(flock_lines) == 2
    for line in flock_lines:
        match = re.search(r"wait=(\d+) lock=(\S+) command=bash -s --", line)
        assert match, line
        assert 1 <= int(match.group(1)) <= 30
        assert match.group(2) == f"{fake_remote_host['remote_build_dir']}.lock"

    ssh_lines = Path(fake_remote_host["ssh_log"]).read_text()
    assert "bash -s --" in ssh_lines
    assert "--use" not in ssh_lines


def test_remote_build_does_not_extend_budget_for_a_stalled_build(
    fake_remote_host: dict[str, Path | str],
) -> None:
    result = _run_remote_build(
        fake_remote_host,
        "stable",
        build_timeout="2",
        build_sleep="10",
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert not Path(fake_remote_host["build_ran"]).exists()
    flock_lines = Path(fake_remote_host["flock_log"]).read_text().splitlines()
    assert len(flock_lines) == 1
    match = re.search(r"wait=(\d+)", flock_lines[0])
    assert match and 1 <= int(match.group(1)) <= 2
