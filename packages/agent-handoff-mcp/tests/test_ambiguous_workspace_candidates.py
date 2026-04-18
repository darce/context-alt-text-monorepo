"""AHMCP-33: read paths surface structured candidates on ambiguity.

Closes COLDSTART-H-02. Verifies that:

A. ``_resolve_workspace_handoff_row`` raises
   ``AmbiguousWorkspaceContextError`` (a ``UnresolvedTaskContextError``
   subclass, which is itself a ``ValueError`` subclass, so existing
   write-path catches still match) with a populated ``candidates``
   list when 2+ main-branch tasks coexist with null
   ``target_worktree_path``.

B. ``get_handoff_state(task_ref=None)`` surfaces those candidates in
   the error envelope under ``data.candidates`` with a ``resolution``
   hint, instead of returning a bare error string.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agent_handoff_mcp import (
    RuntimeConfig,
    UnresolvedTaskContextError,
    configure_runtime,
    get_handoff_state,
)
from agent_handoff_mcp.shared_primitives import _resolve_workspace_handoff_row
from agent_handoff_mcp.shared_write_context import AmbiguousWorkspaceContextError


def _configured_conn(tmp_path: Path) -> sqlite3.Connection:
    configure_runtime(RuntimeConfig.for_repo(tmp_path))
    from agent_handoff_mcp.shared_schema import _get_db_connection

    return _get_db_connection().__enter__()


def _insert_row(
    conn: sqlite3.Connection,
    *,
    task_ref: str,
    target_worktree_path: str | None = None,
    target_branch: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO handoff_state (
            task_ref, objective, focus, status, target_branch,
            target_worktree_path, revision, updated_at, updated_by,
            updated_branch, updated_commit_sha
        ) VALUES (?, ?, ?, 'in_progress', ?, ?, 0,
                  datetime('now'), 'tester', 'main', 'abc123')
        """,
        (task_ref, f"obj-{task_ref}", f"focus-{task_ref}", target_branch, target_worktree_path),
    )


def test_resolver_raises_structured_error_with_candidates(tmp_path: Path) -> None:
    conn = _configured_conn(tmp_path)
    try:
        _insert_row(conn, task_ref="MAINT-A", target_branch="main")
        _insert_row(conn, task_ref="MAINT-B", target_branch="main")
        conn.commit()

        with pytest.raises(AmbiguousWorkspaceContextError) as excinfo:
            _resolve_workspace_handoff_row(conn)

        assert isinstance(excinfo.value, UnresolvedTaskContextError)
        assert isinstance(excinfo.value, ValueError)
        task_refs = sorted(c["task_ref"] for c in excinfo.value.candidates)
        assert task_refs == ["MAINT-A", "MAINT-B"]
        sample = next(c for c in excinfo.value.candidates if c["task_ref"] == "MAINT-A")
        assert sample["target_branch"] == "main"
        assert sample["target_worktree_path"] is None
        assert sample["status"] == "in_progress"
    finally:
        conn.close()


def test_get_handoff_state_surfaces_candidates_on_ambiguity(tmp_path: Path) -> None:
    conn = _configured_conn(tmp_path)
    try:
        _insert_row(conn, task_ref="MAINT-A", target_branch="main")
        _insert_row(conn, task_ref="MAINT-B", target_branch="main")
        conn.commit()
    finally:
        conn.close()

    envelope = get_handoff_state()
    assert envelope["ok"] is False
    data = envelope["data"]
    assert "Ambiguous active task" in data["error"]
    assert "candidates" in data
    task_refs = sorted(c["task_ref"] for c in data["candidates"])
    assert task_refs == ["MAINT-A", "MAINT-B"]
    assert "resolution" in data
    assert "task_ref" in data["resolution"]
