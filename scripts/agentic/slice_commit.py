#!/usr/bin/env python3
"""Commit staged changes, then record a slice-complete decision atomically."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from agent_handoff_mcp.api import close_slice, get_handoff_state
from agent_handoff_mcp.config import RuntimeConfig
from agent_handoff_mcp.runtime import configure_runtime


def _git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:48] or "slice"


def _build_rationale(message: str, commit_sha: str, changed_files: list[str]) -> str:
    changed = "\n".join(f"- `{path}`" for path in changed_files) if changed_files else "- none."
    return (
        "## Changes\n"
        f"- Created git commit `{commit_sha}` with subject `{message}`.\n"
        f"{changed}\n\n"
        "## Verification\n"
        "- `git diff --cached --name-only` was non-empty before commit.\n"
        f"- `git rev-parse HEAD` after commit = `{commit_sha}`.\n\n"
        "## Schema / Contract Changes\n"
        "- none.\n\n"
        "## Open Threads\n"
        "- Additional test evidence, if required for merge, should be recorded separately.\n"
    )


def record_slice_commit(
    *,
    repo_root: Path,
    workspace_root: str,
    state_dir: str,
    current_task_path: str,
    exports_dir: str,
    task_ref: str,
    session: str,
    message: str,
    focus: str | None = None,
    decision: str | None = None,
    runtime_factory: Callable[..., Any] = RuntimeConfig.for_workspace,
    configure_runtime_fn: Callable[[Any], Any] = configure_runtime,
    git_fn: Callable[..., str] = _git,
    get_handoff_state_fn: Callable[..., dict[str, Any]] = get_handoff_state,
    close_slice_fn: Callable[..., dict[str, Any]] = close_slice,
) -> dict[str, Any]:
    configure_runtime_fn(
        runtime_factory(
            workspace_root,
            state_dir=state_dir,
            current_task_path=current_task_path,
            exports_dir=exports_dir,
        )
    )

    changed_files = [line for line in git_fn(repo_root, "diff", "--cached", "--name-only").splitlines() if line]
    if not changed_files:
        raise ValueError("slice-commit requires staged changes. Stage files first.")

    git_fn(repo_root, "commit", "-m", message)
    commit_sha = git_fn(repo_root, "rev-parse", "HEAD")
    branch = git_fn(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    identity = get_handoff_state_fn(task_ref=task_ref, sections="identity", detail="summary")
    revision = None
    active = ((identity or {}).get("data") or {}).get("active") or {}
    if active.get("task_ref") == task_ref:
        revision = active.get("revision")

    resolved_decision = decision or f"cdx_slice_complete_{task_ref}_{_slugify(message)}"
    rationale = _build_rationale(message, commit_sha, changed_files)
    result = close_slice_fn(
        session=session,
        decision=resolved_decision,
        rationale=rationale,
        expected_revision=revision,
        task_ref=task_ref,
        focus=focus,
        changed_files=changed_files,
        actor={"branch": branch, "commit_sha": commit_sha},
    )
    if not result.get("ok"):
        raise RuntimeError(str(result))

    return {
        "decision": resolved_decision,
        "commit_sha": commit_sha,
        "changed_files": changed_files,
        "close_slice": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--current-task-path", required=True)
    parser.add_argument("--exports-dir", required=True)
    parser.add_argument("--task-ref", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--focus")
    parser.add_argument("--decision")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    try:
        result = record_slice_commit(
            repo_root=repo_root,
            workspace_root=args.workspace_root,
            state_dir=args.state_dir,
            current_task_path=args.current_task_path,
            exports_dir=args.exports_dir,
            task_ref=args.task_ref,
            session=args.session,
            message=args.message,
            focus=args.focus,
            decision=args.decision,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        "Committed and recorded slice-complete decision "
        f"`{result['decision']}` at {result['commit_sha']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
