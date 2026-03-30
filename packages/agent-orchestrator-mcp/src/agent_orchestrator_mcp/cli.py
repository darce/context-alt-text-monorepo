"""CLI entry point for the Agent Orchestrator MCP server.

Subcommands:
  serve / serve-stdio      Start the MCP server over stdio.
  doctor                   Print server diagnostics.
  orchestrator-start       Start the orchestrator daemon for a task.
  orchestrator-status      Print orchestrator daemon status.
  orchestrator-pause       Pause the orchestrator daemon.
  orchestrator-resume      Resume the orchestrator daemon.
  orchestrator-stop        Stop the orchestrator daemon.
  orchestrator-cycle       Run one orchestrator cycle synchronously.
  worker-start             Start a worker daemon for a specific lane.
  worker-status            Print worker daemon status for a lane.
  worker-stop              Stop a worker daemon for a lane.
  worker-resume            Resume a worker daemon for a lane.
  worker-start-all         Start worker daemons for all lanes in a task.
  worker-events            Print worker event history for a lane.
  dispatch                 Dispatch (upsert) work for a lane.
  list-backends            List available AI backends.
  metrics                  Print ACE metrics summary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_handoff_mcp.config import RuntimeConfig

from .api import (
    build_orchestrator_mcp,
    configure_runtime,
    dispatch_lane_work,
    get_metrics_summary,
    list_available_backends,
    orchestrator_pause,
    orchestrator_resume,
    orchestrator_single_cycle,
    orchestrator_start,
    orchestrator_status,
    orchestrator_stop,
    run_doctor,
    worker_event_history,
    worker_resume,
    worker_start,
    worker_start_all,
    worker_status,
    worker_stop,
)


def _build_config(
    workspace_root: Path,
    state_dir: Path | None = None,
    current_task_path: Path | None = None,
    exports_dir: Path | None = None,
) -> RuntimeConfig:
    state_dir = state_dir or (workspace_root / ".task-state")
    return RuntimeConfig(
        workspace_root=workspace_root,
        state_dir=state_dir,
        db_path=state_dir / "handoff.db",
        current_task_path=current_task_path or (workspace_root / "CURRENT_TASK.md"),
        exports_dir=exports_dir or (state_dir / "exports"),
        artifact_db_path=state_dir / "mcp-artifacts.db",
    )


def _print_json(payload: str) -> None:
    print(payload)


def _build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument("--state-dir", type=Path, default=None,
                        help="State directory (default: <workspace-root>/.task-state).")
    parser.add_argument("--current-task-path", type=Path, default=None,
                        help="CURRENT_TASK.md path (default: <workspace-root>/CURRENT_TASK.md).")
    parser.add_argument("--exports-dir", type=Path, default=None,
                        help="Exports directory (default: <state-dir>/exports).")
    subparsers = parser.add_subparsers(dest="command")

    # --- serve ---
    subparsers.add_parser("serve", help="Start the MCP server (default).")
    subparsers.add_parser("serve-stdio", help="Start the MCP server over stdio (alias for serve).")

    # --- doctor ---
    doctor_p = subparsers.add_parser("doctor", help="Print server diagnostics.")
    doctor_p.add_argument("--json", dest="json_output", action="store_true")

    # --- orchestrator daemon ---
    ostart = subparsers.add_parser("orchestrator-start", help="Start the orchestrator daemon.")
    ostart.add_argument("--task-ref", required=True)
    ostart.add_argument("--backend", default="codex-cli")
    ostart.add_argument("--poll-interval", type=int, default=60)
    ostart.add_argument("--single-pass", action="store_true", default=False)
    ostart.add_argument("--worker-start-mode", default="mcp")
    ostart.add_argument("--worker-reasoning-effort", default="auto")
    ostart.add_argument("--model", default=None)

    subparsers.add_parser("orchestrator-status", help="Print orchestrator daemon status.")
    subparsers.add_parser("orchestrator-pause", help="Pause the orchestrator daemon.")
    subparsers.add_parser("orchestrator-resume", help="Resume the orchestrator daemon.")

    ostop = subparsers.add_parser("orchestrator-stop", help="Stop the orchestrator daemon.")
    ostop.add_argument("--force", action="store_true", default=False)
    ostop.add_argument("--wait", type=float, default=5.0, dest="wait_seconds")

    ocycle = subparsers.add_parser("orchestrator-cycle", help="Run one orchestrator cycle synchronously.")
    ocycle.add_argument("--task-ref", required=True)
    ocycle.add_argument("--backend", default="codex-cli")
    ocycle.add_argument("--dry-run", action="store_true", default=False)
    ocycle.add_argument("--timeout", type=float, default=300.0, dest="timeout_seconds")
    ocycle.add_argument("--worker-start-mode", default="mcp")
    ocycle.add_argument("--worker-reasoning-effort", default="auto")
    ocycle.add_argument("--model", default=None)

    # --- worker daemon ---
    wstart = subparsers.add_parser("worker-start", help="Start a worker daemon for a lane.")
    wstart.add_argument("--task-ref", required=True)
    wstart.add_argument("--lane-id", required=True)
    wstart.add_argument("--backend", default="codex-subagent")
    wstart.add_argument("--poll-interval", type=int, default=30)
    wstart.add_argument("--single-pass", action="store_true", default=False)
    wstart.add_argument("--session", default=None)
    wstart.add_argument("--session-mode", default="fresh_turn")
    wstart.add_argument("--reasoning-effort", default="inherit")
    wstart.add_argument("--model", default=None)

    wstatus = subparsers.add_parser("worker-status", help="Print worker daemon status for a lane.")
    wstatus.add_argument("--task-ref", required=True)
    wstatus.add_argument("--lane-id", required=True)

    wstop = subparsers.add_parser("worker-stop", help="Stop a worker daemon for a lane.")
    wstop.add_argument("--task-ref", required=True)
    wstop.add_argument("--lane-id", required=True)
    wstop.add_argument("--force", action="store_true", default=False)

    wresume = subparsers.add_parser("worker-resume", help="Resume a worker daemon for a lane.")
    wresume.add_argument("--task-ref", required=True)
    wresume.add_argument("--lane-id", required=True)

    wall = subparsers.add_parser("worker-start-all", help="Start worker daemons for all lanes in a task.")
    wall.add_argument("--task-ref", required=True)
    wall.add_argument("--backend", default="codex-subagent")
    wall.add_argument("--poll-interval", type=int, default=30)
    wall.add_argument("--single-pass", action="store_true", default=False)
    wall.add_argument("--session-mode", default="fresh_turn")
    wall.add_argument("--reasoning-effort", default="inherit")
    wall.add_argument("--model", default=None)

    wevents = subparsers.add_parser("worker-events", help="Print worker event history for a lane.")
    wevents.add_argument("--task-ref", required=True)
    wevents.add_argument("--lane-id", required=True)
    wevents.add_argument("--limit", type=int, default=50)
    wevents.add_argument("--event-name", default=None)

    # --- dispatch ---
    dispatch_p = subparsers.add_parser("dispatch", help="Dispatch (upsert) work for a lane.")
    dispatch_p.add_argument("--lane-id", required=True)
    dispatch_p.add_argument("--task-ref", default=None)
    dispatch_p.add_argument("--model", default=None)
    dispatch_p.add_argument("--backend", default=None)
    dispatch_p.add_argument("--reasoning-effort", default=None)
    dispatch_p.add_argument("--start-worker", action="store_true", default=False)

    # --- list-backends ---
    subparsers.add_parser("list-backends", help="List available AI backends.")

    # --- metrics ---
    metrics_p = subparsers.add_parser("metrics", help="Print ACE metrics summary.")
    metrics_p.add_argument("--task-ref", default=None)
    metrics_p.add_argument("--format", dest="output_format", default="markdown", choices=["markdown", "json"])

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    config = _build_config(
        args.workspace_root,
        state_dir=args.state_dir,
        current_task_path=args.current_task_path,
        exports_dir=args.exports_dir,
    )
    configure_runtime(config)

    cmd = args.command

    # --- serve ---
    if cmd in (None, "serve", "serve-stdio"):
        mcp = build_orchestrator_mcp(config)
        mcp.run()
        return

    # --- doctor ---
    if cmd == "doctor":
        result = run_doctor(config)
        if getattr(args, "json_output", False):
            print(json.dumps(result, indent=2))
        else:
            print(f"server: {result.get('server', 'agent-orchestrator-mcp')}")
            print(f"tool_count: {result.get('tool_count', '?')}")
            for name in sorted(result.get("tools", [])):
                print(f"  - {name}")
        return

    # --- orchestrator daemon ---
    if cmd == "orchestrator-start":
        _print_json(orchestrator_start(
            task_ref=args.task_ref,
            backend=args.backend,
            poll_interval=args.poll_interval,
            single_pass=args.single_pass,
            worker_start_mode=args.worker_start_mode,
            worker_reasoning_effort=args.worker_reasoning_effort,
            model=args.model,
        ))
        return

    if cmd == "orchestrator-status":
        _print_json(orchestrator_status())
        return

    if cmd == "orchestrator-pause":
        _print_json(orchestrator_pause())
        return

    if cmd == "orchestrator-resume":
        _print_json(orchestrator_resume())
        return

    if cmd == "orchestrator-stop":
        _print_json(orchestrator_stop(force=args.force, wait_seconds=args.wait_seconds))
        return

    if cmd == "orchestrator-cycle":
        _print_json(orchestrator_single_cycle(
            task_ref=args.task_ref,
            backend=args.backend,
            dry_run=args.dry_run,
            timeout_seconds=args.timeout_seconds,
            worker_start_mode=args.worker_start_mode,
            worker_reasoning_effort=args.worker_reasoning_effort,
            model=args.model,
        ))
        return

    # --- worker daemon ---
    if cmd == "worker-start":
        _print_json(worker_start(
            task_ref=args.task_ref,
            lane_id=args.lane_id,
            backend=args.backend,
            poll_interval=args.poll_interval,
            single_pass=args.single_pass,
            session=args.session,
            session_mode=args.session_mode,
            reasoning_effort=args.reasoning_effort,
            model=args.model,
        ))
        return

    if cmd == "worker-status":
        _print_json(worker_status(task_ref=args.task_ref, lane_id=args.lane_id))
        return

    if cmd == "worker-stop":
        _print_json(worker_stop(task_ref=args.task_ref, lane_id=args.lane_id, force=args.force))
        return

    if cmd == "worker-resume":
        _print_json(worker_resume(task_ref=args.task_ref, lane_id=args.lane_id))
        return

    if cmd == "worker-start-all":
        _print_json(worker_start_all(
            task_ref=args.task_ref,
            backend=args.backend,
            poll_interval=args.poll_interval,
            single_pass=args.single_pass,
            session_mode=args.session_mode,
            reasoning_effort=args.reasoning_effort,
            model=args.model,
        ))
        return

    if cmd == "worker-events":
        _print_json(worker_event_history(
            task_ref=args.task_ref,
            lane_id=args.lane_id,
            limit=args.limit,
            event_name=args.event_name,
        ))
        return

    # --- dispatch ---
    if cmd == "dispatch":
        _print_json(dispatch_lane_work(
            lane_id=args.lane_id,
            model=args.model,
            backend=args.backend,
            reasoning_effort=args.reasoning_effort,
            task_ref=args.task_ref,
            start_worker=args.start_worker,
        ))
        return

    # --- list-backends ---
    if cmd == "list-backends":
        _print_json(list_available_backends())
        return

    # --- metrics ---
    if cmd == "metrics":
        result = get_metrics_summary(task_ref=args.task_ref, output_format=args.output_format)
        print(result)
        return

    parser.error(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
