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
get_lane_activity = core.get_lane_activity
list_lane_messages = core.list_lane_messages
get_plan_cursor = core.get_plan_cursor
list_next_actions = core.list_next_actions
list_plan_cursors = core.list_plan_cursors
upsert_plan_cursor = core.upsert_plan_cursor
list_worker_reports = core.list_worker_reports
list_worktree_lanes = core.list_worktree_lanes
record_lane_message = core.record_lane_message
record_worker_report = core.record_worker_report
update_lane_message = core.update_lane_message
upsert_worktree_lane = core.upsert_worktree_lane


TOOL_DESCRIPTIONS: dict[str, str] = {
    "set_handoff_state": "Set or update the active handoff task state with optimistic revision protection.",
    "get_handoff_state": "Read the active or requested task handoff summary, including blockers, actions, tests, and findings.",
    "upsert_worktree_lane": "Create or update worktree lane metadata for a task, including branch, status, and worktree path.",
    "list_worktree_lanes": "List registered worktree lanes for the active or requested task.",
    "get_lane_activity": "Read the current activity summary for a lane, including blockers, actions, findings, messages, and tests.",
    "list_next_actions": "List next-action rows for the active or requested task, optionally filtered by lane or status.",
    "record_decision": "Record an orchestrator or worker decision in the handoff ledger for the active task.",
    "update_next_actions": "Add, update, complete, or skip next-action items for the active task.",
    "record_test_result": "Record the result of a verification command for the active task.",
    "report_blocker": "Add, resolve, or reopen a blocker for the active task.",
    "record_worker_report": "Record a structured worker report for a lane, including summary, changed files, blockers, and merge readiness.",
    "list_worker_reports": "List recent worker reports for the active or requested task, optionally scoped to a lane.",
    "record_lane_message": "Create a lane message between orchestrator and worker for the active or requested task.",
    "update_lane_message": "Update the status of a lane message, such as closing or acknowledging it.",
    "list_lane_messages": "List lane messages for the active or requested task, optionally filtered by lane, direction, or status.",
    "get_plan_cursor": "Fetch the durable plan-dispatch cursor for a specific task-plan item.",
    "list_plan_cursors": "List durable plan-dispatch cursor rows for the active or requested task, optionally filtered by state or lane.",
    "upsert_plan_cursor": "Create or update a durable task-plan cursor row recording dispatch, completion, skip, or escalation state.",
    "record_review_finding": "Record or reopen a review finding for a task with stable finding IDs and optional line metadata.",
    "update_review_finding": "Mark a review finding fixed, deferred, wontfix, or reopen it with notes.",
    "reopen_review_finding": "Reopen a previously closed review finding with a reopen reason.",
    "list_review_findings": "List review findings for the active or requested task, optionally filtered by status or severity.",
    "get_review_finding": "Fetch a single review finding by stable finding ID or database ID.",
    "get_review_findings_summary": "Return aggregate counts of review findings by status and severity for the active or requested task.",
    "reconcile_review_findings": "Compare open findings against current files and return a reconciliation summary for review workflows.",
    "handoff_close_check": "Evaluate whether a task is ready to close based on open blockers, pending actions, open findings, and lane state.",
    "generate_current_task_md": "Generate CURRENT_TASK.md from handoff state for the active or requested task.",
    "export_handoff_state": "Export the task handoff state to a portable JSON snapshot.",
    "import_handoff_state": "Import a previously exported handoff state snapshot into the local database.",
    "archive_task_state": "Archive completed task state from the live handoff tables into archive storage.",
    "get_handoff_dashboard": "Return a broader handoff dashboard view across task state, lanes, findings, blockers, and reports.",
}


def _apply_tool_descriptions() -> None:
    for name, description in TOOL_DESCRIPTIONS.items():
        tool = globals().get(name)
        if tool is None:
            continue
        existing = getattr(tool, "__doc__", None)
        if existing and existing.strip():
            continue
        tool.__doc__ = description


_apply_tool_descriptions()


def generate_current_task_md(
    task_ref: str | None = None,
    write_file: bool = True,
    related_task_refs: str | None = None,
) -> str:
    """Generate CURRENT_TASK.md for the active task.

    Args:
        task_ref: The task to render. Defaults to the active task.
        write_file: Write the markdown to disk.
        related_task_refs: Comma-separated task_ref values whose open review
            findings should also appear in the output, grouped under
            "Related Open Review Findings".
    """
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

    if related_task_refs:
        refs = [r.strip() for r in related_task_refs.split(",") if r.strip()]
        active_ref = state.get("task_ref", "")
        refs = [r for r in refs if r != active_ref]
        if refs:
            state["related_findings_open"] = core._fetch_related_open_findings(refs)

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
        upsert_worktree_lane,
        list_worktree_lanes,
        get_lane_activity,
        list_next_actions,
        record_decision,
        update_next_actions,
        record_test_result,
        report_blocker,
        record_worker_report,
        list_worker_reports,
        record_lane_message,
        update_lane_message,
        list_lane_messages,
        get_plan_cursor,
        list_plan_cursors,
        upsert_plan_cursor,
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
