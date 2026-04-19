"""Regression tests for MAINT-* target_worktree_path defaulting.

Contract: `_default_maint_target_worktree_path` backfills the active task's
`target_worktree_path` to the current workspace root when all of:
  - task_ref starts with 'MAINT-'
  - caller did not pass target_worktree_path explicitly
  - either target_branch or the actor branch is main/master

Rationale: maintenance patches on main need a concrete target_worktree_path so
the E17-11 task resolver (which disambiguates overlapping task scopes by
workspace path) does not surface ambiguity errors for routine main-branch
cleanup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_handoff_mcp import RuntimeConfig, configure_runtime, set_handoff_state
from agent_handoff_mcp.handoff_state import _default_maint_target_worktree_path


def _setup(tmp_path: Path) -> str:
    configure_runtime(RuntimeConfig.for_repo(tmp_path))
    # _workspace_root() resolves the configured workspace; stringify for compare.
    from agent_handoff_mcp.shared_primitives import _workspace_root

    return str(_workspace_root())


def test_maint_on_main_defaults_to_workspace_root(tmp_path: Path) -> None:
    ws = _setup(tmp_path)
    got = _default_maint_target_worktree_path(
        task_ref="MAINT-foo",
        target_branch="main",
        target_worktree_path=None,
        actor_branch="main",
    )
    assert got == ws


def test_maint_on_master_defaults_to_workspace_root(tmp_path: Path) -> None:
    ws = _setup(tmp_path)
    got = _default_maint_target_worktree_path(
        task_ref="MAINT-bar",
        target_branch="master",
        target_worktree_path=None,
        actor_branch=None,
    )
    assert got == ws


def test_explicit_target_worktree_path_wins(tmp_path: Path) -> None:
    _setup(tmp_path)
    got = _default_maint_target_worktree_path(
        task_ref="MAINT-explicit",
        target_branch="main",
        target_worktree_path="/opt/somewhere/else",
        actor_branch="main",
    )
    assert got == "/opt/somewhere/else"


def test_non_main_branch_does_not_default(tmp_path: Path) -> None:
    _setup(tmp_path)
    got = _default_maint_target_worktree_path(
        task_ref="MAINT-featurewip",
        target_branch="feature/xyz",
        target_worktree_path=None,
        actor_branch="feature/xyz",
    )
    assert got is None


def test_non_maint_task_does_not_default(tmp_path: Path) -> None:
    _setup(tmp_path)
    got = _default_maint_target_worktree_path(
        task_ref="AHMCP-99",
        target_branch="main",
        target_worktree_path=None,
        actor_branch="main",
    )
    assert got is None


def test_maint_with_actor_branch_main_only_still_defaults(tmp_path: Path) -> None:
    ws = _setup(tmp_path)
    got = _default_maint_target_worktree_path(
        task_ref="MAINT-actor",
        target_branch=None,
        target_worktree_path=None,
        actor_branch="main",
    )
    assert got == ws


def test_maint_without_branch_info_does_not_default(tmp_path: Path) -> None:
    _setup(tmp_path)
    got = _default_maint_target_worktree_path(
        task_ref="MAINT-nobranch",
        target_branch=None,
        target_worktree_path=None,
        actor_branch=None,
    )
    assert got is None


def test_set_handoff_state_persists_defaulted_path(tmp_path: Path) -> None:
    """End-to-end: set_handoff_state for a MAINT task on main backfills the column."""
    ws = _setup(tmp_path)
    result = set_handoff_state(
        task_ref="MAINT-e2e",
        objective="test default backfill",
        status="in_progress",
        target_branch="main",
    )
    assert result["ok"] is True, result

    from agent_handoff_mcp.shared_schema import _get_db_connection

    with _get_db_connection() as conn:
        row = conn.execute(
            "SELECT target_worktree_path FROM handoff_state WHERE task_ref = ?",
            ("MAINT-e2e",),
        ).fetchone()
    assert row is not None
    assert row["target_worktree_path"] == ws


def test_set_handoff_state_non_maint_leaves_path_null(tmp_path: Path) -> None:
    _setup(tmp_path)
    result = set_handoff_state(
        task_ref="AHMCP-99",
        objective="no-default",
        status="in_progress",
        target_branch="main",
    )
    assert result["ok"] is True, result

    from agent_handoff_mcp.shared_schema import _get_db_connection

    with _get_db_connection() as conn:
        row = conn.execute(
            "SELECT target_worktree_path FROM handoff_state WHERE task_ref = ?",
            ("AHMCP-99",),
        ).fetchone()
    assert row is not None
    assert row["target_worktree_path"] is None
