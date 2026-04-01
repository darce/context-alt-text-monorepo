from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, cast

from fastmcp import FastMCP
from fastmcp.client import Client, PythonStdioTransport
from pydantic import BaseModel, Field

from . import core
from ._shared import WriteActor
from .config import RuntimeConfig
from .core import PromptMetrics, ResolvedWriteContext, TokenUsage
from .runtime import configure_runtime, get_runtime_config, reset_runtime_config

_core_record_decision = core.record_decision
build_write_actor = core.build_write_actor
_core_update_next_actions = core.update_next_actions
_core_record_test_result = core.record_test_result
_core_report_blocker = core.report_blocker
record_review_finding = core.record_review_finding
batch_record_review_findings = core.batch_record_review_findings
_core_update_review_finding = core.update_review_finding
list_review_findings = core.list_review_findings
_core_record_review_run = core.record_review_run
list_review_runs = core.list_review_runs
get_review_coverage = core.get_review_coverage
handoff_close_check = core.handoff_close_check
export_handoff_state = core.export_handoff_state
import_handoff_state = core.import_handoff_state
archive_task_state = core.archive_task_state
_core_update_task_status = core.update_task_status
_core_set_handoff_state = core.set_handoff_state
get_handoff_state = core.get_handoff_state
list_next_actions = core.list_next_actions

record_artifact = core.record_artifact
search_artifacts = core.search_artifacts
get_artifact = core.get_artifact
purge_artifacts = core.purge_artifacts
search_handoff = core.search_handoff
load_session = core.load_session
_core_close_slice = core.close_slice
audit_decision_ids = core.audit_decision_ids


TOOL_DESCRIPTIONS: dict[str, str] = {
    "set_handoff_state": "Update the active task state (objective, focus, status). Optimistic revision guard.",
    "get_handoff_state": "Read task handoff summary (blockers, actions, findings). Pass view='dashboard' for cross-task view. Pass sections='decisions_recent,findings_open' to select specific sections; active and limits are always included. Pass sections='identity' for an identity-only response (active + limits, no data sections). Pass detail='summary' to truncate long rationale and verification fields.",
    "list_next_actions": "List next-action items, optionally filtered by lane or status.",
    "record_decision": "Record a decision in the handoff ledger. Pass changed_files as a list of monorepo-relative paths touched by this slice for structured review scope.",
    "update_next_actions": "Add, update, complete, or skip next-action items.",
    "record_test_result": "Record a verification command result.",
    "report_blocker": "Add, resolve, or reopen a blocker.",
    "record_review_finding": "Record or reopen a single review finding with stable ID, line metadata, and review_mode.",
    "batch_record_review_findings": "Record or reopen multiple review findings atomically. Max 100 items per call.",
    "update_review_finding": "Mark a review finding fixed, deferred, wontfix, or reopen it with notes.",
    "list_review_findings": "List review findings filtered by status, severity, or review_mode. Pass finding_id to fetch a single finding globally. Pass detail='summary' to truncate long text fields.",
    "record_review_run": "Record a completed review pass in the ledger.",
    "list_review_runs": "List review-run ledger entries. Filter by task_ref, subject_path, review_mode, or verdict.",
    "get_review_coverage": "Return review-coverage summary: run count, verdict, open findings by severity.",
    "handoff_close_check": "Check task readiness to close: blockers, pending actions, findings, and optional fresh-test gate.",
    "audit_decision_ids": "Audit decision IDs for grammar conformance. Returns canonical/malformed/freeform classifications.",
    "generate_current_task_md": "Generate CURRENT_TASK.md for the active task.",
    "export_handoff_state": "Export the task handoff state to a portable JSON snapshot.",
    "import_handoff_state": "Import a previously exported handoff state snapshot into the local database.",
    "archive_task_state": "Archive completed task state from the live handoff tables into archive storage.",
    "update_task_status": "Update a task status without recording a slice decision. For the active task this requires expected_revision; for archived tasks it updates the archived snapshot status used by the dashboard.",
    "load_session": "Load session context: get_handoff_state + list_review_findings(open) in one call. Pass sections to shape the nested state payload and detail to shape both state and findings.",
    "close_slice": "Record a slice-complete decision, keep the task status in_progress, and regenerate CURRENT_TASK.md. Requires expected_revision when the target task is currently active. Pass changed_files to persist structured review scope on the nested decision write.",
    "record_artifact": "Index a large artifact in the sidecar FTS5 database for scoped retrieval.",
    "search_artifacts": "Search artifact chunks by BM25 relevance. Empty queries return a source listing. Pass detail='summary' to truncate summaries and snippets, and fields='source_label,summary' or fields='source_id,title,snippet' to project per-source or per-hit fields.",
    "get_artifact": "Return artifact source record. Lookup by source_id or task_ref+source_label. Pass detail='summary' for truncated chunk previews and fields='source_label,chunk_count' to project source fields.",
    "purge_artifacts": "Delete artifact sources and FTS chunks (post-archival cleanup).",
    "search_handoff": "Search decisions, findings, blockers, actions by keyword with BM25 ranking. Pass detail='summary' to truncate snippets and fields='record_type,snippet' to project per-result fields.",
}


class WriteActorInput(BaseModel):
    agent: Annotated[
        str | None,
        Field(
            description="Optional stable agent identity override. Omit to derive it from model metadata when available."
        ),
    ] = None
    model: Annotated[
        str | None,
        Field(description="Canonical model slug for the writing agent, for example 'gpt-5.4'."),
    ] = None
    model_label: Annotated[
        str | None,
        Field(description="Canonical human-readable label for model; must match the normalized label for actor.model."),
    ] = None
    reasoning_level: Annotated[
        str | None,
        Field(description="Reasoning effort label used to derive agent identity and provenance."),
    ] = None
    branch: Annotated[
        str | None,
        Field(description="Git branch override for the write provenance."),
    ] = None
    commit_sha: Annotated[
        str | None,
        Field(description="Git commit SHA override for the write provenance."),
    ] = None
    lane_id: Annotated[
        str | None,
        Field(description="Optional worktree lane identifier for the write provenance."),
    ] = None


TaskRefParam = Annotated[
    str | None,
    Field(description="Optional task reference override. When omitted, the active task is used."),
]

ActorParam = Annotated[
    WriteActorInput | None,
    Field(description="Optional structured provenance override for the write operation."),
]

DecisionChangedFilesParam = Annotated[
    list[str] | None,
    Field(description="Optional monorepo-relative paths touched by this slice."),
]


def _dump_actor(actor: WriteActorInput | dict[str, Any] | None) -> WriteActor | None:
    if actor is None:
        return None
    actor_model = WriteActorInput.model_validate(actor) if isinstance(actor, dict) else actor
    return cast(
        WriteActor,
        {key: value for key, value in actor_model.model_dump(exclude_none=True).items() if isinstance(value, str)},
    )


def set_handoff_state(
    task_ref: Annotated[
        str, Field(description="Task reference whose active handoff state should be created or updated.")
    ],
    objective: Annotated[
        str | None,
        Field(description="Task objective. Required only when creating a brand-new handoff state row."),
    ] = None,
    focus: Annotated[
        str | None,
        Field(description="Current working focus for the task. Omit to keep the existing focus."),
    ] = None,
    status: Annotated[
        str,
        Field(description="Active handoff status, typically in_progress, blocked, review, or done."),
    ] = "in_progress",
    expected_revision: Annotated[
        int | None,
        Field(description="Optimistic concurrency guard. Required when updating an existing handoff row."),
    ] = None,
    actor: ActorParam = None,
) -> str:
    return _core_set_handoff_state(
        task_ref=task_ref,
        objective=objective,
        focus=focus,
        status=status,
        expected_revision=expected_revision,
        actor=_dump_actor(actor),
    )


def update_task_status(
    task_ref: Annotated[
        str,
        Field(description="Task reference whose status should be updated, whether active or archived."),
    ],
    status: Annotated[
        Literal["in_progress", "blocked", "review", "done"],
        Field(description="New task status to persist on the active row or archived snapshot."),
    ],
    expected_revision: Annotated[
        int | None,
        Field(description="Optimistic concurrency guard for active-task updates. Not used for archived-task updates."),
    ] = None,
    actor: ActorParam = None,
) -> str:
    return _core_update_task_status(
        task_ref=task_ref,
        status=status,
        expected_revision=expected_revision,
        actor=_dump_actor(actor),
    )


def record_decision(
    session: Annotated[str, Field(description="Session identifier for the decision write.")],
    decision: Annotated[str, Field(description="Stable decision identifier to persist in the ledger.")],
    rationale: Annotated[
        str | None,
        Field(description="Optional markdown rationale explaining the decision, verification, and open threads."),
    ] = None,
    actor: ActorParam = None,
    task_ref: TaskRefParam = None,
    input_tokens: Annotated[int | None, Field(description="Optional prompt token count for this slice.")] = None,
    output_tokens: Annotated[int | None, Field(description="Optional completion token count for this slice.")] = None,
    total_tokens: Annotated[int | None, Field(description="Optional total token count for this slice.")] = None,
    changed_files: DecisionChangedFilesParam = None,
) -> str:
    return _core_record_decision(
        session=session,
        decision=decision,
        rationale=rationale,
        actor=_dump_actor(actor),
        task_ref=task_ref,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        changed_files=changed_files,
    )


def update_next_actions(
    operation: Annotated[
        Literal["add", "update", "complete", "skip"],
        Field(description="Mutation to apply to the next-actions table."),
    ],
    action_id: Annotated[
        int | None,
        Field(description="Existing action id. Required for update, complete, and skip operations."),
    ] = None,
    action: Annotated[
        str | None,
        Field(description="Action text. Required for add; optional replacement text for update."),
    ] = None,
    priority: Annotated[
        int | None,
        Field(description="Optional priority value. Lower numbers sort first; defaults to 100 on add."),
    ] = None,
    status: Annotated[
        Literal["pending", "done", "skipped"] | None,
        Field(description="Optional explicit status override. Only used for update operations."),
    ] = None,
    actor: ActorParam = None,
    task_ref: TaskRefParam = None,
) -> str:
    return _core_update_next_actions(
        operation=operation,
        action_id=action_id,
        action=action,
        priority=priority,
        status=status,
        actor=_dump_actor(actor),
        task_ref=task_ref,
    )


def record_test_result(
    session: Annotated[str, Field(description="Session identifier for the verification run.")],
    command: Annotated[str, Field(description="Verification command that was executed.")],
    passed: Annotated[bool, Field(description="Whether the verification command passed.")],
    result: Annotated[
        str | None,
        Field(description="Optional stdout or summarized verification evidence for the command."),
    ] = None,
    exit_code: Annotated[int | None, Field(description="Optional process exit code for the command.")] = None,
    actor: ActorParam = None,
    task_ref: TaskRefParam = None,
) -> str:
    return _core_record_test_result(
        session=session,
        command=command,
        passed=passed,
        result=result,
        exit_code=exit_code,
        actor=_dump_actor(actor),
        task_ref=task_ref,
    )


def report_blocker(
    operation: Annotated[
        Literal["add", "resolve", "reopen"],
        Field(description="Blocker mutation to perform."),
    ],
    description: Annotated[
        str | None,
        Field(description="Blocker description. Required when adding a new blocker."),
    ] = None,
    blocker_id: Annotated[
        int | None,
        Field(description="Existing blocker id. Required for resolve and reopen."),
    ] = None,
    actor: ActorParam = None,
    task_ref: TaskRefParam = None,
) -> str:
    return _core_report_blocker(
        operation=operation,
        description=description,
        blocker_id=blocker_id,
        actor=_dump_actor(actor),
        task_ref=task_ref,
    )


def update_review_finding(
    status: Annotated[
        Literal["open", "fixed", "deferred", "wontfix"],
        Field(description="New finding status to apply."),
    ],
    finding_id: Annotated[
        str | None,
        Field(description="Stable finding identifier. Provide this or finding_db_id."),
    ] = None,
    finding_db_id: Annotated[
        int | None,
        Field(description="Numeric database id alternative to finding_id."),
    ] = None,
    resolution_notes: Annotated[
        str | None,
        Field(description="Optional notes describing how the finding was resolved or dispositioned."),
    ] = None,
    reopen_reason: Annotated[
        str | None,
        Field(description="Required when moving a non-open finding back to open."),
    ] = None,
    task_ref: TaskRefParam = None,
    session: Annotated[str | None, Field(description="Optional session identifier for the update.")] = None,
    actor: ActorParam = None,
    verified_commit_sha: Annotated[
        str | None,
        Field(description="Optional commit SHA that verified a fixed finding."),
    ] = None,
    verification_evidence: Annotated[
        str | None,
        Field(description="Optional verification evidence used when closing a finding as fixed."),
    ] = None,
) -> str:
    return _core_update_review_finding(
        status=status,
        finding_id=finding_id,
        finding_db_id=finding_db_id,
        resolution_notes=resolution_notes,
        reopen_reason=reopen_reason,
        task_ref=task_ref,
        session=session,
        actor=_dump_actor(actor),
        verified_commit_sha=verified_commit_sha,
        verification_evidence=verification_evidence,
    )


def record_review_run(
    review_run_id: Annotated[str, Field(description="Globally unique review run identifier.")],
    session: Annotated[str, Field(description="Session identifier for the review run.")],
    subject_path: Annotated[str, Field(description="Workspace-relative path reviewed in this run.")],
    subject_kind: Annotated[
        Literal["task_plan", "epic", "branch", "adr", "roadmap", "other"],
        Field(description="Kind of artifact reviewed in this run."),
    ] = "task_plan",
    review_mode: Annotated[str, Field(description="Review mode label, for example planning or branch.")] = "planning",
    verdict: Annotated[
        Literal["pass", "pass_with_findings", "fail", "conditional_pass"] | None,
        Field(description="Optional review verdict to store with the run."),
    ] = None,
    verdict_decision: Annotated[
        str | None,
        Field(description="Optional decision id or summary that explains the verdict."),
    ] = None,
    task_ref: TaskRefParam = None,
    actor: ActorParam = None,
) -> str:
    return _core_record_review_run(
        review_run_id=review_run_id,
        session=session,
        subject_path=subject_path,
        subject_kind=subject_kind,
        review_mode=review_mode,
        verdict=verdict,
        verdict_decision=verdict_decision,
        task_ref=task_ref,
        actor=_dump_actor(actor),
    )


def close_slice(
    session: Annotated[str, Field(description="Session identifier for the slice completion write.")],
    decision: Annotated[str, Field(description="Stable slice-complete decision identifier.")],
    rationale: Annotated[
        str | None,
        Field(description="Optional markdown rationale for the slice completion decision."),
    ] = None,
    actor: ActorParam = None,
    expected_revision: Annotated[
        int | None,
        Field(description="Optimistic concurrency guard passed to the nested handoff-state update."),
    ] = None,
    task_ref: TaskRefParam = None,
    focus: Annotated[
        str | None,
        Field(description="Optional new focus to store on the task after recording the decision."),
    ] = None,
    changed_files: DecisionChangedFilesParam = None,
) -> str:
    return _core_close_slice(
        session=session,
        decision=decision,
        rationale=rationale,
        actor=_dump_actor(actor),
        expected_revision=expected_revision,
        task_ref=task_ref,
        focus=focus,
        changed_files=changed_files,
    )


def _apply_tool_descriptions() -> None:
    for name, description in TOOL_DESCRIPTIONS.items():
        tool = globals().get(name)
        if tool is None:
            continue
        existing = getattr(tool, "__doc__", None)
        if existing and existing.strip():
            continue
        tool.__doc__ = description


@dataclass
class ArgSpec:
    """Declarative specification for a single CLI argument."""

    name: str
    type: type = str
    default: Any = None
    required: bool = False
    help: str = ""
    choices: list[str] | None = None
    action: str | None = None  # e.g. "store_true", "append"
    nargs: str | None = None
    dest: str | None = None  # override argparse dest


# Choices used by both the tool registry and CLI for worker reasoning effort.
_WORKER_REASONING_EFFORT_CHOICES = ("inherit", "auto", "low", "medium", "high", "xhigh")


@dataclass
class ToolEntry:
    """Registry entry for a single MCP tool."""

    name: str
    handler: Callable[..., Any]
    description: str
    cli_args: list[ArgSpec] = field(default_factory=list)  # CLI argument specs (single source of truth)
    cli_name: str | None = None  # CLI subcommand name; None = no CLI exposure
    deprecated_since: str | None = None  # Version string; non-None appends [DEPRECATED] to description
    profile: str = "core"  # "core" | "extended" — controls which MCP surface the tool is included in
    surface_class: str = "action"  # "query" | "action" | "generator" — matches contract taxonomy
    entity_family: str = (
        "handoff_state"  # "handoff_state" | "review_findings" | "review_runs" | "artifacts" | "session" | "lifecycle"
    )


def _build_tool_registry() -> list[ToolEntry]:
    """Build the handoff MCP tool registry (called lazily after all handlers defined)."""
    _re = _WORKER_REASONING_EFFORT_CHOICES
    return [
        # Task state (2)
        ToolEntry(
            "set_handoff_state",
            set_handoff_state,
            TOOL_DESCRIPTIONS["set_handoff_state"],
            cli_name="set",
            cli_args=[
                ArgSpec("--task-ref", required=True),
                ArgSpec("--objective", help="Task objective."),
                ArgSpec("--focus", help="Mutable current-focus text."),
                ArgSpec("--status", default="in_progress"),
                ArgSpec("--expected-revision", type=int),
            ],
            surface_class="action",
            entity_family="handoff_state",
        ),
        ToolEntry(
            "get_handoff_state",
            get_handoff_state,
            TOOL_DESCRIPTIONS["get_handoff_state"],
            cli_name="state",
            cli_args=[
                ArgSpec("task_ref", nargs="?"),
                ArgSpec("--verbose", action="store_true"),
                ArgSpec(
                    "--sections",
                    help="Comma-separated sections to include (e.g. 'decisions_recent,findings_open'). Use 'identity' for identity-only (active + limits).",
                ),
                ArgSpec("--detail", default="full", choices=["full", "summary"], help="Detail level: full or summary"),
            ],
            surface_class="query",
            entity_family="handoff_state",
        ),
        # Decisions (1)
        ToolEntry(
            "record_decision",
            record_decision,
            TOOL_DESCRIPTIONS["record_decision"],
            cli_name="decision",
            cli_args=[
                ArgSpec("--session", required=True),
                ArgSpec("--decision", required=True),
                ArgSpec("--rationale"),
                ArgSpec("--task-ref"),
                ArgSpec(
                    "--changed-files",
                    nargs="+",
                    dest="changed_files",
                    help="Monorepo-relative paths touched by this slice.",
                ),
            ],
            surface_class="action",
            entity_family="handoff_state",
        ),
        # Actions (2)
        ToolEntry(
            "update_next_actions",
            update_next_actions,
            TOOL_DESCRIPTIONS["update_next_actions"],
            cli_name="action",
            cli_args=[
                ArgSpec("--operation", required=True, choices=["add", "update", "complete", "skip"]),
                ArgSpec("--action-id", type=int),
                ArgSpec("--text", dest="action", help="Action text (maps to handler param 'action')."),
                ArgSpec("--priority", type=int),
                ArgSpec("--status"),
                ArgSpec("--task-ref"),
            ],
            surface_class="action",
            entity_family="handoff_state",
        ),
        ToolEntry(
            "list_next_actions",
            list_next_actions,
            TOOL_DESCRIPTIONS["list_next_actions"],
            profile="extended",
            surface_class="query",
            entity_family="handoff_state",
        ),
        # Tests / blockers (2)
        ToolEntry(
            "record_test_result",
            record_test_result,
            TOOL_DESCRIPTIONS["record_test_result"],
            cli_name="test",
            cli_args=[
                ArgSpec("--session", required=True),
                # dest="command" matches the handler param directly; "command" is safe as an arg
                # dest because _build_parser() uses dest="subcommand" for the subparser, not "command".
                ArgSpec("--command", dest="command", help="Test command."),
                ArgSpec("--passed", action="store_true"),
                ArgSpec("--result"),
                ArgSpec("--exit-code", type=int),
                ArgSpec("--task-ref"),
            ],
            surface_class="action",
            entity_family="handoff_state",
        ),
        ToolEntry(
            "report_blocker",
            report_blocker,
            TOOL_DESCRIPTIONS["report_blocker"],
            cli_name="blocker",
            cli_args=[
                ArgSpec("--operation", required=True, choices=["add", "resolve", "reopen"]),
                ArgSpec("--description"),
                ArgSpec("--blocker-id", type=int),
                ArgSpec("--task-ref"),
            ],
            surface_class="action",
            entity_family="handoff_state",
        ),
        # Findings (4)
        ToolEntry(
            "record_review_finding",
            record_review_finding,
            TOOL_DESCRIPTIONS["record_review_finding"],
            cli_name="review-record",
            cli_args=[
                ArgSpec("--session", required=True),
                ArgSpec("--finding-id", required=True),
                ArgSpec("--severity", required=True),
                ArgSpec("--file-path", required=True),
                ArgSpec("--description", required=True),
                ArgSpec("--line-start", type=int),
                ArgSpec("--line-end", type=int),
                ArgSpec("--fix"),
                ArgSpec("--task-ref"),
            ],
            surface_class="action",
            entity_family="review_findings",
        ),
        ToolEntry(
            "batch_record_review_findings",
            batch_record_review_findings,
            TOOL_DESCRIPTIONS["batch_record_review_findings"],
            surface_class="action",
            entity_family="review_findings",
        ),
        ToolEntry(
            "update_review_finding",
            update_review_finding,
            TOOL_DESCRIPTIONS["update_review_finding"],
            cli_name="review-update",
            cli_args=[
                ArgSpec("--status", required=True),
                ArgSpec("--finding-id"),
                ArgSpec("--finding-db-id", type=int),
                ArgSpec("--resolution-notes"),
                ArgSpec("--reopen-reason"),
                ArgSpec("--verified-commit-sha"),
                ArgSpec("--verification-evidence"),
                ArgSpec("--task-ref"),
                ArgSpec("--session"),
            ],
            surface_class="action",
            entity_family="review_findings",
        ),
        ToolEntry(
            "list_review_findings",
            list_review_findings,
            TOOL_DESCRIPTIONS["list_review_findings"],
            cli_name="review-list",
            cli_args=[
                ArgSpec("--task-ref"),
                ArgSpec("--status", default="all"),
                ArgSpec("--severity", default="all"),
                ArgSpec("--limit", type=int, default=20),
                ArgSpec("--offset", type=int, default=0),
                ArgSpec("--detail", default="full", choices=["full", "summary"], help="Detail level: full or summary"),
            ],
            surface_class="query",
            entity_family="review_findings",
        ),
        # Review-run ledger (3)
        ToolEntry(
            "record_review_run",
            record_review_run,
            TOOL_DESCRIPTIONS["record_review_run"],
            cli_name="review-run-record",
            cli_args=[
                ArgSpec("--review-run-id", required=True),
                ArgSpec("--session", required=True),
                ArgSpec("--subject-path", required=True),
                ArgSpec("--subject-kind", default="task_plan"),
                ArgSpec("--review-mode", default="planning"),
                ArgSpec("--verdict"),
                ArgSpec("--verdict-decision"),
                ArgSpec("--task-ref"),
            ],
            surface_class="action",
            entity_family="review_runs",
        ),
        ToolEntry(
            "list_review_runs",
            list_review_runs,
            TOOL_DESCRIPTIONS["list_review_runs"],
            cli_name="review-run-list",
            cli_args=[
                ArgSpec("--task-ref"),
                ArgSpec("--subject-path"),
                ArgSpec("--review-mode"),
                ArgSpec("--verdict"),
                ArgSpec("--limit", type=int, default=20),
                ArgSpec("--offset", type=int, default=0),
            ],
            surface_class="query",
            entity_family="review_runs",
        ),
        ToolEntry(
            "get_review_coverage",
            get_review_coverage,
            TOOL_DESCRIPTIONS["get_review_coverage"],
            profile="extended",
            cli_name="review-coverage",
            cli_args=[
                ArgSpec("--task-ref"),
                ArgSpec("--subject-path"),
            ],
            surface_class="query",
            entity_family="review_runs",
        ),
        # Close check + CURRENT_TASK.md (2)
        ToolEntry(
            "handoff_close_check",
            handoff_close_check,
            TOOL_DESCRIPTIONS["handoff_close_check"],
            cli_name="handoff-close-check",
            cli_args=[
                ArgSpec("--task-ref"),
                ArgSpec("--allow-no-active-task", action="store_true"),
                ArgSpec("--enforce", action="store_true"),
                ArgSpec("--require-fresh-tests", action="store_true"),
                ArgSpec("--current-commit-sha"),
            ],
            surface_class="generator",
            entity_family="lifecycle",
        ),
        ToolEntry(
            "generate_current_task_md",
            generate_current_task_md,
            TOOL_DESCRIPTIONS["generate_current_task_md"],
            cli_name="task",
            cli_args=[
                ArgSpec("task_ref", nargs="?"),
                ArgSpec("--no-write", action="store_true"),
            ],
            surface_class="generator",
            entity_family="lifecycle",
        ),
        # Export / import / archive (3)
        ToolEntry(
            "export_handoff_state",
            export_handoff_state,
            TOOL_DESCRIPTIONS["export_handoff_state"],
            profile="extended",
            cli_name="export",
            cli_args=[
                ArgSpec("--task-ref"),
                ArgSpec("--output-path"),
                ArgSpec("--no-markdown", action="store_true"),
            ],
            surface_class="generator",
            entity_family="lifecycle",
        ),
        ToolEntry(
            "import_handoff_state",
            import_handoff_state,
            TOOL_DESCRIPTIONS["import_handoff_state"],
            profile="extended",
            cli_name="import",
            cli_args=[
                ArgSpec("--input-path", required=True),
                ArgSpec("--mode", default="merge"),
                ArgSpec("--set-active", action="store_true"),
                ArgSpec("--allow-destructive-clear", action="store_true"),
            ],
            surface_class="action",
            entity_family="lifecycle",
        ),
        ToolEntry(
            "archive_task_state",
            archive_task_state,
            TOOL_DESCRIPTIONS["archive_task_state"],
            profile="extended",
            cli_name="archive",
            cli_args=[
                ArgSpec("--task-ref"),
                ArgSpec("--notes"),
                ArgSpec("--clear-active-if-matches", action="store_true"),
                ArgSpec("--prune-working-rows", action="store_true"),
                ArgSpec("--allow-destructive-clear", action="store_true"),
            ],
            surface_class="action",
            entity_family="lifecycle",
        ),
        ToolEntry(
            "update_task_status",
            update_task_status,
            TOOL_DESCRIPTIONS["update_task_status"],
            profile="extended",
            cli_name="task-status",
            cli_args=[
                ArgSpec("--task-ref", required=True),
                ArgSpec("--status", required=True),
                ArgSpec("--expected-revision"),
            ],
            surface_class="action",
            entity_family="lifecycle",
        ),
        # Compound tools (3)
        ToolEntry(
            "load_session",
            load_session,
            TOOL_DESCRIPTIONS["load_session"],
            surface_class="query",
            entity_family="session",
        ),
        ToolEntry(
            "close_slice",
            close_slice,
            TOOL_DESCRIPTIONS["close_slice"],
            surface_class="action",
            entity_family="lifecycle",
        ),
        ToolEntry(
            "audit_decision_ids",
            audit_decision_ids,
            TOOL_DESCRIPTIONS["audit_decision_ids"],
            profile="extended",
            cli_name="audit-decisions",
            cli_args=[
                ArgSpec("--task-ref"),
                ArgSpec("--limit", type=int, default=50),
                ArgSpec(
                    "--include-categories",
                    nargs="+",
                    choices=["canonical", "legacy_slice", "malformed_slice", "freeform"],
                    dest="include_categories",
                    help="Categories to include in the violations list (default: malformed_slice freeform).",
                ),
            ],
            surface_class="query",
            entity_family="handoff_state",
        ),
        # Artifact tools (4)
        ToolEntry(
            "record_artifact",
            record_artifact,
            TOOL_DESCRIPTIONS["record_artifact"],
            profile="extended",
            cli_name="artifact-record",
            cli_args=[
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id"),
                ArgSpec("--app-root"),
                ArgSpec("--source-kind", required=True),
                ArgSpec("--source-label", required=True),
                ArgSpec("--content-type", default="text/plain"),
                ArgSpec("--summary"),
                ArgSpec("--content-file", help="Path to a file whose contents will be used as the artifact content."),
                ArgSpec("--content", help="Artifact content as a string."),
            ],
            surface_class="action",
            entity_family="artifacts",
        ),
        ToolEntry(
            "search_artifacts",
            search_artifacts,
            TOOL_DESCRIPTIONS["search_artifacts"],
            profile="extended",
            cli_name="artifact-search",
            cli_args=[
                ArgSpec("--query", action="append", dest="queries", required=True, help="Search term (repeatable)."),
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id"),
                ArgSpec("--app-root"),
                ArgSpec("--source-kind"),
                ArgSpec("--content-type"),
                ArgSpec("--limit", type=int, default=10),
                ArgSpec("--detail", default="full", choices=["full", "summary"], help="Detail level: full or summary"),
                ArgSpec("--fields", help="Comma-separated fields to keep in each search hit."),
            ],
            surface_class="generator",
            entity_family="artifacts",
        ),
        ToolEntry(
            "get_artifact",
            get_artifact,
            TOOL_DESCRIPTIONS["get_artifact"],
            profile="extended",
            cli_name="artifact-get",
            cli_args=[
                ArgSpec("--source-id", type=int),
                ArgSpec("--task-ref"),
                ArgSpec("--source-label"),
                ArgSpec("--detail", default="full", choices=["full", "summary"], help="Detail level: full or summary"),
                ArgSpec("--fields", help="Comma-separated fields to keep in the returned source."),
            ],
            surface_class="query",
            entity_family="artifacts",
        ),
        ToolEntry(
            "purge_artifacts",
            purge_artifacts,
            TOOL_DESCRIPTIONS["purge_artifacts"],
            profile="extended",
            cli_name="artifact-purge",
            cli_args=[
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id"),
                ArgSpec("--app-root"),
                ArgSpec("--older-than-days", type=int),
            ],
            surface_class="action",
            entity_family="artifacts",
        ),
        # Search (1)
        ToolEntry(
            "search_handoff",
            search_handoff,
            TOOL_DESCRIPTIONS["search_handoff"],
            profile="extended",
            cli_name="handoff-search",
            surface_class="generator",
            entity_family="handoff_state",
            cli_args=[
                ArgSpec(
                    "--query",
                    action="append",
                    dest="queries",
                    help="Search term (repeatable; multiple terms are OR-joined). At least one required.",
                ),
                ArgSpec("--task-ref", help="Scope results to a specific task."),
                ArgSpec("--lane-id", help="Scope results to a specific lane."),
                ArgSpec(
                    "--record-types",
                    nargs="+",
                    choices=["decision", "finding", "blocker", "action"],
                    help="Limit search to these record types (decision, finding, blocker, action).",
                ),
                ArgSpec("--limit", type=int, default=20, help="Max results (default 20, max 100)."),
                ArgSpec("--detail", default="full", choices=["full", "summary"], help="Detail level: full or summary"),
                ArgSpec("--fields", help="Comma-separated fields to keep in each result row."),
            ],
        ),
    ]


def generate_current_task_md(
    task_ref: str | None = None,
    write_file: bool = True,
) -> str:
    """Generate CURRENT_TASK.md for the active task.

    Args:
        task_ref: The task to render. Defaults to the active task.
        write_file: Write the markdown to disk.

    Open review findings from all other tasks are always included in the
    rendered output, grouped by task_ref under "## Open Review Findings".
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
    with core._get_db_connection() as conn:
        state["dashboard_tasks"] = core._collect_dashboard_rows(conn)
        state["related_findings_open"] = core._collect_all_open_findings(conn, active_task_ref=state.get("task_ref"))
        state["related_findings_deferred"] = core._collect_all_deferred_findings(
            conn, active_task_ref=state.get("task_ref")
        )
        if state.get("task_ref"):
            try:
                from .review_findings import _collect_review_coverage  # noqa: PLC0415

                state["review_coverage"] = _collect_review_coverage(conn, task_ref=state["task_ref"])
            except Exception:
                pass

    # If the requested task is not currently active, hydrate `active` from the
    # archived snapshot so the renderer can display the objective, focus, and
    # status instead of producing an empty stub.
    if state.get("active") is None and task_ref is not None:
        resolved_ref = state.get("task_ref", task_ref)
        with core._get_db_connection() as conn:
            archive_row = conn.execute(
                "SELECT snapshot_json FROM task_archives WHERE task_ref = ?",
                (resolved_ref,),
            ).fetchone()
            if archive_row is not None:
                archived_snapshot = json.loads(archive_row["snapshot_json"])
                state["active"] = archived_snapshot.get("active")

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
    _apply_tool_descriptions()
    for entry in _build_tool_registry():
        if config.tool_profile == "core" and entry.profile == "extended":
            continue
        if entry.deprecated_since is not None:
            entry.handler.__doc__ = f"[DEPRECATED since {entry.deprecated_since}] " + (
                entry.handler.__doc__ or entry.description
            )
        mcp.add_tool(entry.handler)
    return mcp


def run_doctor(config: RuntimeConfig) -> dict[str, Any]:
    configure_runtime(config)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    config.exports_dir.mkdir(parents=True, exist_ok=True)

    # FTS5 availability check - hard requirement for artifact indexing
    import sqlite3 as _sqlite3

    with _sqlite3.connect(":memory:") as _fts5_probe:
        try:
            _fts5_probe.execute("CREATE VIRTUAL TABLE _fts5_test USING fts5(body)")
            _fts5_probe.execute("DROP TABLE IF EXISTS _fts5_test")
            fts5_available = True
        except _sqlite3.OperationalError:
            fts5_available = False
    if not fts5_available:
        raise RuntimeError(
            "SQLite FTS5 extension is not available on this system. "
            "agent-handoff-mcp artifact indexing requires FTS5. "
            "Rebuild SQLite with SQLITE_ENABLE_FTS5 or use a Python distribution "
            "that bundles FTS5 (e.g. system Python on macOS 10.15+ or major Linux distros)."
        )

    writable_probe = config.state_dir / ".write-test"
    writable_probe.write_text("ok")
    writable_probe.unlink()
    _FTS_TABLES = ("decisions_fts", "findings_fts", "blockers_fts", "actions_fts")
    handoff_fts_check: dict[str, Any] = {}
    with core._get_db_connection() as conn:
        conn.execute("SELECT 1").fetchone()
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?,?)",
                _FTS_TABLES,
            ).fetchall()
        }
        table_counts: dict[str, int] = {}
        for tbl in _FTS_TABLES:
            if tbl in existing:
                count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]  # noqa: S608
                table_counts[tbl] = count
            else:
                table_counts[tbl] = -1  # -1 signals table missing

        handoff_fts_check = {
            "ok": all(v >= 0 for v in table_counts.values()),
            "tables": table_counts,
        }

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

        _package_root = Path(__file__).resolve().parents[4]
        _pythonpath_parts = [
            str(_package_root / "packages" / "agent-handoff-mcp" / "src"),
            str(_package_root / "packages" / "codex-subagent-bridge" / "src"),
        ]
        _existing_pp = os.environ.get("PYTHONPATH")
        if _existing_pp:
            _pythonpath_parts.append(_existing_pp)
        cli_env = dict(**os.environ)
        cli_env["PYTHONPATH"] = ":".join(p for p in _pythonpath_parts if p)
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

    _registry = _build_tool_registry()
    _core_count = sum(1 for e in _registry if e.profile == "core")
    _extended_count = sum(1 for e in _registry if e.profile == "extended")

    # Portable hook semantics discovery: enumerate defined hooks and check
    # for observable evidence of each one's durable output in this workspace.
    ace_reflect_log = config.state_dir / "ace_reflect_log.jsonl"
    worker_log_dir = config.workspace_root / "logs" / "worker-daemon"
    worker_logs_found = any(worker_log_dir.glob("worker-*.jsonl")) if worker_log_dir.exists() else False
    portable_hook_semantics = [
        {
            "name": "after_review_findings_recorded",
            "trigger": "worker-daemon review turn produces new findings",
            "durable_output": ".task-state/ace_reflect_log.jsonl",
            "evidence_path": str(ace_reflect_log),
            "evidence_found": ace_reflect_log.exists(),
        },
        {
            "name": "before_close_check",
            "trigger": "handoff_close_check() is invoked",
            "durable_output": "structured readiness verdict returned synchronously",
            "evidence_path": "MCP tool handoff_close_check (always registered)",
            "evidence_found": True,
        },
        {
            "name": "after_worker_turn",
            "trigger": "worker execution turn completes",
            "durable_output": "logs/worker-daemon/worker-<lane>.jsonl",
            "evidence_path": str(worker_log_dir),
            "evidence_found": worker_logs_found,
        },
        {
            "name": "after_task_switch",
            "trigger": "switch_task() completes",
            "durable_output": "CURRENT_TASK.md regenerated for new active task",
            "evidence_path": str(config.current_task_path),
            "evidence_found": config.current_task_path.exists(),
        },
        {
            "name": "before_review_prompt_build",
            "trigger": "orchestrator or review_runner prepares review prompt for a worker turn",
            "durable_output": "scope_violation event in worker JSONL; prompt metadata in worker_event_history",
            "evidence_path": str(worker_log_dir),
            "evidence_found": worker_logs_found,
        },
    ]

    return {
        "ok": True,
        "workspace_root": str(config.workspace_root),
        "state_dir": str(config.state_dir),
        "db_path": str(config.db_path),
        "artifact_db_path": str(config.artifact_db_path),
        "current_task_path": str(config.current_task_path),
        "exports_dir": str(config.exports_dir),
        "checks": {
            "sqlite": True,
            "fts5_available": True,
            "state_dir_writable": True,
            "handoff_fts_index": handoff_fts_check,
            "stdio_startup": {
                "ok": True,
                "tool_count": len(stdio_tools),
                "tool_profile": config.tool_profile,
                "registry_counts": {
                    "core": _core_count,
                    "extended": _extended_count,
                    "total": len(_registry),
                },
            },
            "cli_fallback_startup": True,
        },
        "portable_hook_semantics": portable_hook_semantics,
    }
