from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .api import (
    ArgSpec,
    archive_task_state,
    build_handoff_mcp,
    configure_runtime,
    dispatch_lane_work,
    export_handoff_state,
    generate_current_task_md,
    get_artifact,
    get_handoff_state,
    get_lane_activity,
    get_review_findings_summary,
    handoff_close_check,
    import_handoff_state,
    list_lane_messages,
    list_lane_briefs,
    list_review_findings,
    list_worker_reports,
    list_worktree_lanes,
    orchestrator_pause,
    orchestrator_resume,
    orchestrator_single_cycle,
    orchestrator_start,
    orchestrator_status,
    orchestrator_stop,
    purge_artifacts,
    record_artifact,
    record_lane_message,
    record_lane_brief,
    record_decision,
    record_review_finding,
    record_test_result,
    record_worker_report,
    report_blocker,
    run_structured_turn,
    run_doctor,
    search_artifacts,
    search_handoff,
    set_handoff_state,
    switch_task,
    update_lane_message,
    update_next_actions,
    update_review_finding,
    upsert_worktree_lane,
    worker_resume,
    worker_start,
    worker_start_all,
    worker_event_history,
    worker_status,
    worker_stop,
    _WORKER_REASONING_EFFORT_CHOICES,
)
from .config import RuntimeConfig

WORKER_REASONING_EFFORT_CHOICES = _WORKER_REASONING_EFFORT_CHOICES


def _print_json(payload: str | dict) -> None:
    if isinstance(payload, str):
        print(payload)
        return
    print(json.dumps(payload, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Registry infrastructure
# ---------------------------------------------------------------------------


@dataclass
class CliEntry:
    """Registry entry for a single CLI sub-command."""

    name: str
    dispatch: Callable[[argparse.Namespace], Any]
    description: str = ""
    args: list[ArgSpec] = field(default_factory=list)


def _auto_dispatch(handler: Callable[..., Any], cli_args: list[ArgSpec]) -> Callable[[argparse.Namespace], Any]:
    """Generate a dispatch function from ArgSpec definitions.

    Works for tools where every ArgSpec dest matches the handler parameter name directly.
    Use ``_CLI_DISPATCH_OVERRIDES`` for tools that require custom logic (negations, dict
    construction, file reading, etc.).
    """
    def dispatch(args: argparse.Namespace) -> Any:
        kwargs: dict[str, Any] = {}
        for spec in cli_args:
            if spec.name.startswith("-"):
                dest = spec.dest or spec.name.lstrip("-").replace("-", "_")
            else:
                dest = spec.dest or spec.name
            kwargs[dest] = getattr(args, dest, None)
        return handler(**kwargs)
    return dispatch


def _add_arg(sub: argparse.ArgumentParser, spec: ArgSpec) -> None:
    """Add one ArgSpec to a subparser."""
    is_positional = not spec.name.startswith("-")
    kwargs: dict[str, Any] = {}
    if spec.help:
        kwargs["help"] = spec.help
    if spec.action:
        kwargs["action"] = spec.action
        if spec.action == "store_true":
            kwargs.setdefault("default", False)
        elif spec.action == "append":
            kwargs["default"] = spec.default if spec.default is not None else []
    elif not is_positional:
        if spec.type is not str:
            kwargs["type"] = spec.type
        kwargs["default"] = spec.default
    else:
        # positional — type and default handled by nargs
        if spec.type is not str:
            kwargs["type"] = spec.type
    if not is_positional and spec.required:
        kwargs["required"] = True
    if spec.choices:
        kwargs["choices"] = spec.choices
    if spec.nargs:
        kwargs["nargs"] = spec.nargs
    if spec.dest and not is_positional:
        kwargs["dest"] = spec.dest
    sub.add_argument(spec.name, **kwargs)


# ---------------------------------------------------------------------------
# Command dispatch functions
# ---------------------------------------------------------------------------
# Most MCP-registry tools are dispatched automatically via _auto_dispatch() in
# _build_cli_registry(). Only tools that require custom argument handling
# (negations, dict construction, file reading) need an explicit function here.




def _dispatch_lane_upsert(args: argparse.Namespace) -> Any:
    return upsert_worktree_lane(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        worktree_path=args.worktree_path,
        branch=args.branch,
        title=args.title,
        objective=args.objective,
        owner_agent=args.owner_agent,
        status=args.status,
        model=args.model,
        backend=args.backend,
        reasoning_effort=args.reasoning_effort,
        notes=args.notes,
    )


def _dispatch_lane_list(args: argparse.Namespace) -> Any:
    return list_worktree_lanes(
        task_ref=args.task_ref,
        status=args.status,
        limit=args.limit,
        offset=args.offset,
    )


def _dispatch_lane_activity(args: argparse.Namespace) -> Any:
    return get_lane_activity(
        lane_id=args.lane_id,
        task_ref=args.task_ref,
        limit_decisions=args.limit_decisions,
        limit_tests=args.limit_tests,
        limit_blockers=args.limit_blockers,
        limit_actions=args.limit_actions,
        limit_findings=args.limit_findings,
    )



def _dispatch_lane_report(args: argparse.Namespace) -> Any:
    return record_worker_report(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        session=args.session,
        summary=args.summary,
        changed_files=args.changed_file,
        test_commands=args.test_command,
        blockers=args.blocker,
        merge_ready=args.merge_ready,
        status=args.status,
    )


def _dispatch_lane_report_list(args: argparse.Namespace) -> Any:
    return list_worker_reports(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        limit=args.limit,
        offset=args.offset,
    )


def _dispatch_lane_message(args: argparse.Namespace) -> Any:
    return record_lane_message(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        session=args.session,
        direction=args.direction,
        message=args.message,
        subject=args.subject,
        status=args.status,
        payload={"artifacts": args.artifact} if args.artifact else None,
    )


def _dispatch_lane_brief(args: argparse.Namespace) -> Any:
    return record_lane_brief(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        session=args.session,
        source_lane=args.source_lane,
        reason=args.reason,
        summary=args.summary,
        message=args.message,
        required_actions=args.required_action,
        artifacts=args.artifact,
        status=args.status,
    )


def _dispatch_lane_message_update(args: argparse.Namespace) -> Any:
    return update_lane_message(message_id=args.message_id, status=args.status, task_ref=args.task_ref)


def _dispatch_lane_message_list(args: argparse.Namespace) -> Any:
    return list_lane_messages(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        status=args.status,
        limit=args.limit,
        offset=args.offset,
    )


def _dispatch_lane_brief_list(args: argparse.Namespace) -> Any:
    return list_lane_briefs(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        status=args.status,
        limit=args.limit,
        offset=args.offset,
    )


def _dispatch_review_record(args: argparse.Namespace) -> Any:
    details: dict[str, int | str] = {}
    if args.line_start is not None:
        details["line_start"] = args.line_start
    if args.line_end is not None:
        details["line_end"] = args.line_end
    if args.fix:
        details["fix"] = args.fix
    return record_review_finding(
        session=args.session,
        finding_id=args.finding_id,
        severity=args.severity,
        file_path=args.file_path,
        description=args.description,
        details=details or None,
        task_ref=getattr(args, "task_ref", None),
    )


def _dispatch_review_summary(args: argparse.Namespace) -> Any:
    return get_review_findings_summary(
        task_ref=args.task_ref,
        top_n_open=args.top_n_open,
        top_n_recent_updates=args.top_n_recent_updates,
    )


def _dispatch_task(args: argparse.Namespace) -> Any:
    return generate_current_task_md(task_ref=args.task_ref, write_file=not args.no_write)


def _dispatch_export(args: argparse.Namespace) -> Any:
    return export_handoff_state(
        task_ref=args.task_ref,
        output_path=args.output_path,
        include_markdown=not args.no_markdown,
    )


def _dispatch_dispatch_lane_work(args: argparse.Namespace) -> Any:
    return dispatch_lane_work(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        model=args.model,
        backend=args.backend,
        reasoning_effort=args.reasoning_effort,
    )


def _dispatch_switch(args: argparse.Namespace) -> Any:
    return switch_task(
        task_ref=args.task_ref,
        objective=args.objective,
        focus=args.focus,
        status=args.status,
    )


def _dispatch_orchestrator_start(args: argparse.Namespace) -> Any:
    return orchestrator_start(
        task_ref=args.task_ref,
        backend=args.backend,
        poll_interval=args.poll_interval,
        worker_start_mode=args.worker_start_mode,
        worker_reasoning_effort=args.worker_reasoning_effort,
        single_pass=args.single_pass,
    )


def _dispatch_orchestrator_stop(args: argparse.Namespace) -> Any:
    return orchestrator_stop(force=args.force)


def _dispatch_worker_start(args: argparse.Namespace) -> Any:
    return worker_start(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        backend=args.backend,
        poll_interval=args.poll_interval,
        single_pass=args.single_pass,
        session=args.session,
        session_mode=args.session_mode,
        reasoning_effort=args.reasoning_effort,
        model=args.model,
    )


def _dispatch_worker_status(args: argparse.Namespace) -> Any:
    return worker_status(task_ref=args.task_ref, lane_id=args.lane_id)


def _dispatch_worker_event_history(args: argparse.Namespace) -> Any:
    return worker_event_history(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        limit=args.limit,
        event_name=args.event_name,
    )


def _dispatch_worker_stop(args: argparse.Namespace) -> Any:
    return worker_stop(task_ref=args.task_ref, lane_id=args.lane_id, force=args.force)


def _dispatch_worker_resume(args: argparse.Namespace) -> Any:
    return worker_resume(task_ref=args.task_ref, lane_id=args.lane_id)


def _dispatch_worker_start_all(args: argparse.Namespace) -> Any:
    return worker_start_all(
        task_ref=args.task_ref,
        backend=args.backend,
        poll_interval=args.poll_interval,
        single_pass=args.single_pass,
        session_mode=args.session_mode,
        reasoning_effort=args.reasoning_effort,
        model=args.model,
    )


def _dispatch_run_structured_turn(args: argparse.Namespace) -> Any:
    return run_structured_turn(
        prompt=Path(args.prompt_file).read_text(),
        schema=json.loads(Path(args.schema_file).read_text()),
        cwd=args.cwd,
        backend=args.backend,
        timeout_seconds=args.timeout_seconds,
    )


def _dispatch_artifact_record(args: argparse.Namespace) -> Any:
    content = args.content
    if content is None and args.content_file:
        content = Path(args.content_file).read_text()
    return record_artifact(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        app_root=args.app_root,
        source_kind=args.source_kind,
        source_label=args.source_label,
        content=content or "",
        content_type=args.content_type,
        summary=args.summary,
    )


def _dispatch_artifact_list(args: argparse.Namespace) -> Any:
    return search_artifacts(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        app_root=args.app_root,
        source_kind=args.source_kind,
        limit=args.limit,
        offset=args.offset,
    )


def _dispatch_artifact_terms(args: argparse.Namespace) -> Any:
    return get_artifact(
        source_id=args.source_id,
        task_ref=args.task_ref,
        source_label=args.source_label,
        include_terms=True,
        top_n_terms=args.top_n,
    )


# ---------------------------------------------------------------------------
# CLI registry
# ---------------------------------------------------------------------------

# Tools that need custom dispatch logic (negation flags, dict construction,
# or file-reading side effects). All other MCP tools use _auto_dispatch().
_CLI_DISPATCH_OVERRIDES: dict[str, Callable[[argparse.Namespace], Any]] = {
    "record_review_finding": _dispatch_review_record,
    "generate_current_task_md": _dispatch_task,
    "export_handoff_state": _dispatch_export,
    "record_artifact": _dispatch_artifact_record,
}


def _build_cli_registry() -> list[CliEntry]:
    from .api import _build_tool_registry  # noqa: PLC0415

    _re = WORKER_REASONING_EFFORT_CHOICES

    # Build entries for MCP tools that declare a cli_name.
    registry: list[CliEntry] = []
    for tool_entry in _build_tool_registry():
        if tool_entry.cli_name is None:
            continue
        override = _CLI_DISPATCH_OVERRIDES.get(tool_entry.name)
        dispatch_fn = override if override is not None else _auto_dispatch(tool_entry.handler, tool_entry.cli_args)
        registry.append(
            CliEntry(
                name=tool_entry.cli_name,
                dispatch=dispatch_fn,
                description=tool_entry.description,
                args=tool_entry.cli_args,
            )
        )

    # CLI-only commands: lane management, orchestrator/worker daemons,
    # extra artifact variants, and utility tools not in the MCP registry.
    registry.extend([
        # --- lane management (not in MCP tool registry) ---
        CliEntry(
            name="lane-upsert",
            dispatch=_dispatch_lane_upsert,
            description="Create or update a worktree lane.",
            args=[
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id", required=True),
                ArgSpec("--worktree-path", required=True),
                ArgSpec("--branch", required=True),
                ArgSpec("--title"),
                ArgSpec("--objective"),
                ArgSpec("--owner-agent"),
                ArgSpec("--status", default="planned"),
                ArgSpec("--model"),
                ArgSpec("--backend"),
                ArgSpec("--reasoning-effort", choices=list(_re)),
                ArgSpec("--notes"),
            ],
        ),
        CliEntry(
            name="lane-list",
            dispatch=_dispatch_lane_list,
            description="List registered worktree lanes.",
            args=[
                ArgSpec("--task-ref"),
                ArgSpec("--status", default="all"),
                ArgSpec("--limit", type=int, default=100),
                ArgSpec("--offset", type=int, default=0),
            ],
        ),
        CliEntry(
            name="lane-activity",
            dispatch=_dispatch_lane_activity,
            description="Read lane activity summary.",
            args=[
                ArgSpec("--lane-id", required=True),
                ArgSpec("--task-ref"),
                ArgSpec("--limit-decisions", type=int, default=20),
                ArgSpec("--limit-tests", type=int, default=20),
                ArgSpec("--limit-blockers", type=int, default=20),
                ArgSpec("--limit-actions", type=int, default=20),
                ArgSpec("--limit-findings", type=int, default=20),
            ],
        ),
        CliEntry(
            name="lane-report",
            dispatch=_dispatch_lane_report,
            description="Record a worker report for a lane.",
            args=[
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id", required=True),
                ArgSpec("--session", required=True),
                ArgSpec("--summary", required=True),
                ArgSpec("--changed-file", action="append", default=[]),
                ArgSpec("--test-command", action="append", default=[]),
                ArgSpec("--blocker", action="append", default=[]),
                ArgSpec("--merge-ready", action="store_true"),
                ArgSpec("--status", default="submitted"),
            ],
        ),
        CliEntry(
            name="lane-report-list",
            dispatch=_dispatch_lane_report_list,
            description="List worker reports.",
            args=[
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id"),
                ArgSpec("--limit", type=int, default=20),
                ArgSpec("--offset", type=int, default=0),
            ],
        ),
        CliEntry(
            name="lane-message",
            dispatch=_dispatch_lane_message,
            description="Create a lane message.",
            args=[
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id", required=True),
                ArgSpec("--session", required=True),
                ArgSpec("--direction", required=True),
                ArgSpec("--message", required=True),
                ArgSpec("--subject"),
                ArgSpec("--status", default="open"),
                ArgSpec("--artifact", action="append", default=[]),
            ],
        ),
        CliEntry(
            name="lane-brief",
            dispatch=_dispatch_lane_brief,
            description="Create a structured orchestrator-to-worker brief.",
            args=[
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id", required=True),
                ArgSpec("--session", required=True),
                ArgSpec("--source-lane", required=True),
                ArgSpec("--reason", required=True),
                ArgSpec("--summary", required=True),
                ArgSpec("--message"),
                ArgSpec("--required-action", action="append", default=[]),
                ArgSpec("--artifact", action="append", default=[]),
                ArgSpec("--status", default="open"),
            ],
        ),
        CliEntry(
            name="lane-message-update",
            dispatch=_dispatch_lane_message_update,
            description="Update the status of a lane message.",
            args=[
                ArgSpec("--message-id", type=int, required=True),
                ArgSpec("--status", required=True),
                ArgSpec("--task-ref"),
            ],
        ),
        CliEntry(
            name="lane-message-list",
            dispatch=_dispatch_lane_message_list,
            description="List lane messages.",
            args=[
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id"),
                ArgSpec("--status", default="all"),
                ArgSpec("--limit", type=int, default=20),
                ArgSpec("--offset", type=int, default=0),
            ],
        ),
        CliEntry(
            name="lane-brief-list",
            dispatch=_dispatch_lane_brief_list,
            description="List lane briefs.",
            args=[
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id"),
                ArgSpec("--status", default="open"),
                ArgSpec("--limit", type=int, default=20),
                ArgSpec("--offset", type=int, default=0),
            ],
        ),
        # --- review extras ---
        CliEntry(
            name="review-summary",
            dispatch=_dispatch_review_summary,
            description="Return aggregate review finding counts.",
            args=[
                ArgSpec("--task-ref"),
                ArgSpec("--top-n-open", type=int, default=10),
                ArgSpec("--top-n-recent-updates", type=int, default=10),
            ],
        ),
        # --- task switching ---
        CliEntry(
            name="switch",
            dispatch=_dispatch_switch,
            description="Switch active task (auto-archives the outgoing task).",
            args=[
                ArgSpec("task_ref", help="Task reference to activate."),
                ArgSpec("--objective", help="Override objective."),
                ArgSpec("--focus", help="Set current focus for the target task."),
                ArgSpec("--status", default="in_progress"),
            ],
        ),
        # --- lane work dispatch ---
        CliEntry(
            name="dispatch-lane-work",
            dispatch=_dispatch_dispatch_lane_work,
            description="Update lane dispatch parameters.",
            args=[
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id", required=True),
                ArgSpec("--model"),
                ArgSpec("--backend"),
                ArgSpec("--reasoning-effort", choices=list(_re)),
            ],
        ),
        # --- orchestrator daemon ---
        CliEntry(
            name="orchestrator-start",
            dispatch=_dispatch_orchestrator_start,
            description="Start the orchestrator daemon.",
            args=[
                ArgSpec("--task-ref", required=True),
                ArgSpec("--backend", default="codex-cli"),
                ArgSpec("--poll-interval", type=int, default=60),
                ArgSpec("--worker-start-mode", default="mcp", choices=["mcp", "manual"]),
                ArgSpec("--worker-reasoning-effort", default="auto", choices=list(_re)),
                ArgSpec("--single-pass", action="store_true"),
            ],
        ),
        CliEntry(
            name="orchestrator-status",
            dispatch=lambda args: orchestrator_status(),
            description="Return orchestrator daemon status.",
        ),
        CliEntry(
            name="orchestrator-stop",
            dispatch=_dispatch_orchestrator_stop,
            description="Stop the orchestrator daemon.",
            args=[
                ArgSpec("--force", action="store_true"),
            ],
        ),
        CliEntry(
            name="orchestrator-pause",
            dispatch=lambda args: orchestrator_pause(),
            description="Pause the orchestrator daemon.",
        ),
        CliEntry(
            name="orchestrator-resume",
            dispatch=lambda args: orchestrator_resume(),
            description="Resume the orchestrator daemon.",
        ),
        # --- worker daemon ---
        CliEntry(
            name="worker-start",
            dispatch=_dispatch_worker_start,
            description="Start a lane worker daemon.",
            args=[
                ArgSpec("--task-ref", required=True),
                ArgSpec("--lane-id", required=True),
                ArgSpec("--backend", default="codex-subagent"),
                ArgSpec("--model"),
                ArgSpec("--poll-interval", type=int, default=30),
                ArgSpec("--single-pass", action="store_true"),
                ArgSpec("--session"),
                ArgSpec("--session-mode", default="fresh_turn", choices=["fresh_turn", "shared_lane"]),
                ArgSpec("--reasoning-effort", default="inherit", choices=list(_re)),
            ],
        ),
        CliEntry(
            name="worker-status",
            dispatch=_dispatch_worker_status,
            description="Return worker daemon status.",
            args=[
                ArgSpec("--task-ref", required=True),
                ArgSpec("--lane-id", required=True),
            ],
        ),
        CliEntry(
            name="worker-event-history",
            dispatch=_dispatch_worker_event_history,
            description="Return recent worker-daemon events.",
            args=[
                ArgSpec("--task-ref", required=True),
                ArgSpec("--lane-id", required=True),
                ArgSpec("--limit", type=int, default=50),
                ArgSpec("--event-name"),
            ],
        ),
        CliEntry(
            name="worker-stop",
            dispatch=_dispatch_worker_stop,
            description="Stop a lane worker daemon.",
            args=[
                ArgSpec("--task-ref", required=True),
                ArgSpec("--lane-id", required=True),
                ArgSpec("--force", action="store_true"),
            ],
        ),
        CliEntry(
            name="worker-resume",
            dispatch=_dispatch_worker_resume,
            description="Resume a stopped worker daemon.",
            args=[
                ArgSpec("--task-ref", required=True),
                ArgSpec("--lane-id", required=True),
            ],
        ),
        CliEntry(
            name="worker-start-all",
            dispatch=_dispatch_worker_start_all,
            description="Start worker daemons for all lanes.",
            args=[
                ArgSpec("--task-ref", required=True),
                ArgSpec("--backend", default="codex-subagent"),
                ArgSpec("--model"),
                ArgSpec("--poll-interval", type=int, default=30),
                ArgSpec("--single-pass", action="store_true"),
                ArgSpec("--session-mode", default="fresh_turn", choices=["fresh_turn", "shared_lane"]),
                ArgSpec("--reasoning-effort", default="inherit", choices=list(_re)),
            ],
        ),
        # --- structured turn ---
        CliEntry(
            name="run-structured-turn",
            dispatch=_dispatch_run_structured_turn,
            description="Execute one synchronous structured bridge turn.",
            args=[
                ArgSpec("--prompt-file", required=True),
                ArgSpec("--schema-file", required=True),
                ArgSpec("--cwd", required=True),
                ArgSpec("--backend", default="codex-subagent"),
                ArgSpec("--timeout-seconds", type=float, default=120.0),
            ],
        ),
        # --- artifact extras (artifact-list and artifact-terms are CLI variants
        #     of MCP tools with slightly different arg shapes) ---
        CliEntry(
            name="artifact-list",
            dispatch=_dispatch_artifact_list,
            description="List artifact sources.",
            args=[
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id"),
                ArgSpec("--app-root"),
                ArgSpec("--source-kind"),
                ArgSpec("--limit", type=int, default=50),
                ArgSpec("--offset", type=int, default=0),
            ],
        ),
        CliEntry(
            name="artifact-terms",
            dispatch=_dispatch_artifact_terms,
            description="Return artifact with distinctive terms.",
            args=[
                ArgSpec("--source-id", type=int),
                ArgSpec("--task-ref"),
                ArgSpec("--source-label"),
                ArgSpec("--top-n", type=int, default=10),
            ],
        ),
    ])

    return registry


# ---------------------------------------------------------------------------
# Parser and main
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Portable agent handoff MCP server")
    parser.add_argument("--workspace-root")
    parser.add_argument("--state-dir")
    parser.add_argument("--current-task-path")
    parser.add_argument("--exports-dir")

    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Special-case commands not in the generic registry
    subparsers.add_parser("serve-stdio")
    http_parser = subparsers.add_parser("serve-http")
    http_parser.add_argument(
        "--host", default="127.0.0.1",
        help="Host address to bind to (default: 127.0.0.1)",
    )
    http_parser.add_argument(
        "--port", type=int, default=8741,
        help="Port to bind to (default: 8741)",
    )
    cycle_parser = subparsers.add_parser("single-cycle")
    cycle_parser.add_argument("--task-ref", required=True, help="MCP task reference.")
    cycle_parser.add_argument("--backend", default="codex-cli", help="Execution backend.")
    cycle_parser.add_argument("--worker-start-mode", default="mcp", choices=("mcp", "manual"))
    cycle_parser.add_argument(
        "--worker-reasoning-effort",
        default="auto",
        choices=WORKER_REASONING_EFFORT_CHOICES,
    )
    cycle_parser.add_argument("--dry-run", action="store_true", help="Skip mutating operations.")
    cycle_parser.add_argument("--timeout", type=float, default=300.0, help="Timeout in seconds.")
    subparsers.add_parser("doctor")
    subparsers.add_parser("dashboard").add_argument("--limit", type=int, default=20)

    # Registry-driven commands
    for entry in _build_cli_registry():
        sub = subparsers.add_parser(entry.name, help=entry.description)
        for spec in entry.args:
            _add_arg(sub, spec)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    config = RuntimeConfig.from_args(args)
    configure_runtime(config)

    # Special-case commands
    if args.subcommand == "serve-stdio":
        build_handoff_mcp(config).run(transport="stdio")
        return
    if args.subcommand == "serve-http":
        build_handoff_mcp(config).run(
            transport="streamable-http", host=args.host, port=args.port,
        )
        return
    if args.subcommand == "single-cycle":
        _print_json(orchestrator_single_cycle(
            task_ref=args.task_ref,
            backend=args.backend,
            dry_run=args.dry_run,
            timeout_seconds=args.timeout,
            worker_start_mode=args.worker_start_mode,
            worker_reasoning_effort=args.worker_reasoning_effort,
        ))
        return
    if args.subcommand == "doctor":
        _print_json(run_doctor(config))
        return
    if args.subcommand == "dashboard":
        _print_json(get_handoff_state(view="dashboard", top_n_findings=args.limit))
        return

    # Registry-driven dispatch
    registry_map = {entry.name: entry for entry in _build_cli_registry()}
    entry = registry_map.get(args.subcommand)
    if entry is not None:
        _print_json(entry.dispatch(args))
        return

    parser.error(f"Unknown command: {args.subcommand}")
