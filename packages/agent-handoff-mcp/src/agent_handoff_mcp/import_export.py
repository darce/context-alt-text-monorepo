"""Import/export domain module.

Contains export_handoff_state, import_handoff_state, archive_task_state,
get_archived_task, update_task_status, and switch_task.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from ._shared import (
    HANDOFF_ACTIVE_STATUSES,
    ResolvedWriteContext,
    TaskSnapshot,
    WriteActor,
    _build_current_task_state_from_snapshot,
    _collect_task_snapshot,
    _count_task_rows,
    _detect_git_write_context,
    _envelope,
    _get_db_connection,
    _normalize_optional_text,
    _render_current_task_md,
    _resolve_import_lane_id,
    _resolve_import_row_actor,
    _resolve_output_path,
    _resolve_task_ref,
    _resolve_write_actor,
    _row_to_dict,
    _utcnow_iso,
    _workspace_root,
    _write_current_task_md_for_task,
    build_write_actor,
    collect_target_context_warnings,
)


def _persist_task_archive_snapshot(
    conn: sqlite3.Connection,
    *,
    task_ref: str,
    snapshot: TaskSnapshot | Mapping[str, object],
    ctx: ResolvedWriteContext,
    notes: str,
) -> None:
    conn.execute(
        """
        INSERT INTO task_archives (task_ref, archived_at, archived_by, archived_branch, archived_commit_sha, notes, snapshot_json)
        VALUES (?, datetime('now'), ?, ?, ?, ?, ?)
        ON CONFLICT(task_ref) DO UPDATE SET
            archived_at = datetime('now'),
            archived_by = excluded.archived_by,
            archived_branch = excluded.archived_branch,
            archived_commit_sha = excluded.archived_commit_sha,
            notes = excluded.notes,
            snapshot_json = excluded.snapshot_json
        """,
        (
            task_ref,
            ctx.agent,
            ctx.branch,
            ctx.commit_sha,
            notes,
            json.dumps(snapshot, sort_keys=True),
        ),
    )


def export_handoff_state(
    task_ref: str | None = None, output_path: str | None = None, include_markdown: bool = False
) -> dict:
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        snapshot = _collect_task_snapshot(conn, resolved_task_ref)
    payload: dict[str, object] = {
        "export_version": 1,
        "task_ref": resolved_task_ref,
        "exported_at": _utcnow_iso(),
        "snapshot": snapshot,
    }
    if include_markdown:
        render_state = _build_current_task_state_from_snapshot(snapshot)
        payload["current_task_markdown"] = _render_current_task_md(render_state)
    destination = _resolve_output_path(output_path, resolved_task_ref)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return _envelope(
        ok=True,
        tool="export_handoff_state",
        data={
            "path": str(destination),
            "counts": {
                "blockers": len(snapshot["blockers"]),
                "next_actions": len(snapshot["next_actions"]),
                "decisions": len(snapshot["decisions"]),
                "verified_tests": len(snapshot["verified_tests"]),
                "review_findings": len(snapshot["review_findings"]),
                "worktree_lanes": len(snapshot["worktree_lanes"]),
                "worker_reports": len(snapshot["worker_reports"]),
                "lane_messages": len(snapshot["lane_messages"]),
                "plan_cursors": len(snapshot.get("plan_cursors", [])),
                "turn_metrics": len(snapshot.get("turn_metrics", [])),
            },
        },
        task_ref=resolved_task_ref,
        artifacts=[{"type": "file", "path": str(destination)}],
    )


def _set_import_active_state(conn: sqlite3.Connection, task_ref: str, active: dict) -> None:
    git_branch, git_commit = _detect_git_write_context()
    updated_by = (
        _normalize_optional_text(active.get("updated_by"))
        or _normalize_optional_text(os.environ.get("AGENT_HANDOFF_DEFAULT_AGENT"))
        or "codex"
    )
    updated_branch = _normalize_optional_text(active.get("updated_branch")) or git_branch or "unknown-branch"
    updated_commit_sha = _normalize_optional_text(active.get("updated_commit_sha")) or git_commit
    current = conn.execute("SELECT revision FROM handoff_state WHERE id = 1").fetchone()
    if current is None:
        conn.execute(
            """
            INSERT INTO handoff_state (
                id, task_ref, objective, focus, status, revision, updated_at, updated_by, updated_branch, updated_commit_sha
            ) VALUES (1, ?, ?, ?, ?, 0, datetime('now'), ?, ?, ?)
            """,
            (
                task_ref,
                active.get("objective", ""),
                active.get("focus"),
                active.get("status", "in_progress"),
                updated_by,
                updated_branch,
                updated_commit_sha,
            ),
        )
        return
    conn.execute(
        "UPDATE handoff_state SET task_ref = ?, objective = ?, focus = ?, status = ?, revision = revision + 1, updated_at = datetime('now'), updated_by = ?, updated_branch = ?, updated_commit_sha = ? WHERE id = 1",
        (
            task_ref,
            active.get("objective", ""),
            active.get("focus"),
            active.get("status", "in_progress"),
            updated_by,
            updated_branch,
            updated_commit_sha,
        ),
    )


def _import_plan_cursors(conn: sqlite3.Connection, task_ref: str, rows: list[dict], now: str) -> None:
    for row in rows:
        conn.execute(
            """
            INSERT INTO plan_cursors (
                task_ref, plan_item_id, state, lane_id, mcp_action_id, worker_message_id,
                source_heading, summary, dispatch_count, dispatched_at, completed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_ref,
                row.get("plan_item_id", ""),
                row.get("state", "dispatched"),
                row.get("lane_id"),
                row.get("mcp_action_id"),
                row.get("worker_message_id"),
                row.get("source_heading"),
                row.get("summary", ""),
                int(row.get("dispatch_count") or 0),
                row.get("dispatched_at"),
                row.get("completed_at"),
                row.get("created_at") or now,
                row.get("updated_at") or row.get("created_at") or now,
            ),
        )


def _import_turn_metrics(conn: sqlite3.Connection, task_ref: str, rows: list[dict], now: str) -> None:
    for row in rows:
        attribution_json = row.get("attribution_json")
        if attribution_json is None:
            attribution_json = json.dumps(row.get("attribution", {}), sort_keys=True)
        section_sizes_json = row.get("section_sizes_json")
        if section_sizes_json is None:
            section_sizes_json = json.dumps(row.get("section_sizes", {}), sort_keys=True)
        raw_usage_json = row.get("raw_usage_json")
        if raw_usage_json is None and row.get("raw_usage") is not None:
            raw_usage_json = json.dumps(row.get("raw_usage"), sort_keys=True)
        conn.execute(
            """
            INSERT INTO turn_metrics (
                task_ref, lane_id, session, cycle, phase, backend, model, thread_id, turn_id,
                input_tokens, output_tokens, cached_input_tokens, reasoning_output_tokens,
                total_tokens, usage_source, model_context_window, prompt_tokens, prompt_chars,
                prompt_token_source, utilization_ratio, domain_signal_ratio, pressure_level,
                attribution_json, section_sizes_json, raw_usage_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_ref,
                row.get("lane_id"),
                row.get("session", "import"),
                row.get("cycle"),
                row.get("phase", "execution"),
                row.get("backend", "unknown"),
                row.get("model"),
                row.get("thread_id"),
                row.get("turn_id"),
                row.get("input_tokens"),
                row.get("output_tokens"),
                row.get("cached_input_tokens"),
                row.get("reasoning_output_tokens"),
                row.get("total_tokens"),
                row.get("usage_source"),
                row.get("model_context_window"),
                row.get("prompt_tokens"),
                row.get("prompt_chars"),
                row.get("prompt_token_source"),
                row.get("utilization_ratio"),
                row.get("domain_signal_ratio"),
                row.get("pressure_level"),
                attribution_json,
                section_sizes_json,
                raw_usage_json,
                row.get("created_at") or now,
            ),
        )


def _import_snapshot(
    conn: sqlite3.Connection, task_ref: str, snapshot: dict, mode: str, set_active: bool
) -> dict[str, int]:
    blockers = snapshot.get("blockers", [])
    actions = snapshot.get("next_actions", [])
    decisions = snapshot.get("decisions", [])
    tests = snapshot.get("verified_tests", [])
    findings = snapshot.get("review_findings", [])
    lanes = snapshot.get("worktree_lanes", [])
    reports = snapshot.get("worker_reports", [])
    messages = snapshot.get("lane_messages", [])
    plan_cursors = snapshot.get("plan_cursors", [])
    turn_metrics = snapshot.get("turn_metrics", [])
    active = snapshot.get("active")
    now = _utcnow_iso().replace("T", " ").replace("Z", "")
    git_branch, git_commit = _detect_git_write_context()
    fallback_agent = _normalize_optional_text(os.environ.get("AGENT_HANDOFF_DEFAULT_AGENT")) or "codex"
    fallback_branch = git_branch or "unknown-branch"
    fallback_commit = git_commit
    if isinstance(active, dict):
        fallback_agent = _normalize_optional_text(active.get("updated_by")) or fallback_agent
        fallback_branch = _normalize_optional_text(active.get("updated_branch")) or fallback_branch
        fallback_commit = _normalize_optional_text(active.get("updated_commit_sha")) or fallback_commit
    if mode == "replace_task":
        for table in (
            "blockers",
            "next_actions",
            "decisions",
            "verified_tests",
            "review_findings",
            "worktree_lanes",
            "worker_reports",
            "lane_messages",
            "plan_cursors",
            "turn_metrics",
        ):
            conn.execute(f"DELETE FROM {table} WHERE task_ref = ?", (task_ref,))
    for row in blockers:
        agent, branch, commit_sha, _model, _model_label, _reasoning_level = _resolve_import_row_actor(
            row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit
        )
        conn.execute(
            "INSERT INTO blockers (task_ref, lane_id, description, status, agent, branch, commit_sha, resolved_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_ref,
                _resolve_import_lane_id(row),
                row.get("description", ""),
                row.get("status", "open"),
                agent,
                branch,
                commit_sha,
                row.get("resolved_at"),
                row.get("created_at") or now,
            ),
        )
    for row in actions:
        agent, branch, commit_sha, _model, _model_label, _reasoning_level = _resolve_import_row_actor(
            row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit
        )
        conn.execute(
            "INSERT INTO next_actions (task_ref, lane_id, action, priority, status, agent, branch, commit_sha, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_ref,
                _resolve_import_lane_id(row),
                row.get("action", ""),
                int(row.get("priority", 100)),
                row.get("status", "pending"),
                agent,
                branch,
                commit_sha,
                row.get("created_at") or now,
                row.get("updated_at") or row.get("created_at") or now,
            ),
        )
    for row in decisions:
        agent, branch, commit_sha, model, model_label, reasoning_level = _resolve_import_row_actor(
            row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit
        )
        conn.execute(
            "INSERT INTO decisions (task_ref, lane_id, session, decision, rationale, agent, model, model_label, reasoning_level, input_tokens, output_tokens, total_tokens, changed_files_json, branch, commit_sha, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_ref,
                _resolve_import_lane_id(row),
                row.get("session", "import"),
                row.get("decision", ""),
                row.get("rationale"),
                agent,
                model,
                model_label,
                reasoning_level,
                row.get("input_tokens"),
                row.get("output_tokens"),
                row.get("total_tokens"),
                row.get("changed_files_json", "[]"),
                branch,
                commit_sha,
                row.get("created_at") or now,
            ),
        )
    for row in tests:
        agent, branch, commit_sha, _model, _model_label, _reasoning_level = _resolve_import_row_actor(
            row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit
        )
        conn.execute(
            "INSERT INTO verified_tests (task_ref, lane_id, command, passed, exit_code, result, session, agent, branch, commit_sha, verified_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_ref,
                _resolve_import_lane_id(row),
                row.get("command", ""),
                1 if row.get("passed") else 0,
                row.get("exit_code"),
                row.get("result"),
                row.get("session", "import"),
                agent,
                branch,
                commit_sha,
                row.get("verified_at") or now,
            ),
        )
    for row in findings:
        agent, branch, commit_sha, _model, _model_label, _reasoning_level = _resolve_import_row_actor(
            row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit
        )
        conn.execute(
            "INSERT INTO review_findings (task_ref, lane_id, finding_id, severity, file_path, line_start, line_end, description, fix, status, review_mode, session, agent, branch, commit_sha, resolution_notes, reopen_count, last_reopen_reason, last_reopened_at, resolved_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_ref,
                _resolve_import_lane_id(row),
                row.get("finding_id", ""),
                row.get("severity", "low"),
                row.get("file_path", ""),
                row.get("line_start"),
                row.get("line_end"),
                row.get("description", ""),
                row.get("fix"),
                row.get("status", "open"),
                row.get("review_mode"),
                row.get("session", "import"),
                agent,
                branch,
                commit_sha,
                row.get("resolution_notes"),
                int(row.get("reopen_count") or 0),
                row.get("last_reopen_reason"),
                row.get("last_reopened_at"),
                row.get("resolved_at"),
                row.get("created_at") or now,
                row.get("updated_at") or row.get("resolved_at") or row.get("created_at") or now,
            ),
        )
    for row in lanes:
        conn.execute(
            "INSERT INTO worktree_lanes (task_ref, lane_id, title, objective, worktree_path, branch, owner_agent, status, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_ref,
                row.get("lane_id", ""),
                row.get("title"),
                row.get("objective"),
                row.get("worktree_path", ""),
                row.get("branch", ""),
                row.get("owner_agent"),
                row.get("status", "planned"),
                row.get("notes"),
                row.get("created_at") or now,
                row.get("updated_at") or row.get("created_at") or now,
            ),
        )
    for row in reports:
        agent, branch, commit_sha, _model, _model_label, _reasoning_level = _resolve_import_row_actor(
            row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit
        )
        conn.execute(
            "INSERT INTO worker_reports (task_ref, lane_id, session, summary, changed_files_json, test_commands_json, blockers_json, merge_ready, status, agent, branch, commit_sha, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_ref,
                row.get("lane_id", ""),
                row.get("session", "import"),
                row.get("summary", ""),
                row.get("changed_files_json") or json.dumps(row.get("changed_files", [])),
                row.get("test_commands_json") or json.dumps(row.get("test_commands", [])),
                row.get("blockers_json") or json.dumps(row.get("blockers", [])),
                1 if row.get("merge_ready") else 0,
                row.get("status", "submitted"),
                agent,
                branch,
                commit_sha,
                row.get("created_at") or now,
            ),
        )
    for row in messages:
        agent, branch, commit_sha, _model, _model_label, _reasoning_level = _resolve_import_row_actor(
            row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit
        )
        payload_json = row.get("payload_json")
        payload = row.get("payload")
        if isinstance(payload, dict):
            payload_json = json.dumps(payload, sort_keys=True)
        conn.execute(
            "INSERT INTO lane_messages (task_ref, lane_id, session, direction, subject, message, status, payload_json, agent, branch, commit_sha, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_ref,
                row.get("lane_id", ""),
                row.get("session", "import"),
                row.get("direction", "worker_to_orchestrator"),
                row.get("subject"),
                row.get("message", ""),
                row.get("status", "open"),
                payload_json,
                agent,
                branch,
                commit_sha,
                row.get("created_at") or now,
                row.get("updated_at") or row.get("created_at") or now,
            ),
        )
    _import_plan_cursors(conn, task_ref, plan_cursors, now)
    _import_turn_metrics(conn, task_ref, turn_metrics, now)
    if set_active and isinstance(active, dict):
        _set_import_active_state(conn, task_ref, active)
    return {
        "blockers": len(blockers),
        "next_actions": len(actions),
        "decisions": len(decisions),
        "verified_tests": len(tests),
        "review_findings": len(findings),
        "worktree_lanes": len(lanes),
        "worker_reports": len(reports),
        "lane_messages": len(messages),
        "plan_cursors": len(plan_cursors),
        "turn_metrics": len(turn_metrics),
    }


def import_handoff_state(
    input_path: str, mode: str = "merge", set_active: bool = False, allow_destructive_clear: bool = False
) -> dict:
    if mode not in {"merge", "replace_task"}:
        return _envelope(
            ok=False, tool="import_handoff_state", data={"error": "Invalid mode. Valid: merge, replace_task."}
        )
    source = Path(input_path)
    if not source.is_absolute():
        source = _workspace_root() / source
    if not source.exists():
        return _envelope(ok=False, tool="import_handoff_state", data={"error": f"Input file not found: {source}"})
    payload = json.loads(source.read_text())
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        return _envelope(
            ok=False, tool="import_handoff_state", data={"error": "Invalid import payload: snapshot must be an object."}
        )
    task_ref = payload.get("task_ref") or snapshot.get("task_ref")
    if not task_ref:
        return _envelope(ok=False, tool="import_handoff_state", data={"error": "Missing task_ref in import payload."})
    required_sections = (
        "blockers",
        "next_actions",
        "decisions",
        "verified_tests",
        "review_findings",
        "worktree_lanes",
        "worker_reports",
        "lane_messages",
    )
    if mode == "replace_task":
        missing_sections = [key for key in required_sections if key not in snapshot]
        if missing_sections:
            return _envelope(
                ok=False,
                tool="import_handoff_state",
                data={
                    "error": f"Invalid replace_task payload: missing required snapshot sections {', '.join(missing_sections)}.",
                },
            )
    for key in (*required_sections, "plan_cursors", "turn_metrics"):
        items = snapshot.get(key, [])
        if not isinstance(items, list):
            return _envelope(
                ok=False,
                tool="import_handoff_state",
                data={"error": f"Invalid import payload: snapshot.{key} must be an array."},
            )
        for item in items:
            if not isinstance(item, dict):
                return _envelope(
                    ok=False,
                    tool="import_handoff_state",
                    data={"error": f"Invalid import payload: items in snapshot.{key} must be objects."},
                )
    if "active" in snapshot and snapshot["active"] is not None and not isinstance(snapshot["active"], dict):
        return _envelope(
            ok=False,
            tool="import_handoff_state",
            data={"error": "Invalid import payload: snapshot.active must be an object."},
        )
    with _get_db_connection() as conn:
        if mode == "replace_task" and not allow_destructive_clear:
            existing_counts = _count_task_rows(conn, task_ref)
            incoming_counts = {
                key: len(snapshot.get(key, [])) for key in (*required_sections, "plan_cursors", "turn_metrics")
            }
            potentially_cleared = [
                section
                for section, existing_count in existing_counts.items()
                if existing_count > 0 and incoming_counts.get(section, 0) == 0
            ]
            if potentially_cleared:
                return _envelope(
                    ok=False,
                    tool="import_handoff_state",
                    data={
                        "error": f"replace_task would clear existing handoff rows in sections: {', '.join(potentially_cleared)}. Re-run with allow_destructive_clear=true to confirm.",
                        "existing_counts": existing_counts,
                        "incoming_counts": incoming_counts,
                    },
                    task_ref=task_ref,
                )
        counts = _import_snapshot(conn, task_ref=task_ref, snapshot=snapshot, mode=mode, set_active=set_active)
    return _envelope(
        ok=True,
        tool="import_handoff_state",
        data={
            "mode": mode,
            "set_active": set_active,
            "allow_destructive_clear": allow_destructive_clear,
            "counts": counts,
        },
        task_ref=task_ref,
        mutation={
            "entity": "handoff_state",
            "operation": f"import_{mode}",
            "affected_ids": [task_ref],
            "task_revision": snapshot.get("active", {}).get("revision")
            if isinstance(snapshot.get("active"), dict)
            else None,
        },
    )


def archive_task_state(
    task_ref: str | None = None,
    notes: str | None = None,
    archive_by: str | None = None,
    archive_branch: str | None = None,
    archive_commit_sha: str | None = None,
    clear_active_if_matches: bool = True,
    prune_working_rows: bool = False,
    allow_destructive_clear: bool = False,
) -> dict:
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        snapshot = _collect_task_snapshot(conn, resolved_task_ref)
        ctx = _resolve_write_actor(
            conn,
            build_write_actor(
                agent=archive_by,
                branch=archive_branch,
                commit_sha=archive_commit_sha,
            ),
        )
        warnings = collect_target_context_warnings(conn, ctx)
        if prune_working_rows and not allow_destructive_clear:
            working_counts = _count_task_rows(conn, resolved_task_ref)
            non_zero_sections = [section for section, count in working_counts.items() if count > 0]
            if non_zero_sections:
                return _envelope(
                    ok=False,
                    tool="archive_task_state",
                    data={
                        "error": f"prune_working_rows would clear handoff rows in sections: {', '.join(non_zero_sections)}. Re-run with allow_destructive_clear=true to confirm.",
                        "existing_counts": working_counts,
                    },
                    task_ref=resolved_task_ref,
                )
        _persist_task_archive_snapshot(
            conn,
            task_ref=resolved_task_ref,
            snapshot=snapshot,
            ctx=ctx,
            notes=notes or f"Archived {resolved_task_ref}",
        )
        active_cleared = False
        if clear_active_if_matches:
            active_row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
            if active_row is not None and str(active_row["task_ref"]) == resolved_task_ref:
                conn.execute("DELETE FROM handoff_state WHERE id = 1")
                active_cleared = True
        pruned = False
        if prune_working_rows:
            for table in (
                "decisions",
                "blockers",
                "next_actions",
                "verified_tests",
                "review_findings",
                "worktree_lanes",
                "worker_reports",
                "lane_messages",
                "plan_cursors",
            ):
                conn.execute(f"DELETE FROM {table} WHERE task_ref = ?", (resolved_task_ref,))
            pruned = True
    return _envelope(
        ok=True,
        tool="archive_task_state",
        data={
            "active_cleared": active_cleared,
            "pruned_working_rows": pruned,
            "allow_destructive_clear": allow_destructive_clear,
        },
        task_ref=resolved_task_ref,
        mutation={
            "entity": "task_archive",
            "operation": "archive",
            "affected_ids": [resolved_task_ref],
            "task_revision": None,
        },
        warnings=warnings or None,
    )


def get_archived_task(task_ref: str, include_snapshot: bool = True) -> dict:
    """Read an archived task row from ``task_archives`` by ``task_ref``.

    The handoff dashboard surfaces archive metadata in the cross-task view,
    but there is no MCP-side read tool for inspecting individual archive
    rows directly. Without this, callers (audit scripts, lifecycle tooling,
    review-handoff agents) had to either drop to raw sqlite — guessing
    column names — or roundtrip through ``export_handoff_state`` which only
    works for the currently-active task. AHMCP-16 closes the gap so the
    archive table is reachable through the same envelope as every other
    handoff read.

    Returns the archive row's metadata (``task_ref``, ``archived_at``,
    ``archived_by``, ``archived_branch``, ``archived_commit_sha``,
    ``notes``) plus the parsed snapshot when ``include_snapshot=True``.
    Returns ``ok=False`` with a structured error when no archive row
    exists for the given ``task_ref``.
    """
    normalized_task_ref = _normalize_optional_text(task_ref)
    if not normalized_task_ref:
        return _envelope(
            ok=False,
            tool="get_archived_task",
            data={"error": "task_ref must not be empty."},
        )
    with _get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT task_ref, archived_at, archived_by, archived_branch,
                   archived_commit_sha, notes, snapshot_json
            FROM task_archives WHERE task_ref = ?
            """,
            (normalized_task_ref,),
        ).fetchone()
    if row is None:
        return _envelope(
            ok=False,
            tool="get_archived_task",
            data={
                "error": f"No archived task found for task_ref={normalized_task_ref!r}.",
                "task_ref": normalized_task_ref,
            },
            task_ref=normalized_task_ref,
        )
    archive_metadata: dict[str, object] = {
        "task_ref": str(row["task_ref"]),
        "archived_at": str(row["archived_at"]) if row["archived_at"] is not None else None,
        "archived_by": str(row["archived_by"]) if row["archived_by"] is not None else None,
        "archived_branch": str(row["archived_branch"]) if row["archived_branch"] is not None else None,
        "archived_commit_sha": str(row["archived_commit_sha"]) if row["archived_commit_sha"] is not None else None,
        "notes": str(row["notes"]) if row["notes"] is not None else None,
    }
    data: dict[str, object] = {"archive": archive_metadata}
    if include_snapshot:
        snapshot_json = row["snapshot_json"]
        if snapshot_json is None:
            data["snapshot"] = None
            data["snapshot_parse_error"] = "snapshot_json column is null"
        else:
            try:
                data["snapshot"] = json.loads(snapshot_json)
            except json.JSONDecodeError as exc:
                # Defensive: surface the parse error rather than swallowing it.
                # The archive write path always serialises via json.dumps so a
                # parse failure indicates external tampering or a schema
                # migration mismatch — both worth flagging loudly.
                data["snapshot"] = None
                data["snapshot_parse_error"] = f"snapshot_json failed to parse: {exc}"
    return _envelope(
        ok=True,
        tool="get_archived_task",
        data=data,
        task_ref=normalized_task_ref,
    )


def update_task_status(
    task_ref: str,
    status: str,
    expected_revision: int | None = None,
    actor: WriteActor | None = None,
) -> dict:
    """Update task status for the active task or an archived/inactive task snapshot."""
    if status not in HANDOFF_ACTIVE_STATUSES:
        return _envelope(
            ok=False,
            tool="update_task_status",
            data={"error": f"Invalid status. Valid: {', '.join(sorted(HANDOFF_ACTIVE_STATUSES))}"},
            task_ref=task_ref,
        )

    with _get_db_connection() as conn:
        ctx = _resolve_write_actor(conn, actor)
        warnings = collect_target_context_warnings(conn, ctx)
        active_row = conn.execute(
            "SELECT * FROM handoff_state WHERE id = 1 AND task_ref = ?",
            (task_ref,),
        ).fetchone()

        if active_row is not None:
            from .handoff_state import set_handoff_state as _set_handoff_state

            delegated = _set_handoff_state(
                task_ref=task_ref,
                status=status,
                expected_revision=expected_revision,
                actor=actor,
            )
            if not delegated.get("ok"):
                return _envelope(
                    ok=False,
                    tool="update_task_status",
                    data=delegated.get("data", {}),
                    task_ref=task_ref,
                )
            active = delegated.get("data", {}).get("active", {}) or {}
            try:
                _write_current_task_md_for_task(conn, task_ref)
                regen = "ok"
            except Exception as exc:  # noqa: BLE001
                regen = str(exc)
            data: dict[str, object] = {
                "status": status,
                "updated_scope": "active",
                "active": active,
                "current_task_md_regen": "ok" if regen == "ok" else "failed",
            }
            if regen != "ok":
                data["current_task_md_regen_error"] = regen
            return _envelope(
                ok=True,
                tool="update_task_status",
                data=data,
                task_ref=task_ref,
                mutation={
                    "entity": "handoff_state",
                    "operation": "update_status",
                    "affected_ids": [task_ref],
                    "task_revision": active.get("revision"),
                },
                artifacts=[{"type": "file", "path": "CURRENT_TASK.md"}] if regen == "ok" else None,
            )

        archive_row = conn.execute(
            "SELECT snapshot_json FROM task_archives WHERE task_ref = ?",
            (task_ref,),
        ).fetchone()
        if archive_row is None:
            return _envelope(
                ok=False,
                tool="update_task_status",
                data={
                    "error": "Task is neither active nor archived; switch to it or archive it before updating its inactive status.",
                },
                task_ref=task_ref,
            )

        try:
            snapshot = json.loads(archive_row["snapshot_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return _envelope(
                ok=False,
                tool="update_task_status",
                data={
                    "error": "Archived snapshot is invalid JSON.",
                },
                task_ref=task_ref,
            )

        active_block = snapshot.get("active")
        if not isinstance(active_block, dict):
            active_block = {"task_ref": task_ref}
            snapshot["active"] = active_block
        active_block["task_ref"] = task_ref
        active_block["status"] = status
        active_block["updated_by"] = ctx.agent
        active_block["updated_branch"] = ctx.branch
        active_block["updated_commit_sha"] = ctx.commit_sha
        _persist_task_archive_snapshot(
            conn,
            task_ref=task_ref,
            snapshot=snapshot,
            ctx=ctx,
            notes=f"Updated archived status to {status}",
        )

        active_task_row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
        regen_result = "skipped"
        if active_task_row is not None:
            try:
                _write_current_task_md_for_task(conn, str(active_task_row["task_ref"]))
                regen_result = "ok"
            except Exception as exc:  # noqa: BLE001
                regen_result = str(exc)

        data_archived: dict[str, object] = {
            "status": status,
            "updated_scope": "archived",
            "current_task_md_regen": "ok" if regen_result == "ok" else regen_result,
        }
        if regen_result not in {"ok", "skipped"}:
            data_archived["current_task_md_regen"] = "failed"
            data_archived["current_task_md_regen_error"] = regen_result
        return _envelope(
            ok=True,
            tool="update_task_status",
            data=data_archived,
            task_ref=task_ref,
            mutation={
                "entity": "task_archive",
                "operation": "update_status",
                "affected_ids": [task_ref],
                "task_revision": None,
            },
            artifacts=[{"type": "file", "path": "CURRENT_TASK.md"}] if regen_result == "ok" else None,
            warnings=warnings or None,
        )


def switch_task(
    task_ref: str,
    objective: str | None = None,
    focus: str | None = None,
    status: str = "in_progress",
    actor: WriteActor | None = None,
    target_branch: str | None = None,
) -> dict:
    """Switch the active task, archiving the current one if different.

    If the target task was previously archived, its objective is restored
    automatically.  Pass *objective* explicitly to override.
    Focus is cleared on restore (stale focus from a previous session is misleading)
    unless explicitly provided.
    """
    if status not in HANDOFF_ACTIVE_STATUSES:
        return _envelope(
            ok=False,
            tool="switch_task",
            data={"error": f"Invalid status. Valid: {', '.join(sorted(HANDOFF_ACTIVE_STATUSES))}"},
            task_ref=task_ref,
        )

    with _get_db_connection() as conn:
        ctx = _resolve_write_actor(conn, actor)
        warnings = collect_target_context_warnings(conn, ctx)
        current = conn.execute("SELECT task_ref, objective, revision FROM handoff_state WHERE id = 1").fetchone()

        # Already active; nothing to do.
        if current is not None and str(current["task_ref"]) == task_ref:
            active = _row_to_dict(conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone())
            return _envelope(
                ok=True,
                tool="switch_task",
                data={"already_active": True, "active": active},
                task_ref=task_ref,
                warnings=warnings or None,
            )

        # Resolve objective and target_branch for the target task.
        resolved_objective = objective
        resolved_target_branch = target_branch
        resolved_focus = focus
        archive_row = conn.execute("SELECT snapshot_json FROM task_archives WHERE task_ref = ?", (task_ref,)).fetchone()
        if archive_row is not None:
            try:
                snapshot = json.loads(archive_row["snapshot_json"])
                active_block = snapshot.get("active")
                if isinstance(active_block, dict):
                    if resolved_objective is None and active_block.get("objective"):
                        resolved_objective = active_block["objective"]
                    if resolved_target_branch is None and active_block.get("target_branch"):
                        resolved_target_branch = active_block["target_branch"]
                    if focus is None:
                        resolved_focus = None
            except (json.JSONDecodeError, TypeError):
                pass
        if resolved_objective is None:
            return _envelope(
                ok=False,
                tool="switch_task",
                data={
                    "error": "Cannot determine objective for the target task. Pass --objective explicitly or archive the current task first.",
                },
                task_ref=task_ref,
            )

        # Archive the outgoing task so it can be restored later.
        archived_previous = False
        previous_task_ref = None
        if current is not None:
            previous_task_ref = str(current["task_ref"])
            snapshot = _collect_task_snapshot(conn, previous_task_ref)
            conn.execute(
                """
                INSERT INTO task_archives (task_ref, archived_at, archived_by, archived_branch, archived_commit_sha, notes, snapshot_json)
                VALUES (?, datetime('now'), ?, ?, ?, ?, ?)
                ON CONFLICT(task_ref) DO UPDATE SET
                    archived_at = datetime('now'),
                    archived_by = excluded.archived_by,
                    archived_branch = excluded.archived_branch,
                    archived_commit_sha = excluded.archived_commit_sha,
                    notes = excluded.notes,
                    snapshot_json = excluded.snapshot_json
                """,
                (
                    previous_task_ref,
                    ctx.agent,
                    ctx.branch,
                    ctx.commit_sha,
                    f"Auto-archived by switch_task to {task_ref}",
                    json.dumps(snapshot, sort_keys=True),
                ),
            )
            archived_previous = True

        # Upsert the singleton to point at the target task.
        if current is None:
            conn.execute(
                "INSERT INTO handoff_state (id, task_ref, objective, focus, status, target_branch, revision, updated_at, updated_by, updated_branch, updated_commit_sha) VALUES (1, ?, ?, ?, ?, ?, 0, datetime('now'), ?, ?, ?)",
                (
                    task_ref,
                    resolved_objective,
                    resolved_focus,
                    status,
                    resolved_target_branch,
                    ctx.agent,
                    ctx.branch,
                    ctx.commit_sha,
                ),
            )
        else:
            conn.execute(
                "UPDATE handoff_state SET task_ref = ?, objective = ?, focus = ?, status = ?, target_branch = ?, revision = revision + 1, updated_at = datetime('now'), updated_by = ?, updated_branch = ?, updated_commit_sha = ? WHERE id = 1",
                (
                    task_ref,
                    resolved_objective,
                    resolved_focus,
                    status,
                    resolved_target_branch,
                    ctx.agent,
                    ctx.branch,
                    ctx.commit_sha,
                ),
            )

        active = _row_to_dict(conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone())
        if active is None:
            return _envelope(
                ok=False,
                tool="switch_task",
                data={"error": "Active handoff state missing after task switch."},
                task_ref=task_ref,
            )
        regen_error: str | None = None
        try:
            _write_current_task_md_for_task(conn, task_ref)
        except Exception as exc:  # noqa: BLE001
            regen_error = str(exc)
        switch_data: dict[str, object] = {
            "switched": True,
            "active": active,
            "archived_previous": archived_previous,
            "previous_task_ref": previous_task_ref,
            "current_task_md_regen": "failed" if regen_error else "ok",
        }
        if regen_error is not None:
            switch_data["current_task_md_regen_error"] = regen_error
        return _envelope(
            ok=True,
            tool="switch_task",
            data=switch_data,
            task_ref=task_ref,
            mutation={
                "entity": "handoff_state",
                "operation": "switch_task",
                "affected_ids": [task_ref],
                "task_revision": active.get("revision"),
            },
            artifacts=[{"type": "file", "path": "CURRENT_TASK.md"}] if regen_error is None else None,
            warnings=warnings or None,
        )
