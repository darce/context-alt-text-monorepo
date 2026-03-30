"""Shared utilities for agent_handoff_mcp domain modules.

This module contains all cross-cutting helpers that multiple domain modules
need. Domain modules import from here; core.py re-exports from here for
backward-compatible access.

No imports from .core (circular). Only imports from standard library,
.runtime, .enums, .slice_decision, .artifact_index.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from typing import Any, Awaitable, Callable, Protocol, TypedDict, cast, runtime_checkable

from .runtime import get_runtime_config
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
    ReviewKind,
    ReportStatus,
    ReviewMode,
    ReviewScopeSource,
    normalize_model_identity,
    normalize_model_label,
    normalize_reasoning_level,
)
from .slice_decision import (
    classify_decision_id,  # noqa: F401 – re-exported for core.py
    extract_slice_label,  # noqa: F401 – re-exported for core.py
    is_canonical_decision,  # noqa: F401 – re-exported for core.py
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
# Constants
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
# TypedDicts / dataclasses
# ---------------------------------------------------------------------------


class WriteActor(TypedDict, total=False):
    agent: str
    model: str
    model_label: str
    reasoning_level: str
    branch: str
    commit_sha: str
    lane_id: str


@dataclass
class ResolvedWriteContext:
    agent: str | None
    branch: str | None
    commit_sha: str | None
    lane_id: str | None
    model: str | None
    model_label: str | None
    reasoning_level: str | None


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
# Schema SQL strings
# ---------------------------------------------------------------------------

HANDOFF_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS handoff_state (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    task_ref          TEXT NOT NULL,
    objective         TEXT NOT NULL,
    focus             TEXT,
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
    model         TEXT,
    model_label   TEXT,
    reasoning_level TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    total_tokens  INTEGER,
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
    review_mode   TEXT
                  CHECK (review_mode IN ('branch', 'release_audit', 'planning') OR review_mode IS NULL),
    review_run_id TEXT,
    session       TEXT NOT NULL,
    agent         TEXT,
    branch        TEXT,
    commit_sha    TEXT,
    resolution_notes TEXT,
    reopen_count  INTEGER NOT NULL DEFAULT 0,
    last_reopen_reason TEXT,
    last_reopened_at TEXT,
    resolved_at   TEXT,
    verification_evidence TEXT,
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
    model         TEXT,
    backend       TEXT,
    reasoning_effort TEXT,
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
    payload_json  TEXT,
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

CREATE TABLE IF NOT EXISTS turn_metrics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    lane_id       TEXT,
    session       TEXT NOT NULL,
    cycle         INTEGER,
    phase         TEXT NOT NULL,
    backend       TEXT NOT NULL,
    model         TEXT,
    thread_id     TEXT,
    turn_id       TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cached_input_tokens INTEGER,
    reasoning_output_tokens INTEGER,
    total_tokens  INTEGER,
    usage_source  TEXT
                  CHECK (usage_source IN ('observed', 'tokenizer_estimate', 'char_estimate') OR usage_source IS NULL),
    model_context_window INTEGER,
    prompt_tokens INTEGER,
    prompt_chars  INTEGER,
    prompt_token_source TEXT
                  CHECK (prompt_token_source IN ('observed', 'tokenizer_estimate', 'char_estimate') OR prompt_token_source IS NULL),
    utilization_ratio REAL,
    domain_signal_ratio REAL,
    pressure_level TEXT,
    attribution_json TEXT NOT NULL DEFAULT '{}',
    section_sizes_json TEXT NOT NULL DEFAULT '{}',
    raw_usage_json TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS review_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    review_run_id    TEXT NOT NULL UNIQUE,
    task_ref         TEXT,
    subject_path     TEXT NOT NULL,
    subject_kind     TEXT NOT NULL DEFAULT 'task_plan'
                     CHECK (subject_kind IN ('task_plan', 'epic', 'branch', 'adr', 'roadmap', 'other')),
    review_mode      TEXT NOT NULL
                     CHECK (review_mode IN ('branch', 'release_audit', 'planning')),
    verdict_decision TEXT,
    verdict          TEXT
                     CHECK (verdict IN ('pass', 'pass_with_findings', 'fail', 'conditional_pass') OR verdict IS NULL),
    reviewed_at      TEXT NOT NULL DEFAULT (datetime('now')),
    agent            TEXT,
    model            TEXT,
    model_label      TEXT,
    branch           TEXT,
    commit_sha       TEXT,
    session          TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
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
CREATE INDEX IF NOT EXISTS idx_turn_metrics_task_lane_created
    ON turn_metrics(task_ref, lane_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_turn_metrics_task_backend_model
    ON turn_metrics(task_ref, backend, model, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_review_runs_task_reviewed
    ON review_runs(task_ref, reviewed_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_runs_subject_path
    ON review_runs(subject_path, reviewed_at DESC);
"""

HANDOFF_FTS_SCHEMA_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
    body,
    record_id UNINDEXED,
    task_ref  UNINDEXED,
    lane_id   UNINDEXED,
    tokenize='porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS findings_fts USING fts5(
    body,
    record_id UNINDEXED,
    task_ref  UNINDEXED,
    lane_id   UNINDEXED,
    status    UNINDEXED,
    tokenize='porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS blockers_fts USING fts5(
    body,
    record_id UNINDEXED,
    task_ref  UNINDEXED,
    lane_id   UNINDEXED,
    status    UNINDEXED,
    tokenize='porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS actions_fts USING fts5(
    body,
    record_id UNINDEXED,
    task_ref  UNINDEXED,
    lane_id   UNINDEXED,
    status    UNINDEXED,
    tokenize='porter unicode61'
);
"""

_HANDOFF_FTS_TRIGGERS_SQL = """
-- decisions triggers
CREATE TRIGGER IF NOT EXISTS decisions_fts_insert AFTER INSERT ON decisions BEGIN
    INSERT INTO decisions_fts(rowid, body, record_id, task_ref, lane_id)
    VALUES (new.id,
            new.decision || ' ' || COALESCE(new.rationale, ''),
            new.id, new.task_ref, new.lane_id);
END;

CREATE TRIGGER IF NOT EXISTS decisions_fts_update AFTER UPDATE ON decisions BEGIN
    DELETE FROM decisions_fts WHERE rowid = old.id;
    INSERT INTO decisions_fts(rowid, body, record_id, task_ref, lane_id)
    VALUES (new.id,
            new.decision || ' ' || COALESCE(new.rationale, ''),
            new.id, new.task_ref, new.lane_id);
END;

CREATE TRIGGER IF NOT EXISTS decisions_fts_delete AFTER DELETE ON decisions BEGIN
    DELETE FROM decisions_fts WHERE rowid = old.id;
END;

-- review_findings triggers
CREATE TRIGGER IF NOT EXISTS findings_fts_insert AFTER INSERT ON review_findings BEGIN
    INSERT INTO findings_fts(rowid, body, record_id, task_ref, lane_id, status)
    VALUES (new.id,
            new.description || ' ' || COALESCE(new.fix, ''),
            new.id, new.task_ref, new.lane_id, new.status);
END;

CREATE TRIGGER IF NOT EXISTS findings_fts_update AFTER UPDATE ON review_findings BEGIN
    DELETE FROM findings_fts WHERE rowid = old.id;
    INSERT INTO findings_fts(rowid, body, record_id, task_ref, lane_id, status)
    VALUES (new.id,
            new.description || ' ' || COALESCE(new.fix, ''),
            new.id, new.task_ref, new.lane_id, new.status);
END;

CREATE TRIGGER IF NOT EXISTS findings_fts_delete AFTER DELETE ON review_findings BEGIN
    DELETE FROM findings_fts WHERE rowid = old.id;
END;

-- blockers triggers
CREATE TRIGGER IF NOT EXISTS blockers_fts_insert AFTER INSERT ON blockers BEGIN
    INSERT INTO blockers_fts(rowid, body, record_id, task_ref, lane_id, status)
    VALUES (new.id, new.description, new.id, new.task_ref, new.lane_id, new.status);
END;

CREATE TRIGGER IF NOT EXISTS blockers_fts_update AFTER UPDATE ON blockers BEGIN
    DELETE FROM blockers_fts WHERE rowid = old.id;
    INSERT INTO blockers_fts(rowid, body, record_id, task_ref, lane_id, status)
    VALUES (new.id, new.description, new.id, new.task_ref, new.lane_id, new.status);
END;

CREATE TRIGGER IF NOT EXISTS blockers_fts_delete AFTER DELETE ON blockers BEGIN
    DELETE FROM blockers_fts WHERE rowid = old.id;
END;

-- next_actions triggers
CREATE TRIGGER IF NOT EXISTS actions_fts_insert AFTER INSERT ON next_actions BEGIN
    INSERT INTO actions_fts(rowid, body, record_id, task_ref, lane_id, status)
    VALUES (new.id, new.action, new.id, new.task_ref, new.lane_id, new.status);
END;

CREATE TRIGGER IF NOT EXISTS actions_fts_update AFTER UPDATE ON next_actions BEGIN
    DELETE FROM actions_fts WHERE rowid = old.id;
    INSERT INTO actions_fts(rowid, body, record_id, task_ref, lane_id, status)
    VALUES (new.id, new.action, new.id, new.task_ref, new.lane_id, new.status);
END;

CREATE TRIGGER IF NOT EXISTS actions_fts_delete AFTER DELETE ON next_actions BEGIN
    DELETE FROM actions_fts WHERE rowid = old.id;
END;
"""


def _backfill_handoff_fts(conn: sqlite3.Connection) -> None:
    """Populate FTS tables for rows that existed before triggers were created."""
    pairs: list[tuple[str, str, str]] = [
        (
            "decisions",
            "decisions_fts",
            "INSERT INTO decisions_fts(rowid, body, record_id, task_ref, lane_id) "
            "SELECT id, decision || ' ' || COALESCE(rationale, ''), id, task_ref, lane_id "
            "FROM decisions",
        ),
        (
            "review_findings",
            "findings_fts",
            "INSERT INTO findings_fts(rowid, body, record_id, task_ref, lane_id, status) "
            "SELECT id, description || ' ' || COALESCE(fix, ''), id, task_ref, lane_id, status "
            "FROM review_findings",
        ),
        (
            "blockers",
            "blockers_fts",
            "INSERT INTO blockers_fts(rowid, body, record_id, task_ref, lane_id, status) "
            "SELECT id, description, id, task_ref, lane_id, status FROM blockers",
        ),
        (
            "next_actions",
            "actions_fts",
            "INSERT INTO actions_fts(rowid, body, record_id, task_ref, lane_id, status) "
            "SELECT id, action, id, task_ref, lane_id, status FROM next_actions",
        ),
    ]
    existing_fts = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?,?)",
            ("decisions_fts", "findings_fts", "blockers_fts", "actions_fts"),
        ).fetchall()
    }
    for source_table, fts_table, backfill_sql in pairs:
        if fts_table not in existing_fts:
            continue
        src_count = conn.execute(f"SELECT COUNT(*) FROM {source_table}").fetchone()[0]
        if src_count > 0:
            fts_count = conn.execute(f"SELECT COUNT(*) FROM {fts_table}").fetchone()[0]
            if fts_count == 0:
                conn.execute(backfill_sql)


def _ensure_handoff_fts(conn: sqlite3.Connection) -> None:
    """Create FTS5 virtual tables, insert/update/delete triggers, and backfill existing rows."""
    import logging as _logging
    _log = _logging.getLogger("agent_handoff_mcp")
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_handoff_probe USING fts5(body)")
        conn.execute("DROP TABLE IF EXISTS _fts5_handoff_probe")
    except sqlite3.OperationalError:
        _log.debug("Handoff FTS5 unavailable on this SQLite build; structured search disabled.")
        return
    try:
        conn.executescript(HANDOFF_FTS_SCHEMA_SQL)
        _fts_expected = {"decisions_fts", "findings_fts", "blockers_fts", "actions_fts"}
        _fts_created = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?,?)",
                tuple(sorted(_fts_expected)),
            ).fetchall()
        }
        if _fts_created != _fts_expected:
            _log.warning(
                "FTS tables partially created (%s of %s); skipping trigger/backfill setup.",
                len(_fts_created), len(_fts_expected),
            )
            return
        conn.executescript(_HANDOFF_FTS_TRIGGERS_SQL)
        _backfill_handoff_fts(conn)
    except sqlite3.OperationalError as exc:
        errstr = str(exc).lower()
        if "locked" in errstr or "no such table" in errstr:
            _log.warning("Handoff FTS setup skipped (%s); will retry on next connection.", exc)
        elif "vtable constructor failed" in errstr:
            _log.warning(
                "Handoff FTS5 vtable corrupt (%s); dropping and recreating FTS tables.", exc
            )
            for _fts_table in ("decisions_fts", "findings_fts", "blockers_fts", "actions_fts"):
                conn.execute(f"DROP TABLE IF EXISTS {_fts_table}")
            conn.executescript(HANDOFF_FTS_SCHEMA_SQL)
            conn.executescript(_HANDOFF_FTS_TRIGGERS_SQL)
            _backfill_handoff_fts(conn)
        else:
            raise


def _ensure_review_findings_unique_index(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_review_findings_task_finding_unique
        ON review_findings(task_ref, finding_id)
        """
    )


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
                review_mode = ?,
                session = ?,
                agent = ?,
                branch = ?,
                commit_sha = ?,
                resolution_notes = ?,
                reopen_count = ?,
                last_reopen_reason = ?,
                last_reopened_at = ?,
                resolved_at = ?,
                verification_evidence = ?,
                created_at = ?,
                updated_at = COALESCE(updated_at, ?)
            WHERE id = ?
            """,
            (
                keep_row["severity"],
                keep_row["file_path"],
                keep_row["line_start"],
                keep_row["line_end"],
                keep_row["description"],
                keep_row["fix"],
                keep_row["status"],
                keep_row["review_mode"],
                keep_row["session"],
                keep_row["agent"],
                keep_row["branch"],
                keep_row["commit_sha"],
                keep_row["resolution_notes"],
                max(reopen_counts) if reopen_counts else 0,
                keep_row["last_reopen_reason"],
                keep_row["last_reopened_at"],
                keep_row["resolved_at"],
                keep_row["verification_evidence"],
                merged_created_at,
                merged_created_at,
                keep_id,
            ),
        )
        ids_to_delete = [int(row["id"]) for row in rows if int(row["id"]) != keep_id]
        for row_id in ids_to_delete:
            conn.execute("DELETE FROM review_findings WHERE id = ?", (row_id,))
            removed_rows += 1
    return removed_rows


def _apply_handoff_migrations(conn: sqlite3.Connection) -> None:
    try:
        needs_backfill = False
        for table in ("decisions", "blockers", "next_actions", "verified_tests", "review_findings"):
            if not _has_column(conn, table, "lane_id"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN lane_id TEXT")
        for column in ("model", "model_label", "reasoning_level"):
            if not _has_column(conn, "decisions", column):
                conn.execute(f"ALTER TABLE decisions ADD COLUMN {column} TEXT")
        for column in ("input_tokens", "output_tokens", "total_tokens"):
            if not _has_column(conn, "decisions", column):
                conn.execute(f"ALTER TABLE decisions ADD COLUMN {column} INTEGER")
        for column, sql in [
            ("resolution_notes", "ALTER TABLE review_findings ADD COLUMN resolution_notes TEXT"),
            ("reopen_count", "ALTER TABLE review_findings ADD COLUMN reopen_count INTEGER NOT NULL DEFAULT 0"),
            ("last_reopen_reason", "ALTER TABLE review_findings ADD COLUMN last_reopen_reason TEXT"),
            ("last_reopened_at", "ALTER TABLE review_findings ADD COLUMN last_reopened_at TEXT"),
            ("updated_at", "ALTER TABLE review_findings ADD COLUMN updated_at TEXT"),
            ("verification_evidence", "ALTER TABLE review_findings ADD COLUMN verification_evidence TEXT"),
            ("review_mode", "ALTER TABLE review_findings ADD COLUMN review_mode TEXT"),
            ("review_run_id", "ALTER TABLE review_findings ADD COLUMN review_run_id TEXT"),
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
        if not _has_column(conn, "lane_messages", "payload_json"):
            conn.execute("ALTER TABLE lane_messages ADD COLUMN payload_json TEXT")
        for column in ("model", "backend", "reasoning_effort"):
            if not _has_column(conn, "worktree_lanes", column):
                conn.execute(f"ALTER TABLE worktree_lanes ADD COLUMN {column} TEXT")
        if not _has_column(conn, "handoff_state", "focus"):
            conn.execute("ALTER TABLE handoff_state ADD COLUMN focus TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS turn_metrics (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                task_ref      TEXT NOT NULL,
                lane_id       TEXT,
                session       TEXT NOT NULL,
                cycle         INTEGER,
                phase         TEXT NOT NULL,
                backend       TEXT NOT NULL,
                model         TEXT,
                thread_id     TEXT,
                turn_id       TEXT,
                input_tokens  INTEGER,
                output_tokens INTEGER,
                cached_input_tokens INTEGER,
                reasoning_output_tokens INTEGER,
                total_tokens  INTEGER,
                usage_source  TEXT
                              CHECK (usage_source IN ('observed', 'tokenizer_estimate', 'char_estimate') OR usage_source IS NULL),
                model_context_window INTEGER,
                prompt_tokens INTEGER,
                prompt_chars  INTEGER,
                prompt_token_source TEXT
                              CHECK (prompt_token_source IN ('observed', 'tokenizer_estimate', 'char_estimate') OR prompt_token_source IS NULL),
                utilization_ratio REAL,
                domain_signal_ratio REAL,
                pressure_level TEXT,
                attribution_json TEXT NOT NULL DEFAULT '{}',
                section_sizes_json TEXT NOT NULL DEFAULT '{}',
                raw_usage_json TEXT,
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        if not _has_index(conn, "turn_metrics", "idx_turn_metrics_task_lane_created"):
            conn.execute(
                "CREATE INDEX idx_turn_metrics_task_lane_created "
                "ON turn_metrics(task_ref, lane_id, created_at DESC, id DESC)"
            )
        if not _has_index(conn, "turn_metrics", "idx_turn_metrics_task_backend_model"):
            conn.execute(
                "CREATE INDEX idx_turn_metrics_task_backend_model "
                "ON turn_metrics(task_ref, backend, model, created_at DESC, id DESC)"
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
        _ensure_handoff_fts(conn)
    except Exception:
        conn.close()
        raise
    return conn


# ---------------------------------------------------------------------------
# Core text utilities
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
# DB utilities
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


def _has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row["name"]) == column_name for row in rows)


def _has_index(conn: sqlite3.Connection, table_name: str, index_name: str) -> bool:
    rows = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
    return any(str(row["name"]) == index_name for row in rows)


def _resolve_task_ref(conn: sqlite3.Connection, task_ref: str | None) -> str:
    if task_ref:
        return task_ref
    row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
    if row is None:
        raise ValueError("No active task in handoff_state. Call set_handoff_state first or pass task_ref explicitly.")
    return str(row["task_ref"])


def _fetch_handoff_rows(conn: sqlite3.Connection, *, table: str, where_sql: str, order_sql: str, limit: int, params: tuple[object, ...]) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM {table} WHERE {where_sql} ORDER BY {order_sql} LIMIT ?", (*params, limit)).fetchall()
    payload = [dict(row) for row in rows]
    if table == "lane_messages":
        return [_decode_lane_message_row_dict(row) for row in payload]
    if table == "turn_metrics":
        return [_decode_turn_metric_row_dict(row) for row in payload]
    return payload


def _paginated_query(
    conn: sqlite3.Connection,
    table: str,
    where_sql: str,
    params: tuple[object, ...],
    limit: int,
    offset: int,
    order_sql: str,
    row_decoder: Callable[[dict], dict] = dict,
) -> tuple[int, list[dict]]:
    """Run a COUNT then a paginated SELECT, returning (total, rows)."""
    total = int(conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {where_sql}", params).fetchone()["count"])
    rows = [
        row_decoder(dict(row))
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    ]
    return total, rows


def _count_task_rows(conn: sqlite3.Connection, task_ref: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in ("blockers", "next_actions", "decisions", "verified_tests", "review_findings", "worktree_lanes", "worker_reports", "lane_messages", "plan_cursors", "turn_metrics"):
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
# Normalization utilities
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


# ---------------------------------------------------------------------------
# Test result utilities
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
        return (
            "Malformed slice-complete id. New writes must use "
            "<author_tag>_slice_complete_<work_ref>_<slug>."
        )
    if "_slice_complete_" in decision and not is_prefixed_slice_complete_decision(decision):
        return (
            "Malformed slice-complete id. Expected "
            "<author_tag>_slice_complete_<work_ref>_<slug>."
        )
    if is_slice_complete_decision(decision) and not _has_structured_slice_summary(str(rationale or "")):
        headings = ", ".join(MANDATORY_SLICE_DECISION_HEADINGS)
        return (
            "slice_complete_* decisions require a structured rationale with non-empty sections for: "
            f"{headings}."
        )
    return None


# ---------------------------------------------------------------------------
# Build write actor
# ---------------------------------------------------------------------------


def build_write_actor(
    agent: str | None = None,
    model: str | None = None,
    model_label: str | None = None,
    reasoning_level: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
    lane_id: str | None = None,
) -> WriteActor:
    actor: WriteActor = {}
    normalized_model = _normalize_optional_text(model)
    normalized_model_label = _normalize_optional_text(model_label) or normalize_model_label(normalized_model)
    normalized_reasoning_level = normalize_reasoning_level(reasoning_level)
    derived_agent = normalize_model_identity(normalized_model_label, normalized_reasoning_level)
    normalized_agent = _normalize_optional_text(agent)
    normalized_branch = _normalize_optional_text(branch)
    normalized_commit_sha = _normalize_optional_text(commit_sha)
    normalized_lane_id = _normalize_optional_text(lane_id)
    if normalized_model is not None:
        actor["model"] = normalized_model
    if normalized_model_label is not None:
        actor["model_label"] = normalized_model_label
    if normalized_reasoning_level is not None:
        actor["reasoning_level"] = normalized_reasoning_level
    if derived_agent is not None:
        actor["agent"] = derived_agent
    elif normalized_agent is not None:
        actor["agent"] = normalized_agent
    if normalized_branch is not None:
        actor["branch"] = normalized_branch
    if normalized_commit_sha is not None:
        actor["commit_sha"] = normalized_commit_sha
    if normalized_lane_id is not None:
        actor["lane_id"] = normalized_lane_id
    return actor


# ---------------------------------------------------------------------------
# Git / env utilities
# ---------------------------------------------------------------------------


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


def _git_is_ancestor(ancestor_sha: str | None, descendant_sha: str | None) -> bool | None:
    normalized_ancestor = _normalize_optional_text(ancestor_sha)
    normalized_descendant = _normalize_optional_text(descendant_sha)
    if normalized_ancestor is None or normalized_descendant is None:
        return None
    if normalized_ancestor == normalized_descendant:
        return True
    try:
        proc = _run_cmd(["git", "merge-base", "--is-ancestor", normalized_ancestor, normalized_descendant])
    except Exception:
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def _classify_commit_relation(reference_sha: str | None, candidate_sha: str | None) -> str:
    normalized_reference = _normalize_optional_text(reference_sha)
    normalized_candidate = _normalize_optional_text(candidate_sha)
    if normalized_reference is None or normalized_candidate is None:
        return "unknown"
    if normalized_reference == normalized_candidate:
        return "same"
    if _git_is_ancestor(normalized_reference, normalized_candidate) is True:
        return "descendant"
    if _git_is_ancestor(normalized_candidate, normalized_reference) is True:
        return "ancestor"
    if _git_is_ancestor(normalized_reference, normalized_candidate) is False:
        return "diverged"
    return "unknown"


def _workspace_git_context() -> dict[str, str | None]:
    # Use the core module's version when available so test monkeypatching is respected.
    import sys as _sys  # noqa: PLC0415
    _core_mod = _sys.modules.get("agent_handoff_mcp.core")
    _detect_fn = getattr(_core_mod, "_detect_git_write_context", None) if _core_mod is not None else None
    if _detect_fn is None:
        _detect_fn = _detect_git_write_context
    branch, commit_sha = _detect_fn()
    return {
        "branch": branch,
        "commit_sha": commit_sha,
    }


# ---------------------------------------------------------------------------
# Review finding helpers
# ---------------------------------------------------------------------------


def _annotate_review_finding(row: dict[str, object], *, workspace_branch: str | None, workspace_commit_sha: str | None) -> dict[str, object]:
    finding = dict(row)
    finding_branch = _normalize_optional_text(finding.get("branch"))
    finding_commit_sha = _normalize_optional_text(finding.get("commit_sha"))
    branch_matches = None
    if finding_branch is not None and workspace_branch is not None:
        branch_matches = finding_branch == workspace_branch
    finding["workspace_branch"] = workspace_branch
    finding["workspace_commit_sha"] = workspace_commit_sha
    finding["workspace_branch_matches"] = branch_matches
    # Use the core module's version when available so test monkeypatching is respected.
    import sys as _sys  # noqa: PLC0415
    _core_mod = _sys.modules.get("agent_handoff_mcp.core")
    _classify_fn = getattr(_core_mod, "_classify_commit_relation", None) if _core_mod is not None else None
    if _classify_fn is None:
        _classify_fn = _classify_commit_relation
    finding["workspace_commit_relation"] = _classify_fn(finding_commit_sha, workspace_commit_sha)
    return finding


def _parse_review_finding_details(details: ReviewFindingDetails | None) -> tuple[int | None, int | None, str | None]:
    if not details:
        return None, None, None
    return details.get("line_start"), details.get("line_end"), details.get("fix")


# ---------------------------------------------------------------------------
# Write actor resolution
# ---------------------------------------------------------------------------


def _resolve_write_actor(
    conn: sqlite3.Connection,
    actor: WriteActor | None,
) -> ResolvedWriteContext:
    explicit_agent = _normalize_optional_text(actor.get("agent")) if actor else None
    explicit_model = _normalize_optional_text(actor.get("model")) if actor else None
    explicit_model_label = (_normalize_optional_text(actor.get("model_label")) if actor else None) or normalize_model_label(explicit_model)
    explicit_reasoning_level = normalize_reasoning_level(actor.get("reasoning_level")) if actor else None
    explicit_identity = normalize_model_identity(explicit_model_label, explicit_reasoning_level)
    explicit_branch = _normalize_optional_text(actor.get("branch")) if actor else None
    explicit_commit = _normalize_optional_text(actor.get("commit_sha")) if actor else None
    explicit_lane = _normalize_optional_text(actor.get("lane_id")) if actor else None
    default_agent = _normalize_optional_text(os.environ.get("AGENT_HANDOFF_DEFAULT_AGENT")) or "codex"
    active = conn.execute("SELECT updated_by, updated_branch, updated_commit_sha FROM handoff_state WHERE id = 1").fetchone()
    active_agent = _normalize_optional_text(active["updated_by"]) if active is not None else None
    active_branch = _normalize_optional_text(active["updated_branch"]) if active is not None else None
    active_commit = _normalize_optional_text(active["updated_commit_sha"]) if active is not None else None
    # Use the core module's version of _detect_git_write_context when available so
    # that test monkeypatching of handoff_core._detect_git_write_context is respected.
    import sys as _sys  # noqa: PLC0415
    _core_mod = _sys.modules.get("agent_handoff_mcp.core")
    _detect_fn = getattr(_core_mod, "_detect_git_write_context", None) if _core_mod is not None else None
    if _detect_fn is None:
        _detect_fn = _detect_git_write_context
    git_branch, git_commit = _detect_fn()
    preferred_git_branch = git_branch if git_branch not in (None, "unknown-branch") else None
    return ResolvedWriteContext(
        agent=explicit_identity or explicit_agent or active_agent or default_agent,
        branch=explicit_branch or preferred_git_branch or active_branch or git_branch,
        commit_sha=explicit_commit or git_commit or active_commit,
        lane_id=explicit_lane,
        model=explicit_model,
        model_label=explicit_model_label,
        reasoning_level=explicit_reasoning_level,
    )


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


# ---------------------------------------------------------------------------
# Archival summary helpers
# ---------------------------------------------------------------------------


def _count_by_value(
    conn: sqlite3.Connection,
    *,
    table: str,
    field: str,
    task_ref: str,
    lane_id: str,
    allowed_values: frozenset[str],
) -> dict[str, int]:
    # This helper intentionally supports only the fixed archival-summary queries below.
    allowed_identifiers = {
        ("review_findings", "status"),
        ("lane_messages", "direction"),
        ("lane_messages", "status"),
    }
    if (table, field) not in allowed_identifiers:
        raise ValueError(f"Unsupported count identifiers: {table}.{field}")
    counts = {value: 0 for value in sorted(allowed_values)}
    rows = conn.execute(
        f"SELECT {field} AS value, COUNT(*) AS count FROM {table} WHERE task_ref = ? AND lane_id = ? GROUP BY {field}",
        (task_ref, lane_id),
    ).fetchall()
    for row in rows:
        value = _normalize_optional_text(row["value"])
        if value is not None and value in counts:
            counts[value] = int(row["count"])
    return counts


class ArchivalSummaryBuilder:
    """Composes archival activity summaries for a single (task_ref, lane_id) pair.

    Combines the five ``_build_archival_*`` helpers into a single object so the
    shared ``(conn, task_ref, lane_id)`` context is passed once instead of being
    threaded through every call.
    """

    def __init__(self, conn: sqlite3.Connection, *, task_ref: str, lane_id: str) -> None:
        self._conn = conn
        self._task_ref = task_ref
        self._lane_id = lane_id

    def decision_summary(self) -> dict[str, object]:
        decisions_total_row = self._conn.execute(
            "SELECT COUNT(*) AS count FROM decisions WHERE task_ref = ? AND lane_id = ?",
            (self._task_ref, self._lane_id),
        ).fetchone()
        latest_decision_row = self._conn.execute(
            """
            SELECT rationale
            FROM decisions
            WHERE task_ref = ? AND lane_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (self._task_ref, self._lane_id),
        ).fetchone()
        return {
            "count": int(decisions_total_row["count"]) if decisions_total_row else 0,
            "latest_rationale_excerpt": _excerpt_text(
                str(latest_decision_row["rationale"]) if latest_decision_row and latest_decision_row["rationale"] is not None else None
            ),
        }

    def report_summary(self) -> dict[str, object]:
        reports_total_row = self._conn.execute(
            "SELECT COUNT(*) AS count FROM worker_reports WHERE task_ref = ? AND lane_id = ?",
            (self._task_ref, self._lane_id),
        ).fetchone()
        latest_report_row = self._conn.execute(
            """
            SELECT merge_ready
            FROM worker_reports
            WHERE task_ref = ? AND lane_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (self._task_ref, self._lane_id),
        ).fetchone()
        return {
            "count": int(reports_total_row["count"]) if reports_total_row else 0,
            "latest_merge_ready": (
                bool(latest_report_row["merge_ready"])
                if latest_report_row is not None and latest_report_row["merge_ready"] is not None
                else None
            ),
        }

    def test_summary(self) -> dict[str, object]:
        tests_summary_row = self._conn.execute(
            """
            SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END), 0) AS passed
            FROM verified_tests
            WHERE task_ref = ? AND lane_id = ?
            """,
            (self._task_ref, self._lane_id),
        ).fetchone()
        tests_total = int(tests_summary_row["total"]) if tests_summary_row else 0
        tests_passed = int(tests_summary_row["passed"]) if tests_summary_row else 0
        return {
            "total": tests_total,
            "passed": tests_passed,
            "pass_rate": round(tests_passed / tests_total, 3) if tests_total else None,
        }

    def message_summary(self) -> dict[str, object]:
        return {
            "counts_by_direction": _count_by_value(
                self._conn,
                table="lane_messages",
                field="direction",
                task_ref=self._task_ref,
                lane_id=self._lane_id,
                allowed_values=LANE_MESSAGE_DIRECTIONS,
            ),
            "counts_by_status": _count_by_value(
                self._conn,
                table="lane_messages",
                field="status",
                task_ref=self._task_ref,
                lane_id=self._lane_id,
                allowed_values=MESSAGE_STATUSES,
            ),
        }

    def lane_activity_summary(self) -> dict[str, object]:
        return {
            "decisions": self.decision_summary(),
            "findings": {
                "counts_by_status": _count_by_value(
                    self._conn,
                    table="review_findings",
                    field="status",
                    task_ref=self._task_ref,
                    lane_id=self._lane_id,
                    allowed_values=REVIEW_FINDING_STATUSES,
                ),
            },
            "reports": self.report_summary(),
            "messages": self.message_summary(),
            "tests": self.test_summary(),
        }


def _build_archival_decision_summary(conn: sqlite3.Connection, *, task_ref: str, lane_id: str) -> dict[str, object]:
    return ArchivalSummaryBuilder(conn, task_ref=task_ref, lane_id=lane_id).decision_summary()


def _build_archival_report_summary(conn: sqlite3.Connection, *, task_ref: str, lane_id: str) -> dict[str, object]:
    return ArchivalSummaryBuilder(conn, task_ref=task_ref, lane_id=lane_id).report_summary()


def _build_archival_test_summary(conn: sqlite3.Connection, *, task_ref: str, lane_id: str) -> dict[str, object]:
    return ArchivalSummaryBuilder(conn, task_ref=task_ref, lane_id=lane_id).test_summary()


def _build_archival_message_summary(conn: sqlite3.Connection, *, task_ref: str, lane_id: str) -> dict[str, object]:
    return ArchivalSummaryBuilder(conn, task_ref=task_ref, lane_id=lane_id).message_summary()


def _build_archival_lane_activity_summary(
    conn: sqlite3.Connection,
    *,
    task_ref: str,
    lane_id: str,
) -> dict[str, object]:
    return ArchivalSummaryBuilder(conn, task_ref=task_ref, lane_id=lane_id).lane_activity_summary()


# ---------------------------------------------------------------------------
# Tool invocation helpers
# ---------------------------------------------------------------------------


def _resolve_awaitable(value: object) -> object:
    if not inspect.isawaitable(value):
        return value

    async def _await_value(awaitable: Awaitable[Any]) -> Any:
        return await awaitable

    awaitable = cast(Awaitable[Any], value)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_await_value(awaitable))
    box: dict[str, object] = {}

    def _runner() -> None:
        try:
            box["value"] = asyncio.run(_await_value(awaitable))
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


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def _collect_task_snapshot(conn: sqlite3.Connection, task_ref: str) -> dict:
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


def _write_current_task_md_from_state(task_ref: str) -> None:
    """Write CURRENT_TASK.md for a task using the internal DB write path."""
    with _get_db_connection() as conn:
        _write_current_task_md_for_task(conn, task_ref)


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


def _render_current_task_md(state: dict) -> str:
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
