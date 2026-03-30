"""CURRENT_TASK.md rendering cluster for agent_handoff_mcp.

Extracted from _shared.py (Slice 1 of E12-10). Contains:
  - snapshot collection (_collect_task_snapshot)
  - state assembly (_build_current_task_state_from_snapshot)
  - write path (_write_current_task_md_for_task, _write_current_task_md_from_state)
  - related-findings helpers (_fetch_related_open_findings_impl, _fetch_related_open_findings)
  - rendering sub-helpers (_format_token_suffix, _render_lanes_section,
    _render_findings_section, _render_coverage_section, _render_token_summary_section)
  - primary render function (_render_current_task_md)

All symbols are re-exported from _shared.py for backward compatibility.

Imports from _shared are done at function level (late imports) to avoid a circular
module dependency: _shared.py re-exports from this module at its end, so module-level
imports in this file would create a deadlock when this module is loaded first.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import NotRequired, TypedDict


# ---------------------------------------------------------------------------
# Typed containers
# ---------------------------------------------------------------------------


class TaskSnapshot(TypedDict):
    """Raw data collected from the DB for a single task reference."""

    task_ref: str
    active: dict | None
    blockers: list[dict]
    next_actions: list[dict]
    decisions: list[dict]
    verified_tests: list[dict]
    review_findings: list[dict]
    worktree_lanes: list[dict]
    worker_reports: list[dict]
    lane_messages: list[dict]
    plan_cursors: list[dict]
    turn_metrics: list[dict]


class ReviewCoverageSummary(TypedDict, total=False):
    """Coverage summary returned by get_review_coverage and stored in render state."""

    ok: bool
    run_count: int
    latest_verdict: str | None
    latest_review_run_id: str | None
    open_findings_by_severity: dict[str, int]
    reopened_findings_count: int


class CurrentTaskRenderState(TypedDict):
    """Filtered, render-ready view of a task's handoff state."""

    task_ref: str | None
    active: dict | None
    blockers_open: list[dict]
    actions_pending: list[dict]
    decisions_recent: list[dict]
    tests_recent: list[dict]
    findings_open: list[dict]
    worktree_lanes: list[dict]
    worker_reports_recent: list[dict]
    lane_messages_open: list[dict]
    review_coverage: NotRequired[ReviewCoverageSummary | None]
    related_findings_open: NotRequired[dict[str, list[dict]]]


# ---------------------------------------------------------------------------
# Snapshot collection
# ---------------------------------------------------------------------------


def _collect_task_snapshot(conn: sqlite3.Connection, task_ref: str) -> TaskSnapshot:
    # Late imports: _shared defines these before re-exporting from this module,
    # but importing them at module-level here creates a circular import.
    from ._shared import (  # noqa: PLC0415
        _decode_lane_message_row_dict,
        _decode_turn_metric_row_dict,
        _row_to_dict,
    )

    active_row = conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone()
    active = _row_to_dict(active_row) if active_row is not None and active_row["task_ref"] == task_ref else None

    def _rows(query: str) -> list[dict]:
        rows = [dict(row) for row in conn.execute(query, (task_ref,)).fetchall()]
        if "lane_messages" in query:
            return [_decode_lane_message_row_dict(row) for row in rows]
        if "turn_metrics" in query:
            return [_decode_turn_metric_row_dict(row) for row in rows]
        return rows

    return {
        "task_ref": task_ref,
        "active": active,
        "blockers": _rows("SELECT * FROM blockers WHERE task_ref = ? ORDER BY created_at DESC"),
        "next_actions": _rows("SELECT * FROM next_actions WHERE task_ref = ? ORDER BY priority ASC, created_at ASC"),
        "decisions": _rows("SELECT * FROM decisions WHERE task_ref = ? ORDER BY created_at DESC"),
        "verified_tests": _rows("SELECT * FROM verified_tests WHERE task_ref = ? ORDER BY verified_at DESC"),
        "review_findings": _rows(
            "SELECT * FROM review_findings WHERE task_ref = ? ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, COALESCE(updated_at, created_at) DESC"
        ),
        "worktree_lanes": _rows("SELECT * FROM worktree_lanes WHERE task_ref = ? ORDER BY updated_at DESC, id DESC"),
        "worker_reports": _rows("SELECT * FROM worker_reports WHERE task_ref = ? ORDER BY created_at DESC, id DESC"),
        "lane_messages": _rows("SELECT * FROM lane_messages WHERE task_ref = ? ORDER BY updated_at DESC, id DESC"),
        "plan_cursors": _rows("SELECT * FROM plan_cursors WHERE task_ref = ? ORDER BY updated_at DESC, id DESC"),
        "turn_metrics": _rows("SELECT * FROM turn_metrics WHERE task_ref = ? ORDER BY created_at DESC, id DESC"),
    }


# ---------------------------------------------------------------------------
# State assembly
# ---------------------------------------------------------------------------


def _build_current_task_state_from_snapshot(snapshot: TaskSnapshot) -> CurrentTaskRenderState:
    return {
        "task_ref": snapshot.get("task_ref"),
        "active": snapshot["active"],
        "blockers_open": [row for row in snapshot["blockers"] if row.get("status") == "open"],
        "actions_pending": [row for row in snapshot["next_actions"] if row.get("status") == "pending"],
        "decisions_recent": snapshot["decisions"],
        "tests_recent": snapshot["verified_tests"],
        "findings_open": [row for row in snapshot["review_findings"] if row.get("status") == "open"],
        "worktree_lanes": snapshot.get("worktree_lanes", []),
        "worker_reports_recent": snapshot.get("worker_reports", []),
        "lane_messages_open": [row for row in snapshot.get("lane_messages", []) if row.get("status") == "open"],
    }


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------


def _write_current_task_md_for_task(conn: sqlite3.Connection, task_ref: str) -> None:
    from ._shared import _current_task_path  # noqa: PLC0415

    snapshot = _collect_task_snapshot(conn, task_ref)
    state = _build_current_task_state_from_snapshot(snapshot)
    try:
        from .review_findings import get_review_coverage as _get_review_coverage  # noqa: PLC0415 – late import to break circular
        import json as _json
        state["review_coverage"] = _json.loads(_get_review_coverage(task_ref=task_ref))
    except Exception:
        pass
    _current_task_path().write_text(_render_current_task_md(state))


def _write_current_task_md_from_state(task_ref: str) -> None:
    """Write CURRENT_TASK.md for a task using the internal DB write path."""
    from ._shared import _get_db_connection  # noqa: PLC0415

    with _get_db_connection() as conn:
        _write_current_task_md_for_task(conn, task_ref)


# ---------------------------------------------------------------------------
# Related-findings helpers
# ---------------------------------------------------------------------------


def _fetch_related_open_findings_impl(conn: sqlite3.Connection, task_refs: list[str]) -> dict[str, list[dict]]:
    """Query open review findings for multiple task_refs, grouped by task_ref.

    Takes a connection so callers can use their own connection context.
    """
    if not task_refs:
        return {}
    placeholders = ",".join("?" for _ in task_refs)
    rows = conn.execute(
        f"SELECT * FROM review_findings WHERE task_ref IN ({placeholders}) AND status = 'open' "
        "ORDER BY task_ref, CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, created_at DESC",
        tuple(task_refs),
    ).fetchall()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        d = dict(row)
        grouped.setdefault(d["task_ref"], []).append(d)
    return grouped


def _fetch_related_open_findings(task_refs: list[str]) -> dict[str, list[dict]]:
    """Query open review findings for multiple task_refs, grouped by task_ref."""
    from ._shared import _get_db_connection  # noqa: PLC0415

    if not task_refs:
        return {}
    with _get_db_connection() as conn:
        return _fetch_related_open_findings_impl(conn, task_refs)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _format_token_suffix(item: dict) -> str:
    total = item.get("total_tokens")
    if total is None:
        return ""
    if total >= 1000:
        return f" [{total / 1000:.1f}K tok]"
    return f" [{total} tok]"


def _render_lanes_section(state: dict) -> list[str]:
    lines: list[str] = ["", "## Worktree Lanes"]
    lanes = state.get("worktree_lanes", [])
    if lanes:
        for lane in lanes:
            lines.append(
                f"- `{lane.get('lane_id')}` [{lane.get('status')}] {lane.get('branch')} @ {lane.get('worktree_path')}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Lane Dispatches"])
    lane_message_rows = state.get("lane_messages_open")
    if lane_message_rows is None:
        lane_message_rows = [
            message
            for message in state.get("lane_messages", [])
            if message.get("status") == "open"
        ]
    lane_messages = [
        message
        for message in lane_message_rows
        if message.get("direction") == "orchestrator_to_worker"
    ]
    if lane_messages:
        for message in lane_messages:
            lane_id = message.get("lane_id", "?")
            subject = message.get("subject", "")
            body = message.get("message", "")
            lines.append(f"- `{lane_id}` [{message.get('id')}] {subject} -- {body}")
    else:
        lines.append("- None")
    return lines


def _render_findings_section(state: dict) -> list[str]:
    lines: list[str] = ["", "## Open Review Findings"]
    findings = state.get("findings_open", [])
    if findings:
        for finding in findings:
            location = f"{finding.get('file_path')}:{finding.get('line_start')}" if finding.get("line_start") else finding.get("file_path")
            lines.append(f"- [{finding.get('severity', '').upper()}] {finding.get('finding_id')}: {location} -- {finding.get('description')}")
    else:
        lines.append("- None")
    related = state.get("related_findings_open", {})
    if related:
        lines.extend(["", "## Related Open Review Findings"])
        for ref, ref_findings in related.items():
            lines.append(f"")
            lines.append(f"### {ref}")
            for finding in ref_findings:
                location = f"{finding.get('file_path')}:{finding.get('line_start')}" if finding.get("line_start") else finding.get("file_path")
                lines.append(f"- [{finding.get('severity', '').upper()}] {finding.get('finding_id')}: {location} -- {finding.get('description')}")
    return lines


def _render_coverage_section(state: dict) -> list[str]:
    """Render a `## Review Coverage` section when coverage data is in state."""
    coverage = state.get("review_coverage")
    if not coverage or not coverage.get("ok"):
        return []
    lines: list[str] = ["", "## Review Coverage"]
    lines.append(f"- review runs: {coverage.get('run_count', 0)}")
    latest_verdict = coverage.get("latest_verdict")
    latest_run_id = coverage.get("latest_review_run_id")
    if latest_verdict or latest_run_id:
        verdict_str = latest_verdict or "no verdict"
        run_str = f" (run: {latest_run_id})" if latest_run_id else ""
        lines.append(f"- latest verdict: {verdict_str}{run_str}")
    else:
        lines.append("- latest verdict: none")
    sev = coverage.get("open_findings_by_severity", {})
    lines.append(
        f"- open findings: high={sev.get('high', 0)} medium={sev.get('medium', 0)} low={sev.get('low', 0)}"
    )
    lines.append(f"- reopened findings: {coverage.get('reopened_findings_count', 0)}")
    return lines


def _render_token_summary_section(decisions: list[dict]) -> list[str]:
    token_decisions = [d for d in decisions if d.get("total_tokens") is not None]
    if not token_decisions:
        return []
    total_tok = sum(d.get("total_tokens", 0) for d in token_decisions)
    total_in = sum(d.get("input_tokens", 0) for d in token_decisions if d.get("input_tokens") is not None)
    total_out = sum(d.get("output_tokens", 0) for d in token_decisions if d.get("output_tokens") is not None)
    by_agent: dict[str, int] = {}
    for d in token_decisions:
        agent_key = d.get("agent") or "unknown"
        by_agent[agent_key] = by_agent.get(agent_key, 0) + (d.get("total_tokens") or 0)

    def _fmt_tok(n: int) -> str:
        return f"{n / 1000:.1f}K" if n >= 1000 else str(n)

    lines: list[str] = ["", "## Token Summary"]
    lines.append(f"- Decisions with tokens: {len(token_decisions)} ; Total: {_fmt_tok(total_tok)} (in: {_fmt_tok(total_in)}, out: {_fmt_tok(total_out)})")
    agent_parts = " ; ".join(f"{a}: {_fmt_tok(t)}" for a, t in sorted(by_agent.items(), key=lambda x: -x[1]))
    lines.append(f"- By agent: {agent_parts}")
    return lines


def _render_current_task_md(state: CurrentTaskRenderState) -> str:
    active = state.get("active")
    _generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    decisions = state.get("decisions_recent", [])
    latest_decision = decisions[0] if decisions else None

    def _decision_line(item: dict) -> str:
        parts = f"- [#{item.get('id')}] {item.get('decision')}"
        if item.get("agent"):
            parts += f" ({item.get('agent')})"
        parts += _format_token_suffix(item)
        return parts

    def _truncate_command(cmd: str, max_len: int = 120) -> str:
        if not cmd:
            return ""
        single_line = cmd.replace("\n", " \u21a9 ").strip()
        if len(single_line) > max_len:
            return single_line[:max_len] + "\u2026"
        return single_line

    if not active:
        has_data = any(
            state.get(key)
            for key in ("decisions_recent", "findings_open", "blockers_open", "actions_pending")
        )
        if not has_data:
            return f"# CURRENT_TASK\n\n_DO NOT EDIT: generated from .task-state/handoff.db. Last generated: {_generated_at}_\n\nNo active handoff state found.\n"
        task_ref_display = state.get("task_ref", "unknown")
        lines: list[str] = [
            "# CURRENT_TASK",
            "",
            f"_DO NOT EDIT: generated from .task-state/handoff.db. Last generated: {_generated_at}_",
            "",
            f"## Task Ref: `{task_ref_display}`",
            "",
            "> **Note**: No active `handoff_state` row for this task. Context assembled from available decisions, findings, blockers, and actions.",
            "",
            "## Latest Decision",
        ]
    else:
        lines = [
            "# CURRENT_TASK",
            "",
            f"_DO NOT EDIT: generated from .task-state/handoff.db. Last generated: {_generated_at}_",
            "",
            "## Objective",
            f"{active.get('objective', '')}",
            "",
        ]
        focus_val = active.get('focus')
        if focus_val:
            lines.extend(["## Current Focus", f"{focus_val}", ""])
        lines.extend([
            "## Active Status",
            f"- task_ref: `{active.get('task_ref', '')}`",
            f"- status: `{active.get('status', '')}`",
            f"- revision: `{active.get('revision', 0)}`",
            f"- updated_at: `{active.get('updated_at', '')}`",
            "",
            "## Latest Decision",
        ])
    if latest_decision:
        lines.append(_decision_line(latest_decision))
    else:
        lines.append("- None")
    lines.extend(["", "## Open Blockers"])
    for section, empty_text, formatter in [
        ("blockers_open", "- None", lambda item: f"- [#{item.get('id')}] {item.get('description')}"),
        ("actions_pending", "- None", lambda item: f"- (P{item.get('priority')}) [#{item.get('id')}] {item.get('action')}"),
        ("decisions_recent", "- None", _decision_line),
        ("tests_recent", "- None", lambda item: f"- [#{item.get('id')}] `{_truncate_command(item.get('command', ''))}` -> `{'pass' if item.get('passed') else 'fail'}`"),
    ]:
        items = state.get(section, [])
        if section == "actions_pending":
            lines.extend(["", "## Pending Next Actions"])
        elif section == "decisions_recent":
            lines.extend(["", "## Recent Decisions"])
        elif section == "tests_recent":
            lines.extend(["", "## Latest Verified Tests"])
        if items:
            lines.extend(formatter(item) for item in items)
        else:
            lines.append(empty_text)
    lines.extend(_render_lanes_section(state))
    lines.extend(_render_coverage_section(state))
    lines.extend(_render_findings_section(state))
    lines.extend(_render_token_summary_section(decisions))
    lines.append("")
    return "\n".join(lines)
