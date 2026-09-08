#!/usr/bin/env python3
"""Classify and safely reap redundant linked Git worktrees.

The default CLI mode is an observational dry run.  A worktree is only a
reap candidate when it is clean and its branch is already represented by its
parent branch, either by reachability or by Git's patch-equivalence check.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import warnings
from collections.abc import Callable, Collection, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Literal

try:
    import fcntl
except ImportError:  # pragma: no cover - supported CI/production hosts are POSIX.
    fcntl = None

WorktreeStatus = Literal["REDUNDANT", "LIVE", "DIRTY", "ROOT", "UNKNOWN"]

# These are build products that may be recreated from tracked source.  The
# allowlist is deliberately path-shaped: a broad "ignored means disposable"
# rule would also remove models, dependency trees, and local infrastructure.
_REGENERABLE_IGNORED_DIRS = frozenset(
    {".pytest_cache", "__pycache__", ".ruff_cache", ".mypy_cache"}
)
_REGENERABLE_IGNORED_PATHS = frozenset({".task-state/.heartbeat"})
# The harness owns .task-state/ and writes its own bookkeeping there.  Naming
# each file one at a time rots on the next stamp the harness adds, so the rule
# is provenance-shaped: a lock, a heartbeat, or a sweep stamp under the
# harness's own directory is regenerable by construction.
_HARNESS_SCRATCH_ROOT = ".task-state"
_HARNESS_SCRATCH_DIRS = frozenset({".heartbeat", ".locks"})
_HARNESS_SCRATCH_SUFFIXES = (".stamp", ".lock", ".pid")

# A lane row in any non-terminal state still owns its worktree.  Containment
# and cleanliness cannot distinguish a finished lane from a freshly
# re-dispatched one: both are landed, clean, and about to be written to.
_TERMINAL_LANE_STATUSES = frozenset({"closed", "closed_stale", "merged"})

# The registry paginates.  A truncated page would silently under-report
# ownership, so the reader demands the whole set or fails closed.
_LANE_PAGE_LIMIT = 5000


class GitError(RuntimeError):
    """A Git command could not be run or returned an unexpected failure."""


class ReapLockError(RuntimeError):
    """Another reaper owns the repository mutation lock."""


class LaneStateError(RuntimeError):
    """Live lane ownership could not be determined."""


class RegistryBackendUnavailable(LaneStateError):
    """The handoff registry package cannot be imported."""


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
    allow_ignored: bool = field(default=False, repr=False, compare=False)
    # A reclaim receipt must distinguish "ownership checked, none found" from
    # "ownership never checked".  A bare status cannot say which.
    lane_verified: bool = field(default=True, repr=False, compare=False)


def _git(
    repo: Path,
    *args: str,
    check: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run Git rooted at ``repo`` and optionally raise on command failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
            input=input_text,
        )
    except OSError as exc:
        raise GitError(f"could not run git: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitError(detail or f"git {' '.join(args)} exited {result.returncode}")
    return result


def _common_git_dir(repo: Path) -> Path:
    """Return the shared Git directory used by every linked worktree."""
    result = _git(repo, "rev-parse", "--git-common-dir")
    if result.returncode != 0 or not result.stdout.strip():
        raise GitError(_failure(result, "git rev-parse --git-common-dir"))
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = (repo / common_dir).resolve()
    return common_dir


@contextmanager
def _repository_lock(repo: Path | str):
    """Hold a non-blocking shared-repository lock for a mutation run."""
    repo_path = Path(repo).resolve()
    if fcntl is None:
        raise ReapLockError("cannot acquire repository lock: POSIX flock is unavailable")
    try:
        lock_path = _common_git_dir(repo_path) / "worktree-reap.lock"
    except (GitError, OSError, ValueError) as exc:
        raise ReapLockError(f"cannot resolve repository lock: {exc}") from exc
    try:
        handle = lock_path.open("a+")
    except OSError as exc:
        raise ReapLockError(f"cannot open repository lock {lock_path}: {exc}") from exc
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReapLockError(f"another worktree reaper holds {lock_path}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


@contextmanager
def _locked_repositories(records: Collection[WorktreeRecord]):
    """Acquire all candidate repository locks in a stable order."""
    repositories = sorted(
        {
            _record_repo(record)
            for record in records
        },
        key=str,
    )
    with ExitStack() as stack:
        for repo in repositories:
            stack.enter_context(_repository_lock(repo))
        yield


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
        elif line.startswith("HEAD "):
            current["head"] = line.removeprefix("HEAD ").strip()
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


def _merged_state(
    repo: Path,
    branch: str,
    parent: str,
) -> tuple[bool | None, str | None]:
    """Return landed, not-landed, or unknown for one Git reachability check."""
    try:
        ancestor = _git(repo, "merge-base", "--is-ancestor", branch, parent)
        if ancestor.returncode == 0:
            return True, None
        if ancestor.returncode != 1:
            return None, _failure(ancestor, "git merge-base --is-ancestor")

        cherry = _git(repo, "cherry", parent, branch)
        if cherry.returncode != 0:
            return None, _failure(cherry, "git cherry")
        return all(line.startswith("-") for line in cherry.stdout.splitlines()), None
    except (GitError, OSError, ValueError) as exc:
        return None, str(exc)


def is_merged(repo: Path | str, branch: str, parent: str) -> bool:
    """Return whether ``branch`` is landed in ``parent``.

    Reachability is the primary predicate.  When a branch was rebased, the
    commit IDs can differ while the patches remain equivalent, so the Git
    cherry fallback is also required.  Git failures remain a safe ``False``
    for this boolean helper; classification uses ``_merged_state`` so that it
    can report those failures as ``UNKNOWN`` instead of ``LIVE``.
    """
    repo_path = Path(repo).resolve()
    merged, _reason = _merged_state(repo_path, branch, parent)
    return merged is True


def _lane_owners_from_rows(rows: Collection[object]) -> dict[Path, str]:
    """Reduce lane registry rows to the worktrees they still own."""
    owners: dict[Path, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise LaneStateError("lane registry returned a malformed row")
        status = str(row.get("status") or "").strip().lower()
        if not status:
            raise LaneStateError(f"lane {row.get('lane_id')!r} has no status")
        if status in _TERMINAL_LANE_STATUSES:
            continue
        worktree_path = row.get("worktree_path")
        if worktree_path is None or not str(worktree_path).strip():
            raise LaneStateError(
                f"lane {row.get('lane_id')!r} has no usable worktree_path"
            )
        try:
            resolved = Path(str(worktree_path)).expanduser().resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise LaneStateError(
                f"lane {row.get('lane_id')!r} has no usable worktree_path: {exc}"
            ) from exc
        owners.setdefault(resolved, str(row.get("lane_id") or "unnamed lane"))
    return owners


def active_lane_paths(repo: Path | str) -> dict[Path, str]:
    """Return ``{worktree path: lane id}`` for every lane that still owns a tree.

    The lane registry is the authority on liveness.  Heartbeats and locks are
    corroborating signals at best: a lane that has not yet written its first
    byte has neither, and its worktree is indistinguishable from a reclaimable
    one by branch containment alone.

    Raises ``LaneStateError`` when ownership cannot be read, so the caller can
    fail closed instead of reclaiming a tree it cannot account for.
    """
    try:
        from workbay_handoff_mcp import RuntimeConfig, configure_runtime
        from workbay_handoff_mcp.lanes_recording import list_lanes
    except ImportError as exc:  # pragma: no cover - exercised via injection
        raise RegistryBackendUnavailable(
            "registry backend unavailable; run via `make worktree-reap*`"
        ) from exc

    repo_path = Path(repo).resolve()
    try:
        configure_runtime(RuntimeConfig.for_repo(repo_path))
        response = list_lanes(all_tasks=True, limit=_LANE_PAGE_LIMIT)
        if not isinstance(response, Mapping):
            raise LaneStateError("lane registry response is not a mapping")
        if not response.get("ok"):
            raise LaneStateError("lane registry response was not ok")
        data = response.get("data")
        if not isinstance(data, Mapping):
            raise LaneStateError("lane registry response data is not a mapping")
        rows = data.get("lanes")
        if not isinstance(rows, list):
            raise LaneStateError("lane registry response data.lanes is not a list")
        if data.get("has_more"):
            raise LaneStateError("lane registry response was truncated: data.has_more")
        return _lane_owners_from_rows(rows)
    except LaneStateError:
        raise
    except Exception as exc:  # noqa: BLE001 - any failure must fail closed
        raise LaneStateError(f"cannot read lane registry: {exc}") from exc


def _lane_ownership_block(repo: Path, target: Path) -> str | None:
    """Return a fail-closed reason if mutation must not proceed."""
    try:
        owners = active_lane_paths(repo)
    except LaneStateError as exc:
        return f"lane ownership unreadable: {exc}"
    lane_id = owners.get(Path(target).resolve())
    if lane_id is not None:
        return f"active lane {lane_id} owns worktree"
    return None


def _is_harness_scratch(parts: tuple[str, ...]) -> bool:
    """Return whether one path is harness bookkeeping under .task-state/."""
    for index, part in enumerate(parts):
        if part != _HARNESS_SCRATCH_ROOT:
            continue
        remainder = parts[index + 1 :]
        if not remainder:
            continue
        if remainder[0] in _HARNESS_SCRATCH_DIRS:
            return True
        # Only the leaf is checked: a stamp is a file the harness rewrites,
        # never a directory whose contents someone else may own.
        if len(remainder) == 1 and remainder[0].endswith(_HARNESS_SCRATCH_SUFFIXES):
            return True
    return False


def _is_regenerable_ignored(relative_path: str) -> bool:
    """Return whether one ignored path is an explicitly disposable product."""
    normalized = relative_path.replace("\\", "/").rstrip("/")
    if normalized in _REGENERABLE_IGNORED_PATHS:
        return True
    parts = PurePosixPath(normalized).parts
    if any(part in _REGENERABLE_IGNORED_DIRS for part in parts):
        return True
    return _is_harness_scratch(parts)


def _worktree_status(path: Path | str) -> tuple[bool, tuple[str, ...]]:
    """Return real dirtiness and every ignored path found in a worktree."""
    path_obj = Path(path).resolve()
    result = _git(
        path_obj,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignored",
        "-z",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitError(detail or f"cannot inspect worktree {path_obj}")
    ignored: list[str] = []
    dirty = False
    for entry in result.stdout.split("\0"):
        if not entry:
            continue
        status = entry[:2]
        entry_path = entry[3:] if len(entry) > 3 and entry[2] == " " else entry[2:]
        if status == "!!":
            ignored.append(entry_path)
        else:
            dirty = True
    return dirty, tuple(ignored)


def is_dirty(path: Path | str) -> bool:
    """Return whether a worktree has tracked or untracked changes.

    Ignored-only content is reported separately because it is removable only
    when the caller explicitly opts into ``allow_ignored``.
    """
    dirty, _ignored = _worktree_status(path)
    return dirty


def _env_protected_values() -> tuple[str, ...]:
    """Read protection values from REAP_PROTECT, one per line.

    Make cannot pass a repeatable option without word-splitting, which turns a
    worktree path containing a space into two useless fragments and silently
    drops the fence.  A newline-delimited environment variable survives intact.
    """
    raw = os.environ.get("REAP_PROTECT", "")
    return tuple(value for value in (line.strip() for line in raw.splitlines()) if value)


def _protected_values(protected: Collection[str | Path] | str | Path | None) -> tuple[str, ...]:
    explicit: tuple[str, ...]
    if protected is None:
        explicit = ()
    elif isinstance(protected, (str, Path)):
        explicit = (str(protected),)
    else:
        explicit = tuple(str(value) for value in protected)
    return explicit + _env_protected_values()


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
    allow_ignored: bool = False,
    lane_verified: bool = True,
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
        allow_ignored=allow_ignored,
        lane_verified=lane_verified,
    )


def _landing_status(
    repo: Path,
    branch: str,
    parent: str,
) -> tuple[str | None, str | None]:
    """Return the branch proving landing, or an inspection failure."""
    candidates = [parent] if parent == "main" else [parent, "main"]
    unknown: list[str] = []
    for candidate in candidates:
        merged, reason = _merged_state(repo, branch, candidate)
        if merged is True:
            return candidate, None
        if merged is None:
            unknown.append(f"{candidate}: {reason or 'Git inspection failed'}")
    if unknown:
        return None, "cannot determine landing state (" + "; ".join(unknown) + ")"
    return None, None


def _landing_branch(repo: Path, branch: str, parent: str) -> str | None:
    """Return the integration branch that proves ``branch`` redundant."""
    landing, _reason = _landing_status(repo, branch, parent)
    return landing


def _landing_proof(
    repo: Path,
    branch: str,
    parent: str,
) -> tuple[str | None, str | None, str | None]:
    """Capture the landing branch and its OID, or a safe inspection result."""
    candidates = [parent] if parent == "main" else [parent, "main"]
    captured: list[tuple[str, str]] = []
    for candidate in candidates:
        proof_oid = _ref_oid(repo, candidate)
        if proof_oid is None:
            return None, None, f"landing parent ref cannot be inspected: {candidate}"
        captured.append((candidate, proof_oid))

    unknown: list[str] = []
    for candidate, proof_oid in captured:
        # The parent OID is deliberately passed to Git instead of the ref
        # name.  A ref rewrite after capture must not change the proof.
        merged, reason = _merged_state(repo, branch, proof_oid)
        if merged is True:
            return candidate, proof_oid, None
        if merged is None:
            unknown.append(f"{candidate}: {reason or 'Git inspection failed'}")
    if unknown:
        return None, None, "cannot determine landing state (" + "; ".join(unknown) + ")"
    return None, None, None


def _classify_clean(
    repo: Path,
    path: Path,
    branch: str,
    parent: str,
    branch_oid: str,
    allow_ignored: bool,
) -> WorktreeRecord:
    try:
        proof_parent, proof_oid, landing_error = _landing_proof(repo, branch, parent)
        branch_unchanged = _ref_oid(repo, branch) == branch_oid
    except (GitError, OSError, ValueError) as exc:
        return _unknown_record(repo, path, branch, parent, f"cannot capture landing proof: {exc}")
    if not branch_unchanged:
        return _unknown_record(repo, path, branch, parent, "branch changed during classification")
    if landing_error is not None:
        return _unknown_record(repo, path, branch, parent, landing_error)
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
            allow_ignored=allow_ignored,
        )
    return _state_record(
        repo,
        path,
        branch,
        parent,
        "LIVE",
        f"{branch} is not landed in {parent}",
        branch_oid=branch_oid,
        allow_ignored=allow_ignored,
    )


def _classify_observed(
    repo: Path,
    path: Path,
    branch: str,
    parent: str,
    branch_oid: str,
    dirty: bool,
    ignored_paths: Collection[str],
    protected: bool,
    allow_ignored: bool,
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
            allow_ignored=allow_ignored,
        )
    if dirty:
        return _state_record(
            repo,
            path,
            branch,
            parent,
            "DIRTY",
            "worktree has tracked or untracked changes",
            branch_oid=branch_oid,
            allow_ignored=allow_ignored,
        )
    unsafe_ignored = tuple(
        path for path in ignored_paths if not _is_regenerable_ignored(path)
    )
    if unsafe_ignored and not allow_ignored:
        return _state_record(
            repo,
            path,
            branch,
            parent,
            "DIRTY",
            "worktree has non-regenerable ignored changes: "
            + ", ".join(unsafe_ignored)
            + "; pass --allow-ignored to opt in",
            branch_oid=branch_oid,
            allow_ignored=allow_ignored,
        )
    return _classify_clean(repo, path, branch, parent, branch_oid, allow_ignored)


def _classify_linked(
    repo: Path,
    path: Path,
    branch: str,
    parent: str,
    entry: dict[str, object],
    protected: tuple[str, ...],
    allow_ignored: bool,
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
        dirty, ignored_paths = _worktree_status(path)
    except (GitError, OSError, ValueError) as exc:
        return _unknown_record(repo, path, branch, parent, f"cannot inspect worktree: {exc}")

    return _classify_observed(
        repo,
        path,
        branch,
        parent,
        branch_oid,
        dirty,
        ignored_paths,
        _is_protected(repo, path, branch, protected),
        allow_ignored,
    )


def _missing_feature_parent(branch: str, branches: Collection[str]) -> str | None:
    """Return an absent feature parent when the branch name implies one."""
    if not branch.startswith("feature/"):
        return None
    value = branch.removeprefix("feature/")
    candidates = _candidate_prefixes("feature/", value, include_full=False)
    if not candidates or any(candidate in branches for candidate in candidates):
        return None
    return candidates[0]


def _classify_entry(
    repo: Path,
    root_path: Path,
    entry: dict[str, object],
    branches: set[str],
    protected: tuple[str, ...],
    allow_ignored: bool,
    lane_owners: Mapping[Path, str],
    lane_error: str | None,
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
    # Ownership outranks every observation below it.  A lane may be mid-write
    # in a tree that is clean and landed at this instant.
    if lane_error is not None:
        return _unknown_record(
            root_path, path, branch, parent, f"lane state unreadable: {lane_error}"
        )
    lane_id = lane_owners.get(path)
    if lane_id is not None:
        return _state_record(
            root_path,
            path,
            branch,
            parent,
            "LIVE",
            f"active lane {lane_id}",
            protected=True,
            allow_ignored=allow_ignored,
        )
    missing_parent = _missing_feature_parent(branch, branches)
    if missing_parent is not None and not _is_protected(repo, path, branch, protected):
        return _unknown_record(
            root_path,
            path,
            branch,
            missing_parent,
            f"expected parent branch is missing: {missing_parent}",
        )
    if not branch:
        return _unknown_record(
            root_path,
            path,
            "",
            parent,
            "detached worktree cannot be associated with a branch",
        )
    return _classify_linked(
        root_path,
        path,
        branch,
        parent,
        entry,
        protected,
        allow_ignored,
    )


def classify(
    repo: Path | str,
    *,
    protected: Collection[str | Path] | str | Path | None = None,
    allow_ignored: bool = False,
    lane_lookup: Callable[[Path], Mapping[Path, str]] | None = None,
    require_lane_state: bool = True,
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

    lane_owners: Mapping[Path, str] = {}
    lane_error: str | None = None
    lane_verified = True
    try:
        lane_owners = (lane_lookup or active_lane_paths)(repo_path)
    except RegistryBackendUnavailable as exc:
        # A missing backend is not an advisory UNKNOWN pass.  Inspection may
        # opt in with require_lane_state=False; mutation still refuses later.
        if require_lane_state:
            raise
        lane_verified = False
        warnings.warn(
            f"reaping without lane-state verification: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
    except LaneStateError as exc:
        # Fail closed by default: an unreadable registry means every linked
        # worktree might be owned, and reclaiming one would be unrecoverable.
        if require_lane_state:
            lane_verified = False
            lane_error = str(exc)
        else:
            lane_verified = False
            warnings.warn(
                f"reaping without lane-state verification: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )

    records = [
        _classify_entry(
            repo_path,
            root_path,
            entry,
            branches,
            protected_values,
            allow_ignored,
            lane_owners,
            lane_error,
        )
        for entry in entries
    ]
    if lane_verified:
        return records
    # Carry the unexamined state on every record rather than dropping it: a
    # status that looks identical either way is how a reclaimer reports
    # success at the moment it is failing.
    return [replace(record, lane_verified=False) for record in records]


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


def _intent_path(repo: Path) -> Path:
    return _common_git_dir(repo) / "worktree-reap.intent.json"


def _fsync_directory(directory: Path) -> None:
    file_descriptor = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)


def _write_intent(
    repo: Path,
    record: WorktreeRecord,
    target: Path,
    phase: str,
) -> str | None:
    """Durably record the identity authorized for the next mutation."""
    intent_path: Path | None = None
    temporary_path: Path | None = None
    try:
        intent_path = _intent_path(repo)
        payload = {
            "repo": str(repo.resolve()),
            "target": str(target.resolve()),
            "branch": record.branch,
            "parent": record.parent,
            "branch_oid": record.branch_oid,
            "proof_parent": record.proof_parent,
            "proof_oid": record.proof_oid,
            "phase": phase,
            "allow_ignored": record.allow_ignored,
        }
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{intent_path.name}.",
            dir=str(intent_path.parent),
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, intent_path)
        temporary_path = None
        _fsync_directory(intent_path.parent)
    except (OSError, TypeError, ValueError) as exc:
        return f"cannot durably record reaper intent: {exc}"
    finally:
        if temporary_path is not None:
            with contextlib.suppress(OSError):
                temporary_path.unlink()
    return None


def _read_intent(repo: Path) -> tuple[dict[str, object] | None, str | None]:
    """Read a prior intent, refusing malformed state instead of ignoring it."""
    try:
        intent_path = _intent_path(repo)
        if not intent_path.exists():
            return None, None
        value = json.loads(intent_path.read_text(encoding="utf-8"))
    except (GitError, OSError, TypeError, ValueError) as exc:
        return None, f"cannot inspect reaper intent: {exc}"
    if not isinstance(value, dict):
        return None, "cannot inspect reaper intent: expected a JSON object"
    return value, None


def _intent_matches(
    intent: dict[str, object],
    repo: Path,
    record: WorktreeRecord,
    target: Path,
) -> bool:
    required = {
        "repo": str(repo.resolve()),
        "target": str(target.resolve()),
        "branch": record.branch,
    }
    if any(intent.get(key) != value for key, value in required.items()):
        return False
    for key in ("branch_oid", "proof_parent", "proof_oid"):
        expected = getattr(record, key)
        if expected is not None and intent.get(key) != expected:
            return False
    return True


def _record_from_intent(
    repo: Path,
    intent: dict[str, object],
) -> tuple[WorktreeRecord | None, str | None]:
    """Build a recovery record only from a complete, local intent snapshot."""
    required = ("repo", "target", "branch", "parent", "branch_oid", "proof_parent", "proof_oid")
    if any(not isinstance(intent.get(key), str) for key in required):
        return None, "cannot recover reaper intent: incomplete identity snapshot"
    if intent["repo"] != str(repo.resolve()):
        return None, "cannot recover reaper intent: repository identity changed"
    target = Path(intent["target"])
    if not target.is_absolute():
        return None, "cannot recover reaper intent: target path is not absolute"
    phase = intent.get("phase")
    if phase not in {"prepared", "worktree-removed"}:
        return None, "cannot recover reaper intent: unknown phase"
    allow_ignored = intent.get("allow_ignored", False)
    if not isinstance(allow_ignored, bool):
        return None, "cannot recover reaper intent: invalid allow-ignored flag"
    return (
        WorktreeRecord(
            path=target,
            branch=str(intent["branch"]),
            parent=str(intent["parent"]),
            status="REDUNDANT",
            reason="recovered from durable reaper intent",
            repo=repo,
            branch_oid=str(intent["branch_oid"]),
            proof_parent=str(intent["proof_parent"]),
            proof_oid=str(intent["proof_oid"]),
            allow_ignored=allow_ignored,
        ),
        None,
    )


def _recover_intent_records(
    records: list[WorktreeRecord],
) -> tuple[list[WorktreeRecord], list[str]]:
    """Add an interrupted mutation to a fresh classification for safe retry."""
    recovered = list(records)
    errors: list[str] = []
    repositories = {_record_repo(record) for record in records}
    for repo in repositories:
        intent, intent_error = _read_intent(repo)
        if intent_error is not None:
            errors.append(f"{repo}: {intent_error}")
            continue
        if intent is None:
            continue
        recovery, recovery_error = _record_from_intent(repo, intent)
        if recovery_error is not None:
            errors.append(f"{repo}: {recovery_error}")
            continue
        assert recovery is not None
        recovery_target = Path(recovery.path).resolve()
        ownership_error = _lane_ownership_block(repo, recovery_target)
        if ownership_error is not None:
            errors.append(f"{recovery_target}: {ownership_error}")
            continue
        recovery = replace(recovery, lane_verified=True)
        if not any(
            _intent_matches(intent, repo, record, Path(record.path).resolve())
            for record in recovered
        ):
            recovered.append(recovery)
    return recovered, errors


def _clear_intent(repo: Path) -> str | None:
    try:
        intent_path = _intent_path(repo)
        if not intent_path.exists():
            return None
        intent_path.unlink()
        _fsync_directory(intent_path.parent)
    except (GitError, OSError, ValueError) as exc:
        return f"cannot clear reaper intent: {exc}"
    return None


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
    if record.proof_parent is not None and record.proof_oid is not None:
        return record.proof_parent, record.proof_oid, None
    proof_parent, proof_oid, proof_error = _landing_proof(
        repo,
        record.branch,
        record.parent,
    )
    return proof_parent, proof_oid, proof_error


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


def _proof_for_delete(
    repo: Path,
    record: WorktreeRecord,
) -> tuple[str | None, str | None, str | None]:
    try:
        proof_parent, proof_oid, proof_error = _proof_snapshot(repo, record)
        current_proof_oid = _ref_oid(repo, proof_parent) if proof_parent else None
    except (GitError, OSError, ValueError) as exc:
        return f"cannot inspect landing proof: {exc}", None, None
    if proof_error is not None or proof_oid is None:
        return proof_error or "landing parent ref cannot be inspected", None, None
    if current_proof_oid != proof_oid:
        return "landing parent changed since classification", None, None
    return None, proof_parent, proof_oid


def _delete_ref(
    repo: Path,
    branch: str,
    expected_oid: str,
    proof_parent: str | None = None,
    proof_oid: str | None = None,
) -> tuple[str | None, bool]:
    """Delete a branch only while both its OID and landing proof are stable."""
    if proof_parent is None or proof_oid is None:
        return "landing proof is required for conditional branch deletion", False
    commands = (
        f"verify refs/heads/{proof_parent} {proof_oid}",
        f"delete refs/heads/{branch} {expected_oid}",
    )
    try:
        deleted = _git(
            repo,
            "update-ref",
            "--stdin",
            input_text="\n".join(commands) + "\n",
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
    return _failure(deleted, f"git update-ref refs/heads/{branch}"), False


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
    proof_error, proof_parent, proof_oid = _proof_for_delete(repo, record)
    if proof_error is not None or proof_parent is None or proof_oid is None:
        return proof_error, False
    if _branch_is_checked_out(repo, record.branch):
        return "branch is checked out by a worktree", False
    return _delete_ref(repo, record.branch, expected_oid, proof_parent, proof_oid)


def _validate_target(record: WorktreeRecord, repo: Path, current_path: Path) -> None:
    target = Path(record.path).resolve()
    if target == current_path or target in current_path.parents:
        raise RuntimeError(f"refusing to reap the current worktree: {target}")
    if target == _repository_root(repo):
        raise RuntimeError(f"refusing to reap the root worktree: {target}")


def _binding_error(
    repo: Path,
    target: Path,
    branch: str,
    expected_oid: str | None = None,
) -> str | None:
    """Ensure a live path still belongs to the classified branch."""
    try:
        listing = _git(repo, "worktree", "list", "--porcelain")
    except (GitError, OSError, ValueError) as exc:
        return f"cannot inspect worktree binding: {exc}"
    if listing.returncode != 0:
        return _failure(listing, "git worktree list")
    matches = [
        entry
        for entry in _worktree_entries(listing.stdout)
        if Path(entry["path"]).resolve() == target
    ]
    if not matches:
        return f"worktree path no longer maps to {branch}"
    if len(matches) != 1:
        return f"worktree path has {len(matches)} Git registrations"
    actual_branch = str(matches[0].get("branch", ""))
    if actual_branch != branch:
        return f"worktree path now maps to {actual_branch or 'a detached worktree'}"
    if expected_oid is not None and matches[0].get("head") != expected_oid:
        return "worktree HEAD changed since classification"
    if matches[0].get("locked") or matches[0].get("prunable"):
        return "worktree is locked or prunable"
    return None


@dataclass(frozen=True)
class _CandidatePlan:
    record: WorktreeRecord
    repo: Path
    target: Path
    stale: bool = False
    worktree_removed: bool = False


def _plan_candidate(
    record: WorktreeRecord,
    repo: Path,
    current_path: Path,
) -> tuple[_CandidatePlan | None, str | None]:
    """Validate one candidate without mutating Git or the filesystem."""
    target = Path(record.path).resolve()
    _validate_target(record, repo, current_path)
    if not record.lane_verified:
        return None, "lane ownership was not verified"
    ownership_error = _lane_ownership_block(repo, target)
    if ownership_error is not None:
        return None, ownership_error

    target_exists = target.exists()
    branch_error, expected_oid = _branch_snapshot_for_delete(repo, record)
    if branch_error is not None:
        return None, branch_error
    if expected_oid is None:
        # A retry after a successful reap is intentionally idempotent.  A
        # missing path plus a missing branch is the only stale state accepted.
        if not target_exists:
            intent, intent_error = _read_intent(repo)
            if intent_error is not None:
                return None, intent_error
            if intent is not None and _intent_matches(intent, repo, record, target):
                clear_error = _clear_intent(repo)
                if clear_error is not None:
                    return None, clear_error
            return _CandidatePlan(record, repo, target, stale=True), None
        return None, "branch ref cannot be inspected while worktree still exists"

    if not target_exists:
        intent, intent_error = _read_intent(repo)
        if intent_error is not None:
            return None, intent_error
        if intent is None or not _intent_matches(intent, repo, record, target):
            return None, "worktree path disappeared since classification"
        proof_error, proof_parent, proof_oid = _proof_for_delete(repo, record)
        if proof_error is not None or proof_parent is None or proof_oid is None:
            return None, proof_error or "landing proof cannot be inspected"
        return _CandidatePlan(record, repo, target, worktree_removed=True), None

    binding_error = _binding_error(repo, target, record.branch, expected_oid)
    if binding_error is not None:
        return None, binding_error

    try:
        dirty, ignored_paths = _worktree_status(target)
    except (GitError, OSError, ValueError) as exc:
        return None, f"cannot inspect worktree before removal: {exc}"
    if dirty:
        return None, "worktree became dirty since classification"
    unsafe_ignored = tuple(
        path for path in ignored_paths if not _is_regenerable_ignored(path)
    )
    if unsafe_ignored and not record.allow_ignored:
        return (
            None,
            "worktree gained non-regenerable ignored changes: "
            + ", ".join(unsafe_ignored)
            + "; refusing removal",
        )

    proof_error, proof_parent, proof_oid = _proof_for_delete(repo, record)
    if proof_error is not None or proof_parent is None or proof_oid is None:
        return None, proof_error or "landing proof cannot be inspected"
    return _CandidatePlan(record, repo, target), None


def _restore_if_lane_claimed(
    record: WorktreeRecord,
    repo: Path,
    target: Path,
) -> tuple[str | None, bool]:
    """Restore a removed worktree if ownership appeared during removal."""
    # WHY: lane registration and Git worktree removal do not share a fence in
    # this repository; this is detect-and-undo compensation, not a lock.
    lane_id: str
    try:
        owners = active_lane_paths(repo)
    except LaneStateError as exc:
        lane_id = "unknown (registry unreadable)"
        ownership_error = f"lane ownership unreadable after removal: {exc}"
    else:
        lane_id = owners.get(target, "")
        if not lane_id:
            return None, False
        ownership_error = f"active lane {lane_id} registered during removal"

    branch_oid = record.branch_oid
    if branch_oid is None:
        try:
            branch_oid = _ref_oid(repo, record.branch)
        except (GitError, OSError, ValueError):
            branch_oid = None
    branch_oid = branch_oid or "unknown"
    try:
        restored = _git(repo, "worktree", "add", "--", str(target), record.branch)
    except (GitError, OSError, ValueError) as exc:
        return (
            f"{ownership_error}; failed to restore worktree {target} for lane "
            f"{lane_id}, branch OID {branch_oid}: {exc}",
            False,
        )
    if restored.returncode != 0:
        return (
            f"{ownership_error}; failed to restore worktree {target} for lane "
            f"{lane_id}, branch OID {branch_oid}: "
            f"{_failure(restored, 'git worktree add')}",
            False,
        )
    return (
        f"{ownership_error}; restored worktree {target} for lane {lane_id}, "
        f"branch OID {branch_oid}; branch deletion refused",
        True,
    )


def _remove_worktree(
    record: WorktreeRecord,
    repo: Path,
    current_path: Path,
) -> tuple[str | None, bool, _CandidatePlan | None]:
    """Remove one candidate without force and retain it for ref cleanup."""
    plan, error = _plan_candidate(record, repo, current_path)
    if error is not None:
        return error, False, plan
    if plan is None or plan.stale:
        return None, False, plan
    if plan.worktree_removed:
        ownership_error, restored = _restore_if_lane_claimed(
            record, repo, Path(record.path).resolve()
        )
        if ownership_error is not None:
            if restored:
                clear_error = _clear_intent(repo)
                if clear_error is not None:
                    ownership_error += f"; {clear_error}"
            return ownership_error, True, plan
        return None, True, plan
    intent_error = _write_intent(repo, record, plan.target, "prepared")
    if intent_error is not None:
        return intent_error, False, plan
    branch_error, expected_oid = _branch_snapshot_for_delete(repo, record)
    if branch_error is not None or expected_oid is None:
        error = branch_error or "branch ref cannot be inspected immediately before removal"
        clear_error = _clear_intent(repo)
        if clear_error is not None:
            error += f"; {clear_error}"
        return error, False, plan
    binding_error = _binding_error(repo, plan.target, record.branch, expected_oid)
    if binding_error is not None:
        clear_error = _clear_intent(repo)
        error = f"{binding_error} immediately before removal"
        if clear_error is not None:
            error += f"; {clear_error}"
        return error, False, plan
    proof_error, proof_parent, proof_oid = _proof_for_delete(repo, record)
    if proof_error is not None or proof_parent is None or proof_oid is None:
        error = proof_error or "landing proof cannot be inspected immediately before removal"
        clear_error = _clear_intent(repo)
        if clear_error is not None:
            error += f"; {clear_error}"
        return error, False, plan
    try:
        dirty, ignored_paths = _worktree_status(plan.target)
    except (GitError, OSError, ValueError) as exc:
        clear_error = _clear_intent(repo)
        error = f"cannot inspect worktree immediately before removal: {exc}"
        if clear_error is not None:
            error += f"; {clear_error}"
        return error, False, plan
    unsafe_ignored = tuple(
        path for path in ignored_paths if not _is_regenerable_ignored(path)
    )
    if dirty or (unsafe_ignored and not record.allow_ignored):
        if dirty:
            error = "worktree became dirty immediately before removal"
        else:
            error = (
                "worktree gained non-regenerable ignored changes immediately "
                "before removal: "
                + ", ".join(unsafe_ignored)
            )
        clear_error = _clear_intent(repo)
        if clear_error is not None:
            error += f"; {clear_error}"
        return error, False, plan
    ownership_error = _lane_ownership_block(repo, plan.target)
    if ownership_error is not None:
        clear_error = _clear_intent(repo)
        error = ownership_error
        if clear_error is not None:
            error += f"; {clear_error}"
        return error, False, plan
    removed = _git(repo, "worktree", "remove", "--", str(plan.target))
    if removed.returncode != 0:
        clear_error = _clear_intent(repo)
        error = _failure(removed, "git worktree remove")
        if clear_error is not None:
            error += f"; {clear_error}"
        return error, False, plan
    ownership_error, restored = _restore_if_lane_claimed(
        record, repo, Path(record.path).resolve()
    )
    if ownership_error is not None:
        if restored:
            clear_error = _clear_intent(repo)
            if clear_error is not None:
                ownership_error += f"; {clear_error}"
        return ownership_error, True, plan
    intent_error = _write_intent(repo, record, plan.target, "worktree-removed")
    if intent_error is not None:
        return (
            f"worktree removed but {intent_error}; branch deletion deferred",
            True,
            plan,
        )
    return None, True, plan


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


def _apply_unlocked(
    records: list[WorktreeRecord],
    *,
    dry_run: bool = True,
    initial_errors: Collection[str] = (),
) -> dict[str, list[str]]:
    """Remove redundant worktrees after a complete, non-mutating preflight."""
    result: dict[str, list[str]] = {"removed": [], "skipped": [], "errors": []}
    current_path = Path.cwd().resolve()
    candidates: list[tuple[WorktreeRecord, Path, Path]] = []
    preflight_errors: list[str] = list(initial_errors)

    for record in records:
        target = Path(record.path).resolve()
        if record.status != "REDUNDANT" or record.protected:
            result["skipped"].append(str(target))
            continue
        try:
            repo = _record_repo(record)
            if dry_run:
                _validate_target(record, repo, current_path)
                candidates.append((record, repo, target))
            else:
                plan, error = _plan_candidate(record, repo, current_path)
                if error is not None:
                    preflight_errors.append(f"{target}: {error}")
                elif plan is not None and not plan.stale:
                    candidates.append((record, repo, target))
                else:
                    result["skipped"].append(str(target))
        except RuntimeError:
            raise
        except (GitError, OSError, ValueError) as exc:
            preflight_errors.append(f"{target}: cannot resolve repository: {exc}")

    if dry_run:
        result["errors"].extend(preflight_errors)
        result["skipped"].extend(str(target) for _record, _repo, target in candidates)
        return result
    if preflight_errors:
        result["errors"].extend(preflight_errors)
        result["skipped"].extend(str(target) for _record, _repo, target in candidates)
        return result

    ordered_candidates = _ordered_pending(
        [(record, repo) for record, repo, _target in candidates]
    )
    removed_worktrees: set[str] = set()

    for index, (record, repo) in enumerate(ordered_candidates):
        target = str(Path(record.path).resolve())
        error, did_remove, _plan = _remove_worktree(record, repo, current_path)
        if error is not None:
            result["errors"].append(f"{target}: {error}")
            result["skipped"].extend(
                str(Path(remaining.path).resolve())
                for remaining, _remaining_repo in ordered_candidates[index + 1 :]
            )
            break
        if did_remove:
            removed_worktrees.add(target)
        ownership_error, restored = _restore_if_lane_claimed(
            record, repo, Path(record.path).resolve()
        )
        if ownership_error is not None:
            if restored:
                clear_error = _clear_intent(repo)
                if clear_error is not None:
                    ownership_error += f"; {clear_error}"
            result["errors"].append(f"{target}: {ownership_error}")
            result["skipped"].extend(
                str(Path(remaining.path).resolve())
                for remaining, _remaining_repo in ordered_candidates[index + 1 :]
            )
            break
        error, did_delete = _delete_branch(repo, record)
        if error is not None:
            result["errors"].append(f"{target}: {error}")
            result["skipped"].extend(
                str(Path(remaining.path).resolve())
                for remaining, _remaining_repo in ordered_candidates[index + 1 :]
            )
            break
        intent_error = _clear_intent(repo)
        if intent_error is not None:
            result["errors"].append(f"{target}: {intent_error}")
            result["skipped"].extend(
                str(Path(remaining.path).resolve())
                for remaining, _remaining_repo in ordered_candidates[index + 1 :]
            )
            break
        if did_delete or target in removed_worktrees:
            result["removed"].append(target)
    return result


def apply(
    records: list[WorktreeRecord],
    *,
    dry_run: bool = True,
    _lock_held: bool = False,
) -> dict[str, list[str]]:
    """Apply a classification while serializing all Git mutations."""
    if dry_run or _lock_held:
        recovered, recovery_errors = _recover_intent_records(records) if not dry_run else (records, [])
        return _apply_unlocked(
            recovered,
            dry_run=dry_run,
            initial_errors=recovery_errors,
        )
    try:
        with _locked_repositories(records):
            recovered, recovery_errors = _recover_intent_records(records)
            return _apply_unlocked(
                recovered,
                dry_run=False,
                initial_errors=recovery_errors,
            )
    except (GitError, OSError, ReapLockError, ValueError) as exc:
        return {
            "removed": [],
            "skipped": [
                str(Path(record.path).resolve())
                for record in records
                if record.status != "REDUNDANT" or record.protected
            ],
            "errors": [str(exc)],
        }


def _record_json(record: WorktreeRecord) -> dict[str, object]:
    return {
        "path": str(record.path),
        "branch": record.branch,
        "parent": record.parent,
        "status": record.status,
        "reason": record.reason,
        "lane_verified": record.lane_verified,
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
        help="report redundancy; exit 3 when redundant worktrees exist",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return non-zero when redundancy or an unknown inspection exists",
    )
    parser.add_argument(
        "--allow-ignored",
        action="store_true",
        help="allow reclaiming landed worktrees containing ignored-only files",
    )
    parser.add_argument(
        "--protect",
        action="append",
        default=[],
        metavar="PATH_OR_BRANCH",
        help="protect a worktree path or branch (repeatable)",
    )
    parser.add_argument(
        "--allow-missing-lane-state",
        action="store_true",
        help="relax lane-registry inspection for --check; never licenses --apply",
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
        records = classify(
            args.repo,
            protected=args.protect,
            allow_ignored=args.allow_ignored,
            require_lane_state=not args.allow_missing_lane_state,
        )
    except RegistryBackendUnavailable as exc:
        print(f"worktree-reap: {exc}", file=sys.stderr)
        return 1
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
    if any(not record.lane_verified for record in records):
        print(
            "worktree-reap: lane ownership was NOT verified; "
            "classifications below cannot distinguish a reclaimable worktree "
            "from a live lane",
            file=sys.stderr,
        )

    unverified = [record for record in records if not record.lane_verified]
    if unverified:
        if args.apply:
            listed = ", ".join(str(Path(record.path).resolve()) for record in unverified)
            print(
                "worktree-reap: refusing to apply; ownership was not verified for: "
                + listed,
                file=sys.stderr,
            )
        return 1

    redundant = any(record.status == "REDUNDANT" for record in records)
    unknown = any(record.status == "UNKNOWN" for record in records)
    strict = args.strict or _strict_check()
    if args.check:
        # UNKNOWN means the reaper declined to decide, not that the repository
        # is broken.  An advisory gate must not fail for being correctly
        # cautious ([RES-10]); strict mode is where that becomes a hard signal.
        if unknown and strict:
            return 4
        return 3 if redundant else 0
    if strict and unknown:
        return 4
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
