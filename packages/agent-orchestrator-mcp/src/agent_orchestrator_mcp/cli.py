"""Minimal CLI entry point for the Agent Orchestrator MCP server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_handoff_mcp.config import RuntimeConfig

from .api import build_orchestrator_mcp


def _build_config(workspace_root: Path) -> RuntimeConfig:
    state_dir = workspace_root / ".task-state"
    return RuntimeConfig(
        workspace_root=workspace_root,
        state_dir=state_dir,
        db_path=state_dir / "handoff.db",
        current_task_path=workspace_root / "CURRENT_TASK.md",
        exports_dir=state_dir / "exports",
        artifact_db_path=state_dir / "mcp-artifacts.db",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-orchestrator-mcp",
        description="Agent Orchestrator MCP server.",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path.cwd(),
        help="Workspace root directory (default: cwd).",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("serve", help="Start the MCP server (default).")
    subparsers.add_parser("serve-stdio", help="Start the MCP server over stdio (alias for serve).")

    doctor_parser = subparsers.add_parser("doctor", help="Print server diagnostics.")
    doctor_parser.add_argument("--json", dest="json_output", action="store_true")

    args = parser.parse_args()
    config = _build_config(args.workspace_root)

    if args.command == "doctor":
        from .api import run_doctor

        result = run_doctor(config)
        if getattr(args, "json_output", False):
            print(json.dumps(result, indent=2))
        else:
            print(f"server: {result.get('server', 'agent-orchestrator-mcp')}")
            print(f"tool_count: {result.get('tool_count', '?')}")
            tools = result.get("tools", [])
            for name in sorted(tools):
                print(f"  - {name}")
        return

    # Default: serve (also handles serve-stdio alias)
    mcp = build_orchestrator_mcp(config)
    mcp.run()


if __name__ == "__main__":
    main()
