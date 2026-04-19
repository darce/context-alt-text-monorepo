from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from fastmcp.client import Client, PythonStdioTransport


@pytest.mark.timeout(60)
def test_vscode_adapter_points_to_installed_entrypoint_and_doctor_runs() -> None:
    """The vscode adapter wires up the right entrypoint and `doctor` reports
    a sane workspace_root.

    AHMCP-16-BR-01 made `from_args` collapse a linked-worktree
    `--workspace-root` to the primary worktree via `for_repo`. As a result,
    when this test runs from a linked worktree, `mcp-server.sh doctor`
    invokes the binary with `--workspace-root <linked>` but the doctor
    reports the **primary** worktree's path. The assertion below derives
    the expected primary independently of where pytest is running so the
    test stays correct in both primary and linked worktree contexts.
    """
    from agent_handoff_mcp.config import _resolve_primary_worktree_root

    repo_root = Path(__file__).resolve().parents[3]
    config = json.loads((repo_root / ".vscode" / "mcp.json").read_text())

    server = config["servers"]["altcontext-mcp"]
    assert server["command"] == "agent-handoff-mcp"
    assert server["args"] == [
        "--workspace-root",
        "${workspaceFolder}",
        "--state-dir",
        "${workspaceFolder}/.task-state",
        "--current-task-path",
        "${workspaceFolder}/CURRENT_TASK.json",
        "--exports-dir",
        "${workspaceFolder}/.task-state/exports",
        "serve-stdio",
    ]
    assert server["env"]["PYENV_VERSION"] == "description-service"
    assert server["env"]["PYENV_ROOT"] == "${env:PYENV_ROOT}"
    assert "PYTHONPATH" not in server["env"]

    result = subprocess.run(
        ["./scripts/mcp/mcp-server.sh", "doctor"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True

    # AHMCP-16-BR-01: from_args() routes through for_repo(), so doctor's
    # reported workspace_root is the primary worktree even when invoked
    # from a linked worktree. Derive the expected primary independently
    # so the test passes in both contexts.
    expected_primary = _resolve_primary_worktree_root(repo_root) or repo_root
    assert payload["workspace_root"] == str(expected_primary)


def test_project_codex_config_registers_installed_stdio_adapter() -> None:
    """The project Codex adapter stays portable and repo-relative."""
    test_repo_root = Path(__file__).resolve().parents[3]
    config = tomllib.loads((test_repo_root / ".codex" / "config.toml").read_text())

    server = config["mcp_servers"]["altcontext-mcp"]
    assert server["command"] == "agent-handoff-mcp"
    assert server["cwd"] == "."
    assert server["args"] == [
        "--workspace-root",
        ".",
        "--state-dir",
        ".task-state",
        "--current-task-path",
        "CURRENT_TASK.json",
        "--exports-dir",
        ".task-state/exports",
        "serve-stdio",
    ]
    assert server["env"]["PYENV_VERSION"] == "description-service"
    assert "PYTHONPATH" not in server["env"]


def test_project_mcp_json_sets_runtime_env_and_relative_workspace_root() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config = json.loads((repo_root / ".mcp.json").read_text())

    for server_name in ("agent-handoff-mcp", "agent-orchestrator-mcp"):
        server = config["mcpServers"][server_name]
        assert server["command"] in {"agent-handoff-mcp", "agent-orchestrator-mcp"}
        assert server["args"] == ["--workspace-root", ".", "serve-stdio"]
        assert server["env"]["PYENV_VERSION"] == "description-service"
        assert server["env"]["AGENT_HANDOFF_ENFORCE_BRANCH"] == "1"


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
    assert "next_actions" in tool_names
    assert "review_findings" in tool_names
    assert "artifacts" in tool_names
    assert "review_runs" in tool_names


@pytest.mark.timeout(60)
def test_only_all_tool_profile_is_accepted(tmp_path: Path) -> None:
    """Legacy tool-profile aliases are rejected instead of silently normalized."""
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    async def _count(extra_args: list[str], log_name: str) -> int:
        transport = PythonStdioTransport(
            script_path=launcher,
            args=["--workspace-root", str(repo_root)] + extra_args + ["serve-stdio"],
            cwd=str(repo_root),
            python_cmd=sys.executable,
            log_file=tmp_path / log_name,
        )
        async with Client(transport) as client:
            return len(await client.list_tools())

    default_count = asyncio.run(_count([], "default-count.log"))
    assert default_count == 23, f"Expected 23 default tools, got {default_count}"

    for value in ("core", "extended"):
        result = subprocess.run(
            [
                sys.executable,
                str(launcher),
                "--workspace-root",
                str(repo_root),
                "--tool-profile",
                value,
                "doctor",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "invalid choice" in result.stderr.lower() or "Invalid tool_profile" in result.stderr
