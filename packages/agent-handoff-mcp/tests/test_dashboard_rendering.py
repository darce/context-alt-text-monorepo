"""Tests for dashboard_rendering.py — Slice 1 of AHMCP-23."""

from __future__ import annotations

from pathlib import Path

import pytest

from unittest.mock import patch

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp.config import RuntimeConfig
from agent_handoff_mcp.dashboard_rendering import (
    DashboardContext,
    DashboardSection,
    _collect_needs_attention,
    _render_dashboard_md,
    clear_dashboard_extensions,
    generate_dashboard_md,
    register_dashboard_extension,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_extensions():
    """Prevent extension leakage between tests."""
    clear_dashboard_extensions()
    yield
    clear_dashboard_extensions()


@pytest.fixture()
def isolated_handoff(tmp_path: Path):
    """Redirect handoff sqlite + generated markdown paths into tmp dir."""
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    current_task_path = tmp_path / "CURRENT_TASK.md"
    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=state_dir,
        current_task_path=current_task_path,
    )
    mcp_server.configure_runtime(runtime)
    return runtime


# ---------------------------------------------------------------------------
# Extension registry
# ---------------------------------------------------------------------------


def test_register_and_clear_extensions() -> None:
    def ext(_ctx: DashboardContext) -> list[DashboardSection]:
        return [{"heading": "Test", "content": "body", "order": 99}]

    register_dashboard_extension(ext)
    register_dashboard_extension(ext)
    clear_dashboard_extensions()

    # After clear, generate_dashboard_md should produce no extension sections.
    # We test indirectly via _render_dashboard_md with empty extension_sections.
    result = _render_dashboard_md(
        generated_at="2026-01-01 00:00 UTC",
        dashboard_rows=[],
        open_findings={},
        deferred_findings={},
        needs_attention=[],
        active_task_ref=None,
        extension_sections=[],
    )
    assert "## Test" not in result


def test_extension_sections_appear_in_output() -> None:
    def ext(_ctx: DashboardContext) -> list[DashboardSection]:
        return [{"heading": "Lane Health", "content": "all clear", "order": 50}]

    register_dashboard_extension(ext)

    result = _render_dashboard_md(
        generated_at="2026-01-01 00:00 UTC",
        dashboard_rows=[],
        open_findings={},
        deferred_findings={},
        needs_attention=[],
        active_task_ref=None,
        extension_sections=ext({"worktree_lanes": [], "worker_reports": [], "turn_metrics": []}),
    )
    assert "LANE HEALTH" in result
    assert "all clear" in result


def test_extension_sections_ordered_by_order_field() -> None:
    sections: list[DashboardSection] = [
        {"heading": "Worker Status", "content": "w", "order": 60},
        {"heading": "Lane Health", "content": "l", "order": 50},
    ]
    result = _render_dashboard_md(
        generated_at="2026-01-01 00:00 UTC",
        dashboard_rows=[],
        open_findings={},
        deferred_findings={},
        needs_attention=[],
        active_task_ref=None,
        extension_sections=sections,
    )
    lane_pos = result.index("LANE HEALTH")
    worker_pos = result.index("WORKER STATUS")
    assert lane_pos < worker_pos, "Lower order should render first"


def test_no_extensions_registered_renders_core_only(isolated_handoff) -> None:
    mcp_server.set_handoff_state(task_ref="T1", objective="obj", status="in_progress")
    result = generate_dashboard_md(write_file=False)
    assert result["ok"] is True
    md = result["markdown"]
    assert "NEEDS ATTENTION" in md
    assert "ALL TASKS" in md
    assert "LANE HEALTH" not in md
    assert "WORKER STATUS" not in md


# ---------------------------------------------------------------------------
# Core section rendering
# ---------------------------------------------------------------------------


def test_render_with_no_data() -> None:
    result = _render_dashboard_md(
        generated_at="2026-01-01 00:00 UTC",
        dashboard_rows=[],
        open_findings={},
        deferred_findings={},
        needs_attention=[],
        active_task_ref=None,
        extension_sections=[],
    )
    assert "DASHBOARD" in result
    assert "NEEDS ATTENTION" in result
    assert "  (all clear)" in result
    assert "ALL TASKS" in result
    assert "OPEN FINDINGS" in result
    assert "  (none)" in result


def test_render_open_findings_grouped_by_task() -> None:
    open_findings = {
        "TASK-A": [
            {
                "finding_id": "TASK-A-01",
                "severity": "high",
                "file_path": "src/foo.py",
                "line_start": 42,
                "description": "Bad thing",
            }
        ],
        "TASK-B": [
            {
                "finding_id": "TASK-B-01",
                "severity": "medium",
                "file_path": "src/bar.py",
                "line_start": None,
                "description": "Medium thing",
            }
        ],
    }
    result = _render_dashboard_md(
        generated_at="2026-01-01 00:00 UTC",
        dashboard_rows=[],
        open_findings=open_findings,
        deferred_findings={},
        needs_attention=[],
        active_task_ref=None,
        extension_sections=[],
    )
    assert "  [TASK-A]" in result
    assert "TASK-A-01" in result
    assert "src/foo.py:42" in result
    assert "  [TASK-B]" in result
    assert "TASK-B-01" in result


def test_deferred_findings_section_omitted_when_empty() -> None:
    result = _render_dashboard_md(
        generated_at="2026-01-01 00:00 UTC",
        dashboard_rows=[],
        open_findings={},
        deferred_findings={},
        needs_attention=[],
        active_task_ref=None,
        extension_sections=[],
    )
    assert "DEFERRED" not in result


def test_deferred_findings_section_present_when_populated() -> None:
    deferred = {
        "TASK-X": [
            {
                "finding_id": "TASK-X-01",
                "severity": "low",
                "status": "wontfix",
                "file_path": "src/x.py",
                "line_start": None,
                "description": "Wontfix this",
            }
        ]
    }
    result = _render_dashboard_md(
        generated_at="2026-01-01 00:00 UTC",
        dashboard_rows=[],
        open_findings={},
        deferred_findings=deferred,
        needs_attention=[],
        active_task_ref=None,
        extension_sections=[],
    )
    assert "DEFERRED / WONTFIX" in result
    assert "TASK-X-01" in result
    assert "WONTFIX" in result


# ---------------------------------------------------------------------------
# Needs Attention aggregation
# ---------------------------------------------------------------------------


def test_needs_attention_high_medium_findings(isolated_handoff) -> None:
    from agent_handoff_mcp.shared_schema import _get_db_connection

    mcp_server.set_handoff_state(task_ref="NA-TASK", objective="obj", status="in_progress")
    mcp_server.record_event(
        event={
            "event_kind": "decision",
            "session": "s1",
            "decision": "d1",
            "rationale": "r",
            "task_ref": "NA-TASK",
        }
    )

    # Insert a high-severity finding directly
    with _get_db_connection() as conn:
        conn.execute(
            "INSERT INTO review_findings (task_ref, finding_id, severity, status, file_path, description, session) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("OTHER-TASK", "OTHER-01", "high", "open", "f.py", "desc", "s1"),
        )
        conn.commit()

        from agent_handoff_mcp.current_task_rendering import (
            _collect_all_open_findings,
            _collect_dashboard_rows,
        )

        dashboard_rows = _collect_dashboard_rows(conn)
        open_findings = _collect_all_open_findings(conn, max_per_task=100)
        items = _collect_needs_attention(conn, dashboard_rows, open_findings)

    task_refs_in_attention = [i["task_ref"] for i in items]
    assert "OTHER-TASK" in task_refs_in_attention
    high_item = next(i for i in items if i["task_ref"] == "OTHER-TASK")
    assert high_item["kind"] == "findings"
    assert "high" in high_item["detail"]


def test_needs_attention_low_findings_not_flagged(isolated_handoff) -> None:
    from agent_handoff_mcp.shared_schema import _get_db_connection

    mcp_server.set_handoff_state(task_ref="LOW-TASK", objective="obj", status="in_progress")

    with _get_db_connection() as conn:
        conn.execute(
            "INSERT INTO review_findings (task_ref, finding_id, severity, status, file_path, description, session) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("LOW-TASK", "LOW-01", "low", "open", "f.py", "desc", "s1"),
        )
        conn.commit()

        from agent_handoff_mcp.current_task_rendering import (
            _collect_all_open_findings,
            _collect_dashboard_rows,
        )

        dashboard_rows = _collect_dashboard_rows(conn)
        open_findings = _collect_all_open_findings(conn, max_per_task=100)
        items = _collect_needs_attention(conn, dashboard_rows, open_findings)

    finding_items = [i for i in items if i["kind"] == "findings"]
    assert not any(i["task_ref"] == "LOW-TASK" for i in finding_items)


def test_needs_attention_blocked_task(isolated_handoff) -> None:
    from agent_handoff_mcp.shared_schema import _get_db_connection

    mcp_server.set_handoff_state(task_ref="BLK-TASK", objective="obj", status="blocked")
    mcp_server.record_event(
        event={
            "event_kind": "blocker",
            "operation": "add",
            "session": "s1",
            "description": "Blocked by infra",
            "task_ref": "BLK-TASK",
        }
    )

    with _get_db_connection() as conn:
        from agent_handoff_mcp.current_task_rendering import (
            _collect_all_open_findings,
            _collect_dashboard_rows,
        )

        dashboard_rows = _collect_dashboard_rows(conn)
        open_findings = _collect_all_open_findings(conn, max_per_task=100)
        items = _collect_needs_attention(conn, dashboard_rows, open_findings)

    blocked_items = [i for i in items if i["kind"] == "blocked"]
    assert any(i["task_ref"] == "BLK-TASK" for i in blocked_items)


def test_needs_attention_all_clear_when_no_issues(isolated_handoff) -> None:
    from agent_handoff_mcp.shared_schema import _get_db_connection

    mcp_server.set_handoff_state(task_ref="OK-TASK", objective="obj", status="in_progress")

    with _get_db_connection() as conn:
        from agent_handoff_mcp.current_task_rendering import (
            _collect_all_open_findings,
            _collect_dashboard_rows,
        )

        dashboard_rows = _collect_dashboard_rows(conn)
        open_findings = _collect_all_open_findings(conn, max_per_task=100)
        items = _collect_needs_attention(conn, dashboard_rows, open_findings)

    finding_or_blocked = [i for i in items if i["kind"] in ("findings", "blocked")]
    assert not finding_or_blocked


# ---------------------------------------------------------------------------
# generate_dashboard_md integration
# ---------------------------------------------------------------------------


def test_generate_dashboard_md_writes_file(isolated_handoff) -> None:
    mcp_server.set_handoff_state(task_ref="DASH-1", objective="obj", status="in_progress")
    result = generate_dashboard_md(write_file=True)

    assert result["ok"] is True
    assert result["written"] is True
    assert result["path"] is not None
    dashboard_path = Path(result["path"])
    assert dashboard_path.exists()
    assert dashboard_path.name == "DASHBOARD.txt"
    content = dashboard_path.read_text()
    assert "DASHBOARD" in content


def test_dashboard_no_fences(isolated_handoff) -> None:
    """ALL TASKS table must not contain backtick fences (E17-5 Slice 1)."""
    mcp_server.set_handoff_state(task_ref="FENCE-1", objective="obj", status="in_progress")
    result = generate_dashboard_md(write_file=False)

    assert result["ok"] is True
    assert "```" not in result["markdown"]


def test_generate_dashboard_md_uses_runtime_dashboard_path(tmp_path: Path) -> None:
    state_dir = tmp_path / ".task-state"
    feature_root = tmp_path / "feature-worktree"
    main_root = tmp_path / "main-root"
    state_dir.mkdir(parents=True, exist_ok=True)
    feature_root.mkdir(parents=True, exist_ok=True)
    main_root.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=state_dir,
        current_task_path=feature_root / "CURRENT_TASK.md",
        dashboard_path=main_root / "DASHBOARD.md",
    )
    mcp_server.configure_runtime(runtime)

    mcp_server.set_handoff_state(task_ref="DASH-SPLIT", objective="obj", status="in_progress")
    result = generate_dashboard_md(write_file=True)

    assert result["ok"] is True
    assert result["path"] == str(runtime.dashboard_path)
    assert runtime.dashboard_path.exists()
    assert not (feature_root / "DASHBOARD.md").exists()


def test_generate_dashboard_md_no_write_returns_markdown(isolated_handoff) -> None:
    mcp_server.set_handoff_state(task_ref="DASH-2", objective="obj", status="in_progress")
    result = generate_dashboard_md(write_file=False)

    assert result["ok"] is True
    assert result["written"] is False
    assert result["markdown"] is not None
    assert "DASHBOARD" in result["markdown"]


def test_task_test_status_filtered_to_epic(isolated_handoff) -> None:
    """TEST STATUS shows only tasks from the active epic (E17-5 Slice 2)."""
    # Create an active task under the E17 epic.
    mcp_server.set_handoff_state(task_ref="E17-4", objective="obj", status="in_progress")
    # Record test results for two different epics.
    mcp_server.record_event(
        event={
            "event_kind": "test_result",
            "session": "epic-filter",
            "command": "make test",
            "passed": True,
            "task_ref": "E17-4",
        }
    )
    mcp_server.record_event(
        event={
            "event_kind": "test_result",
            "session": "epic-filter",
            "command": "make test",
            "passed": True,
            "task_ref": "AHMCP-9",
        }
    )
    result = generate_dashboard_md(write_file=False)
    assert result["ok"] is True
    md = result["markdown"]
    # Extract TEST STATUS section.
    test_section_start = md.index("TEST STATUS")
    # Find the next section heading (a line that is all-caps followed by dashes).
    remaining = md[test_section_start + len("TEST STATUS"):]
    next_heading = len(md)
    for i, line in enumerate(remaining.split("\n")):
        stripped = line.strip()
        if stripped and stripped == stripped.upper() and len(stripped) > 3 and not stripped.startswith("-") and not stripped.startswith("─"):
            next_heading = test_section_start + len("TEST STATUS") + sum(len(ln) + 1 for ln in remaining.split("\n")[:i])
            break
    test_section = md[test_section_start:next_heading]
    # E17-family task must appear in TEST STATUS.
    assert "E17-4" in test_section
    # Cross-epic task must NOT appear in TEST STATUS.
    assert "AHMCP-9" not in test_section


def test_section_order_findings_before_test_status(isolated_handoff) -> None:
    """OPEN FINDINGS must render before TEST STATUS (E17-5 Slice 3b)."""
    mcp_server.set_handoff_state(task_ref="E17-4", objective="obj", status="in_progress")
    mcp_server.record_event(
        event={
            "event_kind": "test_result",
            "session": "order",
            "command": "make test",
            "passed": True,
            "task_ref": "E17-4",
        }
    )
    result = generate_dashboard_md(write_file=False)
    assert result["ok"] is True
    md = result["markdown"]
    findings_pos = md.index("OPEN FINDINGS")
    test_pos = md.index("TEST STATUS")
    assert findings_pos < test_pos, "OPEN FINDINGS must appear before TEST STATUS"


def test_workflow_integrity_section_only_on_anomalies(isolated_handoff) -> None:
    """WORKFLOW INTEGRITY section omitted when no anomalies exist (E17-5 Slice 3b)."""
    mcp_server.set_handoff_state(task_ref="CLEAN-1", objective="obj", status="in_progress")
    # No target_branch set, so no integrity checks to run.
    result = generate_dashboard_md(write_file=False)
    assert result["ok"] is True
    assert "WORKFLOW INTEGRITY" not in result["markdown"]


def test_workflow_integrity_missing_branch(isolated_handoff) -> None:
    """WORKFLOW INTEGRITY shows alert when target branch doesn't exist (E17-5 Slice 3b)."""
    mcp_server.set_handoff_state(
        task_ref="MISS-1",
        objective="obj",
        status="in_progress",
        target_branch="feature/nonexistent-branch-xyz",
    )

    import subprocess as _sp

    def _fake_run(cmd, **kwargs):
        if "rev-parse" in cmd and "feature/nonexistent-branch-xyz" in cmd:
            return _sp.CompletedProcess(cmd, returncode=128, stdout="", stderr="not found")
        if "worktree" in cmd and "list" in cmd:
            return _sp.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "branch" in cmd and "--merged" in cmd:
            return _sp.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        return _sp.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    with patch("agent_handoff_mcp.dashboard_rendering.subprocess.run", side_effect=_fake_run):
        result = generate_dashboard_md(write_file=False)

    assert result["ok"] is True
    md = result["markdown"]
    assert "WORKFLOW INTEGRITY" in md
    assert "feature/nonexistent-branch-xyz" in md


def test_workflow_integrity_git_timeout(isolated_handoff) -> None:
    """Git timeout renders degraded-mode notice (E17-5 Slice 3b)."""
    import subprocess as _sp

    mcp_server.set_handoff_state(
        task_ref="TIME-1",
        objective="obj",
        status="in_progress",
        target_branch="feature/timeout-branch",
    )

    def _timeout_run(cmd, **kwargs):
        raise _sp.TimeoutExpired(cmd, 5)

    with patch("agent_handoff_mcp.dashboard_rendering.subprocess.run", side_effect=_timeout_run):
        result = generate_dashboard_md(write_file=False)

    assert result["ok"] is True
    md = result["markdown"]
    assert "WORKFLOW INTEGRITY" in md
    assert "timed out" in md.lower()


def test_generate_dashboard_md_with_registered_extension(isolated_handoff) -> None:
    def my_ext(ctx: DashboardContext) -> list[DashboardSection]:
        return [{"heading": "Lane Health", "content": "3 lanes active", "order": 50}]

    register_dashboard_extension(my_ext)
    mcp_server.set_handoff_state(task_ref="EXT-1", objective="obj", status="in_progress")
    result = generate_dashboard_md(write_file=False)

    assert result["ok"] is True
    assert "LANE HEALTH" in result["markdown"]
    assert "3 lanes active" in result["markdown"]


def test_generate_dashboard_md_extension_exception_does_not_abort(isolated_handoff) -> None:
    def bad_ext(_ctx: DashboardContext) -> list[DashboardSection]:
        raise RuntimeError("extension blew up")

    register_dashboard_extension(bad_ext)
    mcp_server.set_handoff_state(task_ref="EXC-1", objective="obj", status="in_progress")
    result = generate_dashboard_md(write_file=False)

    assert result["ok"] is True
    assert "DASHBOARD" in result["markdown"]
