"""Tests for the E17-10 Slice 4 follow-up:
- one-shot WARNING when any daemon starts
- event-driven rework design note exists
- TODO(E17-10-REWORK) anchors at the named poll sites
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DESIGN_NOTE_PATH = (
    PACKAGE_ROOT / "docs" / "reworks" / "event-driven-daemon-design-note.md"
)
ORCHESTRATOR_DAEMON_PATH = (
    PACKAGE_ROOT
    / "src"
    / "agent_orchestrator_mcp"
    / "orchestration"
    / "orchestrator_daemon.py"
)
WORKER_DAEMON_PATH = (
    PACKAGE_ROOT
    / "src"
    / "agent_orchestrator_mcp"
    / "orchestration"
    / "worker_daemon.py"
)
DESIGN_NOTE_REL = (
    "packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md"
)


# ---------------------------------------------------------------------------
# Warning helper
# ---------------------------------------------------------------------------


def _import_helper():
    from agent_orchestrator_mcp.orchestration import daemon_startup

    daemon_startup._reset_emitted_for_tests()
    return daemon_startup


def test_emit_daemon_startup_warning_logs_once_per_kind(caplog: pytest.LogCaptureFixture) -> None:
    helper = _import_helper()
    with caplog.at_level(logging.WARNING, logger="agent_orchestrator_mcp.daemon_startup"):
        helper.emit_daemon_startup_warning("orchestrator", poll_interval=60)
        helper.emit_daemon_startup_warning("orchestrator", poll_interval=60)
        helper.emit_daemon_startup_warning("worker", poll_interval=30)
        helper.emit_daemon_startup_warning("worker", poll_interval=30)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2, f"expected one warning per daemon_kind, got {warnings!r}"


def test_emit_daemon_startup_warning_message_contents(caplog: pytest.LogCaptureFixture) -> None:
    helper = _import_helper()
    with caplog.at_level(logging.WARNING, logger="agent_orchestrator_mcp.daemon_startup"):
        helper.emit_daemon_startup_warning("orchestrator", poll_interval=60)
        helper.emit_daemon_startup_warning("worker", poll_interval=30)

    assert len(caplog.records) >= 2
    orch_msg = next(r.getMessage() for r in caplog.records if "orchestrator" in r.getMessage())
    worker_msg = next(r.getMessage() for r in caplog.records if "worker" in r.getMessage())

    for msg, interval in ((orch_msg, "60"), (worker_msg, "30")):
        assert "daemon enabled" in msg
        assert f"poll_interval={interval}s" in msg
        assert "MCP queries/cycle" in msg
        assert "may consume significant agent tokens" in msg
        assert DESIGN_NOTE_REL in msg
        # No invented tokens/hour figure (PA-05 in the task plan).
        assert not re.search(r"tokens?\s*(per\s*hour|/\s*hour|/h\b)", msg, re.IGNORECASE), (
            f"warning must not invent a tokens/hour figure: {msg!r}"
        )

    assert "lane_prompt.py --check" in worker_msg


# ---------------------------------------------------------------------------
# Design note doc
# ---------------------------------------------------------------------------


def test_event_driven_design_note_exists_and_enumerates_alternatives() -> None:
    assert DESIGN_NOTE_PATH.is_file(), f"missing design note at {DESIGN_NOTE_PATH}"
    text = DESIGN_NOTE_PATH.read_text(encoding="utf-8")

    # Four alternatives required by the plan.
    for needle in (
        "sqlite",
        "update_hook",
        "filesystem watcher",
        "unix-domain",
        "hybrid",
    ):
        assert needle.lower() in text.lower(), f"design note missing alternative anchor: {needle}"

    # Symbolic anchors required by the plan.
    for anchor in (
        "orchestrator_loop",
        "_worker_management_phase",
        "_poll_merge_ready_lanes",
        "_dispatch_phase",
        "_guidance_phase",
        "worker_loop",
        "_poll_phase",
        "poll_lane_state",
        "OrchestratorLock",
        "WorkerLock",
    ):
        assert anchor in text, f"design note missing symbolic anchor: {anchor}"


# ---------------------------------------------------------------------------
# TODO anchors at sleep sites
# ---------------------------------------------------------------------------


def _lines_with_todo_above_pattern(path: Path, pattern: str) -> list[int]:
    """Return 1-based line numbers of `pattern` matches that have a
    TODO(E17-10-REWORK) comment within the previous 5 lines."""
    lines = path.read_text(encoding="utf-8").splitlines()
    hits: list[int] = []
    for idx, line in enumerate(lines):
        if pattern in line:
            window = lines[max(0, idx - 5) : idx]
            if any("TODO(E17-10-REWORK)" in w for w in window):
                hits.append(idx + 1)
    return hits


def _all_lines_with_pattern(path: Path, pattern: str) -> list[int]:
    return [
        i + 1
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines())
        if pattern in line
    ]


def test_orchestrator_main_loop_sleep_has_rework_todo() -> None:
    sleep_lines = _all_lines_with_pattern(ORCHESTRATOR_DAEMON_PATH, "time.sleep(poll_interval)")
    assert sleep_lines, "expected at least one time.sleep(poll_interval) site"
    annotated = _lines_with_todo_above_pattern(ORCHESTRATOR_DAEMON_PATH, "time.sleep(poll_interval)")
    # The plan requires the main-loop sleep specifically. We assert ALL three
    # poll-interval sleeps in this module are anchored, since they all
    # contribute to the same per-cycle token cost the rework would address.
    assert set(annotated) == set(sleep_lines), (
        f"orchestrator sleep sites missing TODO(E17-10-REWORK): "
        f"sleep_lines={sleep_lines} annotated={annotated}"
    )


def test_worker_loop_sleep_sites_have_rework_todo() -> None:
    sleep_lines = _all_lines_with_pattern(WORKER_DAEMON_PATH, "time.sleep(cfg.poll_interval)")
    assert sleep_lines, "expected at least one time.sleep(cfg.poll_interval) site"
    annotated = _lines_with_todo_above_pattern(WORKER_DAEMON_PATH, "time.sleep(cfg.poll_interval)")
    assert set(annotated) == set(sleep_lines), (
        f"worker_loop sleep sites missing TODO(E17-10-REWORK): "
        f"sleep_lines={sleep_lines} annotated={annotated}"
    )


def test_rework_todo_references_design_note_path() -> None:
    for path in (ORCHESTRATOR_DAEMON_PATH, WORKER_DAEMON_PATH):
        text = path.read_text(encoding="utf-8")
        assert "TODO(E17-10-REWORK)" in text, f"{path} missing TODO(E17-10-REWORK)"
        assert DESIGN_NOTE_REL in text, (
            f"{path} TODO must cite the design note path {DESIGN_NOTE_REL!r}"
        )
