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

# Step 4b: Working-tree integrity check before archiving.
#
# AHMCP-18 (item B): immediately before invoking the inline Python that
# touches the handoff DB, run `git diff HEAD` against the merged main and
# fail loudly if any tracked file disagrees with HEAD content. This is the
# detection guard for the AHMCP-15-BR-FIXES incident where api.py was
# silently reverted in the working tree between the AHMCP-16 merge and the
# AHMCP-15-BR-FIXES merge, causing task-finish to fail mid-flight on a
# bad import.
#
# Files in `.task-state/dirty-allowlist` (one path per line, comments OK)
# are treated as expected drift and skipped. Untracked files are not
# considered integrity violations because git tracks intent through the
# index; only tracked-but-modified content is verified.
echo "→ Checking working-tree integrity"
INTEGRITY_DIRTY=$(git -C "$REPO_ROOT" diff --name-only HEAD 2>/dev/null || true)
if [[ -n "$INTEGRITY_DIRTY" ]]; then
  ALLOWLIST_FILE="$REPO_ROOT/.task-state/dirty-allowlist"
  ALLOWED_PATHS=()
  if [[ -f "$ALLOWLIST_FILE" ]]; then
    while IFS= read -r line; do
      stripped="${line#"${line%%[![:space:]]*}"}"
      stripped="${stripped%"${stripped##*[![:space:]]}"}"
      [[ -z "$stripped" || "$stripped" == \#* ]] && continue
      ALLOWED_PATHS+=("$stripped")
    done < "$ALLOWLIST_FILE"
  fi
  UNEXPECTED_DIRTY=()
  while IFS= read -r dirty_path; do
    [[ -z "$dirty_path" ]] && continue
    is_allowed=0
    # ${ALLOWED_PATHS[@]+"${ALLOWED_PATHS[@]}"} expands to nothing when the
    # array is empty, which is required because `set -u` rejects bare
    # `${ALLOWED_PATHS[@]}` when no entries have been appended.
    for allowed in ${ALLOWED_PATHS[@]+"${ALLOWED_PATHS[@]}"}; do
      if [[ "$dirty_path" == "$allowed" ]]; then
        is_allowed=1
        break
      fi
    done
    if [[ "$is_allowed" -eq 0 ]]; then
      UNEXPECTED_DIRTY+=("$dirty_path")
    fi
  done <<< "$INTEGRITY_DIRTY"

  if [[ "${#UNEXPECTED_DIRTY[@]}" -gt 0 ]]; then
    echo "❌ Working tree disagrees with HEAD on ${#UNEXPECTED_DIRTY[@]} tracked file(s):" >&2
    for unexpected in "${UNEXPECTED_DIRTY[@]:0:10}"; do
      echo "    - $unexpected" >&2
    done
    if [[ "${#UNEXPECTED_DIRTY[@]}" -gt 10 ]]; then
      echo "    ... and $(( ${#UNEXPECTED_DIRTY[@]} - 10 )) more" >&2
    fi
    echo "" >&2
    echo "  task-finish refuses to archive when the working tree has drifted from HEAD." >&2
    echo "  Investigate before archiving — silent file reverts and stale editor buffers" >&2
    echo "  are exactly the kind of out-of-band write that this guard exists to catch." >&2
    echo "" >&2
    echo "  Resolution options:" >&2
    echo "    1. Restore from HEAD:    git -C $REPO_ROOT checkout HEAD -- <path>" >&2
    echo "    2. Allow the drift:      add the path to $ALLOWLIST_FILE and re-run" >&2
    echo "    3. Commit the change:    git add + git commit, then re-run" >&2
    exit 4
  fi
fi

# Step 5: Archive the MCP task and regenerate CURRENT_TASK.md.
echo "→ Archiving MCP task state $TASK"
# AHMCP-20: the inline Python that used to live here as a `python -c '...'`
# heredoc now lives at scripts/_task_finish_inline.py. Bash quoting is no
# longer in the loop, so the AHMCP-17 apostrophe-in-comment bug class is
# unrepresentable here. The lint guard at scripts/hooks/lint-no-inline-python-heredoc.py
# prevents future heredocs from sneaking back in.
REPO_ROOT="$REPO_ROOT" TASK="$TASK" \
PYTHONPATH="${REPO_ROOT}/packages/agent-handoff-mcp/src:${REPO_ROOT}/packages/agent-orchestrator-mcp/src" \
  PYENV_VERSION="${PYENV_VERSION:-description-service}" \
  "${PYENV_ROOT:-$HOME/.pyenv}/versions/${PYENV_VERSION:-description-service}/bin/python" \
  "${REPO_ROOT}/scripts/_task_finish_inline.py" \
  || echo "⚠ MCP archive failed — clean up manually with archive_task_state."

echo
echo "✓ Task $TASK finished and cleaned up."
git worktree list
