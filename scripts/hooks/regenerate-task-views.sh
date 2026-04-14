#!/usr/bin/env bash
set +e

WORKSPACE_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

agent-handoff-mcp --workspace-root "$WORKSPACE_ROOT" task >/dev/null 2>&1 || true
agent-handoff-mcp --workspace-root "$WORKSPACE_ROOT" dashboard >/dev/null 2>&1 || true

exit 0
