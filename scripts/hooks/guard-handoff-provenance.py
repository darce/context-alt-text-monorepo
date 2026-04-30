#!/usr/bin/env python3
"""PreToolUse hook: block MCP writes with branch/SHA provenance drift.

When a caller provides an explicit ``actor.branch`` and ``actor.commit_sha`` for
handoff writes, those values should reflect the active task's canonical worktree
HEAD. A common failure mode is running the write from the orchestrator root while
copy-pasting ``actor.branch`` for the feature task, which records a feature
branch paired with the root-main commit SHA.

This hook checks the active task's ``target_branch`` + ``target_worktree_path``
and rejects writes when the provided actor claims that target branch but the
provided commit SHA does not resolve to the target worktree's current HEAD.

Hook contract (PreToolUse):
  stdin: JSON with ``tool_name`` and ``tool_input``
  exit 0 to allow, exit 2 to block with stderr guidance.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


WRITE_TOOL_FRAGMENTS = (
    "record_event",
    "review_findings",
    "review_runs",
    "set_handoff_state",
    "update_task_status",
    "close_slice",
)


def _extract_payload() -> tuple[str, dict[str, Any]]:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return "", {}
    tool_name = payload.get("tool_name") or payload.get("toolName") or ""
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return "", {}
    return tool_name, tool_input


def _is_relevant_tool(tool_name: str) -> bool:
    return any(fragment in tool_name for fragment in WRITE_TOOL_FRAGMENTS)


def _extract_task_ref(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    if "record_event" in tool_name:
        event = tool_input.get("event")
        if isinstance(event, dict):
            return _string_or_none(event.get("task_ref"))
    if "review_findings" in tool_name:
        review = tool_input.get("review")
        if isinstance(review, dict):
            return _string_or_none(review.get("task_ref"))
    return _string_or_none(tool_input.get("task_ref"))


def _extract_actor(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any] | None:
    container: dict[str, Any] | None = None
    if "record_event" in tool_name:
        event = tool_input.get("event")
        container = event if isinstance(event, dict) else None
    elif "review_findings" in tool_name:
        review = tool_input.get("review")
        container = review if isinstance(review, dict) else None
    else:
        container = tool_input
    if not isinstance(container, dict):
        return None
    actor = container.get("actor")
    return actor if isinstance(actor, dict) else None


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _load_task_identity(task_ref: str) -> dict[str, Any] | None:
    try:
        from agent_handoff_mcp import RuntimeConfig, configure_runtime, get_handoff_state
    except ImportError:
        return None

    repo_root = _repo_root()
    try:
        configure_runtime(RuntimeConfig.for_repo(repo_root))
        state = get_handoff_state(task_ref=task_ref, sections="identity", detail="summary")
    except Exception:
        return None
    if not isinstance(state, dict):
        return None
    data = state.get("data")
    if not isinstance(data, dict):
        return None
    active = data.get("active")
    return active if isinstance(active, dict) else None


def _repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return Path.cwd()
    return Path(proc.stdout.strip())


def _resolve_head(path: Path) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def _resolve_commit(path: Path, commit_sha: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", f"{commit_sha}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def _validate_actor(actor: dict[str, Any], identity: dict[str, Any]) -> str | None:
    actor_branch = _string_or_none(actor.get("branch"))
    actor_commit = _string_or_none(actor.get("commit_sha"))
    if not actor_branch or not actor_commit:
        return None

    target_branch = _string_or_none(identity.get("target_branch"))
    target_worktree_path = _string_or_none(identity.get("target_worktree_path"))
    if not target_branch or not target_worktree_path:
        return None
    if actor_branch != target_branch:
        return None

    target_path = Path(target_worktree_path)
    head_sha = _resolve_head(target_path)
    resolved_actor_sha = _resolve_commit(target_path, actor_commit)
    if not head_sha or not resolved_actor_sha:
        return None
    if resolved_actor_sha == head_sha:
        return None

    return (
        f"handoff provenance drift: actor.branch={actor_branch!r} matches the active task target branch, "
        f"but actor.commit_sha resolves to {resolved_actor_sha[:12]} while "
        f"{target_worktree_path} is at HEAD {head_sha[:12]}. "
        "Record the write from the target worktree or pass the target worktree HEAD SHA instead."
    )


def main() -> int:
    tool_name, tool_input = _extract_payload()
    if not tool_name or not _is_relevant_tool(tool_name):
        return 0

    actor = _extract_actor(tool_name, tool_input)
    if actor is None:
        return 0

    task_ref = _extract_task_ref(tool_name, tool_input)
    if not task_ref:
        return 0

    identity = _load_task_identity(task_ref)
    if identity is None:
        return 0

    error = _validate_actor(actor, identity)
    if error:
        print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())