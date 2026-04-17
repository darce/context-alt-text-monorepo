from __future__ import annotations

import asyncio
import functools
import inspect
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, cast

from fastmcp import FastMCP
from fastmcp.client import Client, PythonStdioTransport
from pydantic import BaseModel, Field, TypeAdapter

from . import core
from ._shared import WriteActor
from .config import RuntimeConfig
from .core import PromptMetrics, ResolvedWriteContext, ReviewFindingDetails, TokenUsage
from .review_findings import BatchFindingItem, merge_review_findings
from .runtime import configure_runtime, get_runtime_config, reset_runtime_config
from .shared_write_context import BranchMismatchError

_core_record_decision = core.record_decision
build_write_actor = core.build_write_actor
_core_update_next_actions = core.update_next_actions
_core_record_test_result = core.record_test_result
_core_report_blocker = core.report_blocker
record_review_finding = core.record_review_finding
batch_record_review_findings = core.batch_record_review_findings
_core_update_review_finding = core.update_review_finding
repair_review_finding_provenance = core.repair_review_finding_provenance
_core_repair_review_finding_provenance = repair_review_finding_provenance
list_review_findings = core.list_review_findings
_core_record_review_run = core.record_review_run
list_review_runs = core.list_review_runs
get_review_coverage = core.get_review_coverage
handoff_close_check = core.handoff_close_check
export_handoff_state = core.export_handoff_state
import_handoff_state = core.import_handoff_state
archive_task_state = core.archive_task_state
get_archived_task = core.get_archived_task
switch_task = core.switch_task
_core_update_task_status = core.update_task_status
_core_set_handoff_state = core.set_handoff_state
get_handoff_state = core.get_handoff_state
list_next_actions = core.list_next_actions
record_file_touch = core.record_file_touch
get_touched_files = core.get_touched_files

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
    "get_handoff_state": "Read task handoff summary (blockers, actions, findings). Pass sections='decisions_recent,findings_open' to select specific sections; active and limits are always included. Pass sections='identity' for an identity-only response (active + limits, no data sections). Pass detail='summary' to truncate long rationale and verification fields.",
    "record_event": "Record a decision, verification result, or blocker mutation through one typed event surface. Set event.event_kind to 'decision', 'test_result', or 'blocker' to select the required fields.",
    "next_actions": "List or mutate next-action items through one typed domain surface. Set action.operation to 'list', 'add', 'update', 'complete', or 'skip'.",
    "review_findings": "Record, batch record, update, repair provenance, merge, or list review findings through one typed domain surface. Set review.operation to 'record', 'batch_record', 'update', 'repair_provenance', 'merge', or 'list'. The 'repair_provenance' operation is the bounded admin path for fixing a finding row whose source branch/commit_sha was attributed to the wrong commit (e.g. the reviewer's workspace HEAD instead of the actual buggy code's commit) — see ReviewFindingsRepairProvenanceOp. The 'merge' operation (coordinator-centric, additive) re-records findings from one or more source task_refs under a target coordinator task_ref with merged_from provenance — see ReviewFindingsMergeOp.",
    "review_runs": "Record, list, or summarize review-run coverage through one typed domain surface. Set review.operation to 'record', 'list', or 'coverage'.",
    "handoff_close_check": "Check task readiness to close: blockers, pending actions, findings, and optional fresh-test gate.",
    "audit_decision_ids": "Audit decision IDs for grammar conformance. Returns canonical/malformed/freeform classifications.",
    "render_handoff": (
        "Render the handoff surface files through one compound tool. "
        "Set kind='current_task' to produce the machine-readable CURRENT_TASK.json "
        "snapshot for the active task; set kind='dashboard' to produce DASHBOARD.txt — "
        "the human-scoped observatory view with Needs Attention summary, All Tasks table, "
        "cross-task open findings, and optional extension sections (e.g. Lane Health from "
        "agent-orchestrator-mcp)."
    ),
    "export_handoff_state": "Export the task handoff state to a portable JSON snapshot.",
    "import_handoff_state": "Import a previously exported handoff state snapshot into the local database.",
    "archive_task_state": "Archive completed task state from the live handoff tables into archive storage.",
    "get_archived_task": "Read an archived task row from task_archives by task_ref. Returns archive metadata (archived_at/archived_by/archived_branch/archived_commit_sha/notes) plus the parsed snapshot when include_snapshot=True. Use this to inspect a task's terminal state without dropping to raw sqlite.",
    "get_verified_tests": "List verified test rows from the handoff ledger with optional task, lane, branch, commit, pass/fail, trace, and changed-file correlation filters.",
    "record_file_touch": "Record one task-scoped file touch row for a file path and change kind. Append-only surface for the file-touch ledger.",
    "get_touched_files": "List task-scoped file-touch rows with deterministic newest-first ordering and a bounded limit.",
    "update_task_status": "Update a task status without recording a slice decision. For the active task this requires expected_revision; for archived tasks it updates the archived snapshot status used by the dashboard.",
    "load_session": "Load session context: get_handoff_state + review_findings(list open) + touched_files in one call. Pass sections to shape the nested state payload, detail to shape both state and findings, and top_n_touched_files (default 20, max 200) to bound the additive touched_files list.",
    "close_slice": "Record a slice-complete decision, keep the task status in_progress, and regenerate CURRENT_TASK.json plus DASHBOARD.txt. Requires expected_revision when the target task is currently active. Pass changed_files to persist structured review scope on the nested decision write.",
    "artifacts": "Record, search, get, or purge artifact sources through one typed domain surface. Set artifact.operation to 'record', 'search', 'get', or 'purge'.",
    "search_handoff": "Search decisions, findings, blockers, actions, and verified tests by keyword with BM25 ranking. Pass detail='summary' to truncate snippets and fields='record_type,snippet' to project per-result fields.",
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


class RecordDecisionEvent(BaseModel):
    event_kind: Literal["decision"]
    session: Annotated[str, Field(description="Session identifier for the decision write.")]
    decision: Annotated[str, Field(description="Stable decision identifier to persist in the ledger.")]
    rationale: Annotated[
        str | None,
        Field(
            description=(
                "Optional markdown rationale. Soft limit: 1,500 chars; hard limit: 3,000 chars "
                "(enforced by hook before call reaches server). For slice_complete_* decisions "
                "use close_slice, which enforces required sections."
            )
        ),
    ] = None
    actor: ActorParam = None
    task_ref: TaskRefParam = None
    input_tokens: Annotated[int | None, Field(description="Optional prompt token count for this slice.")] = None
    output_tokens: Annotated[int | None, Field(description="Optional completion token count for this slice.")] = None
    total_tokens: Annotated[int | None, Field(description="Optional total token count for this slice.")] = None
    changed_files: DecisionChangedFilesParam = None


class RecordTestResultEvent(BaseModel):
    event_kind: Literal["test_result"]
    session: Annotated[str, Field(description="Session identifier for the verification run.")]
    command: Annotated[str, Field(description="Verification command that was executed.")]
    passed: Annotated[bool, Field(description="Whether the verification command passed.")]
    result: Annotated[
        str | None,
        Field(description="Optional stdout or summarized verification evidence for the command."),
    ] = None
    traces: Annotated[
        list[str] | None,
        Field(description="Optional raw verification trace payloads to archive alongside the summarized result."),
    ] = None
    exit_code: Annotated[int | None, Field(description="Optional process exit code for the command.")] = None
    actor: ActorParam = None
    task_ref: TaskRefParam = None


class ReportBlockerEvent(BaseModel):
    event_kind: Literal["blocker"]
    operation: Annotated[
        Literal["add", "resolve", "reopen"],
        Field(description="Blocker mutation to perform."),
    ]
    description: Annotated[
        str | None,
        Field(description="Blocker description. Required when adding a new blocker."),
    ] = None
    blocker_id: Annotated[
        int | None,
        Field(description="Existing blocker id. Required for resolve and reopen."),
    ] = None
    actor: ActorParam = None
    task_ref: TaskRefParam = None


RecordEventParam = Annotated[
    RecordDecisionEvent | RecordTestResultEvent | ReportBlockerEvent,
    Field(discriminator="event_kind"),
]

_RECORD_EVENT_ADAPTER: TypeAdapter[RecordDecisionEvent | RecordTestResultEvent | ReportBlockerEvent] = TypeAdapter(
    RecordEventParam
)


class ReviewFindingDetailsInput(BaseModel):
    line_start: Annotated[int | None, Field(description="Optional 1-based start line for the finding.")] = None
    line_end: Annotated[int | None, Field(description="Optional 1-based end line for the finding.")] = None
    fix: Annotated[str | None, Field(description="Optional suggested fix text.")] = None


class ReviewFindingBatchItemInput(BaseModel):
    finding_id: Annotated[str, Field(description="Stable finding identifier to persist or reopen.")]
    severity: Annotated[Literal["high", "medium", "low"], Field(description="Finding severity.")]
    file_path: Annotated[str, Field(description="Workspace-relative file path for the finding.")]
    description: Annotated[str, Field(description="Human-readable finding description.")]
    review_mode: Annotated[
        Literal["branch", "release_audit", "planning"] | None,
        Field(description="Optional review mode label for the finding."),
    ] = None
    details: Annotated[
        ReviewFindingDetailsInput | None,
        Field(description="Optional structured line/fix metadata for the finding."),
    ] = None


class ReviewFindingsRecordOp(BaseModel):
    operation: Literal["record"]
    session: Annotated[str, Field(description="Session identifier for the review-finding write.")]
    finding_id: Annotated[str, Field(description="Stable finding identifier to persist or reopen.")]
    severity: Annotated[Literal["high", "medium", "low"], Field(description="Finding severity.")]
    file_path: Annotated[str, Field(description="Workspace-relative file path for the finding.")]
    description: Annotated[str, Field(description="Human-readable finding description.")]
    details: Annotated[
        ReviewFindingDetailsInput | None,
        Field(description="Optional structured line/fix metadata for the finding."),
    ] = None
    actor: ActorParam = None
    task_ref: TaskRefParam = None
    review_mode: Annotated[
        Literal["branch", "release_audit", "planning"] | None,
        Field(description="Optional review mode label for the finding."),
    ] = None


class ReviewFindingsBatchRecordOp(BaseModel):
    operation: Literal["batch_record"]
    session: Annotated[str, Field(description="Session identifier for the batch review-finding write.")]
    findings: Annotated[
        list[ReviewFindingBatchItemInput],
        Field(description="One or more review findings to write atomically."),
    ]
    actor: ActorParam = None
    task_ref: TaskRefParam = None


class ReviewFindingsUpdateOp(BaseModel):
    operation: Literal["update"]
    status: Annotated[
        Literal["open", "fixed", "deferred", "wontfix"],
        Field(description="New finding status to apply."),
    ]
    finding_id: Annotated[str | None, Field(description="Stable finding identifier to update.")] = None
    finding_db_id: Annotated[int | None, Field(description="Numeric finding id to update.")] = None
    resolution_notes: Annotated[
        str | None,
        Field(description="Optional notes describing how the finding was resolved or dispositioned."),
    ] = None
    reopen_reason: Annotated[
        str | None,
        Field(description="Required when moving a non-open finding back to open."),
    ] = None
    task_ref: TaskRefParam = None
    session: Annotated[str | None, Field(description="Optional session identifier for the update.")] = None
    actor: ActorParam = None
    verified_commit_sha: Annotated[
        str | None,
        Field(description="Optional commit SHA that verified a fixed finding."),
    ] = None
    verification_evidence: Annotated[
        str | None,
        Field(description="Optional verification evidence used when closing a finding as fixed."),
    ] = None


class ReviewFindingsRepairProvenanceOp(BaseModel):
    operation: Literal["repair_provenance"]
    session: Annotated[
        str,
        Field(description="Session identifier for the repair audit-trail decision row."),
    ]
    finding_id: Annotated[
        str,
        Field(description="Stable finding identifier of the row whose source branch/commit_sha must be repaired."),
    ]
    expected_branch: Annotated[
        str,
        Field(
            description="The branch currently stored on the row. The repair refuses to apply unless this matches exactly — concurrency / mistake guard."
        ),
    ]
    expected_commit_sha: Annotated[
        str,
        Field(
            description="The commit_sha currently stored on the row (full or abbreviated; auto-expanded). Must match exactly after expansion."
        ),
    ]
    new_branch: Annotated[
        str,
        Field(description="The corrected branch the row should reference."),
    ]
    new_commit_sha: Annotated[
        str,
        Field(
            description="The corrected commit_sha. Validated against the active git repo and auto-expanded to its 40-char form."
        ),
    ]
    reason: Annotated[
        str,
        Field(
            description="At least 20 characters explaining why the original attribution was wrong. Recorded in the audit decision row.",
            min_length=20,
        ),
    ]
    task_ref: TaskRefParam = None
    actor: ActorParam = None


class ReviewFindingsMergeOp(BaseModel):
    operation: Literal["merge"]
    source_task_refs: Annotated[
        list[str],
        Field(
            description=(
                "Non-empty list of source task_refs whose review findings should be merged "
                "into the coordinator target_task_ref. Duplicate entries are deduplicated."
            )
        ),
    ]
    target_task_ref: Annotated[
        str,
        Field(description="Coordinator task_ref under which the merged rows should live."),
    ]
    session: Annotated[
        str | None,
        Field(
            description=(
                "Optional session prefix for merged rows. When omitted, auto-generated "
                "as merge-<target_task_ref>-<utc-ts>."
            )
        ),
    ] = None
    actor: ActorParam = None


class ReviewFindingsListOp(BaseModel):
    operation: Literal["list"]
    task_ref: TaskRefParam = None
    status: Annotated[str, Field(description="Finding status filter.")] = "all"
    severity: Annotated[str, Field(description="Finding severity filter.")] = "all"
    limit: Annotated[int, Field(description="Maximum number of findings to return.")] = 100
    offset: Annotated[int, Field(description="Pagination offset.")] = 0
    review_mode: Annotated[
        Literal["branch", "release_audit", "planning"] | None,
        Field(description="Optional review-mode filter."),
    ] = None
    finding_id: Annotated[str | None, Field(description="Optional stable finding identifier lookup.")] = None
    finding_db_id: Annotated[int | None, Field(description="Optional numeric finding id lookup.")] = None
    detail: Annotated[
        Literal["full", "summary"],
        Field(description="Detail level for returned finding rows."),
    ] = "full"


ReviewFindingsParam = Annotated[
    ReviewFindingsRecordOp
    | ReviewFindingsBatchRecordOp
    | ReviewFindingsUpdateOp
    | ReviewFindingsRepairProvenanceOp
    | ReviewFindingsMergeOp
    | ReviewFindingsListOp,
    Field(discriminator="operation"),
]

_REVIEW_FINDINGS_ADAPTER: TypeAdapter[
    ReviewFindingsRecordOp
    | ReviewFindingsBatchRecordOp
    | ReviewFindingsUpdateOp
    | ReviewFindingsRepairProvenanceOp
    | ReviewFindingsMergeOp
    | ReviewFindingsListOp
] = TypeAdapter(ReviewFindingsParam)


class ReviewRunsRecordOp(BaseModel):
    operation: Literal["record"]
    review_run_id: Annotated[str, Field(description="Globally unique review run identifier.")]
    session: Annotated[str, Field(description="Session identifier for the review run.")]
    subject_path: Annotated[str, Field(description="Workspace-relative path reviewed in this run.")]
    subject_kind: Annotated[
        Literal["task_plan", "epic", "branch", "adr", "roadmap", "other"],
        Field(description="Kind of artifact reviewed in this run."),
    ] = "task_plan"
    review_mode: Annotated[
        Literal["branch", "release_audit", "planning"],
        Field(description="Review mode label, for example planning or branch."),
    ] = "planning"
    verdict: Annotated[
        Literal["pass", "pass_with_findings", "fail", "conditional_pass"] | None,
        Field(description="Optional review verdict to store with the run."),
    ] = None
    verdict_decision: Annotated[
        str | None,
        Field(description="Optional decision id or summary that explains the verdict."),
    ] = None
    task_ref: TaskRefParam = None
    actor: ActorParam = None


class ReviewRunsListOp(BaseModel):
    operation: Literal["list"]
    task_ref: TaskRefParam = None
    subject_path: Annotated[str | None, Field(description="Optional reviewed artifact path filter.")] = None
    limit: Annotated[int, Field(description="Maximum number of review runs to return.")] = 20
    offset: Annotated[int, Field(description="Pagination offset.")] = 0
    review_mode: Annotated[
        Literal["branch", "release_audit", "planning"] | None,
        Field(description="Optional review-mode filter."),
    ] = None
    verdict: Annotated[
        Literal["pass", "pass_with_findings", "fail", "conditional_pass"] | None,
        Field(description="Optional verdict filter."),
    ] = None


class ReviewRunsCoverageOp(BaseModel):
    operation: Literal["coverage"]
    task_ref: TaskRefParam = None
    subject_path: Annotated[str | None, Field(description="Optional reviewed artifact path scope.")] = None


ReviewRunsParam = Annotated[
    ReviewRunsRecordOp | ReviewRunsListOp | ReviewRunsCoverageOp,
    Field(discriminator="operation"),
]

_REVIEW_RUNS_ADAPTER: TypeAdapter[ReviewRunsRecordOp | ReviewRunsListOp | ReviewRunsCoverageOp] = TypeAdapter(
    ReviewRunsParam
)


class NextActionsAddOp(BaseModel):
    operation: Literal["add"]
    action: Annotated[str, Field(description="Action text to add.")]
    priority: Annotated[
        int | None,
        Field(description="Optional priority value. Lower numbers sort first; defaults to 100 on add."),
    ] = None
    actor: ActorParam = None
    task_ref: TaskRefParam = None


class NextActionsUpdateOp(BaseModel):
    operation: Literal["update"]
    action_id: Annotated[int, Field(description="Existing action id to update.")]
    action: Annotated[str | None, Field(description="Optional replacement action text.")] = None
    priority: Annotated[int | None, Field(description="Optional replacement priority value.")] = None
    status: Annotated[
        Literal["pending", "done", "skipped"] | None,
        Field(description="Optional explicit status override. Only used for update operations."),
    ] = None
    actor: ActorParam = None
    task_ref: TaskRefParam = None


class NextActionsCompleteOp(BaseModel):
    operation: Literal["complete"]
    action_id: Annotated[int, Field(description="Existing action id to mark complete.")]
    actor: ActorParam = None
    task_ref: TaskRefParam = None


class NextActionsSkipOp(BaseModel):
    operation: Literal["skip"]
    action_id: Annotated[int, Field(description="Existing action id to skip.")]
    actor: ActorParam = None
    task_ref: TaskRefParam = None


class NextActionsListOp(BaseModel):
    operation: Literal["list"]
    task_ref: TaskRefParam = None
    lane_id: Annotated[str | None, Field(description="Optional lane filter.")] = None
    status: Annotated[
        Literal["all", "pending", "done", "skipped"],
        Field(description="Action status filter."),
    ] = "all"
    limit: Annotated[int, Field(description="Maximum number of actions to return.")] = 100
    offset: Annotated[int, Field(description="Pagination offset.")] = 0


NextActionsParam = Annotated[
    NextActionsAddOp | NextActionsUpdateOp | NextActionsCompleteOp | NextActionsSkipOp | NextActionsListOp,
    Field(discriminator="operation"),
]

_NEXT_ACTIONS_ADAPTER: TypeAdapter[
    NextActionsAddOp | NextActionsUpdateOp | NextActionsCompleteOp | NextActionsSkipOp | NextActionsListOp
] = TypeAdapter(NextActionsParam)


class ArtifactsRecordOp(BaseModel):
    operation: Literal["record"]
    source_kind: Annotated[str, Field(description="Artifact source kind.")]
    source_label: Annotated[str, Field(description="Artifact source label.")]
    content: Annotated[str, Field(description="Artifact content to index.")]
    task_ref: TaskRefParam = None
    lane_id: Annotated[str | None, Field(description="Optional lane scope.")] = None
    app_root: Annotated[str | None, Field(description="Optional application root scope.")] = None
    content_type: Annotated[str, Field(description="Artifact content type.")] = "text/plain"
    summary: Annotated[str | None, Field(description="Optional artifact summary.")] = None
    metadata: Annotated[dict[str, Any] | None, Field(description="Optional structured metadata.")] = None


class ArtifactsSearchOp(BaseModel):
    operation: Literal["search"]
    queries: Annotated[
        list[str] | None,
        Field(description="Optional search queries. Omit or pass empty to list sources."),
    ] = None
    task_ref: TaskRefParam = None
    lane_id: Annotated[str | None, Field(description="Optional lane scope.")] = None
    app_root: Annotated[str | None, Field(description="Optional application root scope.")] = None
    source_kind: Annotated[str | None, Field(description="Optional source-kind filter.")] = None
    content_type: Annotated[str | None, Field(description="Optional content-type filter.")] = None
    limit: Annotated[int, Field(description="Maximum number of hits or sources to return.")] = 10
    offset: Annotated[int, Field(description="Pagination offset.")] = 0
    detail: Annotated[Literal["full", "summary"], Field(description="Detail level for returned rows.")] = "full"
    fields: Annotated[str | None, Field(description="Optional comma-separated field projection.")] = None


class ArtifactsGetOp(BaseModel):
    operation: Literal["get"]
    source_id: Annotated[int | None, Field(description="Optional numeric source id lookup.")] = None
    task_ref: TaskRefParam = None
    source_label: Annotated[str | None, Field(description="Optional source label lookup within a task.")] = None
    include_terms: Annotated[bool, Field(description="Whether to include distinctive terms.")] = False
    top_n_terms: Annotated[int, Field(description="Maximum number of distinctive terms to return.")] = 10
    detail: Annotated[Literal["full", "summary"], Field(description="Detail level for the returned source.")] = "full"
    fields: Annotated[str | None, Field(description="Optional comma-separated field projection.")] = None


class ArtifactsPurgeOp(BaseModel):
    operation: Literal["purge"]
    task_ref: TaskRefParam = None
    lane_id: Annotated[str | None, Field(description="Optional lane scope.")] = None
    app_root: Annotated[str | None, Field(description="Optional application root scope.")] = None
    older_than_days: Annotated[int | None, Field(description="Optional age cutoff in days.")] = None


ArtifactsParam = Annotated[
    ArtifactsRecordOp | ArtifactsSearchOp | ArtifactsGetOp | ArtifactsPurgeOp,
    Field(discriminator="operation"),
]

_ARTIFACTS_ADAPTER: TypeAdapter[ArtifactsRecordOp | ArtifactsSearchOp | ArtifactsGetOp | ArtifactsPurgeOp] = (
    TypeAdapter(ArtifactsParam)
)


def _dump_actor(actor: WriteActorInput | dict[str, Any] | None) -> WriteActor | None:
    if actor is None:
        return None
    actor_model = WriteActorInput.model_validate(actor) if isinstance(actor, dict) else actor
    return cast(
        WriteActor,
        {key: value for key, value in actor_model.model_dump(exclude_none=True).items() if isinstance(value, str)},
    )


def _validate_record_event(
    event: RecordEventParam | dict[str, Any],
) -> RecordDecisionEvent | RecordTestResultEvent | ReportBlockerEvent:
    return _RECORD_EVENT_ADAPTER.validate_python(event)


def _dump_review_finding_details(details: ReviewFindingDetailsInput | dict[str, Any] | None) -> dict[str, Any] | None:
    if details is None:
        return None
    details_model = ReviewFindingDetailsInput.model_validate(details) if isinstance(details, dict) else details
    payload = details_model.model_dump(exclude_none=True)
    return payload or None


def _dump_batch_review_finding_item(item: ReviewFindingBatchItemInput) -> dict[str, Any]:
    payload = item.model_dump(exclude_none=True)
    if item.details is not None:
        payload["details"] = _dump_review_finding_details(item.details)
    return payload


def _validate_review_findings(
    review: ReviewFindingsParam | dict[str, Any],
) -> (
    ReviewFindingsRecordOp
    | ReviewFindingsBatchRecordOp
    | ReviewFindingsUpdateOp
    | ReviewFindingsRepairProvenanceOp
    | ReviewFindingsMergeOp
    | ReviewFindingsListOp
):
    return _REVIEW_FINDINGS_ADAPTER.validate_python(review)


def _validate_review_runs(
    review: ReviewRunsParam | dict[str, Any],
) -> ReviewRunsRecordOp | ReviewRunsListOp | ReviewRunsCoverageOp:
    return _REVIEW_RUNS_ADAPTER.validate_python(review)


def _validate_next_actions(
    action: NextActionsParam | dict[str, Any],
) -> NextActionsAddOp | NextActionsUpdateOp | NextActionsCompleteOp | NextActionsSkipOp | NextActionsListOp:
    return _NEXT_ACTIONS_ADAPTER.validate_python(action)


def _validate_artifacts(
    artifact: ArtifactsParam | dict[str, Any],
) -> ArtifactsRecordOp | ArtifactsSearchOp | ArtifactsGetOp | ArtifactsPurgeOp:
    return _ARTIFACTS_ADAPTER.validate_python(artifact)


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
    target_branch: Annotated[
        str | None,
        Field(description="Target git branch for this task. Preserved on update when omitted."),
    ] = None,
    target_worktree_path: Annotated[
        str | None,
        Field(
            description=(
                "Absolute filesystem path of the linked worktree where this task should be implemented. "
                "Used by `make context` and write-side guards to fail-fast when an agent runs from the wrong "
                "directory. Preserved on update when omitted."
            )
        ),
    ] = None,
) -> dict:
    return _core_set_handoff_state(
        task_ref=task_ref,
        objective=objective,
        focus=focus,
        status=status,
        expected_revision=expected_revision,
        actor=_dump_actor(actor),
        target_branch=target_branch,
        target_worktree_path=target_worktree_path,
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
) -> dict:
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
) -> dict:
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


def record_event(
    event: Annotated[
        RecordEventParam,
        Field(
            description="Typed event payload. event_kind selects one of the decision, test_result, or blocker variants."
        ),
    ],
) -> dict:
    event_payload = _validate_record_event(event)
    resolved_actor = _dump_actor(event_payload.actor)
    if isinstance(event_payload, RecordDecisionEvent):
        return _core_record_decision(
            session=event_payload.session,
            decision=event_payload.decision,
            rationale=event_payload.rationale,
            actor=resolved_actor,
            task_ref=event_payload.task_ref,
            input_tokens=event_payload.input_tokens,
            output_tokens=event_payload.output_tokens,
            total_tokens=event_payload.total_tokens,
            changed_files=event_payload.changed_files,
        )
    if isinstance(event_payload, RecordTestResultEvent):
        return _core_record_test_result(
            session=event_payload.session,
            command=event_payload.command,
            passed=event_payload.passed,
            result=event_payload.result,
            traces=event_payload.traces,
            exit_code=event_payload.exit_code,
            actor=resolved_actor,
            task_ref=event_payload.task_ref,
        )
    return _core_report_blocker(
        operation=event_payload.operation,
        description=event_payload.description,
        blocker_id=event_payload.blocker_id,
        actor=resolved_actor,
        task_ref=event_payload.task_ref,
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
) -> dict:
    return _core_update_next_actions(
        operation=operation,
        action_id=action_id,
        action=action,
        priority=priority,
        status=status,
        actor=_dump_actor(actor),
        task_ref=task_ref,
    )


def next_actions(
    action: Annotated[
        NextActionsParam,
        Field(
            description="Typed next-actions payload. operation selects one of the list, add, update, complete, or skip variants."
        ),
    ],
) -> dict:
    action_payload = _validate_next_actions(action)
    if isinstance(action_payload, NextActionsListOp):
        return list_next_actions(
            task_ref=action_payload.task_ref,
            lane_id=action_payload.lane_id,
            status=action_payload.status,
            limit=action_payload.limit,
            offset=action_payload.offset,
        )
    return _core_update_next_actions(
        operation=action_payload.operation,
        action_id=getattr(action_payload, "action_id", None),
        action=getattr(action_payload, "action", None),
        priority=getattr(action_payload, "priority", None),
        status=getattr(action_payload, "status", None),
        actor=_dump_actor(getattr(action_payload, "actor", None)),
        task_ref=getattr(action_payload, "task_ref", None),
    )


def record_test_result(
    session: Annotated[str, Field(description="Session identifier for the verification run.")],
    command: Annotated[str, Field(description="Verification command that was executed.")],
    passed: Annotated[bool, Field(description="Whether the verification command passed.")],
    result: Annotated[
        str | None,
        Field(description="Optional stdout or summarized verification evidence for the command."),
    ] = None,
    traces: Annotated[
        list[str] | None,
        Field(description="Optional raw verification trace payloads to archive alongside the summarized result."),
    ] = None,
    exit_code: Annotated[int | None, Field(description="Optional process exit code for the command.")] = None,
    actor: ActorParam = None,
    task_ref: TaskRefParam = None,
) -> dict:
    return _core_record_test_result(
        session=session,
        command=command,
        passed=passed,
        result=result,
        traces=traces,
        exit_code=exit_code,
        actor=_dump_actor(actor),
        task_ref=task_ref,
    )


def get_verified_tests(
    task_ref: TaskRefParam = None,
    lane_id: Annotated[str | None, Field(description="Optional lane filter.")] = None,
    branch: Annotated[str | None, Field(description="Optional branch filter.")] = None,
    commit_sha: Annotated[str | None, Field(description="Optional commit SHA filter.")] = None,
    passed: Annotated[bool | None, Field(description="Optional pass/fail filter.")] = None,
    include_traces: Annotated[bool, Field(description="When true, include raw archived traces in each row.")] = False,
    correlated_file: Annotated[
        str | None,
        Field(description="Optional monorepo-relative file path used to correlate tests to changed_files decisions."),
    ] = None,
    correlation_window_minutes: Annotated[
        int,
        Field(description="Absolute decision/test time window used for changed-file correlation when commit SHAs are missing."),
    ] = 120,
    exclude_never_passed: Annotated[
        bool,
        Field(description="When true, omit commands that never recorded a passing row in the filtered result set."),
    ] = False,
    limit: Annotated[int, Field(description="Maximum number of tests to return.")] = 100,
    offset: Annotated[int, Field(description="Pagination offset.")] = 0,
) -> dict:
    return core.get_verified_tests(
        task_ref=task_ref,
        lane_id=lane_id,
        branch=branch,
        commit_sha=commit_sha,
        passed=passed,
        include_traces=include_traces,
        correlated_file=correlated_file,
        correlation_window_minutes=correlation_window_minutes,
        exclude_never_passed=exclude_never_passed,
        limit=limit,
        offset=offset,
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
) -> dict:
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
) -> dict:
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


def review_findings(
    review: Annotated[
        ReviewFindingsParam,
        Field(
            description="Typed review-findings payload. operation selects one of the record, batch_record, update, or list variants."
        ),
    ],
) -> dict:
    review_payload = _validate_review_findings(review)
    if isinstance(review_payload, ReviewFindingsRecordOp):
        return record_review_finding(
            session=review_payload.session,
            finding_id=review_payload.finding_id,
            severity=review_payload.severity,
            file_path=review_payload.file_path,
            description=review_payload.description,
            details=cast(ReviewFindingDetails | None, _dump_review_finding_details(review_payload.details)),
            actor=_dump_actor(review_payload.actor),
            task_ref=review_payload.task_ref,
            review_mode=review_payload.review_mode,
        )
    if isinstance(review_payload, ReviewFindingsBatchRecordOp):
        return batch_record_review_findings(
            session=review_payload.session,
            findings=cast(
                list[BatchFindingItem], [_dump_batch_review_finding_item(item) for item in review_payload.findings]
            ),
            actor=_dump_actor(review_payload.actor),
            task_ref=review_payload.task_ref,
        )
    if isinstance(review_payload, ReviewFindingsUpdateOp):
        return _core_update_review_finding(
            status=review_payload.status,
            finding_id=review_payload.finding_id,
            finding_db_id=review_payload.finding_db_id,
            resolution_notes=review_payload.resolution_notes,
            reopen_reason=review_payload.reopen_reason,
            task_ref=review_payload.task_ref,
            session=review_payload.session,
            actor=_dump_actor(review_payload.actor),
            verified_commit_sha=review_payload.verified_commit_sha,
            verification_evidence=review_payload.verification_evidence,
        )
    if isinstance(review_payload, ReviewFindingsRepairProvenanceOp):
        return _core_repair_review_finding_provenance(
            session=review_payload.session,
            finding_id=review_payload.finding_id,
            expected_branch=review_payload.expected_branch,
            expected_commit_sha=review_payload.expected_commit_sha,
            new_branch=review_payload.new_branch,
            new_commit_sha=review_payload.new_commit_sha,
            reason=review_payload.reason,
            task_ref=review_payload.task_ref,
            actor=_dump_actor(review_payload.actor),
        )
    if isinstance(review_payload, ReviewFindingsMergeOp):
        return merge_review_findings(
            session=review_payload.session,
            source_task_refs=review_payload.source_task_refs,
            target_task_ref=review_payload.target_task_ref,
            actor=_dump_actor(review_payload.actor),
        )
    return list_review_findings(
        task_ref=review_payload.task_ref,
        status=review_payload.status,
        severity=review_payload.severity,
        limit=review_payload.limit,
        offset=review_payload.offset,
        review_mode=review_payload.review_mode,
        finding_id=review_payload.finding_id,
        finding_db_id=review_payload.finding_db_id,
        detail=review_payload.detail,
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
) -> dict:
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


def review_runs(
    review: Annotated[
        ReviewRunsParam,
        Field(
            description="Typed review-runs payload. operation selects one of the record, list, or coverage variants."
        ),
    ],
) -> dict:
    review_payload = _validate_review_runs(review)
    if isinstance(review_payload, ReviewRunsRecordOp):
        return _core_record_review_run(
            review_run_id=review_payload.review_run_id,
            session=review_payload.session,
            subject_path=review_payload.subject_path,
            subject_kind=review_payload.subject_kind,
            review_mode=review_payload.review_mode,
            verdict=review_payload.verdict,
            verdict_decision=review_payload.verdict_decision,
            task_ref=review_payload.task_ref,
            actor=_dump_actor(review_payload.actor),
        )
    if isinstance(review_payload, ReviewRunsListOp):
        return list_review_runs(
            task_ref=review_payload.task_ref,
            subject_path=review_payload.subject_path,
            limit=review_payload.limit,
            offset=review_payload.offset,
            review_mode=review_payload.review_mode,
            verdict=review_payload.verdict,
        )
    return get_review_coverage(
        task_ref=review_payload.task_ref,
        subject_path=review_payload.subject_path,
    )


def artifacts(
    artifact: Annotated[
        ArtifactsParam,
        Field(
            description="Typed artifacts payload. operation selects one of the record, search, get, or purge variants."
        ),
    ],
) -> dict:
    artifact_payload = _validate_artifacts(artifact)
    if isinstance(artifact_payload, ArtifactsRecordOp):
        return record_artifact(
            source_kind=artifact_payload.source_kind,
            source_label=artifact_payload.source_label,
            content=artifact_payload.content,
            task_ref=artifact_payload.task_ref,
            lane_id=artifact_payload.lane_id,
            app_root=artifact_payload.app_root,
            content_type=artifact_payload.content_type,
            summary=artifact_payload.summary,
            metadata=artifact_payload.metadata,
        )
    if isinstance(artifact_payload, ArtifactsSearchOp):
        return search_artifacts(
            queries=artifact_payload.queries,
            task_ref=artifact_payload.task_ref,
            lane_id=artifact_payload.lane_id,
            app_root=artifact_payload.app_root,
            source_kind=artifact_payload.source_kind,
            content_type=artifact_payload.content_type,
            limit=artifact_payload.limit,
            offset=artifact_payload.offset,
            detail=artifact_payload.detail,
            fields=artifact_payload.fields,
        )
    if isinstance(artifact_payload, ArtifactsGetOp):
        return get_artifact(
            source_id=artifact_payload.source_id,
            task_ref=artifact_payload.task_ref,
            source_label=artifact_payload.source_label,
            include_terms=artifact_payload.include_terms,
            top_n_terms=artifact_payload.top_n_terms,
            detail=artifact_payload.detail,
            fields=artifact_payload.fields,
        )
    return purge_artifacts(
        task_ref=artifact_payload.task_ref,
        lane_id=artifact_payload.lane_id,
        app_root=artifact_payload.app_root,
        older_than_days=artifact_payload.older_than_days,
    )


_RATIONALE_XML_ANTI_PATTERNS = ("<actor>", "<changed_files>", "</actor>", "</changed_files>")


def close_slice(
    session: Annotated[str, Field(description="Session identifier for the slice completion write.")],
    decision: Annotated[str, Field(description="Stable slice-complete decision identifier.")],
    rationale: Annotated[
        str | None,
        Field(
            description=(
                "Structured markdown rationale. MUST include non-empty sections: "
                "## Changes, ## Verification, ## Schema / Contract Changes, ## Open Threads. "
                "Soft limit: 1,500 chars; hard limit: 4,000 chars (enforced by hook before call reaches server). "
                "See docs/agentic/templates/slice-complete-template.md."
            )
        ),
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
) -> dict:
    # AHMCP-22 / Layer 2 of the XML-in-rationale bug class eradication.
    # Reject rationale strings that contain XML-like <actor> or
    # <changed_files> tags — these indicate the caller accidentally
    # embedded the top-level `actor` and `changed_files` parameters
    # inside the rationale string instead of passing them as separate
    # JSON fields. The misattribution is silent (the decision row gets
    # default actor provenance) and the resulting audit trail is polluted
    # with two superseded rows, as happened with AHMCP-19 decisions
    # #1507 and #1508.
    if rationale is not None:
        # AHMCP-22-BR-01: case-insensitive scan so <ACTOR>, <Actor>, etc.
        # are caught. The anti-pattern is structural (XML tags inside a
        # markdown rationale), not case-dependent.
        rationale_lower = rationale.lower()
        for tag in _RATIONALE_XML_ANTI_PATTERNS:
            if tag in rationale_lower:
                return core._envelope(
                    ok=False,
                    tool="close_slice",
                    data={
                        "error": (
                            f"rationale contains the XML-like tag `{tag}` which indicates "
                            f"the `actor` or `changed_files` parameters were accidentally "
                            f"embedded inside the rationale string instead of being passed "
                            f"as separate top-level JSON fields. Remove the XML tags from "
                            f"the rationale and pass actor={{...}} and changed_files=[...] "
                            f"as separate parameters to close_slice."
                        ),
                        "rejected_tag": tag,
                    },
                    task_ref=task_ref,
                )
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
        # Events (1)
        ToolEntry(
            "record_event",
            record_event,
            TOOL_DESCRIPTIONS["record_event"],
            cli_name="event",
            cli_args=[
                ArgSpec("--event-kind", required=True, choices=["decision", "test_result", "blocker"]),
                ArgSpec("--session"),
                ArgSpec("--decision"),
                ArgSpec("--rationale"),
                ArgSpec("--input-tokens", type=int),
                ArgSpec("--output-tokens", type=int),
                ArgSpec("--total-tokens", type=int),
                ArgSpec(
                    "--changed-files",
                    nargs="+",
                    dest="changed_files",
                    help="Monorepo-relative paths touched by this slice.",
                ),
                ArgSpec("--command", dest="command", help="Test command."),
                ArgSpec("--passed", action="store_true"),
                ArgSpec("--result"),
                ArgSpec(
                    "--trace",
                    action="append",
                    dest="traces",
                    help="Raw verification trace to archive. Repeat for multiple trace payloads.",
                ),
                ArgSpec("--exit-code", type=int),
                ArgSpec("--operation", choices=["add", "resolve", "reopen"]),
                ArgSpec("--description"),
                ArgSpec("--blocker-id", type=int),
                ArgSpec("--task-ref"),
            ],
            surface_class="action",
            entity_family="handoff_state",
        ),
        # Next actions (1)
        ToolEntry(
            "next_actions",
            next_actions,
            TOOL_DESCRIPTIONS["next_actions"],
            cli_name="next-actions",
            cli_args=[
                ArgSpec("--operation", required=True, choices=["list", "add", "update", "complete", "skip"]),
                ArgSpec("--action-id", type=int),
                ArgSpec("--text", dest="action", help="Action text (maps to handler param 'action')."),
                ArgSpec("--lane-id"),
                ArgSpec("--priority", type=int),
                ArgSpec("--status", choices=["all", "pending", "done", "skipped"]),
                ArgSpec("--limit", type=int, default=100),
                ArgSpec("--offset", type=int, default=0),
                ArgSpec("--task-ref"),
            ],
            surface_class="action",
            entity_family="handoff_state",
        ),
        # Review findings (1)
        ToolEntry(
            "review_findings",
            review_findings,
            TOOL_DESCRIPTIONS["review_findings"],
            cli_name="review-findings",
            cli_args=[
                ArgSpec("--operation", required=True, choices=["record", "batch_record", "update", "list"]),
                ArgSpec("--session"),
                ArgSpec("--finding-id"),
                ArgSpec("--severity", choices=["high", "medium", "low"]),
                ArgSpec("--file-path"),
                ArgSpec("--description"),
                ArgSpec("--line-start", type=int),
                ArgSpec("--line-end", type=int),
                ArgSpec("--fix"),
                ArgSpec("--findings-json"),
                ArgSpec("--findings-file"),
                ArgSpec("--status"),
                ArgSpec("--finding-db-id", type=int),
                ArgSpec("--resolution-notes"),
                ArgSpec("--reopen-reason"),
                ArgSpec("--verified-commit-sha"),
                ArgSpec("--verification-evidence"),
                ArgSpec("--review-mode"),
                ArgSpec("--limit", type=int, default=20),
                ArgSpec("--offset", type=int, default=0),
                ArgSpec("--detail", default="full", choices=["full", "summary"], help="Detail level: full or summary"),
                ArgSpec("--task-ref"),
            ],
            surface_class="action",
            entity_family="review_findings",
        ),
        # Review runs (1)
        ToolEntry(
            "review_runs",
            review_runs,
            TOOL_DESCRIPTIONS["review_runs"],
            cli_name="review-runs",
            cli_args=[
                ArgSpec("--operation", required=True, choices=["record", "list", "coverage"]),
                ArgSpec("--review-run-id"),
                ArgSpec("--session"),
                ArgSpec("--subject-path"),
                ArgSpec("--subject-kind", default="task_plan"),
                ArgSpec("--review-mode", default="planning"),
                ArgSpec("--verdict"),
                ArgSpec("--verdict-decision"),
                ArgSpec("--limit", type=int, default=20),
                ArgSpec("--offset", type=int, default=0),
                ArgSpec("--task-ref"),
            ],
            surface_class="action",
            entity_family="review_runs",
        ),
        # Close check + CURRENT_TASK.json (2)
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
            "render_handoff",
            render_handoff,
            TOOL_DESCRIPTIONS["render_handoff"],
            cli_name="render-handoff",
            cli_args=[
                ArgSpec("--kind", required=True, choices=["current_task", "dashboard"]),
                ArgSpec("--task-ref", help="Task ref (only used when --kind=current_task)."),
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
            "get_archived_task",
            get_archived_task,
            TOOL_DESCRIPTIONS["get_archived_task"],
            profile="extended",
            cli_name="get-archived-task",
            cli_args=[
                ArgSpec("--task-ref", required=True),
                ArgSpec("--no-snapshot", dest="include_snapshot", action="store_false"),
            ],
            surface_class="query",
            entity_family="lifecycle",
        ),
        ToolEntry(
            "get_verified_tests",
            get_verified_tests,
            TOOL_DESCRIPTIONS["get_verified_tests"],
            profile="extended",
            cli_name="get-verified-tests",
            cli_args=[
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id"),
                ArgSpec("--branch"),
                ArgSpec("--commit-sha"),
                ArgSpec("--passed", choices=["true", "false"]),
                ArgSpec("--include-traces", action="store_true"),
                ArgSpec("--correlated-file"),
                ArgSpec("--correlation-window-minutes", type=int, default=120),
                ArgSpec("--exclude-never-passed", action="store_true"),
                ArgSpec("--limit", type=int, default=100),
                ArgSpec("--offset", type=int, default=0),
            ],
            surface_class="query",
            entity_family="handoff_state",
        ),
        ToolEntry(
            "record_file_touch",
            record_file_touch,
            TOOL_DESCRIPTIONS["record_file_touch"],
            profile="extended",
            cli_name="record-file-touch",
            cli_args=[
                ArgSpec("--file-path", required=True),
                ArgSpec("--change-kind", required=True, choices=["edit", "add", "delete"]),
                ArgSpec("--session"),
                ArgSpec("--commit-sha"),
                ArgSpec("--task-ref"),
            ],
            surface_class="action",
            entity_family="handoff_state",
        ),
        ToolEntry(
            "get_touched_files",
            get_touched_files,
            TOOL_DESCRIPTIONS["get_touched_files"],
            profile="extended",
            cli_name="get-touched-files",
            cli_args=[
                ArgSpec("--task-ref"),
                ArgSpec("--limit", type=int, default=20),
                ArgSpec("--offset", type=int, default=0),
            ],
            surface_class="query",
            entity_family="handoff_state",
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
        # Artifact tools (1)
        ToolEntry(
            "artifacts",
            artifacts,
            TOOL_DESCRIPTIONS["artifacts"],
            profile="extended",
            cli_name="artifacts",
            cli_args=[
                ArgSpec("--operation", required=True, choices=["record", "search", "get", "purge"]),
                ArgSpec("--task-ref"),
                ArgSpec("--lane-id"),
                ArgSpec("--app-root"),
                ArgSpec("--source-kind"),
                ArgSpec("--source-label"),
                ArgSpec("--content-type", default="text/plain"),
                ArgSpec("--summary"),
                ArgSpec("--content-file", help="Path to a file whose contents will be used as the artifact content."),
                ArgSpec("--content", help="Artifact content as a string."),
                ArgSpec("--metadata-json"),
                ArgSpec("--query", action="append", dest="queries", help="Search term (repeatable)."),
                ArgSpec("--limit", type=int, default=10),
                ArgSpec("--offset", type=int, default=0),
                ArgSpec("--detail", default="full", choices=["full", "summary"], help="Detail level: full or summary"),
                ArgSpec("--fields", help="Comma-separated fields to keep in returned rows."),
                ArgSpec("--source-id", type=int),
                ArgSpec("--include-terms", action="store_true"),
                ArgSpec("--top-n-terms", type=int, default=10),
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
                    choices=["decision", "finding", "blocker", "action", "verified_test"],
                    help="Limit search to these record types (decision, finding, blocker, action, verified_test).",
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
) -> dict:
    """Generate CURRENT_TASK.json for the active task.

    Renders only the active task's data: objective, focus, status, blockers,
    actions, decisions, tests, findings, lanes, and coverage.  Cross-task
    sections (All Tasks table, findings from other tasks) have moved to
    DASHBOARD.txt — call render_handoff(kind='dashboard') to produce that file.

    Args:
        task_ref: The task to render. Defaults to the active task.
        write_file: Write the machine-readable CURRENT_TASK.json snapshot to disk.

    Return keys (data envelope):
        task_ref: resolved task reference.
        path: absolute path to CURRENT_TASK.json (machine-readable JSON).
        written: True when write_file=True.
        current_task_json: JSON content of CURRENT_TASK.json; present only
            when write_file=False.
    """
    with core._get_db_connection() as conn:
        resolved_task_ref = task_ref
        if resolved_task_ref is None:
            active_row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
            resolved_task_ref = (
                str(active_row["task_ref"]) if active_row is not None and active_row["task_ref"] else None
            )

        if resolved_task_ref is not None:
            from .current_task_rendering import _build_current_task_render_state  # noqa: PLC0415

            state = _build_current_task_render_state(conn, resolved_task_ref)
        else:
            state = {
                "task_ref": None,
                "active": None,
                "blockers_open": [],
                "actions_pending": [],
                "decisions_recent": [],
                "tests_recent": [],
                "findings_open": [],
                "findings_deferred": [],
                "worktree_lanes": [],
                "worker_reports_recent": [],
                "lane_messages_open": [],
            }

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

    from .current_task_rendering import _render_current_task_json  # noqa: PLC0415

    current_task_json = _render_current_task_json(state)
    runtime = get_runtime_config()
    current_task_path = runtime.current_task_path

    if write_file:
        current_task_path.write_text(current_task_json)

    resolved_ref = state.get("task_ref")
    artifacts = []
    if write_file:
        artifacts = [
            {"type": "current_task_md", "path": str(current_task_path), "written": True},
        ]
    return core._envelope(
        ok=True,
        tool="generate_current_task_md",
        data={
            "task_ref": resolved_ref,
            "path": str(current_task_path),
            "written": write_file,
            "current_task_json": current_task_json if not write_file else None,
        },
        task_ref=resolved_ref,
        artifacts=artifacts,
    )


def generate_dashboard_md(write_file: bool = True) -> dict:
    """Generate DASHBOARD.txt — the human-scoped observatory view.

    Contains: Needs Attention summary, All Tasks table, cross-task open findings
    grouped by task_ref, deferred/wontfix findings, and any registered extension
    sections (e.g. Lane Health, Worker Status added by agent-orchestrator-mcp).

    Core sections always render.  Extension sections appear only when
    register_dashboard_extension() has been called by an extension provider.
    The CLI path (make dashboard) renders core sections only without importing
    agent-orchestrator-mcp.

    Args:
        write_file: Write the markdown to DASHBOARD.txt alongside CURRENT_TASK.json.
    """
    from .dashboard_rendering import generate_dashboard_md as _generate  # noqa: PLC0415

    return _generate(write_file=write_file)


def render_handoff(
    kind: Annotated[
        Literal["current_task", "dashboard"],
        Field(
            description=(
                "Which handoff surface to render. 'current_task' writes CURRENT_TASK.json "
                "for the requested (or active) task; 'dashboard' writes DASHBOARD.txt — "
                "the cross-task observatory view."
            )
        ),
    ],
    task_ref: Annotated[
        str | None,
        Field(
            description=(
                "Only used when kind='current_task'. Task reference to render. "
                "Defaults to the active task when omitted."
            )
        ),
    ] = None,
    write_file: Annotated[
        bool,
        Field(description="Write the rendered artifact to disk. Defaults to True."),
    ] = True,
) -> dict:
    """Compound renderer for CURRENT_TASK.json and DASHBOARD.txt.

    Replaces the two single-purpose tools ``generate_current_task_md`` and
    ``generate_dashboard_md``. The Python aliases remain importable for
    backward compatibility, but the MCP surface advertises a single
    ``render_handoff`` tool.
    """
    if kind == "current_task":
        result = generate_current_task_md(task_ref=task_ref, write_file=write_file)
    elif kind == "dashboard":
        result = generate_dashboard_md(write_file=write_file)
    else:  # pragma: no cover - pydantic rejects unknown kinds at boundary.
        raise ValueError(f"Unknown render_handoff kind: {kind!r}")
    result["tool"] = "render_handoff"
    return result


def _wrap_branch_mismatch_for_mcp(entry: ToolEntry) -> Callable[..., dict]:
    """Return an MCP-only wrapper that adapts BranchMismatchError to a v2 envelope."""

    handler = entry.handler
    signature = inspect.signature(handler)

    @functools.wraps(handler)
    def _wrapped(*args: object, **kwargs: object) -> dict:
        try:
            return handler(*args, **kwargs)
        except BranchMismatchError as exc:
            return core._envelope(
                ok=False,
                tool=entry.name,
                task_ref=exc.task_ref,
                data={
                    "error": str(exc),
                    "task_ref": exc.task_ref,
                    "expected_branch": exc.expected_branch,
                    "actual_branch": exc.actual_branch,
                },
            )

    _wrapped.__signature__ = signature.replace(return_annotation=dict)  # type: ignore[attr-defined]
    return _wrapped


def build_handoff_mcp(config: RuntimeConfig) -> FastMCP:
    configure_runtime(config)
    mcp = FastMCP(
        "Agent Handoff MCP",
        instructions=(
            "You are connected to the Agent Handoff MCP server. "
            "Use these tools for task state, review findings, exports, and close checks.\n\n"
            "## Task State Model\n\n"
            "One task is active at a time (stored in handoff_state id=1). "
            "Completed tasks are archived into task_archives with a status snapshot. "
            "DASHBOARD.txt renders the human-readable active-task view plus the cross-task dashboard, "
            "while CURRENT_TASK.json stores the machine-readable active-task snapshot. "
            "The dashboard renders both the active task's live status and each archived task's snapshot status. "
            "Non-archived, non-active tasks default to 'active' in the dashboard — "
            "this is a rendering fallback, not a real stored status.\n\n"
            "## Task Lifecycle\n\n"
            "1. **Start**: `set_handoff_state(task_ref=..., objective=..., status='in_progress')` "
            "or `switch_task(task_ref=...)` (on agent-orchestrator-mcp).\n"
            "2. **Work**: record decisions with `record_event(event={event_kind:'decision', ...})`, "
            "record test results with `record_event(event={event_kind:'test_result', ...})`, "
            "and record blockers with `record_event(event={event_kind:'blocker', ...})`.\n"
            "3. **Complete slices**: use `close_slice(...)` to record a slice-complete decision. "
            "This keeps the task status as in_progress and regenerates CURRENT_TASK.json plus DASHBOARD.txt.\n"
            "4. **Finish task**: when all slices are done, update status to done: "
            "`update_task_status(task_ref=..., status='done')`. "
            "Then archive: `archive_task_state(task_ref=...)`.\n"
            "5. **Archive without finishing**: if you archive a task while it is still in_progress, "
            "its dashboard status will remain in_progress permanently. "
            "Always set status to done before or after archiving.\n\n"
            "## Key Tool Guidance\n\n"
            "- `load_session`: use at session start to get state + open findings in one call.\n"
            "- `close_slice`: use for slice completions — it records a decision, keeps status "
            "in_progress, and regenerates CURRENT_TASK.json plus DASHBOARD.txt atomically.\n"
            "- `update_task_status`: use to change status (in_progress/done/blocked/review) "
            "without recording a decision. Works for both active and archived tasks.\n"
            "- `set_handoff_state`: use to update objective, focus, or status on the active task. "
            "Requires expected_revision.\n"
            "- `archive_task_state`: snapshots task state into archive storage. "
            "Does not change task status — the archived snapshot preserves whatever status "
            "the task had at archive time.\n"
            "- `render_handoff`: call after any state-changing operation "
            "(record_event, review_findings with record/batch_record/update). "
            "Use kind='current_task' to refresh the machine-readable CURRENT_TASK.json "
            "snapshot, and kind='dashboard' to refresh the human-readable DASHBOARD.txt "
            "observatory view."
        ),
    )
    _apply_tool_descriptions()
    for entry in _build_tool_registry():
        if entry.deprecated_since is not None:
            entry.handler.__doc__ = f"[DEPRECATED since {entry.deprecated_since}] " + (
                entry.handler.__doc__ or entry.description
            )
        # Tool handlers return native dicts via _envelope() / _json_response()
        # in shared_primitives.py. FastMCP serialises the dict once on its way
        # out — there is no longer a `json.dumps -> json.loads` round trip,
        # and the wire payload is a clean nested object instead of the legacy
        # `structured_content={"result": "<escaped JSON>"}` envelope. AHMCP-10
        # finished AHMCP-7's Slice 3 by removing the _make_dict_wrapper shim
        # that used to translate `-> str` handlers into `-> dict` at this
        # registration site; the production handlers are now `-> dict` end to
        # end and the wrapper is dead code.
        mcp.add_tool(_wrap_branch_mismatch_for_mcp(entry))
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

        def _run_cli_probe() -> None:
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

        # Run the two subprocess startup probes in parallel: each pays a full
        # Python import + package init cost (~6–7s), so running them serially
        # pushes `doctor` past the default pytest-timeout budget on loaded
        # machines. The ThreadPoolExecutor kicks off the CLI probe while the
        # asyncio event loop drives the stdio handshake; the future is
        # awaited afterwards so any CalledProcessError still surfaces.
        with ThreadPoolExecutor(max_workers=1) as _probe_pool:
            cli_future = _probe_pool.submit(_run_cli_probe)
            stdio_tools = asyncio.run(_list_tools())
            cli_future.result()

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
            "durable_output": "CURRENT_TASK.json regenerated for new active task",
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
