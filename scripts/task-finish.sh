#!/usr/bin/env bash
# task-finish.sh — single-command task lifecycle teardown.
#
# After a feature branch has been merged to main, this script runs the
# canonical post-merge cleanup: returns the root worktree to main (if needed),
# removes the linked worktree, deletes the feature branch, archives the MCP
# task state, and regenerates CURRENT_TASK.md.
#
# Usage:
#   ./scripts/task-finish.sh <TASK_ID>
#
# This script does NOT perform the merge itself — it expects main to already
# contain the work. Pair with `git checkout main && git merge feature/<task>`.

set -euo pipefail

TASK="${1:-}"
if [[ -z "$TASK" ]]; then
  echo "usage: $0 <TASK_ID>" >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
PARENT_DIR="$(dirname "$REPO_ROOT")"
TASK_LOWER="$(echo "$TASK" | tr '[:upper:]' '[:lower:]')"
BRANCH="feature/${TASK_LOWER}"
WORKTREE_PATH="${PARENT_DIR}/context-alt-text-monorepo-${TASK_LOWER}"

cd "$REPO_ROOT"

# Step 1: Verify branch is reachable from main (work has been merged).
if ! git merge-base --is-ancestor "$BRANCH" main 2>/dev/null; then
  if git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
    echo "❌ Branch '$BRANCH' is not yet merged into main." >&2
    echo "   Run the merge first, then re-run task-finish." >&2
    echo "   git checkout main && git merge --ff-only $BRANCH" >&2
    exit 2
  else
    echo "ℹ Branch '$BRANCH' does not exist; assuming already cleaned up." >&2
  fi
fi

# Step 2: Return root worktree to main if currently elsewhere.
ROOT_BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
if [[ "$ROOT_BRANCH" != "main" ]]; then
  echo "→ Returning root worktree to main (was on $ROOT_BRANCH)"
  if ! git -C "$REPO_ROOT" diff --quiet || ! git -C "$REPO_ROOT" diff --cached --quiet; then
    echo "❌ Root worktree has uncommitted changes; refusing to switch." >&2
    echo "   Stash or commit first, then re-run." >&2
    exit 3
  fi
  git -C "$REPO_ROOT" checkout main
fi

# Step 3: Remove the linked worktree.
if [[ -d "$WORKTREE_PATH" ]]; then
  echo "→ Removing linked worktree $WORKTREE_PATH"
  git worktree remove "$WORKTREE_PATH" || {
    echo "⚠ git worktree remove failed; trying --force" >&2
    git worktree remove --force "$WORKTREE_PATH"
  }
else
  echo "ℹ No linked worktree at $WORKTREE_PATH"
fi

git worktree prune

# Step 4: Delete the merged feature branch.
if git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  echo "→ Deleting merged branch $BRANCH"
  git branch -d "$BRANCH"
fi

# Step 5: Archive the MCP task and regenerate CURRENT_TASK.md.
echo "→ Archiving MCP task state $TASK"
PYTHONPATH="${REPO_ROOT}/packages/agent-handoff-mcp/src:${REPO_ROOT}/packages/agent-orchestrator-mcp/src" \
  PYENV_VERSION="${PYENV_VERSION:-description-service}" \
  "${PYENV_ROOT:-$HOME/.pyenv}/versions/${PYENV_VERSION:-description-service}/bin/python" -c "
from agent_handoff_mcp import update_task_status, archive_task_state, generate_current_task_md
import json, subprocess, sys

head_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip().decode()

# Best-effort status -> done before archive (idempotent if already done).
try:
    state = json.loads(update_task_status(task_ref='$TASK', status='done'))
    if not state.get('ok'):
        print('⚠ update_task_status returned ok=False:', state, file=sys.stderr)
except Exception as exc:
    print('⚠ update_task_status skipped:', exc, file=sys.stderr)

archived = json.loads(archive_task_state(task_ref='$TASK', archive_branch='main', archive_commit_sha=head_sha))
if not archived.get('ok'):
    print('⚠ archive_task_state returned ok=False:', archived, file=sys.stderr)

regen = json.loads(generate_current_task_md())
if not regen.get('ok'):
    print('⚠ generate_current_task_md returned ok=False:', regen, file=sys.stderr)
print('  OK')
" || echo "⚠ MCP archive failed — clean up manually with archive_task_state."

echo
echo "✓ Task $TASK finished and cleaned up."
git worktree list
