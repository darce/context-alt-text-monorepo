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
  # AHMCP-20: the inline Python that used to live here as a `python -c '...'`
  # heredoc now lives at scripts/_task_start_inline.py. Bash quoting is no
  # longer in the loop, so the AHMCP-17 apostrophe-in-comment bug class is
  # unrepresentable here. The lint guard at scripts/hooks/lint-no-inline-python-heredoc.py
  # prevents future heredocs from sneaking back in.
  REPO_ROOT="$REPO_ROOT" TASK="$TASK" OBJECTIVE="$OBJECTIVE" BRANCH="$BRANCH" WORKTREE_PATH="$WORKTREE_PATH" \
  PYTHONPATH="${REPO_ROOT}/packages/agent-handoff-mcp/src:${REPO_ROOT}/packages/agent-orchestrator-mcp/src" \
    PYENV_VERSION="${PYENV_VERSION:-description-service}" \
    "${PYENV_ROOT:-$HOME/.pyenv}/versions/${PYENV_VERSION:-description-service}/bin/python" \
    "${REPO_ROOT}/scripts/_task_start_inline.py" \
    || echo "⚠ MCP registration skipped — register manually with set_handoff_state."
else
  echo "→ Skipping MCP registration (no OBJECTIVE provided)"
  echo "  Register manually:"
  echo "  set_handoff_state(task_ref='$TASK', objective='...', target_branch='$BRANCH', target_worktree_path='$WORKTREE_PATH')"
fi

echo
echo "✓ Task scaffold ready."
echo "  Next:"
echo "  cd $WORKTREE_PATH && make context"
