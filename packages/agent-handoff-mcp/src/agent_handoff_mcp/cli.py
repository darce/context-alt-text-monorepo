from __future__ import annotations

import argparse
import json
from pathlib import Path

from .api import (
    archive_task_state,
    build_handoff_mcp,
    configure_runtime,
    dispatch_lane_work,
    export_handoff_state,
    generate_current_task_md,
    get_artifact_source,
    get_artifact_terms,
    get_handoff_dashboard,
    get_handoff_state,
    get_lane_activity,
    get_review_findings_summary,
    handoff_close_check,
    import_handoff_state,
    list_artifact_sources,
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
)
from .config import RuntimeConfig

WORKER_REASONING_EFFORT_CHOICES = ("inherit", "auto", "low", "medium", "high", "xhigh")


def _print_json(payload: str | dict) -> None:
    if isinstance(payload, str):
        print(payload)
        return
    print(json.dumps(payload, indent=2, sort_keys=True))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Portable agent handoff MCP server")
    parser.add_argument("--workspace-root")
    parser.add_argument("--state-dir")
    parser.add_argument("--current-task-path")
    parser.add_argument("--exports-dir")

    subparsers = parser.add_subparsers(dest="command", required=True)

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

    state_parser = subparsers.add_parser("state")
    state_parser.add_argument("task_ref", nargs="?")
    state_parser.add_argument("--verbose", action="store_true")

    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("--task-ref", required=True)
    set_parser.add_argument("--objective", required=True)
    set_parser.add_argument("--status", default="in_progress")
    set_parser.add_argument("--expected-revision", type=int)

    decision_parser = subparsers.add_parser("decision")
    decision_parser.add_argument("--session", required=True)
    decision_parser.add_argument("--decision", required=True)
    decision_parser.add_argument("--rationale")

    action_parser = subparsers.add_parser("action")
    action_parser.add_argument("--operation", required=True, choices=["add", "update", "complete", "skip"])
    action_parser.add_argument("--action-id", type=int)
    action_parser.add_argument("--text")
    action_parser.add_argument("--priority", type=int)
    action_parser.add_argument("--status")

    lane_upsert_parser = subparsers.add_parser("lane-upsert")
    lane_upsert_parser.add_argument("--task-ref")
    lane_upsert_parser.add_argument("--lane-id", required=True)
    lane_upsert_parser.add_argument("--worktree-path", required=True)
    lane_upsert_parser.add_argument("--branch", required=True)
    lane_upsert_parser.add_argument("--title")
    lane_upsert_parser.add_argument("--objective")
    lane_upsert_parser.add_argument("--owner-agent")
    lane_upsert_parser.add_argument("--status", default="planned")
    lane_upsert_parser.add_argument("--model")
    lane_upsert_parser.add_argument("--backend")
    lane_upsert_parser.add_argument("--reasoning-effort", choices=WORKER_REASONING_EFFORT_CHOICES)
    lane_upsert_parser.add_argument("--notes")

    lane_list_parser = subparsers.add_parser("lane-list")
    lane_list_parser.add_argument("--task-ref")
    lane_list_parser.add_argument("--status", default="all")
    lane_list_parser.add_argument("--limit", type=int, default=100)
    lane_list_parser.add_argument("--offset", type=int, default=0)

    lane_activity_parser = subparsers.add_parser("lane-activity")
    lane_activity_parser.add_argument("--lane-id", required=True)
    lane_activity_parser.add_argument("--task-ref")
    lane_activity_parser.add_argument("--limit-decisions", type=int, default=20)
    lane_activity_parser.add_argument("--limit-tests", type=int, default=20)
    lane_activity_parser.add_argument("--limit-blockers", type=int, default=20)
    lane_activity_parser.add_argument("--limit-actions", type=int, default=20)
    lane_activity_parser.add_argument("--limit-findings", type=int, default=20)

    blocker_parser = subparsers.add_parser("blocker")
    blocker_parser.add_argument("--operation", required=True, choices=["add", "resolve", "reopen"])
    blocker_parser.add_argument("--description")
    blocker_parser.add_argument("--blocker-id", type=int)

    test_parser = subparsers.add_parser("test")
    test_parser.add_argument("--session", required=True)
    test_parser.add_argument("--command", dest="test_command", required=True)
    test_parser.add_argument("--passed", action="store_true")
    test_parser.add_argument("--result")
    test_parser.add_argument("--exit-code", type=int)

    report_parser = subparsers.add_parser("lane-report")
    report_parser.add_argument("--task-ref")
    report_parser.add_argument("--lane-id", required=True)
    report_parser.add_argument("--session", required=True)
    report_parser.add_argument("--summary", required=True)
    report_parser.add_argument("--changed-file", action="append", default=[])
    report_parser.add_argument("--test-command", action="append", default=[])
    report_parser.add_argument("--blocker", action="append", default=[])
    report_parser.add_argument("--merge-ready", action="store_true")
    report_parser.add_argument("--status", default="submitted")

    report_list_parser = subparsers.add_parser("lane-report-list")
    report_list_parser.add_argument("--task-ref")
    report_list_parser.add_argument("--lane-id")
    report_list_parser.add_argument("--limit", type=int, default=20)
    report_list_parser.add_argument("--offset", type=int, default=0)

    message_parser = subparsers.add_parser("lane-message")
    message_parser.add_argument("--task-ref")
    message_parser.add_argument("--lane-id", required=True)
    message_parser.add_argument("--session", required=True)
    message_parser.add_argument("--direction", required=True)
    message_parser.add_argument("--message", required=True)
    message_parser.add_argument("--subject")
    message_parser.add_argument("--status", default="open")
    message_parser.add_argument("--artifact", action="append", default=[])

    brief_parser = subparsers.add_parser("lane-brief")
    brief_parser.add_argument("--task-ref")
    brief_parser.add_argument("--lane-id", required=True)
    brief_parser.add_argument("--session", required=True)
    brief_parser.add_argument("--source-lane", required=True)
    brief_parser.add_argument("--reason", required=True)
    brief_parser.add_argument("--summary", required=True)
    brief_parser.add_argument("--message")
    brief_parser.add_argument("--required-action", action="append", default=[])
    brief_parser.add_argument("--artifact", action="append", default=[])
    brief_parser.add_argument("--status", default="open")

    message_update_parser = subparsers.add_parser("lane-message-update")
    message_update_parser.add_argument("--message-id", type=int, required=True)
    message_update_parser.add_argument("--status", required=True)
    message_update_parser.add_argument("--task-ref")

    message_list_parser = subparsers.add_parser("lane-message-list")
    message_list_parser.add_argument("--task-ref")
    message_list_parser.add_argument("--lane-id")
    message_list_parser.add_argument("--status", default="all")
    message_list_parser.add_argument("--limit", type=int, default=20)
    message_list_parser.add_argument("--offset", type=int, default=0)

    brief_list_parser = subparsers.add_parser("lane-brief-list")
    brief_list_parser.add_argument("--task-ref")
    brief_list_parser.add_argument("--lane-id")
    brief_list_parser.add_argument("--status", default="open")
    brief_list_parser.add_argument("--limit", type=int, default=20)
    brief_list_parser.add_argument("--offset", type=int, default=0)

    review_record_parser = subparsers.add_parser("review-record")
    review_record_parser.add_argument("--session", required=True)
    review_record_parser.add_argument("--finding-id", required=True)
    review_record_parser.add_argument("--severity", required=True)
    review_record_parser.add_argument("--file-path", required=True)
    review_record_parser.add_argument("--description", required=True)
    review_record_parser.add_argument("--line-start", type=int)
    review_record_parser.add_argument("--line-end", type=int)
    review_record_parser.add_argument("--fix")
    review_record_parser.add_argument("--task-ref")

    review_update_parser = subparsers.add_parser("review-update")
    review_update_parser.add_argument("--status", required=True)
    review_update_parser.add_argument("--finding-id")
    review_update_parser.add_argument("--finding-db-id", type=int)
    review_update_parser.add_argument("--resolution-notes")
    review_update_parser.add_argument("--reopen-reason")
    review_update_parser.add_argument("--verified-commit-sha")
    review_update_parser.add_argument("--verification-evidence")
    review_update_parser.add_argument("--task-ref")
    review_update_parser.add_argument("--session")

    review_list_parser = subparsers.add_parser("review-list")
    review_list_parser.add_argument("--task-ref")
    review_list_parser.add_argument("--status", default="all")
    review_list_parser.add_argument("--severity", default="all")
    review_list_parser.add_argument("--limit", type=int, default=20)
    review_list_parser.add_argument("--offset", type=int, default=0)

    review_summary_parser = subparsers.add_parser("review-summary")
    review_summary_parser.add_argument("--task-ref")
    review_summary_parser.add_argument("--top-n-open", type=int, default=10)
    review_summary_parser.add_argument("--top-n-recent-updates", type=int, default=10)

    close_parser = subparsers.add_parser("handoff-close-check")
    close_parser.add_argument("--task-ref")
    close_parser.add_argument("--allow-no-active-task", action="store_true")
    close_parser.add_argument("--enforce", action="store_true")
    close_parser.add_argument("--require-fresh-tests", action="store_true")
    close_parser.add_argument("--current-commit-sha")

    task_parser = subparsers.add_parser("task")
    task_parser.add_argument("task_ref", nargs="?")
    task_parser.add_argument("--no-write", action="store_true")

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--task-ref")
    export_parser.add_argument("--output-path")
    export_parser.add_argument("--no-markdown", action="store_true")

    dispatch_parser = subparsers.add_parser("dispatch-lane-work")
    dispatch_parser.add_argument("--task-ref")
    dispatch_parser.add_argument("--lane-id", required=True)
    dispatch_parser.add_argument("--model")
    dispatch_parser.add_argument("--backend")
    dispatch_parser.add_argument("--reasoning-effort", choices=WORKER_REASONING_EFFORT_CHOICES)

    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("--input-path", required=True)
    import_parser.add_argument("--mode", default="merge")
    import_parser.add_argument("--set-active", action="store_true")
    import_parser.add_argument("--allow-destructive-clear", action="store_true")

    archive_parser = subparsers.add_parser("archive")
    archive_parser.add_argument("--task-ref")
    archive_parser.add_argument("--notes")
    archive_parser.add_argument("--clear-active-if-matches", action="store_true")
    archive_parser.add_argument("--prune-working-rows", action="store_true")
    archive_parser.add_argument("--allow-destructive-clear", action="store_true")

    switch_parser = subparsers.add_parser("switch", help="Switch active task (auto-archives the outgoing task).")
    switch_parser.add_argument("task_ref", help="Task reference to activate.")
    switch_parser.add_argument("--objective", help="Override objective (auto-resolved from archive if omitted).")
    switch_parser.add_argument("--status", default="in_progress")

    orchestrator_start_parser = subparsers.add_parser("orchestrator-start")
    orchestrator_start_parser.add_argument("--task-ref", required=True)
    orchestrator_start_parser.add_argument("--backend", default="codex-cli")
    orchestrator_start_parser.add_argument("--poll-interval", type=int, default=60)
    orchestrator_start_parser.add_argument("--worker-start-mode", default="mcp", choices=("mcp", "manual"))
    orchestrator_start_parser.add_argument(
        "--worker-reasoning-effort",
        default="auto",
        choices=WORKER_REASONING_EFFORT_CHOICES,
    )
    orchestrator_start_parser.add_argument("--single-pass", action="store_true")

    subparsers.add_parser("orchestrator-status")

    orchestrator_stop_parser = subparsers.add_parser("orchestrator-stop")
    orchestrator_stop_parser.add_argument("--force", action="store_true")

    subparsers.add_parser("orchestrator-pause")
    subparsers.add_parser("orchestrator-resume")

    worker_start_parser = subparsers.add_parser("worker-start")
    worker_start_parser.add_argument("--task-ref", required=True)
    worker_start_parser.add_argument("--lane-id", required=True)
    worker_start_parser.add_argument("--backend", default="codex-subagent")
    worker_start_parser.add_argument("--model")
    worker_start_parser.add_argument("--poll-interval", type=int, default=30)
    worker_start_parser.add_argument("--single-pass", action="store_true")
    worker_start_parser.add_argument("--session")
    worker_start_parser.add_argument("--session-mode", default="fresh_turn", choices=("fresh_turn", "shared_lane"))
    worker_start_parser.add_argument(
        "--reasoning-effort",
        default="inherit",
        choices=WORKER_REASONING_EFFORT_CHOICES,
    )

    worker_status_parser = subparsers.add_parser("worker-status")
    worker_status_parser.add_argument("--task-ref", required=True)
    worker_status_parser.add_argument("--lane-id", required=True)

    worker_history_parser = subparsers.add_parser("worker-event-history")
    worker_history_parser.add_argument("--task-ref", required=True)
    worker_history_parser.add_argument("--lane-id", required=True)
    worker_history_parser.add_argument("--limit", type=int, default=50)
    worker_history_parser.add_argument("--event-name")

    worker_stop_parser = subparsers.add_parser("worker-stop")
    worker_stop_parser.add_argument("--task-ref", required=True)
    worker_stop_parser.add_argument("--lane-id", required=True)
    worker_stop_parser.add_argument("--force", action="store_true")

    worker_resume_parser = subparsers.add_parser("worker-resume")
    worker_resume_parser.add_argument("--task-ref", required=True)
    worker_resume_parser.add_argument("--lane-id", required=True)

    worker_start_all_parser = subparsers.add_parser("worker-start-all")
    worker_start_all_parser.add_argument("--task-ref", required=True)
    worker_start_all_parser.add_argument("--backend", default="codex-subagent")
    worker_start_all_parser.add_argument("--model")
    worker_start_all_parser.add_argument("--poll-interval", type=int, default=30)
    worker_start_all_parser.add_argument("--single-pass", action="store_true")
    worker_start_all_parser.add_argument("--session-mode", default="fresh_turn", choices=("fresh_turn", "shared_lane"))
    worker_start_all_parser.add_argument(
        "--reasoning-effort",
        default="inherit",
        choices=WORKER_REASONING_EFFORT_CHOICES,
    )

    turn_parser = subparsers.add_parser("run-structured-turn")
    turn_parser.add_argument("--prompt-file", required=True)
    turn_parser.add_argument("--schema-file", required=True)
    turn_parser.add_argument("--cwd", required=True)
    turn_parser.add_argument("--backend", default="codex-subagent")
    turn_parser.add_argument("--timeout-seconds", type=float, default=120.0)

    artifact_record_parser = subparsers.add_parser("artifact-record")
    artifact_record_parser.add_argument("--task-ref")
    artifact_record_parser.add_argument("--lane-id")
    artifact_record_parser.add_argument("--app-root")
    artifact_record_parser.add_argument("--source-kind", required=True)
    artifact_record_parser.add_argument("--source-label", required=True)
    artifact_record_parser.add_argument("--content-type", default="text/plain")
    artifact_record_parser.add_argument("--summary")
    artifact_record_parser.add_argument(
        "--content-file",
        help="Path to a file whose contents will be used as the artifact content.",
    )
    artifact_record_parser.add_argument(
        "--content",
        help="Artifact content as a string (use --content-file for large inputs).",
    )

    artifact_search_parser = subparsers.add_parser("artifact-search")
    artifact_search_parser.add_argument("--query", dest="queries", action="append", required=True)
    artifact_search_parser.add_argument("--task-ref")
    artifact_search_parser.add_argument("--lane-id")
    artifact_search_parser.add_argument("--app-root")
    artifact_search_parser.add_argument("--source-kind")
    artifact_search_parser.add_argument("--content-type")
    artifact_search_parser.add_argument("--limit", type=int, default=10)

    artifact_list_parser = subparsers.add_parser("artifact-list")
    artifact_list_parser.add_argument("--task-ref")
    artifact_list_parser.add_argument("--lane-id")
    artifact_list_parser.add_argument("--app-root")
    artifact_list_parser.add_argument("--source-kind")
    artifact_list_parser.add_argument("--limit", type=int, default=50)
    artifact_list_parser.add_argument("--offset", type=int, default=0)

    artifact_get_parser = subparsers.add_parser("artifact-get")
    artifact_get_parser.add_argument("--source-id", type=int)
    artifact_get_parser.add_argument("--task-ref")
    artifact_get_parser.add_argument("--source-label")

    artifact_terms_parser = subparsers.add_parser("artifact-terms")
    artifact_terms_parser.add_argument("--source-id", type=int)
    artifact_terms_parser.add_argument("--task-ref")
    artifact_terms_parser.add_argument("--source-label")
    artifact_terms_parser.add_argument("--top-n", type=int, default=10)

    artifact_purge_parser = subparsers.add_parser("artifact-purge")
    artifact_purge_parser.add_argument("--task-ref")
    artifact_purge_parser.add_argument("--lane-id")
    artifact_purge_parser.add_argument("--app-root")
    artifact_purge_parser.add_argument("--older-than-days", type=int)

    handoff_search_parser = subparsers.add_parser(
        "handoff-search",
        help="Search canonical handoff records (decisions, findings, blockers, actions) by keyword (BM25/FTS5).",
    )
    handoff_search_parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        metavar="TERM",
        help="Search term (repeatable; multiple terms are OR-joined). At least one required.",
    )
    handoff_search_parser.add_argument("--task-ref", help="Scope results to a specific task.")
    handoff_search_parser.add_argument("--lane-id", help="Scope results to a specific lane.")
    handoff_search_parser.add_argument(
        "--record-types",
        nargs="+",
        choices=["decision", "finding", "blocker", "action"],
        metavar="TYPE",
        help="Limit search to these record types (decision, finding, blocker, action).",
    )
    handoff_search_parser.add_argument("--limit", type=int, default=20, help="Max results (default 20, max 100).")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    config = RuntimeConfig.from_args(args)
    configure_runtime(config)

    if args.command == "serve-stdio":
        build_handoff_mcp(config).run(transport="stdio")
        return
    if args.command == "serve-http":
        build_handoff_mcp(config).run(
            transport="streamable-http", host=args.host, port=args.port,
        )
        return
    if args.command == "single-cycle":
        _print_json(orchestrator_single_cycle(
            task_ref=args.task_ref,
            backend=args.backend,
            dry_run=args.dry_run,
            timeout_seconds=args.timeout,
            worker_start_mode=args.worker_start_mode,
            worker_reasoning_effort=args.worker_reasoning_effort,
        ))
        return
    if args.command == "doctor":
        _print_json(run_doctor(config))
        return
    if args.command == "dashboard":
        _print_json(get_handoff_dashboard(limit=args.limit))
        return
    if args.command == "state":
        _print_json(get_handoff_state(task_ref=args.task_ref, verbose=args.verbose))
        return
    if args.command == "set":
        _print_json(
            set_handoff_state(
                task_ref=args.task_ref,
                objective=args.objective,
                status=args.status,
                expected_revision=args.expected_revision,
            )
        )
        return
    if args.command == "decision":
        _print_json(record_decision(session=args.session, decision=args.decision, rationale=args.rationale))
        return
    if args.command == "action":
        _print_json(
            update_next_actions(
                operation=args.operation,
                action_id=args.action_id,
                action=args.text,
                priority=args.priority,
                status=args.status,
            )
        )
        return
    if args.command == "lane-upsert":
        _print_json(
            upsert_worktree_lane(
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
        )
        return
    if args.command == "lane-list":
        _print_json(
            list_worktree_lanes(
                task_ref=args.task_ref,
                status=args.status,
                limit=args.limit,
                offset=args.offset,
            )
        )
        return
    if args.command == "lane-activity":
        _print_json(
            get_lane_activity(
                lane_id=args.lane_id,
                task_ref=args.task_ref,
                limit_decisions=args.limit_decisions,
                limit_tests=args.limit_tests,
                limit_blockers=args.limit_blockers,
                limit_actions=args.limit_actions,
                limit_findings=args.limit_findings,
            )
        )
        return
    if args.command == "blocker":
        _print_json(
            report_blocker(
                operation=args.operation,
                description=args.description,
                blocker_id=args.blocker_id,
            )
        )
        return
    if args.command == "test":
        _print_json(
            record_test_result(
                session=args.session,
                command=args.test_command,
                passed=args.passed,
                result=args.result,
                exit_code=args.exit_code,
            )
        )
        return
    if args.command == "lane-report":
        _print_json(
            record_worker_report(
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
        )
        return
    if args.command == "lane-report-list":
        _print_json(
            list_worker_reports(
                task_ref=args.task_ref,
                lane_id=args.lane_id,
                limit=args.limit,
                offset=args.offset,
            )
        )
        return
    if args.command == "lane-message":
        _print_json(
            record_lane_message(
                task_ref=args.task_ref,
                lane_id=args.lane_id,
                session=args.session,
                direction=args.direction,
                message=args.message,
                subject=args.subject,
                status=args.status,
                payload={"artifacts": args.artifact} if args.artifact else None,
            )
        )
        return
    if args.command == "lane-brief":
        _print_json(
            record_lane_brief(
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
        )
        return
    if args.command == "lane-message-update":
        _print_json(update_lane_message(message_id=args.message_id, status=args.status, task_ref=args.task_ref))
        return
    if args.command == "lane-message-list":
        _print_json(
            list_lane_messages(
                task_ref=args.task_ref,
                lane_id=args.lane_id,
                status=args.status,
                limit=args.limit,
                offset=args.offset,
            )
        )
        return
    if args.command == "lane-brief-list":
        _print_json(
            list_lane_briefs(
                task_ref=args.task_ref,
                lane_id=args.lane_id,
                status=args.status,
                limit=args.limit,
                offset=args.offset,
            )
        )
        return
    if args.command == "review-record":
        details: dict[str, int | str] = {}
        if args.line_start is not None:
            details["line_start"] = args.line_start
        if args.line_end is not None:
            details["line_end"] = args.line_end
        if args.fix:
            details["fix"] = args.fix
        _print_json(
            record_review_finding(
                session=args.session,
                finding_id=args.finding_id,
                severity=args.severity,
                file_path=args.file_path,
                description=args.description,
                details=details or None,
                task_ref=getattr(args, "task_ref", None),
            )
        )
        return
    if args.command == "review-update":
        _print_json(
            update_review_finding(
                status=args.status,
                finding_id=args.finding_id,
                finding_db_id=args.finding_db_id,
                resolution_notes=args.resolution_notes,
                reopen_reason=args.reopen_reason,
                verified_commit_sha=args.verified_commit_sha,
                verification_evidence=args.verification_evidence,
                task_ref=args.task_ref,
                session=args.session,
            )
        )
        return
    if args.command == "review-list":
        _print_json(
            list_review_findings(
                task_ref=args.task_ref,
                status=args.status,
                severity=args.severity,
                limit=args.limit,
                offset=args.offset,
            )
        )
        return
    if args.command == "review-summary":
        _print_json(
            get_review_findings_summary(
                task_ref=args.task_ref,
                top_n_open=args.top_n_open,
                top_n_recent_updates=args.top_n_recent_updates,
            )
        )
        return
    if args.command == "handoff-close-check":
        _print_json(
            handoff_close_check(
                task_ref=args.task_ref,
                allow_no_active_task=args.allow_no_active_task,
                enforce=args.enforce,
                require_fresh_tests=args.require_fresh_tests,
                current_commit_sha=args.current_commit_sha,
            )
        )
        return
    if args.command == "task":
        _print_json(generate_current_task_md(task_ref=args.task_ref, write_file=not args.no_write))
        return
    if args.command == "export":
        _print_json(
            export_handoff_state(
                task_ref=args.task_ref,
                output_path=args.output_path,
                include_markdown=not args.no_markdown,
            )
        )
        return
    if args.command == "import":
        _print_json(
            import_handoff_state(
                input_path=args.input_path,
                mode=args.mode,
                set_active=args.set_active,
                allow_destructive_clear=args.allow_destructive_clear,
            )
        )
        return
    if args.command == "dispatch-lane-work":
        _print_json(
            dispatch_lane_work(
                task_ref=args.task_ref,
                lane_id=args.lane_id,
                model=args.model,
                backend=args.backend,
                reasoning_effort=args.reasoning_effort,
            )
        )
        return
    if args.command == "archive":
        _print_json(
            archive_task_state(
                task_ref=args.task_ref,
                notes=args.notes,
                clear_active_if_matches=args.clear_active_if_matches,
                prune_working_rows=args.prune_working_rows,
                allow_destructive_clear=args.allow_destructive_clear,
            )
        )
        return
    if args.command == "switch":
        _print_json(
            switch_task(
                task_ref=args.task_ref,
                objective=args.objective,
                status=args.status,
            )
        )
        return
    if args.command == "orchestrator-start":
        _print_json(
            orchestrator_start(
                task_ref=args.task_ref,
                backend=args.backend,
                poll_interval=args.poll_interval,
                worker_start_mode=args.worker_start_mode,
                worker_reasoning_effort=args.worker_reasoning_effort,
                single_pass=args.single_pass,
            )
        )
        return
    if args.command == "orchestrator-status":
        _print_json(orchestrator_status())
        return
    if args.command == "orchestrator-stop":
        _print_json(orchestrator_stop(force=args.force))
        return
    if args.command == "orchestrator-pause":
        _print_json(orchestrator_pause())
        return
    if args.command == "orchestrator-resume":
        _print_json(orchestrator_resume())
        return
    if args.command == "worker-start":
        _print_json(
            worker_start(
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
        )
        return
    if args.command == "worker-status":
        _print_json(worker_status(task_ref=args.task_ref, lane_id=args.lane_id))
        return
    if args.command == "worker-event-history":
        _print_json(
            worker_event_history(
                task_ref=args.task_ref,
                lane_id=args.lane_id,
                limit=args.limit,
                event_name=args.event_name,
            )
        )
        return
    if args.command == "worker-stop":
        _print_json(worker_stop(task_ref=args.task_ref, lane_id=args.lane_id, force=args.force))
        return
    if args.command == "worker-resume":
        _print_json(worker_resume(task_ref=args.task_ref, lane_id=args.lane_id))
        return
    if args.command == "worker-start-all":
        _print_json(
            worker_start_all(
                task_ref=args.task_ref,
                backend=args.backend,
                poll_interval=args.poll_interval,
                single_pass=args.single_pass,
                session_mode=args.session_mode,
                reasoning_effort=args.reasoning_effort,
                model=args.model,
            )
        )
        return
    if args.command == "run-structured-turn":
        _print_json(
            run_structured_turn(
                prompt=Path(args.prompt_file).read_text(),
                schema=json.loads(Path(args.schema_file).read_text()),
                cwd=args.cwd,
                backend=args.backend,
                timeout_seconds=args.timeout_seconds,
            )
        )
        return
    if args.command == "artifact-record":
        content = args.content
        if content is None and args.content_file:
            content = Path(args.content_file).read_text()
        _print_json(
            record_artifact(
                task_ref=args.task_ref,
                lane_id=args.lane_id,
                app_root=args.app_root,
                source_kind=args.source_kind,
                source_label=args.source_label,
                content=content or "",
                content_type=args.content_type,
                summary=args.summary,
            )
        )
        return
    if args.command == "artifact-search":
        _print_json(
            search_artifacts(
                queries=args.queries,
                task_ref=args.task_ref,
                lane_id=args.lane_id,
                app_root=args.app_root,
                source_kind=args.source_kind,
                content_type=args.content_type,
                limit=args.limit,
            )
        )
        return
    if args.command == "artifact-list":
        _print_json(
            list_artifact_sources(
                task_ref=args.task_ref,
                lane_id=args.lane_id,
                app_root=args.app_root,
                source_kind=args.source_kind,
                limit=args.limit,
                offset=args.offset,
            )
        )
        return
    if args.command == "artifact-get":
        _print_json(
            get_artifact_source(
                source_id=args.source_id,
                task_ref=args.task_ref,
                source_label=args.source_label,
            )
        )
        return
    if args.command == "artifact-terms":
        _print_json(
            get_artifact_terms(
                source_id=args.source_id,
                task_ref=args.task_ref,
                source_label=args.source_label,
                top_n=args.top_n,
            )
        )
        return
    if args.command == "artifact-purge":
        _print_json(
            purge_artifacts(
                task_ref=args.task_ref,
                lane_id=args.lane_id,
                app_root=args.app_root,
                older_than_days=args.older_than_days,
            )
        )
        return
    if args.command == "handoff-search":
        _print_json(
            search_handoff(
                queries=args.queries,
                task_ref=getattr(args, "task_ref", None),
                lane_id=getattr(args, "lane_id", None),
                record_types=getattr(args, "record_types", None),
                limit=getattr(args, "limit", 20),
            )
        )
        return
