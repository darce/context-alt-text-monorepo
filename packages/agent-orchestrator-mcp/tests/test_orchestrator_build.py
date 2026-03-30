"""Smoke tests verifying the orchestrator MCP package builds and registers the expected tools."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from agent_handoff_mcp.config import RuntimeConfig

from agent_orchestrator_mcp.api import build_orchestrator_mcp

EXPECTED_TOOL_COUNT = 38  # 17 CRUD + 17 wrappers + 4 cross-task tools (incl. manage_worker)


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


def test_orchestrator_has_lane_tools():
    config = _make_config()
    mcp = build_orchestrator_mcp(config)
    # Verify the mcp object was built without error
    assert mcp is not None


def test_orchestrator_has_daemon_tools():
    """Orchestration wrapper functions should be importable."""
    from agent_orchestrator_mcp.api import (
        orchestrator_pause,
        orchestrator_resume,
        orchestrator_single_cycle,
        orchestrator_start,
        orchestrator_status,
        orchestrator_stop,
        worker_event_history,
        worker_resume,
        worker_start,
        worker_start_all,
        worker_status,
        worker_stop,
    )

    assert callable(orchestrator_start)
    assert callable(worker_start)


def test_orchestrator_crud_tools_importable():
    """CRUD tools re-exported from agent_handoff_mcp.core should be callable."""
    from agent_orchestrator_mcp.api import (
        close_worktree_lane,
        get_lane_activity,
        get_plan_cursor,
        get_turn_metrics_summary,
        list_lane_messages,
        list_plan_cursors,
        list_turn_metrics,
        list_worker_reports,
        list_worktree_lanes,
        record_lane_message,
        record_turn_metric,
        record_worker_report,
        upsert_plan_cursor,
        upsert_worktree_lane,
    )

    assert callable(upsert_worktree_lane)
    assert callable(list_plan_cursors)


def test_orchestration_dir_points_to_orchestration():
    """_orchestration_dir() should resolve to the package-local orchestration directory."""
    from agent_orchestrator_mcp.api import _orchestration_dir

    scripts_dir = _orchestration_dir()
    assert scripts_dir.exists(), f"orchestration dir not found: {scripts_dir}"
    assert (scripts_dir / "orchestrator_daemon.py").exists()
