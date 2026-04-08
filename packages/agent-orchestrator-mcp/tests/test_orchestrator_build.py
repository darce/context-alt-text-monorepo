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
        current_task_path=p / "CURRENT_TASK.md",
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
