from __future__ import annotations

import asyncio
from pathlib import Path

from fastmcp.client import Client, PythonStdioTransport


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
    assert "get_handoff_state" in tool_names
    assert "record_review_finding" in tool_names
    assert "handoff_close_check" in tool_names
    assert "record_lane_brief" in tool_names
    assert "list_lane_briefs" in tool_names
    assert "orchestrator_start" in tool_names
    assert "orchestrator_status" in tool_names
    assert "orchestrator_single_cycle" in tool_names
    assert "worker_start" in tool_names
    assert "worker_status" in tool_names
    assert "worker_resume" in tool_names
    assert "worker_stop" in tool_names
    assert "worker_start_all" in tool_names
    assert "run_structured_turn" in tool_names
