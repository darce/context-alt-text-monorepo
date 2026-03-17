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

The workspace-local MCP adapter now points directly at the installed `agent-handoff-mcp` binary. VS Code manages the server lifecycle automatically.

### How It Works

```
.vscode/mcp.json  →  agent-handoff-mcp --workspace-root <repo> serve-stdio
```

The packaged server is handoff-only: task state, review findings, exports/imports, dashboard, and close checks. The old repo-intel helpers remain a separate decomposition task and are not part of this package.

### Prerequisites

- VS Code 1.99+ with Copilot (or other MCP-capable client)
- `.vscode/mcp.json` already committed to the repo
- Python 3.11+ environment
- Preferred: installed `agent-handoff-mcp` binary
- Fallback for local development: package source at `packages/agent-handoff-mcp/src` available to the launcher

### Install Options

Local beta from a checked-out repo:

```bash
uv tool install /path/to/context-alt-text-monorepo/packages/agent-handoff-mcp
```

Pinned git-tag install from the monorepo:

```bash
uv tool install "git+ssh://git@github.com/<org>/context-alt-text-monorepo.git@agent-handoff-mcp-v0.1.0#subdirectory=packages/agent-handoff-mcp"
```

This uses the package [`pyproject.toml`](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/pyproject.toml) as the canonical packaging contract. That is the right practice here because the install target is a real Python package living inside a monorepo subdirectory.

### Validation

Command Palette → `MCP: List Servers` → "context-alt-text" should show the registered adapter.

### Available Tools

This adapter exposes the handoff tool family only. Use editor-native tools for file search/read/navigation until the separate repo-intel MCP work lands.

Daemon-8 extended that surface with orchestration controls:

- `orchestrator_start`
- `orchestrator_status`
- `orchestrator_stop`
- `orchestrator_pause`
- `orchestrator_resume`
- `run_structured_turn`

These tools are intended for in-app agents that already have MCP access to the
authoritative checkout. `run_structured_turn` is bridge-only and rejects
`codex-cli`.

Example CLI equivalents:

```bash
agent-handoff-mcp --workspace-root "$(pwd)" orchestrator-start --task-ref <task-ref> --backend codex-cli
agent-handoff-mcp --workspace-root "$(pwd)" orchestrator-status
agent-handoff-mcp --workspace-root "$(pwd)" orchestrator-pause
agent-handoff-mcp --workspace-root "$(pwd)" orchestrator-resume
agent-handoff-mcp --workspace-root "$(pwd)" orchestrator-stop
agent-handoff-mcp --workspace-root "$(pwd)" run-structured-turn \
  --prompt-file /tmp/prompt.md \
  --schema-file /tmp/schema.json \
  --cwd /absolute/path/to/worktree \
  --backend codex-subagent
```

Remote HTTP deployment for Codex custom MCP is intentionally tracked as follow-on
work in daemon-9. Daemon-8's completed scope is the in-repo MCP tool surface and its
CLI/stdio exposure.

### Troubleshooting

If tools don't appear in VS Code:

1. Check `MCP: List Servers` — server should be listed
2. Ensure the selected Python environment has `fastmcp`
3. Test manually: `agent-handoff-mcp --workspace-root "$(pwd)" serve-stdio` (should block on stdin)
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

### Lane Run Pipeline

`make lane-run` automates worker execution via `codex exec`. The pipeline:

1. `scripts/mcp/lane_prompt.py` renders an actionable worker prompt from MCP state (open lane messages, pending actions, open blockers, open findings).
2. `codex exec` runs in the lane worktree with that prompt.
3. The worker outputs a structured JSON result matching the schema from `scripts/mcp/lane_result.py schema`.
4. `scripts/mcp/lane_result.py handoff` converts the result into a `scripts/worktree-lane report` call.

Required JSON output schema from the worker:

```json
{
  "handoff_action": "merge_ready | needs_guidance",
  "summary": "One short sentence for the orchestrator.",
  "details": "What changed or was verified, and why the lane is ready or blocked.",
  "tests_run": ["make test"],
  "blockers": []
}
```

- `merge_ready`: lane-result runs `make lane-commit` then submits a merge-ready worker report.
- `needs_guidance`: lane-result submits a blocked worker report with the listed blockers.

---
