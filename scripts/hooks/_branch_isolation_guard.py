#!/usr/bin/env python3
"""Shared helpers for main-branch branch-isolation guards."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from _harness_protocol import find_permitted_main_surface, is_branch_isolation_protected_path


_EDIT_TOOLS = {
    "Edit",
    "Write",
    "apply_patch",
    "create_file",
    "multi_replace_string_in_file",
    "replace_string_in_file",
}


def resolve_path_branch(abs_path: str) -> str | None:
    """Return the git branch of the worktree containing ``abs_path``.

    The harness cwd is always the project root, which by repo convention stays
    on ``main`` even when active work happens in linked feature-branch
    worktrees. Without per-path resolution, the guards misclassify edits to
    files that physically live in a feature-branch worktree as main-branch
    edits and block them.

    Returns the branch reported by ``git branch --show-current`` when run
    inside the worktree containing ``abs_path``. Returns ``None`` when the
    path is not inside a git working tree (so the caller can fall back to
    the harness branch and preserve the conservative default).
    """
    if not abs_path:
        return None
    try:
        candidate = Path(abs_path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    anchor = candidate if candidate.is_dir() else candidate.parent
    while not anchor.exists():
        parent = anchor.parent
        if parent == anchor:
            return None
        anchor = parent
    try:
        proc = subprocess.run(
            ["git", "-C", str(anchor), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _payload_value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def to_repo_relative(path: str, repo_root: str) -> str:
    normalized_path = path.strip()
    if not normalized_path:
        return normalized_path
    if not repo_root:
        return normalized_path
    try:
        candidate = Path(normalized_path).expanduser().resolve(strict=False)
        root = Path(repo_root).expanduser().resolve(strict=False)
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return normalized_path


def extract_candidate_paths(tool_name: str, tool_input: dict[str, Any]) -> list[str]:
    file_path = _payload_value(tool_input, "filePath", "file_path")
    if tool_name != "apply_patch":
        if tool_name not in _EDIT_TOOLS and not (isinstance(file_path, str) and file_path.strip()):
            return []
        return [str(file_path)] if isinstance(file_path, str) and file_path.strip() else []

    patch_input = tool_input.get("input")
    if not isinstance(patch_input, str) or not patch_input.strip():
        return []

    paths: list[str] = []
    for line in patch_input.splitlines():
        if not line.startswith("*** ") or " File: " not in line:
            continue
        _, raw_path = line.split(" File: ", 1)
        parsed_path = raw_path.split(" -> ", 1)[0].strip()
        if parsed_path:
            paths.append(parsed_path)
    return paths


def check_file_edit(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    branch: str,
    repo_root: str,
    policy,
    protected_branches: set[str] | frozenset[str],
) -> tuple[str, list[str]] | None:
    if branch not in protected_branches:
        return None

    blocked_paths: list[str] = []
    for raw_path in extract_candidate_paths(tool_name, tool_input):
        relative_path = to_repo_relative(raw_path, repo_root)
        if not is_branch_isolation_protected_path(relative_path, policy):
            continue
        if find_permitted_main_surface(relative_path, policy) is not None:
            continue
        per_path_branch = resolve_path_branch(raw_path)
        effective_branch = per_path_branch if per_path_branch else branch
        if effective_branch in protected_branches:
            blocked_paths.append(relative_path)

    if not blocked_paths:
        return None
    return branch, blocked_paths


def find_dirty_protected_paths(
    *,
    branch: str,
    repo_root: str,
    policy,
    protected_branches: set[str] | frozenset[str],
) -> tuple[str, list[str]] | None:
    if branch not in protected_branches or not repo_root:
        return None

    dirty_paths: list[str] = []
    for candidate in _git_dirty_paths(Path(repo_root)):
        if is_branch_isolation_protected_path(candidate, policy):
            dirty_paths.append(candidate)

    if not dirty_paths:
        return None
    return branch, sorted(dict.fromkeys(dirty_paths))


def _git_dirty_paths(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return []

    entries = proc.stdout.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue

        status = entry[:2]
        path = entry[3:]
        if path:
            paths.append(path)

        if status[0] in {"R", "C"} and index < len(entries):
            renamed_path = entries[index]
            index += 1
            if renamed_path:
                paths.append(renamed_path)

    return [path.replace("\\", "/").lstrip("/") for path in paths if path.strip()]
