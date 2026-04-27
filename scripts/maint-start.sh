#!/usr/bin/env bash
# maint-start.sh — single-command MAINT task bootstrap on main/master.

set -euo pipefail

SLUG="${1:-}"
OBJECTIVE="${2:-}"

if [[ -z "$SLUG" || -z "$OBJECTIVE" ]]; then
  echo "usage: $0 <slug> <OBJECTIVE>" >&2
  echo "example: $0 localwp-admin-assets \"Patch packaged asset docs\"" >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

ROOT_BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
if [[ "$ROOT_BRANCH" != "main" && "$ROOT_BRANCH" != "master" ]]; then
  echo "❌ maint-start must run from the root main/master worktree." >&2
  echo "   Current branch: $ROOT_BRANCH" >&2
  exit 2
fi

echo "→ Registering MAINT task on $ROOT_BRANCH"
REPO_ROOT="$REPO_ROOT" SLUG="$SLUG" OBJECTIVE="$OBJECTIVE" \
PYTHONPATH="${REPO_ROOT}/packages/agent-handoff-mcp/src:${REPO_ROOT}/packages/agent-orchestrator-mcp/src" \
  PYENV_VERSION="${PYENV_VERSION:-description-service}" \
  "${PYENV_ROOT:-$HOME/.pyenv}/versions/${PYENV_VERSION:-description-service}/bin/python" \
  "${REPO_ROOT}/scripts/_maint_start_inline.py"

echo
echo "✓ Maintenance task ready."
echo "  Next:"
echo "  make context"