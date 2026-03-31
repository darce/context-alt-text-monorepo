from __future__ import annotations

import asyncio
from pathlib import Path

from fastmcp.client import Client, PythonStdioTransport

# Core profile tools that must always be present in the default (core) launch.
_CORE_TOOLS = {
    "get_handoff_state",
    "set_handoff_state",
    "record_decision",
    "update_next_actions",
    "record_test_result",
    "report_blocker",
    "record_review_finding",
    "batch_record_review_findings",
    "update_review_finding",
    "list_review_findings",
    "record_review_run",
    "list_review_runs",
    "handoff_close_check",
    "generate_current_task_md",
    "load_session",
    "close_slice",
}

# Extended tools that must NOT appear in the default (core) profile.
_EXTENDED_ONLY_TOOLS = {
    "list_next_actions",
    "get_review_coverage",
    "audit_decision_ids",
    "export_handoff_state",
    "import_handoff_state",
    "archive_task_state",
    "record_artifact",
    "search_artifacts",
    "get_artifact",
    "purge_artifacts",
    "search_handoff",
}


def test_stdio_server_lists_handoff_tools(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    async def _run() -> list[str]:
        transport = PythonStdioTransport(
            script_path=launcher,
            args=["--workspace-root", str(repo_root), "serve-stdio"],
            cwd=str(repo_root),
            log_file=tmp_path / "stdio-smoke.log",
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            return sorted(tool.name for tool in tools)

    tool_names = asyncio.run(_run())
    # Default launch uses core profile — all core tools present.
    assert "get_handoff_state" in tool_names
    assert "record_review_finding" in tool_names
    assert "handoff_close_check" in tool_names
    assert "load_session" in tool_names
    assert "close_slice" in tool_names
    # orchestration tools moved to agent-orchestrator-mcp
    assert "record_lane_brief" not in tool_names
    assert "orchestrator_start" not in tool_names
    assert "worker_start" not in tool_names
    assert "run_structured_turn" not in tool_names


def test_stdio_core_profile_excludes_extended_tools(tmp_path: Path) -> None:
    """Default (core) profile must include all 16 core tools and exclude all 11 extended."""
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    async def _run() -> set[str]:
        transport = PythonStdioTransport(
            script_path=launcher,
            args=["--workspace-root", str(repo_root), "serve-stdio"],
            cwd=str(repo_root),
            log_file=tmp_path / "core-profile-smoke.log",
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    tool_names = asyncio.run(_run())
    missing_core = _CORE_TOOLS - tool_names
    assert not missing_core, f"Core tools missing from default profile: {missing_core}"
    present_extended = _EXTENDED_ONLY_TOOLS & tool_names
    assert not present_extended, f"Extended tools incorrectly present in core profile: {present_extended}"
    assert len(tool_names) == 16


def test_stdio_full_profile_exposes_all_27_tools(tmp_path: Path) -> None:
    """--tool-profile full must expose all 27 tools."""
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    async def _run() -> set[str]:
        transport = PythonStdioTransport(
            script_path=launcher,
            args=["--workspace-root", str(repo_root), "--tool-profile", "full", "serve-stdio"],
            cwd=str(repo_root),
            log_file=tmp_path / "full-profile-smoke.log",
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    tool_names = asyncio.run(_run())
    assert _CORE_TOOLS <= tool_names, f"Core tools missing from full profile: {_CORE_TOOLS - tool_names}"
    assert _EXTENDED_ONLY_TOOLS <= tool_names, (
        f"Extended tools missing from full profile: {_EXTENDED_ONLY_TOOLS - tool_names}"
    )
    assert len(tool_names) == 27
