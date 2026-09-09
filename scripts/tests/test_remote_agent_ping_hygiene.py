from __future__ import annotations

import os
import shlex
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/remote_agent_hygiene.sh"


def _run(
    *args: str,
    env: dict[str, str] | None = None,
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=merged,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def test_ping_timeout_zero_is_rejected() -> None:
    completed = _run("ping", "true", env={"PING_TIMEOUT_SEC": "0"})
    assert completed.returncode == 2
    assert "PING_TIMEOUT_SEC" in completed.stderr
    assert "0 disables the bound" in completed.stderr


def test_ping_timeout_non_integer_is_rejected() -> None:
    completed = _run("ping", "true", env={"PING_TIMEOUT_SEC": "1.5"})
    assert completed.returncode == 2
    assert "PING_TIMEOUT_SEC must be an integer" in completed.stderr


def test_ping_timeout_above_max_is_rejected() -> None:
    completed = _run("ping", "true", env={"PING_TIMEOUT_SEC": "121"})
    assert completed.returncode == 2
    assert "<= 120" in completed.stderr


def test_ping_timeout_minimum_is_accepted() -> None:
    completed = _run("ping", "true", env={"PING_TIMEOUT_SEC": "1"})
    assert completed.returncode == 0, completed.stderr


def _etime(value: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; acx_etime_to_seconds "$2"', "bash", str(SCRIPT), value],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


@pytest.mark.parametrize(
    ("etime", "seconds"),
    [
        ("00:08", 8),
        ("00:09", 9),
        ("01:08", 68),
        ("08:09", 489),
        ("10:08", 608),
        ("12:08:30", 43710),
        ("1-02:08:09", 94089),
        ("00:45", 45),
        ("05:00", 300),
        ("1-02:03:04", 93784),
        ("08:09:08", 29348),
        ("1-08:09:08", 115748),
    ],
)
def test_etime_to_seconds_table(etime: str, seconds: int) -> None:
    """ps etime zero-pads 08/09; bash $((08)) is invalid octal (HARM-03)."""
    completed = _etime(etime)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == str(seconds)


def test_ping_timeout_zero_padded_is_normalized_to_decimal() -> None:
    completed = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; acx_validate_ping_timeout; printf "%s\\n" "$PING_TIMEOUT_SEC"',
            "bash",
            str(SCRIPT),
        ],
        env={**os.environ, "PING_TIMEOUT_SEC": "08"},
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "8"


def test_ping_timeout_zero_padded_zero_is_rejected() -> None:
    completed = _run("ping", "true", env={"PING_TIMEOUT_SEC": "00"})
    assert completed.returncode == 2
    assert "PING_TIMEOUT_SEC" in completed.stderr
    assert "0 disables the bound" in completed.stderr


def test_ping_timeout_unset_falls_back_to_bounded_default() -> None:
    env = {key: value for key, value in os.environ.items() if key != "PING_TIMEOUT_SEC"}
    completed = subprocess.run(
        ["bash", "-c", 'source "$1"; printf "%s\\n" "$PING_TIMEOUT_SEC"', "bash", str(SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "5"
    assert "PING_TIMEOUT_SEC unset or empty; defaulting to 5" in completed.stderr


def test_ping_timeout_empty_falls_back_to_bounded_default() -> None:
    completed = subprocess.run(
        ["bash", "-c", 'source "$1"; printf "%s\\n" "$PING_TIMEOUT_SEC"', "bash", str(SCRIPT)],
        env={**os.environ, "PING_TIMEOUT_SEC": ""},
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "5"
    assert "PING_TIMEOUT_SEC unset or empty; defaulting to 5" in completed.stderr


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_orphan_reaper_kills_only_stale_ppid1_ping(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    kill_log = tmp_path / "kill.log"
    _write_executable(
        fake_bin / "ps",
        """#!/usr/bin/env bash
cat <<'EOF'
  111     1       00:45 codex exec --json ping
  222     1       00:05 codex exec --json ping
  333    50       05:00 codex exec --json ping
  444     1       01:00 sleep 300
EOF
""",
    )
    state_dir = tmp_path / "kill-state"
    state_dir.mkdir()
    _write_executable(
        fake_bin / "kill",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >>{shlex.quote(str(kill_log))}
sig="$1"
pid="$2"
state={shlex.quote(str(state_dir))}
case "$sig" in
  -TERM)
    printf 'dead\\n' >"$state/$pid"
    exit 0
    ;;
  -KILL)
    printf 'dead\\n' >"$state/$pid"
    exit 0
    ;;
  -0)
    if [[ "$(cat "$state/$pid" 2>/dev/null || true)" == "dead" ]]; then
      exit 1
    fi
    exit 0
    ;;
esac
exit 0
""",
    )
    completed = subprocess.run(
        ["bash", "-c", 'source "$1"; acx_reap_orphan_pings', "bash", str(SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "ORPHAN_PING_STALE_SEC": "30",
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    lines = kill_log.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "-TERM 111"
    assert all(line.split()[-1] == "111" for line in lines)
    assert "-KILL 111" not in lines
    assert "reaped 1 stale orphan ping probe(s)" in completed.stdout


def test_orphan_reaper_escalates_term_to_kill_for_stubborn_ping(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    kill_log = tmp_path / "kill.log"
    state_dir = tmp_path / "kill-state"
    state_dir.mkdir()
    _write_executable(
        fake_bin / "ps",
        """#!/usr/bin/env bash
cat <<'EOF'
  111     1       00:45 codex exec --json ping
EOF
""",
    )
    _write_executable(
        fake_bin / "kill",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >>{shlex.quote(str(kill_log))}
sig="$1"
pid="$2"
state={shlex.quote(str(state_dir))}
case "$sig" in
  -TERM)
    printf 'alive\\n' >"$state/$pid"
    exit 0
    ;;
  -KILL)
    printf 'dead\\n' >"$state/$pid"
    exit 0
    ;;
  -0)
    if [[ "$(cat "$state/$pid" 2>/dev/null || true)" == "dead" ]]; then
      exit 1
    fi
    exit 0
    ;;
esac
exit 0
""",
    )
    completed = subprocess.run(
        ["bash", "-c", 'source "$1"; acx_reap_orphan_pings', "bash", str(SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "ORPHAN_PING_STALE_SEC": "30",
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    lines = kill_log.read_text(encoding="utf-8").splitlines()
    assert "-TERM 111" in lines
    assert "-KILL 111" in lines
    assert lines.index("-TERM 111") < lines.index("-KILL 111")
    assert "reaped 1 stale orphan ping probe(s)" in completed.stdout


def test_orphan_reaper_does_not_count_unkillable_ping(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    kill_log = tmp_path / "kill.log"
    _write_executable(
        fake_bin / "ps",
        """#!/usr/bin/env bash
cat <<'EOF'
  111     1       00:45 codex exec --json ping
EOF
""",
    )
    _write_executable(
        fake_bin / "kill",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >>{shlex.quote(str(kill_log))}
exit 0
""",
    )
    completed = subprocess.run(
        ["bash", "-c", 'source "$1"; acx_reap_orphan_pings', "bash", str(SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "ORPHAN_PING_STALE_SEC": "30",
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    lines = kill_log.read_text(encoding="utf-8").splitlines()
    assert "-TERM 111" in lines
    assert "-KILL 111" in lines
    assert "reaped 0 stale orphan ping probe(s)" in completed.stdout


def test_bounded_ping_times_out_a_sleeping_codex(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "codex",
        """#!/usr/bin/env bash
exec sleep 30
""",
    )
    started = time.monotonic()
    completed = _run(
        "ping",
        str(fake_bin / "codex"),
        env={"PING_TIMEOUT_SEC": "1"},
        timeout=10,
    )
    elapsed = time.monotonic() - started
    assert completed.returncode == 124, completed.stderr
    assert elapsed < 5, f"hung ping was not bounded: {elapsed:.1f}s"


def test_bounded_ping_does_not_call_gnu_timeout(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "timeout",
        """#!/usr/bin/env bash
echo GNU_TIMEOUT_CALLED >&2
exit 99
""",
    )
    _write_executable(
        fake_bin / "codex",
        """#!/usr/bin/env bash
exec sleep 30
""",
    )
    started = time.monotonic()
    completed = _run(
        "ping",
        str(fake_bin / "codex"),
        env={
            "PING_TIMEOUT_SEC": "1",
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        },
        timeout=10,
    )
    elapsed = time.monotonic() - started
    assert completed.returncode == 124, completed.stderr
    assert "GNU_TIMEOUT_CALLED" not in completed.stderr
    assert elapsed < 5, f"hung ping was not bounded: {elapsed:.1f}s"


def test_bounded_ping_reaps_grandchild(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    pidfile = tmp_path / "grandchild.pid"
    _write_executable(
        fake_bin / "codex",
        f"""#!/usr/bin/env bash
sleep 30 &
printf '%s\\n' "$!" >{shlex.quote(str(pidfile))}
wait
""",
    )
    started = time.monotonic()
    completed = _run(
        "ping",
        str(fake_bin / "codex"),
        env={"PING_TIMEOUT_SEC": "1"},
        timeout=10,
    )
    elapsed = time.monotonic() - started
    assert completed.returncode == 124, completed.stderr
    assert elapsed < 5, f"hung ping was not bounded: {elapsed:.1f}s"
    assert pidfile.exists(), "grandchild pid was not recorded"
    grandchild = int(pidfile.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"grandchild {grandchild} still alive after ping deadline")


def test_orphan_reaper_kills_stale_ping_with_zero_padded_etime(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    kill_log = tmp_path / "kill.log"
    _write_executable(
        fake_bin / "ps",
        """#!/usr/bin/env bash
cat <<'EOF'
  111     1       08:00 codex exec --json ping
  222     1       00:08 codex exec --json ping
EOF
""",
    )
    state_dir = tmp_path / "kill-state"
    state_dir.mkdir()
    _write_executable(
        fake_bin / "kill",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >>{shlex.quote(str(kill_log))}
sig="$1"
pid="$2"
state={shlex.quote(str(state_dir))}
case "$sig" in
  -TERM)
    printf 'dead\\n' >"$state/$pid"
    exit 0
    ;;
  -KILL)
    printf 'dead\\n' >"$state/$pid"
    exit 0
    ;;
  -0)
    if [[ "$(cat "$state/$pid" 2>/dev/null || true)" == "dead" ]]; then
      exit 1
    fi
    exit 0
    ;;
esac
exit 0
""",
    )
    completed = subprocess.run(
        ["bash", "-c", 'source "$1"; acx_reap_orphan_pings', "bash", str(SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "ORPHAN_PING_STALE_SEC": "30",
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    lines = kill_log.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "-TERM 111"
    assert all(line.split()[-1] == "111" for line in lines)
    assert "reaped 1 stale orphan ping probe(s)" in completed.stdout


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _real_kill_wrapper(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    kill_log = tmp_path / "kill.log"
    real_kill = subprocess.run(
        ["bash", "-c", "type -P kill"],
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    ).stdout.strip()
    assert real_kill, "kill executable not found on PATH"
    _write_executable(
        fake_bin / "kill",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >>{shlex.quote(str(kill_log))}
exec {shlex.quote(real_kill)} "$@"
""",
    )
    return fake_bin, kill_log


def _spawn_managed_child(tmp_path: Path, *, ignore_term: bool) -> tuple[subprocess.Popen[bytes], int]:
    pidfile = tmp_path / "child.pid"
    helper = f"""
import os, signal, time
pid = os.fork()
if pid == 0:
    if {ignore_term!r}:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open({str(pidfile)!r}, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
        fh.flush()
        os.fsync(fh.fileno())
    time.sleep(60)
    os._exit(0)
os.waitpid(pid, 0)
"""
    reaper = subprocess.Popen(
        [sys.executable, "-c", helper],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if pidfile.exists():
            text = pidfile.read_text(encoding="utf-8").strip()
            if text.isdigit():
                child = int(text)
                if _pid_is_alive(child):
                    return reaper, child
        if reaper.poll() is not None:
            break
        time.sleep(0.02)
    try:
        os.killpg(reaper.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    raise AssertionError("managed child did not start")


def _reap_managed(reaper: subprocess.Popen[bytes], child: int) -> None:
    try:
        os.kill(child, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        os.killpg(reaper.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    reaper.wait(timeout=2)


def test_kill_pid_terminates_child_that_ignores_term(tmp_path: Path) -> None:
    fake_bin, kill_log = _real_kill_wrapper(tmp_path)
    reaper, child = _spawn_managed_child(tmp_path, ignore_term=True)
    try:
        completed = subprocess.run(
            ["bash", "-c", 'source "$1"; acx_kill_pid "$2"', "bash", str(SCRIPT), str(child)],
            env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert completed.returncode == 0, completed.stderr
        lines = kill_log.read_text(encoding="utf-8").splitlines()
        assert f"-TERM {child}" in lines
        assert f"-KILL {child}" in lines
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and _pid_is_alive(child):
            time.sleep(0.02)
        assert not _pid_is_alive(child), f"pid {child} still alive after acx_kill_pid"
    finally:
        _reap_managed(reaper, child)


def test_kill_pid_does_not_send_kill_when_term_exits(tmp_path: Path) -> None:
    fake_bin, kill_log = _real_kill_wrapper(tmp_path)
    reaper, child = _spawn_managed_child(tmp_path, ignore_term=False)
    try:
        completed = subprocess.run(
            ["bash", "-c", 'source "$1"; acx_kill_pid "$2"', "bash", str(SCRIPT), str(child)],
            env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert completed.returncode == 0, completed.stderr
        lines = kill_log.read_text(encoding="utf-8").splitlines()
        assert f"-TERM {child}" in lines
        assert f"-KILL {child}" not in lines
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and _pid_is_alive(child):
            time.sleep(0.02)
        assert not _pid_is_alive(child), f"pid {child} still alive after TERM"
    finally:
        _reap_managed(reaper, child)


def test_orphan_reaper_logs_unparseable_etime(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    kill_log = tmp_path / "kill.log"
    _write_executable(
        fake_bin / "ps",
        """#!/usr/bin/env bash
cat <<'EOF'
  111     1       not-a-clock codex exec --json ping
EOF
""",
    )
    _write_executable(
        fake_bin / "kill",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >>{shlex.quote(str(kill_log))}
exit 0
""",
    )
    completed = subprocess.run(
        ["bash", "-c", 'source "$1"; acx_reap_orphan_pings', "bash", str(SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "ORPHAN_PING_STALE_SEC": "30",
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert not kill_log.exists() or kill_log.read_text(encoding="utf-8") == ""
    assert "could not parse etime" in completed.stderr
    assert "skipped 1 ping probe(s) with unparseable etime" in completed.stderr
    assert "reaped 0 stale orphan ping probe(s)" in completed.stdout


@pytest.mark.parametrize(
    ("cmd", "expect_match"),
    [
        ("codex exec --json ping", True),
        ("codex exec ping --json", True),
        ("ping", True),
        ("codex exec --json ping ", True),
        ("codex exec ping-hygiene", False),
        ("codex mapping --json", False),
        ("keeping", False),
        ("codex pingpong", False),
        ("pinging codex", False),
    ],
)
def test_cmd_has_ping_token(cmd: str, expect_match: bool) -> None:
    completed = subprocess.run(
        ["bash", "-c", 'source "$1"; acx_cmd_has_ping_token "$2"', "bash", str(SCRIPT), cmd],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert (completed.returncode == 0) is expect_match, completed.stderr


def test_orphan_reaper_ignores_ping_substring_false_positives(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    kill_log = tmp_path / "kill.log"
    state_dir = tmp_path / "kill-state"
    state_dir.mkdir()
    _write_executable(
        fake_bin / "ps",
        """#!/usr/bin/env bash
cat <<'EOF'
  111     1       00:45 codex exec --json ping
  555     1       01:00 codex exec ping-hygiene
  666     1       01:00 codex mapping --json
  777     1       01:00 keeping pinging mapping
EOF
""",
    )
    _write_executable(
        fake_bin / "kill",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >>{shlex.quote(str(kill_log))}
sig="$1"
pid="$2"
state={shlex.quote(str(state_dir))}
case "$sig" in
  -TERM|-KILL)
    printf 'dead\\n' >"$state/$pid"
    exit 0
    ;;
  -0)
    if [[ "$(cat "$state/$pid" 2>/dev/null || true)" == "dead" ]]; then
      exit 1
    fi
    exit 0
    ;;
esac
exit 0
""",
    )
    completed = subprocess.run(
        ["bash", "-c", 'source "$1"; acx_reap_orphan_pings', "bash", str(SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "ORPHAN_PING_STALE_SEC": "30",
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    lines = kill_log.read_text(encoding="utf-8").splitlines()
    pids = {line.split()[-1] for line in lines}
    assert pids == {"111"}
    assert "reaped 1 stale orphan ping probe(s)" in completed.stdout


def test_bounded_ping_under_job_control_reaps_real_child(tmp_path: Path) -> None:
    pidfile = tmp_path / "child.pid"
    helper = tmp_path / "hang.sh"
    _write_executable(
        helper,
        f"""#!/usr/bin/env bash
printf '%s\\n' "$$" >{shlex.quote(str(pidfile))}
exec sleep 30
""",
    )
    started = time.monotonic()
    completed = subprocess.run(
        [
            "bash",
            "-c",
            'set -m\nsource "$1"\nacx_run_bounded_ping "$2"\n',
            "bash",
            str(SCRIPT),
            str(helper),
        ],
        env={**os.environ, "PING_TIMEOUT_SEC": "1"},
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    elapsed = time.monotonic() - started
    assert completed.returncode == 124, completed.stderr
    assert elapsed < 5, f"job-control ping was not bounded: {elapsed:.1f}s"
    assert pidfile.exists(), "child pid was not recorded"
    child = int(pidfile.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and _pid_is_alive(child):
        time.sleep(0.02)
    assert not _pid_is_alive(child), (
        f"job-control ping leftover pid {child} still alive (ppid=1 leak)"
    )


def test_help_ignores_invalid_unrelated_knobs() -> None:
    completed = _run(
        "--help",
        env={"PING_TIMEOUT_SEC": "0", "ORPHAN_PING_STALE_SEC": "0"},
    )
    assert completed.returncode == 0, completed.stderr
    assert "Usage:" in completed.stderr


def test_reap_ignores_invalid_ping_timeout() -> None:
    completed = _run(
        "reap-orphan-pings",
        env={"PING_TIMEOUT_SEC": "0", "ORPHAN_PING_STALE_SEC": "30"},
    )
    assert completed.returncode == 0, completed.stderr
    assert "reaped" in completed.stdout


def test_ping_ignores_invalid_orphan_stale() -> None:
    completed = _run(
        "ping",
        "true",
        env={"PING_TIMEOUT_SEC": "1", "ORPHAN_PING_STALE_SEC": "0"},
    )
    assert completed.returncode == 0, completed.stderr


def test_unknown_command_ignores_invalid_knobs() -> None:
    completed = _run(
        "not-a-command",
        env={"PING_TIMEOUT_SEC": "0", "ORPHAN_PING_STALE_SEC": "0"},
    )
    assert completed.returncode == 2, completed.stderr
    assert "unknown command" in completed.stderr


def test_overlay_seam_contract(tmp_path: Path) -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "OVERLAY_SEAM_CONTRACT" in source
    assert "acx_run_bounded_ping" in source
    assert "acx_reap_orphan_pings" in source
    overlay = REPO_ROOT / "scripts/remote_agent.sh"
    if overlay.is_file():
        text = overlay.read_text(encoding="utf-8")
        assert "remote_agent_hygiene.sh" in text
        assert "acx_run_bounded_ping" in text
        assert "acx_reap_orphan_pings" in text
    fixture = tmp_path / "remote_agent.sh"
    fixture.write_text(
        "#!/usr/bin/env bash\n"
        "# Contract fixture for the plugin-managed overlay.\n"
        'source "$1"\n'
        "type acx_run_bounded_ping >/dev/null\n"
        "type acx_reap_orphan_pings >/dev/null\n"
        "acx_run_bounded_ping true\n"
        "acx_reap_orphan_pings\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["bash", str(fixture), str(SCRIPT)],
        env={**os.environ, "PING_TIMEOUT_SEC": "2", "ORPHAN_PING_STALE_SEC": "30"},
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert "reaped" in completed.stdout
    help_run = _run("--help")
    assert help_run.returncode == 0, help_run.stderr
    assert "ping [--]" in help_run.stderr
    assert "reap-orphan-pings" in help_run.stderr

