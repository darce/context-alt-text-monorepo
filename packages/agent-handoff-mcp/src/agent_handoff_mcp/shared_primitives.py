"""Primitive cross-cutting utilities for agent_handoff_mcp.

Extracted from _shared.py (M-1058-01 / M-1058-02 follow-up). Contains
the lowest-level helpers that every focused module needs without creating
circular imports:

  - Typed containers: TokenUsage, PromptMetrics, ReviewFindingDetails,
    LaneMessagePayload
  - Domain constants: frozensets from enums, integer validation limits
  - Workspace path helpers: _workspace_root, _current_task_path, _exports_dir
  - Text utilities: _normalize_optional_text, _first_present, _utcnow_iso,
    _json_response, _excerpt_text
  - DB row utilities: _row_to_dict, _coerce_string_list, _resolve_task_ref,
    _decode_lane_message_row_dict, _decode_turn_metric_row_dict
  - Datetime utilities: _parse_sqlite_datetime
  - Normalization helpers: _normalize_review_mode, _normalize_lane_message_payload,
    _normalize_path_for_match, _resolve_current_lane_row
  - Test-result utilities: _summarize_test_result
  - Decision/slice utilities: _has_structured_slice_summary, _validate_decision_payload
  - Review/import helpers: _parse_review_finding_details, _resolve_import_row_actor,
    _resolve_import_lane_id

No imports from .shared_write_context, .shared_schema, .shared_db_utils,
.shared_archival, .current_task_rendering, or .shared_tool_adapters (avoids
circular dependencies).  _shared.py re-exports from here for backward compat.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from .enums import (
    ActionStatus,
    BlockerStatus,
    FindingSeverity,
    FindingStatus,
    HandoffStatus,
    LaneMessageDirection,
    LaneStatus,
    MessageStatus,
    PlanCursorState,
    ReportStatus,
    ReviewKind,
    ReviewMode,
    ReviewScopeSource,
    normalize_model_identity,
    normalize_model_label,
    normalize_reasoning_level,
)
from .runtime import get_runtime_config
from .slice_decision import (
    is_legacy_slice_complete_decision,
    is_prefixed_slice_complete_decision,
    is_slice_complete_decision,
)

# ---------------------------------------------------------------------------
# Regex constants
# ---------------------------------------------------------------------------

_FTS5_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_VERIFIED_TEST_RESULT_HINT_RE = re.compile(
    r"\b(pass(?:ed)?|fail(?:ed)?|error(?:s)?|warning(?:s)?|clean|ready|not ready|ok)\b",
    re.IGNORECASE,
)
_VERIFIED_TEST_RESULT_MAX_CHARS = 280

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

DEFAULT_HANDOFF_LIMITS = {
    "blockers": 5,
    "actions": 5,
    "decisions": 3,
    "tests": 3,
    "findings": 10,
}
HANDOFF_ACTIVE_STATUSES = frozenset(status.value for status in HandoffStatus)
BLOCKER_STATUSES = frozenset(status.value for status in BlockerStatus)
ACTION_STATUSES = frozenset(status.value for status in ActionStatus)
REVIEW_FINDING_STATUSES = frozenset(status.value for status in FindingStatus)
REVIEW_FINDING_SEVERITIES = frozenset(status.value for status in FindingSeverity)
REVIEW_MODES = frozenset(mode.value for mode in ReviewMode)
REVIEW_KINDS = frozenset(kind.value for kind in ReviewKind)
REVIEW_SCOPE_SOURCES = frozenset(source.value for source in ReviewScopeSource)
LANE_STATUSES = frozenset(status.value for status in LaneStatus)
CLOSEABLE_LANE_STATUSES = frozenset({LaneStatus.MERGED.value, LaneStatus.CLOSED.value})
REPORT_STATUSES = frozenset(status.value for status in ReportStatus)
MESSAGE_STATUSES = frozenset(status.value for status in MessageStatus)
LANE_MESSAGE_DIRECTIONS = frozenset(direction.value for direction in LaneMessageDirection)
PLAN_CURSOR_STATES = frozenset(state.value for state in PlanCursorState)
MANDATORY_SLICE_DECISION_HEADINGS = (
    "## Changes",
    "## Verification",
    "## Schema / Contract Changes",
    "## Open Threads",
)
MAX_RESOLUTION_NOTES_LENGTH = 500
MAX_REOPEN_REASON_LENGTH = 500
MAX_VERIFICATION_EVIDENCE_LENGTH = 2000
BATCH_CLOSE_WINDOW_SECONDS = 60
BATCH_CLOSE_THRESHOLD = 2
REOPEN_ESCALATION_THRESHOLD = 2
SUBPROCESS_TIMEOUT = 10

# ---------------------------------------------------------------------------
# Typed containers
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    total_tokens: int | None = None
    usage_source: str | None = None


@dataclass
class PromptMetrics:
    model_context_window: int | None = None
    prompt_tokens: int | None = None
    prompt_chars: int | None = None
    prompt_token_source: str | None = None
    utilization_ratio: float | None = None
    domain_signal_ratio: float | None = None
    pressure_level: str | None = None


class ReviewFindingDetails(TypedDict, total=False):
    line_start: int
    line_end: int
    fix: str


class LaneMessagePayload(TypedDict, total=False):
    source_lane: str
    reason: str
    summary: str
    required_actions: list[str]
    artifacts: list[str]


# ---------------------------------------------------------------------------
# Workspace / path utilities
# ---------------------------------------------------------------------------


def _workspace_root() -> Path:
    return get_runtime_config().workspace_root


def _current_task_path() -> Path:
    return get_runtime_config().current_task_path


def _exports_dir() -> Path:
    return get_runtime_config().exports_dir


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized != "" else None


def _first_present(values: list[object]) -> object | None:
    for value in values:
        if isinstance(value, str):
            if value.strip() != "":
                return value
            continue
        if value is not None:
            return value
    return None


def _utcnow_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_response(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _excerpt_text(value: str | None, *, limit: int = 240) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    collapsed = " ".join(normalized.split())
    if len(collapsed) <= limit:
        return collapsed
    if limit <= 3:
        return "." * limit
    return f"{collapsed[: limit - 3].rstrip()}..."


# ---------------------------------------------------------------------------
# DB row utilities
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _coerce_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            normalized = item.strip()
            if normalized:
                result.append(normalized)
    return result


def _resolve_task_ref(conn: sqlite3.Connection, task_ref: str | None) -> str:
    if task_ref:
        return task_ref
    row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
    if row is None:
        raise ValueError("No active task in handoff_state. Call set_handoff_state first or pass task_ref explicitly.")
    return str(row["task_ref"])


def _decode_lane_message_row_dict(row: dict) -> dict:
    payload_json = row.get("payload_json")
    if isinstance(payload_json, str) and payload_json.strip():
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            row["payload"] = payload
    return row


def _decode_turn_metric_row_dict(row: dict) -> dict:
    for key, empty in (
        ("attribution_json", {}),
        ("section_sizes_json", {}),
        ("raw_usage_json", None),
    ):
        raw_value = row.get(key)
        if not isinstance(raw_value, str) or not raw_value.strip():
            row[key.removesuffix("_json")] = empty
            continue
        try:
            row[key.removesuffix("_json")] = json.loads(raw_value)
        except json.JSONDecodeError:
            row[key.removesuffix("_json")] = empty
    return row


# ---------------------------------------------------------------------------
# Datetime utilities
# ---------------------------------------------------------------------------


def _parse_sqlite_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized == "":
        return None
    try:
        return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        try:
            return datetime.fromisoformat(normalized.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _normalize_review_mode(value: object) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    if normalized not in REVIEW_MODES:
        raise ValueError(f"Invalid review_mode. Valid: {', '.join(sorted(REVIEW_MODES))}")
    return normalized


def _normalize_lane_message_payload(payload: object) -> tuple[dict[str, object] | None, str | None]:
    if payload is None:
        return None, None
    if not isinstance(payload, dict):
        return None, "lane message payload must be an object when provided."
    normalized: dict[str, object] = {}
    source_lane = _normalize_optional_text(payload.get("source_lane"))
    if source_lane is not None:
        normalized["source_lane"] = source_lane
    reason = _normalize_optional_text(payload.get("reason"))
    if reason is not None:
        normalized["reason"] = reason
    summary = _normalize_optional_text(payload.get("summary"))
    if summary is not None:
        normalized["summary"] = summary
    required_actions = _coerce_string_list(payload.get("required_actions"))
    if required_actions:
        normalized["required_actions"] = required_actions
    artifacts = _coerce_string_list(payload.get("artifacts"))
    if artifacts:
        normalized["artifacts"] = artifacts
    _raw_override = payload.get("owned_paths_override")
    if isinstance(_raw_override, str):
        _raw_override = [_raw_override]
    owned_paths_override = _coerce_string_list(_raw_override)
    if owned_paths_override:
        normalized["owned_paths_override"] = owned_paths_override
    return normalized, None


def _normalize_path_for_match(path_value: str | Path) -> str:
    return os.path.normcase(str(Path(path_value).expanduser().resolve()))


def _resolve_current_lane_row(conn: sqlite3.Connection, task_ref: str) -> sqlite3.Row | None:
    workspace_path = _normalize_path_for_match(_workspace_root())
    lane_rows = conn.execute(
        "SELECT * FROM worktree_lanes WHERE task_ref = ? ORDER BY updated_at DESC, id DESC",
        (task_ref,),
    ).fetchall()
    for row in lane_rows:
        raw_path = _normalize_optional_text(row["worktree_path"])
        if raw_path is None:
            continue
        if _normalize_path_for_match(raw_path) == workspace_path:
            return row  # type: ignore[return-value]
    return None


# ---------------------------------------------------------------------------
# Test-result utilities
# ---------------------------------------------------------------------------


def _summarize_test_result(result: str | None) -> str | None:
    normalized = _normalize_optional_text(result)
    if normalized is None:
        return None
    lines = [re.sub(r"\s+", " ", line).strip() for line in normalized.splitlines() if line.strip()]
    if not lines:
        return None
    summary = next((line for line in reversed(lines) if _VERIFIED_TEST_RESULT_HINT_RE.search(line)), lines[-1])
    if len(summary) <= _VERIFIED_TEST_RESULT_MAX_CHARS:
        return summary
    return summary[: _VERIFIED_TEST_RESULT_MAX_CHARS - 3].rstrip() + "..."


# ---------------------------------------------------------------------------
# Decision / slice utilities
# ---------------------------------------------------------------------------


def _has_structured_slice_summary(text: str) -> bool:
    normalized = _normalize_optional_text(text)
    if normalized is None:
        return False
    section_content: dict[str, list[str]] = {heading: [] for heading in MANDATORY_SLICE_DECISION_HEADINGS}
    current_heading: str | None = None
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in section_content:
            current_heading = line
            continue
        if current_heading is not None:
            section_content[current_heading].append(line)
    return all(section_content[heading] for heading in MANDATORY_SLICE_DECISION_HEADINGS)


def _validate_decision_payload(decision: str, rationale: str | None) -> str | None:
    if is_legacy_slice_complete_decision(decision):
        return (
            "Legacy slice-complete ids are grandfathered for historical rows only. "
            "New writes must use <author_tag>_slice_complete_<work_ref>_<slug>."
        )
    if decision.startswith("slice_complete_"):
        return "Malformed slice-complete id. New writes must use <author_tag>_slice_complete_<work_ref>_<slug>."
    if "_slice_complete_" in decision and not is_prefixed_slice_complete_decision(decision):
        return "Malformed slice-complete id. Expected <author_tag>_slice_complete_<work_ref>_<slug>."
    if is_slice_complete_decision(decision) and not _has_structured_slice_summary(str(rationale or "")):
        headings = ", ".join(MANDATORY_SLICE_DECISION_HEADINGS)
        return f"slice_complete_* decisions require a structured rationale with non-empty sections for: {headings}."
    return None


# ---------------------------------------------------------------------------
# Review finding helpers
# ---------------------------------------------------------------------------


def _parse_review_finding_details(details: ReviewFindingDetails | None) -> tuple[int | None, int | None, str | None]:
    if not details:
        return None, None, None
    return details.get("line_start"), details.get("line_end"), details.get("fix")


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------


def _resolve_import_row_actor(
    row: dict,
    *,
    fallback_agent: str,
    fallback_branch: str,
    fallback_commit: str | None,
) -> tuple[str, str, str | None, str | None, str | None, str | None]:
    model = _normalize_optional_text(row.get("model"))
    model_label = _normalize_optional_text(row.get("model_label")) or normalize_model_label(model)
    reasoning_level = normalize_reasoning_level(row.get("reasoning_level"))
    derived_agent = normalize_model_identity(model_label, reasoning_level)
    return (
        derived_agent or _normalize_optional_text(row.get("agent")) or fallback_agent,
        _normalize_optional_text(row.get("branch")) or fallback_branch,
        _normalize_optional_text(row.get("commit_sha")) or fallback_commit,
        model,
        model_label,
        reasoning_level,
    )


def _resolve_import_lane_id(row: dict) -> str | None:
    return _normalize_optional_text(row.get("lane_id"))
