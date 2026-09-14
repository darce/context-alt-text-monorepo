"""Focused integration coverage for the real shared env-tag lock helper."""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"
REPO_ROOT = SCRIPT.parents[2]

pytestmark = pytest.mark.skipif(shutil.which("flock") is None, reason="requires real flock")


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _make_fake_tools(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "fake-state"
    state.mkdir()
    real_flock = shutil.which("flock")
    real_install = shutil.which("install")
    real_chmod = shutil.which("chmod")
    assert real_flock is not None
    assert real_install is not None
    assert real_chmod is not None

    _write_executable(
        fake_bin / "ssh",
        r"""#!/usr/bin/env bash
remote_command=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) shift; shift ;;
    -l) shift; shift ;;
    -n) shift ;;
    --)
      shift
      shift
      remote_command="$1"
      break
      ;;
    *) remote_command="$1"; break ;;
  esac
done
printf '%s\n' "$remote_command" >>"$FAKE_STATE/ssh.log"
exec /bin/bash -c "$remote_command"
""",
    )
    _write_executable(
        fake_bin / "sudo",
        r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FAKE_STATE/sudo.log"
command_name="$1"
shift
case "$command_name" in
  install)
    "__REAL_INSTALL__" "$@"
    rc=$?
    if [ "$rc" -eq 0 ]; then
      target=""
      for arg in "$@"; do
        target="$arg"
      done
      if [ -d "$target" ]; then
        "__REAL_CHMOD__" a-w "$target"
      fi
    fi
    exit "$rc"
    ;;
  flock)
    if [ "$FAKE_SUDO_FLOCK_FAILURE" = "1" ]; then
      printf '%s\n' "$FAKE_SUDO_FLOCK_STDERR" >&2
      exit 42
    fi
    lock_path=""
    expect_timeout=0
    for arg in "$@"; do
      if [ "$expect_timeout" = "1" ]; then
        expect_timeout=0
        continue
      fi
      if [ "$arg" = "-w" ]; then
        expect_timeout=1
        continue
      fi
      case "$arg" in
        -*) ;;
        *) lock_path="$arg"; break ;;
      esac
    done
    if [ -z "$lock_path" ]; then
      echo "fake sudo: flock lock path missing" >&2
      exit 43
    fi
    lock_dir="$(dirname "$lock_path")"
    "__REAL_CHMOD__" u+w "$lock_dir"
    FAKE_SUDO=1
    export FAKE_SUDO
    "__REAL_FLOCK__" "$@"
    rc=$?
    "__REAL_CHMOD__" a-w "$lock_dir"
    exit "$rc"
    ;;
  *) exec "$command_name" "$@" ;;
esac
""".replace("__REAL_INSTALL__", real_install)
        .replace("__REAL_CHMOD__", real_chmod)
        .replace("__REAL_FLOCK__", real_flock),
    )
    _write_executable(
        fake_bin / "flock",
        r"""#!/usr/bin/env bash
if [ "$FAKE_SUDO" != "1" ]; then
  echo "flock: unprivileged lock open denied" >&2
  exit 13
fi
exec "__REAL_FLOCK__" "$@"
""".replace("__REAL_FLOCK__", real_flock),
    )
    return fake_bin, state


def _base_env(fake_bin: Path, state: Path, tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
            "FAKE_STATE": str(state),
            "TMPDIR": str(tmp_path),
            "FAKE_SUDO": "0",
            "FAKE_SUDO_FLOCK_FAILURE": "0",
            "FAKE_SUDO_FLOCK_STDERR": "fake flock failure",
        }
    )
    return env


def _driver_command(tmp_path: Path, timeout: int, body: str) -> str:
    backup_root = tmp_path / "remote-backups"
    return "\n".join(
        [
            f"source {shlex.quote(str(SCRIPT))}",
            f"ACX_DEPLOY_BACKUP_ROOT={shlex.quote(str(backup_root))}",
            f"ACX_REMOTE_COMMAND_TIMEOUT={timeout}",
            body,
        ]
    )


def _run_driver(
    tmp_path: Path,
    fake_bin: Path,
    state: Path,
    body: str,
    *,
    timeout: int = 3,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = _base_env(fake_bin, state, tmp_path)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["/bin/bash", "-c", _driver_command(tmp_path, timeout, body)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )


def _start_driver(
    tmp_path: Path,
    fake_bin: Path,
    state: Path,
    body: str,
    *,
    timeout: int = 5,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["/bin/bash", "-c", _driver_command(tmp_path, timeout, body)],
        cwd=REPO_ROOT,
        env=_base_env(fake_bin, state, tmp_path),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_wrapped_command_runs_and_returns_its_status(tmp_path: Path) -> None:
    fake_bin, state = _make_fake_tools(tmp_path)
    marker = shlex.quote(str(tmp_path / "wrapped-ran"))
    result = _run_driver(
        tmp_path,
        fake_bin,
        state,
        f"wrapped() {{ printf '%s\\n' wrapped >{marker}; return 37; }}\nwith_shared_tag_lock shared wrapped",
    )

    assert result.returncode == 37, result.stderr
    assert (tmp_path / "wrapped-ran").read_text() == "wrapped\n"


def test_privileged_lock_open_passes_legacy_regression(tmp_path: Path) -> None:
    fake_bin, state = _make_fake_tools(tmp_path)
    locks = tmp_path / "remote-backups" / "locks"
    lock_path = locks / "tag-shared.lock"
    legacy_rc = shlex.quote(str(tmp_path / "legacy-rc"))
    new_marker = shlex.quote(str(tmp_path / "new-path"))
    legacy_remote = (
        f"sudo install -d -m 700 {shlex.quote(str(locks))} && "
        f"exec 9>{shlex.quote(str(lock_path))} && flock -w 1 9 && printf LEGACY"
    )
    body = "\n".join(
        [
            "legacy_rc=0",
            f"ssh -l \"$OCI_USER\" -- \"$OCI_HOST\" {shlex.quote(legacy_remote)} || legacy_rc=$?",
            f"printf '%s\\n' \"$legacy_rc\" >{legacy_rc}",
            f"with_shared_tag_lock shared printf 'new\\n' >{new_marker}",
        ]
    )
    result = _run_driver(tmp_path, fake_bin, state, body)

    assert result.returncode == 0, result.stderr
    assert int((tmp_path / "legacy-rc").read_text()) != 0
    assert (tmp_path / "new-path").read_text() == "new\n"
    remote_commands = (state / "ssh.log").read_text().splitlines()
    assert "exec 9>" in remote_commands[0]
    assert "sudo flock -w" in remote_commands[-1]
    assert "exec 9>" not in remote_commands[-1]
    assert "sh -c 'printf \"LOCKED\\n\"; exec cat >/dev/null'" in remote_commands[-1]


def test_holder_failure_warning_includes_sanitized_stderr(tmp_path: Path) -> None:
    fake_bin, state = _make_fake_tools(tmp_path)
    holder_stderr = "\n".join(f"holder diagnostic line {index}" for index in range(1, 7))
    result = _run_driver(
        tmp_path,
        fake_bin,
        state,
        "with_shared_tag_lock shared true",
        extra_env={
            "FAKE_SUDO_FLOCK_FAILURE": "1",
            "FAKE_SUDO_FLOCK_STDERR": holder_stderr,
        },
    )

    assert result.returncode == 1
    assert "could not acquire shared env-tag lock for shared" in result.stderr
    assert "holder stderr (first 5 lines)" in result.stderr
    assert "diagnostic: holder diagnostic line 1" in result.stderr
    assert "diagnostic: holder diagnostic line 5" in result.stderr
    assert "holder diagnostic line 6" not in result.stderr
    assert not list(tmp_path.glob("acx-tag-lock.*"))


def test_reentrant_call_does_not_open_a_second_holder(tmp_path: Path) -> None:
    fake_bin, state = _make_fake_tools(tmp_path)
    marker = shlex.quote(str(tmp_path / "reentrant"))
    body = f"inner() {{ printf 'inner\\n' >{marker}; }}\nwith_shared_tag_lock shared inner"
    result = _run_driver(tmp_path, fake_bin, state, body)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "reentrant").read_text() == "inner\n"
    remote_commands = (state / "ssh.log").read_text().splitlines()
    assert len(remote_commands) == 1


def test_second_holder_waits_until_first_releases(tmp_path: Path) -> None:
    fake_bin, state = _make_fake_tools(tmp_path)
    events = shlex.quote(str(tmp_path / "events"))
    first_body = "\n".join(
        [
            f"first() {{ printf 'first-started\\n' >>{events}; sleep 2; printf 'first-released\\n' >>{events}; }}",
            "with_shared_tag_lock shared first",
        ]
    )
    second_body = f"second() {{ printf 'second-started\\n' >>{events}; }}\nwith_shared_tag_lock shared second"
    first = _start_driver(tmp_path, fake_bin, state, first_body)
    second: subprocess.Popen[str] | None = None
    try:
        deadline = time.monotonic() + 6
        while not (tmp_path / "events").exists():
            if first.poll() is not None:
                stdout, stderr = first.communicate()
                pytest.fail(f"first holder exited early: {stdout}{stderr}")
            if time.monotonic() >= deadline:
                pytest.fail("first holder never acquired the shared lock")
            time.sleep(0.05)

        second = _start_driver(tmp_path, fake_bin, state, second_body)
        second_stdout, second_stderr = second.communicate(timeout=12)
        assert second.returncode == 0, second_stderr
        first_stdout, first_stderr = first.communicate(timeout=12)
        assert first.returncode == 0, first_stderr
        assert (tmp_path / "events").read_text().splitlines() == [
            "first-started",
            "first-released",
            "second-started",
        ]
        assert not second_stdout
    finally:
        if second is not None and second.poll() is None:
            second.terminate()
            second.communicate(timeout=5)
        if first.poll() is None:
            first.terminate()
        if first.poll() is None:
            first.communicate(timeout=5)
