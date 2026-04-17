"""Smoke tests verifying the orchestrator MCP package builds and registers the expected tools."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from agent_handoff_mcp.config import RuntimeConfig

from agent_orchestrator_mcp.api import build_orchestrator_mcp, run_tools_snapshot

EXPECTED_TOOL_COUNT = 16  # Slice C removes 28 deprecated registrations from the 44-tool additive surface


def _make_config() -> RuntimeConfig:
    td = tempfile.mkdtemp()
    p = Path(td)
    return RuntimeConfig(
        workspace_root=p,
        state_dir=p / ".task-state",
        db_path=p / ".task-state" / "handoff.db",
        current_task_path=p / "CURRENT_TASK.json",
        dashboard_path=p / "DASHBOARD.md",
        exports_dir=p / ".task-state" / "exports",
        artifact_db_path=p / ".task-state" / "mcp-artifacts.db",
    )


def test_build_orchestrator_mcp_returns_fastmcp():
    config = _make_config()
    mcp = build_orchestrator_mcp(config)
    assert mcp is not None


def test_orchestrator_tool_count():
    config = _make_config()
    mcp = build_orchestrator_mcp(config)
    # Count tools by inspecting the tool list function
    # FastMCP exposes tools via different APIs depending on version
    tool_count = 0
    if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
        tool_count = len(mcp._tool_manager._tools)
    elif hasattr(mcp, "list_tools"):
        import asyncio

        tools = asyncio.run(mcp.list_tools())
        tool_count = len(tools)
    assert tool_count == EXPECTED_TOOL_COUNT, f"Expected {EXPECTED_TOOL_COUNT} tools, got {tool_count}"


def test_orchestrator_registry_omits_removed_legacy_tool_names():
    config = _make_config()
    mcp = build_orchestrator_mcp(config)
    tool_names: set[str] = set()
    if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
        tool_names = set(mcp._tool_manager._tools)
    elif hasattr(mcp, "list_tools"):
        import asyncio

        tools = asyncio.run(mcp.list_tools())
        tool_names = {tool.name for tool in tools}
    assert "manage_worktree_lane" in tool_names
    assert "lane_communication" in tool_names
    assert "manage_orchestrator" in tool_names
    assert "manage_worker" in tool_names
    assert "upsert_worktree_lane" not in tool_names
    assert "record_lane_message" not in tool_names
    assert "record_lane_brief" not in tool_names
    assert "record_turn_metric" not in tool_names
    assert "record_worker_report" not in tool_names
    assert "upsert_plan_cursor" not in tool_names
    assert "orchestrator_start" not in tool_names
    assert "worker_start" not in tool_names


def test_orchestrator_has_lane_tools():
    config = _make_config()
    mcp = build_orchestrator_mcp(config)
    # Verify the mcp object was built without error
    assert mcp is not None


def test_orchestrator_has_daemon_tools():
    """Orchestration wrapper functions should be importable."""
    from agent_orchestrator_mcp.api import (
        manage_orchestrator,
        manage_worker,
    )

    assert callable(manage_orchestrator)
    assert callable(manage_worker)


def test_orchestrator_crud_tools_importable():
    """The public wrapper-era CRUD tools should remain importable."""
    from agent_orchestrator_mcp.api import (
        get_lane_activity,
        lane_communication,
        manage_worktree_lane,
        plan_cursor,
        turn_metrics,
        worker_reports,
    )

    assert callable(lane_communication)
    assert callable(manage_worktree_lane)
    assert callable(plan_cursor)
    assert callable(turn_metrics)
    assert callable(worker_reports)


def test_tools_snapshot_counts_across_phases(tmp_path: Path) -> None:
    config = _make_config()
    current_output = tmp_path / "current.json"
    current_snapshot = run_tools_snapshot(config, phase="current", output_path=current_output)
    assert current_snapshot["tool_count"] == 16
    assert current_output.exists()

    phase_counts = {
        "a1": 38,
        "a2": 39,
        "a3": 44,
    }
    for phase, expected in phase_counts.items():
        snapshot = run_tools_snapshot(config, phase=phase)
        assert snapshot["tool_count"] == expected, f"{phase} should expose {expected} tools"


def test_orchestration_dir_points_to_orchestration():
    """_orchestration_dir() should resolve to the package-local orchestration directory."""
    from agent_orchestrator_mcp.api import _orchestration_dir

    scripts_dir = _orchestration_dir()
    assert scripts_dir.exists(), f"orchestration dir not found: {scripts_dir}"
    assert (scripts_dir / "orchestrator_daemon.py").exists()


def test_dashboard_extension_lane_health_and_worker_status(tmp_path: Path) -> None:
    """AHMCP-23: lane_worker_extension contributes Lane Health + Worker Status to DASHBOARD.md.

    Registers the real ``lane_worker_extension`` from the orchestrator package,
    seeds the handoff DB with a lane row and a submitted worker-report row,
    then calls ``generate_dashboard_md(write_file=False)`` and asserts both
    extension sections appear in the output markdown.
    """
    from agent_handoff_mcp.config import RuntimeConfig
    from agent_handoff_mcp.dashboard_rendering import (
        clear_dashboard_extensions,
        register_dashboard_extension,
    )
    from agent_handoff_mcp.shared_schema import _get_db_connection

    from agent_orchestrator_mcp.api import configure_runtime, generate_dashboard_md
    from agent_orchestrator_mcp.orchestration.dashboard_extension import lane_worker_extension

    # Isolated runtime
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir()
    runtime = RuntimeConfig(
        workspace_root=tmp_path,
        state_dir=state_dir,
        db_path=state_dir / "handoff.db",
        current_task_path=tmp_path / "CURRENT_TASK.json",
        dashboard_path=tmp_path / "DASHBOARD.md",
        exports_dir=state_dir / "exports",
        artifact_db_path=state_dir / "mcp-artifacts.db",
    )
    configure_runtime(runtime)

    # Bootstrap the DB schema by opening a managed connection (which runs migrations)
    # then seed lane and worker-report rows.
    with _get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO worktree_lanes
            (task_ref, lane_id, title, objective, worktree_path, branch,
             owner_agent, model, backend, reasoning_effort, status, created_at, updated_at)
            VALUES ('TEST-1', 'frontend', 'Frontend lane', 'Build UI', '/tmp/wt', 'feature/frontend',
                    'claude', 'claude-sonnet-4', 'local', 'medium', 'active',
                    datetime('now'), datetime('now'))
            """
        )
        conn.execute(
            """
            INSERT INTO worker_reports
            (task_ref, lane_id, session, summary, changed_files_json, test_commands_json,
             blockers_json, merge_ready, status, agent, branch, commit_sha, created_at)
            VALUES ('TEST-1', 'frontend', 'sess-1', 'Implemented UI components', '[]', '[]',
                    '[]', 1, 'submitted', 'claude', 'feature/frontend', 'abc1234', datetime('now'))
            """
        )

    # Register only our extension for this test
    clear_dashboard_extensions()
    register_dashboard_extension(lane_worker_extension)

    try:
        result = generate_dashboard_md(write_file=False)
    finally:
        # Restore the module-level registration
        clear_dashboard_extensions()
        register_dashboard_extension(lane_worker_extension)

    assert result["ok"] is True
    md = result["markdown"]
    assert md is not None

    # Lane Health section
    assert "LANE HEALTH" in md
    assert "frontend" in md
    assert "active" in md

    # Worker Status section
    assert "WORKER STATUS" in md
    assert "Implemented UI components" in md
    assert "merge-ready" in md
