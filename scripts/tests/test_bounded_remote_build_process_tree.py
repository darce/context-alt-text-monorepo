from __future__ import annotations

import stat
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/deploy/lib/bounded-remote-build.sh"


def test_inner_watchdog_kills_process_group() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "acx_kill_tree" in source
    assert "setsid" in source
    assert 'kill -TERM -- "-$acx_pid"' in source
    assert 'kill -KILL -- "-$acx_pid"' in source


def test_kill_tree_reaps_a_synthetic_descendant(tmp_path: Path) -> None:
    marker = tmp_path / "descendant-lived"
    driver = tmp_path / "driver.sh"
    driver.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
acx_kill_tree() {{
  local acx_pid="$1"
  kill -TERM -- "-$acx_pid" 2>/dev/null || kill -TERM "$acx_pid" 2>/dev/null || true
  sleep 0.1
  kill -KILL -- "-$acx_pid" 2>/dev/null || kill -KILL "$acx_pid" 2>/dev/null || true
}}
setsid bash -c 'sleep 8; echo lived > "{marker}"' &
pid=$!
sleep 0.2
acx_kill_tree "$pid"
wait "$pid" 2>/dev/null || true
sleep 1
test ! -f "{marker}"
""",
        encoding="utf-8",
    )
    driver.chmod(driver.stat().st_mode | stat.S_IEXEC)
    completed = subprocess.run(["bash", str(driver)], capture_output=True, text=True, check=False, timeout=10)
    time.sleep(0.2)
    assert completed.returncode == 0, completed.stderr
    assert not marker.exists()
