from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.client import Client, PythonStdioTransport

from .config import RuntimeConfig
from . import core
from .runtime import configure_runtime, get_runtime_config, reset_runtime_config


record_decision = core.record_decision
update_next_actions = core.update_next_actions
record_test_result = core.record_test_result
report_blocker = core.report_blocker
record_review_finding = core.record_review_finding
update_review_finding = core.update_review_finding
reopen_review_finding = core.reopen_review_finding
list_review_findings = core.list_review_findings
get_review_finding = core.get_review_finding
get_review_findings_summary = core.get_review_findings_summary
reconcile_review_findings = core.reconcile_review_findings
handoff_close_check = core.handoff_close_check
export_handoff_state = core.export_handoff_state
import_handoff_state = core.import_handoff_state
archive_task_state = core.archive_task_state
get_handoff_dashboard = core.get_handoff_dashboard
set_handoff_state = core.set_handoff_state
get_handoff_state = core.get_handoff_state


def generate_current_task_md(task_ref: str | None = None, write_file: bool = True) -> str:
    raw_state = core._invoke_tool(
        get_handoff_state,
        task_ref=task_ref,
        top_n_blockers=50,
        top_n_actions=50,
        top_n_decisions=50,
        top_n_tests=50,
        top_n_findings=100,
        verbose=True,
    )
    state = json.loads(raw_state)
    markdown = core._render_current_task_md(state)
    current_task_path = get_runtime_config().current_task_path

    if write_file:
        current_task_path.write_text(markdown)

    return core._json_response(
        {
            "ok": True,
            "task_ref": state.get("task_ref"),
            "path": str(current_task_path),
            "written": write_file,
            "markdown": markdown if not write_file else None,
        }
    )


def build_handoff_mcp(config: RuntimeConfig) -> FastMCP:
    configure_runtime(config)
    mcp = FastMCP(
        "Agent Handoff MCP",
        instructions=(
            "You are connected to the Agent Handoff MCP server. "
            "Use these tools for task state, review findings, exports, and close checks."
        ),
    )
    for tool in [
        set_handoff_state,
        get_handoff_state,
        record_decision,
        update_next_actions,
        record_test_result,
        report_blocker,
        record_review_finding,
        update_review_finding,
        reopen_review_finding,
        list_review_findings,
        get_review_finding,
        get_review_findings_summary,
        reconcile_review_findings,
        handoff_close_check,
        generate_current_task_md,
        export_handoff_state,
        import_handoff_state,
        archive_task_state,
        get_handoff_dashboard,
    ]:
        mcp.add_tool(tool)
    return mcp


def run_doctor(config: RuntimeConfig) -> dict[str, Any]:
    configure_runtime(config)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    config.exports_dir.mkdir(parents=True, exist_ok=True)
    writable_probe = config.state_dir / ".write-test"
    writable_probe.write_text("ok")
    writable_probe.unlink()
    with core._get_db_connection() as conn:
        conn.execute("SELECT 1").fetchone()

    package_src = Path(__file__).resolve().parents[1]
    launcher = package_src / "agent_handoff_mcp_launcher.py"
    stdio_tools: list[str] = []
    with tempfile.TemporaryDirectory() as temp_dir:

        async def _list_tools() -> list[str]:
            transport = PythonStdioTransport(
                script_path=launcher,
                args=["--workspace-root", str(config.workspace_root), "serve-stdio"],
                cwd=str(config.workspace_root),
                python_cmd=sys.executable,
                log_file=Path(temp_dir) / "doctor-stdio.log",
            )
            async with Client(transport) as client:
                tools = await client.list_tools()
                return sorted(tool.name for tool in tools)

        stdio_tools = asyncio.run(_list_tools())

        cli_env = dict(**os.environ)
        existing_pythonpath = cli_env.get("PYTHONPATH")
        cli_env["PYTHONPATH"] = str(package_src) if not existing_pythonpath else f"{package_src}:{existing_pythonpath}"
        cli_probe = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_handoff_mcp",
                "--workspace-root",
                str(config.workspace_root),
                "state",
            ],
            cwd=str(config.workspace_root),
            env=cli_env,
            capture_output=True,
            text=True,
            check=True,
        )
        json.loads(cli_probe.stdout)

    return {
        "ok": True,
        "workspace_root": str(config.workspace_root),
        "state_dir": str(config.state_dir),
        "db_path": str(config.db_path),
        "current_task_path": str(config.current_task_path),
        "exports_dir": str(config.exports_dir),
        "checks": {
            "sqlite": True,
            "state_dir_writable": True,
            "stdio_startup": {
                "ok": True,
                "tool_count": len(stdio_tools),
            },
            "cli_fallback_startup": True,
        },
    }
