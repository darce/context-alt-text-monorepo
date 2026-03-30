# pyright: reportUnusedImport=false, reportPrivateUsage=false

"""Backward-compatible re-export surface for agent_handoff_mcp.

This module is the compatibility layer for consumers that import from
``agent_handoff_mcp._shared``.  All implementation now lives in focused
submodules; this file re-exports everything so existing imports continue to
work unchanged.

Import map:
  - Primitive utilities, constants, containers  -> shared_primitives
  - Write-context / git / actor resolution      -> shared_write_context
  - Schema SQL / DB bootstrap                   -> shared_schema
  - Generic DB query helpers                    -> shared_db_utils
  - CURRENT_TASK.md rendering cluster           -> current_task_rendering
  - Archival summary helpers                    -> shared_archival
  - Tool invocation adapters                    -> shared_tool_adapters

Only ``_annotate_review_finding`` remains implemented here because it depends
on both shared_primitives and shared_write_context; moving it to either would
create a circular import.
"""

from __future__ import annotations

import sqlite3  # noqa: F401 – kept for type annotations used in _annotate_review_finding

# ---------------------------------------------------------------------------
# Rendering cluster (extracted to current_task_rendering — E12-10 Slice 1)
# ---------------------------------------------------------------------------
from .current_task_rendering import (  # noqa: F401
    CurrentTaskRenderState,
    DashboardTaskRow,
    ReviewCoverageSummary,
    TaskSnapshot,
    _build_current_task_state_from_snapshot,
    _collect_dashboard_rows,
    _collect_task_snapshot,
    _fetch_related_open_findings,
    _fetch_related_open_findings_impl,
    _format_token_suffix,
    _render_coverage_section,
    _render_current_task_md,
    _render_dashboard_section,
    _render_findings_section,
    _render_lanes_section,
    _render_token_summary_section,
    _write_current_task_md_for_task,
    _write_current_task_md_from_state,
)

# ---------------------------------------------------------------------------
# Archival summary helpers (extracted to shared_archival — E12-10 Slice 7)
# ---------------------------------------------------------------------------
from .shared_archival import (  # noqa: F401
    ArchivalSummaryBuilder,
    _build_archival_decision_summary,
    _build_archival_lane_activity_summary,
    _build_archival_message_summary,
    _build_archival_report_summary,
    _build_archival_test_summary,
    _count_by_value,
)

# ---------------------------------------------------------------------------
# DB query utilities (extracted to shared_db_utils — E12-10 Slice 6)
# ---------------------------------------------------------------------------
from .shared_db_utils import (  # noqa: F401
    _count_task_rows,
    _fetch_handoff_rows,
    _paginated_query,
    _resolve_output_path,
)

# ---------------------------------------------------------------------------
# Primitive utilities, constants, and typed containers
# (extracted to shared_primitives — E12-9 boundary cleanup)
# ---------------------------------------------------------------------------
from .shared_primitives import (  # noqa: F401
    _FTS5_CONTROL_RE,
    _VERIFIED_TEST_RESULT_HINT_RE,
    _VERIFIED_TEST_RESULT_MAX_CHARS,
    ACTION_STATUSES,
    BATCH_CLOSE_THRESHOLD,
    BATCH_CLOSE_WINDOW_SECONDS,
    BLOCKER_STATUSES,
    CLOSEABLE_LANE_STATUSES,
    DEFAULT_HANDOFF_LIMITS,
    HANDOFF_ACTIVE_STATUSES,
    LANE_MESSAGE_DIRECTIONS,
    LANE_STATUSES,
    MANDATORY_SLICE_DECISION_HEADINGS,
    MAX_REOPEN_REASON_LENGTH,
    MAX_RESOLUTION_NOTES_LENGTH,
    MAX_VERIFICATION_EVIDENCE_LENGTH,
    MESSAGE_STATUSES,
    PLAN_CURSOR_STATES,
    REOPEN_ESCALATION_THRESHOLD,
    REPORT_STATUSES,
    REVIEW_FINDING_SEVERITIES,
    REVIEW_FINDING_STATUSES,
    REVIEW_KINDS,
    REVIEW_MODES,
    REVIEW_SCOPE_SOURCES,
    SUBPROCESS_TIMEOUT,
    LaneMessagePayload,
    PromptMetrics,
    ReviewFindingDetails,
    TokenUsage,
    _coerce_string_list,
    _current_task_path,
    _decode_lane_message_row_dict,
    _decode_turn_metric_row_dict,
    _excerpt_text,
    _exports_dir,
    _first_present,
    _has_structured_slice_summary,
    _json_response,
    _normalize_lane_message_payload,
    _normalize_optional_text,
    _normalize_path_for_match,
    _normalize_review_mode,
    _parse_review_finding_details,
    _parse_sqlite_datetime,
    _resolve_current_lane_row,
    _resolve_import_lane_id,
    _resolve_import_row_actor,
    _resolve_task_ref,
    _row_to_dict,
    _summarize_test_result,
    _utcnow_iso,
    _validate_decision_payload,
    _workspace_root,
)

# ---------------------------------------------------------------------------
# Schema SQL strings + bootstrap (extracted to shared_schema — E12-10 Slice 3)
# ---------------------------------------------------------------------------
from .shared_schema import (  # noqa: F401
    _HANDOFF_FTS_TRIGGERS_SQL,
    HANDOFF_FTS_SCHEMA_SQL,
    HANDOFF_SCHEMA_SQL,
    _apply_handoff_migrations,
    _backfill_handoff_fts,
    _dedupe_review_findings,
    _ensure_handoff_fts,
    _ensure_review_findings_unique_index,
    _get_db_connection,
    _has_column,
    _has_index,
)

# ---------------------------------------------------------------------------
# Tool invocation helpers (extracted to shared_tool_adapters — E12-10 Slice 5)
# ---------------------------------------------------------------------------
from .shared_tool_adapters import (  # noqa: F401
    _FnWrappedTool,
    _FunctionWrappedTool,
    _FuncWrappedTool,
    _invoke_tool,
    _normalize_tool_result,
    _resolve_awaitable,
    _RunnableTool,
    _unwrap_tool_candidate,
)

# ---------------------------------------------------------------------------
# Write-context cluster (extracted to shared_write_context — E12-10 Slice 2)
# ---------------------------------------------------------------------------
from .shared_write_context import (  # noqa: F401
    ResolvedWriteContext,
    WriteActor,
    _classify_commit_relation,
    _detect_git_write_context,
    _first_non_empty_env,
    _git_is_ancestor,
    _resolve_core_override,
    _resolve_write_actor,
    _run_cmd,
    _workspace_git_context,
    build_write_actor,
)

# ---------------------------------------------------------------------------
# Slice-decision helpers re-exported for core.py backward compat
# ---------------------------------------------------------------------------
from .slice_decision import (  # noqa: F401
    classify_decision_id,
    extract_slice_label,
    is_canonical_decision,
    is_slice_complete_decision,
)

# ---------------------------------------------------------------------------
# _annotate_review_finding — must remain here to avoid a circular import.
# It needs _normalize_optional_text (shared_primitives) AND _resolve_core_override
# / _classify_commit_relation (shared_write_context).  Moving it to either
# module would create a dependency cycle.
# ---------------------------------------------------------------------------


def _annotate_review_finding(
    row: dict[str, object], *, workspace_branch: str | None, workspace_commit_sha: str | None
) -> dict[str, object]:
    finding = dict(row)
    finding_branch = _normalize_optional_text(finding.get("branch"))
    finding_commit_sha = _normalize_optional_text(finding.get("commit_sha"))
    branch_matches = None
    if finding_branch is not None and workspace_branch is not None:
        branch_matches = finding_branch == workspace_branch
    finding["workspace_branch"] = workspace_branch
    finding["workspace_commit_sha"] = workspace_commit_sha
    finding["workspace_branch_matches"] = branch_matches
    _classify_fn = _resolve_core_override("_classify_commit_relation", _classify_commit_relation)
    finding["workspace_commit_relation"] = _classify_fn(finding_commit_sha, workspace_commit_sha)
    return finding
