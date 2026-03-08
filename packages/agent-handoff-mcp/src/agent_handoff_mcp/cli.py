from __future__ import annotations

import argparse
import json

from .api import (
    archive_task_state,
    build_handoff_mcp,
    configure_runtime,
    export_handoff_state,
    generate_current_task_md,
    get_handoff_dashboard,
    get_handoff_state,
    get_review_findings_summary,
    handoff_close_check,
    import_handoff_state,
    list_review_findings,
    record_decision,
    record_review_finding,
    record_test_result,
    report_blocker,
    run_doctor,
    set_handoff_state,
    update_next_actions,
    update_review_finding,
)
from .config import RuntimeConfig


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
    subparsers.add_parser("serve-http")
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

    review_record_parser = subparsers.add_parser("review-record")
    review_record_parser.add_argument("--session", required=True)
    review_record_parser.add_argument("--finding-id", required=True)
    review_record_parser.add_argument("--severity", required=True)
    review_record_parser.add_argument("--file-path", required=True)
    review_record_parser.add_argument("--description", required=True)
    review_record_parser.add_argument("--line-start", type=int)
    review_record_parser.add_argument("--line-end", type=int)
    review_record_parser.add_argument("--fix")

    review_update_parser = subparsers.add_parser("review-update")
    review_update_parser.add_argument("--status", required=True)
    review_update_parser.add_argument("--finding-id")
    review_update_parser.add_argument("--finding-db-id", type=int)
    review_update_parser.add_argument("--resolution-notes")
    review_update_parser.add_argument("--reopen-reason")
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

    task_parser = subparsers.add_parser("task")
    task_parser.add_argument("task_ref", nargs="?")
    task_parser.add_argument("--no-write", action="store_true")

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--task-ref")
    export_parser.add_argument("--output-path")
    export_parser.add_argument("--no-markdown", action="store_true")

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
        build_handoff_mcp(config).run(transport="streamable-http")
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
