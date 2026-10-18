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

FAKE_DOCKER = r"""#!/usr/bin/env bash
set -euo pipefail

log_file="${FAKE_DOCKER_LOG:?}"
printf '%s\n' "$*" >>"$log_file"

command_name="${1:-}"
shift || true
if [[ "$command_name" == "info" ]]; then
  exit 0
fi
if [[ "$command_name" == "inspect" ]]; then
  printf '%s\n' '{"HostConfig":{"Memory":6442450944,"MemorySwap":6442450944,"CpuPeriod":100000,"CpuQuota":200000}}'
  exit 0
fi
[[ "$command_name" == "buildx" ]] || exit 0

subcommand="${1:-}"
shift || true
case "$subcommand" in
  version)
    exit 0
    ;;
  inspect)
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
    exit 0
    ;;
  prune)
    exit 0
    ;;
  build)
    sleep 300 &
    echo $! > "${FAKE_GRANDCHILD_PIDFILE:?}"
    wait
    ;;
  *)
    exit 2
    ;;
esac
"""

PROGRAM_ARGS = (
    "acx-deploy-builder-v1",
    "acx-deploy-builder-v1-node",
    "unix:///var/run/docker.sock",
    "repo/image",
    "a" * 40,
    "",
)


def _render_program() -> str:
    completed = subprocess.run(
        ["bash", "-c", 'source "$1"; bounded_remote_build_program', "bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _watchdog_prefix(generated: str) -> str:
    watchdog_prefix, separator, _ = generated.partition('if ! acx_run "Buildx capability probe"')
    assert separator, "generated program no longer exposes the actual watchdog before build setup"
    return watchdog_prefix


def _run_watchdog_harness(
    harness: str,
    tmp_path: Path,
    *,
    env: dict[str, str],
    bash_bin: str = "bash",
    timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def test_generated_program_fake_docker_reaps_grandchild(tmp_path: Path) -> None:
    """Full generated program: a FAKE_DOCKER build grandchild must die with the deadline.

    This is the behavioural replacement for grepping the source for `setsid`.
    Isolation is intentional: recognition-service.sh's outer terminator is not
    on the path, so a passing result cannot be the local SSH walker masking a
    broken inner watchdog.
    """
    pidfile = tmp_path / "grandchild.pid"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "docker", FAKE_DOCKER)

    deadline = int(time.time()) + 2
    completed = subprocess.run(
        [
            "bash",
            "-c",
            _render_program(),
            "bash",
            *PROGRAM_ARGS,
            str(deadline),
            str(tmp_path),
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
            "FAKE_GRANDCHILD_PIDFILE": str(pidfile),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    time.sleep(0.2)
    assert completed.returncode == 124, completed.stdout + completed.stderr
    assert pidfile.exists() and pidfile.stat().st_size > 0, completed.stderr
    grandchild = int(pidfile.read_text(encoding="utf-8").strip())
    assert grandchild > 1
    assert not _pid_is_alive(grandchild), f"FAKE_DOCKER grandchild {grandchild} survived the generated watchdog"
    docker_log = (tmp_path / "docker.log").read_text(encoding="utf-8")
    assert "buildx build" in docker_log


def test_generated_watchdog_reaps_a_synthetic_descendant(tmp_path: Path) -> None:
    """Run the production watchdog against a real grandchild, not a reimplemented killer."""
    pidfile = tmp_path / "grandchild.pid"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)

    pid_arg = shlex.quote(str(pidfile))
    harness = (
        _watchdog_prefix(_render_program())
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
    completed = _run_watchdog_harness(
        harness,
        tmp_path,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
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

    pid_arg = shlex.quote(str(pidfile))
    harness = (
        _watchdog_prefix(_render_program())
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
    completed = _run_watchdog_harness(
        harness,
        tmp_path,
        env={"PATH": str(fake_bin)},
        bash_bin=bash_bin,
    )
    time.sleep(0.2)
    assert completed.returncode == 0, completed.stderr
    grandchild = int(pidfile.read_text(encoding="utf-8").strip())
    assert grandchild > 1
    assert not _pid_is_alive(grandchild), f"grandchild {grandchild} survived without setsid"


def test_generated_watchdog_reaps_a_term_ignoring_grandchild_without_setsid(tmp_path: Path) -> None:
    """TERM-ignoring grandchildren must still die from the captured KILL set."""
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

    pid_arg = shlex.quote(str(pidfile))
    harness = (
        _watchdog_prefix(_render_program())
        + f"""
set +e
acx_deadline_epoch=$(( $(date +%s) + 1 ))
acx_run "synthetic process-tree probe" sh -c '( trap "" TERM; exec sleep 300 ) & echo $! > {pid_arg}; wait'
rc=$?
set -e
test "$rc" -eq 124
test -s {pid_arg}
"""
    )
    completed = _run_watchdog_harness(
        harness,
        tmp_path,
        env={"PATH": str(fake_bin)},
        bash_bin=bash_bin,
    )
    time.sleep(0.2)
    assert completed.returncode == 0, completed.stderr
    grandchild = int(pidfile.read_text(encoding="utf-8").strip())
    assert grandchild > 1
    assert not _pid_is_alive(grandchild), f"TERM-ignoring grandchild {grandchild} survived without setsid"


def test_generated_program_preserves_deadline_exit_when_already_expired(
    tmp_path: Path,
) -> None:
    """Deadline 124 must not be rewritten as bulkhead-unavailable 125."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "docker", FAKE_DOCKER)

    deadline = int(time.time()) - 1
    completed = subprocess.run(
        [
            "bash",
            "-c",
            _render_program(),
            "bash",
            *PROGRAM_ARGS,
            str(deadline),
            str(tmp_path),
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
            "FAKE_GRANDCHILD_PIDFILE": str(tmp_path / "grandchild.pid"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    combined = completed.stdout + completed.stderr
    assert completed.returncode == 124, combined
    assert "overall deadline exhausted" in combined
    assert "bulkhead:" not in combined


def test_generated_program_reaps_grandchild_when_fractional_sleep_is_rejected(
    tmp_path: Path,
) -> None:
    """BSD sleep rejects `0.1`; under set -e that must not skip KILL (macOS bash 3.2)."""
    pidfile = tmp_path / "grandchild.pid"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    bash_bin = shutil.which("bash")
    assert bash_bin
    real_sleep = shutil.which("sleep")
    assert real_sleep
    for command in ("awk", "cat", "date", "kill", "ps", "pgrep", "sh", "setsid"):
        target = shutil.which(command)
        if target is None and command == "setsid":
            continue
        assert target, command
        (fake_bin / command).symlink_to(target)
    (fake_bin / "bash").symlink_to(bash_bin)
    _write_executable(
        fake_bin / "sleep",
        f"""\
#!/usr/bin/env bash
if [[ "${{1:-}}" == "0.1" ]]; then
  printf 'sleep: invalid time interval\\n' >&2
  exit 1
fi
exec {shlex.quote(real_sleep)} "$@"
""",
    )
    _write_executable(fake_bin / "docker", FAKE_DOCKER)

    # Integer sleep fallback is 1s per poll, so a 2s overall budget can
    # expire during setup and never start the build grandchild.
    deadline = int(time.time()) + 12
    completed = subprocess.run(
        [
            bash_bin,
            "-c",
            _render_program(),
            "bash",
            *PROGRAM_ARGS,
            str(deadline),
            str(tmp_path),
        ],
        env={
            "PATH": str(fake_bin),
            "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
            "FAKE_GRANDCHILD_PIDFILE": str(pidfile),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=25,
    )
    time.sleep(0.2)
    assert completed.returncode == 124, completed.stdout + completed.stderr
    assert pidfile.exists() and pidfile.stat().st_size > 0, completed.stderr
    grandchild = int(pidfile.read_text(encoding="utf-8").strip())
    assert grandchild > 1
    assert not _pid_is_alive(grandchild), f"grandchild {grandchild} survived after fractional sleep was rejected"


def test_generated_watchdog_fails_closed_without_process_enumeration(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    bash_bin = shutil.which("bash")
    assert bash_bin
    for command in ("awk", "date", "sleep", "kill", "sh"):
        target = shutil.which(command)
        assert target, command
        (fake_bin / command).symlink_to(target)
    (fake_bin / "bash").symlink_to(bash_bin)
    docker = fake_bin / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)

    harness = _watchdog_prefix(_render_program()) + "\ntrue\n"
    completed = _run_watchdog_harness(
        harness,
        tmp_path,
        env={"PATH": str(fake_bin)},
        bash_bin=bash_bin,
    )
    assert completed.returncode == 125, completed.stderr
    assert "pgrep or ps" in completed.stderr
