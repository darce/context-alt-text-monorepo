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

# Extract file_path from the hook payload.
FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('file_path', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")

# No file path means this isn't a file-edit invocation — allow.
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Determine current branch.
BRANCH=$(git branch --show-current 2>/dev/null || echo "")

if [ "$BRANCH" != "main" ] && [ "$BRANCH" != "master" ]; then
  exit 0
fi

# Convert absolute path to repo-relative using canonical paths so /var vs
# /private/var aliases do not bypass the prefix check in temp fixtures.
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
REL_PATH=$(python3 -c '
import sys
from pathlib import Path

raw_path = sys.argv[1]
repo_root = sys.argv[2]
if not repo_root:
    print(raw_path)
    raise SystemExit(0)

candidate = Path(raw_path).expanduser().resolve(strict=False)
root = Path(repo_root).expanduser().resolve(strict=False)
try:
    print(candidate.relative_to(root).as_posix())
except ValueError:
    print(raw_path)
' "$FILE_PATH" "$REPO_ROOT")

if ! SHOULD_BLOCK=$(python3 -c '
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
rel_path = sys.argv[2]
sys.path.insert(0, str(repo_root / "scripts" / "hooks"))

from _harness_protocol import HarnessContractMissingError, is_branch_isolation_protected_path, load_branch_isolation_policy

try:
    policy = load_branch_isolation_policy(repo_root)
except HarnessContractMissingError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(2)

print("1" if is_branch_isolation_protected_path(rel_path, policy) else "0")
' "$REPO_ROOT" "$REL_PATH"); then
  exit 2
fi

if [ "$SHOULD_BLOCK" = "1" ]; then
  cat >&2 <<EOF
BLOCKED: Code file edits are not allowed on the main branch.

  Branch: $BRANCH
  File:   $REL_PATH

Create a feature branch first:
  git checkout -b feature/<task-id>-<slug>

Or use worktree isolation for agent work:
  Use the Agent tool with isolation: "worktree"

See: docs/agentic/rules/development-workflow.md § Branch Isolation Protocol
EOF
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

  File: $REL_PATH

Register a maintenance task before continuing:
  set_handoff_state(task_ref='MAINT-<slug>', objective='Describe the main-branch patch', status='in_progress')

This rollout is warning-only for permitted main-branch edits.
EOF
fi

exit 0
