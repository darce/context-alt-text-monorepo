"""TDD coverage for the repository-local linked-worktree reaper."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "worktree_reap.py"


def _load_reaper() -> Any:
    spec = importlib.util.spec_from_file_location("worktree_reap_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


reaper = _load_reaper()


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _commit(repo: Path, message: str, filename: str, contents: str) -> None:
    (repo / filename).write_text(contents)
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> dict[str, Any]:
    """Build a root worktree plus redundant, live, and dirty linked worktrees."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "worktree-reap@example.test")
    _git(repo, "config", "user.name", "Worktree Reap Test")
    _commit(repo, "initial", "README", "initial\n")

    # Keep the parent branch in the root worktree.  That makes it ROOT rather
    # than an accidental REDUNDANT candidate when the fixture is applied.
    _git(repo, "switch", "-c", "feature/parent")
    _commit(repo, "parent patch", "parent.txt", "parent\n")

    paths: dict[str, Path] = {}

    _git(repo, "branch", "feature/parent-ancestor")
    paths["ancestor"] = repo.parent / "ancestor"
    _git(repo, "worktree", "add", str(paths["ancestor"]), "feature/parent-ancestor")

    _git(repo, "branch", "feature/parent-live")
    paths["live"] = repo.parent / "live"
    _git(repo, "worktree", "add", str(paths["live"]), "feature/parent-live")
    _commit(paths["live"], "live patch", "live.txt", "live\n")

    _git(repo, "branch", "feature/parent-dirty")
    paths["dirty"] = repo.parent / "dirty"
    _git(repo, "worktree", "add", str(paths["dirty"]), "feature/parent-dirty")
    (paths["dirty"] / "untracked.txt").write_text("keep me\n")

    # review/x has no feature/x parent in this fixture, so it maps to main.
    _git(repo, "branch", "review/x", "main")
    paths["review"] = repo.parent / "review-x"
    _git(repo, "worktree", "add", str(paths["review"]), "review/x")

    # The rebased branch has the same patch as feature/parent but a different
    # commit SHA, so merge-base is false while git cherry reports '-'.
    _git(repo, "branch", "feature/parent-rebased", "main")
    paths["rebased"] = repo.parent / "rebased"
    _git(repo, "worktree", "add", str(paths["rebased"]), "feature/parent-rebased")
    _commit(paths["rebased"], "rebased patch", "parent.txt", "parent\n")

    _git(repo, "branch", "misc/live", "main")
    paths["orphan"] = repo.parent / "orphan"
    _git(repo, "worktree", "add", str(paths["orphan"]), "misc/live")
    _commit(paths["orphan"], "orphan patch", "orphan.txt", "orphan\n")

    return {"repo": repo, "paths": paths}


def test_parent_of_is_pure_and_uses_existing_parent_branches() -> None:
    assert reaper.parent_of("feature/parent-sub", {"main", "feature/parent"}) == "feature/parent"
    assert reaper.parent_of("feature/parent-sub", {"main"}) == "main"
    assert reaper.parent_of("review/x", {"main", "feature/x"}) == "feature/x"
    assert reaper.parent_of("review/x", {"main"}) == "main"
    assert reaper.parent_of("misc/live", {"main", "feature/parent"}) == "main"


def test_classify_covers_redundant_live_dirty_and_root(fixture_repo: dict[str, Any]) -> None:
    records = reaper.classify(fixture_repo["repo"])
    by_branch = {record.branch: record for record in records}

    assert by_branch["feature/parent"].status == "ROOT"
    assert by_branch["feature/parent-ancestor"].status == "REDUNDANT"
    assert by_branch["feature/parent-live"].status == "LIVE"
    assert by_branch["feature/parent-dirty"].status == "DIRTY"
    assert by_branch["review/x"].status == "REDUNDANT"
    assert by_branch["feature/parent-rebased"].status == "REDUNDANT"
    assert by_branch["misc/live"].status == "LIVE"
    assert by_branch["review/x"].parent == "main"

    # Mutation check: removing the git cherry fallback from is_merged must
    # make the rebased same-patch case above fail.
    assert reaper.is_merged(
        fixture_repo["repo"], "feature/parent-rebased", "feature/parent"
    )


def test_apply_removes_only_redundant_and_is_idempotent(
    fixture_repo: dict[str, Any],
) -> None:
    repo = fixture_repo["repo"]
    paths = fixture_repo["paths"]
    records = reaper.classify(repo)

    preview = reaper.apply(records, dry_run=True)
    assert preview["removed"] == []
    assert {Path(path).resolve() for path in preview["skipped"]} == {
        repo.resolve(),
        paths["ancestor"].resolve(),
        paths["live"].resolve(),
        paths["dirty"].resolve(),
        paths["review"].resolve(),
        paths["rebased"].resolve(),
        paths["orphan"].resolve(),
    }

    result = reaper.apply(records, dry_run=False)
    assert {Path(path).resolve() for path in result["removed"]} == {
        paths["ancestor"].resolve(),
        paths["review"].resolve(),
        paths["rebased"].resolve(),
    }
    assert result["errors"] == []

    remaining = {record.branch: record for record in reaper.classify(repo)}
    assert set(remaining) == {"feature/parent", "feature/parent-live", "feature/parent-dirty", "misc/live"}
    assert paths["live"].exists()
    assert paths["dirty"].exists()
    assert paths["orphan"].exists()
    assert _git(repo, "show-ref", "--verify", "refs/heads/feature/parent-ancestor", check=False).returncode != 0
    assert _git(repo, "show-ref", "--verify", "refs/heads/review/x", check=False).returncode != 0
    assert _git(repo, "show-ref", "--verify", "refs/heads/feature/parent-rebased", check=False).returncode != 0

    # Reusing the original records is an idempotent retry, not an error.
    retry = reaper.apply(records, dry_run=False)
    assert retry["removed"] == []
    assert retry["errors"] == []


def test_apply_refuses_root_and_current_worktree(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = fixture_repo["repo"]
    root_record = reaper.WorktreeRecord(
        path=repo,
        branch="feature/parent",
        parent="main",
        status="REDUNDANT",
        reason="synthetic safety check",
        repo=repo,
    )
    with pytest.raises(RuntimeError, match="root worktree"):
        reaper.apply([root_record], dry_run=False)

    current = repo.parent / "current"
    _git(repo, "branch", "feature/current", "main")
    _git(repo, "worktree", "add", str(current), "feature/current")
    monkeypatch.chdir(current)
    current_record = next(
        record for record in reaper.classify(repo) if record.branch == "feature/current"
    )
    with pytest.raises(RuntimeError, match="current worktree"):
        reaper.apply([current_record], dry_run=False)


def test_json_cli_emits_full_records_and_dry_run_exit_code(
    fixture_repo: dict[str, Any],
) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--repo", str(fixture_repo["repo"]), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert {row["status"] for row in payload} >= {"REDUNDANT", "LIVE", "DIRTY"}


def test_json_cli_on_root_only_repo_is_an_empty_list(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "worktree-reap@example.test")
    _git(repo, "config", "user.name", "Worktree Reap Test")
    _commit(repo, "initial", "README", "initial\n")

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--repo", str(repo), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == []
