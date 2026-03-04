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
make php-cs-fix                      # PHPCBF only (mutating)

# Root convenience target (mutating)
cd ../..
make fix-php-style                   # Runs plugin PHPCBF fixer
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

Command Palette → `MCP: List Servers` → "context-alt-text" should show this server and its custom tools.

### Available Tools

These tools handle cross-boundary and domain-specific queries. For generic operations, use editor-native tools (for example, `search_code`, `find_definition`, `read_file`, `list_dir`, diagnostics) or Pylance MCP tools.

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

## MCP Handoff Protocol

Before any code exploration:

1. Call `get_handoff_state(task_ref="<task>")`.
2. If no active state exists, call `set_handoff_state(...)` to initialize it.
3. Do not use manual edits to `CURRENT_TASK.md` for state tracking.

During work:

1. Record non-trivial decisions with `record_decision(..., actor={ agent?, branch?, commit_sha? })`.
2. Add/update/complete task steps with `update_next_actions(..., actor={ ... })`.
3. Record blockers immediately with `report_blocker(..., actor={ ... })`.
4. Record verification commands with `record_test_result(..., actor={ ... })`.
5. Record/code-review findings with `record_review_finding(..., details={ line_start?, line_end?, fix? }, actor={ ... })`.
6. Update finding status with `update_review_finding(..., actor={ ... })`.
7. Validate review state using `get_review_findings_summary(...)` and `list_review_findings(...)` (not direct `sqlite3` queries).

Write-tool targeting rule:

- Write tools target the **active task only**.
- To write against a different task, switch active state first via `set_handoff_state(...)`.

Before final response:

1. Mark completed/skipped actions via `update_next_actions(...)`.
2. Update singleton state via `set_handoff_state(..., expected_revision=<current>, actor={ ... })`.
3. Regenerate `CURRENT_TASK.md` using `generate_current_task_md(...)`.
4. Include a one-line status marker in the response: `Handoff updated: yes`.

Read discipline:

- Do not query `.task-state/handoff.db` directly when MCP tools are available.
- Use `get_handoff_state` for active-task snapshot, `get_review_findings_summary` for counts, and `list_review_findings`/`get_review_finding` for detailed review verification.

State integrity invariants:

- Treat import/restore payloads as untrusted input. Validate payload shape and required object types before writes; malformed payloads must return `ok: false` (never silent success/no-op).
- Preserve write provenance on mutable records (for example review findings): creation metadata (`agent`, `branch`, `commit_sha`) is immutable once set; status updates may fill missing fields but must not overwrite recorded provenance.

Failure policy:

- If MCP handoff tools are unavailable, stop normal implementation work.
- Record/report the blocker, and include: `Handoff updated: no (tool unavailable)`.
- Use `templates/CURRENT_TASK.template.md` only as fallback when MCP handoff is unavailable.

Completion gate:

- A task response is incomplete if MCP handoff was not updated.
