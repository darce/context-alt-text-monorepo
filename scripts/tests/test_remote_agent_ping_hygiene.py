from __future__ import annotations

import os
import shlex
import stat
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/remote_agent_hygiene.sh"
TRACKED_WRAPPER = REPO_ROOT / "scripts/remote_agent.sh"


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


def test_tracked_remote_agent_wrapper_rejects_zero_timeout() -> None:
    assert TRACKED_WRAPPER.is_file()
    completed = subprocess.run(
        ["bash", str(TRACKED_WRAPPER), "ping", "true"],
        env={**os.environ, "PING_TIMEOUT_SEC": "0"},
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
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
    _write_executable(
        fake_bin / "kill",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >>{shlex.quote(str(kill_log))}
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
    assert kill_log.read_text(encoding="utf-8").splitlines() == ["-TERM 111"]
    assert "reaped 1 stale orphan ping probe(s)" in completed.stdout


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
