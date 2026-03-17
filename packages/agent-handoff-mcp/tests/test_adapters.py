from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from fastmcp.client import Client, PythonStdioTransport


def test_vscode_adapter_points_to_repo_local_launcher_and_doctor_runs() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config = json.loads((repo_root / ".vscode" / "mcp.json").read_text())

    server = config["servers"]["context-alt-text"]
    assert server["command"] == "python3"
    assert server["args"] == [
        "${workspaceFolder}/packages/agent-handoff-mcp/src/agent_handoff_mcp_launcher.py",
        "--workspace-root",
        "${workspaceFolder}",
        "--state-dir",
        "${workspaceFolder}/.task-state",
        "--current-task-path",
        "${workspaceFolder}/CURRENT_TASK.md",
        "--exports-dir",
        "${workspaceFolder}/.task-state/exports",
        "serve-stdio",
    ]

    result = subprocess.run(
        ["./scripts/mcp/mcp-server.sh", "doctor"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["workspace_root"] == str(repo_root)


def test_generic_stdio_adapter_launches_packaged_server(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    adapter = {
        "name": "agent-handoff",
        "command": sys.executable,
        "args": [str(launcher), "--workspace-root", str(repo_root), "serve-stdio"],
    }

    async def _run() -> list[str]:
        transport = PythonStdioTransport(
            script_path=Path(adapter["args"][0]),
            args=adapter["args"][1:],
            cwd=str(repo_root),
            python_cmd=adapter["command"],
            log_file=tmp_path / "generic-adapter.log",
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            return sorted(tool.name for tool in tools)

    tool_names = asyncio.run(_run())
    assert "get_handoff_state" in tool_names
    assert "list_review_findings" in tool_names
