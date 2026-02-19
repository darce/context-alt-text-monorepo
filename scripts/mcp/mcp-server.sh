#!/bin/bash
#
# MCP Server Entry Point
#
# VS Code spawns this script via .vscode/mcp.json and communicates over stdio.
# No manual start/stop needed — VS Code manages the lifecycle automatically.
#
# Usage:
#   ./scripts/mcp/mcp-server.sh run      # Run server (stdio transport)
#
# Provides monorepo-specific code intelligence tools for AI agents:
#   - trace_api_endpoint (cross-boundary PHP→Python→TS)
#   - find_react_component, find_react_hook, list_frontend_tests
#   - find_wp_action, find_wp_rest_route, find_php_class
#   - get_context_map, get_api_contract, get_instructions
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONOREPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SERVER_SCRIPT="$SCRIPT_DIR/unified_server.py"

# Ensure common tools (ripgrep, etc.) are in PATH for VS Code spawned processes
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

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

case "${1:-run}" in
    run)
        cd "$MONOREPO_ROOT"
        exec "${PYTHON_CMD[@]}" "$SERVER_SCRIPT"
        ;;
    *)
        echo "MCP Server Entry Point"
        echo ""
        echo "Usage: $0 run"
        echo ""
        echo "VS Code calls this automatically via .vscode/mcp.json."
        echo "No manual start/stop needed."
        ;;
esac
