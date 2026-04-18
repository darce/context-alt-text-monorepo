#!/usr/bin/env bash
# PreToolUse hook: blocks code-file edits on the main branch.
#
# Receives tool invocation as JSON on stdin (Claude Code hook protocol).
# Exit 0 = allow, Exit 2 = block (stderr shown to agent as reason).
#
# Policy: docs, configs, and planning artifacts may be edited on main.
#         Contract-protected code-adjacent files require a feature branch.

set -euo pipefail

INPUT=$(cat)

# Determine current branch.
BRANCH=$(git branch --show-current 2>/dev/null || echo "")

if [ "$BRANCH" != "main" ] && [ "$BRANCH" != "master" ]; then
  exit 0
fi

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
if ! BLOCK_REASON=$(printf '%s' "$INPUT" | python3 -c '
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
branch = sys.argv[2]
sys.path.insert(0, str(repo_root / "scripts" / "hooks"))

from _branch_isolation_guard import check_file_edit, find_dirty_protected_paths
from _harness_protocol import HarnessContractMissingError, load_branch_isolation_policy

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
        "BLOCKED: Code file edits are not allowed on the main branch.\n\n"
        f"Branch: {resolved_branch}\n"
        "Files:\n"
        f"{rendered_paths}\n\n"
        "Create a feature branch first:\n"
        "  git checkout -b feature/<task-id>-<slug>\n\n"
        "If you already have dirty code changes on main, move them to a feature branch or stash them before continuing.\n\n"
        "Isolation options:\n"
        "  1. Feature branch for single-agent work\n"
        "  2. Worktree isolation for delegated subtasks\n"
        "  3. Lane orchestration for multi-agent parallel work\n\n"
        "Docs, markdown, and permitted planning surfaces remain allowed on main.\n"
        "See: docs/agentic/rules/development-workflow.md#branch-isolation-protocol-mandatory"
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
    "See: docs/agentic/rules/development-workflow.md#branch-isolation-protocol-mandatory"
)
' "$REPO_ROOT" "$BRANCH"); then
  exit 2
fi

if [ -n "$BLOCK_REASON" ]; then
  printf '%s\n' "$BLOCK_REASON" >&2
  exit 2
fi

# Warning-only rollout: permitted main-branch edits still require a handoff task.
# If none is active, print a maintenance-task reminder but do not block the edit.
# Only query (and warn) when the CLI is actually installed — a missing CLI must
# not masquerade as "no active task" (E17-4 Slice 2 regression).
if ! command -v agent-handoff-mcp >/dev/null 2>&1; then
  exit 0
fi

ACTIVE_TASK=$(
  agent-handoff-mcp --workspace-root "$REPO_ROOT" state --sections identity 2>/dev/null | python3 -c "
import sys, json
try:
    payload = json.load(sys.stdin)
except Exception:
    print('')
    raise SystemExit(0)
data = payload.get('data') if isinstance(payload, dict) else None
active = data.get('active') if isinstance(data, dict) else None
task_ref = active.get('task_ref') if isinstance(active, dict) else ''
print(task_ref or '')
" 2>/dev/null || true
)

if [ -z "$ACTIVE_TASK" ]; then
  cat >&2 <<EOF
WARNING: Editing on $BRANCH without an active handoff task.
  Register a MAINT-* task before continuing.

Register a maintenance task before continuing:
  set_handoff_state(task_ref='MAINT-<slug>', objective='Describe the main-branch patch', status='in_progress')

This rollout is warning-only for permitted main-branch edits.
EOF
fi

exit 0
