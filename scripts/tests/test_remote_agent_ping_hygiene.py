from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/remote_agent.sh"


def test_remote_agent_bounds_and_reaps_orphan_pings() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "reap_orphan_codex_pings" in text
    assert "PING_TIMEOUT_SEC" in text
    assert "PING_ORPHAN_AGE_SEC" in text
    assert 'TW="timeout -k 5 ${PING_TIMEOUT_SEC}"' in text
    assert "orphan-ping-hygiene" in text
    assert "ppid" in text and " = 1" in text


def test_user_slice_tasksmax_dropin_is_shipped() -> None:
    script = REPO_ROOT / "scripts/vm/install-user-slice-tasksmax.sh"
    text = script.read_text(encoding="utf-8")
    assert "TasksMax=4096" in text
    assert "user-${uid}.slice.d" in text
