"""Tests for per-file worktree branch resolution in branch-isolation guards.

The harness cwd always reports the project root, which by repo convention
stays on ``main`` even while active work happens inside linked
feature-branch worktrees. Without per-path resolution, both the file-edit
guard (``check_file_edit``) and the bash guard (``scan_bash_command``)
misclassify edits to files that physically live in a feature-branch
worktree as main-branch edits and block them. This module pins down the
post-fix behavior and the regression cases.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))

from _bash_isolation_guard import scan_bash_command  # noqa: E402
from _branch_isolation_guard import (  # noqa: E402
    check_file_edit,
    resolve_path_branch,
)
from _harness_protocol import BranchIsolationPolicy, MainSurfacePattern  # noqa: E402


_PROTECTED = frozenset({"main", "master"})


def _policy(*, permitted_main_surfaces: tuple[MainSurfacePattern, ...] = ()) -> BranchIsolationPolicy:
    return BranchIsolationPolicy(
        code_roots=("apps/", "packages/", "scripts/", ".github/hooks/", ".claude/", "mk/"),
        protected_extensions=(".py", ".ts", ".sh"),
        root_protected_files=("Makefile",),
        protected_main_surfaces=(),
        permitted_main_surfaces=permitted_main_surfaces,
    )


def _git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5, check=True
    )
    return proc.stdout.strip()


def _make_repo_with_feature_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a primary repo on ``main`` plus a linked worktree on a feature branch.

    Returns ``(primary_root, feature_worktree_root)``.
    """
    primary = tmp_path / "primary"
    primary.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(primary)], check=True)
    _git("config", "user.email", "test@example.com", cwd=primary)
    _git("config", "user.name", "Test", cwd=primary)
    (primary / "README.md").write_text("seed\n", encoding="utf-8")
    _git("add", "README.md", cwd=primary)
    _git("commit", "-q", "-m", "init", cwd=primary)

    feature_root = tmp_path / "primary-feature"
    _git("worktree", "add", "-b", "feature/x", str(feature_root), cwd=primary)
    return primary, feature_root


def test_resolve_path_branch_returns_worktree_branch(tmp_path: Path) -> None:
    primary, feature_root = _make_repo_with_feature_worktree(tmp_path)

    assert resolve_path_branch(str(primary / "README.md")) == "main"
    assert resolve_path_branch(str(feature_root / "README.md")) == "feature/x"


def test_resolve_path_branch_handles_nonexistent_file_in_worktree(tmp_path: Path) -> None:
    _, feature_root = _make_repo_with_feature_worktree(tmp_path)
    target = feature_root / "scripts" / "hooks" / "new_file.py"
    assert resolve_path_branch(str(target)) == "feature/x"


def test_resolve_path_branch_returns_none_outside_git(tmp_path: Path) -> None:
    outside = tmp_path / "not-a-repo" / "foo.py"
    outside.parent.mkdir()
    outside.write_text("x", encoding="utf-8")
    assert resolve_path_branch(str(outside)) is None


def test_check_file_edit_allows_feature_worktree_file_when_harness_on_main(tmp_path: Path) -> None:
    primary, feature_root = _make_repo_with_feature_worktree(tmp_path)
    target = feature_root / "scripts" / "thing.py"
    result = check_file_edit(
        "Edit",
        {"file_path": str(target)},
        branch="main",
        repo_root=str(primary),
        policy=_policy(),
        protected_branches=_PROTECTED,
    )
    assert result is None, f"expected allow for feature-worktree file, got {result!r}"


def test_check_file_edit_still_blocks_main_worktree_file(tmp_path: Path) -> None:
    primary, _ = _make_repo_with_feature_worktree(tmp_path)
    target = primary / "scripts" / "thing.py"
    result = check_file_edit(
        "Edit",
        {"file_path": str(target)},
        branch="main",
        repo_root=str(primary),
        policy=_policy(),
        protected_branches=_PROTECTED,
    )
    assert result is not None
    branch, blocked = result
    assert branch == "main"
    assert any(p.endswith("scripts/thing.py") for p in blocked), blocked


def test_check_file_edit_allows_permitted_main_surface_on_main(tmp_path: Path) -> None:
    primary, _ = _make_repo_with_feature_worktree(tmp_path)
    target = primary / "scripts" / "hooks" / "thing.py"
    policy = _policy(
        permitted_main_surfaces=(
            MainSurfacePattern(pattern="scripts/hooks/**", reason="Guard helpers stay editable on main"),
        )
    )

    result = check_file_edit(
        "Edit",
        {"file_path": str(target)},
        branch="main",
        repo_root=str(primary),
        policy=policy,
        protected_branches=_PROTECTED,
    )

    assert result is None, f"expected allow for permitted main surface, got {result!r}"


def test_scan_bash_command_allows_write_to_feature_worktree(tmp_path: Path) -> None:
    primary, feature_root = _make_repo_with_feature_worktree(tmp_path)
    target = feature_root / "scripts" / "thing.py"
    command = f"cat > {target} <<EOF\nx\nEOF"
    blocked = scan_bash_command(command, primary, _policy())
    real_path_blocks = [b for b in blocked if not b.endswith("(formatter)")]
    assert not real_path_blocks, f"feature-worktree write was blocked: {real_path_blocks!r}"


def test_scan_bash_command_still_blocks_main_worktree_write(tmp_path: Path) -> None:
    primary, _ = _make_repo_with_feature_worktree(tmp_path)
    target = primary / "scripts" / "thing.py"
    command = f"cat > {target} <<EOF\nx\nEOF"
    blocked = scan_bash_command(command, primary, _policy())
    real_path_blocks = [b for b in blocked if not b.endswith("(formatter)")]
    assert real_path_blocks, "main-worktree write was unexpectedly allowed"


def test_scan_bash_command_blocks_mixed_main_and_feature_paths(tmp_path: Path) -> None:
    primary, feature_root = _make_repo_with_feature_worktree(tmp_path)
    feature_target = feature_root / "scripts" / "ok.py"
    main_target = primary / "scripts" / "bad.py"
    command = f"echo a > {feature_target}; echo b > {main_target}"
    blocked = scan_bash_command(command, primary, _policy())
    real_path_blocks = [b for b in blocked if not b.endswith("(formatter)")]
    assert any("bad.py" in p for p in real_path_blocks), real_path_blocks
    assert not any("ok.py" in p for p in real_path_blocks), real_path_blocks
