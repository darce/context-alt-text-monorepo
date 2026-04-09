#!/usr/bin/env bash
# task-start.sh — single-command task lifecycle bootstrap.
#
# Creates a feature branch, links a sibling worktree at the canonical path,
# and registers the task in agent-handoff-mcp with target_branch and
# target_worktree_path populated. Print the cd command for the user to run.
#
# Usage:
#   ./scripts/task-start.sh <TASK_ID> [OBJECTIVE]
#
# Naming convention:
#   feature/<lower-task-id>            for the branch
#   ../context-alt-text-monorepo-<lower-task-id>   for the worktree path
#
# Example:
#   ./scripts/task-start.sh AHMCP-9 "Add target_worktree_path field to handoff state"

set -euo pipefail

TASK="${1:-}"
OBJECTIVE="${2:-}"

if [[ -z "$TASK" ]]; then
  echo "usage: $0 <TASK_ID> [OBJECTIVE]" >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
PARENT_DIR="$(dirname "$REPO_ROOT")"
TASK_LOWER="$(echo "$TASK" | tr '[:upper:]' '[:lower:]')"
BRANCH="feature/${TASK_LOWER}"
WORKTREE_PATH="${PARENT_DIR}/context-alt-text-monorepo-${TASK_LOWER}"

cd "$REPO_ROOT"

# Refuse to start a task from a non-main root worktree (per worktree-ownership rule).
ROOT_BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
if [[ "$ROOT_BRANCH" != "main" ]]; then
  echo "❌ Root worktree is on '$ROOT_BRANCH', not 'main'." >&2
  echo "   Per the worktree-ownership rule, the root worktree must stay on main." >&2
  echo "   Run from a clean root before scaffolding a new task." >&2
  exit 2
fi

# Refuse to overwrite an existing branch or worktree.
if git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  echo "❌ Branch '$BRANCH' already exists. Resume by cd-ing into the existing worktree:" >&2
  if [[ -d "$WORKTREE_PATH" ]]; then
    echo "   cd $WORKTREE_PATH" >&2
  fi
  exit 3
fi
if [[ -d "$WORKTREE_PATH" ]]; then
  echo "❌ Worktree path '$WORKTREE_PATH' already exists. Pick a unique TASK id." >&2
  exit 3
fi

echo "→ Creating branch $BRANCH from main"
git branch "$BRANCH" main

echo "→ Linking worktree $WORKTREE_PATH"
git worktree add "$WORKTREE_PATH" "$BRANCH"

if [[ -n "$OBJECTIVE" ]]; then
  echo "→ Registering MCP handoff task $TASK with target_branch=$BRANCH target_worktree_path=$WORKTREE_PATH"
  REPO_ROOT="$REPO_ROOT" TASK="$TASK" OBJECTIVE="$OBJECTIVE" BRANCH="$BRANCH" WORKTREE_PATH="$WORKTREE_PATH" \
  PYTHONPATH="${REPO_ROOT}/packages/agent-handoff-mcp/src:${REPO_ROOT}/packages/agent-orchestrator-mcp/src" \
    PYENV_VERSION="${PYENV_VERSION:-description-service}" \
    "${PYENV_ROOT:-$HOME/.pyenv}/versions/${PYENV_VERSION:-description-service}/bin/python" -c '
import json, os, sys
from pathlib import Path
from agent_handoff_mcp import (
    RuntimeConfig,
    configure_runtime,
    get_handoff_state,
    set_handoff_state,
)

# Anchor the runtime at the primary git worktree so the handoff DB is the
# same one the MCP server reads from. AHMCP-16: previously this used
# `RuntimeConfig.for_workspace(repo_root)` which is correct for the primary
# worktree but a fresh empty per-worktree DB when invoked from a linked
# worktree, breaking task switches.
runtime = RuntimeConfig.for_repo(Path(os.environ["REPO_ROOT"]))
configure_runtime(runtime)

# Fetch the current handoff_state revision before updating. The set_handoff_state
# write path requires expected_revision for any update of the singleton id=1
# row, and that row is non-null whenever any task has ever been started, so
# omitting expected_revision here failed every invocation after the first.
# AHMCP-16: read identity-only and pass through expected_revision; treat the
# absence of an active row (genuine cold start) as expected_revision=None so
# the create-row path still works.
identity = get_handoff_state(sections="identity")
if isinstance(identity, str):
    identity = json.loads(identity)
identity_data = identity.get("data") if isinstance(identity, dict) else None
active_row = identity_data.get("active") if isinstance(identity_data, dict) else None
expected_revision = active_row.get("revision") if isinstance(active_row, dict) else None

result = set_handoff_state(
    task_ref=os.environ["TASK"],
    objective=os.environ["OBJECTIVE"],
    status="in_progress",
    target_branch=os.environ["BRANCH"],
    target_worktree_path=os.environ["WORKTREE_PATH"],
    expected_revision=expected_revision,
)
parsed = json.loads(result) if isinstance(result, str) else result
if not parsed.get("ok"):
    print("\u26a0 set_handoff_state failed:", parsed, file=sys.stderr)
    sys.exit(1)
revision = parsed.get("data", {}).get("active", {}).get("revision", "?")
print(f"  OK rev={revision}")
' || echo "⚠ MCP registration skipped — register manually with set_handoff_state."
else
  echo "→ Skipping MCP registration (no OBJECTIVE provided)"
  echo "  Register manually:"
  echo "  set_handoff_state(task_ref='$TASK', objective='...', target_branch='$BRANCH', target_worktree_path='$WORKTREE_PATH')"
fi

echo
echo "✓ Task scaffold ready."
echo "  Next:"
echo "  cd $WORKTREE_PATH && make context"
