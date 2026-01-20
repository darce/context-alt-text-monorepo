#!/bin/bash
#
# MCP Server Control Script
# 
# Usage:
#   ./scripts/mcp/mcp-server.sh start    # Start the MCP server in background
#   ./scripts/mcp/mcp-server.sh stop     # Stop the MCP server
#   ./scripts/mcp/mcp-server.sh status   # Check if server is running
#   ./scripts/mcp/mcp-server.sh restart  # Restart the server
#   ./scripts/mcp/mcp-server.sh run      # Run in foreground (for debugging)
#
# The server provides code intelligence tools for agents working across:
#   - Python backend (apps/prototype-description-service/)
#   - TypeScript frontend (apps/prototype-wp-alt-context/js/)
#   - PHP plugin (apps/prototype-wp-alt-context/src/)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONOREPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SERVER_SCRIPT="$SCRIPT_DIR/unified_server.py"
PID_FILE="$SCRIPT_DIR/.mcp-server.pid"
LOG_FILE="$MONOREPO_ROOT/logs/mcp-server.log"

# Ensure common tools (ripgrep, etc.) are in PATH for VS Code spawned processes
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Python interpreter - prefer pyenv description-service, fallback to system
if [ -f "$HOME/.pyenv/versions/description-service/bin/python" ]; then
    PYTHON="$HOME/.pyenv/versions/description-service/bin/python"
elif command -v python3 &> /dev/null; then
    PYTHON="python3"
else
    echo "❌ Python not found. Install Python 3.11+ or pyenv."
    exit 1
fi

# Ensure logs directory exists
mkdir -p "$MONOREPO_ROOT/logs"

start_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "⚠️  MCP server already running (PID: $PID)"
            return 0
        else
            rm -f "$PID_FILE"
        fi
    fi

    echo "🚀 Starting MCP server..."
    echo "   Python: $PYTHON"
    echo "   Server: $SERVER_SCRIPT"
    echo "   Log: $LOG_FILE"
    
    cd "$MONOREPO_ROOT"
    nohup "$PYTHON" "$SERVER_SCRIPT" > "$LOG_FILE" 2>&1 &
    PID=$!
    echo $PID > "$PID_FILE"
    
    # Wait a moment and check if it started
    sleep 1
    if kill -0 "$PID" 2>/dev/null; then
        echo "✅ MCP server started (PID: $PID)"
        echo ""
        echo "To connect from VS Code, add to settings.json:"
        echo '  "mcp.servers": {'
        echo '    "context-alt-text": {'
        echo '      "command": "'"$PYTHON"'",'
        echo '      "args": ["'"$SERVER_SCRIPT"'"]'
        echo '    }'
        echo '  }'
    else
        echo "❌ MCP server failed to start. Check $LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
}

stop_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "🛑 Stopping MCP server (PID: $PID)..."
            kill "$PID"
            rm -f "$PID_FILE"
            echo "✅ MCP server stopped"
        else
            echo "⚠️  MCP server not running (stale PID file)"
            rm -f "$PID_FILE"
        fi
    else
        echo "⚠️  MCP server not running (no PID file)"
    fi
}

status_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "✅ MCP server running (PID: $PID)"
            echo "   Log: $LOG_FILE"
            return 0
        else
            echo "❌ MCP server not running (stale PID file)"
            rm -f "$PID_FILE"
            return 1
        fi
    else
        echo "❌ MCP server not running"
        return 1
    fi
}

run_foreground() {
    echo "🚀 Starting MCP server in foreground (Ctrl+C to stop)..."
    echo "   Python: $PYTHON"
    echo "   Server: $SERVER_SCRIPT"
    echo ""
    cd "$MONOREPO_ROOT"
    exec "$PYTHON" "$SERVER_SCRIPT"
}

case "${1:-help}" in
    start)
        start_server
        ;;
    stop)
        stop_server
        ;;
    restart)
        stop_server
        sleep 1
        start_server
        ;;
    status)
        status_server
        ;;
    run)
        run_foreground
        ;;
    *)
        echo "MCP Server Control Script"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|run}"
        echo ""
        echo "Commands:"
        echo "  start   - Start MCP server in background"
        echo "  stop    - Stop MCP server"
        echo "  restart - Restart MCP server"
        echo "  status  - Check if server is running"
        echo "  run     - Run in foreground (for debugging)"
        echo ""
        echo "The MCP server provides code intelligence tools for AI agents:"
        echo "  - search_code, find_definition"
        echo "  - trace_api_endpoint (cross-boundary)"
        echo "  - find_react_component, find_react_hook"
        echo "  - find_wp_action, find_wp_rest_route"
        echo "  - get_context_map, get_api_contract"
        ;;
esac
