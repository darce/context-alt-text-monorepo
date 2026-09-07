"""TDD coverage for the repository-local linked-worktree reaper."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import replace
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


@pytest.fixture(autouse=True)
def _no_active_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    """No lane owns a throwaway fixture repo unless a test says otherwise.

    Without this the default probe reads the real lane registry, which makes
    every classification depend on the developer's live handoff database.
    """
    monkeypatch.setattr(reaper, "active_lane_paths", lambda repo: {})


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
    (repo / ".gitignore").write_text("ignored/\n.venv/\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "ignore test files")

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

    _git(repo, "branch", "feature/parent-ignored")
    paths["ignored"] = repo.parent / "ignored"
    _git(repo, "worktree", "add", str(paths["ignored"]), "feature/parent-ignored")
    (paths["ignored"] / ".venv").mkdir()
    (paths["ignored"] / ".venv" / "keep.txt").write_text("keep ignored data\n")

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
    assert by_branch["feature/parent-ignored"].status == "DIRTY"
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
        paths["ignored"].resolve(),
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
    assert set(remaining) == {
        "feature/parent",
        "feature/parent-live",
        "feature/parent-dirty",
        "feature/parent-ignored",
        "misc/live",
    }
    assert paths["live"].exists()
    assert paths["dirty"].exists()
    assert paths["ignored"].exists()
    assert (paths["ignored"] / ".venv" / "keep.txt").read_text() == "keep ignored data\n"
    assert paths["orphan"].exists()
    assert _git(repo, "show-ref", "--verify", "refs/heads/feature/parent-ancestor", check=False).returncode != 0
    assert _git(repo, "show-ref", "--verify", "refs/heads/review/x", check=False).returncode != 0
    assert _git(repo, "show-ref", "--verify", "refs/heads/feature/parent-rebased", check=False).returncode != 0

    # Reusing the original records is an idempotent retry, not an error.
    retry = reaper.apply(records, dry_run=False)
    assert retry["removed"] == []
    assert retry["errors"] == []


def test_apply_skips_a_protected_redundant_record(fixture_repo: dict[str, Any]) -> None:
    repo = fixture_repo["repo"]
    record = next(
        item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor"
    )
    protected = replace(record, protected=True)

    result = reaper.apply([protected], dry_run=False)

    assert result == {"removed": [], "skipped": [str(record.path)], "errors": []}
    assert record.path.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode == 0


def test_protect_accepts_branch_and_path_forms(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = fixture_repo["repo"]
    review_path = fixture_repo["paths"]["review"]
    monkeypatch.delenv("REAP_STRICT", raising=False)

    for value in ("review/x", str(review_path)):
        record = next(item for item in reaper.classify(repo, protected={value}) if item.branch == "review/x")
        assert record.status == "LIVE"
        assert record.reason == "protected by caller"
        assert record.protected is True
        assert (
            reaper.main(["--repo", str(repo), "--check", "--protect", value])
            == 0
        )


def test_ignored_only_content_requires_explicit_opt_in(
    fixture_repo: dict[str, Any],
) -> None:
    repo = fixture_repo["repo"]
    ignored_path = fixture_repo["paths"]["ignored"]

    default_record = next(
        item for item in reaper.classify(repo) if item.branch == "feature/parent-ignored"
    )
    assert default_record.status == "DIRTY"
    assert reaper.is_dirty(ignored_path) is False

    allowed_record = next(
        item
        for item in reaper.classify(repo, allow_ignored=True)
        if item.branch == "feature/parent-ignored"
    )
    assert allowed_record.status == "REDUNDANT"
    assert allowed_record.allow_ignored is True

    result = reaper.apply([allowed_record], dry_run=False)

    assert result["errors"] == []
    assert result["removed"] == [str(ignored_path.resolve())]
    assert not ignored_path.exists()


def test_regenerable_ignored_content_does_not_make_landed_worktree_dirty(
    fixture_repo: dict[str, Any],
) -> None:
    repo = fixture_repo["repo"]
    target = fixture_repo["paths"]["ancestor"]
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_text(
        exclude.read_text()
        + "\n.pytest_cache/\n__pycache__/\n.ruff_cache/\n.mypy_cache/\n"
        + ".task-state/\n"
    )
    for relative in (
        ".pytest_cache/state",
        "src/__pycache__/module.pyc",
        ".ruff_cache/state",
        ".mypy_cache/state",
        ".task-state/.heartbeat/pulse",
    ):
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("regenerable\n")

    record = next(
        item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor"
    )

    assert record.status == "REDUNDANT"
    result = reaper.apply([record], dry_run=False)

    assert result["errors"] == []
    assert result["removed"] == [str(target.resolve())]
    assert not target.exists()


def test_apply_rechecks_ignored_content_created_after_classification(
    fixture_repo: dict[str, Any],
) -> None:
    repo = fixture_repo["repo"]
    target = fixture_repo["paths"]["ancestor"]
    record = next(item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor")
    (target / ".venv").mkdir()
    (target / ".venv" / ".venv-marker").write_text("keep me\n")

    result = reaper.apply([record], dry_run=False)

    assert result["removed"] == []
    assert result["errors"]
    assert target.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode == 0


def test_apply_rechecks_cleanliness_after_recording_intent(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = fixture_repo["repo"]
    target = fixture_repo["paths"]["ancestor"]
    record = next(item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor")
    original_write_intent = reaper._write_intent
    created = False

    def create_ignored_after_intent(
        git_repo: Path,
        intent_record: reaper.WorktreeRecord,
        intent_target: Path,
        phase: str,
    ) -> str | None:
        nonlocal created
        error = original_write_intent(git_repo, intent_record, intent_target, phase)
        if not created and phase == "prepared":
            created = True
            (target / ".venv").mkdir()
            (target / ".venv" / "late-marker").write_text("keep me\n")
        return error

    monkeypatch.setattr(reaper, "_write_intent", create_ignored_after_intent)
    result = reaper.apply([record], dry_run=False)

    assert result["removed"] == []
    assert result["errors"]
    assert target.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode == 0


def test_apply_rechecks_branch_binding_after_recording_intent(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = fixture_repo["repo"]
    target = fixture_repo["paths"]["ancestor"]
    record = next(item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor")
    original_write_intent = reaper._write_intent
    advanced = False

    def advance_branch_after_intent(
        git_repo: Path,
        intent_record: reaper.WorktreeRecord,
        intent_target: Path,
        phase: str,
    ) -> str | None:
        nonlocal advanced
        error = original_write_intent(git_repo, intent_record, intent_target, phase)
        if not advanced and phase == "prepared":
            advanced = True
            _commit(target, "advance branch after intent", "late.txt", "late\n")
        return error

    monkeypatch.setattr(reaper, "_write_intent", advance_branch_after_intent)
    result = reaper.apply([record], dry_run=False)

    assert result["removed"] == []
    assert result["errors"]
    assert target.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode == 0


def test_apply_refuses_parent_tip_change_before_removing_worktree(
    fixture_repo: dict[str, Any],
) -> None:
    repo = fixture_repo["repo"]
    target = fixture_repo["paths"]["ancestor"]
    record = next(item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor")
    _commit(repo, "move landing parent", "parent-moved.txt", "moved\n")

    result = reaper.apply([record], dry_run=False)

    assert result["removed"] == []
    assert result["errors"]
    assert target.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode == 0


def test_apply_refuses_when_branch_tip_advances_between_classify_and_apply(
    fixture_repo: dict[str, Any],
) -> None:
    repo = fixture_repo["repo"]
    target = fixture_repo["paths"]["ancestor"]
    record = next(item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor")
    _commit(target, "advance classified branch", "advanced.txt", "advanced\n")

    result = reaper.apply([record], dry_run=False)

    assert result["removed"] == []
    assert result["errors"]
    assert target.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode == 0


def test_apply_refuses_when_path_is_repointed_to_another_branch(
    fixture_repo: dict[str, Any],
) -> None:
    repo = fixture_repo["repo"]
    target = fixture_repo["paths"]["ancestor"]
    record = next(item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor")
    _git(repo, "worktree", "remove", "--", str(target))
    _git(repo, "branch", "feature/repointed", "main")
    _git(repo, "worktree", "add", str(target), "feature/repointed")

    result = reaper.apply([record], dry_run=False)

    assert result["removed"] == []
    assert result["errors"]
    assert target.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode == 0
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/repointed",
        check=False,
    ).returncode == 0


def test_apply_preflights_all_targets_before_mutating(
    fixture_repo: dict[str, Any],
) -> None:
    repo = fixture_repo["repo"]
    target = fixture_repo["paths"]["ancestor"]
    candidate = next(item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor")
    root_record = reaper.WorktreeRecord(
        path=repo,
        branch="feature/parent",
        parent="main",
        status="REDUNDANT",
        reason="synthetic root safety check",
        repo=repo,
    )

    with pytest.raises(RuntimeError, match="root worktree"):
        reaper.apply([candidate, root_record], dry_run=False)

    assert target.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode == 0


def test_apply_does_not_delete_branch_when_worktree_removal_fails(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = fixture_repo["repo"]
    target = fixture_repo["paths"]["ancestor"]
    record = next(item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor")
    original_git = reaper._git
    failed = False

    def fail_remove(
        git_repo: Path,
        *args: str,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal failed
        if not failed and args[:3] == ("worktree", "remove", "--"):
            failed = True
            return subprocess.CompletedProcess(
                ["git", *args],
                1,
                "",
                "simulated worktree removal failure",
            )
        return original_git(git_repo, *args, **kwargs)

    monkeypatch.setattr(reaper, "_git", fail_remove)
    result = reaper.apply([record], dry_run=False)

    assert result["removed"] == []
    assert result["errors"]
    assert target.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode == 0


def test_apply_recovers_after_worktree_removal_before_branch_delete(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = fixture_repo["repo"]
    target = fixture_repo["paths"]["ancestor"]
    record = next(item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor")
    original_git = reaper._git
    failed = False

    def fail_delete_once(
        git_repo: Path,
        *args: str,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal failed
        if not failed and args[:2] == ("update-ref", "--stdin"):
            failed = True
            return subprocess.CompletedProcess(
                ["git", *args],
                1,
                "",
                "simulated branch deletion failure",
            )
        return original_git(git_repo, *args, **kwargs)

    monkeypatch.setattr(reaper, "_git", fail_delete_once)
    first = reaper.apply([record], dry_run=False)

    assert first["removed"] == []
    assert first["errors"]
    assert not target.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode == 0

    second = reaper.apply(reaper.classify(repo), dry_run=False)

    assert second["errors"] == []
    assert str(target.resolve()) in second["removed"]
    assert not (repo / ".git" / "worktree-reap.intent.json").exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode != 0


def test_apply_refuses_when_another_reaper_holds_the_repository_lock(
    fixture_repo: dict[str, Any],
) -> None:
    repo = fixture_repo["repo"]
    target = fixture_repo["paths"]["ancestor"]
    record = next(item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor")

    with reaper._repository_lock(repo):
        result = reaper.apply([record], dry_run=False)

    assert result["removed"] == []
    assert result["errors"]
    assert target.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode == 0


def test_protected_path_with_spaces_is_not_reaped(
    fixture_repo: dict[str, Any],
) -> None:
    repo = fixture_repo["repo"]
    target = repo.parent / "protected worktree"
    _git(repo, "branch", "feature/protected-space", "main")
    _git(repo, "worktree", "add", str(target), "feature/protected-space")

    record = next(
        item
        for item in reaper.classify(repo, protected=[str(target)])
        if item.branch == "feature/protected-space"
    )
    assert record.status == "LIVE"
    assert record.protected is True
    result = reaper.apply([record], dry_run=False)

    assert result == {"removed": [], "skipped": [str(target.resolve())], "errors": []}
    assert target.exists()


def test_merge_base_failure_is_unknown_and_strict_fails(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = fixture_repo["repo"]
    original_git = reaper._git

    def fail_merge_base(
        git_repo: Path,
        *args: str,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        if args == (
            "merge-base",
            "--is-ancestor",
            "feature/parent-ancestor",
            "feature/parent",
        ):
            return subprocess.CompletedProcess(
                ["git", *args],
                128,
                "",
                "simulated merge-base failure",
            )
        return original_git(git_repo, *args, **kwargs)

    monkeypatch.setattr(reaper, "_git", fail_merge_base)
    record = next(
        item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor"
    )
    assert record.status == "UNKNOWN"
    monkeypatch.delenv("REAP_STRICT", raising=False)
    assert reaper.main(["--repo", str(repo), "--strict"]) == 4
    # UNKNOWN is the reaper declining to decide.  An advisory --check must not
    # fail for that; strict mode is where indecision becomes a hard signal.
    assert reaper.main(["--repo", str(repo), "--check"]) == 0
    assert reaper.main(["--repo", str(repo), "--check", "--strict"]) == 4
    monkeypatch.setenv("REAP_STRICT", "1")
    assert reaper.main(["--repo", str(repo), "--check"]) == 4


def test_landed_directly_in_main_is_redundant(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "worktree-reap@example.test")
    _git(repo, "config", "user.name", "Worktree Reap Test")
    _commit(repo, "initial", "README", "initial\n")
    _git(repo, "branch", "feature/parent")
    _git(repo, "branch", "feature/parent-child", "main")
    child_path = repo.parent / "direct-main"
    _git(repo, "worktree", "add", str(child_path), "feature/parent-child")
    _commit(child_path, "child patch", "child.txt", "child\n")
    _git(repo, "merge", "--ff-only", "feature/parent-child")

    record = next(
        item for item in reaper.classify(repo) if item.branch == "feature/parent-child"
    )

    assert record.parent == "feature/parent"
    assert record.status == "REDUNDANT"
    assert record.reason == "feature/parent-child is landed in main"
    result = reaper.apply([record], dry_run=False)
    assert result["errors"] == []
    assert result["removed"] == [str(child_path.resolve())]
    assert not child_path.exists()


def test_missing_parent_is_unknown_and_not_reaped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "worktree-reap@example.test")
    _git(repo, "config", "user.name", "Worktree Reap Test")
    _commit(repo, "initial", "README", "initial\n")
    _git(repo, "branch", "feature/missing")
    _git(repo, "branch", "feature/missing-child", "main")
    child_path = repo.parent / "missing-parent-child"
    _git(repo, "worktree", "add", str(child_path), "feature/missing-child")
    _git(repo, "update-ref", "-d", "refs/heads/feature/missing")

    record = next(
        item for item in reaper.classify(repo) if item.branch == "feature/missing-child"
    )

    assert record.status == "UNKNOWN"
    assert record.parent == "feature/missing"
    assert "missing" in record.reason
    result = reaper.apply([record], dry_run=False)
    assert result["removed"] == []
    assert result["errors"] == []
    assert child_path.exists()


def test_branch_only_refs_are_not_classified_or_reaped(fixture_repo: dict[str, Any]) -> None:
    repo = fixture_repo["repo"]
    _git(repo, "branch", "feature/parent-branch-only", "feature/parent")

    records = reaper.classify(repo)

    assert all(record.branch != "feature/parent-branch-only" for record in records)
    result = reaper.apply(records, dry_run=False)
    assert result["errors"] == []
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-branch-only",
        check=False,
    ).returncode == 0


def test_apply_deletes_child_branch_when_parent_is_a_linked_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "worktree-reap@example.test")
    _git(repo, "config", "user.name", "Worktree Reap Test")
    _commit(repo, "initial", "README", "initial\n")
    _git(repo, "branch", "feature/parent")
    parent_path = repo.parent / "linked-parent"
    _git(repo, "worktree", "add", str(parent_path), "feature/parent")
    _commit(parent_path, "parent patch", "parent.txt", "parent\n")
    _git(repo, "branch", "feature/parent-child", "feature/parent")
    child_path = repo.parent / "linked-child"
    _git(repo, "worktree", "add", str(child_path), "feature/parent-child")

    records = reaper.classify(repo)
    child_record = next(item for item in records if item.branch == "feature/parent-child")
    assert child_record.status == "REDUNDANT"
    assert child_record.proof_parent == "feature/parent"

    result = reaper.apply(records, dry_run=False)

    assert result["errors"] == []
    assert result["removed"] == [str(child_path.resolve())]
    assert not child_path.exists()
    assert parent_path.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-child",
        check=False,
    ).returncode != 0
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent",
        check=False,
    ).returncode == 0


def test_apply_deletes_redundant_children_before_redundant_parents(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "worktree-reap@example.test")
    _git(repo, "config", "user.name", "Worktree Reap Test")
    _commit(repo, "initial", "README", "initial\n")
    _git(repo, "branch", "feature/parent")
    parent_path = repo.parent / "redundant-parent"
    _git(repo, "worktree", "add", str(parent_path), "feature/parent")
    _git(repo, "branch", "feature/parent-child", "feature/parent")
    child_path = repo.parent / "redundant-child"
    _git(repo, "worktree", "add", str(child_path), "feature/parent-child")

    records = reaper.classify(repo)
    assert {
        item.branch for item in records if item.status == "REDUNDANT"
    } == {"feature/parent", "feature/parent-child"}

    result = reaper.apply(records, dry_run=False)

    assert result["errors"] == []
    assert {Path(path).resolve() for path in result["removed"]} == {
        parent_path.resolve(),
        child_path.resolve(),
    }
    assert not parent_path.exists()
    assert not child_path.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent",
        check=False,
    ).returncode != 0
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-child",
        check=False,
    ).returncode != 0


def test_delete_ref_rechecks_landing_parent_in_same_transaction(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = fixture_repo["repo"]
    target = fixture_repo["paths"]["ancestor"]
    record = next(item for item in reaper.classify(repo) if item.branch == "feature/parent-ancestor")
    original_git = reaper._git
    changed = False

    def advance_parent_before_delete(
        git_repo: Path,
        *args: str,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal changed
        if not changed and args[:2] == ("update-ref", "--stdin"):
            changed = True
            _commit(repo, "advance landing parent during delete", "race.txt", "race\n")
        return original_git(git_repo, *args, **kwargs)

    monkeypatch.setattr(reaper, "_git", advance_parent_before_delete)
    result = reaper.apply([record], dry_run=False)

    assert result["removed"] == []
    assert result["errors"]
    assert not target.exists()
    assert _git(
        repo,
        "show-ref",
        "--verify",
        "refs/heads/feature/parent-ancestor",
        check=False,
    ).returncode == 0


def test_check_exit_honours_reap_strict(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = fixture_repo["repo"]
    monkeypatch.delenv("REAP_STRICT", raising=False)
    assert reaper.main(["--repo", str(repo), "--check"]) == 0

    monkeypatch.setenv("REAP_STRICT", "1")
    assert reaper.main(["--repo", str(repo), "--check"]) == 3


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
    for dry_run in (True, False):
        with pytest.raises(RuntimeError, match="root worktree"):
            reaper.apply([root_record], dry_run=dry_run)

    current = repo.parent / "current"
    _git(repo, "branch", "feature/current", "main")
    _git(repo, "worktree", "add", str(current), "feature/current")
    monkeypatch.chdir(current)
    current_record = next(
        record for record in reaper.classify(repo) if record.branch == "feature/current"
    )
    for dry_run in (True, False):
        with pytest.raises(RuntimeError, match="current worktree"):
            reaper.apply([current_record], dry_run=dry_run)


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


def test_active_lane_worktree_is_live_even_when_landed_and_clean(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4-01: a re-dispatched lane is landed and clean, exactly like a reap target."""
    repo = fixture_repo["repo"]
    ancestor = fixture_repo["paths"]["ancestor"].resolve()

    baseline = next(
        item for item in reaper.classify(repo) if item.path == ancestor
    )
    assert baseline.status == "REDUNDANT"

    monkeypatch.setattr(
        reaper, "active_lane_paths", lambda _repo: {ancestor: "parent-ancestor-lane"}
    )
    record = next(item for item in reaper.classify(repo) if item.path == ancestor)
    assert record.status == "LIVE"
    assert record.reason == "active lane parent-ancestor-lane"
    assert record.protected is True


def test_active_lane_worktree_survives_apply(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = fixture_repo["repo"]
    ancestor = fixture_repo["paths"]["ancestor"].resolve()
    monkeypatch.setattr(
        reaper, "active_lane_paths", lambda _repo: {ancestor: "parent-ancestor-lane"}
    )
    assert reaper.main(["--repo", str(repo), "--apply"]) == 0
    assert ancestor.exists()
    assert _git(
        repo, "rev-parse", "--verify", "refs/heads/feature/parent-ancestor", check=False
    ).returncode == 0


def test_unreadable_lane_state_fails_closed(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable registry must not license a removal."""
    repo = fixture_repo["repo"]

    def unreadable(_repo: Path) -> dict[Path, str]:
        raise reaper.LaneStateError("registry offline")

    monkeypatch.setattr(reaper, "active_lane_paths", unreadable)
    records = reaper.classify(repo)
    linked = [item for item in records if item.status != "ROOT"]
    assert linked
    assert {item.status for item in linked} == {"UNKNOWN"}
    assert all("registry offline" in item.reason for item in linked)

    monkeypatch.delenv("REAP_STRICT", raising=False)
    assert reaper.main(["--repo", str(repo), "--apply"]) == 0
    assert fixture_repo["paths"]["ancestor"].exists()


def test_missing_lane_state_can_be_overridden_explicitly(
    fixture_repo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = fixture_repo["repo"]

    def unreadable(_repo: Path) -> dict[Path, str]:
        raise reaper.LaneStateError("registry offline")

    monkeypatch.setattr(reaper, "active_lane_paths", unreadable)
    with pytest.warns(RuntimeWarning, match="without lane-state verification"):
        records = reaper.classify(repo, require_lane_state=False)
    assert any(item.status == "REDUNDANT" for item in records)
    # A zero in a reclaim receipt must distinguish "examined, none eligible"
    # from "never examined"; the status alone reads the same either way.
    assert all(item.lane_verified is False for item in records)
    assert all(
        reaper._record_json(item)["lane_verified"] is False
        for item in records
        if item.status != "ROOT"
    )


def test_verified_lane_state_marks_records_verified(
    fixture_repo: dict[str, Any],
) -> None:
    records = reaper.classify(fixture_repo["repo"])
    assert all(item.lane_verified is True for item in records)


def test_terminal_lane_rows_do_not_protect_a_worktree() -> None:
    rows = [
        {"lane_id": "done", "status": "merged", "worktree_path": "/tmp/reap-a"},
        {"lane_id": "shut", "status": "closed", "worktree_path": "/tmp/reap-b"},
        {"lane_id": "busy", "status": "blocked", "worktree_path": "/tmp/reap-c"},
        {"lane_id": "stale", "status": "closed_stale", "worktree_path": "/tmp/reap-d"},
    ]
    owners = reaper._lane_owners_from_rows(rows)
    assert set(owners) == {Path("/tmp/reap-c").resolve(), Path("/tmp/reap-d").resolve()}


def test_a_lane_row_without_a_status_fails_closed() -> None:
    with pytest.raises(reaper.LaneStateError):
        reaper._lane_owners_from_rows([{"lane_id": "x", "worktree_path": "/tmp/reap-a"}])


@pytest.mark.parametrize(
    "relative_path",
    [
        ".task-state/.heartbeat/1__a.json",
        ".task-state/.locks/reap.lock",
        ".task-state/auto-reap-stale-maint.stamp",
        ".task-state/a-stamp-nobody-enumerated-yet.stamp",
        ".task-state/daemon.pid",
        "nested/.task-state/.heartbeat",
    ],
)
def test_harness_scratch_is_regenerable(relative_path: str) -> None:
    """R4-02: the allowlist is provenance-shaped, not a list of filenames."""
    assert reaper._is_regenerable_ignored(relative_path) is True


@pytest.mark.parametrize(
    "relative_path",
    [
        ".task-state/remote-exec-lane/turn.patch",
        ".task-state/coord/briefs/one.md",
        ".task-state/evidence.json",
        "models/weights.bin",
        ".venv/bin/python",
    ],
)
def test_unowned_content_is_not_regenerable(relative_path: str) -> None:
    """The provenance rule must not collapse into 'ignored means disposable'."""
    assert reaper._is_regenerable_ignored(relative_path) is False


def test_a_newly_named_harness_stamp_does_not_block_a_reap(
    fixture_repo: dict[str, Any],
) -> None:
    repo = fixture_repo["repo"]
    ancestor = fixture_repo["paths"]["ancestor"].resolve()
    scratch = ancestor / ".task-state"
    scratch.mkdir()
    (scratch / "a-stamp-nobody-enumerated-yet.stamp").write_text("swept\n")
    (ancestor / ".gitignore").write_text(".task-state/\n")
    _git(ancestor, "add", ".gitignore")
    _git(ancestor, "commit", "-m", "ignore harness scratch")
    _git(repo, "merge", "--ff-only", "feature/parent-ancestor")

    record = next(item for item in reaper.classify(repo) if item.path == ancestor)
    assert record.status == "REDUNDANT", record.reason


def test_env_protect_preserves_a_path_containing_spaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-06: make cannot pass a repeatable option without word-splitting it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "worktree-reap@example.test")
    _git(repo, "config", "user.name", "Worktree Reap Test")
    _commit(repo, "initial", "README", "initial\n")
    _git(repo, "branch", "feature/landed")
    spaced = tmp_path / "a lane with spaces"
    _git(repo, "worktree", "add", str(spaced), "feature/landed")

    monkeypatch.delenv("REAP_PROTECT", raising=False)
    unprotected = next(
        item for item in reaper.classify(repo) if item.path == spaced.resolve()
    )
    assert unprotected.status == "REDUNDANT"

    monkeypatch.setenv("REAP_PROTECT", f"{spaced}\nfeature/other")
    record = next(item for item in reaper.classify(repo) if item.path == spaced.resolve())
    assert record.status == "LIVE"
    assert record.protected is True
