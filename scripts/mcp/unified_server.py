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
            "created_at DESC",
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


def _insert_import_blockers(conn: sqlite3.Connection, task_ref: str, blockers: list[dict], now: str) -> None:
    for row in blockers:
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
                row.get("agent"),
                row.get("branch"),
                row.get("commit_sha"),
                row.get("resolved_at"),
                row.get("created_at") or now,
            ),
        )


def _insert_import_actions(conn: sqlite3.Connection, task_ref: str, actions: list[dict], now: str) -> None:
    for row in actions:
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
                row.get("agent"),
                row.get("branch"),
                row.get("commit_sha"),
                row.get("created_at") or now,
                row.get("updated_at") or row.get("created_at") or now,
            ),
        )


def _insert_import_decisions(conn: sqlite3.Connection, task_ref: str, decisions: list[dict], now: str) -> None:
    for row in decisions:
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
                row.get("agent"),
                row.get("branch"),
                row.get("commit_sha"),
                row.get("created_at") or now,
            ),
        )


def _insert_import_tests(conn: sqlite3.Connection, task_ref: str, tests: list[dict], now: str) -> None:
    for row in tests:
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
                row.get("agent"),
                row.get("branch"),
                row.get("commit_sha"),
                row.get("verified_at") or now,
            ),
        )


def _insert_import_findings(conn: sqlite3.Connection, task_ref: str, findings: list[dict], now: str) -> None:
    for row in findings:
        conn.execute(
            """
            INSERT INTO review_findings (
                task_ref, finding_id, severity, file_path, line_start, line_end,
                description, fix, status, session, agent, branch, commit_sha, resolved_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                row.get("agent"),
                row.get("branch"),
                row.get("commit_sha"),
                row.get("resolved_at"),
                row.get("created_at") or now,
            ),
        )


def _set_import_active_state(conn: sqlite3.Connection, task_ref: str, active: dict) -> None:
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
                active.get("updated_by"),
                active.get("updated_branch"),
                active.get("updated_commit_sha"),
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
            active.get("updated_by"),
            active.get("updated_branch"),
            active.get("updated_commit_sha"),
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

    if mode == "replace_task":
        conn.execute("DELETE FROM blockers WHERE task_ref = ?", (task_ref,))
        conn.execute("DELETE FROM next_actions WHERE task_ref = ?", (task_ref,))
        conn.execute("DELETE FROM decisions WHERE task_ref = ?", (task_ref,))
        conn.execute("DELETE FROM verified_tests WHERE task_ref = ?", (task_ref,))
        conn.execute("DELETE FROM review_findings WHERE task_ref = ?", (task_ref,))

    _insert_import_blockers(conn, task_ref, blockers, now)
    _insert_import_actions(conn, task_ref, actions, now)
    _insert_import_decisions(conn, task_ref, decisions, now)
    _insert_import_tests(conn, task_ref, tests, now)
    _insert_import_findings(conn, task_ref, findings, now)

    if set_active and isinstance(active, dict):
        _set_import_active_state(conn, task_ref, active)

    return {
        "blockers": len(blockers),
        "next_actions": len(actions),
        "decisions": len(decisions),
        "verified_tests": len(tests),
        "review_findings": len(findings),
    }


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


def _resolve_write_actor(conn: sqlite3.Connection, actor: WriteActor | None) -> tuple[str | None, str | None, str | None]:
    """Resolve write provenance from explicit actor or active handoff row."""
    if actor:
        return (
            actor.get("agent"),
            actor.get("branch"),
            actor.get("commit_sha"),
        )

    active = conn.execute("SELECT updated_by, updated_branch, updated_commit_sha FROM handoff_state WHERE id = 1").fetchone()
    if active is None:
        return None, None, None
    return (
        active["updated_by"],
        active["updated_branch"],
        active["updated_commit_sha"],
    )


def _parse_review_finding_details(details: ReviewFindingDetails | None) -> tuple[int | None, int | None, str | None]:
    """Extract optional finding detail fields."""
    if not details:
        return None, None, None
    return details.get("line_start"), details.get("line_end"), details.get("fix")


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
TASK_STATE_DIR = MONOREPO_ROOT / ".task-state"
HANDOFF_DB_PATH = TASK_STATE_DIR / "handoff.db"
CURRENT_TASK_PATH = MONOREPO_ROOT / "CURRENT_TASK.md"
TASK_EXPORTS_DIR = TASK_STATE_DIR / "exports"

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
    resolved_at   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
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

REVIEW_FINDING_STATUSES = {"open", "fixed", "wontfix", "deferred"}
REVIEW_FINDING_SEVERITIES = {"high", "medium", "low"}


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
    if status not in {"in_progress", "blocked", "review", "done"}:
        return _json_response({"ok": False, "error": "Invalid status value."})

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
        cur = conn.execute(
            """
            INSERT INTO review_findings (
                task_ref, finding_id, severity, file_path, line_start, line_end,
                description, fix, status, session, agent, branch, commit_sha, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, datetime('now'))
            """,
            (
                resolved_task_ref, finding_id, severity, file_path,
                line_start, line_end, description, fix,
                session, agent, branch, commit_sha,
            ),
        )
        row = conn.execute("SELECT * FROM review_findings WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _json_response({"ok": True, "finding": _row_to_dict(row)})


@mcp.tool()
def update_review_finding(
    finding_db_id: int,
    status: str,
    actor: WriteActor | None = None,
) -> str:
    """
    Update a review finding's status.

    status: open | fixed | wontfix | deferred
    finding_db_id: The integer primary key from record_review_finding on the active task.
    """
    if status not in REVIEW_FINDING_STATUSES:
        return _json_response(
            {"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(REVIEW_FINDING_STATUSES))}"}
        )

    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, None)
        agent, branch, commit_sha = _resolve_write_actor(conn, actor)
        existing = conn.execute(
            "SELECT * FROM review_findings WHERE id = ? AND task_ref = ?",
            (finding_db_id, resolved_task_ref),
        ).fetchone()
        if existing is None:
            return _json_response({"ok": False, "error": "Finding not found for active task."})

        conn.execute(
            """
            UPDATE review_findings
            SET status = ?, resolved_at = CASE WHEN ? IN ('fixed', 'wontfix') THEN datetime('now') ELSE NULL END,
                agent = COALESCE(agent, ?), branch = COALESCE(branch, ?), commit_sha = COALESCE(commit_sha, ?)
            WHERE id = ? AND task_ref = ?
            """,
            (status, status, agent, branch, commit_sha, finding_db_id, resolved_task_ref),
        )
        row = conn.execute("SELECT * FROM review_findings WHERE id = ?", (finding_db_id,)).fetchone()
        return _json_response({"ok": True, "finding": _row_to_dict(row)})


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
                    created_at DESC,
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
    finding_db_id: int,
    task_ref: str | None = None,
) -> str:
    """
    Retrieve a single review finding by DB id for a task.
    """
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        row = conn.execute(
            "SELECT * FROM review_findings WHERE id = ? AND task_ref = ?",
            (finding_db_id, resolved_task_ref),
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
                    created_at DESC,
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
                ORDER BY COALESCE(resolved_at, created_at) DESC, id DESC
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

    with _get_db_connection() as conn:
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
) -> str:
    """
    Archive task snapshot and optionally prune working rows for completed tasks.
    """
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        snapshot = _collect_task_snapshot(conn, resolved_task_ref)

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
                SELECT task_ref, COALESCE(resolved_at, created_at) AS updated_at FROM review_findings
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

    custom_commands = {
        "dashboard", "state", "task", "set", "decision", "action", "blocker", "test",
        "review-record", "review-update", "review-list", "review-get", "review-summary"
    }

    if len(sys.argv) == 1 or sys.argv[1] not in custom_commands and sys.argv[1] not in ["-h", "--help"]:
        mcp.run()
        return

    parser = argparse.ArgumentParser(description="MCP Tool CLI")
    subparsers = parser.add_subparsers(dest="cli_command", required=True)

    # Read-only commands
    subparsers.add_parser("dashboard", help="Print handoff dashboard")
    
    p_state = subparsers.add_parser("state", help="Print current handoff state")
    p_state.add_argument("task_ref", nargs="?", help="Optional task reference")

    p_task = subparsers.add_parser("task", help="Generate CURRENT_TASK.md")
    p_task.add_argument("task_ref", nargs="?", help="Optional task reference")

    # Write commands
    p_set = subparsers.add_parser("set", help="Set active handoff state")
    p_set.add_argument("--task_ref", required=True)
    p_set.add_argument("--objective", required=True)
    p_set.add_argument("--status", default="in_progress")
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
    p_find_rec.add_argument("--severity", required=True, choices=["high", "medium", "low"])
    p_find_rec.add_argument("--fix")
    p_find_rec.add_argument("--session", default="cli")

    p_find_upd = subparsers.add_parser("review-update", help="Update a review finding")
    p_find_upd.add_argument("--id", type=int, required=True)
    p_find_upd.add_argument("--status", choices=["open", "resolved", "ignored"])
    p_find_upd.add_argument("--resolution_notes")
    p_find_upd.add_argument("--session", default="cli")

    p_find_list = subparsers.add_parser("review-list", help="List review findings")
    p_find_list.add_argument("--task_ref")
    p_find_list.add_argument("--status")
    p_find_list.add_argument("--severity")
    
    p_find_get = subparsers.add_parser("review-get", help="Get a review finding")
    p_find_get.add_argument("--id", type=int, required=True)

    p_find_sum = subparsers.add_parser("review-summary", help="Get a summary of review findings")
    p_find_sum.add_argument("--task_ref")

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
    with _get_db_connection() as conn:
        if args.cli_command == "dashboard":
            process_result(get_handoff_dashboard())
        elif args.cli_command == "state":
            process_result(get_handoff_state(task_ref=args.task_ref, verbose=True))
        elif args.cli_command == "task":
            process_result(generate_current_task_md(task_ref=args.task_ref, write_file=True))
        elif args.cli_command == "set":
            process_result(set_handoff_state(
                task_ref=args.task_ref, objective=args.objective, status=args.status,
                expected_revision=args.expected_revision
            ))
        elif args.cli_command == "decision":
            process_result(record_decision(session=args.session, decision=args.decision, rationale=args.rationale))
        elif args.cli_command == "action":
            process_result(update_next_actions(
                operation=args.op, action_id=args.id, action=args.text,
                priority=args.priority, status=args.status
            ))
        elif args.cli_command == "blocker":
            process_result(report_blocker(operation=args.op, description=args.description, blocker_id=args.id))
        elif args.cli_command == "test":
            process_result(record_test_result(
                session=args.session, command=args.command, passed=args.passed, result=args.result
            ))
        elif args.cli_command == "review-record":
            details: ReviewFindingDetails = {}
            if args.line_start is not None:
                details["line_start"] = args.line_start
            if args.line_end is not None:
                details["line_end"] = args.line_end
            if args.fix:
                details["fix"] = args.fix
            process_result(record_review_finding(
                session=args.session, finding_id=args.finding_id, file_path=args.file_path,
                description=args.description, severity=args.severity, details=details
            ))
        elif args.cli_command == "review-update":
            process_result(update_review_finding(
                finding_id=args.id, status=args.status, resolution_notes=args.resolution_notes, session=args.session
            ))
        elif args.cli_command == "review-list":
            process_result(list_review_findings(
                task_ref=args.task_ref,
                status=args.status or "all",
                severity=args.severity or "all",
            ))
        elif args.cli_command == "review-get":
            process_result(get_review_finding(finding_id=args.id))
        elif args.cli_command == "review-summary":
            process_result(get_review_findings_summary(task_ref=args.task_ref))

if __name__ == "__main__":
    _cli()
