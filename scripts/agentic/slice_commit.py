#!/usr/bin/env python3
"""Commit staged changes, then record a slice-complete decision atomically."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

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
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
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
    configure_runtime(
        RuntimeConfig.for_workspace(
            args.workspace_root,
            state_dir=args.state_dir,
            current_task_path=args.current_task_path,
            exports_dir=args.exports_dir,
        )
    )

    changed_files = [line for line in _git(repo_root, "diff", "--cached", "--name-only").splitlines() if line]
    if not changed_files:
        print("slice-commit requires staged changes. Stage files first.", file=sys.stderr)
        return 1

    _git(repo_root, "commit", "-m", args.message)
    commit_sha = _git(repo_root, "rev-parse", "HEAD")
    identity = get_handoff_state(task_ref=args.task_ref, sections="identity", detail="summary")
    revision = None
    active = ((identity or {}).get("data") or {}).get("active") or {}
    if active.get("task_ref") == args.task_ref:
        revision = active.get("revision")

    decision = args.decision or f"mk_slice_complete_{args.task_ref}_{_slugify(args.message)}"
    rationale = _build_rationale(args.message, commit_sha, changed_files)
    result = close_slice(
        session=args.session,
        decision=decision,
        rationale=rationale,
        expected_revision=revision,
        task_ref=args.task_ref,
        focus=args.focus,
        changed_files=changed_files,
    )
    if not result.get("ok"):
        print(result, file=sys.stderr)
        return 1

    print(f"Committed and recorded slice-complete decision `{decision}` at {commit_sha}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
