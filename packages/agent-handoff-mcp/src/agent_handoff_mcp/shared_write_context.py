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
    normalized_model_label = _normalize_optional_text(model_label) or normalize_model_label(normalized_model)
    normalized_reasoning_level = normalize_reasoning_level(reasoning_level)
    derived_agent = normalize_model_identity(normalized_model_label, normalized_reasoning_level)
    normalized_agent = _normalize_optional_text(agent)
    normalized_branch = _normalize_optional_text(branch)
    normalized_commit_sha = _normalize_optional_text(commit_sha)
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


def _resolve_write_actor(
    conn: sqlite3.Connection,
    actor: WriteActor | None,
) -> ResolvedWriteContext:
    explicit_agent = _normalize_optional_text(actor.get("agent")) if actor else None
    explicit_model = _normalize_optional_text(actor.get("model")) if actor else None
    explicit_model_label = (
        _normalize_optional_text(actor.get("model_label")) if actor else None
    ) or normalize_model_label(explicit_model)
    explicit_reasoning_level = normalize_reasoning_level(actor.get("reasoning_level")) if actor else None
    explicit_identity = normalize_model_identity(explicit_model_label, explicit_reasoning_level)
    explicit_branch = _normalize_optional_text(actor.get("branch")) if actor else None
    explicit_commit = _normalize_optional_text(actor.get("commit_sha")) if actor else None
    explicit_lane = _normalize_optional_text(actor.get("lane_id")) if actor else None
    default_agent = _normalize_optional_text(os.environ.get("AGENT_HANDOFF_DEFAULT_AGENT")) or "codex"
    active = conn.execute(
        "SELECT updated_by, updated_branch, updated_commit_sha FROM handoff_state WHERE id = 1"
    ).fetchone()
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
