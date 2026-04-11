from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, cast

from .api import (
    ArgSpec,
    ArtifactsParam,
    NextActionsParam,
    RecordEventParam,
    ReviewFindingsParam,
    ReviewRunsParam,
    archive_task_state,
    artifacts,
    build_handoff_mcp,
    configure_runtime,
    export_handoff_state,
    generate_current_task_md,
    get_handoff_state,
    get_verified_tests,
    handoff_close_check,
    import_handoff_state,
    next_actions,
    record_event,
    review_findings,
    review_runs,
    run_doctor,
    search_handoff,
    set_handoff_state,
)
from .config import RuntimeConfig


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


def _dispatch_review_findings(args: argparse.Namespace) -> Any:
    payload: dict[str, Any] = {"operation": args.operation}
    if args.task_ref is not None:
        payload["task_ref"] = args.task_ref

    if args.operation == "record":
        payload["session"] = args.session
        payload["finding_id"] = args.finding_id
        payload["severity"] = args.severity
        payload["file_path"] = args.file_path
        payload["description"] = args.description
        details: dict[str, Any] = {}
        if args.line_start is not None:
            details["line_start"] = args.line_start
        if args.line_end is not None:
            details["line_end"] = args.line_end
        if args.fix:
            details["fix"] = args.fix
        if details:
            payload["details"] = details
        if args.review_mode is not None:
            payload["review_mode"] = args.review_mode
    elif args.operation == "batch_record":
        payload["session"] = args.session
        findings_json = args.findings_json
        if findings_json is None and args.findings_file:
            findings_json = Path(args.findings_file).read_text()
        payload["findings"] = json.loads(findings_json or "[]")
    elif args.operation == "update":
        payload["status"] = args.status
        if args.finding_id is not None:
            payload["finding_id"] = args.finding_id
        if args.finding_db_id is not None:
            payload["finding_db_id"] = args.finding_db_id
        if args.resolution_notes is not None:
            payload["resolution_notes"] = args.resolution_notes
        if args.reopen_reason is not None:
            payload["reopen_reason"] = args.reopen_reason
        if args.verified_commit_sha is not None:
            payload["verified_commit_sha"] = args.verified_commit_sha
        if args.verification_evidence is not None:
            payload["verification_evidence"] = args.verification_evidence
        if args.session is not None:
            payload["session"] = args.session
    else:
        if args.status is not None:
            payload["status"] = args.status
        if args.severity is not None:
            payload["severity"] = args.severity
        payload["limit"] = args.limit
        payload["offset"] = args.offset
        payload["detail"] = args.detail
        if args.review_mode is not None:
            payload["review_mode"] = args.review_mode
        if args.finding_id is not None:
            payload["finding_id"] = args.finding_id
        if args.finding_db_id is not None:
            payload["finding_db_id"] = args.finding_db_id

    return review_findings(review=cast(ReviewFindingsParam, payload))


def _dispatch_review_runs(args: argparse.Namespace) -> Any:
    payload: dict[str, Any] = {"operation": args.operation}
    if args.task_ref is not None:
        payload["task_ref"] = args.task_ref

    if args.operation == "record":
        payload["review_run_id"] = args.review_run_id
        payload["session"] = args.session
        payload["subject_path"] = args.subject_path
        payload["subject_kind"] = args.subject_kind
        payload["review_mode"] = args.review_mode
        if args.verdict is not None:
            payload["verdict"] = args.verdict
        if args.verdict_decision is not None:
            payload["verdict_decision"] = args.verdict_decision
    elif args.operation == "list":
        if args.subject_path is not None:
            payload["subject_path"] = args.subject_path
        if args.review_mode is not None:
            payload["review_mode"] = args.review_mode
        if args.verdict is not None:
            payload["verdict"] = args.verdict
        payload["limit"] = args.limit
        payload["offset"] = args.offset
    else:
        if args.subject_path is not None:
            payload["subject_path"] = args.subject_path

    return review_runs(review=cast(ReviewRunsParam, payload))


def _dispatch_get_verified_tests(args: argparse.Namespace) -> Any:
    passed: bool | None = None
    if args.passed == "true":
        passed = True
    elif args.passed == "false":
        passed = False
    return get_verified_tests(
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        branch=args.branch,
        commit_sha=args.commit_sha,
        passed=passed,
        limit=args.limit,
        offset=args.offset,
    )


def _dispatch_event_record(args: argparse.Namespace) -> Any:
    payload: dict[str, Any] = {"event_kind": args.event_kind}
    if args.task_ref is not None:
        payload["task_ref"] = args.task_ref

    if args.event_kind == "decision":
        payload["session"] = args.session
        payload["decision"] = args.decision
        if args.rationale is not None:
            payload["rationale"] = args.rationale
        if args.input_tokens is not None:
            payload["input_tokens"] = args.input_tokens
        if args.output_tokens is not None:
            payload["output_tokens"] = args.output_tokens
        if args.total_tokens is not None:
            payload["total_tokens"] = args.total_tokens
        if args.changed_files:
            payload["changed_files"] = args.changed_files
    elif args.event_kind == "test_result":
        payload["session"] = args.session
        payload["command"] = args.command
        payload["passed"] = args.passed
        if args.result is not None:
            payload["result"] = args.result
        if args.exit_code is not None:
            payload["exit_code"] = args.exit_code
    else:
        payload["operation"] = args.operation
        if args.description is not None:
            payload["description"] = args.description
        if args.blocker_id is not None:
            payload["blocker_id"] = args.blocker_id

    return record_event(event=cast(RecordEventParam, payload))


def _dispatch_next_actions(args: argparse.Namespace) -> Any:
    payload: dict[str, Any] = {"operation": args.operation}
    if args.task_ref is not None:
        payload["task_ref"] = args.task_ref

    if args.operation == "list":
        if args.lane_id is not None:
            payload["lane_id"] = args.lane_id
        if args.status is not None:
            payload["status"] = args.status
        payload["limit"] = args.limit
        payload["offset"] = args.offset
    else:
        if args.action_id is not None:
            payload["action_id"] = args.action_id
        if args.action is not None:
            payload["action"] = args.action
        if args.priority is not None:
            payload["priority"] = args.priority
        if args.status is not None and args.operation == "update":
            payload["status"] = args.status

    return next_actions(action=cast(NextActionsParam, payload))


def _dispatch_artifacts(args: argparse.Namespace) -> Any:
    payload: dict[str, Any] = {"operation": args.operation}
    if args.task_ref is not None:
        payload["task_ref"] = args.task_ref
    if args.lane_id is not None:
        payload["lane_id"] = args.lane_id
    if args.app_root is not None:
        payload["app_root"] = args.app_root

    if args.operation == "record":
        payload["source_kind"] = args.source_kind
        payload["source_label"] = args.source_label
        payload["content_type"] = args.content_type
        if args.summary is not None:
            payload["summary"] = args.summary
        content = args.content
        if content is None and args.content_file:
            content = Path(args.content_file).read_text()
        payload["content"] = content or ""
        if args.metadata_json is not None:
            payload["metadata"] = json.loads(args.metadata_json)
    elif args.operation == "search":
        if args.queries is not None:
            payload["queries"] = args.queries
        if args.source_kind is not None:
            payload["source_kind"] = args.source_kind
        if args.content_type is not None:
            payload["content_type"] = args.content_type
        payload["limit"] = args.limit
        payload["offset"] = args.offset
        payload["detail"] = args.detail
        if args.fields is not None:
            payload["fields"] = args.fields
    elif args.operation == "get":
        if args.source_id is not None:
            payload["source_id"] = args.source_id
        if args.source_label is not None:
            payload["source_label"] = args.source_label
        payload["include_terms"] = args.include_terms
        payload["top_n_terms"] = args.top_n_terms
        payload["detail"] = args.detail
        if args.fields is not None:
            payload["fields"] = args.fields
    else:
        if args.older_than_days is not None:
            payload["older_than_days"] = args.older_than_days

    return artifacts(artifact=cast(ArtifactsParam, payload))


def _dispatch_task(args: argparse.Namespace) -> Any:
    return generate_current_task_md(task_ref=args.task_ref, write_file=not args.no_write)


def _dispatch_export(args: argparse.Namespace) -> Any:
    return export_handoff_state(
        task_ref=args.task_ref,
        output_path=args.output_path,
        include_markdown=not args.no_markdown,
    )


def _dispatch_artifact_list(args: argparse.Namespace) -> Any:
    return artifacts(
        artifact=cast(ArtifactsParam, {
            "operation": "search",
            "task_ref": args.task_ref,
            "lane_id": args.lane_id,
            "app_root": args.app_root,
            "source_kind": args.source_kind,
            "limit": args.limit,
            "offset": args.offset,
            "detail": args.detail,
            "fields": args.fields,
        })
    )


def _dispatch_artifact_terms(args: argparse.Namespace) -> Any:
    return artifacts(
        artifact=cast(ArtifactsParam, {
            "operation": "get",
            "source_id": args.source_id,
            "task_ref": args.task_ref,
            "source_label": args.source_label,
            "include_terms": True,
            "top_n_terms": args.top_n,
            "detail": args.detail,
            "fields": args.fields,
        })
    )


# ---------------------------------------------------------------------------
# CLI registry
# ---------------------------------------------------------------------------

# Tools that need custom dispatch logic (negation flags, dict construction,
# or file-reading side effects). All other MCP tools use _auto_dispatch().
_CLI_DISPATCH_OVERRIDES: dict[str, Callable[[argparse.Namespace], Any]] = {
    "record_event": _dispatch_event_record,
    "next_actions": _dispatch_next_actions,
    "review_findings": _dispatch_review_findings,
    "review_runs": _dispatch_review_runs,
    "get_verified_tests": _dispatch_get_verified_tests,
    "artifacts": _dispatch_artifacts,
    "generate_current_task_md": _dispatch_task,
    "export_handoff_state": _dispatch_export,
}


def _build_cli_registry() -> list[CliEntry]:
    from .api import _build_tool_registry  # noqa: PLC0415

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

    # CLI-only extras: artifact variants with slightly different arg shapes.
    registry.extend(
        [
            # --- artifact extras (CLI variants with slightly different arg shapes) ---
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
                    ArgSpec("--detail", default="full", choices=["full", "summary"]),
                    ArgSpec("--fields", help="Comma-separated fields to keep in each listed source."),
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
                    ArgSpec("--detail", default="full", choices=["full", "summary"]),
                    ArgSpec("--fields", help="Comma-separated fields to keep in the returned source."),
                ],
            ),
        ]
    )

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
    parser.add_argument(
        "--tool-profile",
        default=None,
        choices=["all", "core", "extended"],
        help="Legacy tool-profile selector. All launches now expose the same 17-tool surface; core/extended are accepted as deprecated aliases.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Special-case commands not in the generic registry
    subparsers.add_parser("serve-stdio")
    http_parser = subparsers.add_parser("serve-http")
    http_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind to (default: 127.0.0.1)",
    )
    http_parser.add_argument(
        "--port",
        type=int,
        default=8741,
        help="Port to bind to (default: 8741)",
    )
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
            transport="streamable-http",
            host=args.host,
            port=args.port,
        )
        return
    if args.subcommand == "doctor":
        _print_json(run_doctor(config))
        return
    if args.subcommand == "dashboard":
        rendered = generate_current_task_md(write_file=False)
        if isinstance(rendered, dict):
            data = rendered.get("data", {}) or {}
            dashboard_markdown = data.get("dashboard_markdown") or data.get("markdown")
            if isinstance(dashboard_markdown, str):
                print(dashboard_markdown)
                return
        sys.stderr.write(
            "DASHBOARD.md render unavailable; falling back to raw get_handoff_state(view=\"dashboard\") output.\n"
        )
        _print_json(get_handoff_state(view="dashboard", top_n_findings=args.limit))
        return

    # Registry-driven dispatch
    registry_map = {entry.name: entry for entry in _build_cli_registry()}
    entry = registry_map.get(args.subcommand)
    if entry is not None:
        _print_json(entry.dispatch(args))
        return

    parser.error(f"Unknown command: {args.subcommand}")
