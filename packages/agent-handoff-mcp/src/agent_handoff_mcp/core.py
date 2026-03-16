from __future__ import annotations

import asyncio
import inspect
import json
import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from typing import Protocol, TypedDict, runtime_checkable

from .runtime import get_runtime_config


HANDOFF_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS handoff_state (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    task_ref          TEXT NOT NULL,
    objective         TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'in_progress'
                      CHECK (status IN ('in_progress', 'blocked', 'review', 'done')),
    revision          INTEGER NOT NULL DEFAULT 0,
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_by        TEXT,
    updated_branch    TEXT,
    updated_commit_sha TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    lane_id       TEXT,
    session       TEXT NOT NULL,
    decision      TEXT NOT NULL,
    rationale     TEXT,
    agent         TEXT,
    branch        TEXT,
    commit_sha    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS blockers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    lane_id       TEXT,
    description   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open', 'resolved')),
    agent         TEXT,
    branch        TEXT,
    commit_sha    TEXT,
    resolved_at   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (
        (status = 'open' AND resolved_at IS NULL)
        OR (status = 'resolved' AND resolved_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS next_actions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    lane_id       TEXT,
    action        TEXT NOT NULL,
    priority      INTEGER NOT NULL DEFAULT 100,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'done', 'skipped')),
    agent         TEXT,
    branch        TEXT,
    commit_sha    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS verified_tests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    lane_id       TEXT,
    command       TEXT NOT NULL,
    passed        INTEGER NOT NULL CHECK (passed IN (0, 1)),
    exit_code     INTEGER,
    result        TEXT,
    session       TEXT NOT NULL,
    agent         TEXT,
    branch        TEXT,
    commit_sha    TEXT,
    verified_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS task_archives (
    task_ref       TEXT PRIMARY KEY,
    archived_at    TEXT NOT NULL DEFAULT (datetime('now')),
    archived_by    TEXT,
    archived_branch TEXT,
    archived_commit_sha TEXT,
    notes          TEXT,
    snapshot_json  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    lane_id       TEXT,
    finding_id    TEXT NOT NULL,
    severity      TEXT NOT NULL CHECK (severity IN ('high', 'medium', 'low')),
    file_path     TEXT NOT NULL,
    line_start    INTEGER,
    line_end      INTEGER,
    description   TEXT NOT NULL,
    fix           TEXT,
    status        TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open', 'fixed', 'wontfix', 'deferred')),
    session       TEXT NOT NULL,
    agent         TEXT,
    branch        TEXT,
    commit_sha    TEXT,
    resolution_notes TEXT,
    reopen_count  INTEGER NOT NULL DEFAULT 0,
    last_reopen_reason TEXT,
    last_reopened_at TEXT,
    resolved_at   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS worktree_lanes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    lane_id       TEXT NOT NULL,
    title         TEXT,
    objective     TEXT,
    worktree_path TEXT NOT NULL,
    branch        TEXT NOT NULL,
    owner_agent   TEXT,
    status        TEXT NOT NULL DEFAULT 'planned'
                  CHECK (status IN ('planned', 'active', 'blocked', 'review', 'merged', 'closed')),
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(task_ref, lane_id)
);

CREATE TABLE IF NOT EXISTS worker_reports (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref          TEXT NOT NULL,
    lane_id           TEXT NOT NULL,
    session           TEXT NOT NULL,
    summary           TEXT NOT NULL,
    changed_files_json TEXT NOT NULL DEFAULT '[]',
    test_commands_json TEXT NOT NULL DEFAULT '[]',
    blockers_json      TEXT NOT NULL DEFAULT '[]',
    merge_ready       INTEGER NOT NULL DEFAULT 0 CHECK (merge_ready IN (0, 1)),
    status            TEXT NOT NULL DEFAULT 'submitted'
                      CHECK (status IN ('submitted', 'acknowledged', 'superseded')),
    agent             TEXT,
    branch            TEXT,
    commit_sha        TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lane_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    lane_id       TEXT NOT NULL,
    session       TEXT NOT NULL,
    direction     TEXT NOT NULL
                  CHECK (direction IN ('orchestrator_to_worker', 'worker_to_orchestrator')),
    subject       TEXT,
    message       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open', 'acknowledged', 'closed')),
    agent         TEXT,
    branch        TEXT,
    commit_sha    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plan_cursors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    plan_item_id  TEXT NOT NULL,
    state         TEXT NOT NULL
                  CHECK (state IN ('dispatched', 'completed', 'skipped', 'escalated')),
    lane_id       TEXT,
    mcp_action_id INTEGER,
    worker_message_id INTEGER,
    source_heading TEXT,
    summary       TEXT NOT NULL,
    dispatch_count INTEGER NOT NULL DEFAULT 0,
    dispatched_at TEXT,
    completed_at  TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(task_ref, plan_item_id)
);

CREATE INDEX IF NOT EXISTS idx_decisions_task_created
    ON decisions(task_ref, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_blockers_task_status
    ON blockers(task_ref, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_actions_task_status_priority
    ON next_actions(task_ref, status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_tests_task_verified
    ON verified_tests(task_ref, verified_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_archives_archived_at
    ON task_archives(archived_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_findings_task_status
    ON review_findings(task_ref, status, severity);
CREATE INDEX IF NOT EXISTS idx_lanes_task_status
    ON worktree_lanes(task_ref, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_worker_reports_task_lane
    ON worker_reports(task_ref, lane_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lane_messages_task_lane
    ON lane_messages(task_ref, lane_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_plan_cursors_task_state_lane
    ON plan_cursors(task_ref, state, lane_id, updated_at DESC);
"""

DEFAULT_HANDOFF_LIMITS = {
    "blockers": 5,
    "actions": 5,
    "decisions": 3,
    "tests": 3,
    "findings": 10,
}
HANDOFF_ACTIVE_STATUSES = {"in_progress", "blocked", "review", "done"}
REVIEW_FINDING_STATUSES = {"open", "fixed", "wontfix", "deferred"}
REVIEW_FINDING_SEVERITIES = {"high", "medium", "low"}
MAX_RESOLUTION_NOTES_LENGTH = 500
MAX_REOPEN_REASON_LENGTH = 500
SUBPROCESS_TIMEOUT = 10


class WriteActor(TypedDict, total=False):
    agent: str
    branch: str
    commit_sha: str
    lane_id: str


class ReviewFindingDetails(TypedDict, total=False):
    line_start: int
    line_end: int
    fix: str


def _workspace_root() -> Path:
    return get_runtime_config().workspace_root


def _current_task_path() -> Path:
    return get_runtime_config().current_task_path


def _exports_dir() -> Path:
    return get_runtime_config().exports_dir


def _get_db_connection() -> sqlite3.Connection:
    config = get_runtime_config()
    config.state_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.db_path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.executescript(HANDOFF_SCHEMA_SQL)
        _apply_handoff_migrations(conn)
    except Exception:
        conn.close()
        raise
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _resolve_task_ref(conn: sqlite3.Connection, task_ref: str | None) -> str:
    if task_ref:
        return task_ref
    row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
    if row is None:
        raise ValueError("No active task in handoff_state. Call set_handoff_state first or pass task_ref explicitly.")
    return str(row["task_ref"])


def _json_response(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row["name"]) == column_name for row in rows)


def _has_index(conn: sqlite3.Connection, table_name: str, index_name: str) -> bool:
    rows = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
    return any(str(row["name"]) == index_name for row in rows)


def _first_present(values: list[object]) -> object | None:
    for value in values:
        if isinstance(value, str):
            if value.strip() != "":
                return value
            continue
        if value is not None:
            return value
    return None


def _dedupe_review_findings(conn: sqlite3.Connection, task_ref: str | None = None) -> int:
    query = """
        SELECT task_ref, finding_id, COUNT(*) AS dup_count
        FROM review_findings
        {where_clause}
        GROUP BY task_ref, finding_id
        HAVING COUNT(*) > 1
    """
    params: tuple[object, ...] = ()
    where_clause = ""
    if task_ref is not None:
        where_clause = "WHERE task_ref = ?"
        params = (task_ref,)
    duplicate_groups = conn.execute(query.format(where_clause=where_clause), params).fetchall()
    removed_rows = 0
    for group in duplicate_groups:
        group_task_ref = str(group["task_ref"])
        group_finding_id = str(group["finding_id"])
        rows = conn.execute(
            """
            SELECT *
            FROM review_findings
            WHERE task_ref = ? AND finding_id = ?
            ORDER BY COALESCE(resolved_at, created_at) DESC, id DESC
            """,
            (group_task_ref, group_finding_id),
        ).fetchall()
        if len(rows) <= 1:
            continue
        keep_row = rows[0]
        keep_id = int(keep_row["id"])
        values_by_column = {column: [row[column] for row in rows] for column in keep_row.keys()}
        merged_created_at = min(
            [str(value) for value in values_by_column["created_at"] if isinstance(value, str) and value.strip() != ""],
            default=keep_row["created_at"],
        )
        reopen_counts = [int(value) for value in values_by_column.get("reopen_count", []) if isinstance(value, int)]
        conn.execute(
            """
            UPDATE review_findings
            SET severity = ?,
                file_path = ?,
                line_start = ?,
                line_end = ?,
                description = ?,
                fix = ?,
                status = ?,
                session = ?,
                agent = ?,
                branch = ?,
                commit_sha = ?,
                resolution_notes = ?,
                reopen_count = ?,
                last_reopen_reason = ?,
                last_reopened_at = ?,
                resolved_at = ?,
                created_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                _first_present(values_by_column["severity"]) or "low",
                _first_present(values_by_column["file_path"]) or "",
                _first_present(values_by_column["line_start"]),
                _first_present(values_by_column["line_end"]),
                _first_present(values_by_column["description"]) or "",
                _first_present(values_by_column["fix"]),
                _first_present(values_by_column["status"]) or "open",
                _first_present(values_by_column["session"]) or "migration",
                _first_present(values_by_column["agent"]),
                _first_present(values_by_column["branch"]),
                _first_present(values_by_column["commit_sha"]),
                _first_present(values_by_column["resolution_notes"]),
                max(reopen_counts, default=0),
                _first_present(values_by_column.get("last_reopen_reason", [])),
                _first_present(values_by_column.get("last_reopened_at", [])),
                _first_present(values_by_column["resolved_at"]),
                merged_created_at,
                _first_present(values_by_column.get("updated_at", []))
                or _first_present(values_by_column["resolved_at"])
                or merged_created_at,
                keep_id,
            ),
        )
        conn.execute(
            "DELETE FROM review_findings WHERE task_ref = ? AND finding_id = ? AND id <> ?",
            (group_task_ref, group_finding_id, keep_id),
        )
        removed_rows += len(rows) - 1
    return removed_rows


def _ensure_review_findings_unique_index(conn: sqlite3.Connection) -> None:
    index_name = "idx_review_findings_task_finding_unique"
    if _has_index(conn, "review_findings", index_name):
        return
    _dedupe_review_findings(conn)
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_review_findings_task_finding_unique
        ON review_findings(task_ref, finding_id)
        """
    )


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


def _build_current_task_state_from_snapshot(snapshot: dict) -> dict:
    return {
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


def _write_current_task_md_for_task(conn: sqlite3.Connection, task_ref: str) -> None:
    snapshot = _collect_task_snapshot(conn, task_ref)
    _current_task_path().write_text(_render_current_task_md(_build_current_task_state_from_snapshot(snapshot)))


def _apply_handoff_migrations(conn: sqlite3.Connection) -> None:
    try:
        needs_backfill = False
        # lane_id migration -- add to all per-task tables once
        for table in ("decisions", "blockers", "next_actions", "verified_tests", "review_findings"):
            if not _has_column(conn, table, "lane_id"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN lane_id TEXT")
        # review_findings extra columns
        for column, sql in [
            ("resolution_notes", "ALTER TABLE review_findings ADD COLUMN resolution_notes TEXT"),
            ("reopen_count", "ALTER TABLE review_findings ADD COLUMN reopen_count INTEGER NOT NULL DEFAULT 0"),
            ("last_reopen_reason", "ALTER TABLE review_findings ADD COLUMN last_reopen_reason TEXT"),
            ("last_reopened_at", "ALTER TABLE review_findings ADD COLUMN last_reopened_at TEXT"),
            ("updated_at", "ALTER TABLE review_findings ADD COLUMN updated_at TEXT"),
        ]:
            if not _has_column(conn, "review_findings", column):
                conn.execute(sql)
                needs_backfill = True
        if not needs_backfill:
            needs_backfill = conn.execute(
                """
                SELECT 1
                FROM review_findings
                WHERE reopen_count IS NULL
                   OR updated_at IS NULL
                   OR TRIM(updated_at) = ''
                LIMIT 1
                """
            ).fetchone() is not None
        if needs_backfill:
            conn.execute(
                """
                UPDATE review_findings
                SET reopen_count = COALESCE(reopen_count, 0),
                    updated_at = COALESCE(NULLIF(TRIM(updated_at), ''), resolved_at, created_at, datetime('now'))
                """
            )
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            import logging
            logging.getLogger("agent_handoff_mcp").warning("DB locked during migration -- skipping (PRAGMA busy_timeout should prevent this)")
            return
        raise
    try:
        _ensure_review_findings_unique_index(conn)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            import logging
            logging.getLogger("agent_handoff_mcp").warning("DB locked during unique index creation -- skipping")
            return
        raise


def _resolve_awaitable(value: object) -> object:
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    box: dict[str, object] = {}

    def _runner() -> None:
        try:
            box["value"] = asyncio.run(value)
        except Exception as exc:
            box["error"] = exc
            box["traceback"] = exc.__traceback__

    thread = Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        error = box["error"]
        if isinstance(error, Exception) and box.get("traceback") is not None:
            error = error.with_traceback(box["traceback"])  # type: ignore[arg-type]
        raise error  # type: ignore[misc]
    return box.get("value")


def _normalize_tool_result(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    structured_content = getattr(value, "structured_content", None)
    if isinstance(structured_content, dict):
        structured_result = structured_content.get("result")
        if isinstance(structured_result, str):
            return structured_result
    text = getattr(value, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(value, "content", None)
    if isinstance(content, list):
        parts = [item.text for item in content if isinstance(getattr(item, "text", None), str)]
        if parts:
            return "\n".join(parts)
    return str(value)


@runtime_checkable
class _FnWrappedTool(Protocol):
    fn: object


@runtime_checkable
class _FunctionWrappedTool(Protocol):
    function: object


@runtime_checkable
class _FuncWrappedTool(Protocol):
    func: object


@runtime_checkable
class _RunnableTool(Protocol):
    def run(self, arguments: dict[str, object]) -> object: ...


def _unwrap_tool_candidate(candidate: object) -> object | None:
    if isinstance(candidate, _FnWrappedTool) and candidate.fn is not candidate:
        return candidate.fn
    if isinstance(candidate, _FunctionWrappedTool) and candidate.function is not candidate:
        return candidate.function
    if isinstance(candidate, _FuncWrappedTool) and candidate.func is not candidate:
        return candidate.func
    return None


def _invoke_tool(tool: object, **kwargs: object) -> str:
    candidate: object = tool
    visited: set[int] = set()
    for _ in range(10):
        if inspect.isawaitable(candidate):
            candidate = _resolve_awaitable(candidate)
            continue
        if callable(candidate):
            return _normalize_tool_result(_resolve_awaitable(candidate(**kwargs)))
        marker = id(candidate)
        if marker in visited:
            break
        visited.add(marker)
        unwrapped = _unwrap_tool_candidate(candidate)
        if unwrapped is not None:
            candidate = unwrapped
            continue
        if isinstance(candidate, _RunnableTool):
            return _normalize_tool_result(_resolve_awaitable(candidate.run(kwargs)))
        break
    raise TypeError(f"Unable to invoke tool of type {type(tool).__name__}")


def _utcnow_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _render_current_task_md(state: dict) -> str:
    active = state.get("active")
    if not active:
        return "# CURRENT_TASK\n\n_DO NOT EDIT: generated from .task-state/handoff.db._\n\nNo active handoff state found.\n"
    lines = [
        "# CURRENT_TASK",
        "",
        "_DO NOT EDIT: generated from .task-state/handoff.db._",
        "",
        "## Objective",
        f"{active.get('objective', '')}",
        "",
        "## Active Status",
        f"- task_ref: `{active.get('task_ref', '')}`",
        f"- status: `{active.get('status', '')}`",
        f"- revision: `{active.get('revision', 0)}`",
        f"- updated_at: `{active.get('updated_at', '')}`",
        "",
        "## Open Blockers",
    ]
    for section, empty_text, formatter in [
        ("blockers_open", "- None", lambda item: f"- [#{item.get('id')}] {item.get('description')}"),
        ("actions_pending", "- None", lambda item: f"- (P{item.get('priority')}) [#{item.get('id')}] {item.get('action')}"),
        ("decisions_recent", "- None", lambda item: f"- [#{item.get('id')}] {item.get('decision')}"),
        ("tests_recent", "- None", lambda item: f"- [#{item.get('id')}] `{item.get('command')}` -> `{'pass' if item.get('passed') else 'fail'}`"),
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
    lanes = state.get("worktree_lanes", [])
    lines.extend(["", "## Worktree Lanes"])
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
    lines.extend(["", "## Open Review Findings"])
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

    lines.append("")
    return "\n".join(lines)


def _collect_task_snapshot(conn: sqlite3.Connection, task_ref: str) -> dict:
    active_row = conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone()
    active = _row_to_dict(active_row) if active_row is not None and active_row["task_ref"] == task_ref else None

    def _rows(query: str) -> list[dict]:
        return [dict(row) for row in conn.execute(query, (task_ref,)).fetchall()]

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
    }


def _fetch_handoff_rows(conn: sqlite3.Connection, *, table: str, where_sql: str, order_sql: str, limit: int, params: tuple[object, ...]) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM {table} WHERE {where_sql} ORDER BY {order_sql} LIMIT ?", (*params, limit)).fetchall()
    return [dict(row) for row in rows]


def _fetch_related_open_findings(task_refs: list[str]) -> dict[str, list[dict]]:
    """Query open review findings for multiple task_refs, grouped by task_ref."""
    if not task_refs:
        return {}
    with _get_db_connection() as conn:
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


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized != "" else None


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
            return row
    return None


def _first_non_empty_env(*keys: str) -> str | None:
    for key in keys:
        candidate = _normalize_optional_text(os.environ.get(key))
        if candidate is not None:
            return candidate
    return None

def _run_cmd(cmd: list[str], timeout: int = SUBPROCESS_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=str(_workspace_root()),
        timeout=timeout,
    )


def _detect_git_write_context() -> tuple[str | None, str | None]:
    branch = _first_non_empty_env(
        "AGENT_HANDOFF_DEFAULT_BRANCH",
        "GITHUB_HEAD_REF",
        "GITHUB_REF_NAME",
        "CI_COMMIT_REF_NAME",
        "BRANCH_NAME",
    )
    commit_sha = _first_non_empty_env(
        "AGENT_HANDOFF_DEFAULT_COMMIT_SHA",
        "GITHUB_SHA",
        "CI_COMMIT_SHA",
    )
    try:
        branch_proc = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if branch_proc.returncode == 0:
            raw_branch = _normalize_optional_text(branch_proc.stdout)
            if raw_branch is not None and raw_branch != "HEAD":
                branch = raw_branch
            elif raw_branch == "HEAD" and branch is None:
                branch = "detached-head"
    except Exception:
        pass
    try:
        commit_proc = _run_cmd(["git", "rev-parse", "HEAD"])
        if commit_proc.returncode == 0:
            commit_sha = _normalize_optional_text(commit_proc.stdout)
    except Exception:
        pass
    if branch is None:
        branch = "unknown-branch"
    return branch, commit_sha


def _resolve_write_actor(conn: sqlite3.Connection, actor: WriteActor | None) -> tuple[str | None, str | None, str | None, str | None]:
    explicit_agent = _normalize_optional_text(actor.get("agent")) if actor else None
    explicit_branch = _normalize_optional_text(actor.get("branch")) if actor else None
    explicit_commit = _normalize_optional_text(actor.get("commit_sha")) if actor else None
    explicit_lane = _normalize_optional_text(actor.get("lane_id")) if actor else None
    default_agent = _normalize_optional_text(os.environ.get("AGENT_HANDOFF_DEFAULT_AGENT")) or "codex"
    active = conn.execute("SELECT updated_by, updated_branch, updated_commit_sha FROM handoff_state WHERE id = 1").fetchone()
    active_agent = _normalize_optional_text(active["updated_by"]) if active is not None else None
    active_branch = _normalize_optional_text(active["updated_branch"]) if active is not None else None
    active_commit = _normalize_optional_text(active["updated_commit_sha"]) if active is not None else None
    git_branch, git_commit = _detect_git_write_context()
    preferred_git_branch = git_branch if git_branch not in (None, "unknown-branch") else None
    return (
        explicit_agent or active_agent or default_agent,
        explicit_branch or preferred_git_branch or active_branch or git_branch,
        explicit_commit or git_commit or active_commit,
        explicit_lane,
    )


def _parse_review_finding_details(details: ReviewFindingDetails | None) -> tuple[int | None, int | None, str | None]:
    if not details:
        return None, None, None
    return details.get("line_start"), details.get("line_end"), details.get("fix")


def _resolve_import_row_actor(row: dict, *, fallback_agent: str, fallback_branch: str, fallback_commit: str | None) -> tuple[str, str, str | None]:
    return (
        _normalize_optional_text(row.get("agent")) or fallback_agent,
        _normalize_optional_text(row.get("branch")) or fallback_branch,
        _normalize_optional_text(row.get("commit_sha")) or fallback_commit,
    )


def _resolve_import_lane_id(row: dict) -> str | None:
    return _normalize_optional_text(row.get("lane_id"))


def _count_task_rows(conn: sqlite3.Connection, task_ref: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in ("blockers", "next_actions", "decisions", "verified_tests", "review_findings", "worktree_lanes", "worker_reports", "lane_messages", "plan_cursors"):
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {key} WHERE task_ref = ?", (task_ref,)).fetchone()
        counts[key] = int(row["count"]) if row else 0
    return counts


def _resolve_output_path(output_path: str | None, task_ref: str) -> Path:
    if output_path:
        path = Path(output_path)
        if not path.is_absolute():
            path = _workspace_root() / path
    else:
        safe_task_ref = task_ref.replace("/", "_").replace("..", "_")
        path = _exports_dir() / f"handoff-{safe_task_ref}.json"
        resolved = path.resolve()
        allowed_root = _workspace_root().resolve()
        if not str(resolved).startswith(str(allowed_root) + "/") and resolved != allowed_root:
            raise ValueError(f"Output path escapes workspace root: {resolved}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def set_handoff_state(task_ref: str, objective: str, status: str = "in_progress", expected_revision: int | None = None, actor: WriteActor | None = None) -> str:
    if status not in HANDOFF_ACTIVE_STATUSES:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(HANDOFF_ACTIVE_STATUSES))}"})
    with _get_db_connection() as conn:
        agent, branch, commit_sha, _lane_id = _resolve_write_actor(conn, actor)
        current = conn.execute("SELECT revision FROM handoff_state WHERE id = 1").fetchone()
        if current is None:
            conn.execute(
                """
                INSERT INTO handoff_state (
                    id, task_ref, objective, status, revision, updated_at, updated_by, updated_branch, updated_commit_sha
                ) VALUES (1, ?, ?, ?, 0, datetime('now'), ?, ?, ?)
                """,
                (task_ref, objective, status, agent, branch, commit_sha),
            )
            return _json_response({"ok": True, "inserted": True, "active": _row_to_dict(conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone())})
        if expected_revision is None:
            return _json_response({"ok": False, "error": "expected_revision is required for updates.", "current_revision": int(current["revision"])})
        updated = conn.execute(
            """
            UPDATE handoff_state
            SET task_ref = ?, objective = ?, status = ?, revision = revision + 1, updated_at = datetime('now'),
                updated_by = ?, updated_branch = ?, updated_commit_sha = ?
            WHERE id = 1 AND revision = ?
            """,
            (task_ref, objective, status, agent, branch, commit_sha, expected_revision),
        )
        if updated.rowcount == 0:
            latest = conn.execute("SELECT revision FROM handoff_state WHERE id = 1").fetchone()
            return _json_response({"ok": False, "error": "Revision conflict.", "expected_revision": expected_revision, "current_revision": int(latest["revision"]) if latest else None})
        return _json_response({"ok": True, "updated": True, "active": _row_to_dict(conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone())})


def get_handoff_state(task_ref: str | None = None, top_n_blockers: int = DEFAULT_HANDOFF_LIMITS["blockers"], top_n_actions: int = DEFAULT_HANDOFF_LIMITS["actions"], top_n_decisions: int = DEFAULT_HANDOFF_LIMITS["decisions"], top_n_tests: int = DEFAULT_HANDOFF_LIMITS["tests"], top_n_findings: int = DEFAULT_HANDOFF_LIMITS["findings"], verbose: bool = False) -> str:
    top_n_blockers = max(1, top_n_blockers)
    top_n_actions = max(1, top_n_actions)
    top_n_decisions = max(1, top_n_decisions)
    top_n_tests = max(1, top_n_tests)
    top_n_findings = max(1, top_n_findings)
    with _get_db_connection() as conn:
        active_row = conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone()
        if active_row is None and task_ref is None:
            return _json_response({"ok": True, "active": None, "message": "No active handoff state."})
        resolved_task_ref = task_ref or str(active_row["task_ref"])
        active = _row_to_dict(active_row) if active_row is not None else None
        if active is not None and resolved_task_ref != active["task_ref"]:
            active = None
        current_lane_row = _resolve_current_lane_row(conn, resolved_task_ref)
        current_lane = _row_to_dict(current_lane_row)
        query_limit = (lambda size: size if not verbose else 10000)
        lane_messages_where_sql = "task_ref = ? AND status = 'open'"
        lane_messages_params: tuple[object, ...] = (resolved_task_ref,)
        if current_lane_row is not None:
            lane_messages_where_sql += " AND lane_id = ?"
            lane_messages_params = (resolved_task_ref, str(current_lane_row["lane_id"]))
        return _json_response(
            {
                "ok": True,
                "limits": {"blockers": top_n_blockers, "actions": top_n_actions, "decisions": top_n_decisions, "tests": top_n_tests, "findings": top_n_findings},
                "task_ref": resolved_task_ref,
                "active": active,
                "current_lane": current_lane,
                "blockers_open": _fetch_handoff_rows(conn, table="blockers", where_sql="task_ref = ? AND status = 'open'", order_sql="created_at DESC", limit=query_limit(top_n_blockers), params=(resolved_task_ref,)),
                "actions_pending": _fetch_handoff_rows(conn, table="next_actions", where_sql="task_ref = ? AND status = 'pending'", order_sql="priority ASC, created_at ASC", limit=query_limit(top_n_actions), params=(resolved_task_ref,)),
                "decisions_recent": _fetch_handoff_rows(conn, table="decisions", where_sql="task_ref = ?", order_sql="created_at DESC", limit=query_limit(top_n_decisions), params=(resolved_task_ref,)),
                "tests_recent": _fetch_handoff_rows(conn, table="verified_tests", where_sql="task_ref = ?", order_sql="verified_at DESC", limit=query_limit(top_n_tests), params=(resolved_task_ref,)),
                "findings_open": _fetch_handoff_rows(conn, table="review_findings", where_sql="task_ref = ? AND status = 'open'", order_sql="CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, created_at DESC", limit=query_limit(top_n_findings), params=(resolved_task_ref,)),
                "worktree_lanes": _fetch_handoff_rows(conn, table="worktree_lanes", where_sql="task_ref = ?", order_sql="updated_at DESC, id DESC", limit=50, params=(resolved_task_ref,)),
                "worker_reports_recent": _fetch_handoff_rows(conn, table="worker_reports", where_sql="task_ref = ?", order_sql="created_at DESC, id DESC", limit=query_limit(top_n_tests), params=(resolved_task_ref,)),
                "lane_messages_open": _fetch_handoff_rows(conn, table="lane_messages", where_sql=lane_messages_where_sql, order_sql="updated_at DESC, id DESC", limit=50, params=lane_messages_params),
            }
        )


def _get_lane_row(conn: sqlite3.Connection, task_ref: str, lane_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM worktree_lanes WHERE task_ref = ? AND lane_id = ?",
        (task_ref, lane_id),
    ).fetchone()


def upsert_worktree_lane(
    lane_id: str,
    worktree_path: str,
    branch: str,
    title: str | None = None,
    objective: str | None = None,
    owner_agent: str | None = None,
    status: str = "planned",
    notes: str | None = None,
) -> str:
    valid_statuses = {"planned", "active", "blocked", "review", "merged", "closed"}
    normalized_lane_id = _normalize_optional_text(lane_id)
    normalized_path = _normalize_optional_text(worktree_path)
    normalized_branch = _normalize_optional_text(branch)
    if normalized_lane_id is None:
        return _json_response({"ok": False, "error": "lane_id is required."})
    if normalized_path is None:
        return _json_response({"ok": False, "error": "worktree_path is required."})
    if normalized_branch is None:
        return _json_response({"ok": False, "error": "branch is required."})
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    with _get_db_connection() as conn:
        task_ref = _resolve_task_ref(conn, None)
        conn.execute(
            """
            INSERT INTO worktree_lanes (task_ref, lane_id, title, objective, worktree_path, branch, owner_agent, status, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(task_ref, lane_id) DO UPDATE SET
                title = excluded.title,
                objective = excluded.objective,
                worktree_path = excluded.worktree_path,
                branch = excluded.branch,
                owner_agent = excluded.owner_agent,
                status = excluded.status,
                notes = excluded.notes,
                updated_at = datetime('now')
            """,
            (task_ref, normalized_lane_id, title, objective, normalized_path, normalized_branch, owner_agent, status, notes),
        )
        row = _get_lane_row(conn, task_ref, normalized_lane_id)
        _write_current_task_md_for_task(conn, task_ref)
        return _json_response({"ok": True, "lane": _row_to_dict(row)})


def list_worktree_lanes(task_ref: str | None = None, status: str = "all", limit: int = 100, offset: int = 0) -> str:
    limit = max(1, limit)
    offset = max(0, offset)
    valid_statuses = {"all", "planned", "active", "blocked", "review", "merged", "closed"}
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        params: list[object] = [resolved_task_ref]
        where_sql = "task_ref = ?"
        if status != "all":
            where_sql += " AND status = ?"
            params.append(status)
        total = int(conn.execute(f"SELECT COUNT(*) AS count FROM worktree_lanes WHERE {where_sql}", tuple(params)).fetchone()["count"])
        rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM worktree_lanes WHERE {where_sql} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        ]
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "status": status,
                "total_matching": total,
                "returned": len(rows),
                "has_more": offset + len(rows) < total,
                "lanes": rows,
            }
        )


def get_lane_activity(
    lane_id: str,
    task_ref: str | None = None,
    limit_decisions: int = 20,
    limit_tests: int = 20,
    limit_blockers: int = 20,
    limit_actions: int = 20,
    limit_findings: int = 20,
) -> str:
    normalized_lane_id = _normalize_optional_text(lane_id)
    if normalized_lane_id is None:
        return _json_response({"ok": False, "error": "lane_id is required."})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        lane = _get_lane_row(conn, resolved_task_ref, normalized_lane_id)
        if lane is None:
            return _json_response({"ok": False, "error": "Lane not found for task_ref."})
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "lane": dict(lane),
                "decisions": _fetch_handoff_rows(conn, table="decisions", where_sql="task_ref = ? AND lane_id = ?", order_sql="created_at DESC, id DESC", limit=max(1, limit_decisions), params=(resolved_task_ref, normalized_lane_id)),
                "tests": _fetch_handoff_rows(conn, table="verified_tests", where_sql="task_ref = ? AND lane_id = ?", order_sql="verified_at DESC, id DESC", limit=max(1, limit_tests), params=(resolved_task_ref, normalized_lane_id)),
                "blockers": _fetch_handoff_rows(conn, table="blockers", where_sql="task_ref = ? AND lane_id = ?", order_sql="created_at DESC, id DESC", limit=max(1, limit_blockers), params=(resolved_task_ref, normalized_lane_id)),
                "actions": _fetch_handoff_rows(conn, table="next_actions", where_sql="task_ref = ? AND lane_id = ?", order_sql="updated_at DESC, id DESC", limit=max(1, limit_actions), params=(resolved_task_ref, normalized_lane_id)),
                "findings": _fetch_handoff_rows(conn, table="review_findings", where_sql="task_ref = ? AND lane_id = ?", order_sql="COALESCE(updated_at, created_at) DESC, id DESC", limit=max(1, limit_findings), params=(resolved_task_ref, normalized_lane_id)),
                "reports": _fetch_handoff_rows(conn, table="worker_reports", where_sql="task_ref = ? AND lane_id = ?", order_sql="created_at DESC, id DESC", limit=20, params=(resolved_task_ref, normalized_lane_id)),
                "messages": _fetch_handoff_rows(conn, table="lane_messages", where_sql="task_ref = ? AND lane_id = ?", order_sql="updated_at DESC, id DESC", limit=20, params=(resolved_task_ref, normalized_lane_id)),
            }
        )


def record_worker_report(
    lane_id: str,
    session: str,
    summary: str,
    changed_files: list[str] | None = None,
    test_commands: list[str] | None = None,
    blockers: list[str] | None = None,
    merge_ready: bool = False,
    status: str = "submitted",
    actor: WriteActor | None = None,
) -> str:
    valid_statuses = {"submitted", "acknowledged", "superseded"}
    normalized_lane_id = _normalize_optional_text(lane_id)
    if normalized_lane_id is None:
        return _json_response({"ok": False, "error": "lane_id is required."})
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        if _get_lane_row(conn, resolved_task_ref, normalized_lane_id) is None:
            return _json_response({"ok": False, "error": "Lane not found for active task."})
        agent, branch, commit_sha, _actor_lane_id = _resolve_write_actor(conn, actor)
        cur = conn.execute(
            """
            INSERT INTO worker_reports (
                task_ref, lane_id, session, summary, changed_files_json, test_commands_json, blockers_json,
                merge_ready, status, agent, branch, commit_sha, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                resolved_task_ref,
                normalized_lane_id,
                session,
                summary,
                json.dumps(changed_files or []),
                json.dumps(test_commands or []),
                json.dumps(blockers or []),
                1 if merge_ready else 0,
                status,
                agent,
                branch,
                commit_sha,
            ),
        )
        row = _row_to_dict(conn.execute("SELECT * FROM worker_reports WHERE id = ?", (cur.lastrowid,)).fetchone())
        _write_current_task_md_for_task(conn, resolved_task_ref)
        return _json_response({"ok": True, "report": row})


def list_worker_reports(task_ref: str | None = None, lane_id: str | None = None, limit: int = 20, offset: int = 0) -> str:
    limit = max(1, limit)
    offset = max(0, offset)
    normalized_lane_id = _normalize_optional_text(lane_id)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        params: list[object] = [resolved_task_ref]
        where_sql = "task_ref = ?"
        if normalized_lane_id is not None:
            where_sql += " AND lane_id = ?"
            params.append(normalized_lane_id)
        total = int(conn.execute(f"SELECT COUNT(*) AS count FROM worker_reports WHERE {where_sql}", tuple(params)).fetchone()["count"])
        rows = [dict(row) for row in conn.execute(f"SELECT * FROM worker_reports WHERE {where_sql} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()]
        return _json_response({"ok": True, "task_ref": resolved_task_ref, "lane_id": normalized_lane_id, "total_matching": total, "returned": len(rows), "has_more": offset + len(rows) < total, "reports": rows})


def record_lane_message(
    lane_id: str,
    session: str,
    direction: str,
    message: str,
    subject: str | None = None,
    status: str = "open",
    actor: WriteActor | None = None,
) -> str:
    valid_directions = {"orchestrator_to_worker", "worker_to_orchestrator"}
    valid_statuses = {"open", "acknowledged", "closed"}
    normalized_lane_id = _normalize_optional_text(lane_id)
    if normalized_lane_id is None:
        return _json_response({"ok": False, "error": "lane_id is required."})
    if direction not in valid_directions:
        return _json_response({"ok": False, "error": f"Invalid direction. Valid: {', '.join(sorted(valid_directions))}"})
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        if _get_lane_row(conn, resolved_task_ref, normalized_lane_id) is None:
            return _json_response({"ok": False, "error": "Lane not found for active task."})
        agent, branch, commit_sha, _actor_lane_id = _resolve_write_actor(conn, actor)
        cur = conn.execute(
            """
            INSERT INTO lane_messages (task_ref, lane_id, session, direction, subject, message, status, agent, branch, commit_sha, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (resolved_task_ref, normalized_lane_id, session, direction, subject, message, status, agent, branch, commit_sha),
        )
        row = _row_to_dict(conn.execute("SELECT * FROM lane_messages WHERE id = ?", (cur.lastrowid,)).fetchone())
        _write_current_task_md_for_task(conn, resolved_task_ref)
        return _json_response({"ok": True, "message": row})


def update_lane_message(message_id: int, status: str, actor: WriteActor | None = None) -> str:
    valid_statuses = {"open", "acknowledged", "closed"}
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        row = conn.execute("SELECT * FROM lane_messages WHERE id = ? AND task_ref = ?", (message_id, resolved_task_ref)).fetchone()
        if row is None:
            return _json_response({"ok": False, "error": "Message not found for active task."})
        agent, branch, commit_sha, _actor_lane_id = _resolve_write_actor(conn, actor)
        conn.execute(
            "UPDATE lane_messages SET status = ?, agent = COALESCE(agent, ?), branch = COALESCE(branch, ?), commit_sha = COALESCE(commit_sha, ?), updated_at = datetime('now') WHERE id = ? AND task_ref = ?",
            (status, agent, branch, commit_sha, message_id, resolved_task_ref),
        )
        updated = _row_to_dict(conn.execute("SELECT * FROM lane_messages WHERE id = ?", (message_id,)).fetchone())
        _write_current_task_md_for_task(conn, resolved_task_ref)
        return _json_response({"ok": True, "message": updated})


def list_lane_messages(task_ref: str | None = None, lane_id: str | None = None, status: str = "all", limit: int = 20, offset: int = 0) -> str:
    valid_statuses = {"all", "open", "acknowledged", "closed"}
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    limit = max(1, limit)
    offset = max(0, offset)
    normalized_lane_id = _normalize_optional_text(lane_id)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        inferred_lane = None
        if normalized_lane_id is None:
            inferred_lane_row = _resolve_current_lane_row(conn, resolved_task_ref)
            if inferred_lane_row is not None:
                normalized_lane_id = str(inferred_lane_row["lane_id"])
                inferred_lane = _row_to_dict(inferred_lane_row)
        params: list[object] = [resolved_task_ref]
        where_sql = "task_ref = ?"
        if normalized_lane_id is not None:
            where_sql += " AND lane_id = ?"
            params.append(normalized_lane_id)
        if status != "all":
            where_sql += " AND status = ?"
            params.append(status)
        total = int(conn.execute(f"SELECT COUNT(*) AS count FROM lane_messages WHERE {where_sql}", tuple(params)).fetchone()["count"])
        rows = [dict(row) for row in conn.execute(f"SELECT * FROM lane_messages WHERE {where_sql} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()]
        return _json_response({"ok": True, "task_ref": resolved_task_ref, "lane_id": normalized_lane_id, "current_lane": inferred_lane, "status": status, "total_matching": total, "returned": len(rows), "has_more": offset + len(rows) < total, "messages": rows})


def upsert_plan_cursor(
    plan_item_id: str,
    state: str,
    lane_id: str | None = None,
    mcp_action_id: int | None = None,
    worker_message_id: int | None = None,
    source_heading: str | None = None,
    summary: str | None = None,
    task_ref: str | None = None,
) -> str:
    valid_states = {"dispatched", "completed", "skipped", "escalated"}
    normalized_plan_item_id = _normalize_optional_text(plan_item_id)
    normalized_lane_id = _normalize_optional_text(lane_id)
    normalized_heading = _normalize_optional_text(source_heading)
    normalized_summary = _normalize_optional_text(summary)
    if normalized_plan_item_id is None:
        return _json_response({"ok": False, "error": "plan_item_id is required."})
    if state not in valid_states:
        return _json_response({"ok": False, "error": f"Invalid state. Valid: {', '.join(sorted(valid_states))}"})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        existing = conn.execute(
            "SELECT * FROM plan_cursors WHERE task_ref = ? AND plan_item_id = ?",
            (resolved_task_ref, normalized_plan_item_id),
        ).fetchone()
        if existing is None and normalized_summary is None:
            return _json_response({"ok": False, "error": "summary is required when creating a new plan cursor."})

        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO plan_cursors (
                    task_ref, plan_item_id, state, lane_id, mcp_action_id, worker_message_id,
                    source_heading, summary, dispatch_count, dispatched_at, completed_at, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    CASE WHEN ? = 'dispatched' THEN 1 ELSE 0 END,
                    CASE WHEN ? = 'dispatched' THEN datetime('now') ELSE NULL END,
                    CASE WHEN ? = 'completed' THEN datetime('now') ELSE NULL END,
                    datetime('now'), datetime('now')
                )
                """,
                (
                    resolved_task_ref,
                    normalized_plan_item_id,
                    state,
                    normalized_lane_id,
                    mcp_action_id,
                    worker_message_id,
                    normalized_heading,
                    normalized_summary,
                    state,
                    state,
                    state,
                ),
            )
            row = _row_to_dict(conn.execute("SELECT * FROM plan_cursors WHERE id = ?", (cur.lastrowid,)).fetchone())
            return _json_response({"ok": True, "cursor": row})

        next_summary = normalized_summary or str(existing["summary"])
        next_lane_id = normalized_lane_id or _normalize_optional_text(existing["lane_id"])
        next_heading = normalized_heading or _normalize_optional_text(existing["source_heading"])
        next_action_id = mcp_action_id if mcp_action_id is not None else existing["mcp_action_id"]
        next_worker_message_id = worker_message_id if worker_message_id is not None else existing["worker_message_id"]
        dispatch_count = int(existing["dispatch_count"] or 0) + (1 if state == "dispatched" else 0)
        conn.execute(
            """
            UPDATE plan_cursors
            SET state = ?,
                lane_id = ?,
                mcp_action_id = ?,
                worker_message_id = ?,
                source_heading = ?,
                summary = ?,
                dispatch_count = ?,
                dispatched_at = CASE WHEN ? = 'dispatched' THEN datetime('now') ELSE dispatched_at END,
                completed_at = CASE WHEN ? = 'completed' THEN datetime('now') ELSE completed_at END,
                updated_at = datetime('now')
            WHERE task_ref = ? AND plan_item_id = ?
            """,
            (
                state,
                next_lane_id,
                next_action_id,
                next_worker_message_id,
                next_heading,
                next_summary,
                dispatch_count,
                state,
                state,
                resolved_task_ref,
                normalized_plan_item_id,
            ),
        )
        row = _row_to_dict(
            conn.execute(
                "SELECT * FROM plan_cursors WHERE task_ref = ? AND plan_item_id = ?",
                (resolved_task_ref, normalized_plan_item_id),
            ).fetchone()
        )
        return _json_response({"ok": True, "cursor": row})


def get_plan_cursor(plan_item_id: str, task_ref: str | None = None) -> str:
    normalized_plan_item_id = _normalize_optional_text(plan_item_id)
    if normalized_plan_item_id is None:
        return _json_response({"ok": False, "error": "plan_item_id is required."})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        row = conn.execute(
            "SELECT * FROM plan_cursors WHERE task_ref = ? AND plan_item_id = ?",
            (resolved_task_ref, normalized_plan_item_id),
        ).fetchone()
        return _json_response({"ok": True, "task_ref": resolved_task_ref, "cursor": _row_to_dict(row)})


def list_plan_cursors(
    task_ref: str | None = None,
    state: str = "all",
    lane_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    valid_states = {"all", "dispatched", "completed", "skipped", "escalated"}
    if state not in valid_states:
        return _json_response({"ok": False, "error": f"Invalid state. Valid: {', '.join(sorted(valid_states))}"})
    limit = max(1, limit)
    offset = max(0, offset)
    normalized_lane_id = _normalize_optional_text(lane_id)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        params: list[object] = [resolved_task_ref]
        where_sql = "task_ref = ?"
        if state != "all":
            where_sql += " AND state = ?"
            params.append(state)
        if normalized_lane_id is not None:
            where_sql += " AND lane_id = ?"
            params.append(normalized_lane_id)
        total = int(conn.execute(f"SELECT COUNT(*) AS count FROM plan_cursors WHERE {where_sql}", tuple(params)).fetchone()["count"])
        rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM plan_cursors WHERE {where_sql} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        ]
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "lane_id": normalized_lane_id,
                "state": state,
                "total_matching": total,
                "returned": len(rows),
                "has_more": offset + len(rows) < total,
                "cursors": rows,
            }
        )


def record_decision(session: str, decision: str, rationale: str | None = None, actor: WriteActor | None = None) -> str:
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        agent, branch, commit_sha, lane_id = _resolve_write_actor(conn, actor)
        cur = conn.execute(
            """
            INSERT INTO decisions (task_ref, lane_id, session, decision, rationale, agent, branch, commit_sha, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (resolved_task_ref, lane_id, session, decision, rationale, agent, branch, commit_sha),
        )
        return _json_response({"ok": True, "decision": _row_to_dict(conn.execute("SELECT * FROM decisions WHERE id = ?", (cur.lastrowid,)).fetchone())})


def update_next_actions(operation: str, action_id: int | None = None, action: str | None = None, priority: int | None = None, status: str | None = None, actor: WriteActor | None = None) -> str:
    valid_operations = {"add", "update", "complete", "skip"}
    if operation not in valid_operations:
        return _json_response({"ok": False, "error": f"Invalid operation. Valid: {', '.join(sorted(valid_operations))}"})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        agent, branch, commit_sha, lane_id = _resolve_write_actor(conn, actor)
        if operation == "add":
            if not action:
                return _json_response({"ok": False, "error": "action is required for add."})
            cur = conn.execute(
                """
                INSERT INTO next_actions (task_ref, lane_id, action, priority, status, agent, branch, commit_sha, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (resolved_task_ref, lane_id, action, priority if priority is not None else 100, agent, branch, commit_sha),
            )
            return _json_response({"ok": True, "operation": operation, "action": _row_to_dict(conn.execute("SELECT * FROM next_actions WHERE id = ?", (cur.lastrowid,)).fetchone())})
        if action_id is None:
            return _json_response({"ok": False, "error": "action_id is required for update/complete/skip."})
        existing = conn.execute("SELECT * FROM next_actions WHERE id = ? AND task_ref = ?", (action_id, resolved_task_ref)).fetchone()
        if existing is None:
            return _json_response({"ok": False, "error": "Action not found for task_ref."})
        if operation == "update":
            if action is None and priority is None and status is None:
                return _json_response({"ok": False, "error": "At least one of action, priority, or status is required for update."})
            use_status = status if status is not None else str(existing["status"])
            if use_status not in {"pending", "done", "skipped"}:
                return _json_response({"ok": False, "error": "Invalid status value."})
            conn.execute("UPDATE next_actions SET action = ?, priority = ?, status = ?, agent = ?, branch = ?, commit_sha = ?, lane_id = COALESCE(lane_id, ?), updated_at = datetime('now') WHERE id = ? AND task_ref = ?", (action if action is not None else str(existing["action"]), priority if priority is not None else int(existing["priority"]), use_status, agent, branch, commit_sha, lane_id, action_id, resolved_task_ref))
        elif operation == "complete":
            conn.execute("UPDATE next_actions SET status = 'done', agent = ?, branch = ?, commit_sha = ?, lane_id = COALESCE(lane_id, ?), updated_at = datetime('now') WHERE id = ? AND task_ref = ?", (agent, branch, commit_sha, lane_id, action_id, resolved_task_ref))
        else:
            conn.execute("UPDATE next_actions SET status = 'skipped', agent = ?, branch = ?, commit_sha = ?, lane_id = COALESCE(lane_id, ?), updated_at = datetime('now') WHERE id = ? AND task_ref = ?", (agent, branch, commit_sha, lane_id, action_id, resolved_task_ref))
        return _json_response({"ok": True, "operation": operation, "action": _row_to_dict(conn.execute("SELECT * FROM next_actions WHERE id = ?", (action_id,)).fetchone())})


def list_next_actions(task_ref: str | None = None, lane_id: str | None = None, status: str = "all", limit: int = 100, offset: int = 0) -> str:
    valid_statuses = {"all", "pending", "done", "skipped"}
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    limit = max(1, limit)
    offset = max(0, offset)
    normalized_lane_id = _normalize_optional_text(lane_id)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        params: list[object] = [resolved_task_ref]
        where_sql = "task_ref = ?"
        if normalized_lane_id is not None:
            where_sql += " AND lane_id = ?"
            params.append(normalized_lane_id)
        if status != "all":
            where_sql += " AND status = ?"
            params.append(status)
        total = int(conn.execute(f"SELECT COUNT(*) AS count FROM next_actions WHERE {where_sql}", tuple(params)).fetchone()["count"])
        rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM next_actions WHERE {where_sql} ORDER BY priority ASC, updated_at DESC, id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        ]
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "lane_id": normalized_lane_id,
                "status": status,
                "total_matching": total,
                "returned": len(rows),
                "has_more": offset + len(rows) < total,
                "actions": rows,
            }
        )


def record_test_result(session: str, command: str, passed: bool, result: str | None = None, exit_code: int | None = None, actor: WriteActor | None = None) -> str:
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        agent, branch, commit_sha, lane_id = _resolve_write_actor(conn, actor)
        cur = conn.execute(
            """
            INSERT INTO verified_tests (task_ref, lane_id, command, passed, exit_code, result, session, agent, branch, commit_sha, verified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (resolved_task_ref, lane_id, command, 1 if passed else 0, exit_code, result, session, agent, branch, commit_sha),
        )
        return _json_response({"ok": True, "test": _row_to_dict(conn.execute("SELECT * FROM verified_tests WHERE id = ?", (cur.lastrowid,)).fetchone())})


def report_blocker(operation: str, description: str | None = None, blocker_id: int | None = None, actor: WriteActor | None = None) -> str:
    valid_operations = {"add", "resolve", "reopen"}
    if operation not in valid_operations:
        return _json_response({"ok": False, "error": f"Invalid operation. Valid: {', '.join(sorted(valid_operations))}"})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        agent, branch, commit_sha, lane_id = _resolve_write_actor(conn, actor)
        if operation == "add":
            if not description:
                return _json_response({"ok": False, "error": "description is required for add."})
            cur = conn.execute(
                """
                INSERT INTO blockers (task_ref, lane_id, description, status, agent, branch, commit_sha, resolved_at, created_at)
                VALUES (?, ?, ?, 'open', ?, ?, ?, NULL, datetime('now'))
                """,
                (resolved_task_ref, lane_id, description, agent, branch, commit_sha),
            )
            return _json_response({"ok": True, "operation": operation, "blocker": _row_to_dict(conn.execute("SELECT * FROM blockers WHERE id = ?", (cur.lastrowid,)).fetchone())})
        if blocker_id is None:
            return _json_response({"ok": False, "error": "blocker_id is required for resolve/reopen."})
        existing = conn.execute("SELECT * FROM blockers WHERE id = ? AND task_ref = ?", (blocker_id, resolved_task_ref)).fetchone()
        if existing is None:
            return _json_response({"ok": False, "error": "Blocker not found for task_ref."})
        if operation == "resolve":
            conn.execute("UPDATE blockers SET status = 'resolved', resolved_at = datetime('now'), agent = ?, branch = ?, commit_sha = ?, lane_id = COALESCE(lane_id, ?) WHERE id = ? AND task_ref = ?", (agent, branch, commit_sha, lane_id, blocker_id, resolved_task_ref))
        else:
            conn.execute("UPDATE blockers SET status = 'open', resolved_at = NULL, agent = ?, branch = ?, commit_sha = ?, lane_id = COALESCE(lane_id, ?) WHERE id = ? AND task_ref = ?", (agent, branch, commit_sha, lane_id, blocker_id, resolved_task_ref))
        return _json_response({"ok": True, "operation": operation, "blocker": _row_to_dict(conn.execute("SELECT * FROM blockers WHERE id = ?", (blocker_id,)).fetchone())})


def record_review_finding(session: str, finding_id: str, severity: str, file_path: str, description: str, details: ReviewFindingDetails | None = None, actor: WriteActor | None = None, task_ref: str | None = None) -> str:
    if severity not in REVIEW_FINDING_SEVERITIES:
        return _json_response({"ok": False, "error": f"Invalid severity. Valid: {', '.join(sorted(REVIEW_FINDING_SEVERITIES))}"})
    line_start, line_end, fix = _parse_review_finding_details(details)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        agent, branch, commit_sha, lane_id = _resolve_write_actor(conn, actor)
        existing = conn.execute("SELECT status FROM review_findings WHERE task_ref = ? AND finding_id = ?", (resolved_task_ref, finding_id)).fetchone()
        conn.execute(
            """
            INSERT INTO review_findings (
                task_ref, lane_id, finding_id, severity, file_path, line_start, line_end, description, fix, status, session, agent, branch, commit_sha, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(task_ref, finding_id) DO UPDATE SET
                severity = excluded.severity,
                file_path = excluded.file_path,
                line_start = excluded.line_start,
                line_end = excluded.line_end,
                description = excluded.description,
                fix = excluded.fix,
                status = 'open',
                resolved_at = NULL,
                resolution_notes = NULL,
                reopen_count = CASE WHEN review_findings.status <> 'open' THEN COALESCE(review_findings.reopen_count, 0) + 1 ELSE COALESCE(review_findings.reopen_count, 0) END,
                last_reopen_reason = CASE WHEN review_findings.status <> 'open' THEN 'Re-recorded via review-record.' ELSE review_findings.last_reopen_reason END,
                last_reopened_at = CASE WHEN review_findings.status <> 'open' THEN datetime('now') ELSE review_findings.last_reopened_at END,
                updated_at = datetime('now'),
                session = excluded.session,
                lane_id = COALESCE(review_findings.lane_id, excluded.lane_id),
                agent = COALESCE(review_findings.agent, excluded.agent),
                branch = COALESCE(review_findings.branch, excluded.branch),
                commit_sha = COALESCE(review_findings.commit_sha, excluded.commit_sha)
            """,
            (resolved_task_ref, lane_id, finding_id, severity, file_path, line_start, line_end, description, fix, session, agent, branch, commit_sha),
        )
        row = conn.execute("SELECT * FROM review_findings WHERE task_ref = ? AND finding_id = ?", (resolved_task_ref, finding_id)).fetchone()
        _write_current_task_md_for_task(conn, resolved_task_ref)
        payload = {"ok": True, "finding": _row_to_dict(row)}
        if existing is not None and str(existing["status"]) != "open":
            payload["reopened"] = True
            payload["reopen_reason"] = "Re-recorded via review-record."
        return _json_response(payload)


def update_review_finding(status: str, finding_id: str | None = None, finding_db_id: int | None = None, resolution_notes: str | None = None, reopen_reason: str | None = None, session: str | None = None, actor: WriteActor | None = None) -> str:
    if (finding_id is None and finding_db_id is None) or (finding_id is not None and finding_db_id is not None):
        return _json_response({"ok": False, "error": "Pass exactly one of finding_id (preferred) or finding_db_id."})
    if status not in REVIEW_FINDING_STATUSES:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(REVIEW_FINDING_STATUSES))}"})
    normalized_finding_id = finding_id.strip() if isinstance(finding_id, str) else None
    if normalized_finding_id == "":
        return _json_response({"ok": False, "error": "finding_id must not be empty."})
    normalized_resolution_notes = _normalize_optional_text(resolution_notes)
    normalized_reopen_reason = _normalize_optional_text(reopen_reason)
    if status in {"wontfix", "deferred"} and normalized_resolution_notes is None:
        return _json_response({"ok": False, "error": f"resolution_notes is required when status is '{status}'."})
    if status == "open" and normalized_resolution_notes is not None:
        return _json_response({"ok": False, "error": "resolution_notes is not supported for status='open'. Use reopen_reason when reopening."})
    if normalized_resolution_notes is not None and len(normalized_resolution_notes) > MAX_RESOLUTION_NOTES_LENGTH:
        return _json_response({"ok": False, "error": f"resolution_notes must be <= {MAX_RESOLUTION_NOTES_LENGTH} characters."})
    if normalized_reopen_reason is not None and len(normalized_reopen_reason) > MAX_REOPEN_REASON_LENGTH:
        return _json_response({"ok": False, "error": f"reopen_reason must be <= {MAX_REOPEN_REASON_LENGTH} characters."})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        agent, branch, commit_sha, lane_id = _resolve_write_actor(conn, actor)
        existing = conn.execute(
            "SELECT * FROM review_findings WHERE finding_id = ? AND task_ref = ?" if normalized_finding_id is not None else "SELECT * FROM review_findings WHERE id = ? AND task_ref = ?",
            (normalized_finding_id, resolved_task_ref) if normalized_finding_id is not None else (finding_db_id, resolved_task_ref),
        ).fetchone()
        if existing is None:
            return _json_response({"ok": False, "error": "Finding not found for active task."})
        existing_status = str(existing["status"])
        is_reopen_transition = existing_status != "open" and status == "open"
        if is_reopen_transition and normalized_reopen_reason is None:
            return _json_response({"ok": False, "error": "reopen_reason is required when reopening a finding."})
        if not is_reopen_transition and normalized_reopen_reason is not None:
            return _json_response({"ok": False, "error": "reopen_reason is only valid when transitioning a finding back to open."})
        target_db_id = int(existing["id"])
        reopen_transition_int = 1 if is_reopen_transition else 0
        conn.execute(
            """
            UPDATE review_findings
            SET status = ?, resolved_at = CASE WHEN ? IN ('fixed', 'wontfix') THEN datetime('now') ELSE NULL END,
                agent = COALESCE(agent, ?), branch = COALESCE(branch, ?), commit_sha = COALESCE(commit_sha, ?),
                lane_id = COALESCE(lane_id, ?),
                session = COALESCE(?, session),
                resolution_notes = CASE WHEN ? = 'open' THEN NULL WHEN ? IS NOT NULL THEN ? WHEN ? = 'fixed' THEN NULL ELSE resolution_notes END,
                reopen_count = CASE WHEN ? = 1 THEN COALESCE(reopen_count, 0) + 1 ELSE COALESCE(reopen_count, 0) END,
                last_reopen_reason = CASE WHEN ? = 1 THEN ? ELSE last_reopen_reason END,
                last_reopened_at = CASE WHEN ? = 1 THEN datetime('now') ELSE last_reopened_at END,
                updated_at = datetime('now')
            WHERE id = ? AND task_ref = ?
            """,
            (status, status, agent, branch, commit_sha, lane_id, session, status, normalized_resolution_notes, normalized_resolution_notes, status, reopen_transition_int, reopen_transition_int, normalized_reopen_reason, reopen_transition_int, target_db_id, resolved_task_ref),
        )
        row = conn.execute("SELECT * FROM review_findings WHERE id = ?", (target_db_id,)).fetchone()
        _write_current_task_md_for_task(conn, resolved_task_ref)
        payload = {"ok": True, "finding": _row_to_dict(row)}
        if is_reopen_transition:
            payload["reopened"] = True
            payload["reopen_reason"] = normalized_reopen_reason
        return _json_response(payload)


def reopen_review_finding(reason: str, finding_id: str | None = None, finding_db_id: int | None = None, session: str | None = None, actor: WriteActor | None = None) -> str:
    return update_review_finding(status="open", finding_id=finding_id, finding_db_id=finding_db_id, reopen_reason=reason, session=session, actor=actor)


def list_review_findings(task_ref: str | None = None, status: str = "all", severity: str = "all", limit: int = 100, offset: int = 0) -> str:
    valid_statuses = {"all", *REVIEW_FINDING_STATUSES}
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    valid_severities = {"all", *REVIEW_FINDING_SEVERITIES}
    if severity not in valid_severities:
        return _json_response({"ok": False, "error": f"Invalid severity. Valid: {', '.join(sorted(valid_severities))}"})
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        where_parts = ["task_ref = ?"]
        params: list[object] = [resolved_task_ref]
        if status != "all":
            where_parts.append("status = ?")
            params.append(status)
        if severity != "all":
            where_parts.append("severity = ?")
            params.append(severity)
        where_sql = " AND ".join(where_parts)
        total_row = conn.execute(f"SELECT COUNT(*) AS count FROM review_findings WHERE {where_sql}", tuple(params)).fetchone()
        findings = [dict(row) for row in conn.execute(f"SELECT * FROM review_findings WHERE {where_sql} ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'deferred' THEN 1 WHEN 'fixed' THEN 2 WHEN 'wontfix' THEN 3 END, CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, COALESCE(updated_at, created_at) DESC, id DESC LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()]
        status_counts = {key: 0 for key in sorted(REVIEW_FINDING_STATUSES)}
        for row in conn.execute("SELECT status, COUNT(*) AS count FROM review_findings WHERE task_ref = ? GROUP BY status", (resolved_task_ref,)).fetchall():
            status_counts[str(row["status"])] = int(row["count"])
        severity_counts = {key: 0 for key in sorted(REVIEW_FINDING_SEVERITIES)}
        for row in conn.execute("SELECT severity, COUNT(*) AS count FROM review_findings WHERE task_ref = ? GROUP BY severity", (resolved_task_ref,)).fetchall():
            severity_counts[str(row["severity"])] = int(row["count"])
    total = int(total_row["count"]) if total_row else 0
    return _json_response({"ok": True, "task_ref": resolved_task_ref, "filters": {"status": status, "severity": severity, "limit": limit, "offset": offset}, "total_matching": total, "returned": len(findings), "has_more": (offset + len(findings)) < total, "counts": {"status": status_counts, "severity": severity_counts}, "findings": findings})


def get_review_finding(finding_db_id: int | None = None, finding_id: str | None = None, task_ref: str | None = None) -> str:
    if finding_db_id is None and finding_id is None:
        return _json_response({"ok": False, "error": "Provide finding_db_id (int) or finding_id (string)."})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        row = conn.execute("SELECT * FROM review_findings WHERE id = ? AND task_ref = ?" if finding_db_id is not None else "SELECT * FROM review_findings WHERE finding_id = ? AND task_ref = ?", (finding_db_id, resolved_task_ref) if finding_db_id is not None else (finding_id, resolved_task_ref)).fetchone()
        if row is None:
            return _json_response({"ok": False, "error": "Finding not found for task."})
        return _json_response({"ok": True, "task_ref": resolved_task_ref, "finding": _row_to_dict(row)})


def get_review_findings_summary(task_ref: str | None = None, top_n_open: int = 5, top_n_recent_updates: int = 3) -> str:
    top_n_open = max(1, top_n_open)
    top_n_recent_updates = max(1, top_n_recent_updates)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        total_row = conn.execute("SELECT COUNT(*) AS total FROM review_findings WHERE task_ref = ?", (resolved_task_ref,)).fetchone()
        status_counts = {key: 0 for key in sorted(REVIEW_FINDING_STATUSES)}
        for row in conn.execute("SELECT status, COUNT(*) AS count FROM review_findings WHERE task_ref = ? GROUP BY status", (resolved_task_ref,)).fetchall():
            status_counts[str(row["status"])] = int(row["count"])
        severity_counts = {key: 0 for key in sorted(REVIEW_FINDING_SEVERITIES)}
        for row in conn.execute("SELECT severity, COUNT(*) AS count FROM review_findings WHERE task_ref = ? GROUP BY severity", (resolved_task_ref,)).fetchall():
            severity_counts[str(row["severity"])] = int(row["count"])
        open_findings = [dict(row) for row in conn.execute("SELECT * FROM review_findings WHERE task_ref = ? AND status = 'open' ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, COALESCE(updated_at, created_at) DESC, id DESC LIMIT ?", (resolved_task_ref, top_n_open)).fetchall()]
        recent_updates = [dict(row) for row in conn.execute("SELECT * FROM review_findings WHERE task_ref = ? ORDER BY COALESCE(updated_at, resolved_at, created_at) DESC, id DESC LIMIT ?", (resolved_task_ref, top_n_recent_updates)).fetchall()]
    return _json_response({"ok": True, "task_ref": resolved_task_ref, "counts": {"total": int(total_row["total"]) if total_row else 0, "status": status_counts, "severity": severity_counts}, "open_top": open_findings, "recent_updates": recent_updates, "limits": {"top_n_open": top_n_open, "top_n_recent_updates": top_n_recent_updates}})


def _collect_review_findings_integrity(conn: sqlite3.Connection, task_ref: str, *, apply: bool = False) -> dict:
    duplicate_rows = conn.execute(
        """
        SELECT finding_id, COUNT(*) AS count
        FROM review_findings
        WHERE task_ref = ?
        GROUP BY finding_id
        HAVING COUNT(*) > 1
        ORDER BY count DESC, finding_id ASC
        """,
        (task_ref,),
    ).fetchall()
    duplicates = [{"finding_id": row["finding_id"], "count": int(row["count"])} for row in duplicate_rows]
    deduped_rows_removed = 0
    if apply and duplicates:
        deduped_rows_removed = _dedupe_review_findings(conn, task_ref)
        duplicate_rows = conn.execute(
            """
            SELECT finding_id, COUNT(*) AS count
            FROM review_findings
            WHERE task_ref = ?
            GROUP BY finding_id
            HAVING COUNT(*) > 1
            ORDER BY count DESC, finding_id ASC
            """,
            (task_ref,),
        ).fetchall()
        duplicates = [{"finding_id": row["finding_id"], "count": int(row["count"])} for row in duplicate_rows]
    open_count = int(conn.execute("SELECT COUNT(*) AS count FROM review_findings WHERE task_ref = ? AND status = 'open'", (task_ref,)).fetchone()["count"])
    active_row = conn.execute("SELECT task_ref, status FROM handoff_state WHERE id = 1").fetchone()
    active_status = str(active_row["status"]) if active_row is not None and str(active_row["task_ref"]) == task_ref else None
    done_with_open_findings = bool(active_status == "done" and open_count > 0)
    stale_open_findings = []
    for row in conn.execute("SELECT id, finding_id, file_path, created_at, updated_at FROM review_findings WHERE task_ref = ? AND status = 'open' ORDER BY COALESCE(updated_at, created_at) DESC, id DESC", (task_ref,)).fetchall():
        raw_file_path = str(row["file_path"])
        path = Path(raw_file_path)
        if not path.is_absolute():
            path = _workspace_root() / raw_file_path
        if not path.exists():
            continue
        activity_dt = _parse_sqlite_datetime(row["updated_at"]) or _parse_sqlite_datetime(row["created_at"])
        if activity_dt is None:
            continue
        file_modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if file_modified_at > activity_dt:
            stale_open_findings.append({"id": int(row["id"]), "finding_id": str(row["finding_id"]), "file_path": raw_file_path, "created_at": str(row["created_at"]), "updated_at": str(row["updated_at"]) if row["updated_at"] is not None else None, "file_modified_at": file_modified_at.strftime("%Y-%m-%d %H:%M:%S")})
    missing_provenance = [{"id": int(row["id"]), "finding_id": str(row["finding_id"]), "agent": row["agent"], "branch": row["branch"], "commit_sha": row["commit_sha"]} for row in conn.execute("SELECT id, finding_id, agent, branch, commit_sha FROM review_findings WHERE task_ref = ? AND (agent IS NULL OR TRIM(agent) = '' OR branch IS NULL OR TRIM(branch) = '') ORDER BY id DESC", (task_ref,)).fetchall()]
    reopen_metadata = [{"id": int(row["id"]), "finding_id": str(row["finding_id"]), "reopen_count": int(row["reopen_count"]), "last_reopen_reason": row["last_reopen_reason"], "last_reopened_at": row["last_reopened_at"]} for row in conn.execute("SELECT id, finding_id, reopen_count, last_reopen_reason, last_reopened_at FROM review_findings WHERE task_ref = ? AND COALESCE(reopen_count, 0) > 0 AND (last_reopen_reason IS NULL OR TRIM(last_reopen_reason) = '' OR last_reopened_at IS NULL OR TRIM(last_reopened_at) = '') ORDER BY id DESC", (task_ref,)).fetchall()]
    healthy = len(duplicates) == 0 and not done_with_open_findings and len(stale_open_findings) == 0 and len(missing_provenance) == 0 and len(reopen_metadata) == 0
    return {"healthy": healthy, "checks": {"duplicates": {"count": len(duplicates), "items": duplicates, "deduped_rows_removed": deduped_rows_removed}, "done_with_open_findings": {"active_status": active_status, "open_count": open_count, "is_violation": done_with_open_findings}, "stale_open_findings": {"count": len(stale_open_findings), "items": stale_open_findings}, "missing_provenance": {"count": len(missing_provenance), "items": missing_provenance}, "reopen_metadata": {"count": len(reopen_metadata), "items": reopen_metadata}}}


def reconcile_review_findings(task_ref: str | None = None, apply: bool = False) -> str:
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        report = _collect_review_findings_integrity(conn, resolved_task_ref, apply=apply)
        if apply and int(report["checks"]["duplicates"]["deduped_rows_removed"]) > 0 and report["checks"]["done_with_open_findings"]["active_status"] is not None:
            _write_current_task_md_for_task(conn, resolved_task_ref)
    return _json_response({"ok": True, "task_ref": resolved_task_ref, "healthy": report["healthy"], "checks": report["checks"]})


def _collect_task_provenance_integrity(conn: sqlite3.Connection, task_ref: str) -> dict:
    table_checks: dict[str, dict[str, object]] = {}
    total_issues = 0
    for table_name in ("decisions", "blockers", "next_actions", "verified_tests", "review_findings", "worker_reports", "lane_messages"):
        rows = conn.execute(f"SELECT id AS row_id, agent, branch, commit_sha FROM {table_name} WHERE task_ref = ? AND (agent IS NULL OR TRIM(agent) = '' OR branch IS NULL OR TRIM(branch) = '') ORDER BY id DESC", (task_ref,)).fetchall()
        items = [{"row_id": int(row["row_id"]), "agent": row["agent"], "branch": row["branch"], "commit_sha": row["commit_sha"]} for row in rows]
        table_checks[table_name] = {"count": len(items), "items": items}
        total_issues += len(items)
    active_row = conn.execute("SELECT updated_by, updated_branch, updated_commit_sha FROM handoff_state WHERE id = 1 AND task_ref = ?", (task_ref,)).fetchone()
    active_missing = None
    if active_row is not None:
        missing = _normalize_optional_text(active_row["updated_by"]) is None or _normalize_optional_text(active_row["updated_branch"]) is None
        active_missing = {"count": 1 if missing else 0, "is_violation": missing, "updated_by": active_row["updated_by"], "updated_branch": active_row["updated_branch"], "updated_commit_sha": active_row["updated_commit_sha"]}
        total_issues += 1 if missing else 0
    return {"healthy": total_issues == 0, "total_issues": total_issues, "tables": table_checks, "active_state": active_missing}


def handoff_close_check(task_ref: str | None = None, allow_no_active_task: bool = False, enforce: bool = False) -> str:
    with _get_db_connection() as conn:
        active_row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
        if task_ref is None:
            if active_row is None:
                if allow_no_active_task:
                    return _json_response({"ok": True, "ready_to_close": True, "skipped": True, "reason": "No active handoff task found."})
                return _json_response({"ok": False, "error": "No active handoff task found."})
            resolved_task_ref = str(active_row["task_ref"])
        else:
            resolved_task_ref = task_ref
        snapshot = _collect_task_snapshot(conn, resolved_task_ref)
        active = snapshot["active"]
        active_task_matches = active is not None
        active_status = str(active["status"]) if active is not None else None
        open_blockers = [row for row in snapshot["blockers"] if row.get("status") == "open"]
        pending_actions = [row for row in snapshot["next_actions"] if row.get("status") == "pending"]
        open_findings = [row for row in snapshot["review_findings"] if row.get("status") == "open"]
        review_integrity = _collect_review_findings_integrity(conn, resolved_task_ref, apply=False)
        provenance_integrity = _collect_task_provenance_integrity(conn, resolved_task_ref)
        expected_markdown = _render_current_task_md(_build_current_task_state_from_snapshot(snapshot))
        current_task_exists = _current_task_path().exists()
        current_task_in_sync = bool(current_task_exists and active_task_matches and _current_task_path().read_text() == expected_markdown)
    failures: list[str] = []
    if not active_task_matches:
        failures.append("Target task is not the active handoff task.")
    if active_status != "done":
        failures.append("Active task status must be 'done'.")
    if open_blockers:
        failures.append("Open blockers must be resolved before close.")
    if pending_actions:
        failures.append("Pending next actions must be done or skipped before close.")
    if open_findings:
        failures.append("Open review findings must be fixed, deferred, or wontfix before close.")
    if not review_integrity["healthy"]:
        failures.append("Review finding integrity checks are not healthy.")
    if not provenance_integrity["healthy"]:
        failures.append("Write provenance integrity checks failed (missing agent/branch metadata).")
    if not current_task_in_sync:
        failures.append("CURRENT_TASK.md is out of sync with handoff DB state.")
    ready_to_close = len(failures) == 0
    payload = {
        "ok": not (enforce and not ready_to_close),
        "task_ref": resolved_task_ref,
        "ready_to_close": ready_to_close,
        "checks": {
            "active_task": {"matches_target": active_task_matches, "status": active_status, "is_done": active_status == "done"},
            "open_blockers": {"count": len(open_blockers), "is_violation": len(open_blockers) > 0, "items": open_blockers},
            "pending_actions": {"count": len(pending_actions), "is_violation": len(pending_actions) > 0, "items": pending_actions},
            "open_review_findings": {"count": len(open_findings), "is_violation": len(open_findings) > 0, "items": open_findings},
            "review_integrity": review_integrity,
            "write_provenance": provenance_integrity,
            "current_task_sync": {"path": str(_current_task_path()), "exists": current_task_exists, "is_in_sync": current_task_in_sync},
        },
        "failures": failures,
    }
    if enforce and not ready_to_close:
        payload["error"] = "Handoff close checks failed."
    return _json_response(payload)

def export_handoff_state(task_ref: str | None = None, output_path: str | None = None, include_markdown: bool = True) -> str:
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        snapshot = _collect_task_snapshot(conn, resolved_task_ref)
    payload = {"export_version": 1, "task_ref": resolved_task_ref, "exported_at": _utcnow_iso(), "snapshot": snapshot}
    if include_markdown:
        payload["current_task_markdown"] = _render_current_task_md(_build_current_task_state_from_snapshot(snapshot))
    destination = _resolve_output_path(output_path, resolved_task_ref)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return _json_response({"ok": True, "task_ref": resolved_task_ref, "path": str(destination), "counts": {"blockers": len(snapshot["blockers"]), "next_actions": len(snapshot["next_actions"]), "decisions": len(snapshot["decisions"]), "verified_tests": len(snapshot["verified_tests"]), "review_findings": len(snapshot["review_findings"]), "worktree_lanes": len(snapshot["worktree_lanes"]), "worker_reports": len(snapshot["worker_reports"]), "lane_messages": len(snapshot["lane_messages"]), "plan_cursors": len(snapshot.get("plan_cursors", []))}})


def _set_import_active_state(conn: sqlite3.Connection, task_ref: str, active: dict) -> None:
    git_branch, git_commit = _detect_git_write_context()
    updated_by = _normalize_optional_text(active.get("updated_by")) or _normalize_optional_text(os.environ.get("AGENT_HANDOFF_DEFAULT_AGENT")) or "codex"
    updated_branch = _normalize_optional_text(active.get("updated_branch")) or git_branch or "unknown-branch"
    updated_commit_sha = _normalize_optional_text(active.get("updated_commit_sha")) or git_commit
    current = conn.execute("SELECT revision FROM handoff_state WHERE id = 1").fetchone()
    if current is None:
        conn.execute(
            """
            INSERT INTO handoff_state (
                id, task_ref, objective, status, revision, updated_at, updated_by, updated_branch, updated_commit_sha
            ) VALUES (1, ?, ?, ?, 0, datetime('now'), ?, ?, ?)
            """,
            (task_ref, active.get("objective", ""), active.get("status", "in_progress"), updated_by, updated_branch, updated_commit_sha),
        )
        return
    conn.execute("UPDATE handoff_state SET task_ref = ?, objective = ?, status = ?, revision = revision + 1, updated_at = datetime('now'), updated_by = ?, updated_branch = ?, updated_commit_sha = ? WHERE id = 1", (task_ref, active.get("objective", ""), active.get("status", "in_progress"), updated_by, updated_branch, updated_commit_sha))


def _import_snapshot(conn: sqlite3.Connection, task_ref: str, snapshot: dict, mode: str, set_active: bool) -> dict[str, int]:
    blockers = snapshot.get("blockers", [])
    actions = snapshot.get("next_actions", [])
    decisions = snapshot.get("decisions", [])
    tests = snapshot.get("verified_tests", [])
    findings = snapshot.get("review_findings", [])
    lanes = snapshot.get("worktree_lanes", [])
    reports = snapshot.get("worker_reports", [])
    messages = snapshot.get("lane_messages", [])
    plan_cursors = snapshot.get("plan_cursors", [])
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
        for table in ("blockers", "next_actions", "decisions", "verified_tests", "review_findings", "worktree_lanes", "worker_reports", "lane_messages", "plan_cursors"):
            conn.execute(f"DELETE FROM {table} WHERE task_ref = ?", (task_ref,))
    for row in blockers:
        agent, branch, commit_sha = _resolve_import_row_actor(row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit)
        conn.execute("INSERT INTO blockers (task_ref, lane_id, description, status, agent, branch, commit_sha, resolved_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_ref, _resolve_import_lane_id(row), row.get("description", ""), row.get("status", "open"), agent, branch, commit_sha, row.get("resolved_at"), row.get("created_at") or now))
    for row in actions:
        agent, branch, commit_sha = _resolve_import_row_actor(row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit)
        conn.execute("INSERT INTO next_actions (task_ref, lane_id, action, priority, status, agent, branch, commit_sha, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_ref, _resolve_import_lane_id(row), row.get("action", ""), int(row.get("priority", 100)), row.get("status", "pending"), agent, branch, commit_sha, row.get("created_at") or now, row.get("updated_at") or row.get("created_at") or now))
    for row in decisions:
        agent, branch, commit_sha = _resolve_import_row_actor(row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit)
        conn.execute("INSERT INTO decisions (task_ref, lane_id, session, decision, rationale, agent, branch, commit_sha, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_ref, _resolve_import_lane_id(row), row.get("session", "import"), row.get("decision", ""), row.get("rationale"), agent, branch, commit_sha, row.get("created_at") or now))
    for row in tests:
        agent, branch, commit_sha = _resolve_import_row_actor(row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit)
        conn.execute("INSERT INTO verified_tests (task_ref, lane_id, command, passed, exit_code, result, session, agent, branch, commit_sha, verified_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_ref, _resolve_import_lane_id(row), row.get("command", ""), 1 if row.get("passed") else 0, row.get("exit_code"), row.get("result"), row.get("session", "import"), agent, branch, commit_sha, row.get("verified_at") or now))
    for row in findings:
        agent, branch, commit_sha = _resolve_import_row_actor(row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit)
        conn.execute("INSERT INTO review_findings (task_ref, lane_id, finding_id, severity, file_path, line_start, line_end, description, fix, status, session, agent, branch, commit_sha, resolution_notes, reopen_count, last_reopen_reason, last_reopened_at, resolved_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_ref, _resolve_import_lane_id(row), row.get("finding_id", ""), row.get("severity", "low"), row.get("file_path", ""), row.get("line_start"), row.get("line_end"), row.get("description", ""), row.get("fix"), row.get("status", "open"), row.get("session", "import"), agent, branch, commit_sha, row.get("resolution_notes"), int(row.get("reopen_count") or 0), row.get("last_reopen_reason"), row.get("last_reopened_at"), row.get("resolved_at"), row.get("created_at") or now, row.get("updated_at") or row.get("resolved_at") or row.get("created_at") or now))
    for row in lanes:
        conn.execute("INSERT INTO worktree_lanes (task_ref, lane_id, title, objective, worktree_path, branch, owner_agent, status, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_ref, row.get("lane_id", ""), row.get("title"), row.get("objective"), row.get("worktree_path", ""), row.get("branch", ""), row.get("owner_agent"), row.get("status", "planned"), row.get("notes"), row.get("created_at") or now, row.get("updated_at") or row.get("created_at") or now))
    for row in reports:
        agent, branch, commit_sha = _resolve_import_row_actor(row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit)
        conn.execute("INSERT INTO worker_reports (task_ref, lane_id, session, summary, changed_files_json, test_commands_json, blockers_json, merge_ready, status, agent, branch, commit_sha, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_ref, row.get("lane_id", ""), row.get("session", "import"), row.get("summary", ""), row.get("changed_files_json") or json.dumps(row.get("changed_files", [])), row.get("test_commands_json") or json.dumps(row.get("test_commands", [])), row.get("blockers_json") or json.dumps(row.get("blockers", [])), 1 if row.get("merge_ready") else 0, row.get("status", "submitted"), agent, branch, commit_sha, row.get("created_at") or now))
    for row in messages:
        agent, branch, commit_sha = _resolve_import_row_actor(row, fallback_agent=fallback_agent, fallback_branch=fallback_branch, fallback_commit=fallback_commit)
        conn.execute("INSERT INTO lane_messages (task_ref, lane_id, session, direction, subject, message, status, agent, branch, commit_sha, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_ref, row.get("lane_id", ""), row.get("session", "import"), row.get("direction", "worker_to_orchestrator"), row.get("subject"), row.get("message", ""), row.get("status", "open"), agent, branch, commit_sha, row.get("created_at") or now, row.get("updated_at") or row.get("created_at") or now))
    for row in plan_cursors:
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
    if set_active and isinstance(active, dict):
        _set_import_active_state(conn, task_ref, active)
    return {"blockers": len(blockers), "next_actions": len(actions), "decisions": len(decisions), "verified_tests": len(tests), "review_findings": len(findings), "worktree_lanes": len(lanes), "worker_reports": len(reports), "lane_messages": len(messages), "plan_cursors": len(plan_cursors)}


def import_handoff_state(input_path: str, mode: str = "merge", set_active: bool = False, allow_destructive_clear: bool = False) -> str:
    if mode not in {"merge", "replace_task"}:
        return _json_response({"ok": False, "error": "Invalid mode. Valid: merge, replace_task."})
    source = Path(input_path)
    if not source.is_absolute():
        source = _workspace_root() / source
    if not source.exists():
        return _json_response({"ok": False, "error": f"Input file not found: {source}"})
    payload = json.loads(source.read_text())
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        return _json_response({"ok": False, "error": "Invalid import payload: snapshot must be an object."})
    task_ref = payload.get("task_ref") or snapshot.get("task_ref")
    if not task_ref:
        return _json_response({"ok": False, "error": "Missing task_ref in import payload."})
    required_sections = ("blockers", "next_actions", "decisions", "verified_tests", "review_findings", "worktree_lanes", "worker_reports", "lane_messages")
    if mode == "replace_task":
        missing_sections = [key for key in required_sections if key not in snapshot]
        if missing_sections:
            return _json_response({"ok": False, "error": f"Invalid replace_task payload: missing required snapshot sections {', '.join(missing_sections)}."})
    for key in (*required_sections, "plan_cursors"):
        items = snapshot.get(key, [])
        if not isinstance(items, list):
            return _json_response({"ok": False, "error": f"Invalid import payload: snapshot.{key} must be an array."})
        for item in items:
            if not isinstance(item, dict):
                return _json_response({"ok": False, "error": f"Invalid import payload: items in snapshot.{key} must be objects."})
    if "active" in snapshot and snapshot["active"] is not None and not isinstance(snapshot["active"], dict):
        return _json_response({"ok": False, "error": "Invalid import payload: snapshot.active must be an object."})
    with _get_db_connection() as conn:
        if mode == "replace_task" and not allow_destructive_clear:
            existing_counts = _count_task_rows(conn, task_ref)
            incoming_counts = {key: len(snapshot.get(key, [])) for key in required_sections}
            potentially_cleared = [section for section, existing_count in existing_counts.items() if existing_count > 0 and incoming_counts.get(section, 0) == 0]
            if potentially_cleared:
                return _json_response({"ok": False, "error": f"replace_task would clear existing handoff rows in sections: {', '.join(potentially_cleared)}. Re-run with allow_destructive_clear=true to confirm.", "existing_counts": existing_counts, "incoming_counts": incoming_counts})
        counts = _import_snapshot(conn, task_ref=task_ref, snapshot=snapshot, mode=mode, set_active=set_active)
    return _json_response({"ok": True, "task_ref": task_ref, "mode": mode, "set_active": set_active, "allow_destructive_clear": allow_destructive_clear, "counts": counts})


def archive_task_state(task_ref: str | None = None, notes: str | None = None, archive_by: str | None = None, archive_branch: str | None = None, archive_commit_sha: str | None = None, clear_active_if_matches: bool = True, prune_working_rows: bool = False, allow_destructive_clear: bool = False) -> str:
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        snapshot = _collect_task_snapshot(conn, resolved_task_ref)
        if prune_working_rows and not allow_destructive_clear:
            working_counts = _count_task_rows(conn, resolved_task_ref)
            non_zero_sections = [section for section, count in working_counts.items() if count > 0]
            if non_zero_sections:
                return _json_response({"ok": False, "error": f"prune_working_rows would clear handoff rows in sections: {', '.join(non_zero_sections)}. Re-run with allow_destructive_clear=true to confirm.", "existing_counts": working_counts})
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
            (resolved_task_ref, archive_by, archive_branch, archive_commit_sha, notes, json.dumps(snapshot, sort_keys=True)),
        )
        active_cleared = False
        if clear_active_if_matches:
            active_row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
            if active_row is not None and str(active_row["task_ref"]) == resolved_task_ref:
                conn.execute("DELETE FROM handoff_state WHERE id = 1")
                active_cleared = True
        pruned = False
        if prune_working_rows:
            for table in ("decisions", "blockers", "next_actions", "verified_tests", "review_findings", "worktree_lanes", "worker_reports", "lane_messages", "plan_cursors"):
                conn.execute(f"DELETE FROM {table} WHERE task_ref = ?", (resolved_task_ref,))
            pruned = True
    return _json_response({"ok": True, "task_ref": resolved_task_ref, "active_cleared": active_cleared, "pruned_working_rows": pruned, "allow_destructive_clear": allow_destructive_clear})


def get_handoff_dashboard(limit: int = 20, include_archived: bool = True) -> str:
    limit = max(1, limit)
    archive_union = "UNION ALL SELECT task_ref, archived_at AS updated_at FROM task_archives" if include_archived else ""
    archived_filter = "" if include_archived else "WHERE archived.archived_at IS NULL"
    with _get_db_connection() as conn:
        rows = conn.execute(
            """
            WITH activity AS (
                SELECT task_ref, created_at AS updated_at FROM decisions
                UNION ALL
                SELECT task_ref, created_at AS updated_at FROM blockers
                UNION ALL
                SELECT task_ref, updated_at FROM next_actions
                UNION ALL
                SELECT task_ref, verified_at AS updated_at FROM verified_tests
                UNION ALL
                SELECT task_ref, COALESCE(updated_at, resolved_at, created_at) AS updated_at FROM review_findings
                UNION ALL
                SELECT task_ref, updated_at FROM worktree_lanes
                UNION ALL
                SELECT task_ref, created_at AS updated_at FROM worker_reports
                UNION ALL
                SELECT task_ref, updated_at FROM lane_messages
                """ + archive_union + """
            ),
            candidates AS (
                SELECT task_ref, MAX(updated_at) AS last_activity
                FROM activity
                GROUP BY task_ref
                ORDER BY MAX(updated_at) DESC
                LIMIT ?
            ),
            blocker_counts AS (
                SELECT task_ref, COUNT(*) AS open_blockers
                FROM blockers
                WHERE status = 'open'
                GROUP BY task_ref
            ),
            action_counts AS (
                SELECT task_ref, COUNT(*) AS pending_actions
                FROM next_actions
                WHERE status = 'pending'
                GROUP BY task_ref
            ),
            finding_counts AS (
                SELECT task_ref, COUNT(*) AS open_findings
                FROM review_findings
                WHERE status = 'open'
                GROUP BY task_ref
            ),
            archived AS (
                SELECT task_ref, archived_at
                FROM task_archives
            )
            SELECT
                candidates.task_ref,
                candidates.last_activity,
                COALESCE(blocker_counts.open_blockers, 0) AS open_blockers,
                COALESCE(action_counts.pending_actions, 0) AS pending_actions,
                COALESCE(finding_counts.open_findings, 0) AS open_findings,
                archived.archived_at
            FROM candidates
            LEFT JOIN blocker_counts ON blocker_counts.task_ref = candidates.task_ref
            LEFT JOIN action_counts ON action_counts.task_ref = candidates.task_ref
            LEFT JOIN finding_counts ON finding_counts.task_ref = candidates.task_ref
            LEFT JOIN archived ON archived.task_ref = candidates.task_ref
            """ + archived_filter + """
            ORDER BY candidates.last_activity DESC
            """,
            (limit,),
        ).fetchall()
        active = conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone()
        return _json_response({"ok": True, "active": _row_to_dict(active), "tasks": [dict(row) for row in rows]})
