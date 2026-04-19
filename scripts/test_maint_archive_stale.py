"""Integration tests for `scripts/maint_archive_stale.py`.

The script archives stale `MAINT-*` handoff rows so that cwd-resolution
stays unambiguous for cold-start `/branch-review` (and other ad-hoc
skills) on the `main` branch. A "stale" row is one whose status is in
`{done, review}`. Rows in any other status (notably `in_progress`) stay
put, regardless of age.
"""

from __future__ import annotations

import importlib.util
import os
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
