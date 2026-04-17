"""Regression tests for E17-11 Slice 3a.

Canonical rule: resolution order for the write surface is
(1) explicit ``task_ref`` → (2) workspace-path lookup via
``_resolve_workspace_handoff_row``. No ``WHERE id = 1`` sentinel
fallback. When resolution fails, ``_resolve_task_ref`` raises
``UnresolvedTaskContextError``; the drift-check guard
``collect_target_context_warnings`` is best-effort and returns ``[]``
(no raise) so legitimate cross-task operations (global finding
lookups, merge) are not rejected.

Covers three guarantees:

A. ``_resolve_workspace_handoff_row`` (``shared_primitives.py``)
   raises "Ambiguous active task" when 2+ rows exist and no
   ``target_worktree_path`` registration matches cwd — the former
   ``id = 1`` bootstrap fallback is removed.

B. ``_resolve_task_ref`` promotes that ambiguity into
   ``UnresolvedTaskContextError`` (a ``ValueError`` subclass), giving
   callers a single canonical exception type.

C. ``collect_target_context_warnings`` does NOT raise on ambiguous
   no-task-ref input — it returns ``[]`` so cross-task ops proceed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import agent_handoff_mcp
from agent_handoff_mcp import RuntimeConfig, configure_runtime
from agent_handoff_mcp.core import ResolvedWriteContext
from agent_handoff_mcp.shared_primitives import _resolve_workspace_handoff_row
from agent_handoff_mcp.shared_write_context import collect_target_context_warnings


def _configured_conn(tmp_path: Path) -> sqlite3.Connection:
    """Return a db connection for a runtime rooted at ``tmp_path``."""
    configure_runtime(RuntimeConfig.for_repo(tmp_path))
    from agent_handoff_mcp._shared import _get_db_connection

    return _get_db_connection().__enter__()


def _insert_handoff_row(
    conn: sqlite3.Connection,
    *,
    task_ref: str,
    id_value: int | None,
    target_worktree_path: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO handoff_state (
            id, task_ref, objective, focus, status, target_branch,
            target_worktree_path, revision, updated_at, updated_by,
            updated_branch, updated_commit_sha
        ) VALUES (?, ?, ?, ?, 'in_progress', NULL, ?, 0,
                  datetime('now'), 'tester', 'feature/x', 'abc123')
        """,
        (id_value, task_ref, f"obj-{task_ref}", f"focus-{task_ref}", target_worktree_path),
    )


def test_unresolved_task_context_error_exported_from_package_root() -> None:
    """The exception class must be importable from the package root."""
    assert hasattr(agent_handoff_mcp, "UnresolvedTaskContextError")
    from agent_handoff_mcp import UnresolvedTaskContextError

    assert issubclass(UnresolvedTaskContextError, ValueError)


def test_guard_returns_empty_when_no_task_ref_and_no_workspace_match(
    tmp_path: Path,
) -> None:
    """Drift-check guard tolerates ambiguous no-task-ref input.

    Two rows, neither with a cwd-matching ``target_worktree_path``.
    The guard delegates to ``_resolve_workspace_handoff_row`` which
    raises ambiguity; the guard swallows the raise and returns ``[]``
    so cross-task operations (e.g. global finding lookup) proceed.
    The fail-closed contract lives in ``_resolve_task_ref`` instead.
    """
    conn = _configured_conn(tmp_path)
    try:
        _insert_handoff_row(
            conn,
            task_ref="T1",
            id_value=None,
            target_worktree_path="/nonexistent/path/one",
        )
        _insert_handoff_row(
            conn,
            task_ref="T2",
            id_value=None,
            target_worktree_path="/nonexistent/path/two",
        )
        conn.commit()
        ctx = ResolvedWriteContext(
            agent="tester",
            model=None,
            model_label=None,
            reasoning_level=None,
            branch="feature/x",
            commit_sha="abc123",
            lane_id=None,
        )
        assert collect_target_context_warnings(conn, ctx) == []
    finally:
        conn.close()


def test_resolve_task_ref_raises_unresolved_on_ambiguity(
    tmp_path: Path,
) -> None:
    """``_resolve_task_ref`` is the fail-closed seam for writers.

    Previously the bootstrap sentinel in
    ``_resolve_workspace_handoff_row`` returned the ``id = 1`` row
    whenever no ``target_worktree_path`` registrations existed. That
    path is removed; with 2+ rows the resolver raises "Ambiguous
    active task", and ``_resolve_task_ref`` promotes that to the
    canonical ``UnresolvedTaskContextError`` (a ``ValueError``
    subclass).
    """
    from agent_handoff_mcp import UnresolvedTaskContextError
    from agent_handoff_mcp.shared_primitives import _resolve_task_ref

    conn = _configured_conn(tmp_path)
    try:
        _insert_handoff_row(conn, task_ref="T1", id_value=1, target_worktree_path=None)
        _insert_handoff_row(conn, task_ref="T2", id_value=None, target_worktree_path=None)
        conn.commit()
        with pytest.raises(UnresolvedTaskContextError, match="Ambiguous active task"):
            _resolve_task_ref(conn, None)
        # Underlying resolver still raises bare ValueError (subclass check).
        with pytest.raises(ValueError, match="Ambiguous active task"):
            _resolve_workspace_handoff_row(conn)
    finally:
        conn.close()
