#!/usr/bin/env bash
# task-finish.sh — single-command task lifecycle teardown.
#
# After a feature branch has been merged to main, this script runs the
# canonical post-merge cleanup: returns the root worktree to main (if needed),
# removes the linked worktree, deletes the feature branch, archives the MCP
# task state, and regenerates CURRENT_TASK.json.
#
# Usage:
#   ./scripts/task-finish.sh <TASK_ID> [--merge]
#
# Without --merge this script does NOT perform the merge itself — it expects
# main to already contain the work.
#
# --merge  Performs the merge as part of the teardown sequence:
#          1. Requires the root worktree to be on main.
#          2. Stashes any uncommitted tracked changes on the root worktree so
#             they do not block the fast-forward merge.
#          3. Merges the feature branch into main via git merge --ff-only.
#          4. Pops the stash. If stash pop produces conflicts the merge is
#             left on main but the stash is preserved; the script exits
#             non-zero with recovery instructions.
#          5. Continues with the normal worktree/branch/MCP cleanup.
#
#          This mode is safe for the common pattern where planning artifacts
#          on main are left uncommitted (untracked new files are invisible to
#          git stash and do not interfere).
#
# Makefile shorthand:
#   make task-finish TASK=<id>          # merge already done
#   make task-finish TASK=<id> MERGE=1  # stash + merge + pop, then cleanup

set -euo pipefail

TASK="${1:-}"
if [[ -z "$TASK" ]]; then
  echo "usage: $0 <TASK_ID> [--merge]" >&2
  exit 1
fi

MERGE_MODE=0
[[ "${2:-}" == "--merge" ]] && MERGE_MODE=1

REPO_ROOT="$(git rev-parse --show-toplevel)"
PARENT_DIR="$(dirname "$REPO_ROOT")"
TASK_LOWER="$(echo "$TASK" | tr '[:upper:]' '[:lower:]')"
BRANCH="feature/${TASK_LOWER}"
WORKTREE_PATH="${PARENT_DIR}/context-alt-text-monorepo-${TASK_LOWER}"

cd "$REPO_ROOT"

# Step 0 (--merge mode): stash root worktree, merge feature branch, pop stash.
if [[ "$MERGE_MODE" -eq 1 ]]; then
  ROOT_BRANCH_PRE="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
  if [[ "$ROOT_BRANCH_PRE" != "main" ]]; then
    echo "❌ --merge requires the root worktree to be on main (currently on $ROOT_BRANCH_PRE)." >&2
    exit 5
  fi

  if ! git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
    echo "❌ Branch '$BRANCH' does not exist." >&2
    exit 2
  fi

  # Only stash tracked modifications; untracked new files are invisible to
  # git stash and do not interfere with a fast-forward merge.
  STASH_NEEDED=0
  if ! git -C "$REPO_ROOT" diff --quiet || ! git -C "$REPO_ROOT" diff --cached --quiet; then
    STASH_NEEDED=1
    echo "→ Stashing uncommitted tracked changes on root worktree"
    git -C "$REPO_ROOT" stash push -m "auto-stash before merge of $BRANCH"
  fi

  echo "→ Merging $BRANCH into main (--ff-only)"
  if ! git -C "$REPO_ROOT" merge --ff-only "$BRANCH"; then
    echo "❌ git merge --ff-only failed." >&2
    if [[ "$STASH_NEEDED" -eq 1 ]]; then
      echo "   Your stash is preserved. Run: git stash pop" >&2
    fi
    exit 6
  fi

  if [[ "$STASH_NEEDED" -eq 1 ]]; then
    echo "→ Popping stash"
    if ! git -C "$REPO_ROOT" stash pop; then
      echo "❌ git stash pop produced conflicts." >&2
      echo "   The merge is committed to main. Resolve manually:" >&2
      echo "     git stash list           # locate the stash entry" >&2
      echo "     git checkout -- <path>   # discard conflicting stash file" >&2
      echo "     git stash drop           # remove the stash entry" >&2
      echo "   Then re-run task-finish (without --merge) to continue cleanup." >&2
      exit 7
    fi
  fi
fi

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

# Step 5: Archive the MCP task and regenerate CURRENT_TASK.json.
echo "→ Archiving MCP task state $TASK"
# AHMCP-20: the inline Python that used to live here as a `python -c '...'`
# heredoc now lives at scripts/_task_finish_inline.py. Bash quoting is no
# longer in the loop, so the AHMCP-17 apostrophe-in-comment bug class is
# unrepresentable here. The lint guard at scripts/hooks/lint-no-inline-python-heredoc.py
# prevents future heredocs from sneaking back in.
MCP_HANDOFF_PACKAGE="${MCP_HANDOFF_PACKAGE:-mcp-agent-handoff==0.11.2}"
if ! command -v uvx >/dev/null 2>&1; then
  echo "⚠ uvx not on PATH — skipping MCP archive. Install uv (https://docs.astral.sh/uv/) and run archive_task_state manually." >&2
else
  REPO_ROOT="$REPO_ROOT" TASK="$TASK" \
    uvx --from "$MCP_HANDOFF_PACKAGE" python3 \
    "${REPO_ROOT}/scripts/_task_finish_inline.py" \
    || echo "⚠ MCP archive failed — clean up manually with archive_task_state."
fi

echo
echo "✓ Task $TASK finished and cleaned up."
git worktree list
