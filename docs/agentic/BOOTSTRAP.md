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

# Full Plugin Checks (WordPress plugin)
cd apps/prototype-wp-alt-context
make check                           # All checks: lint + types + arch + JS tests + PHP tests + phpcs + phpstan
make fix                             # Auto-fix ESLint, Prettier, PHPCBF then run make check
```

---

## MCP Server (Agent Tooling)

The MCP server provides **monorepo-specific** code intelligence that Copilot and Pylance cannot do natively. VS Code manages the server lifecycle automatically — no manual start/stop needed.

### How It Works

```
.vscode/mcp.json  →  scripts/mcp/mcp-server.sh run  →  unified_server.py (stdio)
```

VS Code spawns the MCP server process on demand and communicates via stdin/stdout. The server exits when VS Code closes the connection.

### Prerequisites

- VS Code 1.99+ with Copilot (or other MCP-capable client)
- `.vscode/mcp.json` already committed to the repo
- Python 3.11+ virtualenv with `fastmcp` installed (the `description-service` pyenv env)
- Ripgrep installed (`brew install ripgrep` on macOS)

### Validation

Command Palette → `MCP: List Servers` → "context-alt-text" should show **10 tools**.

### Available Tools (10 total)

These tools handle cross-boundary and domain-specific queries. For generic operations, use Copilot built-ins (`grep_search`, `read_file`, `list_dir`, `get_errors`, `semantic_search`, `list_code_usages`) or Pylance MCP tools.

| Category        | Tool                   | When to Use                                       |
| --------------- | ---------------------- | ------------------------------------------------- |
| **Cross-Layer** | `trace_api_endpoint`   | Trace endpoint across PHP→Python→TS layers        |
| **Context**     | `get_context_map`      | Load domain context (backend/frontend/php)        |
|                 | `get_api_contract`     | Load API contract documentation                   |
|                 | `get_instructions`     | Load engineering instructions                     |
| **React/TS**    | `find_react_component` | Find React component definitions                  |
|                 | `find_react_hook`      | Find custom React hooks                           |
|                 | `list_frontend_tests`  | List test files, optionally filtered by component |
| **PHP/WP**      | `find_wp_action`       | Find WordPress action/filter hooks                |
|                 | `find_wp_rest_route`   | Find REST API route registrations                 |
|                 | `find_php_class`       | Find PHP class definitions                        |

Tools are prefixed with `mcp_context-alt-t_` when invoked by agents.

### Troubleshooting

If tools don't appear in VS Code:

1. Check `MCP: List Servers` — server should be listed
2. Ensure pyenv virtualenv has `fastmcp`: `pyenv exec pip show fastmcp`
3. Test manually: `./scripts/mcp/mcp-server.sh run` (should block on stdin)
4. Check VS Code Output panel → "MCP" for error messages

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
