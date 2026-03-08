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
PACKAGE_SRC="$MONOREPO_ROOT/packages/agent-handoff-mcp/src"

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

# Python interpreter — prefer pyenv exec, fallback to system python3
PYENV_CMD=""
if command -v pyenv >/dev/null 2>&1; then
    PYENV_CMD="$(command -v pyenv)"
elif [ -n "${PYENV_ROOT:-}" ] && [ -x "${PYENV_ROOT}/bin/pyenv" ]; then
    PYENV_CMD="${PYENV_ROOT}/bin/pyenv"
fi

PYTHON_CMD=()
if [ -n "$PYENV_CMD" ]; then
    if "$PYENV_CMD" exec python3 -c "import sys" >/dev/null 2>&1; then
        PYTHON_CMD=("$PYENV_CMD" exec python3)
    elif "$PYENV_CMD" exec python -c "import sys" >/dev/null 2>&1; then
        PYTHON_CMD=("$PYENV_CMD" exec python)
    fi
fi

if [ ${#PYTHON_CMD[@]} -eq 0 ]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD=(python3)
    elif command -v python >/dev/null 2>&1; then
        PYTHON_CMD=(python)
    else
        echo "❌ Python not found. Install Python 3.11+ or configure pyenv."
        exit 1
    fi
fi

SERVER_CMD=()
if command -v agent-handoff-mcp >/dev/null 2>&1; then
    SERVER_CMD=(agent-handoff-mcp)
else
    export PYTHONPATH="$PACKAGE_SRC${PYTHONPATH:+:$PYTHONPATH}"
    SERVER_CMD=("${PYTHON_CMD[@]}" -m agent_handoff_mcp)
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
        echo "Prefers installed 'agent-handoff-mcp'; falls back to the repo-local package."
        echo "VS Code calls 'run' automatically via .vscode/mcp.json."
        ;;
esac
