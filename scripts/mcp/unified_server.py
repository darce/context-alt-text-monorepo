"""
Unified MCP Server for the Context Alt Text Monorepo.

Provides domain-specific tools that Copilot/Pylance cannot offer natively:
- Cross-boundary endpoint tracing (PHP → Python → TypeScript)
- WordPress hook and REST route discovery
- React component/hook lookup
- Monorepo documentation access (context maps, API contracts, instructions)

Tools that duplicate Copilot built-ins (grep_search, read_file, list_dir,
get_errors, semantic_search) or Pylance MCP (type info, diagnostics) have
been intentionally omitted. Use those native tools instead.

Run from monorepo root:
    python scripts/mcp/unified_server.py

Or via FastMCP CLI:
    fastmcp run scripts/mcp/unified_server.py
"""

import json
import os
import sqlite3
import subprocess
import asyncio
import inspect
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from typing import Protocol, TypedDict, runtime_checkable

from fastmcp import FastMCP

# Ensure common tools (ripgrep, etc.) are in PATH for VS Code spawned processes
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")

# Use full path to ripgrep for reliability
RG_PATH = "/opt/homebrew/bin/rg"

# Subprocess timeout for all commands
SUBPROCESS_TIMEOUT = 10  # seconds


def run_cmd(cmd: list[str], cwd: str | None = None, timeout: int = SUBPROCESS_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a command with stdin=DEVNULL to avoid MCP stdio conflicts.
    
    MCP uses stdio for JSON-RPC, so subprocesses must not inherit stdin.
    """
    work_dir = cwd or str(MONOREPO_ROOT)
    return subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=work_dir,
        timeout=timeout,
    )


def run_rg(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run ripgrep with timeout and proper error handling."""
    return run_cmd([RG_PATH] + args, cwd=cwd)


def _get_db_connection() -> sqlite3.Connection:
    """Open handoff sqlite DB with concurrency-friendly pragmas."""
    TASK_STATE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HANDOFF_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.executescript(HANDOFF_SCHEMA_SQL)
    _apply_handoff_migrations(conn)
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """Convert sqlite row objects to plain dicts for JSON-style responses."""
    if row is None:
        return None
    return dict(row)


def _resolve_task_ref(conn: sqlite3.Connection, task_ref: str | None) -> str:
    """Use provided task ref or fallback to active task from singleton state."""
    if task_ref:
        return task_ref
    row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
    if row is None:
        raise ValueError("No active task in handoff_state. Call set_handoff_state first or pass task_ref explicitly.")
    return str(row["task_ref"])


def _json_response(payload: dict) -> str:
    """Return stable JSON text for consistent cross-client parsing."""
    return json.dumps(payload, indent=2, sort_keys=True)


def _has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    """Check whether a SQLite table contains the given column."""
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row["name"]) == column_name for row in rows)


def _has_index(conn: sqlite3.Connection, table_name: str, index_name: str) -> bool:
    """Check whether a SQLite table contains the given index."""
    rows = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
    return any(str(row["name"]) == index_name for row in rows)


def _first_present(values: list[object]) -> object | None:
    """Return the first non-empty value from a list."""
    for value in values:
        if isinstance(value, str):
            if value.strip() != "":
                return value
            continue
        if value is not None:
            return value
    return None


def _dedupe_review_findings(conn: sqlite3.Connection, task_ref: str | None = None) -> int:
    """Collapse duplicate logical findings per task/finding_id, keeping most-recent state."""
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
        reopen_counts = [
            int(value)
            for value in values_by_column.get("reopen_count", [])
            if isinstance(value, int)
        ]
        merged_reopen_count = max(reopen_counts, default=0)

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
                merged_reopen_count,
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
    """Ensure logical uniqueness for review findings within each task."""
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
    """Parse sqlite datetime strings to UTC-aware datetimes."""
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
    """Project a full snapshot into CURRENT_TASK rendering state."""
    return {
        "active": snapshot["active"],
        "blockers_open": [row for row in snapshot["blockers"] if row.get("status") == "open"],
        "actions_pending": [row for row in snapshot["next_actions"] if row.get("status") == "pending"],
        "decisions_recent": snapshot["decisions"],
        "tests_recent": snapshot["verified_tests"],
        "findings_open": [row for row in snapshot["review_findings"] if row.get("status") == "open"],
    }


def _write_current_task_md_for_task(conn: sqlite3.Connection, task_ref: str) -> None:
    """Regenerate CURRENT_TASK.md from DB state for the active task."""
    snapshot = _collect_task_snapshot(conn, task_ref)
    markdown = _render_current_task_md(_build_current_task_state_from_snapshot(snapshot))
    CURRENT_TASK_PATH.write_text(markdown)


def _apply_handoff_migrations(conn: sqlite3.Connection) -> None:
    """Apply additive schema migrations for existing handoff DBs."""
    try:
        needs_backfill = False
        if not _has_column(conn, "review_findings", "resolution_notes"):
            conn.execute("ALTER TABLE review_findings ADD COLUMN resolution_notes TEXT")
            needs_backfill = True
        if not _has_column(conn, "review_findings", "reopen_count"):
            conn.execute("ALTER TABLE review_findings ADD COLUMN reopen_count INTEGER NOT NULL DEFAULT 0")
            needs_backfill = True
        if not _has_column(conn, "review_findings", "last_reopen_reason"):
            conn.execute("ALTER TABLE review_findings ADD COLUMN last_reopen_reason TEXT")
            needs_backfill = True
        if not _has_column(conn, "review_findings", "last_reopened_at"):
            conn.execute("ALTER TABLE review_findings ADD COLUMN last_reopened_at TEXT")
            needs_backfill = True
        if not _has_column(conn, "review_findings", "updated_at"):
            conn.execute("ALTER TABLE review_findings ADD COLUMN updated_at TEXT")
            needs_backfill = True
        if not needs_backfill:
            needs_backfill = (
                conn.execute(
                    """
                    SELECT 1
                    FROM review_findings
                    WHERE reopen_count IS NULL
                       OR updated_at IS NULL
                       OR TRIM(updated_at) = ''
                    LIMIT 1
                    """
                ).fetchone()
                is not None
            )
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
            return
        raise

    try:
        _ensure_review_findings_unique_index(conn)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            return
        raise


def _resolve_awaitable(value: object) -> object:
    """Resolve awaitables in both sync contexts and active-event-loop contexts."""
    if not inspect.isawaitable(value):
        return value

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)

    # FastMCP can execute tool handlers inside an active loop; bridge via a helper thread.
    box: dict[str, object] = {}

    def _runner() -> None:
        try:
            box["value"] = asyncio.run(value)
        except Exception as exc:  # pragma: no cover - surfaced to caller
            box["error"] = exc
            box["traceback"] = exc.__traceback__

    thread = Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        error = box["error"]
        if isinstance(error, Exception):
            tb = box.get("traceback")
            if tb is not None:
                error = error.with_traceback(tb)  # type: ignore[arg-type]
        raise error  # type: ignore[misc]
    return box.get("value")


def _normalize_tool_result(value: object) -> str:
    """Normalize FastMCP tool return types into plain text."""
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
    """Extract wrapped tool callables through supported FastMCP wrapper protocols."""
    if isinstance(candidate, _FnWrappedTool) and candidate.fn is not candidate:
        return candidate.fn
    if isinstance(candidate, _FunctionWrappedTool) and candidate.function is not candidate:
        return candidate.function
    if isinstance(candidate, _FuncWrappedTool) and candidate.func is not candidate:
        return candidate.func
    return None


def _invoke_tool(tool: object, **kwargs: object) -> str:
    """
    Call tool handlers across FastMCP wrapper variations.

    Supports:
    - Plain callables (direct function style)
    - Wrapped handlers via `.fn`/`.function`/`.func` chains
    - Tool adapter objects exposing `run(arguments_dict)` (async or sync)
    """
    candidate: object = tool
    visited: set[int] = set()

    for _ in range(10):
        if inspect.isawaitable(candidate):
            candidate = _resolve_awaitable(candidate)
            continue

        if callable(candidate):
            result = _resolve_awaitable(candidate(**kwargs))
            return _normalize_tool_result(result)

        marker = id(candidate)
        if marker in visited:
            break
        visited.add(marker)

        unwrapped = _unwrap_tool_candidate(candidate)
        if unwrapped is not None:
            candidate = unwrapped
            continue

        if isinstance(candidate, _RunnableTool):
            result = _resolve_awaitable(candidate.run(kwargs))
            return _normalize_tool_result(result)

        break

    raise TypeError(f"Unable to invoke tool of type {type(tool).__name__}")


def _utcnow_iso() -> str:
    """UTC timestamp for portable JSON exports/imports."""
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _render_current_task_md(state: dict) -> str:
    """Render a compact, deterministic markdown summary from structured state."""
    active = state.get("active")
    if not active:
        return (
            "# CURRENT_TASK\n\n"
            "_DO NOT EDIT: generated from .task-state/handoff.db._\n\n"
            "No active handoff state found.\n"
        )

    lines = [
        "# CURRENT_TASK",
        "",
        "_DO NOT EDIT: generated from .task-state/handoff.db._",
        "",
        f"## Objective",
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

    blockers = state.get("blockers_open", [])
    if blockers:
        for blocker in blockers:
            lines.append(f"- [#{blocker.get('id')}] {blocker.get('description')}")
    else:
        lines.append("- None")

    lines.extend(["", "## Pending Next Actions"])
    actions = state.get("actions_pending", [])
    if actions:
        for action in actions:
            lines.append(f"- (P{action.get('priority')}) [#{action.get('id')}] {action.get('action')}")
    else:
        lines.append("- None")

    lines.extend(["", "## Recent Decisions"])
    decisions = state.get("decisions_recent", [])
    if decisions:
        for decision in decisions:
            lines.append(f"- [#{decision.get('id')}] {decision.get('decision')}")
    else:
        lines.append("- None")

    lines.extend(["", "## Latest Verified Tests"])
    tests = state.get("tests_recent", [])
    if tests:
        for test in tests:
            passed = "pass" if test.get("passed") else "fail"
            lines.append(f"- [#{test.get('id')}] `{test.get('command')}` -> `{passed}`")
    else:
        lines.append("- None")

    lines.extend(["", "## Open Review Findings"])
    findings = state.get("findings_open", [])
    if findings:
        for finding in findings:
            sev = finding.get("severity", "").upper()
            fid = finding.get("finding_id", "")
            fp = finding.get("file_path", "")
            ls = finding.get("line_start")
            loc = f"{fp}:{ls}" if ls else fp
            desc = finding.get("description", "")
            lines.append(f"- [{sev}] {fid}: {loc} -- {desc}")
    else:
        lines.append("- None")

    lines.append("")
    return "\n".join(lines)


def _collect_task_snapshot(conn: sqlite3.Connection, task_ref: str) -> dict:
    """Collect full task state across all handoff tables."""
    active_row = conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone()
    active = _row_to_dict(active_row) if active_row is not None and active_row["task_ref"] == task_ref else None

    blockers = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM blockers WHERE task_ref = ? ORDER BY created_at DESC",
            (task_ref,),
        ).fetchall()
    ]
    actions = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM next_actions WHERE task_ref = ? ORDER BY priority ASC, created_at ASC",
            (task_ref,),
        ).fetchall()
    ]
    decisions = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM decisions WHERE task_ref = ? ORDER BY created_at DESC",
            (task_ref,),
        ).fetchall()
    ]
    tests = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM verified_tests WHERE task_ref = ? ORDER BY verified_at DESC",
            (task_ref,),
        ).fetchall()
    ]

    findings = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM review_findings WHERE task_ref = ? ORDER BY "
            "CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, "
            "COALESCE(updated_at, created_at) DESC",
            (task_ref,),
        ).fetchall()
    ]

    return {
        "task_ref": task_ref,
        "active": active,
        "blockers": blockers,
        "next_actions": actions,
        "decisions": decisions,
        "verified_tests": tests,
        "review_findings": findings,
    }


def _fetch_handoff_rows(
    conn: sqlite3.Connection,
    *,
    table: str,
    where_sql: str,
    order_sql: str,
    limit: int,
    params: tuple[object, ...],
) -> list[dict]:
    """Fetch rows for handoff list sections using a single shared query shape."""
    query = f"SELECT * FROM {table} WHERE {where_sql} ORDER BY {order_sql} LIMIT ?"
    rows = conn.execute(query, (*params, limit)).fetchall()
    return [dict(row) for row in rows]


def _resolve_import_row_actor(
    row: dict,
    *,
    fallback_agent: str,
    fallback_branch: str,
    fallback_commit: str | None,
) -> tuple[str, str, str | None]:
    """Resolve row-level provenance for imports with non-null agent/branch defaults."""
    agent = _normalize_optional_text(row.get("agent")) or fallback_agent
    branch = _normalize_optional_text(row.get("branch")) or fallback_branch
    commit_sha = _normalize_optional_text(row.get("commit_sha")) or fallback_commit
    return agent, branch, commit_sha


def _insert_import_blockers(
    conn: sqlite3.Connection,
    task_ref: str,
    blockers: list[dict],
    now: str,
    *,
    fallback_agent: str,
    fallback_branch: str,
    fallback_commit: str | None,
) -> None:
    for row in blockers:
        agent, branch, commit_sha = _resolve_import_row_actor(
            row,
            fallback_agent=fallback_agent,
            fallback_branch=fallback_branch,
            fallback_commit=fallback_commit,
        )
        conn.execute(
            """
            INSERT INTO blockers (
                task_ref, description, status, agent, branch, commit_sha, resolved_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_ref,
                row.get("description", ""),
                row.get("status", "open"),
                agent,
                branch,
                commit_sha,
                row.get("resolved_at"),
                row.get("created_at") or now,
            ),
        )


def _insert_import_actions(
    conn: sqlite3.Connection,
    task_ref: str,
    actions: list[dict],
    now: str,
    *,
    fallback_agent: str,
    fallback_branch: str,
    fallback_commit: str | None,
) -> None:
    for row in actions:
        agent, branch, commit_sha = _resolve_import_row_actor(
            row,
            fallback_agent=fallback_agent,
            fallback_branch=fallback_branch,
            fallback_commit=fallback_commit,
        )
        conn.execute(
            """
            INSERT INTO next_actions (
                task_ref, action, priority, status, agent, branch, commit_sha, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_ref,
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


def _insert_import_decisions(
    conn: sqlite3.Connection,
    task_ref: str,
    decisions: list[dict],
    now: str,
    *,
    fallback_agent: str,
    fallback_branch: str,
    fallback_commit: str | None,
) -> None:
    for row in decisions:
        agent, branch, commit_sha = _resolve_import_row_actor(
            row,
            fallback_agent=fallback_agent,
            fallback_branch=fallback_branch,
            fallback_commit=fallback_commit,
        )
        conn.execute(
            """
            INSERT INTO decisions (
                task_ref, session, decision, rationale, agent, branch, commit_sha, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_ref,
                row.get("session", "import"),
                row.get("decision", ""),
                row.get("rationale"),
                agent,
                branch,
                commit_sha,
                row.get("created_at") or now,
            ),
        )


def _insert_import_tests(
    conn: sqlite3.Connection,
    task_ref: str,
    tests: list[dict],
    now: str,
    *,
    fallback_agent: str,
    fallback_branch: str,
    fallback_commit: str | None,
) -> None:
    for row in tests:
        agent, branch, commit_sha = _resolve_import_row_actor(
            row,
            fallback_agent=fallback_agent,
            fallback_branch=fallback_branch,
            fallback_commit=fallback_commit,
        )
        conn.execute(
            """
            INSERT INTO verified_tests (
                task_ref, command, passed, exit_code, result, session, agent, branch, commit_sha, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_ref,
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


def _insert_import_findings(
    conn: sqlite3.Connection,
    task_ref: str,
    findings: list[dict],
    now: str,
    *,
    fallback_agent: str,
    fallback_branch: str,
    fallback_commit: str | None,
) -> None:
    for row in findings:
        agent, branch, commit_sha = _resolve_import_row_actor(
            row,
            fallback_agent=fallback_agent,
            fallback_branch=fallback_branch,
            fallback_commit=fallback_commit,
        )
        conn.execute(
            """
            INSERT INTO review_findings (
                task_ref, finding_id, severity, file_path, line_start, line_end,
                description, fix, status, session, agent, branch, commit_sha,
                resolution_notes, reopen_count, last_reopen_reason, last_reopened_at,
                resolved_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_ref,
                row.get("finding_id", ""),
                row.get("severity", "low"),
                row.get("file_path", ""),
                row.get("line_start"),
                row.get("line_end"),
                row.get("description", ""),
                row.get("fix"),
                row.get("status", "open"),
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


def _set_import_active_state(conn: sqlite3.Connection, task_ref: str, active: dict) -> None:
    git_branch, git_commit = _detect_git_write_context()
    updated_by = _normalize_optional_text(active.get("updated_by")) or _normalize_optional_text(
        os.environ.get("MCP_HANDOFF_DEFAULT_AGENT")
    ) or "codex"
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
            (
                task_ref,
                active.get("objective", ""),
                active.get("status", "in_progress"),
                updated_by,
                updated_branch,
                updated_commit_sha,
            ),
        )
        return

    conn.execute(
        """
        UPDATE handoff_state
        SET task_ref = ?,
            objective = ?,
            status = ?,
            revision = revision + 1,
            updated_at = datetime('now'),
            updated_by = ?,
            updated_branch = ?,
            updated_commit_sha = ?
        WHERE id = 1
        """,
        (
            task_ref,
            active.get("objective", ""),
            active.get("status", "in_progress"),
            updated_by,
            updated_branch,
            updated_commit_sha,
        ),
    )


def _import_snapshot(conn: sqlite3.Connection, task_ref: str, snapshot: dict, mode: str, set_active: bool) -> dict[str, int]:
    blockers = snapshot.get("blockers", [])
    actions = snapshot.get("next_actions", [])
    decisions = snapshot.get("decisions", [])
    tests = snapshot.get("verified_tests", [])
    findings = snapshot.get("review_findings", [])
    active = snapshot.get("active")
    now = _utcnow_iso().replace("T", " ").replace("Z", "")
    git_branch, git_commit = _detect_git_write_context()
    fallback_agent = _normalize_optional_text(os.environ.get("MCP_HANDOFF_DEFAULT_AGENT")) or "codex"
    fallback_branch = git_branch or "unknown-branch"
    fallback_commit = git_commit
    if isinstance(active, dict):
        fallback_agent = _normalize_optional_text(active.get("updated_by")) or fallback_agent
        fallback_branch = _normalize_optional_text(active.get("updated_branch")) or fallback_branch
        fallback_commit = _normalize_optional_text(active.get("updated_commit_sha")) or fallback_commit

    if mode == "replace_task":
        conn.execute("DELETE FROM blockers WHERE task_ref = ?", (task_ref,))
        conn.execute("DELETE FROM next_actions WHERE task_ref = ?", (task_ref,))
        conn.execute("DELETE FROM decisions WHERE task_ref = ?", (task_ref,))
        conn.execute("DELETE FROM verified_tests WHERE task_ref = ?", (task_ref,))
        conn.execute("DELETE FROM review_findings WHERE task_ref = ?", (task_ref,))

    _insert_import_blockers(
        conn,
        task_ref,
        blockers,
        now,
        fallback_agent=fallback_agent,
        fallback_branch=fallback_branch,
        fallback_commit=fallback_commit,
    )
    _insert_import_actions(
        conn,
        task_ref,
        actions,
        now,
        fallback_agent=fallback_agent,
        fallback_branch=fallback_branch,
        fallback_commit=fallback_commit,
    )
    _insert_import_decisions(
        conn,
        task_ref,
        decisions,
        now,
        fallback_agent=fallback_agent,
        fallback_branch=fallback_branch,
        fallback_commit=fallback_commit,
    )
    _insert_import_tests(
        conn,
        task_ref,
        tests,
        now,
        fallback_agent=fallback_agent,
        fallback_branch=fallback_branch,
        fallback_commit=fallback_commit,
    )
    _insert_import_findings(
        conn,
        task_ref,
        findings,
        now,
        fallback_agent=fallback_agent,
        fallback_branch=fallback_branch,
        fallback_commit=fallback_commit,
    )

    if set_active and isinstance(active, dict):
        _set_import_active_state(conn, task_ref, active)

    return {
        "blockers": len(blockers),
        "next_actions": len(actions),
        "decisions": len(decisions),
        "verified_tests": len(tests),
        "review_findings": len(findings),
    }


def _count_task_rows(conn: sqlite3.Connection, task_ref: str) -> dict[str, int]:
    """Count persisted rows per handoff table for a task."""
    table_map = {
        "blockers": "blockers",
        "next_actions": "next_actions",
        "decisions": "decisions",
        "verified_tests": "verified_tests",
        "review_findings": "review_findings",
    }
    counts: dict[str, int] = {}
    for key, table in table_map.items():
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE task_ref = ?", (task_ref,)).fetchone()
        counts[key] = int(row["count"]) if row else 0
    return counts


def _resolve_output_path(output_path: str | None, task_ref: str) -> Path:
    """Resolve export output path and create parent directories."""
    if output_path:
        path = Path(output_path)
        if not path.is_absolute():
            path = MONOREPO_ROOT / path
    else:
        TASK_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = TASK_EXPORTS_DIR / f"handoff-{task_ref}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class WriteActor(TypedDict, total=False):
    """Optional provenance fields stamped on write operations."""

    agent: str
    branch: str
    commit_sha: str


class ReviewFindingDetails(TypedDict, total=False):
    """Optional structured fields for review findings."""

    line_start: int
    line_end: int
    fix: str


def _normalize_optional_text(value: object) -> str | None:
    """Normalize optional text inputs so empty/blank values become None."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized != "" else None


def _first_non_empty_env(*keys: str) -> str | None:
    """Return first non-empty environment variable from ordered keys."""
    for key in keys:
        candidate = _normalize_optional_text(os.environ.get(key))
        if candidate is not None:
            return candidate
    return None


_GIT_WRITE_CONTEXT_CACHE: tuple[str | None, str | None] | None = None


def _detect_git_write_context() -> tuple[str | None, str | None]:
    """Best-effort current branch/commit lookup for write provenance fallback."""
    global _GIT_WRITE_CONTEXT_CACHE
    if _GIT_WRITE_CONTEXT_CACHE is not None:
        return _GIT_WRITE_CONTEXT_CACHE

    branch: str | None = _first_non_empty_env(
        "MCP_HANDOFF_DEFAULT_BRANCH",
        "GITHUB_HEAD_REF",
        "GITHUB_REF_NAME",
        "CI_COMMIT_REF_NAME",
        "BRANCH_NAME",
    )
    commit_sha: str | None = _first_non_empty_env(
        "MCP_HANDOFF_DEFAULT_COMMIT_SHA",
        "GITHUB_SHA",
        "CI_COMMIT_SHA",
    )

    try:
        branch_proc = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if branch_proc.returncode == 0:
            raw_branch = _normalize_optional_text(branch_proc.stdout)
            if raw_branch is not None and raw_branch != "HEAD":
                branch = raw_branch
            elif raw_branch == "HEAD" and branch is None:
                branch = "detached-head"
    except Exception:
        pass

    try:
        commit_proc = run_cmd(["git", "rev-parse", "HEAD"])
        if commit_proc.returncode == 0:
            commit_sha = _normalize_optional_text(commit_proc.stdout)
    except Exception:
        pass

    if branch is None:
        branch = "unknown-branch"

    _GIT_WRITE_CONTEXT_CACHE = (branch, commit_sha)
    return _GIT_WRITE_CONTEXT_CACHE


def _resolve_write_actor(conn: sqlite3.Connection, actor: WriteActor | None) -> tuple[str | None, str | None, str | None]:
    """Resolve write provenance from explicit actor, active state, or git context."""
    explicit_agent = _normalize_optional_text(actor.get("agent")) if actor else None
    explicit_branch = _normalize_optional_text(actor.get("branch")) if actor else None
    explicit_commit = _normalize_optional_text(actor.get("commit_sha")) if actor else None

    default_agent = _normalize_optional_text(os.environ.get("MCP_HANDOFF_DEFAULT_AGENT")) or "codex"
    active = conn.execute("SELECT updated_by, updated_branch, updated_commit_sha FROM handoff_state WHERE id = 1").fetchone()
    active_agent = _normalize_optional_text(active["updated_by"]) if active is not None else None
    active_branch = _normalize_optional_text(active["updated_branch"]) if active is not None else None
    active_commit = _normalize_optional_text(active["updated_commit_sha"]) if active is not None else None
    git_branch, git_commit = _detect_git_write_context()

    resolved_agent = explicit_agent or active_agent or default_agent
    resolved_branch = explicit_branch or active_branch or git_branch
    resolved_commit = explicit_commit or active_commit or git_commit
    return resolved_agent, resolved_branch, resolved_commit


def _parse_review_finding_details(details: ReviewFindingDetails | None) -> tuple[int | None, int | None, str | None]:
    """Extract optional finding detail fields."""
    if not details:
        return None, None, None
    return details.get("line_start"), details.get("line_end"), details.get("fix")


def _path_from_env(var_name: str, default_path: Path) -> Path:
    """Allow local/CI path overrides without changing tool call signatures."""
    raw = os.environ.get(var_name)
    if not raw:
        return default_path
    return Path(raw).expanduser().resolve()


# Initialize server
mcp = FastMCP(
    "ContextAltTextMonorepoMCP",
    instructions="""
    You are connected to the Context Alt Text monorepo MCP server.

    This server provides DOMAIN-SPECIFIC tools that complement (not duplicate)
    the host editor's built-in capabilities:

    - Cross-boundary tracing: trace_api_endpoint (PHP → Python → TS)
    - WordPress: find_wp_action, find_wp_rest_route, find_php_class
    - React/TS: find_react_component, find_react_hook, list_frontend_tests
    - Documentation: get_context_map, get_api_contract, get_instructions

    For general-purpose operations, use the host editor's native tools:
    - File reading/searching → Copilot's read_file, grep_search
    - Diagnostics/errors → Copilot's get_errors, Pylance MCP tools
    - Directory listing → Copilot's list_dir
    """,
)

# Path: scripts/mcp/unified_server.py -> parent.parent = monorepo root
MONOREPO_ROOT = Path(__file__).parent.parent.parent.resolve()
TASK_STATE_DIR = _path_from_env("MCP_HANDOFF_STATE_DIR", MONOREPO_ROOT / ".task-state")
HANDOFF_DB_PATH = TASK_STATE_DIR / "handoff.db"
CURRENT_TASK_PATH = _path_from_env("MCP_HANDOFF_CURRENT_TASK_PATH", MONOREPO_ROOT / "CURRENT_TASK.md")
TASK_EXPORTS_DIR = _path_from_env("MCP_HANDOFF_EXPORTS_DIR", TASK_STATE_DIR / "exports")

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


# =============================================================================
# Context & Documentation Tools
# =============================================================================


@mcp.tool()
def get_context_map(domain: str) -> str:
    """
    Get the context map for a specific domain.

    Args:
        domain: One of 'backend', 'frontend', 'php', 'integration'.

    Returns:
        The content of the relevant context map document.
    """
    context_maps = {
        "backend": MONOREPO_ROOT / "docs" / "agentic" / "maps" / "backend.md",
        "frontend": MONOREPO_ROOT / "docs" / "agentic" / "maps" / "frontend.md",
        "php": MONOREPO_ROOT / "docs" / "agentic" / "maps" / "php-plugin.md",
        "integration": MONOREPO_ROOT / "docs" / "agentic" / "maps" / "integration.md",
    }

    if domain not in context_maps:
        return f"Unknown domain '{domain}'. Valid: {', '.join(context_maps.keys())}"

    map_path = context_maps[domain]
    if not map_path.exists():
        return f"Context map not found: {map_path}"

    return map_path.read_text()


@mcp.tool()
def get_api_contract(contract_name: str = "clustering-api") -> str:
    """
    Get an API contract document.

    Args:
        contract_name: Name of the contract (without .md extension).

    Returns:
        The content of the contract document.
    """
    contract_path = MONOREPO_ROOT / "docs" / "agentic" / "contracts" / f"{contract_name}.md"
    if not contract_path.exists():
        # List available contracts
        contracts_dir = MONOREPO_ROOT / "docs" / "agentic" / "contracts"
        if contracts_dir.exists():
            available = [f.stem for f in contracts_dir.glob("*.md")]
            return f"Contract '{contract_name}' not found. Available: {', '.join(available)}"
        return f"Contract not found: {contract_name}"

    return contract_path.read_text()


@mcp.tool()
def get_instructions() -> str:
    """
    Get the main development instructions document.

    Returns:
        The content of docs/agentic/instructions.md.
    """
    instructions_path = MONOREPO_ROOT / "docs" / "agentic" / "instructions.md"
    if not instructions_path.exists():
        return "Instructions file not found."
    return instructions_path.read_text()


# =============================================================================
# Handoff State Tools (SQLite-backed)
# =============================================================================


@mcp.tool()
def set_handoff_state(
    task_ref: str,
    objective: str,
    status: str = "in_progress",
    expected_revision: int | None = None,
    actor: WriteActor | None = None,
) -> str:
    """
    Upsert singleton handoff state with optimistic revision guard.

    If the row does not exist, inserts id=1 with revision 0.
    If the row exists, requires expected_revision to protect against silent overwrite.
    """
    if status not in HANDOFF_ACTIVE_STATUSES:
        return _json_response(
            {
                "ok": False,
                "error": f"Invalid status. Valid: {', '.join(sorted(HANDOFF_ACTIVE_STATUSES))}",
            }
        )

    with _get_db_connection() as conn:
        agent, branch, commit_sha = _resolve_write_actor(conn, actor)
        current = conn.execute(
            "SELECT revision FROM handoff_state WHERE id = 1",
        ).fetchone()

        if current is None:
            conn.execute(
                """
                INSERT INTO handoff_state (
                    id, task_ref, objective, status, revision, updated_at, updated_by, updated_branch, updated_commit_sha
                ) VALUES (1, ?, ?, ?, 0, datetime('now'), ?, ?, ?)
                """,
                (task_ref, objective, status, agent, branch, commit_sha),
            )
            row = conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone()
            return _json_response({"ok": True, "inserted": True, "active": _row_to_dict(row)})

        if expected_revision is None:
            return _json_response(
                {
                    "ok": False,
                    "error": "expected_revision is required for updates.",
                    "current_revision": int(current["revision"]),
                }
            )

        updated = conn.execute(
            """
            UPDATE handoff_state
            SET task_ref = ?,
                objective = ?,
                status = ?,
                revision = revision + 1,
                updated_at = datetime('now'),
                updated_by = ?,
                updated_branch = ?,
                updated_commit_sha = ?
            WHERE id = 1 AND revision = ?
            """,
            (task_ref, objective, status, agent, branch, commit_sha, expected_revision),
        )

        if updated.rowcount == 0:
            latest = conn.execute("SELECT revision FROM handoff_state WHERE id = 1").fetchone()
            return _json_response(
                {
                    "ok": False,
                    "error": "Revision conflict.",
                    "expected_revision": expected_revision,
                    "current_revision": int(latest["revision"]) if latest else None,
                }
            )

        row = conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone()
        return _json_response({"ok": True, "updated": True, "active": _row_to_dict(row)})


@mcp.tool()
def get_handoff_state(
    task_ref: str | None = None,
    top_n_blockers: int = DEFAULT_HANDOFF_LIMITS["blockers"],
    top_n_actions: int = DEFAULT_HANDOFF_LIMITS["actions"],
    top_n_decisions: int = DEFAULT_HANDOFF_LIMITS["decisions"],
    top_n_tests: int = DEFAULT_HANDOFF_LIMITS["tests"],
    top_n_findings: int = DEFAULT_HANDOFF_LIMITS["findings"],
    verbose: bool = False,
) -> str:
    """
    Return compact handoff state with deterministic defaults for token efficiency.
    """
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

        query_limit = lambda size: size if not verbose else 10000
        blockers = _fetch_handoff_rows(
            conn,
            table="blockers",
            where_sql="task_ref = ? AND status = 'open'",
            order_sql="created_at DESC",
            limit=query_limit(top_n_blockers),
            params=(resolved_task_ref,),
        )
        actions = _fetch_handoff_rows(
            conn,
            table="next_actions",
            where_sql="task_ref = ? AND status = 'pending'",
            order_sql="priority ASC, created_at ASC",
            limit=query_limit(top_n_actions),
            params=(resolved_task_ref,),
        )
        decisions = _fetch_handoff_rows(
            conn,
            table="decisions",
            where_sql="task_ref = ?",
            order_sql="created_at DESC",
            limit=query_limit(top_n_decisions),
            params=(resolved_task_ref,),
        )
        tests = _fetch_handoff_rows(
            conn,
            table="verified_tests",
            where_sql="task_ref = ?",
            order_sql="verified_at DESC",
            limit=query_limit(top_n_tests),
            params=(resolved_task_ref,),
        )
        findings = _fetch_handoff_rows(
            conn,
            table="review_findings",
            where_sql="task_ref = ? AND status = 'open'",
            order_sql="CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, created_at DESC",
            limit=query_limit(top_n_findings),
            params=(resolved_task_ref,),
        )

        payload = {
            "ok": True,
            "limits": {
                "blockers": top_n_blockers,
                "actions": top_n_actions,
                "decisions": top_n_decisions,
                "tests": top_n_tests,
                "findings": top_n_findings,
            },
            "task_ref": resolved_task_ref,
            "active": active,
            "blockers_open": blockers,
            "actions_pending": actions,
            "decisions_recent": decisions,
            "tests_recent": tests,
            "findings_open": findings,
        }
        return _json_response(payload)


@mcp.tool()
def record_decision(
    session: str,
    decision: str,
    rationale: str | None = None,
    actor: WriteActor | None = None,
) -> str:
    """
    Append a decision record for the active handoff task.
    """
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        agent, branch, commit_sha = _resolve_write_actor(conn, actor)
        cur = conn.execute(
            """
            INSERT INTO decisions (
                task_ref, session, decision, rationale, agent, branch, commit_sha, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (resolved_task_ref, session, decision, rationale, agent, branch, commit_sha),
        )
        row = conn.execute("SELECT * FROM decisions WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _json_response({"ok": True, "decision": _row_to_dict(row)})


@mcp.tool()
def update_next_actions(
    operation: str,
    action_id: int | None = None,
    action: str | None = None,
    priority: int | None = None,
    status: str | None = None,
    actor: WriteActor | None = None,
) -> str:
    """
    Add/update/complete/skip next actions for the active handoff task.

    operation: add | update | complete | skip
    """
    valid_operations = {"add", "update", "complete", "skip"}
    if operation not in valid_operations:
        return _json_response({"ok": False, "error": f"Invalid operation. Valid: {', '.join(sorted(valid_operations))}"})

    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        agent, branch, commit_sha = _resolve_write_actor(conn, actor)

        if operation == "add":
            if not action:
                return _json_response({"ok": False, "error": "action is required for add."})
            use_priority = priority if priority is not None else 100
            cur = conn.execute(
                """
                INSERT INTO next_actions (
                    task_ref, action, priority, status, agent, branch, commit_sha, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (resolved_task_ref, action, use_priority, agent, branch, commit_sha),
            )
            row = conn.execute("SELECT * FROM next_actions WHERE id = ?", (cur.lastrowid,)).fetchone()
            return _json_response({"ok": True, "operation": operation, "action": _row_to_dict(row)})

        if action_id is None:
            return _json_response({"ok": False, "error": "action_id is required for update/complete/skip."})

        existing = conn.execute("SELECT * FROM next_actions WHERE id = ? AND task_ref = ?", (action_id, resolved_task_ref)).fetchone()
        if existing is None:
            return _json_response({"ok": False, "error": "Action not found for task_ref."})

        if operation == "update":
            if action is None and priority is None and status is None:
                return _json_response({"ok": False, "error": "At least one of action, priority, or status is required for update."})
            use_action = action if action is not None else str(existing["action"])
            use_priority = priority if priority is not None else int(existing["priority"])
            use_status = status if status is not None else str(existing["status"])
            if use_status not in {"pending", "done", "skipped"}:
                return _json_response({"ok": False, "error": "Invalid status value."})
            conn.execute(
                """
                UPDATE next_actions
                SET action = ?, priority = ?, status = ?, agent = ?, branch = ?, commit_sha = ?, updated_at = datetime('now')
                WHERE id = ? AND task_ref = ?
                """,
                (use_action, use_priority, use_status, agent, branch, commit_sha, action_id, resolved_task_ref),
            )
        elif operation == "complete":
            conn.execute(
                """
                UPDATE next_actions
                SET status = 'done', agent = ?, branch = ?, commit_sha = ?, updated_at = datetime('now')
                WHERE id = ? AND task_ref = ?
                """,
                (agent, branch, commit_sha, action_id, resolved_task_ref),
            )
        elif operation == "skip":
            conn.execute(
                """
                UPDATE next_actions
                SET status = 'skipped', agent = ?, branch = ?, commit_sha = ?, updated_at = datetime('now')
                WHERE id = ? AND task_ref = ?
                """,
                (agent, branch, commit_sha, action_id, resolved_task_ref),
            )

        row = conn.execute("SELECT * FROM next_actions WHERE id = ?", (action_id,)).fetchone()
        return _json_response({"ok": True, "operation": operation, "action": _row_to_dict(row)})


@mcp.tool()
def record_test_result(
    session: str,
    command: str,
    passed: bool,
    result: str | None = None,
    exit_code: int | None = None,
    actor: WriteActor | None = None,
) -> str:
    """
    Append a verified test record for the active handoff task.
    `passed` is required; exit_code is optional.
    """
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        agent, branch, commit_sha = _resolve_write_actor(conn, actor)
        cur = conn.execute(
            """
            INSERT INTO verified_tests (
                task_ref, command, passed, exit_code, result, session, agent, branch, commit_sha, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (resolved_task_ref, command, 1 if passed else 0, exit_code, result, session, agent, branch, commit_sha),
        )
        row = conn.execute("SELECT * FROM verified_tests WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _json_response({"ok": True, "test": _row_to_dict(row)})


@mcp.tool()
def report_blocker(
    operation: str,
    description: str | None = None,
    blocker_id: int | None = None,
    actor: WriteActor | None = None,
) -> str:
    """
    Manage blocker lifecycle for the active handoff task.

    operation: add | resolve | reopen
    """
    valid_operations = {"add", "resolve", "reopen"}
    if operation not in valid_operations:
        return _json_response({"ok": False, "error": f"Invalid operation. Valid: {', '.join(sorted(valid_operations))}"})

    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        agent, branch, commit_sha = _resolve_write_actor(conn, actor)

        if operation == "add":
            if not description:
                return _json_response({"ok": False, "error": "description is required for add."})
            cur = conn.execute(
                """
                INSERT INTO blockers (
                    task_ref, description, status, agent, branch, commit_sha, resolved_at, created_at
                ) VALUES (?, ?, 'open', ?, ?, ?, NULL, datetime('now'))
                """,
                (resolved_task_ref, description, agent, branch, commit_sha),
            )
            row = conn.execute("SELECT * FROM blockers WHERE id = ?", (cur.lastrowid,)).fetchone()
            return _json_response({"ok": True, "operation": operation, "blocker": _row_to_dict(row)})

        if blocker_id is None:
            return _json_response({"ok": False, "error": "blocker_id is required for resolve/reopen."})

        existing = conn.execute("SELECT * FROM blockers WHERE id = ? AND task_ref = ?", (blocker_id, resolved_task_ref)).fetchone()
        if existing is None:
            return _json_response({"ok": False, "error": "Blocker not found for task_ref."})

        if operation == "resolve":
            conn.execute(
                """
                UPDATE blockers
                SET status = 'resolved', resolved_at = datetime('now'), agent = ?, branch = ?, commit_sha = ?
                WHERE id = ? AND task_ref = ?
                """,
                (agent, branch, commit_sha, blocker_id, resolved_task_ref),
            )
        elif operation == "reopen":
            conn.execute(
                """
                UPDATE blockers
                SET status = 'open', resolved_at = NULL, agent = ?, branch = ?, commit_sha = ?
                WHERE id = ? AND task_ref = ?
                """,
                (agent, branch, commit_sha, blocker_id, resolved_task_ref),
            )

        row = conn.execute("SELECT * FROM blockers WHERE id = ?", (blocker_id,)).fetchone()
        return _json_response({"ok": True, "operation": operation, "blocker": _row_to_dict(row)})


@mcp.tool()
def record_review_finding(
    session: str,
    finding_id: str,
    severity: str,
    file_path: str,
    description: str,
    details: ReviewFindingDetails | None = None,
    actor: WriteActor | None = None,
) -> str:
    """
    Record a review finding from a branch review or code audit.

    severity: high | medium | low
    finding_id: Short identifier, e.g. "M-1", "L-3".
    file_path: Relative path from monorepo root.
    details: Optional structured detail fields (line_start, line_end, fix).
    """
    if severity not in REVIEW_FINDING_SEVERITIES:
        return _json_response(
            {"ok": False, "error": f"Invalid severity. Valid: {', '.join(sorted(REVIEW_FINDING_SEVERITIES))}"}
        )
    line_start, line_end, fix = _parse_review_finding_details(details)

    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        agent, branch, commit_sha = _resolve_write_actor(conn, actor)
        existing = conn.execute(
            "SELECT status FROM review_findings WHERE task_ref = ? AND finding_id = ?",
            (resolved_task_ref, finding_id),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO review_findings (
                task_ref, finding_id, severity, file_path, line_start, line_end,
                description, fix, status, session, agent, branch, commit_sha, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, datetime('now'), datetime('now'))
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
                reopen_count = CASE
                    WHEN review_findings.status <> 'open' THEN COALESCE(review_findings.reopen_count, 0) + 1
                    ELSE COALESCE(review_findings.reopen_count, 0)
                END,
                last_reopen_reason = CASE
                    WHEN review_findings.status <> 'open' THEN 'Re-recorded via review-record.'
                    ELSE review_findings.last_reopen_reason
                END,
                last_reopened_at = CASE
                    WHEN review_findings.status <> 'open' THEN datetime('now')
                    ELSE review_findings.last_reopened_at
                END,
                updated_at = datetime('now'),
                session = excluded.session,
                agent = COALESCE(review_findings.agent, excluded.agent),
                branch = COALESCE(review_findings.branch, excluded.branch),
                commit_sha = COALESCE(review_findings.commit_sha, excluded.commit_sha)
            """,
            (
                resolved_task_ref,
                finding_id,
                severity,
                file_path,
                line_start,
                line_end,
                description,
                fix,
                session,
                agent,
                branch,
                commit_sha,
            ),
        )
        row = conn.execute(
            "SELECT * FROM review_findings WHERE task_ref = ? AND finding_id = ?",
            (resolved_task_ref, finding_id),
        ).fetchone()
        _write_current_task_md_for_task(conn, resolved_task_ref)
        response_payload = {"ok": True, "finding": _row_to_dict(row)}
        if existing is not None and str(existing["status"]) != "open":
            response_payload["reopened"] = True
            response_payload["reopen_reason"] = "Re-recorded via review-record."
        return _json_response(response_payload)


@mcp.tool()
def update_review_finding(
    status: str,
    finding_id: str | None = None,
    finding_db_id: int | None = None,
    resolution_notes: str | None = None,
    reopen_reason: str | None = None,
    session: str | None = None,
    actor: WriteActor | None = None,
) -> str:
    """
    Update a review finding's status.

    status: open | fixed | wontfix | deferred
    resolution_notes: Optional short status rationale. Required for wontfix/deferred.
    reopen_reason: Required when transitioning from a non-open status back to open.
    finding_id: Logical finding key from record_review_finding, e.g. "M-3" (preferred).
    finding_db_id: Legacy integer primary key for backward compatibility.
    """
    if (finding_id is None and finding_db_id is None) or (finding_id is not None and finding_db_id is not None):
        return _json_response(
            {
                "ok": False,
                "error": "Pass exactly one of finding_id (preferred) or finding_db_id.",
            }
        )
    if status not in REVIEW_FINDING_STATUSES:
        return _json_response(
            {"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(REVIEW_FINDING_STATUSES))}"}
        )
    normalized_finding_id = finding_id.strip() if isinstance(finding_id, str) else None
    if normalized_finding_id == "":
        return _json_response({"ok": False, "error": "finding_id must not be empty."})
    normalized_resolution_notes = _normalize_optional_text(resolution_notes)
    normalized_reopen_reason = _normalize_optional_text(reopen_reason)
    if status in {"wontfix", "deferred"} and normalized_resolution_notes is None:
        return _json_response(
            {"ok": False, "error": f"resolution_notes is required when status is '{status}'."}
        )
    if status == "open" and normalized_resolution_notes is not None:
        return _json_response(
            {
                "ok": False,
                "error": "resolution_notes is not supported for status='open'. Use reopen_reason when reopening.",
            }
        )
    if normalized_resolution_notes is not None and len(normalized_resolution_notes) > MAX_RESOLUTION_NOTES_LENGTH:
        return _json_response(
            {
                "ok": False,
                "error": f"resolution_notes must be <= {MAX_RESOLUTION_NOTES_LENGTH} characters.",
            }
        )
    if normalized_reopen_reason is not None and len(normalized_reopen_reason) > MAX_REOPEN_REASON_LENGTH:
        return _json_response(
            {
                "ok": False,
                "error": f"reopen_reason must be <= {MAX_REOPEN_REASON_LENGTH} characters.",
            }
        )

    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        agent, branch, commit_sha = _resolve_write_actor(conn, actor)
        if normalized_finding_id is not None:
            existing = conn.execute(
                "SELECT * FROM review_findings WHERE finding_id = ? AND task_ref = ?",
                (normalized_finding_id, resolved_task_ref),
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT * FROM review_findings WHERE id = ? AND task_ref = ?",
                (finding_db_id, resolved_task_ref),
            ).fetchone()
        if existing is None:
            return _json_response(
                {
                    "ok": False,
                    "error": "Finding not found for active task.",
                }
            )

        existing_status = str(existing["status"])
        is_reopen_transition = existing_status != "open" and status == "open"
        if is_reopen_transition and normalized_reopen_reason is None:
            return _json_response({"ok": False, "error": "reopen_reason is required when reopening a finding."})
        if not is_reopen_transition and normalized_reopen_reason is not None:
            return _json_response(
                {
                    "ok": False,
                    "error": "reopen_reason is only valid when transitioning a finding back to open.",
                }
            )

        target_db_id = int(existing["id"])
        reopen_transition_int = 1 if is_reopen_transition else 0

        conn.execute(
            """
            UPDATE review_findings
            SET status = ?, resolved_at = CASE WHEN ? IN ('fixed', 'wontfix') THEN datetime('now') ELSE NULL END,
                agent = COALESCE(agent, ?), branch = COALESCE(branch, ?), commit_sha = COALESCE(commit_sha, ?),
                session = COALESCE(?, session),
                resolution_notes = CASE
                    WHEN ? = 'open' THEN NULL
                    WHEN ? IS NOT NULL THEN ?
                    WHEN ? = 'fixed' THEN NULL
                    ELSE resolution_notes
                END,
                reopen_count = CASE
                    WHEN ? = 1 THEN COALESCE(reopen_count, 0) + 1
                    ELSE COALESCE(reopen_count, 0)
                END,
                last_reopen_reason = CASE
                    WHEN ? = 1 THEN ?
                    ELSE last_reopen_reason
                END,
                last_reopened_at = CASE
                    WHEN ? = 1 THEN datetime('now')
                    ELSE last_reopened_at
                END,
                updated_at = datetime('now')
            WHERE id = ? AND task_ref = ?
            """,
            (
                status,
                status,
                agent,
                branch,
                commit_sha,
                session,
                status,
                normalized_resolution_notes,
                normalized_resolution_notes,
                status,
                reopen_transition_int,
                reopen_transition_int,
                normalized_reopen_reason,
                reopen_transition_int,
                target_db_id,
                resolved_task_ref,
            ),
        )
        row = conn.execute("SELECT * FROM review_findings WHERE id = ?", (target_db_id,)).fetchone()
        _write_current_task_md_for_task(conn, resolved_task_ref)
        payload = {"ok": True, "finding": _row_to_dict(row)}
        if is_reopen_transition:
            payload["reopened"] = True
            payload["reopen_reason"] = normalized_reopen_reason
        return _json_response(payload)


@mcp.tool()
def reopen_review_finding(
    reason: str,
    finding_id: str | None = None,
    finding_db_id: int | None = None,
    session: str | None = None,
    actor: WriteActor | None = None,
) -> str:
    """
    Reopen a review finding with a required rationale note.

    reason: Required short rationale explaining why the finding is reopened.
    """
    return update_review_finding(
        status="open",
        finding_id=finding_id,
        finding_db_id=finding_db_id,
        reopen_reason=reason,
        session=session,
        actor=actor,
    )


@mcp.tool()
def list_review_findings(
    task_ref: str | None = None,
    status: str = "all",
    severity: str = "all",
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    List review findings for a task with explicit filter/pagination support.
    """
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

        total_row = conn.execute(
            f"SELECT COUNT(*) AS count FROM review_findings WHERE {where_sql}",
            tuple(params),
        ).fetchone()
        total = int(total_row["count"]) if total_row else 0

        findings = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT *
                FROM review_findings
                WHERE {where_sql}
                ORDER BY
                    CASE status
                        WHEN 'open' THEN 0
                        WHEN 'deferred' THEN 1
                        WHEN 'fixed' THEN 2
                        WHEN 'wontfix' THEN 3
                    END,
                    CASE severity
                        WHEN 'high' THEN 0
                        WHEN 'medium' THEN 1
                        WHEN 'low' THEN 2
                    END,
                    COALESCE(updated_at, created_at) DESC,
                    id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
        ]

        status_counts = {key: 0 for key in sorted(REVIEW_FINDING_STATUSES)}
        for row in conn.execute(
            "SELECT status, COUNT(*) AS count FROM review_findings WHERE task_ref = ? GROUP BY status",
            (resolved_task_ref,),
        ).fetchall():
            status_counts[str(row["status"])] = int(row["count"])

        severity_counts = {key: 0 for key in sorted(REVIEW_FINDING_SEVERITIES)}
        for row in conn.execute(
            "SELECT severity, COUNT(*) AS count FROM review_findings WHERE task_ref = ? GROUP BY severity",
            (resolved_task_ref,),
        ).fetchall():
            severity_counts[str(row["severity"])] = int(row["count"])

    return _json_response(
        {
            "ok": True,
            "task_ref": resolved_task_ref,
            "filters": {
                "status": status,
                "severity": severity,
                "limit": limit,
                "offset": offset,
            },
            "total_matching": total,
            "returned": len(findings),
            "has_more": (offset + len(findings)) < total,
            "counts": {
                "status": status_counts,
                "severity": severity_counts,
            },
            "findings": findings,
        }
    )


@mcp.tool()
def get_review_finding(
    finding_db_id: int | None = None,
    finding_id: str | None = None,
    task_ref: str | None = None,
) -> str:
    """
    Retrieve a single review finding by DB id or human-readable finding_id.

    Supply exactly one of:
    - finding_db_id: integer primary key (e.g. 110)
    - finding_id: human-readable string (e.g. "H-OCI-28")
    """
    if finding_db_id is None and finding_id is None:
        return _json_response({"ok": False, "error": "Provide finding_db_id (int) or finding_id (string)."})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        if finding_db_id is not None:
            row = conn.execute(
                "SELECT * FROM review_findings WHERE id = ? AND task_ref = ?",
                (finding_db_id, resolved_task_ref),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM review_findings WHERE finding_id = ? AND task_ref = ?",
                (finding_id, resolved_task_ref),
            ).fetchone()
        if row is None:
            return _json_response({"ok": False, "error": "Finding not found for task."})
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "finding": _row_to_dict(row),
            }
        )


@mcp.tool()
def get_review_findings_summary(
    task_ref: str | None = None,
    top_n_open: int = 5,
    top_n_recent_updates: int = 3,
) -> str:
    """
    Return compact counts and short lists for review finding verification.
    """
    top_n_open = max(1, top_n_open)
    top_n_recent_updates = max(1, top_n_recent_updates)

    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)

        totals = conn.execute(
            "SELECT COUNT(*) AS total FROM review_findings WHERE task_ref = ?",
            (resolved_task_ref,),
        ).fetchone()
        total = int(totals["total"]) if totals else 0

        status_counts = {key: 0 for key in sorted(REVIEW_FINDING_STATUSES)}
        for row in conn.execute(
            "SELECT status, COUNT(*) AS count FROM review_findings WHERE task_ref = ? GROUP BY status",
            (resolved_task_ref,),
        ).fetchall():
            status_counts[str(row["status"])] = int(row["count"])

        severity_counts = {key: 0 for key in sorted(REVIEW_FINDING_SEVERITIES)}
        for row in conn.execute(
            "SELECT severity, COUNT(*) AS count FROM review_findings WHERE task_ref = ? GROUP BY severity",
            (resolved_task_ref,),
        ).fetchall():
            severity_counts[str(row["severity"])] = int(row["count"])

        open_findings = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM review_findings
                WHERE task_ref = ? AND status = 'open'
                ORDER BY
                    CASE severity
                        WHEN 'high' THEN 0
                        WHEN 'medium' THEN 1
                        WHEN 'low' THEN 2
                    END,
                    COALESCE(updated_at, created_at) DESC,
                    id DESC
                LIMIT ?
                """,
                (resolved_task_ref, top_n_open),
            ).fetchall()
        ]

        recent_updates = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM review_findings
                WHERE task_ref = ?
                ORDER BY COALESCE(updated_at, resolved_at, created_at) DESC, id DESC
                LIMIT ?
                """,
                (resolved_task_ref, top_n_recent_updates),
            ).fetchall()
        ]

    return _json_response(
        {
            "ok": True,
            "task_ref": resolved_task_ref,
            "counts": {
                "total": total,
                "status": status_counts,
                "severity": severity_counts,
            },
            "open_top": open_findings,
            "recent_updates": recent_updates,
            "limits": {
                "top_n_open": top_n_open,
                "top_n_recent_updates": top_n_recent_updates,
            },
        }
    )


def _collect_review_findings_integrity(
    conn: sqlite3.Connection,
    task_ref: str,
    *,
    apply: bool = False,
) -> dict:
    """Collect review-finding integrity checks for a task."""
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

    open_count = int(
        conn.execute(
            "SELECT COUNT(*) AS count FROM review_findings WHERE task_ref = ? AND status = 'open'",
            (task_ref,),
        ).fetchone()["count"]
    )

    active_row = conn.execute("SELECT task_ref, status FROM handoff_state WHERE id = 1").fetchone()
    active_status = str(active_row["status"]) if active_row is not None and str(active_row["task_ref"]) == task_ref else None
    done_with_open_findings = bool(active_status == "done" and open_count > 0)

    stale_open_findings = []
    open_findings = conn.execute(
        """
        SELECT id, finding_id, file_path, created_at, updated_at
        FROM review_findings
        WHERE task_ref = ? AND status = 'open'
        ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
        """,
        (task_ref,),
    ).fetchall()
    for row in open_findings:
        raw_file_path = str(row["file_path"])
        path = Path(raw_file_path)
        if not path.is_absolute():
            path = MONOREPO_ROOT / raw_file_path
        if not path.exists():
            continue

        activity_dt = _parse_sqlite_datetime(row["updated_at"]) or _parse_sqlite_datetime(row["created_at"])
        if activity_dt is None:
            continue

        file_modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if file_modified_at > activity_dt:
            stale_open_findings.append(
                {
                    "id": int(row["id"]),
                    "finding_id": str(row["finding_id"]),
                    "file_path": raw_file_path,
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]) if row["updated_at"] is not None else None,
                    "file_modified_at": file_modified_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

    missing_provenance_rows = conn.execute(
        """
        SELECT id, finding_id, agent, branch, commit_sha
        FROM review_findings
        WHERE task_ref = ?
          AND (
            agent IS NULL OR TRIM(agent) = ''
            OR branch IS NULL OR TRIM(branch) = ''
          )
        ORDER BY id DESC
        """,
        (task_ref,),
    ).fetchall()
    missing_provenance = [
        {
            "id": int(row["id"]),
            "finding_id": str(row["finding_id"]),
            "agent": row["agent"],
            "branch": row["branch"],
            "commit_sha": row["commit_sha"],
        }
        for row in missing_provenance_rows
    ]

    reopen_metadata_rows = conn.execute(
        """
        SELECT id, finding_id, reopen_count, last_reopen_reason, last_reopened_at
        FROM review_findings
        WHERE task_ref = ?
          AND COALESCE(reopen_count, 0) > 0
          AND (
            last_reopen_reason IS NULL OR TRIM(last_reopen_reason) = ''
            OR last_reopened_at IS NULL OR TRIM(last_reopened_at) = ''
          )
        ORDER BY id DESC
        """,
        (task_ref,),
    ).fetchall()
    reopen_metadata_violations = [
        {
            "id": int(row["id"]),
            "finding_id": str(row["finding_id"]),
            "reopen_count": int(row["reopen_count"]),
            "last_reopen_reason": row["last_reopen_reason"],
            "last_reopened_at": row["last_reopened_at"],
        }
        for row in reopen_metadata_rows
    ]

    healthy = (
        len(duplicates) == 0
        and not done_with_open_findings
        and len(stale_open_findings) == 0
        and len(missing_provenance) == 0
        and len(reopen_metadata_violations) == 0
    )
    return {
        "healthy": healthy,
        "checks": {
            "duplicates": {
                "count": len(duplicates),
                "items": duplicates,
                "deduped_rows_removed": deduped_rows_removed,
            },
            "done_with_open_findings": {
                "active_status": active_status,
                "open_count": open_count,
                "is_violation": done_with_open_findings,
            },
            "stale_open_findings": {
                "count": len(stale_open_findings),
                "items": stale_open_findings,
            },
            "missing_provenance": {
                "count": len(missing_provenance),
                "items": missing_provenance,
            },
            "reopen_metadata": {
                "count": len(reopen_metadata_violations),
                "items": reopen_metadata_violations,
            },
        },
    }


@mcp.tool()
def reconcile_review_findings(task_ref: str | None = None, apply: bool = False) -> str:
    """
    Validate review-finding state integrity for a task.

    Checks:
    - duplicate logical finding ids within a task
    - task marked done while open findings remain
    - open findings whose target file changed after last finding activity (stale)
    - missing write provenance (agent/branch) on findings
    - reopen metadata coherence for reopened findings
    """
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        report = _collect_review_findings_integrity(conn, resolved_task_ref, apply=apply)
        deduped_rows_removed = int(report["checks"]["duplicates"]["deduped_rows_removed"])
        active_status = report["checks"]["done_with_open_findings"]["active_status"]
        if apply and deduped_rows_removed > 0 and active_status is not None:
            _write_current_task_md_for_task(conn, resolved_task_ref)

    return _json_response(
        {
            "ok": True,
            "task_ref": resolved_task_ref,
            "healthy": report["healthy"],
            "checks": report["checks"],
        }
    )


def _collect_task_provenance_integrity(conn: sqlite3.Connection, task_ref: str) -> dict:
    """Collect missing write-provenance checks across handoff tables."""
    table_specs = (
        ("decisions", "id"),
        ("blockers", "id"),
        ("next_actions", "id"),
        ("verified_tests", "id"),
        ("review_findings", "id"),
    )
    table_checks: dict[str, dict[str, object]] = {}
    total_issues = 0

    for table_name, id_column in table_specs:
        rows = conn.execute(
            f"""
            SELECT {id_column} AS row_id, agent, branch, commit_sha
            FROM {table_name}
            WHERE task_ref = ?
              AND (
                agent IS NULL OR TRIM(agent) = ''
                OR branch IS NULL OR TRIM(branch) = ''
              )
            ORDER BY {id_column} DESC
            """,
            (task_ref,),
        ).fetchall()
        items = [
            {
                "row_id": int(row["row_id"]),
                "agent": row["agent"],
                "branch": row["branch"],
                "commit_sha": row["commit_sha"],
            }
            for row in rows
        ]
        table_checks[table_name] = {
            "count": len(items),
            "items": items,
        }
        total_issues += len(items)

    active_row = conn.execute(
        "SELECT updated_by, updated_branch, updated_commit_sha FROM handoff_state WHERE id = 1 AND task_ref = ?",
        (task_ref,),
    ).fetchone()
    active_missing = None
    if active_row is not None:
        missing = (
            _normalize_optional_text(active_row["updated_by"]) is None
            or _normalize_optional_text(active_row["updated_branch"]) is None
        )
        active_missing = {
            "count": 1 if missing else 0,
            "is_violation": missing,
            "updated_by": active_row["updated_by"],
            "updated_branch": active_row["updated_branch"],
            "updated_commit_sha": active_row["updated_commit_sha"],
        }
        total_issues += 1 if missing else 0

    return {
        "healthy": total_issues == 0,
        "total_issues": total_issues,
        "tables": table_checks,
        "active_state": active_missing,
    }


@mcp.tool()
def handoff_close_check(
    task_ref: str | None = None,
    allow_no_active_task: bool = False,
    enforce: bool = False,
) -> str:
    """
    Validate whether a task handoff is safe to close.

    The check enforces:
    - target task is the active singleton task
    - active status is `done`
    - zero open blockers
    - zero pending next actions
    - zero open review findings
    - review finding integrity is healthy
    - write provenance integrity is healthy (agent/branch populated)
    - CURRENT_TASK.md matches deterministic DB-generated view
    """
    with _get_db_connection() as conn:
        active_row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
        if task_ref is None:
            if active_row is None:
                if allow_no_active_task:
                    return _json_response(
                        {
                            "ok": True,
                            "ready_to_close": True,
                            "skipped": True,
                            "reason": "No active handoff task found.",
                        }
                    )
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
        current_task_exists = CURRENT_TASK_PATH.exists()
        current_task_in_sync = False
        if current_task_exists and active_task_matches:
            current_task_in_sync = CURRENT_TASK_PATH.read_text() == expected_markdown

    failures: list[str] = []
    if not active_task_matches:
        failures.append("Target task is not the active handoff task.")
    if active_status != "done":
        failures.append("Active task status must be 'done'.")
    if len(open_blockers) > 0:
        failures.append("Open blockers must be resolved before close.")
    if len(pending_actions) > 0:
        failures.append("Pending next actions must be done or skipped before close.")
    if len(open_findings) > 0:
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
            "active_task": {
                "matches_target": active_task_matches,
                "status": active_status,
                "is_done": active_status == "done",
            },
            "open_blockers": {
                "count": len(open_blockers),
                "is_violation": len(open_blockers) > 0,
                "items": open_blockers,
            },
            "pending_actions": {
                "count": len(pending_actions),
                "is_violation": len(pending_actions) > 0,
                "items": pending_actions,
            },
            "open_review_findings": {
                "count": len(open_findings),
                "is_violation": len(open_findings) > 0,
                "items": open_findings,
            },
            "review_integrity": review_integrity,
            "write_provenance": provenance_integrity,
            "current_task_sync": {
                "path": str(CURRENT_TASK_PATH),
                "exists": current_task_exists,
                "is_in_sync": current_task_in_sync,
            },
        },
        "failures": failures,
    }
    if enforce and not ready_to_close:
        payload["error"] = "Handoff close checks failed."
    return _json_response(payload)


@mcp.tool()
def generate_current_task_md(task_ref: str | None = None, write_file: bool = True) -> str:
    """
    Generate deterministic CURRENT_TASK markdown from handoff state.
    """
    raw_state = _invoke_tool(
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
    markdown = _render_current_task_md(state)

    if write_file:
        CURRENT_TASK_PATH.write_text(markdown)

    return _json_response(
        {
            "ok": True,
            "task_ref": state.get("task_ref"),
            "path": str(CURRENT_TASK_PATH),
            "written": write_file,
            "markdown": markdown if not write_file else None,
        }
    )


@mcp.tool()
def export_handoff_state(
    task_ref: str | None = None,
    output_path: str | None = None,
    include_markdown: bool = True,
) -> str:
    """
    Export handoff state for a task to a JSON file for cross-machine sharing.
    """
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        snapshot = _collect_task_snapshot(conn, resolved_task_ref)

    export_payload = {
        "export_version": 1,
        "task_ref": resolved_task_ref,
        "exported_at": _utcnow_iso(),
        "snapshot": snapshot,
    }
    if include_markdown:
        markdown_state = {
            "active": snapshot["active"],
            "blockers_open": [row for row in snapshot["blockers"] if row.get("status") == "open"],
            "actions_pending": [row for row in snapshot["next_actions"] if row.get("status") == "pending"],
            "decisions_recent": snapshot["decisions"],
            "tests_recent": snapshot["verified_tests"],
            "findings_open": [row for row in snapshot["review_findings"] if row.get("status") == "open"],
        }
        export_payload["current_task_markdown"] = _render_current_task_md(markdown_state)

    destination = _resolve_output_path(output_path, resolved_task_ref)
    destination.write_text(json.dumps(export_payload, indent=2, sort_keys=True))

    return _json_response(
        {
            "ok": True,
            "task_ref": resolved_task_ref,
            "path": str(destination),
            "counts": {
                "blockers": len(snapshot["blockers"]),
                "next_actions": len(snapshot["next_actions"]),
                "decisions": len(snapshot["decisions"]),
                "verified_tests": len(snapshot["verified_tests"]),
                "review_findings": len(snapshot["review_findings"]),
            },
        }
    )


@mcp.tool()
def import_handoff_state(
    input_path: str,
    mode: str = "merge",
    set_active: bool = False,
    allow_destructive_clear: bool = False,
) -> str:
    """
    Import a previously exported handoff snapshot.

    mode: merge | replace_task
    """
    if mode not in {"merge", "replace_task"}:
        return _json_response({"ok": False, "error": "Invalid mode. Valid: merge, replace_task."})

    source = Path(input_path)
    if not source.is_absolute():
        source = MONOREPO_ROOT / source
    if not source.exists():
        return _json_response({"ok": False, "error": f"Input file not found: {source}"})

    payload = json.loads(source.read_text())
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        return _json_response({"ok": False, "error": "Invalid import payload: snapshot must be an object."})
    task_ref = payload.get("task_ref") or snapshot.get("task_ref")
    if not task_ref:
        return _json_response({"ok": False, "error": "Missing task_ref in import payload."})

    required_sections = ("blockers", "next_actions", "decisions", "verified_tests", "review_findings")
    if mode == "replace_task":
        missing_sections = [key for key in required_sections if key not in snapshot]
        if missing_sections:
            return _json_response(
                {
                    "ok": False,
                    "error": (
                        "Invalid replace_task payload: missing required snapshot sections "
                        f"{', '.join(missing_sections)}."
                    ),
                }
            )

    for key in required_sections:
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
            incoming_counts = {
                "blockers": len(snapshot.get("blockers", [])),
                "next_actions": len(snapshot.get("next_actions", [])),
                "decisions": len(snapshot.get("decisions", [])),
                "verified_tests": len(snapshot.get("verified_tests", [])),
                "review_findings": len(snapshot.get("review_findings", [])),
            }
            potentially_cleared = [
                section
                for section, existing_count in existing_counts.items()
                if existing_count > 0 and incoming_counts.get(section, 0) == 0
            ]
            if potentially_cleared:
                return _json_response(
                    {
                        "ok": False,
                        "error": (
                            "replace_task would clear existing handoff rows in sections: "
                            f"{', '.join(potentially_cleared)}. "
                            "Re-run with allow_destructive_clear=true to confirm."
                        ),
                        "existing_counts": existing_counts,
                        "incoming_counts": incoming_counts,
                    }
                )

        counts = _import_snapshot(
            conn,
            task_ref=task_ref,
            snapshot=snapshot,
            mode=mode,
            set_active=set_active,
        )

    return _json_response(
        {
            "ok": True,
            "task_ref": task_ref,
            "mode": mode,
            "set_active": set_active,
            "allow_destructive_clear": allow_destructive_clear,
            "counts": counts,
        }
    )


@mcp.tool()
def archive_task_state(
    task_ref: str | None = None,
    notes: str | None = None,
    archive_by: str | None = None,
    archive_branch: str | None = None,
    archive_commit_sha: str | None = None,
    clear_active_if_matches: bool = True,
    prune_working_rows: bool = False,
    allow_destructive_clear: bool = False,
) -> str:
    """
    Archive task snapshot and optionally prune working rows for completed tasks.
    """
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        snapshot = _collect_task_snapshot(conn, resolved_task_ref)

        if prune_working_rows and not allow_destructive_clear:
            working_counts = _count_task_rows(conn, resolved_task_ref)
            non_zero_sections = [section for section, count in working_counts.items() if count > 0]
            if non_zero_sections:
                return _json_response(
                    {
                        "ok": False,
                        "error": (
                            "prune_working_rows would clear handoff rows in sections: "
                            f"{', '.join(non_zero_sections)}. "
                            "Re-run with allow_destructive_clear=true to confirm."
                        ),
                        "existing_counts": working_counts,
                    }
                )

        conn.execute(
            """
            INSERT INTO task_archives (
                task_ref, archived_at, archived_by, archived_branch, archived_commit_sha, notes, snapshot_json
            ) VALUES (?, datetime('now'), ?, ?, ?, ?, ?)
            ON CONFLICT(task_ref) DO UPDATE SET
                archived_at = datetime('now'),
                archived_by = excluded.archived_by,
                archived_branch = excluded.archived_branch,
                archived_commit_sha = excluded.archived_commit_sha,
                notes = excluded.notes,
                snapshot_json = excluded.snapshot_json
            """,
            (
                resolved_task_ref,
                archive_by,
                archive_branch,
                archive_commit_sha,
                notes,
                json.dumps(snapshot, sort_keys=True),
            ),
        )

        active_cleared = False
        if clear_active_if_matches:
            active_row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
            if active_row is not None and str(active_row["task_ref"]) == resolved_task_ref:
                conn.execute("DELETE FROM handoff_state WHERE id = 1")
                active_cleared = True

        pruned = False
        if prune_working_rows:
            conn.execute("DELETE FROM decisions WHERE task_ref = ?", (resolved_task_ref,))
            conn.execute("DELETE FROM blockers WHERE task_ref = ?", (resolved_task_ref,))
            conn.execute("DELETE FROM next_actions WHERE task_ref = ?", (resolved_task_ref,))
            conn.execute("DELETE FROM verified_tests WHERE task_ref = ?", (resolved_task_ref,))
            conn.execute("DELETE FROM review_findings WHERE task_ref = ?", (resolved_task_ref,))
            pruned = True

    return _json_response(
        {
            "ok": True,
            "task_ref": resolved_task_ref,
            "active_cleared": active_cleared,
            "pruned_working_rows": pruned,
            "allow_destructive_clear": allow_destructive_clear,
        }
    )


@mcp.tool()
def get_handoff_dashboard(limit: int = 20, include_archived: bool = True) -> str:
    """
    Read-only summary of task activity for quick terminal inspection.
    """
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
        task_summaries = [dict(row) for row in rows]

        active = conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone()
        return _json_response(
            {
                "ok": True,
                "active": _row_to_dict(active),
                "tasks": task_summaries,
            }
        )


# =============================================================================
# Cross-Boundary Tools
# =============================================================================


@mcp.tool()
def trace_api_endpoint(endpoint: str) -> str:
    """
    Trace an API endpoint across all layers (PHP proxy, Python backend).

    Args:
        endpoint: The endpoint path fragment (e.g., '/clusters', 'scan').

    Returns:
        All references to this endpoint across PHP and Python code.
    """
    results = []

    # Search PHP (WordPress REST routes)
    php_result = run_rg(
        ["--line-number", "--no-heading", "-g", "*.php", endpoint],
        cwd=str(MONOREPO_ROOT / "apps" / "prototype-wp-alt-context"),
    )
    if php_result.stdout:
        results.append(f"PHP (WordPress):\n{php_result.stdout}")

    # Search Python (FastAPI routes)
    py_result = run_rg(
        ["--line-number", "--no-heading", "-g", "*.py", endpoint],
        cwd=str(MONOREPO_ROOT / "apps" / "prototype-description-service"),
    )
    if py_result.stdout:
        results.append(f"Python (FastAPI):\n{py_result.stdout}")

    # Search TypeScript (API calls)
    ts_result = run_rg(
        ["--line-number", "--no-heading", "-g", "*.ts", "-g", "*.tsx", endpoint],
        cwd=str(MONOREPO_ROOT / "apps" / "prototype-wp-alt-context" / "js"),
    )
    if ts_result.stdout:
        results.append(f"TypeScript (Frontend):\n{ts_result.stdout}")

    return "\n".join(results) if results else f"No references found for endpoint '{endpoint}'."


# =============================================================================
# Frontend-Specific Tools (TypeScript + React)
# =============================================================================


@mcp.tool()
def find_react_component(component_name: str) -> str:
    """
    Find a React component definition in the frontend codebase.

    Args:
        component_name: Name of the component (e.g., 'WorkbenchPage', 'ClusterCard').

    Returns:
        File location and component signature.
    """
    # Search for function components and class components
    patterns = [
        f"export (const|function) {component_name}",
        f"const {component_name}.*React\\.FC",
        f"function {component_name}.*\\(.*\\).*{{",
    ]

    results = []
    for pattern in patterns:
        result = run_rg(
            ["--line-number", "--no-heading", "-g", "*.tsx", pattern],
            cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context" / "js",
        )
        if result.stdout:
            results.append(result.stdout)

    return "\n".join(results) if results else f"Component '{component_name}' not found."


@mcp.tool()
def find_react_hook(hook_name: str) -> str:
    """
    Find a custom React hook definition.

    Args:
        hook_name: Name of the hook (e.g., 'useJobStateMachine', 'useClusters').

    Returns:
        File location and hook signature.
    """
    result = run_rg(
        ["--line-number", "--no-heading", "-g", "*.ts", "-g", "*.tsx", f"export (const|function) {hook_name}"],
        cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context" / "js",
    )
    return result.stdout if result.stdout else f"Hook '{hook_name}' not found."


@mcp.tool()
def list_frontend_tests(component: str | None = None) -> str:
    """
    List frontend test files, optionally filtered by component.

    Args:
        component: Filter tests related to a specific component.

    Returns:
        List of test files.
    """
    test_dir = MONOREPO_ROOT / "apps" / "prototype-wp-alt-context" / "js" / "admin"

    if component:
        result = run_cmd(
            ["find", str(test_dir), "-name", f"*{component}*.test.*", "-o", "-name", f"*{component}*.spec.*"],
        )
        return result.stdout if result.stdout else f"No tests found for '{component}'."

    result = run_cmd(
        ["find", str(test_dir), "-name", "*.test.*", "-o", "-name", "*.spec.*"],
    )
    return result.stdout if result.stdout else "No test files found."


# =============================================================================
# PHP WordPress-Specific Tools
# =============================================================================


@mcp.tool()
def find_wp_action(action_name: str) -> str:
    """
    Find WordPress action/filter hooks in the PHP codebase.

    Args:
        action_name: The action or filter name (e.g., 'init', 'rest_api_init').

    Returns:
        All add_action/add_filter and do_action/apply_filters calls.
    """
    patterns = [
        f"add_action.*['\\\"{action_name}",
        f"add_filter.*['\\\"{action_name}",
        f"do_action.*['\\\"{action_name}",
        f"apply_filters.*['\\\"{action_name}",
    ]

    results = []
    for pattern in patterns:
        result = run_rg(
            ["--line-number", "--no-heading", "-g", "*.php", pattern],
            cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context",
        )
        if result.stdout:
            results.append(result.stdout)

    return "\n".join(results) if results else f"No hooks found for '{action_name}'."


@mcp.tool()
def find_wp_rest_route(route: str) -> str:
    """
    Find WordPress REST API route registrations.

    Args:
        route: The route path or fragment (e.g., 'clusters', 'scan').

    Returns:
        All register_rest_route calls matching the route.
    """
    result = run_rg(
        ["--line-number", "--no-heading", "-A", "5", "-g", "*.php", f"register_rest_route.*{route}"],
        cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context",
    )
    return result.stdout if result.stdout else f"No REST route found for '{route}'."


@mcp.tool()
def find_php_class(class_name: str) -> str:
    """
    Find a PHP class definition.

    Args:
        class_name: Name of the class.

    Returns:
        File location and class declaration.
    """
    result = run_rg(
        ["--line-number", "--no-heading", "-g", "*.php", f"^class {class_name}"],
        cwd=MONOREPO_ROOT / "apps" / "prototype-wp-alt-context",
    )
    return result.stdout if result.stdout else f"Class '{class_name}' not found."


def _cli() -> None:
    """CLI for direct tool invocation from terminal."""
    import sys
    import json
    import argparse

    parser = argparse.ArgumentParser(description="MCP Tool CLI")
    subparsers = parser.add_subparsers(dest="cli_command", required=True)
    
    subparsers.add_parser("mcp", help="Run the MCP server (stdio transport)")

    # Read-only commands
    subparsers.add_parser("dashboard", help="Print handoff dashboard")
    
    p_state = subparsers.add_parser("state", help="Print current handoff state")
    p_state.add_argument("task_ref", nargs="?", help="Optional task reference")

    p_task = subparsers.add_parser("task", help="Generate CURRENT_TASK.md")
    p_task.add_argument("task_ref", nargs="?", help="Optional task reference")

    p_export = subparsers.add_parser("export", help="Export handoff snapshot to JSON")
    p_export.add_argument("--task_ref")
    p_export.add_argument("--output_path")
    p_export.add_argument("--no-markdown", action="store_true", help="Skip CURRENT_TASK markdown in export payload")

    p_import = subparsers.add_parser("import", help="Import handoff snapshot from JSON")
    p_import.add_argument("--input_path", required=True)
    p_import.add_argument("--mode", default="merge", choices=["merge", "replace_task"])
    p_import.add_argument("--set-active", action="store_true")
    p_import.add_argument(
        "--allow-destructive-clear",
        action="store_true",
        help="Acknowledge destructive clears for replace_task imports.",
    )

    p_archive = subparsers.add_parser("archive", help="Archive handoff task snapshot")
    p_archive.add_argument("--task_ref")
    p_archive.add_argument("--notes")
    p_archive.add_argument("--archive_by")
    p_archive.add_argument("--archive_branch")
    p_archive.add_argument("--archive_commit_sha")
    p_archive.add_argument("--no-clear-active", action="store_true")
    p_archive.add_argument("--prune-working-rows", action="store_true")
    p_archive.add_argument(
        "--allow-destructive-clear",
        action="store_true",
        help="Acknowledge destructive clears when pruning working rows.",
    )

    # Write commands
    p_set = subparsers.add_parser("set", help="Set active handoff state")
    p_set.add_argument("--task_ref", required=True)
    p_set.add_argument("--objective", required=True)
    p_set.add_argument("--status", default="in_progress", choices=sorted(HANDOFF_ACTIVE_STATUSES))
    p_set.add_argument("--expected_revision", type=int)

    p_decide = subparsers.add_parser("decision", help="Record a decision")
    p_decide.add_argument("--decision", required=True)
    p_decide.add_argument("--rationale")
    p_decide.add_argument("--session", default="cli")

    p_action = subparsers.add_parser("action", help="Manage next actions")
    p_action.add_argument("op", choices=["add", "update", "complete", "skip"])
    p_action.add_argument("--id", type=int)
    p_action.add_argument("--text")
    p_action.add_argument("--priority", type=int)
    p_action.add_argument("--status")

    p_block = subparsers.add_parser("blocker", help="Manage blockers")
    p_block.add_argument("op", choices=["add", "resolve", "reopen"])
    p_block.add_argument("--description")
    p_block.add_argument("--id", type=int)

    p_test = subparsers.add_parser("test", help="Record a test result")
    p_test.add_argument("--command", required=True)
    p_test.add_argument("--passed", action="store_true")
    p_test.add_argument("--result")
    p_test.add_argument("--session", default="cli")
    
    # Review Findings
    p_find_rec = subparsers.add_parser("review-record", help="Record a review finding")
    p_find_rec.add_argument("--finding_id", required=True, help="Short identifier e.g. H-1, M-3")
    p_find_rec.add_argument("--file_path", required=True)
    p_find_rec.add_argument("--line_start", type=int)
    p_find_rec.add_argument("--line_end", type=int)
    p_find_rec.add_argument("--description", required=True)
    p_find_rec.add_argument("--severity", required=True, choices=sorted(REVIEW_FINDING_SEVERITIES))
    p_find_rec.add_argument("--fix")
    p_find_rec.add_argument("--session", default="cli")

    p_find_upd = subparsers.add_parser("review-update", help="Update a review finding")
    p_find_upd.add_argument("--status", choices=sorted(REVIEW_FINDING_STATUSES), required=True)
    p_find_upd_group = p_find_upd.add_mutually_exclusive_group(required=True)
    p_find_upd_group.add_argument("--finding_id", help="Logical finding identifier (preferred), e.g. M-taskplan-3")
    p_find_upd_group.add_argument("--id", dest="finding_db_id", type=int, help="Legacy DB row id")
    p_find_upd.add_argument("--resolution_notes")
    p_find_upd.add_argument("--reopen_reason")
    p_find_upd.add_argument("--session", default="cli")
    p_find_upd.add_argument("--agent")
    p_find_upd.add_argument("--branch")

    p_find_reopen = subparsers.add_parser("review-reopen", help="Reopen a review finding with required reason")
    p_find_reopen_group = p_find_reopen.add_mutually_exclusive_group(required=True)
    p_find_reopen_group.add_argument("--finding_id", help="Logical finding identifier (preferred), e.g. M-taskplan-3")
    p_find_reopen_group.add_argument("--id", dest="finding_db_id", type=int, help="Legacy DB row id")
    p_find_reopen.add_argument("--reason", required=True)
    p_find_reopen.add_argument("--session", default="cli")

    p_find_list = subparsers.add_parser("review-list", help="List review findings")
    p_find_list.add_argument("--task_ref")
    p_find_list.add_argument("--status")
    p_find_list.add_argument("--severity")
    
    p_find_get = subparsers.add_parser("review-get", help="Get a review finding")
    p_find_get.add_argument("--id", type=int, required=True)

    p_find_sum = subparsers.add_parser("review-summary", help="Get a summary of review findings")
    p_find_sum.add_argument("--task_ref")

    p_find_reconcile = subparsers.add_parser("review-reconcile", help="Validate review-finding integrity for a task")
    p_find_reconcile.add_argument("--task_ref")
    p_find_reconcile.add_argument("--apply", action="store_true", help="Apply safe dedupe fixes when possible")

    p_close_check = subparsers.add_parser("handoff-close-check", help="Validate handoff close readiness")
    p_close_check.add_argument("--task_ref")
    p_close_check.add_argument(
        "--allow-no-active-task",
        action="store_true",
        help="Return success with skipped=true when no active task exists (CI smoke mode).",
    )
    p_close_check.add_argument(
        "--enforce",
        action="store_true",
        help="Exit non-zero when close checks fail.",
    )

    args = parser.parse_args()

    def process_result(json_str: str) -> None:
        try:
            parsed = json.loads(json_str)
            print(json.dumps(parsed, indent=2))
            if parsed.get("ok") is False:
                sys.exit(1)
        except json.JSONDecodeError:
            print(json_str)
            # If not JSON, assume success print (though all tools return JSON)

    # Dispatch
    if args.cli_command == "mcp":
        mcp.run(show_banner=False)
    elif args.cli_command == "dashboard":
        process_result(get_handoff_dashboard())
    elif args.cli_command == "state":
        process_result(get_handoff_state(task_ref=args.task_ref, verbose=True))
    elif args.cli_command == "task":
        process_result(generate_current_task_md(task_ref=args.task_ref, write_file=True))
    elif args.cli_command == "export":
        process_result(
            export_handoff_state(
                task_ref=args.task_ref,
                output_path=args.output_path,
                include_markdown=not args.no_markdown,
            )
        )
    elif args.cli_command == "import":
        process_result(
            import_handoff_state(
                input_path=args.input_path,
                mode=args.mode,
                set_active=args.set_active,
                allow_destructive_clear=args.allow_destructive_clear,
            )
        )
    elif args.cli_command == "archive":
        process_result(
            archive_task_state(
                task_ref=args.task_ref,
                notes=args.notes,
                archive_by=args.archive_by,
                archive_branch=args.archive_branch,
                archive_commit_sha=args.archive_commit_sha,
                clear_active_if_matches=not args.no_clear_active,
                prune_working_rows=args.prune_working_rows,
                allow_destructive_clear=args.allow_destructive_clear,
            )
        )
    elif args.cli_command == "set":
        process_result(
            set_handoff_state(
                task_ref=args.task_ref,
                objective=args.objective,
                status=args.status,
                expected_revision=args.expected_revision,
            )
        )
    elif args.cli_command == "decision":
        process_result(record_decision(session=args.session, decision=args.decision, rationale=args.rationale))
    elif args.cli_command == "action":
        process_result(
            update_next_actions(
                operation=args.op,
                action_id=args.id,
                action=args.text,
                priority=args.priority,
                status=args.status,
            )
        )
    elif args.cli_command == "blocker":
        process_result(report_blocker(operation=args.op, description=args.description, blocker_id=args.id))
    elif args.cli_command == "test":
        process_result(
            record_test_result(
                session=args.session,
                command=args.command,
                passed=args.passed,
                result=args.result,
            )
        )
    elif args.cli_command == "review-record":
        details: ReviewFindingDetails = {}
        if args.line_start is not None:
            details["line_start"] = args.line_start
        if args.line_end is not None:
            details["line_end"] = args.line_end
        if args.fix:
            details["fix"] = args.fix
        process_result(
            record_review_finding(
                session=args.session,
                finding_id=args.finding_id,
                file_path=args.file_path,
                description=args.description,
                severity=args.severity,
                details=details,
            )
        )
    elif args.cli_command == "review-update":
        process_result(
            update_review_finding(
                status=args.status,
                finding_id=args.finding_id,
                finding_db_id=args.finding_db_id,
                resolution_notes=args.resolution_notes,
                reopen_reason=args.reopen_reason,
                session=args.session,
                actor={"agent": args.agent, "branch": args.branch} if args.agent or args.branch else None,
            )
        )
    elif args.cli_command == "review-reopen":
        process_result(
            reopen_review_finding(
                reason=args.reason,
                finding_id=args.finding_id,
                finding_db_id=args.finding_db_id,
                session=args.session,
            )
        )
    elif args.cli_command == "review-list":
        process_result(
            list_review_findings(
                task_ref=args.task_ref,
                status=args.status or "all",
                severity=args.severity or "all",
            )
        )
    elif args.cli_command == "review-get":
        process_result(get_review_finding(finding_db_id=args.id))
    elif args.cli_command == "review-summary":
        process_result(get_review_findings_summary(task_ref=args.task_ref))
    elif args.cli_command == "review-reconcile":
        process_result(reconcile_review_findings(task_ref=args.task_ref, apply=args.apply))
    elif args.cli_command == "handoff-close-check":
        process_result(
            handoff_close_check(
                task_ref=args.task_ref,
                allow_no_active_task=args.allow_no_active_task,
                enforce=args.enforce,
            )
        )

if __name__ == "__main__":
    _cli()
