#!/bin/bash
#
# Agent Handoff MCP Entry Point
#
# VS Code spawns this script via .vscode/mcp.json and communicates over stdio.
# No manual start/stop needed — VS Code manages the lifecycle automatically.
#
# Usage:
#   ./scripts/mcp/mcp-server.sh run         # Run server (stdio transport)
#   ./scripts/mcp/mcp-server.sh doctor      # Validate runtime and state paths
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONOREPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Prefer the backend's pyenv version when available (no hardcoded paths).
if [ -z "${PYENV_VERSION:-}" ]; then
    PYENV_VERSION_FILE="$MONOREPO_ROOT/apps/prototype-description-service/.python-version"
    if [ -f "$PYENV_VERSION_FILE" ]; then
        PYENV_VERSION="$(head -n 1 "$PYENV_VERSION_FILE" | tr -d '[:space:]')"
        if [ -n "$PYENV_VERSION" ]; then
            export PYENV_VERSION
        fi
    fi
fi

SERVER_CMD=()
if command -v agent-handoff-mcp >/dev/null 2>&1; then
    SERVER_CMD=(agent-handoff-mcp)
fi

if [ ${#SERVER_CMD[@]} -eq 0 ]; then
    echo "❌ agent-handoff-mcp runtime not found."
    echo "Bootstrap it once with: uv tool install 'agent-handoff-mcp @ git+ssh://git@github.com/darce/mcp-agent-handoff.git'"
    exit 1
fi

case "${1:-run}" in
    run)
        cd "$MONOREPO_ROOT"
        exec "${SERVER_CMD[@]}" --workspace-root "$MONOREPO_ROOT" serve-stdio
        ;;
    doctor)
        cd "$MONOREPO_ROOT"
        exec "${SERVER_CMD[@]}" --workspace-root "$MONOREPO_ROOT" doctor
        ;;
    *)
        echo "Agent Handoff MCP Entry Point"
        echo ""
        echo "Usage: $0 run|doctor"
        echo ""
        echo "Requires the installed agent-handoff-mcp entrypoint."
        echo "VS Code calls 'run' automatically via .vscode/mcp.json."
        ;;
esac
