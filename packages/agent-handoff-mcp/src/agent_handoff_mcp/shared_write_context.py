"""Write-context cluster for agent_handoff_mcp.

Extracted from _shared.py (Slice 2 of E12-10). Contains:
  - WriteActor TypedDict
  - ResolvedWriteContext dataclass
  - _resolve_core_override()  — shared monkeypatch-fallback helper
  - build_write_actor()
  - _first_non_empty_env()
  - _run_cmd()
  - _detect_git_write_context()
  - _git_is_ancestor()
  - _classify_commit_relation()
  - _workspace_git_context()
  - _resolve_write_actor()

All symbols are re-exported from _shared.py for backward compatibility.

Imports from _shared are done at function level (late imports) to avoid a circular
module dependency: _shared.py re-exports from this module at its end, so module-level
imports in this file would create a deadlock when this module is loaded first.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from typing import Any, TypedDict

from .enums import (
    normalize_model_identity,
    normalize_model_label,
    normalize_reasoning_level,
)
from .runtime import get_runtime_config
from .shared_primitives import _normalize_optional_text

# Mirror the constant from _shared; defined here so this module has no
# module-level dependency on _shared (avoids circular import).
_SUBPROCESS_TIMEOUT = 10

# Regex matching abbreviated and full git commit SHAs (4-40 hex chars).
# Anything shorter than 4 chars is too ambiguous to expand; anything
# non-hex is rejected outright.
_COMMIT_SHA_HEX_RE = re.compile(r"^[0-9a-f]{4,40}$")


class InvalidCommitShaError(ValueError):
    """Raised when a ``commit_sha`` value cannot be validated against git.

    The validator distinguishes three failure modes:

    1. The string is non-empty but not hex (typo, wrong field passed).
    2. The string is hex but does not resolve to any object in the
       active git repository (typically a fabricated SHA, e.g. one
       expanded from a 7-char abbreviation by typing the suffix from
       memory rather than via ``git rev-parse``).
    3. The string resolves to a non-commit object (tag, tree, blob).

    Validation is bypassed entirely when the
    ``AGENT_HANDOFF_SKIP_SHA_VALIDATION`` environment variable is set
    (used by both packages' test suites; see their ``conftest.py``).
    """


class BranchMismatchError(ValueError):
    """Raised when branch enforcement is enabled and a write targets the wrong branch."""

    def __init__(self, task_ref: str, expected_branch: str, actual_branch: str) -> None:
        self.task_ref = task_ref
        self.expected_branch = expected_branch
        self.actual_branch = actual_branch
        super().__init__(
            f"actor.branch {actual_branch!r} does not match active task {task_ref!r} target_branch {expected_branch!r}."
        )


class UnresolvedTaskContextError(ValueError):
    """Raised when a write path cannot resolve an active task_ref.

    The canonical resolution order is: (1) an explicit ``task_ref``
    parameter, (2) a workspace-path lookup via
    ``_resolve_workspace_handoff_row``. When neither resolves, callers
    must fail closed rather than silently falling back to a sentinel
    row (E17-11). Callers that hit this error should either pass
    ``task_ref=`` explicitly, set ``AGENT_HANDOFF_TASK_REF``, or run
    from the task's registered ``target_worktree_path``.
    """


def _commit_sha_validation_enabled() -> bool:
    """Return ``False`` if the test bypass env var is set, else ``True``."""
    bypass = os.environ.get("AGENT_HANDOFF_SKIP_SHA_VALIDATION", "").strip().lower()
    return bypass not in {"1", "true", "yes", "on"}


def _branch_enforcement_enabled() -> bool:
    """Return ``True`` when env-gated branch enforcement should block writes."""
    bypass = os.environ.get("AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT", "").strip().lower()
    if bypass in {"1", "true", "yes", "on"}:
        return False
    enabled = os.environ.get("AGENT_HANDOFF_ENFORCE_BRANCH", "").strip().lower()
    return enabled in {"1", "true", "yes", "on"}


def _branch_target_is_enforceable(target_branch: str | None) -> bool:
    normalized = _normalize_optional_text(target_branch)
    if normalized is None:
        return False
    return normalized.lower() not in {"main", "master"}


def _git_repo_root() -> str | None:
    """Return the absolute path of the active git repo root, or None.

    Resolves the active task's ``target_worktree_path`` if present (so
    validation runs against the worktree the agent claims to be working
    in), falling back to the runtime workspace_root, falling back to
    cwd. Returns ``None`` if no git directory is reachable from any of
    those, which means SHA validation is silently skipped (the agent is
    not in a git context, e.g. running tests in a tmp_path fixture).
    """
    candidates: list[str] = []
    try:
        config = get_runtime_config()
        candidates.append(str(config.workspace_root))
    except RuntimeError:
        pass
    try:
        candidates.append(os.getcwd())
    except OSError:
        pass
    for candidate in candidates:
        try:
            proc = subprocess.run(
                ["git", "-C", candidate, "rev-parse", "--show-toplevel"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            root = proc.stdout.strip()
            if root:
                return root
    return None


def _validate_and_expand_commit_sha(value: str | None) -> str | None:
    """Validate ``value`` against the active git repo and return its full SHA.

    Behavior:

    - ``None`` or empty string -> return as-is (caller is not claiming
      provenance for a specific commit).
    - Non-hex string -> raise ``InvalidCommitShaError`` immediately.
    - Hex string of 4-40 chars -> shell out to
      ``git -C <repo> rev-parse --verify <sha>^{commit}`` to confirm
      the SHA resolves to a real commit. On success, return the
      full 40-char form so the audit trail always stores the
      canonical SHA. On failure (object not found, ambiguous abbrev,
      not a commit), raise ``InvalidCommitShaError``.
    - When git is not available or no repository is reachable from
      the runtime workspace_root, validation is silently skipped and
      the input is returned unchanged. This keeps tmp_path tests and
      non-git environments working.
    - Validation is also bypassed entirely when the
      ``AGENT_HANDOFF_SKIP_SHA_VALIDATION`` env var is truthy. Both
      package test suites set this env var in their ``conftest.py``
      so synthetic test SHAs (``"abc123"``, ``"def456"``) pass
      through unchanged.

    The validator exists because the gate that previously accepted
    fabricated SHAs (``handoff_close_check`` comparing the passed
    ``current_commit_sha`` against the recorded slice decision's
    ``commit_sha`` as opaque strings) had no way to detect that the
    SHA didn't actually point at a real git object. Several
    AHMCP-10/AHMCP-11 audit-trail rows ended up tagged with
    SHA suffixes that were typed from memory rather than read from
    ``git rev-parse``, and the gate passed because the fabricated
    string matched itself.
    """
    if not _commit_sha_validation_enabled():
        return value
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return value
    if not _COMMIT_SHA_HEX_RE.fullmatch(normalized):
        raise InvalidCommitShaError(
            f"commit_sha {value!r} is not a hex string of 4-40 characters. "
            "Pass the full SHA from `git rev-parse HEAD`, never a typed-from-memory expansion."
        )
    repo_root = _git_repo_root()
    if repo_root is None:
        # No git context available -- typical in tmp_path test fixtures.
        # Skip validation rather than failing the write.
        return value
    try:
        proc = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "--verify", f"{normalized}^{{commit}}"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except Exception:
        # git binary not available or hung -- skip rather than fail.
        return value
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise InvalidCommitShaError(
            f"commit_sha {value!r} does not resolve to a real commit object in {repo_root}.\n"
            "Run `git rev-parse <abbrev>` to get the canonical SHA before recording it.\n"
            f"git rev-parse said: {stderr}"
        )
    full_sha = proc.stdout.strip()
    if not _COMMIT_SHA_HEX_RE.fullmatch(full_sha) or len(full_sha) != 40:
        # Defensive: git returned something unexpected.
        return value
    return full_sha


# ---------------------------------------------------------------------------
# TypedDicts / dataclasses
# ---------------------------------------------------------------------------


class WriteActor(TypedDict, total=False):
    agent: str
    model: str
    model_label: str
    reasoning_level: str
    branch: str
    commit_sha: str
    lane_id: str


@dataclass
class ResolvedWriteContext:
    agent: str | None
    branch: str | None
    commit_sha: str | None
    lane_id: str | None
    model: str | None
    model_label: str | None
    reasoning_level: str | None


# ---------------------------------------------------------------------------
# Core-override helper  (M1: eliminate repeated monkeypatch-fallback pattern)
# ---------------------------------------------------------------------------


def _resolve_core_override(attr_name: str, fallback: Any) -> Any:
    """Return the override of *attr_name* from the loaded core module, or *fallback*.

    The core module registers monkeypatched test doubles on itself, so callers
    that respect the monkeypatch contract must prefer the core-module version
    when it exists.  This helper centralises that lookup so every write-context
    function uses a single, tested code path.
    """
    import sys  # noqa: PLC0415

    _core_mod = sys.modules.get("agent_handoff_mcp.core")
    fn = getattr(_core_mod, attr_name, None) if _core_mod is not None else None
    return fn if fn is not None else fallback


# ---------------------------------------------------------------------------
# Build write actor
# ---------------------------------------------------------------------------


def build_write_actor(
    agent: str | None = None,
    model: str | None = None,
    model_label: str | None = None,
    reasoning_level: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
    lane_id: str | None = None,
) -> WriteActor:
    actor: WriteActor = {}
    normalized_model = _normalize_optional_text(model)
    explicit_model_label = _normalize_optional_text(model_label)
    derived_model_label = normalize_model_label(normalized_model)
    if (
        explicit_model_label is not None
        and derived_model_label is not None
        and explicit_model_label != derived_model_label
    ):
        raise ValueError(
            "actor.model_label does not match the canonical label for actor.model: "
            f"{explicit_model_label!r} != {derived_model_label!r}"
        )
    normalized_model_label = explicit_model_label or derived_model_label
    normalized_reasoning_level = normalize_reasoning_level(reasoning_level)
    derived_agent = normalize_model_identity(normalized_model_label, normalized_reasoning_level)
    normalized_agent = _normalize_optional_text(agent)
    normalized_branch = _normalize_optional_text(branch)
    normalized_commit_sha = _normalize_optional_text(commit_sha)
    # Validate the SHA against the active git repo and auto-expand
    # abbreviated forms to the full 40-char canonical hash. Bypassed
    # by AGENT_HANDOFF_SKIP_SHA_VALIDATION (set by both packages'
    # test conftests). Raises InvalidCommitShaError if the SHA is
    # non-hex or does not resolve to a real commit object in a
    # reachable git repo. See _validate_and_expand_commit_sha for
    # the full contract.
    normalized_commit_sha = _validate_and_expand_commit_sha(normalized_commit_sha)
    normalized_lane_id = _normalize_optional_text(lane_id)
    if normalized_model is not None:
        actor["model"] = normalized_model
    if normalized_model_label is not None:
        actor["model_label"] = normalized_model_label
    if normalized_reasoning_level is not None:
        actor["reasoning_level"] = normalized_reasoning_level
    if derived_agent is not None:
        actor["agent"] = derived_agent
    elif normalized_agent is not None:
        actor["agent"] = normalized_agent
    if normalized_branch is not None:
        actor["branch"] = normalized_branch
    if normalized_commit_sha is not None:
        actor["commit_sha"] = normalized_commit_sha
    if normalized_lane_id is not None:
        actor["lane_id"] = normalized_lane_id
    return actor


# ---------------------------------------------------------------------------
# Git / env utilities
# ---------------------------------------------------------------------------


def _first_non_empty_env(*keys: str) -> str | None:
    for key in keys:
        candidate = _normalize_optional_text(os.environ.get(key))
        if candidate is not None:
            return candidate
    return None


def _run_cmd(cmd: list[str], timeout: int = _SUBPROCESS_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=str(get_runtime_config().workspace_root),
        timeout=timeout,
    )


def _detect_git_write_context() -> tuple[str | None, str | None]:
    branch = _first_non_empty_env(
        "AGENT_HANDOFF_DEFAULT_BRANCH",
        "GITHUB_HEAD_REF",
        "GITHUB_REF_NAME",
        "CI_COMMIT_REF_NAME",
        "BRANCH_NAME",
    )
    commit_sha = _first_non_empty_env(
        "AGENT_HANDOFF_DEFAULT_COMMIT_SHA",
        "GITHUB_SHA",
        "CI_COMMIT_SHA",
    )
    try:
        branch_proc = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if branch_proc.returncode == 0:
            raw_branch = _normalize_optional_text(branch_proc.stdout)
            if raw_branch is not None and raw_branch != "HEAD":
                branch = raw_branch
            elif raw_branch == "HEAD" and branch is None:
                branch = "detached-head"
    except Exception:
        pass
    try:
        commit_proc = _run_cmd(["git", "rev-parse", "HEAD"])
        if commit_proc.returncode == 0:
            commit_sha = _normalize_optional_text(commit_proc.stdout)
    except Exception:
        pass
    if branch is None:
        branch = "unknown-branch"
    return branch, commit_sha


def _git_is_ancestor(ancestor_sha: str | None, descendant_sha: str | None) -> bool | None:
    normalized_ancestor = _normalize_optional_text(ancestor_sha)
    normalized_descendant = _normalize_optional_text(descendant_sha)
    if normalized_ancestor is None or normalized_descendant is None:
        return None
    if normalized_ancestor == normalized_descendant:
        return True
    try:
        proc = _run_cmd(["git", "merge-base", "--is-ancestor", normalized_ancestor, normalized_descendant])
    except Exception:
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def _classify_commit_relation(reference_sha: str | None, candidate_sha: str | None) -> str:
    normalized_reference = _normalize_optional_text(reference_sha)
    normalized_candidate = _normalize_optional_text(candidate_sha)
    if normalized_reference is None or normalized_candidate is None:
        return "unknown"
    if normalized_reference == normalized_candidate:
        return "same"
    if _git_is_ancestor(normalized_reference, normalized_candidate) is True:
        return "descendant"
    if _git_is_ancestor(normalized_candidate, normalized_reference) is True:
        return "ancestor"
    if _git_is_ancestor(normalized_reference, normalized_candidate) is False:
        return "diverged"
    return "unknown"


def _workspace_git_context() -> dict[str, str | None]:
    detect_fn = _resolve_core_override("_detect_git_write_context", _detect_git_write_context)
    branch, commit_sha = detect_fn()
    return {
        "branch": branch,
        "commit_sha": commit_sha,
    }


# ---------------------------------------------------------------------------
# Write actor resolution
# ---------------------------------------------------------------------------


def collect_target_context_warnings(
    conn: sqlite3.Connection,
    ctx: ResolvedWriteContext,
    *,
    target_branch: str | None = None,
    target_worktree_path: str | None = None,
    task_ref: str | None = None,
) -> list[str]:
    """Return human-readable warnings when the resolved write context drifts from the active task target.

    Reads the active handoff_state row and compares its `target_branch` and
    `target_worktree_path` against the resolved actor branch and the current
    process working directory. Mismatches are returned as warning strings that
    callers can pass through to `_envelope(warnings=...)`.

    By default the check is non-fatal for branch/worktree drift: it surfaces
    mismatches without rejecting the write, so cross-agent handoff loops still
    record state. When AGENT_HANDOFF_ENFORCE_BRANCH is truthy and
    AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT is not, branch mismatches on
    enforceable target branches raise BranchMismatchError before the write is
    applied. Worktree-path drift remains warning-only.

    Task resolution itself is fail-closed. When no explicit ``task_ref`` is
    provided, the guard delegates to ``_resolve_workspace_handoff_row`` and
    raises UnresolvedTaskContextError if the workspace cannot be resolved to a
    single active row.
    """
    normalized_task_ref = _normalize_optional_text(task_ref)
    try:
        if normalized_task_ref is not None:
            active = conn.execute(
                "SELECT task_ref, target_branch, target_worktree_path FROM handoff_state WHERE task_ref = ?",
                (normalized_task_ref,),
            ).fetchone()
        else:
            # E17-11 Slice 3a: no sentinel `WHERE id = 1` fallback.
            # Delegate to workspace-path resolution and fail closed when
            # ambiguity or an unregistered cwd leaves the active row
            # unresolved.
            from .shared_primitives import _resolve_workspace_handoff_row

            try:
                active = _resolve_workspace_handoff_row(conn)
            except ValueError as exc:
                raise UnresolvedTaskContextError(str(exc)) from exc
    except sqlite3.OperationalError:
        # Schema is older than this build (missing column). Skip the check.
        return []
    if active is None and normalized_task_ref is None:
        raise UnresolvedTaskContextError(
            "No active task in handoff_state. Call set_handoff_state first or pass task_ref explicitly."
        )
    if active is None:
        # No matching row to compare against: either an explicit task_ref
        # pointed at a row that does not exist, or the handoff_state table
        # is empty (bootstrap / test-isolation). Nothing to check.
        # Ambiguous multi-row cases are handled above by the resolver
        # raising UnresolvedTaskContextError.
        return []
    warnings: list[str] = []
    resolved_task_ref = normalized_task_ref
    if resolved_task_ref is None and active["task_ref"]:
        resolved_task_ref = _normalize_optional_text(active["task_ref"])
    resolved_target_branch = _normalize_optional_text(target_branch)
    if resolved_target_branch is None and active["target_branch"]:
        resolved_target_branch = _normalize_optional_text(active["target_branch"])
    resolved_target_worktree_path = _normalize_optional_text(target_worktree_path)
    if resolved_target_worktree_path is None and active["target_worktree_path"]:
        resolved_target_worktree_path = _normalize_optional_text(active["target_worktree_path"])
    if resolved_target_branch and ctx.branch and ctx.branch != resolved_target_branch:
        if (
            _branch_enforcement_enabled()
            and _branch_target_is_enforceable(resolved_target_branch)
            and resolved_task_ref is not None
        ):
            raise BranchMismatchError(
                task_ref=resolved_task_ref,
                expected_branch=resolved_target_branch,
                actual_branch=ctx.branch,
            )
        warnings.append(
            "context_drift: actor.branch={} but active task target_branch={}. "
            "Consider switching to the canonical worktree before recording further events.".format(
                ctx.branch, resolved_target_branch
            )
        )
    if resolved_target_worktree_path:
        cwd = os.path.abspath(os.getcwd())
        canonical = os.path.abspath(resolved_target_worktree_path)
        if cwd != canonical:
            warnings.append(
                "context_drift: cwd={} but active task target_worktree_path={}. "
                "Run `make context` to confirm or switch directories.".format(cwd, canonical)
            )
    return warnings


def _resolve_write_actor(
    conn: sqlite3.Connection,
    actor: WriteActor | None,
) -> ResolvedWriteContext:
    explicit_agent = _normalize_optional_text(actor.get("agent")) if actor else None
    explicit_model = _normalize_optional_text(actor.get("model")) if actor else None
    explicit_model_label = _normalize_optional_text(actor.get("model_label")) if actor else None
    derived_model_label = normalize_model_label(explicit_model)
    if (
        explicit_model_label is not None
        and derived_model_label is not None
        and explicit_model_label != derived_model_label
    ):
        raise ValueError(
            "actor.model_label does not match the canonical label for actor.model: "
            f"{explicit_model_label!r} != {derived_model_label!r}"
        )
    explicit_model_label = explicit_model_label or derived_model_label
    explicit_reasoning_level = normalize_reasoning_level(actor.get("reasoning_level")) if actor else None
    explicit_identity = normalize_model_identity(explicit_model_label, explicit_reasoning_level)
    explicit_branch = _normalize_optional_text(actor.get("branch")) if actor else None
    explicit_commit = _normalize_optional_text(actor.get("commit_sha")) if actor else None
    explicit_lane = _normalize_optional_text(actor.get("lane_id")) if actor else None
    default_agent = _normalize_optional_text(os.environ.get("AGENT_HANDOFF_DEFAULT_AGENT")) or "codex"
    from .shared_primitives import _resolve_workspace_handoff_row  # noqa: PLC0415

    try:
        active = _resolve_workspace_handoff_row(conn)
    except ValueError:
        active = None
    active_agent = _normalize_optional_text(active["updated_by"]) if active is not None else None
    active_branch = _normalize_optional_text(active["updated_branch"]) if active is not None else None
    active_commit = _normalize_optional_text(active["updated_commit_sha"]) if active is not None else None
    detect_fn = _resolve_core_override("_detect_git_write_context", _detect_git_write_context)
    git_branch, git_commit = detect_fn()
    preferred_git_branch = git_branch if git_branch not in (None, "unknown-branch") else None
    return ResolvedWriteContext(
        agent=explicit_identity or explicit_agent or active_agent or default_agent,
        branch=explicit_branch or preferred_git_branch or active_branch or git_branch,
        commit_sha=explicit_commit or git_commit or active_commit,
        lane_id=explicit_lane,
        model=explicit_model,
        model_label=explicit_model_label,
        reasoning_level=explicit_reasoning_level,
    )
