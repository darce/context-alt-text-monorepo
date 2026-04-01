from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ._shared import ReviewFindingDetails
from .api import (
    ArgSpec,
    archive_task_state,
    build_handoff_mcp,
    configure_runtime,
    export_handoff_state,
    generate_current_task_md,
    get_artifact,
    get_handoff_state,
    handoff_close_check,
    import_handoff_state,
    list_review_findings,
    purge_artifacts,
    record_artifact,
    record_decision,
    record_review_finding,
    record_test_result,
    report_blocker,
    run_doctor,
    search_artifacts,
    search_handoff,
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


def _dispatch_review_record(args: argparse.Namespace) -> Any:
    details: ReviewFindingDetails = {}
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


def _dispatch_task(args: argparse.Namespace) -> Any:
    return generate_current_task_md(task_ref=args.task_ref, write_file=not args.no_write)


def _dispatch_export(args: argparse.Namespace) -> Any:
    return export_handoff_state(
        task_ref=args.task_ref,
        output_path=args.output_path,
        include_markdown=not args.no_markdown,
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
        detail=args.detail,
        fields=args.fields,
    )


def _dispatch_artifact_terms(args: argparse.Namespace) -> Any:
    return get_artifact(
        source_id=args.source_id,
        task_ref=args.task_ref,
        source_label=args.source_label,
        include_terms=True,
        top_n_terms=args.top_n,
        detail=args.detail,
        fields=args.fields,
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
        choices=["core", "extended"],
        help="MCP tool profile to expose: core (16 tools) or extended (all 28 tools, default).",
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
        _print_json(get_handoff_state(view="dashboard", top_n_findings=args.limit))
        return

    # Registry-driven dispatch
    registry_map = {entry.name: entry for entry in _build_cli_registry()}
    entry = registry_map.get(args.subcommand)
    if entry is not None:
        _print_json(entry.dispatch(args))
        return

    parser.error(f"Unknown command: {args.subcommand}")
