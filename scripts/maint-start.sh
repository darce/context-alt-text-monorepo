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
MCP_HANDOFF_PACKAGE="${MCP_HANDOFF_PACKAGE:-mcp-workbay-handoff==0.2.0}"
if ! command -v uvx >/dev/null 2>&1; then
  echo "❌ uvx not on PATH. Install uv (https://docs.astral.sh/uv/) before running maint-start." >&2
  exit 3
fi
REPO_ROOT="$REPO_ROOT" SLUG="$SLUG" OBJECTIVE="$OBJECTIVE" \
  uvx --from "$MCP_HANDOFF_PACKAGE" python3 \
  "${REPO_ROOT}/scripts/_maint_start_inline.py"

echo
echo "✓ Maintenance task ready."
echo "  Next:"
echo "  make context"