#!/usr/bin/env python3
"""Classify and safely reap redundant linked Git worktrees.

The default CLI mode is an observational dry run.  A worktree is only a
reap candidate when it is clean and its branch is already represented by its
parent branch, either by reachability or by Git's patch-equivalence check.
"""

from __future__ import annotations

import argparse
import json
import os
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
    # The repository is retained because a caller may apply records after
    # changing cwd or after one of the records has already been removed.
    repo: Path | None = field(default=None, repr=False, compare=False)
    # These are an immutable classification snapshot.  Branch deletion uses
    # them as compare-and-delete evidence instead of retargeting a ref.
    branch_oid: str | None = field(default=None, repr=False, compare=False)
    proof_parent: str | None = field(default=None, repr=False, compare=False)
    proof_oid: str | None = field(default=None, repr=False, compare=False)
    protected: bool = field(default=False, repr=False, compare=False)


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
        elif line == "locked" or line.startswith("locked "):
            current["locked"] = True
        elif line == "prunable" or line.startswith("prunable "):
            current["prunable"] = True
    finish()
    return entries


def _local_branches(repo: Path) -> set[str]:
    result = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitError(detail or "could not enumerate local branches")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _ref_oid(repo: Path, branch: str) -> str | None:
    """Return a local branch's commit OID, or ``None`` when it is unavailable."""
    if not branch:
        return None
    result = _git(repo, "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}")
    if result.returncode != 0:
        return None
    values = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return values[0] if len(values) == 1 else None


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
    """Return whether a worktree has tracked, untracked, or ignored changes."""
    path_obj = Path(path).resolve()
    result = _git(
        path_obj,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignored",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitError(detail or f"cannot inspect worktree {path_obj}")
    return bool(result.stdout)


def _protected_values(protected: Collection[str | Path] | str | Path | None) -> tuple[str, ...]:
    if protected is None:
        return ()
    if isinstance(protected, (str, Path)):
        return (str(protected),)
    return tuple(str(value) for value in protected)


def _is_protected(
    repo: Path,
    path: Path,
    branch: str,
    protected: tuple[str, ...],
) -> bool:
    """Match protection values against either a branch or a worktree path."""
    for value in protected:
        if branch == value:
            return True
        value_path = Path(value).expanduser()
        if value_path.is_absolute() and value_path.resolve() == path:
            return True
        if not value_path.is_absolute() and (
            value_path.resolve() == path or (repo / value_path).resolve() == path
        ):
            return True
    return False


def _unknown_record(
    repo: Path,
    path: Path,
    branch: str,
    parent: str,
    reason: str,
) -> WorktreeRecord:
    return WorktreeRecord(
        path=path,
        branch=branch,
        parent=parent,
        status="UNKNOWN",
        reason=reason,
        repo=repo,
    )


def _state_record(
    repo: Path,
    path: Path,
    branch: str,
    parent: str,
    status: WorktreeStatus,
    reason: str,
    *,
    branch_oid: str | None = None,
    proof_parent: str | None = None,
    proof_oid: str | None = None,
    protected: bool = False,
) -> WorktreeRecord:
    return WorktreeRecord(
        path=path,
        branch=branch,
        parent=parent,
        status=status,
        reason=reason,
        repo=repo,
        branch_oid=branch_oid,
        proof_parent=proof_parent,
        proof_oid=proof_oid,
        protected=protected,
    )


def _landing_branch(repo: Path, branch: str, parent: str) -> str | None:
    """Return the integration branch that proves ``branch`` redundant."""
    candidates = [parent] if parent == "main" else [parent, "main"]
    return next(
        (candidate for candidate in candidates if is_merged(repo, branch, candidate)),
        None,
    )


def _classify_clean(
    repo: Path,
    path: Path,
    branch: str,
    parent: str,
    branch_oid: str,
) -> WorktreeRecord:
    try:
        proof_parent = _landing_branch(repo, branch, parent)
        proof_oid = _ref_oid(repo, proof_parent or "")
        branch_unchanged = _ref_oid(repo, branch) == branch_oid
    except (GitError, OSError, ValueError) as exc:
        return _unknown_record(repo, path, branch, parent, f"cannot capture landing proof: {exc}")
    if not branch_unchanged:
        return _unknown_record(repo, path, branch, parent, "branch changed during classification")
    if proof_parent is not None and proof_oid is not None:
        return _state_record(
            repo,
            path,
            branch,
            parent,
            "REDUNDANT",
            f"{branch} is landed in {proof_parent}",
            proof_parent=proof_parent,
            proof_oid=proof_oid,
            branch_oid=branch_oid,
        )
    return _state_record(
        repo,
        path,
        branch,
        parent,
        "LIVE",
        f"{branch} is not landed in {parent}",
        branch_oid=branch_oid,
    )


def _classify_observed(
    repo: Path,
    path: Path,
    branch: str,
    parent: str,
    branch_oid: str,
    dirty: bool,
    protected: bool,
) -> WorktreeRecord:
    if protected:
        return _state_record(
            repo,
            path,
            branch,
            parent,
            "LIVE",
            "protected by caller",
            branch_oid=branch_oid,
            protected=True,
        )
    if dirty:
        return _state_record(
            repo,
            path,
            branch,
            parent,
            "DIRTY",
            "worktree has tracked, untracked, or ignored changes",
            branch_oid=branch_oid,
        )
    return _classify_clean(repo, path, branch, parent, branch_oid)


def _classify_linked(
    repo: Path,
    path: Path,
    branch: str,
    parent: str,
    entry: dict[str, object],
    protected: tuple[str, ...],
) -> WorktreeRecord:
    """Classify one non-root worktree from one immutable Git snapshot."""
    if entry.get("locked") or entry.get("prunable"):
        return _unknown_record(repo, path, branch, parent, "worktree is locked or prunable")

    try:
        branch_oid = _ref_oid(repo, branch)
    except (GitError, OSError, ValueError) as exc:
        return _unknown_record(repo, path, branch, parent, f"cannot inspect branch: {exc}")
    if branch_oid is None:
        return _unknown_record(repo, path, branch, parent, "branch ref cannot be inspected")

    try:
        dirty = is_dirty(path)
    except (GitError, OSError, ValueError) as exc:
        return _unknown_record(repo, path, branch, parent, f"cannot inspect worktree: {exc}")

    return _classify_observed(
        repo,
        path,
        branch,
        parent,
        branch_oid,
        dirty,
        _is_protected(repo, path, branch, protected),
    )


def _classify_entry(
    repo: Path,
    root_path: Path,
    entry: dict[str, object],
    branches: set[str],
    protected: tuple[str, ...],
) -> WorktreeRecord:
    path = Path(entry["path"]).resolve()
    branch = str(entry.get("branch", ""))
    parent = parent_of(branch, branches)
    if path == root_path:
        return WorktreeRecord(
            path=path,
            branch=branch,
            parent=parent,
            status="ROOT",
            reason="repository root worktree",
            repo=root_path,
        )
    if not branch:
        return _unknown_record(
            root_path,
            path,
            "",
            parent,
            "detached worktree cannot be associated with a branch",
        )
    return _classify_linked(root_path, path, branch, parent, entry, protected)


def classify(
    repo: Path | str,
    *,
    protected: Collection[str | Path] | str | Path | None = None,
) -> list[WorktreeRecord]:
    """Enumerate and classify every worktree Git reports for ``repo``."""
    repo_path = Path(repo).resolve()
    listing = _git(repo_path, "worktree", "list", "--porcelain", check=True)
    entries = _worktree_entries(listing.stdout)
    if not entries:
        return []

    # Git emits the primary worktree first.  Keeping that path rather than
    # treating the invocation cwd as root also works when --repo is linked.
    root_path = Path(entries[0]["path"]).resolve()
    try:
        branches = _local_branches(repo_path)
    except GitError:
        branches = {
            str(entry.get("branch", ""))
            for entry in entries
            if entry.get("branch")
        }
    protected_values = _protected_values(protected)
    return [
        _classify_entry(repo_path, root_path, entry, branches, protected_values)
        for entry in entries
    ]


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
    """Find the primary worktree, even when ``repo`` is a linked worktree."""
    result = _git(repo, "worktree", "list", "--porcelain")
    entries = _worktree_entries(result.stdout) if result.returncode == 0 else []
    if entries:
        return Path(entries[0]["path"]).resolve()
    result = _git(repo, "rev-parse", "--show-toplevel")
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return repo.resolve()


def _failure(result: subprocess.CompletedProcess[str], command: str) -> str:
    detail = (result.stderr or result.stdout).strip()
    return detail or f"{command} exited {result.returncode}"


def _branch_is_checked_out(repo: Path, branch: str) -> bool:
    """Fail closed if a fresh worktree inventory still uses ``branch``."""
    try:
        result = _git(repo, "worktree", "list", "--porcelain")
    except (GitError, OSError, ValueError):
        return True
    if result.returncode != 0:
        return True
    return any(entry.get("branch") == branch for entry in _worktree_entries(result.stdout))


def _proof_snapshot(repo: Path, record: WorktreeRecord) -> tuple[str | None, str | None, str | None]:
    """Obtain safe fallback evidence for records built by older callers."""
    proof_parent = record.proof_parent or record.parent
    proof_oid = record.proof_oid
    if proof_oid is None:
        if not is_merged(repo, record.branch, proof_parent):
            if proof_parent == "main" or not is_merged(repo, record.branch, "main"):
                return proof_parent, None, "record has no current landing proof"
            proof_parent = "main"
        proof_oid = _ref_oid(repo, proof_parent)
    return proof_parent, proof_oid, None


def _branch_snapshot_for_delete(
    repo: Path,
    record: WorktreeRecord,
) -> tuple[str | None, str | None]:
    try:
        current_oid = _ref_oid(repo, record.branch)
    except (GitError, OSError, ValueError) as exc:
        return f"cannot inspect branch: {exc}", None
    if current_oid is None:
        return None, None
    expected_oid = record.branch_oid or current_oid
    if current_oid != expected_oid:
        return "branch changed since classification", None
    return None, expected_oid


def _proof_for_delete(repo: Path, record: WorktreeRecord) -> tuple[str | None, str | None]:
    try:
        proof_parent, proof_oid, proof_error = _proof_snapshot(repo, record)
        current_proof_oid = _ref_oid(repo, proof_parent) if proof_parent else None
    except (GitError, OSError, ValueError) as exc:
        return f"cannot inspect landing proof: {exc}", None
    if proof_error is not None or proof_oid is None:
        return proof_error or "landing parent ref cannot be inspected", None
    if current_proof_oid != proof_oid:
        return "landing parent changed since classification", None
    return None, proof_parent


def _delete_ref(
    repo: Path,
    branch: str,
    expected_oid: str,
) -> tuple[str | None, bool]:
    try:
        deleted = _git(
            repo,
            "update-ref",
            "-d",
            f"refs/heads/{branch}",
            expected_oid,
        )
    except (GitError, OSError, ValueError) as exc:
        return f"cannot delete branch ref: {exc}", False
    if deleted.returncode == 0:
        return None, True
    try:
        branch_still_exists = _ref_oid(repo, branch) is not None
    except (GitError, OSError, ValueError):
        branch_still_exists = True
    if not branch_still_exists:
        return None, False
    return _failure(deleted, f"git update-ref -d refs/heads/{branch}"), False


def _delete_branch(repo: Path, record: WorktreeRecord) -> tuple[str | None, bool]:
    """Conditionally delete exactly the classified branch ref.

    The classifier accepts patch-equivalent rebases, which ``git branch -d``
    cannot prove against a linked parent.  ``git update-ref -d`` is used with
    both the captured branch OID and the unchanged landing-parent OID.  It
    never retargets the branch and therefore cannot lose its original commit.
    """
    if not record.branch:
        return "worktree has no branch ref", False
    branch_error, expected_oid = _branch_snapshot_for_delete(repo, record)
    if branch_error is not None or expected_oid is None:
        return branch_error, False
    proof_error, _proof_parent = _proof_for_delete(repo, record)
    if proof_error is not None:
        return proof_error, False
    if _branch_is_checked_out(repo, record.branch):
        return "branch is checked out by a worktree", False
    return _delete_ref(repo, record.branch, expected_oid)


def _validate_target(record: WorktreeRecord, repo: Path, current_path: Path) -> None:
    target = Path(record.path).resolve()
    if target == current_path or target in current_path.parents:
        raise RuntimeError(f"refusing to reap the current worktree: {target}")
    if target == _repository_root(repo):
        raise RuntimeError(f"refusing to reap the root worktree: {target}")


def _remove_worktree(
    record: WorktreeRecord,
    repo: Path,
    current_path: Path,
) -> tuple[str | None, bool]:
    """Remove one candidate without force and retain it for ref cleanup."""
    target = Path(record.path).resolve()
    _validate_target(record, repo, current_path)
    if not target.exists():
        return None, False
    removed = _git(repo, "worktree", "remove", "--", str(target))
    if removed.returncode != 0:
        return _failure(removed, "git worktree remove"), False
    return None, True


def _dependency_depth(
    record: WorktreeRecord,
    by_branch: dict[str, WorktreeRecord],
    trail: set[str],
) -> int:
    if record.branch in trail:
        return 0
    parent = by_branch.get(record.parent)
    if parent is None:
        return 0
    return 1 + _dependency_depth(parent, by_branch, trail | {record.branch})


def _ordered_pending(
    pending: list[tuple[WorktreeRecord, Path]],
) -> list[tuple[WorktreeRecord, Path]]:
    """Delete child refs before redundant parent refs."""
    by_branch = {record.branch: record for record, _repo in pending}
    return sorted(
        pending,
        key=lambda item: (
            -_dependency_depth(item[0], by_branch, set()),
            str(item[0].path),
        ),
    )


def _prepare_candidate(
    record: WorktreeRecord,
    current_path: Path,
    dry_run: bool,
) -> tuple[Path, Path, str | None, bool]:
    repo = _record_repo(record)
    if dry_run:
        _validate_target(record, repo, current_path)
        return Path(record.path).resolve(), repo, None, False
    error, did_remove = _remove_worktree(record, repo, current_path)
    return Path(record.path).resolve(), repo, error, did_remove


def apply(records: list[WorktreeRecord], *, dry_run: bool = True) -> dict[str, list[str]]:
    """Remove redundant clean worktrees and conditionally delete their refs."""
    result: dict[str, list[str]] = {"removed": [], "skipped": [], "errors": []}
    current_path = Path.cwd().resolve()
    pending: list[tuple[WorktreeRecord, Path]] = []
    removed_worktrees: set[str] = set()

    for record in records:
        target = Path(record.path).resolve()
        if record.status != "REDUNDANT" or record.protected:
            result["skipped"].append(str(target))
            continue
        try:
            target, repo, error, did_remove = _prepare_candidate(record, current_path, dry_run)
        except RuntimeError:
            raise
        except (GitError, OSError, ValueError) as exc:
            result["errors"].append(f"{target}: cannot resolve repository: {exc}")
            continue
        if error is not None:
            result["errors"].append(f"{target}: {error}")
            continue
        if dry_run:
            result["skipped"].append(str(target))
            continue
        if did_remove:
            removed_worktrees.add(str(target))
        pending.append((record, repo))

    for record, repo in _ordered_pending(pending):
        error, did_delete = _delete_branch(repo, record)
        target = str(Path(record.path).resolve())
        if error is not None:
            result["errors"].append(f"{target}: {error}")
            continue
        if did_delete or target in removed_worktrees:
            result["removed"].append(target)
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
        "--check",
        action="store_true",
        help="report redundancy; fail only when REAP_STRICT=1",
    )
    parser.add_argument(
        "--protect",
        action="append",
        default=[],
        metavar="PATH_OR_BRANCH",
        help="protect a worktree path or branch (repeatable)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit linked-worktree records as JSON",
    )
    return parser


def _strict_check() -> bool:
    return os.environ.get("REAP_STRICT", "").strip().lower() in {"1", "true", "yes"}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.apply and args.check:
        print("worktree-reap: --apply and --check cannot be combined", file=sys.stderr)
        return 1
    try:
        records = classify(args.repo, protected=args.protect)
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

    redundant = any(record.status == "REDUNDANT" for record in records)
    if args.check:
        return 3 if redundant and _strict_check() else 0
    if not args.apply:
        return 3 if redundant else 0

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
