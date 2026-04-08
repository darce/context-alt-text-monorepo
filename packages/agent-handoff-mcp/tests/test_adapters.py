from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tomllib
from pathlib import Path

from fastmcp.client import Client, PythonStdioTransport


def test_vscode_adapter_points_to_installed_entrypoint_and_doctor_runs() -> None:
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
        "${workspaceFolder}/CURRENT_TASK.md",
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
    assert payload["workspace_root"] == str(repo_root)


def test_project_codex_config_registers_installed_stdio_adapter() -> None:
    """The Codex MCP config registers the installed handoff binary with
    consistent path arguments.

    This test deliberately does **not** compare the toml's path values
    against ``Path(__file__).parents[3]``. The Codex CLI doesn't know about
    git linked worktrees and always launches from the user's primary
    checkout, so ``.codex/config.toml`` is intentionally pinned to that
    primary path. When this test runs from a linked worktree (under
    ``context-alt-text-monorepo-<task-id>/``), the test file's parent path
    is the linked worktree's root, not the toml's pinned root, and the two
    correctly do not match.

    Instead, the test extracts the toml's own ``cwd`` value and verifies
    **internal consistency**: every other path arg (`--workspace-root`,
    `--state-dir`, `--current-task-path`, `--exports-dir`) must derive
    from the same base. That catches drift between the toml's various
    path values without coupling the test to where pytest happens to be
    running.
    """
    test_repo_root = Path(__file__).resolve().parents[3]
    config = tomllib.loads((test_repo_root / ".codex" / "config.toml").read_text())

    server = config["mcp_servers"]["altcontext-mcp"]
    assert server["command"] == "agent-handoff-mcp"

    # Anchor every path assertion on the toml's own cwd, not on the test
    # file's runtime location. This is what makes the test linked-worktree
    # safe.
    cwd = Path(server["cwd"])
    assert cwd.is_absolute(), f"Codex cwd must be an absolute path; got {cwd!r}"
    assert cwd.name == "context-alt-text-monorepo", (
        f"Codex cwd should point at the primary monorepo checkout; "
        f"got {cwd!r}"
    )

    assert server["args"] == [
        "--workspace-root",
        str(cwd),
        "--state-dir",
        str(cwd / ".task-state"),
        "--current-task-path",
        str(cwd / "CURRENT_TASK.md"),
        "--exports-dir",
        str(cwd / ".task-state" / "exports"),
        "serve-stdio",
    ]
    assert server["env"]["PYENV_VERSION"] == "description-service"
    assert "PYTHONPATH" not in server["env"]


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


def test_legacy_tool_profile_flags_now_all_expose_the_same_17_tools(tmp_path: Path) -> None:
    """Default/core/extended launches all expose the unified 17-tool surface."""
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
    core_count = asyncio.run(_count(["--tool-profile", "core"], "core-count.log"))
    extended_count = asyncio.run(_count(["--tool-profile", "extended"], "extended-count.log"))

    assert default_count == 17, f"Expected 17 default tools, got {default_count}"
    assert core_count == 17, f"Expected 17 tools for legacy core launch, got {core_count}"
    assert extended_count == 17, f"Expected 17 tools for legacy extended launch, got {extended_count}"
