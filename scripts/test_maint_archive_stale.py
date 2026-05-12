"""Integration tests for `scripts/maint_archive_stale.py`.

The script archives stale `MAINT-*` handoff rows so that cwd-resolution
stays unambiguous for cold-start `/branch-review` (and other ad-hoc
skills) on the `main` branch. A row is "stale" if:

* its status is in `{done, review}`, OR
* its status is in `{in_progress, blocked}` but its
  `target_worktree_path` is set, distinct from the repo root, and the
  path no longer exists on disk (the linked worktree was removed
  without first archiving the row — the dominant leak source).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_SRC = REPO_ROOT / "packages" / "agent-handoff-mcp" / "src"
if str(HANDOFF_SRC) not in sys.path:
    sys.path.insert(0, str(HANDOFF_SRC))

# The SHA validator otherwise tries to resolve synthetic commit SHAs
# against the real git repo. Match the package's own conftest pattern.
os.environ.setdefault("AGENT_HANDOFF_SKIP_SHA_VALIDATION", "1")
os.environ.setdefault("AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT", "1")
os.environ.setdefault("AGENT_HANDOFF_SKIP_WORKTREE_DERIVATION", "1")


def _load_script_module():
    script_path = REPO_ROOT / "scripts" / "maint_archive_stale.py"
    spec = importlib.util.spec_from_file_location(
        "maint_archive_stale_under_test", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["maint_archive_stale_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def isolated_runtime(tmp_path: Path) -> dict[str, Any]:
    from agent_handoff_mcp import (  # noqa: PLC0415
        RuntimeConfig,
        configure_runtime,
        set_handoff_state,
        update_task_status,
    )

    state_dir = tmp_path / ".task-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=state_dir,
        current_task_path=tmp_path / "CURRENT_TASK.json",
        dashboard_path=tmp_path / "DASHBOARD.txt",
    )
    configure_runtime(runtime)

    set_handoff_state(
        task_ref="MAINT-STALE-DONE-1",
        objective="Stale done maintenance task",
        status="in_progress",
        target_branch="main",
    )
    update_task_status(
        task_ref="MAINT-STALE-DONE-1", status="done", expected_revision=0
    )

    set_handoff_state(
        task_ref="MAINT-LIVE-1",
        objective="Live in-progress maintenance task",
        status="in_progress",
        target_branch="main",
    )

    set_handoff_state(
        task_ref="E17-42",
        objective="Non-MAINT done task that must stay put",
        status="in_progress",
        target_branch="feature/e17-42",
    )
    update_task_status(task_ref="E17-42", status="done", expected_revision=0)

    return {"runtime": runtime, "tmp_path": tmp_path}


def test_list_active_tasks_api_returns_all_three_rows(
    isolated_runtime: dict[str, Any],
) -> None:
    """Public API prerequisite: we need to enumerate active tasks without raw sqlite."""
    from agent_handoff_mcp import list_active_tasks  # noqa: PLC0415

    result = list_active_tasks()
    refs = {row["task_ref"] for row in result}
    assert refs == {"MAINT-STALE-DONE-1", "MAINT-LIVE-1", "E17-42"}
    by_ref = {row["task_ref"]: row for row in result}
    assert by_ref["MAINT-STALE-DONE-1"]["status"] == "done"
    assert by_ref["MAINT-LIVE-1"]["status"] == "in_progress"
    assert by_ref["E17-42"]["status"] == "done"


def test_collect_stale_maint_returns_only_done_or_review_maint_rows(
    isolated_runtime: dict[str, Any],
) -> None:
    mod = _load_script_module()

    stale = mod.collect_stale_maint()
    refs = {row["task_ref"] for row in stale}

    # Only the MAINT-* row with status=done qualifies.
    assert refs == {"MAINT-STALE-DONE-1"}


def test_archive_stale_maint_archives_done_leaves_live_and_non_maint(
    isolated_runtime: dict[str, Any],
) -> None:
    from agent_handoff_mcp import get_archived_task, list_active_tasks  # noqa: PLC0415

    mod = _load_script_module()

    archived = mod.archive_stale_maint(yes=True)

    assert [row["task_ref"] for row in archived] == ["MAINT-STALE-DONE-1"]

    remaining_refs = {row["task_ref"] for row in list_active_tasks()}
    assert "MAINT-STALE-DONE-1" not in remaining_refs
    assert "MAINT-LIVE-1" in remaining_refs
    # Non-MAINT done tasks are NOT touched by this tool — archival of
    # feature-branch tasks is already handled by `make task-finish`.
    assert "E17-42" in remaining_refs

    # The archived row is now retrievable from the archive table.
    archived_row = get_archived_task(task_ref="MAINT-STALE-DONE-1")
    assert archived_row["ok"] is True


def test_dry_run_reports_without_mutating(isolated_runtime: dict[str, Any]) -> None:
    from agent_handoff_mcp import list_active_tasks  # noqa: PLC0415

    mod = _load_script_module()

    preview = mod.archive_stale_maint(yes=True, dry_run=True)
    assert [row["task_ref"] for row in preview] == ["MAINT-STALE-DONE-1"]

    # State unchanged.
    refs = {row["task_ref"] for row in list_active_tasks()}
    assert "MAINT-STALE-DONE-1" in refs


@pytest.fixture()
def missing_worktree_runtime(tmp_path: Path) -> dict[str, Any]:
    """Same shape as ``isolated_runtime`` but seeds rows exercising the missing-worktree rule.

    Rows seeded:

    * ``MAINT-MISSING-WT`` — status=in_progress, ``target_worktree_path``
      points to a nonexistent sibling of ``tmp_path``. Should be swept.
    * ``MAINT-LIVE-EXISTING-WT`` — status=in_progress,
      ``target_worktree_path`` set to ``tmp_path`` itself (exists).
      Should NOT be swept.
    * ``MAINT-REPO-ROOT`` — status=in_progress, no
      ``target_worktree_path`` (the row resolves to the runtime repo
      root). Should NOT be swept; a live row registered against the
      repo root is treated as potentially active.
    """
    from agent_handoff_mcp import (  # noqa: PLC0415
        RuntimeConfig,
        configure_runtime,
        set_handoff_state,
    )

    state_dir = tmp_path / ".task-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=state_dir,
        current_task_path=tmp_path / "CURRENT_TASK.json",
        dashboard_path=tmp_path / "DASHBOARD.txt",
    )
    configure_runtime(runtime)

    missing_path = tmp_path.parent / f"{tmp_path.name}-missing-worktree"
    assert not missing_path.exists()

    set_handoff_state(
        task_ref="MAINT-MISSING-WT",
        objective="MAINT row whose linked worktree was removed.",
        status="in_progress",
        target_branch="feature/maint-missing-wt",
        target_worktree_path=str(missing_path),
    )

    set_handoff_state(
        task_ref="MAINT-LIVE-EXISTING-WT",
        objective="MAINT row whose linked worktree still exists.",
        status="in_progress",
        target_branch="feature/maint-live-existing",
        target_worktree_path=str(tmp_path),
    )

    set_handoff_state(
        task_ref="MAINT-REPO-ROOT",
        objective="MAINT row registered against the repo root.",
        status="in_progress",
        target_branch="main",
    )

    return {
        "runtime": runtime,
        "tmp_path": tmp_path,
        "missing_path": missing_path,
    }


def test_collect_stale_maint_includes_missing_worktree_in_progress_row(
    missing_worktree_runtime: dict[str, Any],
) -> None:
    mod = _load_script_module()

    stale = mod.collect_stale_maint()
    refs = {row["task_ref"] for row in stale}

    # Only the in_progress MAINT row whose worktree path is missing on
    # disk is reported stale. The same-cwd-as-repo-root row and the
    # row whose worktree still exists are both treated as live.
    assert refs == {"MAINT-MISSING-WT"}


def test_is_missing_worktree_predicate_distinguishes_cases(
    missing_worktree_runtime: dict[str, Any],
) -> None:
    mod = _load_script_module()
    tmp_path = missing_worktree_runtime["tmp_path"]
    missing_path = missing_worktree_runtime["missing_path"]

    # Path is set + does not exist + is not the repo root → True.
    assert mod._is_missing_worktree(
        {"target_worktree_path": str(missing_path)}
    ) is True

    # Path is set + exists → False (worktree present, row may be live).
    assert mod._is_missing_worktree(
        {"target_worktree_path": str(tmp_path)}
    ) is False

    # Path equals the runtime repo root → False (registered against root).
    assert mod._is_missing_worktree(
        {"target_worktree_path": str(tmp_path)}
    ) is False

    # No target_worktree_path → False.
    assert mod._is_missing_worktree({"target_worktree_path": ""}) is False
    assert mod._is_missing_worktree({}) is False


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def real_git_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """tmp_path is a fully initialised git repo on `main`; worktree-derivation is enabled.

    Required for end-to-end scaffolding tests because
    ``_archive_with_scaffold`` runs real ``git worktree add`` against
    the runtime repo root and then calls ``archive_task_state`` without
    the SKIP_WORKTREE_DERIVATION bypass.
    """
    monkeypatch.delenv("AGENT_HANDOFF_SKIP_WORKTREE_DERIVATION", raising=False)

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git("init", "--initial-branch=main", cwd=repo_root)
    _git("config", "user.email", "test@example.com", cwd=repo_root)
    _git("config", "user.name", "Test", cwd=repo_root)
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo_root)
    _git("commit", "-m", "seed", cwd=repo_root)

    from agent_handoff_mcp import (  # noqa: PLC0415
        RuntimeConfig,
        configure_runtime,
        set_handoff_state,
    )

    state_dir = repo_root / ".task-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    runtime = RuntimeConfig.for_workspace(
        repo_root,
        state_dir=state_dir,
        current_task_path=repo_root / "CURRENT_TASK.json",
        dashboard_path=repo_root / "DASHBOARD.txt",
    )
    configure_runtime(runtime)

    missing_path = tmp_path / "missing-worktree"
    assert not missing_path.exists()

    set_handoff_state(
        task_ref="MAINT-MISSING-WT-E2E",
        objective="MAINT row with missing worktree, archived via scaffolding.",
        status="in_progress",
        target_branch="feature/maint-missing-wt-e2e",
        target_worktree_path=str(missing_path),
    )

    return {
        "runtime": runtime,
        "repo_root": repo_root,
        "missing_path": missing_path,
    }


def test_archive_stale_maint_scaffolds_then_archives_missing_worktree_row(
    real_git_runtime: dict[str, Any],
) -> None:
    """End-to-end: scaffold the missing branch+worktree, archive, tear down.

    Verifies the production sweep path works against a real git repo
    without leaking scaffold worktrees or branches.
    """
    from agent_handoff_mcp import get_archived_task, list_active_tasks  # noqa: PLC0415

    mod = _load_script_module()
    repo_root = real_git_runtime["repo_root"]

    # Patch REPO_ROOT so the script's git ops target the test repo.
    original_repo_root = mod.REPO_ROOT
    mod.REPO_ROOT = repo_root
    try:
        archived = mod.archive_stale_maint(yes=True)
    finally:
        mod.REPO_ROOT = original_repo_root

    assert [row["task_ref"] for row in archived] == ["MAINT-MISSING-WT-E2E"]

    remaining_refs = {row["task_ref"] for row in list_active_tasks()}
    assert "MAINT-MISSING-WT-E2E" not in remaining_refs

    archived_row = get_archived_task(task_ref="MAINT-MISSING-WT-E2E")
    assert archived_row["ok"] is True

    # Scaffold cleanup: the branch we recreated should be gone again.
    branch_check = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet",
         "feature/maint-missing-wt-e2e"],
        capture_output=True,
        check=False,
    )
    assert branch_check.returncode != 0, "scaffold branch was not torn down"

    # Scaffold cleanup: no maint-archive-scaffold-* dirs remain in TMPDIR.
    import tempfile  # noqa: PLC0415

    leftover = list(Path(tempfile.gettempdir()).glob("maint-archive-scaffold-*"))
    assert leftover == [], f"scaffold tempdirs leaked: {leftover}"
