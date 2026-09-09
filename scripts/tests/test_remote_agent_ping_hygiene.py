from __future__ import annotations

import os
import shlex
import stat
import subprocess
import time
from pathlib import Path

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


def test_etime_zero_padded_fields_parse_as_decimal() -> None:
    """ps etime zero-pads 08/09; bash $((08)) is invalid octal (TD-05)."""
    mmss = _etime("08:09")
    assert mmss.returncode == 0, mmss.stderr
    assert mmss.stdout.strip() == "489"

    hhmmss = _etime("08:09:08")
    assert hhmmss.returncode == 0, hhmmss.stderr
    assert hhmmss.stdout.strip() == "29348"

    with_days = _etime("1-08:09:08")
    assert with_days.returncode == 0, with_days.stderr
    assert with_days.stdout.strip() == "115748"

    under_a_minute = _etime("00:08")
    assert under_a_minute.returncode == 0, under_a_minute.stderr
    assert under_a_minute.stdout.strip() == "8"


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
