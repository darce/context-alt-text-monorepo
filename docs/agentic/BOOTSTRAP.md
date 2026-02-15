# Agent Setup & Reference

> **Supplementary reference for MCP tooling, testing commands, and context priorities.**
> For cold-start rules and routing, see [instructions.md](instructions.md).

---

## Testing Commands

```bash
# Backend (Python)
cd apps/prototype-description-service
pytest recognition/tests/api/        # API tests
pytest recognition/tests/integration/ # Integration tests (DB)
pytest recognition/tests/unit/       # Unit tests
ruff check . && mypy .               # Lint + types

# Frontend (TypeScript/React)
cd apps/prototype-wp-alt-context
npm run test                         # Vitest
npm run lint                         # ESLint
npm run typecheck                    # TypeScript

# PHP
cd apps/prototype-wp-alt-context
composer test                        # PHPUnit
composer phpstan                     # Static analysis
```

---

## MCP Server (Agent Tooling)

The unified MCP server provides code intelligence tools for agents across all parts of the monorepo.

### Quick Start

```bash
# From monorepo root
make mcp-start        # Start in background
make mcp-stop         # Stop the server
make mcp-status       # Check if running
make mcp-run          # Run in foreground (debug)

# Or use the script directly
./scripts/mcp/mcp-server.sh start
```

### VS Code Configuration (GitHub Copilot)

For GitHub Copilot in VS Code 1.99+, create `.vscode/mcp.json` in the repo root:

```json
{
  "servers": {
    "context-alt-text": {
      "command": "/Users/daniel/.pyenv/versions/description-service/bin/python",
      "args": ["${workspaceFolder}/scripts/mcp/unified_server.py"],
      "env": {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:${env:PATH}"
      }
    }
  }
}
```

> **Note**: Replace the Python path with your own pyenv virtualenv path. The `PATH` env ensures ripgrep and other CLI tools are available.

**Validation**: Command Palette → `MCP: List Servers` should show "context-alt-text" with 18 tools discovered.

#### For Other MCP Clients (Gemini for VS Code, etc.)

Use VS Code user settings with `mcp.servers` key:

```json
{
  "mcp.servers": {
    "context-alt-text": {
      "command": "~/.pyenv/versions/description-service/bin/python",
      "args": ["scripts/mcp/unified_server.py"],
      "cwd": "/path/to/context-alt-text-monorepo"
    }
  }
}
```

#### MCP Availability Checklist

MCP tools are available when **all** of these are true:

- VS Code 1.99+ with MCP-capable client (Copilot or Gemini)
- `.vscode/mcp.json` configured (for Copilot) or `mcp.servers` setting (for Gemini)
- Python virtualenv exists at the configured path
- Ripgrep installed (`brew install ripgrep` on macOS)

### Available Tools (18 total)

| Category        | Tool                   | When to Use                                       |
| --------------- | ---------------------- | ------------------------------------------------- |
| **Search**      | `search_code`          | Find code patterns across entire monorepo         |
|                 | `find_definition`      | Locate where a symbol is defined                  |
|                 | `semantic_search`      | Natural language code search (keyword fallback)   |
| **Navigation**  | `read_file`            | Read file contents with line numbers              |
|                 | `list_directory`       | Browse directory structure                        |
| **Context**     | `get_context_map`      | Load domain context (backend/frontend/php)        |
|                 | `get_api_contract`     | Load API contract documentation                   |
|                 | `get_instructions`     | Load engineering instructions                     |
| **Cross-Layer** | `trace_api_endpoint`   | Trace endpoint across PHP→Python→TS layers        |
| **Diagnostics** | `get_diagnostics`      | Run linters (ruff/eslint/phpstan) on a file       |
|                 | `get_type_info`        | Get type info via Pyright/tsc                     |
| **React/TS**    | `find_react_component` | Find React component definitions                  |
|                 | `find_react_hook`      | Find custom React hooks                           |
|                 | `list_frontend_tests`  | List test files, optionally filtered by component |
| **PHP/WP**      | `find_wp_action`       | Find WordPress action/filter hooks                |
|                 | `find_wp_rest_route`   | Find REST API route registrations                 |
|                 | `find_php_class`       | Find PHP class definitions                        |
| **Debug**       | `debug_subprocess`     | Test subprocess execution (for troubleshooting)   |

Tools are prefixed with `mcp_context-alt-t_` when invoked by agents.

---

## Context Value Hierarchy

| Asset                 | Cold Start Value | When to Use                                   |
| --------------------- | ---------------- | --------------------------------------------- |
| **Contracts**         | Highest          | Cross-boundary work, API changes              |
| **Python API Tests**  | High             | Service implementation, behavior verification |
| **Integration Tests** | High             | Database patterns, RLS, repository queries    |
| **Frontend Hooks**    | Medium           | Job state, SSE, multi-tab coordination        |
| **UML Diagrams**      | Medium           | Architecture understanding, flow questions    |
| **PHP Tests**         | Low              | Currently scaffolding only                    |
