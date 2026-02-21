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
- Python 3.11+ virtualenv with `fastmcp>=3,<4` installed (the `description-service` pyenv env)
- Ripgrep installed (`brew install ripgrep` on macOS)

### Validation

Command Palette → `MCP: List Servers` → "context-alt-text" should show **29 custom tools**.

### Available Tools (29 custom total)

These tools handle cross-boundary and domain-specific queries. For generic operations, use editor-native tools (for example, `search_code`, `find_definition`, `read_file`, `list_dir`, diagnostics) or Pylance MCP tools.

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
| **Handoff**     | `set_handoff_state`    | Set/update active task with revision guard        |
|                 | `get_handoff_state`    | Retrieve compact handoff snapshot (token efficient) |
|                 | `record_decision`      | Append a key decision + rationale                 |
|                 | `update_next_actions`  | Add/complete/reprioritize action queue items      |
|                 | `record_test_result`   | Record verified checks (`passed` + optional exit code) |
|                 | `report_blocker`       | Add/resolve/reopen blockers                       |
|                 | `record_review_finding` | Record structured review findings                 |
|                 | `update_review_finding` | Update finding lifecycle status                   |
|                 | `reopen_review_finding` | Reopen a finding with required rationale          |
|                 | `list_review_findings` | List findings with filters/pagination             |
|                 | `get_review_finding`   | Fetch one finding by DB id within a task          |
|                 | `get_review_findings_summary` | Compact counts + recent finding updates      |
|                 | `reconcile_review_findings` | Validate/repair review finding integrity checks |
|                 | `handoff_close_check` | Enforce close readiness (done + no open blockers/actions/findings + sync) |
|                 | `generate_current_task_md` | Generate deterministic `CURRENT_TASK.md` from SQLite state |
|                 | `export_handoff_state` | Export task snapshot JSON for cross-machine sharing |
|                 | `import_handoff_state` | Import task snapshot JSON (merge/replace)         |
|                 | `archive_task_state`   | Archive completed task state snapshot             |
|                 | `get_handoff_dashboard` | Read-only multi-task activity summary             |

Tools are prefixed with `mcp_context-alt-t_` when invoked by agents.

### Troubleshooting

If tools don't appear in VS Code:

1. Check `MCP: List Servers` — server should be listed
2. Ensure pyenv virtualenv has `fastmcp`: `pyenv exec pip show fastmcp`
3. Test manually: `./scripts/mcp/mcp-server.sh run` (should block on stdin)
4. Check VS Code Output panel → "MCP" for error messages

Handoff guard commands:

- `make handoff-close-check` runs `handoff_close_check(enforce=True)` for the active task.
- `make handoff-integrity-check` runs the CLI parser/lifecycle guard used by CI.

### Handoff State Defaults

- SQLite path: `.task-state/handoff.db` (local workspace state; authoritative source of truth)
- Compact read defaults in `get_handoff_state`:
  - blockers: `5`
  - actions: `5`
  - decisions: `3`
  - tests: `3`
  - findings: `10`
- Write tools (`record_decision`, `update_next_actions`, `record_test_result`, `report_blocker`, `record_review_finding`, `update_review_finding`, `reopen_review_finding`) target the active task only.
- To write to a different task, switch active state first with `set_handoff_state(...)`.
- Optional write provenance is passed as `actor={ "agent"?: str, "branch"?: str, "commit_sha"?: str }`.
- Optional review finding details are passed as `details={ "line_start"?: int, "line_end"?: int, "fix"?: str }`.
- `record_review_finding` is unique per `(task_ref, finding_id)`; re-recording the same logical finding updates the existing row and reopens it.
- `update_review_finding` accepts `finding_id` (preferred logical key) or legacy `finding_db_id`; optional `resolution_notes` is required for `wontfix` / `deferred`, and `reopen_reason` is required for non-open -> `open` transitions.
- `reopen_review_finding` is a thin wrapper over `update_review_finding(status="open", ...)` that always requires a reopen rationale.
- `reconcile_review_findings` validates state integrity (duplicates, done+open mismatch, stale open findings, provenance completeness, reopen metadata coherence) and can apply safe dedupe fixes.
- `handoff_close_check` runs closure gates, including write-provenance checks, and can fail hard with `enforce=True`.
- Review finding write operations auto-refresh `CURRENT_TASK.md`.
- `CURRENT_TASK.md` is a generated view only; if drift is detected, regenerate from DB state.
- For finding verification/history, use `get_review_findings_summary` or `list_review_findings` instead of direct SQLite queries.

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
