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
REPO_ROOT="$REPO_ROOT" TASK="$TASK" \
PYTHONPATH="${REPO_ROOT}/packages/agent-handoff-mcp/src:${REPO_ROOT}/packages/agent-orchestrator-mcp/src" \
  PYENV_VERSION="${PYENV_VERSION:-description-service}" \
  "${PYENV_ROOT:-$HOME/.pyenv}/versions/${PYENV_VERSION:-description-service}/bin/python" -c '
import json, os, subprocess, sys
from pathlib import Path
from agent_handoff_mcp import (
    RuntimeConfig,
    archive_task_state,
    configure_runtime,
    generate_current_task_md,
    get_handoff_state,
    update_task_status,
)

repo_root = Path(os.environ["REPO_ROOT"])
# Anchor at the primary git worktree so the archive write lands in the same
# DB the MCP server reads from. AHMCP-16: previously hard-coded
# `RuntimeConfig.for_workspace(repo_root)` which read a fresh empty DB when
# task-finish was invoked from a linked worktree.
runtime = RuntimeConfig.for_repo(repo_root)
configure_runtime(runtime)

task = os.environ["TASK"]
head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode()

# Best-effort status -> done before archive (idempotent if already done).
# AHMCP-16-FU-01: when the task being finished is the active row
# (handoff_state.id=1), update_task_status delegates to set_handoff_state
# which requires expected_revision for any update of an existing row. Fetch
# the active rows revision via the identity-only sections projection and
# pass it through. When the task is NOT the active row (already cleared, or
# being archived from a snapshot), the active payload is None and we pass
# expected_revision=None and update_task_status falls through to the archived
# snapshot path which does not enforce optimistic concurrency.
# (Apostrophes are intentionally omitted from comments because the inline
# Python is wrapped in bash single quotes; an unescaped apostrophe breaks
# the heredoc parse.)
identity = get_handoff_state(sections="identity")
if isinstance(identity, str):
    identity = json.loads(identity)
identity_data = identity.get("data") if isinstance(identity, dict) else None
active_row = identity_data.get("active") if isinstance(identity_data, dict) else None
expected_revision = (
    active_row.get("revision")
    if isinstance(active_row, dict) and active_row.get("task_ref") == task
    else None
)

try:
    state = update_task_status(
        task_ref=task,
        status="done",
        expected_revision=expected_revision,
    )
    if not state.get("ok"):
        print("\u26a0 update_task_status returned ok=False:", state, file=sys.stderr)
except Exception as exc:
    print("\u26a0 update_task_status skipped:", exc, file=sys.stderr)

archived = archive_task_state(task_ref=task, archive_branch="main", archive_commit_sha=head_sha)
if not archived.get("ok"):
    print("\u26a0 archive_task_state returned ok=False:", archived, file=sys.stderr)

regen = generate_current_task_md()
if not regen.get("ok"):
    print("\u26a0 generate_current_task_md returned ok=False:", regen, file=sys.stderr)
print("  OK")
' || echo "⚠ MCP archive failed — clean up manually with archive_task_state."

echo
echo "✓ Task $TASK finished and cleaned up."
git worktree list
