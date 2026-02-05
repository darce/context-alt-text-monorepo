---
description: Start/stop the MCP server for AI agent tooling
---

**Purpose**: Control the unified MCP server that provides code intelligence tools across the entire monorepo.

**When to use**:

- Starting a development session with AI agents
- Enabling `search_code`, `trace_api_endpoint`, `find_react_component` tools
- Debugging MCP server issues

**Prerequisites**: Python 3.11+ with fastmcp installed (`pip install fastmcp`). If you use pyenv, ensure `pyenv` is on your PATH so the script can run `pyenv exec python`.

**Tools provided by MCP server**:

- `search_code` - Search across all languages
- `find_definition` - Find symbol definitions
- `trace_api_endpoint` - Trace endpoints across PHP→Python→TS
- `find_react_component` / `find_react_hook` - React-specific search
- `find_wp_action` / `find_wp_rest_route` - WordPress-specific search
- `get_context_map` / `get_api_contract` - Load documentation

---

1. Check MCP server status

```bash
cd /Users/daniel/Development/context-alt-text-monorepo && ./scripts/mcp/mcp-server.sh status
```

2. Start MCP server (if not running)

```bash
cd /Users/daniel/Development/context-alt-text-monorepo && ./scripts/mcp/mcp-server.sh start
```

3. View server log (last 20 lines)

```bash
tail -20 /Users/daniel/Development/context-alt-text-monorepo/logs/mcp-server.log 2>/dev/null || echo "No log file yet"
```

---

**Other commands**:

```bash
# Stop the server
make mcp-stop

# Restart the server
make mcp-restart

# Run in foreground (for debugging)
make mcp-run
```

---

**VS Code integration**

VS Code uses the same entry point as the CLI: `scripts/mcp/mcp-server.sh run`.  
The `.vscode/mcp.json` file is configured to call that script and to inherit your
pyenv environment (via `PYENV_ROOT`/`PYENV_VERSION` if set).

If VS Code can’t find `pyenv`, ensure your system PATH includes it (or set
`PYENV_ROOT` in your shell environment so VS Code inherits it).
```
