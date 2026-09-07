#!/usr/bin/env python3
"""Classify and safely reap redundant linked Git worktrees.

The default CLI mode is an observational dry run.  A worktree is only a
reap candidate when it is clean and its branch is already represented by its
parent branch, either by reachability or by Git's patch-equivalence check.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Collection, Literal


WorktreeStatus = Literal["REDUNDANT", "LIVE", "DIRTY", "ROOT", "UNKNOWN"]


class GitError(RuntimeError):
    """A Git command could not be run or returned an unexpected failure."""


@dataclass(frozen=True)
class WorktreeRecord:
    path: Path
    branch: str
    parent: str
    status: WorktreeStatus
    reason: str
    # Records produced by classify carry their repository so apply remains
    # safe and idempotent even after a successful first removal.
    repo: Path | None = field(default=None, repr=False, compare=False)


def _git(
    repo: Path,
    *args: str,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run Git rooted at ``repo`` and optionally raise on command failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise GitError(f"could not run git: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitError(detail or f"git {' '.join(args)} exited {result.returncode}")
    return result


def _worktree_entries(output: str) -> list[dict[str, object]]:
    """Parse Git's porcelain worktree listing into simple dictionaries."""
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    def finish() -> None:
        nonlocal current
        if current is not None and "path" in current:
            entries.append(current)
        current = None

    for line in output.splitlines():
        if not line:
            finish()
            continue
        if line.startswith("worktree "):
            finish()
            current = {"path": Path(line.removeprefix("worktree "))}
        elif current is None:
            continue
        elif line.startswith("branch "):
            branch = line.removeprefix("branch ")
            current["branch"] = branch.removeprefix("refs/heads/")
        elif line == "detached":
            current["detached"] = True
    finish()
    return entries


def _local_branches(repo: Path) -> set[str]:
    result = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitError(detail or "could not enumerate local branches")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _candidate_prefixes(prefix: str, value: str, *, include_full: bool) -> list[str]:
    """Return possible task prefixes from longest to shortest."""
    lengths = [index for index, char in enumerate(value) if char == "-"]
    if include_full:
        lengths.append(len(value))
    return [
        f"{prefix}{value[:length]}"
        for length in sorted({length for length in lengths if length > 0}, reverse=True)
    ]


def parent_of(branch: str, branches: Collection[str] | None = None) -> str:
    """Return the likely parent branch for ``branch``.

    ``branches`` is an optional pure-data view of local branch names.  It lets
    callers resolve the ``feature/<task>-<sub>`` and ``review/<task>-...``
    conventions without making this helper perform Git I/O.  With no branch
    inventory, feature branches use their immediate task prefix and review
    branches conservatively fall back to ``main``.
    """
    branch = str(branch or "")
    known = None if branches is None else {str(item) for item in branches}

    if branch.startswith("feature/"):
        value = branch.removeprefix("feature/")
        candidates = _candidate_prefixes("feature/", value, include_full=False)
        if known is not None:
            return next((candidate for candidate in candidates if candidate in known), "main")
        return candidates[0] if candidates else "main"

    if branch.startswith("review/"):
        value = branch.removeprefix("review/")
        candidates = _candidate_prefixes("feature/", value, include_full=True)
        if known is not None:
            return next((candidate for candidate in candidates if candidate in known), "main")
        return "main"

    return "main"


def is_merged(repo: Path | str, branch: str, parent: str) -> bool:
    """Return whether ``branch`` is landed in ``parent``.

    Reachability is the primary predicate.  When a branch was rebased, the
    commit IDs can differ while the patches remain equivalent, so the Git
    cherry fallback is also required.  Every Git error is a safe ``False``.
    """
    repo_path = Path(repo).resolve()
    try:
        ancestor = _git(repo_path, "merge-base", "--is-ancestor", branch, parent)
        if ancestor.returncode == 0:
            return True
        if ancestor.returncode != 1:
            return False

        cherry = _git(repo_path, "cherry", parent, branch)
        if cherry.returncode != 0:
            return False
        return all(line.startswith("-") for line in cherry.stdout.splitlines())
    except (GitError, OSError, ValueError):
        return False


def is_dirty(path: Path | str) -> bool:
    """Return whether a worktree has tracked or untracked changes."""
    path_obj = Path(path).resolve()
    result = _git(path_obj, "status", "--porcelain", "--untracked-files=all")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitError(detail or f"cannot inspect worktree {path_obj}")
    return bool(result.stdout)


def classify(repo: Path | str) -> list[WorktreeRecord]:
    """Enumerate and classify every worktree Git reports for ``repo``."""
    repo_path = Path(repo).resolve()
    listing = _git(repo_path, "worktree", "list", "--porcelain", check=True)
    entries = _worktree_entries(listing.stdout)
    if not entries:
        return []

    # Git emits the primary worktree first.  Keeping that path rather than
    # treating the invocation cwd as root also works when --repo points at a
    # linked worktree.
    root_path = Path(entries[0]["path"]).resolve()
    try:
        branches = _local_branches(repo_path)
    except GitError:
        branches = {
            str(entry.get("branch", ""))
            for entry in entries
            if entry.get("branch")
        }

    records: list[WorktreeRecord] = []
    for entry in entries:
        path = Path(entry["path"]).resolve()
        branch = str(entry.get("branch", ""))
        parent = parent_of(branch, branches)

        if path == root_path:
            records.append(
                WorktreeRecord(
                    path=path,
                    branch=branch,
                    parent=parent,
                    status="ROOT",
                    reason="repository root worktree",
                    repo=root_path,
                )
            )
            continue

        if not branch:
            reason = "detached worktree cannot be associated with a branch"
            records.append(
                WorktreeRecord(
                    path=path,
                    branch="",
                    parent=parent,
                    status="UNKNOWN",
                    reason=reason,
                    repo=root_path,
                )
            )
            continue

        try:
            dirty = is_dirty(path)
        except (GitError, OSError, ValueError) as exc:
            records.append(
                WorktreeRecord(
                    path=path,
                    branch=branch,
                    parent=parent,
                    status="UNKNOWN",
                    reason=f"cannot inspect worktree: {exc}",
                    repo=root_path,
                )
            )
            continue

        if dirty:
            status: WorktreeStatus = "DIRTY"
            reason = "worktree has tracked or untracked changes"
        elif is_merged(repo_path, branch, parent):
            status = "REDUNDANT"
            reason = f"{branch} is landed in {parent}"
        else:
            status = "LIVE"
            reason = f"{branch} is not landed in {parent}"

        records.append(
            WorktreeRecord(
                path=path,
                branch=branch,
                parent=parent,
                status=status,
                reason=reason,
                repo=root_path,
            )
        )
    return records


def _record_repo(record: WorktreeRecord) -> Path:
    if record.repo is not None:
        return Path(record.repo).resolve()

    path = Path(record.path).resolve()
    common_dir = _git(path, "rev-parse", "--git-common-dir", check=True).stdout.strip()
    common_path = Path(common_dir)
    if not common_path.is_absolute():
        common_path = (path / common_path).resolve()
    return common_path.parent if common_path.name == ".git" else path


def _repository_root(repo: Path) -> Path:
    result = _git(repo, "rev-parse", "--show-toplevel")
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return repo.resolve()


def _failure(result: subprocess.CompletedProcess[str], command: str) -> str:
    detail = (result.stderr or result.stdout).strip()
    return detail or f"{command} exited {result.returncode}"


def _delete_branch(repo: Path, branch: str, parent: str) -> str | None:
    """Delete a redundant branch without force-deleting it.

    ``git branch -d`` uses commit reachability, while the classifier also
    accepts patch-equivalent rebases.  For that one safe case, move the now
    unlinked branch ref to its already-equivalent parent and retry the normal
    non-forcing deletion.
    """
    command = f"git branch -d {branch}"
    result = _git(repo, "branch", "-d", branch)
    if result.returncode == 0:
        return None

    if not is_merged(repo, branch, parent):
        return _failure(result, command)

    moved = _git(
        repo,
        "update-ref",
        f"refs/heads/{branch}",
        f"refs/heads/{parent}",
        f"refs/heads/{branch}",
    )
    if moved.returncode != 0:
        return _failure(moved, f"git update-ref refs/heads/{branch}")

    retry = _git(repo, "branch", "-d", branch)
    if retry.returncode != 0:
        return _failure(retry, command)
    return None


def apply(records: list[WorktreeRecord], *, dry_run: bool = True) -> dict[str, list[str]]:
    """Remove redundant clean worktrees and delete their branches.

    The operation is deliberately idempotent: a record whose path was
    removed by an earlier invocation is skipped on a retry.  Root and current
    worktrees are hard safety errors if ever presented as REDUNDANT records.
    """
    result: dict[str, list[str]] = {"removed": [], "skipped": [], "errors": []}
    current_path = Path.cwd().resolve()

    for record in records:
        target = Path(record.path).resolve()
        if record.status != "REDUNDANT":
            result["skipped"].append(str(target))
            continue

        try:
            repo = _record_repo(record)
            root = _repository_root(repo)
        except (GitError, OSError, ValueError) as exc:
            result["errors"].append(f"{target}: cannot resolve repository: {exc}")
            continue

        if target == root:
            raise RuntimeError(f"refusing to reap the root worktree: {target}")
        if target == current_path or target in current_path.parents:
            raise RuntimeError(f"refusing to reap the current worktree: {target}")

        if dry_run or not target.exists():
            result["skipped"].append(str(target))
            continue

        removed = _git(repo, "worktree", "remove", str(target))
        if removed.returncode != 0:
            result["errors"].append(f"{target}: {_failure(removed, 'git worktree remove')}")
            continue

        branch_error = _delete_branch(repo, record.branch, record.parent)
        if branch_error is not None:
            result["errors"].append(f"{target}: {branch_error}")
            continue
        result["removed"].append(str(target))

    return result


def _record_json(record: WorktreeRecord) -> dict[str, str]:
    return {
        "path": str(record.path),
        "branch": record.branch,
        "parent": record.parent,
        "status": record.status,
        "reason": record.reason,
    }


def _print_table(records: list[WorktreeRecord]) -> None:
    if not records:
        print("No worktrees found.")
        return

    headers = ("STATUS", "BRANCH", "PARENT", "PATH", "REASON")
    rows = [
        (record.status, record.branch or "-", record.parent, str(record.path), record.reason)
        for record in records
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository to inspect")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="remove redundant clean worktrees and delete their branches",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit linked-worktree records as JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        records = classify(args.repo)
    except (GitError, OSError, ValueError) as exc:
        print(f"worktree-reap: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        # The repository root is represented by classify for safety and table
        # observability, but --json describes linked worktrees only.  Thus a
        # converged root-only repository emits the useful machine value [].
        payload = [_record_json(record) for record in records if record.status != "ROOT"]
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_table(records)

    if not args.apply:
        return 3 if any(record.status == "REDUNDANT" for record in records) else 0

    try:
        applied = apply(records, dry_run=False)
    except (GitError, OSError, RuntimeError, ValueError) as exc:
        print(f"worktree-reap: {exc}", file=sys.stderr)
        return 1
    if applied["errors"]:
        for error in applied["errors"]:
            print(f"worktree-reap: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
