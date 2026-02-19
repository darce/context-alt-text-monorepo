---
description: Troubleshoot MCP server for AI agent tooling
---

**Purpose**: The MCP server provides monorepo-specific code intelligence (10 tools). VS Code manages its lifecycle automatically via `.vscode/mcp.json` -- no manual start/stop needed.

**When to use this workflow**: Only when MCP tools are not appearing or behaving unexpectedly.

**Tools provided (10 total)**: `trace_api_endpoint`, `find_react_component`, `find_react_hook`, `find_wp_action`, `find_wp_rest_route`, `find_php_class`, `list_frontend_tests`, `get_context_map`, `get_api_contract`, `get_instructions`

> Generic operations use Copilot built-ins (`grep_search`, `read_file`, `list_dir`, `get_errors`, `semantic_search`, `list_code_usages`) and Pylance MCP tools.

---

**Troubleshooting steps:**

1. Check if VS Code sees the server

```
Command Palette > MCP: List Servers > "context-alt-text" should show 10 tools
```

2. Test the server manually (should block on stdin, Ctrl+C to exit)

```bash
cd /Users/daniel/Development/context-alt-text-monorepo && ./scripts/mcp/mcp-server.sh run
```

3. Verify fastmcp is installed in the pyenv virtualenv

```bash
pyenv exec pip show fastmcp
```

4. Check VS Code Output panel > "MCP" for error messages

---

**Architecture**: `.vscode/mcp.json` > `scripts/mcp/mcp-server.sh run` > `unified_server.py` (stdio transport). VS Code spawns the process and communicates via stdin/stdout.
