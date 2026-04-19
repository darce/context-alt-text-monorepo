#!/usr/bin/env python3
"""Inline Python implementation for scripts/hooks/guard-main-branch.sh.

Promoted from a `python -c '...'` heredoc inside guard-main-branch.sh
to a standalone module so bash quoting cannot break the script. This is
the same bug class eradication as AHMCP-20 (_task_start_inline.py).

Reads two positional arguments set by guard-main-branch.sh:
    sys.argv[1]  REPO_ROOT  — absolute path to the repository root
    sys.argv[2]  BRANCH     — current git branch name

Reads JSON tool-invocation payload on stdin (Claude Code hook protocol).

Exit codes:
    0 — allow (optionally prints a BLOCKED reason to stdout for the
        bash wrapper to relay to stderr)
    2 — hard block (contract missing or unrecoverable error)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
branch = sys.argv[2]
sys.path.insert(0, str(repo_root / "scripts" / "hooks"))

from _branch_isolation_guard import check_file_edit, extract_candidate_paths, find_dirty_protected_paths, to_repo_relative
from _harness_protocol import (
    HarnessContractMissingError,
    find_permitted_main_surface,
    is_branch_isolation_protected_path,
    load_branch_isolation_policy,
)

try:
    payload = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)

tool_name = payload.get("toolName") or payload.get("tool_name") or ""
tool_input = payload.get("toolInput") or payload.get("tool_input") or {}
if not isinstance(tool_input, dict):
    raise SystemExit(0)

try:
    policy = load_branch_isolation_policy(repo_root)
except HarnessContractMissingError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(2)

protected_branches = {"main", "master"}
attempted = check_file_edit(
    tool_name,
    tool_input,
    branch=branch,
    repo_root=str(repo_root),
    policy=policy,
    protected_branches=protected_branches,
)
if attempted is not None:
    resolved_branch, blocked_paths = attempted
    rendered_paths = "\n".join(f"  - {path}" for path in blocked_paths)
    print(
        "BLOCKED: Protected edits are not allowed on the main branch.\n\n"
        f"Branch: {resolved_branch}\n"
        "Files:\n"
        f"{rendered_paths}\n\n"
        "Create a feature branch first:\n"
        "  git checkout -b feature/<task-id>-<slug>\n\n"
        "If you already have dirty code changes on main, move them to a feature "
        "branch or stash them before continuing.\n\n"
        "Isolation options:\n"
        "  1. Feature branch for single-agent work\n"
        "  2. Worktree isolation for delegated subtasks\n"
        "  3. Lane orchestration for multi-agent parallel work\n\n"
        "Only explicitly permitted operator docs/config surfaces remain allowed "
        "on main.\n"
        "Planning docs and implementation files now require a feature branch "
        "from the first edit.\n"
        "See: docs/agentic/rules/development-workflow.md"
        "#branch-isolation-protocol-mandatory"
    )
    raise SystemExit(0)

dirty = find_dirty_protected_paths(
    branch=branch,
    repo_root=str(repo_root),
    policy=policy,
    protected_branches=protected_branches,
)
if dirty is None:
    raise SystemExit(0)

resolved_branch, dirty_paths = dirty

# BR-21: if every candidate edit path resolves to a permitted_main_surface AND
# none of the candidate paths are themselves in the dirty-protected set, the
# edit is a legitimate docs/config update that must not be blocked by unrelated
# dirty code. Emit a warning and allow the edit; the dirty state still needs
# remediation, but that is a separate cleanup.
candidate_rel_paths = [
    to_repo_relative(raw, str(repo_root))
    for raw in extract_candidate_paths(tool_name, tool_input)
]
candidate_rel_paths = [p for p in candidate_rel_paths if p]
all_permitted = bool(candidate_rel_paths) and all(
    find_permitted_main_surface(p, policy) is not None for p in candidate_rel_paths
)
candidates_clean = not any(p in set(dirty_paths) for p in candidate_rel_paths)
if all_permitted and candidates_clean:
    rendered_paths = "\n".join(f"  - {path}" for path in dirty_paths)
    print(
        "WARNING: Protected code files are dirty on main, but this edit targets "
        "only permitted_main_surfaces — allowing.\n\n"
        f"Branch: {resolved_branch}\n"
        "Dirty files (still need remediation):\n"
        f"{rendered_paths}\n\n"
        "Remediation options (not required for this edit):\n"
        "  1. git checkout -b feature/<task-id>-<slug> to move dirty changes off main\n"
        "  2. git stash push -m 'pre-main-cleanup' to set them aside\n"
        "  3. git restore <files> to discard them\n",
        file=sys.stderr,
    )
    raise SystemExit(0)

rendered_paths = "\n".join(f"  - {path}" for path in dirty_paths)
print(
    "BLOCKED: Protected code files are already dirty on the main branch.\n\n"
    f"Branch: {resolved_branch}\n"
    "Dirty files:\n"
    f"{rendered_paths}\n\n"
    "Move the work onto a feature branch or stash it before making more edits.\n\n"
    "Recommended recovery:\n"
    "  1. git checkout -b feature/<task-id>-<slug>\n"
    "  2. keep the dirty changes on that branch, or stash them intentionally\n"
    "  3. return to main only after the protected paths are clean again\n\n"
    "See: docs/agentic/rules/development-workflow.md"
    "#branch-isolation-protocol-mandatory"
)
