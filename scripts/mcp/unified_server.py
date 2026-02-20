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
from datetime import UTC, datetime
from pathlib import Path

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

    return {
        "task_ref": task_ref,
        "active": active,
        "blockers": blockers,
        "next_actions": actions,
        "decisions": decisions,
        "verified_tests": tests,
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
"""

DEFAULT_HANDOFF_LIMITS = {
    "blockers": 5,
    "actions": 5,
    "decisions": 3,
    "tests": 3,
}


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
    agent: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
) -> str:
    """
    Upsert singleton handoff state with optimistic revision guard.

    If the row does not exist, inserts id=1 with revision 0.
    If the row exists, requires expected_revision to protect against silent overwrite.
    """
    if status not in {"in_progress", "blocked", "review", "done"}:
        return _json_response({"ok": False, "error": "Invalid status value."})

    with _get_db_connection() as conn:
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
    verbose: bool = False,
) -> str:
    """
    Return compact handoff state with deterministic defaults for token efficiency.
    """
    top_n_blockers = max(1, top_n_blockers)
    top_n_actions = max(1, top_n_actions)
    top_n_decisions = max(1, top_n_decisions)
    top_n_tests = max(1, top_n_tests)

    with _get_db_connection() as conn:
        active_row = conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone()
        if active_row is None and task_ref is None:
            return _json_response({"ok": True, "active": None, "message": "No active handoff state."})

        resolved_task_ref = task_ref or str(active_row["task_ref"])
        active = _row_to_dict(active_row) if active_row is not None else None
        if active is not None and resolved_task_ref != active["task_ref"]:
            active = None

        blockers = conn.execute(
            """
            SELECT * FROM blockers
            WHERE task_ref = ? AND status = 'open'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (resolved_task_ref, top_n_blockers if not verbose else 10000),
        ).fetchall()

        actions = conn.execute(
            """
            SELECT * FROM next_actions
            WHERE task_ref = ? AND status = 'pending'
            ORDER BY priority ASC, created_at ASC
            LIMIT ?
            """,
            (resolved_task_ref, top_n_actions if not verbose else 10000),
        ).fetchall()

        decisions = conn.execute(
            """
            SELECT * FROM decisions
            WHERE task_ref = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (resolved_task_ref, top_n_decisions if not verbose else 10000),
        ).fetchall()

        tests = conn.execute(
            """
            SELECT * FROM verified_tests
            WHERE task_ref = ?
            ORDER BY verified_at DESC
            LIMIT ?
            """,
            (resolved_task_ref, top_n_tests if not verbose else 10000),
        ).fetchall()

        payload = {
            "ok": True,
            "limits": {
                "blockers": top_n_blockers,
                "actions": top_n_actions,
                "decisions": top_n_decisions,
                "tests": top_n_tests,
            },
            "task_ref": resolved_task_ref,
            "active": active,
            "blockers_open": [dict(row) for row in blockers],
            "actions_pending": [dict(row) for row in actions],
            "decisions_recent": [dict(row) for row in decisions],
            "tests_recent": [dict(row) for row in tests],
        }
        return _json_response(payload)


@mcp.tool()
def record_decision(
    session: str,
    decision: str,
    rationale: str | None = None,
    task_ref: str | None = None,
    agent: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
) -> str:
    """
    Append a decision record, defaulting task_ref to active handoff task.
    """
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
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
    task_ref: str | None = None,
    agent: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
) -> str:
    """
    Add/update/complete/skip next actions.

    operation: add | update | complete | skip
    """
    valid_operations = {"add", "update", "complete", "skip"}
    if operation not in valid_operations:
        return _json_response({"ok": False, "error": f"Invalid operation. Valid: {', '.join(sorted(valid_operations))}"})

    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)

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
    task_ref: str | None = None,
    agent: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
) -> str:
    """
    Append a verified test record. `passed` is required; exit_code is optional.
    """
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
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
    task_ref: str | None = None,
    agent: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
) -> str:
    """
    Manage blocker lifecycle.

    operation: add | resolve | reopen
    """
    valid_operations = {"add", "resolve", "reopen"}
    if operation not in valid_operations:
        return _json_response({"ok": False, "error": f"Invalid operation. Valid: {', '.join(sorted(valid_operations))}"})

    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)

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
def generate_current_task_md(task_ref: str | None = None, write_file: bool = True) -> str:
    """
    Generate deterministic CURRENT_TASK markdown from handoff state.
    """
    raw_state = get_handoff_state(
        task_ref=task_ref,
        top_n_blockers=50,
        top_n_actions=50,
        top_n_decisions=50,
        top_n_tests=50,
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
    snapshot = payload.get("snapshot", {})
    task_ref = payload.get("task_ref") or snapshot.get("task_ref")
    if not task_ref:
        return _json_response({"ok": False, "error": "Missing task_ref in import payload."})

    blockers = snapshot.get("blockers", [])
    actions = snapshot.get("next_actions", [])
    decisions = snapshot.get("decisions", [])
    tests = snapshot.get("verified_tests", [])
    active = snapshot.get("active")
    now = _utcnow_iso().replace("T", " ").replace("Z", "")

    with _get_db_connection() as conn:
        if mode == "replace_task":
            conn.execute("DELETE FROM blockers WHERE task_ref = ?", (task_ref,))
            conn.execute("DELETE FROM next_actions WHERE task_ref = ?", (task_ref,))
            conn.execute("DELETE FROM decisions WHERE task_ref = ?", (task_ref,))
            conn.execute("DELETE FROM verified_tests WHERE task_ref = ?", (task_ref,))

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

        if set_active and active:
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
            else:
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

    return _json_response(
        {
            "ok": True,
            "task_ref": task_ref,
            "mode": mode,
            "set_active": set_active,
            "counts": {
                "blockers": len(blockers),
                "next_actions": len(actions),
                "decisions": len(decisions),
                "verified_tests": len(tests),
            },
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
    with _get_db_connection() as conn:
        task_rows = conn.execute(
            """
            SELECT task_ref, MAX(updated_at) AS last_activity
            FROM (
                SELECT task_ref, created_at AS updated_at FROM decisions
                UNION ALL
                SELECT task_ref, created_at AS updated_at FROM blockers
                UNION ALL
                SELECT task_ref, updated_at FROM next_actions
                UNION ALL
                SELECT task_ref, verified_at AS updated_at FROM verified_tests
            )
            GROUP BY task_ref
            ORDER BY last_activity DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        task_refs = [str(row["task_ref"]) for row in task_rows]
        last_activity_map = {str(row["task_ref"]): row["last_activity"] for row in task_rows}

        if include_archived:
            archive_rows = conn.execute(
                """
                SELECT task_ref, archived_at
                FROM task_archives
                ORDER BY archived_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            for row in archive_rows:
                task_ref = str(row["task_ref"])
                if task_ref not in last_activity_map:
                    last_activity_map[task_ref] = row["archived_at"]
                    task_refs.append(task_ref)

        task_summaries = []
        for task_ref in task_refs:
            open_blockers = conn.execute(
                "SELECT COUNT(*) FROM blockers WHERE task_ref = ? AND status = 'open'",
                (task_ref,),
            ).fetchone()[0]
            pending_actions = conn.execute(
                "SELECT COUNT(*) FROM next_actions WHERE task_ref = ? AND status = 'pending'",
                (task_ref,),
            ).fetchone()[0]
            archived = conn.execute(
                "SELECT archived_at FROM task_archives WHERE task_ref = ?",
                (task_ref,),
            ).fetchone()

            if not include_archived and archived is not None:
                continue

            task_summaries.append(
                {
                    "task_ref": task_ref,
                    "last_activity": last_activity_map[task_ref],
                    "open_blockers": int(open_blockers),
                    "pending_actions": int(pending_actions),
                    "archived_at": archived["archived_at"] if archived is not None else None,
                }
            )

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


if __name__ == "__main__":
    mcp.run()
