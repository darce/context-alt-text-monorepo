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

## ctx7 (Library Documentation)

ctx7 fetches current upstream library documentation on demand. Use it instead of relying on static
generic reference in guideline files.

### Installation

```bash
brew install ctx7          # CLI binary for interactive doc queries
# MCP server is registered in .vscode/mcp.json (npx, no separate install)
```

### Verification

```bash
ctx7 library fastapi                                          # Search; returns resolved ID, e.g. /fastapi/fastapi
ctx7 docs /fastapi/fastapi "routing and dependency injection" # Fetch docs using resolved ID
```

VS Code: Command Palette → `MCP: List Servers` → "context7" should appear.

### Service Map

Hardcoded port references appear in docker-compose files and PHP controllers.
Canonical mapping (portless integration deferred; see task plan M-2 resolution):

| Service             | Local address           |
| ------------------- | ----------------------- |
| FastAPI backend     | `http://localhost:8000` |
| PostgreSQL (local)  | `localhost:5432`        |
| PostgreSQL (Docker) | `localhost:55432`       |

See [maps/tech-stack.md](maps/tech-stack.md) for the full library manifest.

---

## MCP Server (Agent Tooling)

The workspace-local MCP adapter now points at the repo-local
`agent_handoff_mcp_launcher.py` entrypoint. VS Code manages the server lifecycle
automatically.

### How It Works

```text
.vscode/mcp.json  →  python3 packages/agent-handoff-mcp/src/agent_handoff_mcp_launcher.py --workspace-root <repo> ... serve-stdio
```

The packaged server is handoff-only: task state, review findings, exports/imports, dashboard, and close checks. The old repo-intel helpers remain a separate decomposition task and are not part of this package.

### Prerequisites

- VS Code 1.99+ with Copilot (or other MCP-capable client)
- `.vscode/mcp.json` already committed to the repo
- Python 3.11+ environment
- Repo-local package source at `packages/agent-handoff-mcp/src`
- Python resolved through pyenv or another Python 3.11+ environment with the
  package dependencies installed

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

Command Palette → `MCP: List Servers` → "altcontext-mcp" should show the registered adapter.

### Available Tools

This adapter exposes the handoff tool family only. Use editor-native tools for file search/read/navigation until the separate repo-intel MCP work lands.

Daemon-8 extended that surface with orchestration controls:

- `orchestrator_start`
- `orchestrator_status`
- `orchestrator_stop`
- `orchestrator_pause`
- `orchestrator_resume`
- `worker_start` (with optional `model`, `backend`, `reasoning_effort`)
- `worker_start_all` (with optional `model`, `backend`)
- `worker_status`
- `worker_stop`
- `worker_resume`
- `run_structured_turn`
- `dispatch_lane_work`
- `list_available_backends`

Task 8.0 (structured-memory search) added `search_handoff` for BM25/FTS5 search over canonical
handoff records (decisions, findings, blockers, actions) without reading the full snapshot:

- `search_handoff` -- keyword search scoped by `task_ref`, `lane_id`, and `record_types`; returns
  `record_type`, `record_id`, `task_ref`, `lane_id`, `status`, and a ranked snippet per hit.

These tools are intended for in-app agents that already have MCP access to the
authoritative checkout. `run_structured_turn` is bridge-only and rejects
`codex-cli`.

Example CLI equivalents:

```bash
105: agent-handoff-mcp --workspace-root "$(pwd)" orchestrator-start --task-ref <task-ref> --backend codex-cli --model o3-mini
agent-handoff-mcp --workspace-root "$(pwd)" orchestrator-status
agent-handoff-mcp --workspace-root "$(pwd)" orchestrator-pause
agent-handoff-mcp --workspace-root "$(pwd)" orchestrator-resume
agent-handoff-mcp --workspace-root "$(pwd)" orchestrator-stop
agent-handoff-mcp --workspace-root "$(pwd)" run-structured-turn \
  --prompt-file /tmp/prompt.md \
  --schema-file /tmp/schema.json \
  --cwd /absolute/path/to/worktree \
  --backend codex-subagent \
  --model gpt-5.4-mini
```

For Codex app sessions on the same machine, prefer the checked-in project-scoped
adapter at [`../../.codex/config.toml`](../../.codex/config.toml),
which registers the local stdio server as `altcontext-mcp` with the required
`PYENV_VERSION=description-service` and `PYTHONPATH` overrides for both the
handoff MCP package and the Codex subagent bridge.

Remote HTTP deployment for Codex custom MCP is intentionally tracked as follow-on
work in daemon-9. Daemon-8's completed scope is the in-repo MCP tool surface and its
CLI/stdio exposure.

### HTTP Transport (Codex Custom MCP)

For remote or Codex custom MCP attachment, use `serve-http` instead of `serve-stdio`:

```bash
make mcp-serve-http                             # localhost:8741
make mcp-serve-http HOST=0.0.0.0 PORT=9000      # custom bind
```

Or directly:

```bash
agent-handoff-mcp --workspace-root "$(pwd)" serve-http --host 127.0.0.1 --port 8741
```

Verify the endpoint is reachable:

```bash
curl -s http://127.0.0.1:8741/
```

The default bind is `127.0.0.1` (localhost only, no auth). For remote access use SSH
tunneling or a reverse proxy. See [codex-custom-mcp-playbook.md](codex-custom-mcp-playbook.md)
for the full attach-to-Codex walkthrough.

### Troubleshooting

If tools don't appear in VS Code:

1. Check `MCP: List Servers` — server should be listed
2. Ensure the selected Python environment has `fastmcp`
3. Test manually: `agent-handoff-mcp --workspace-root "$(pwd)" serve-stdio` (should block on stdin)
4. Check VS Code Output panel → "MCP" for error messages

Handoff guard commands:

- `make handoff-close-check` runs `handoff_close_check(enforce=True)` for the active task.
- `make handoff-integrity-check` runs the CLI parser/lifecycle guard used by CI.

### Phase 5 Lifecycle

Phase 5 (Verification & Handoff) follows implementation:

1. **5.1 Cross-Lane Verification**: `make check-all` from the root.
2. **5.2 Documentation Audit**: Verify `docs/`, `CURRENT_TASK.md`, and `CHANGELOG`.
3. **5.3 Handoff Closure**: `agent-handoff-mcp handoff-close-check --task-ref <task>`.

174: **BackendAdapter Protocol**: Handled in `scripts/mcp/backend_adapter.py`. All backends (Codex, Claude, Local) must implement this protocol for `execute()` and reasoning effort resolution. The `adapters/` directory contains specific implementations (e.g., `claude_code.py`).

### Handoff State Defaults

- SQLite path: `.task-state/handoff.db` (local workspace state; authoritative source of truth)
- Compact read defaults in `get_handoff_state`:
  - blockers: `5`
  - actions: `5`
  - decisions: `3`
  - tests: `3`
  - findings: `10`
- Write tools (`record_decision`, `update_next_actions`, `record_test_result`, `report_blocker`, `record_review_finding`, `update_review_finding`, `reopen_review_finding`) target the active task only.
- To switch between tasks, use `switch_task(task_ref)`. It auto-archives the outgoing task and restores the target's objective from its archive. This replaces the multi-step `archive_task_state` + `set_handoff_state` workflow.
- For in-place updates to the _current_ task (status, objective change), use `set_handoff_state(...)` directly.
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

### Structured Handoff Search

`search_handoff` (MCP) and the `handoff-search` CLI subcommand provide BM25/FTS5 keyword search
over canonical handoff records without reading the full task snapshot.

```bash
# CLI: search all record types for a keyword, scoped to a task
agent-handoff-mcp --workspace-root "$(pwd)" handoff-search \
  --query "retry policy" --task-ref <task-ref>

# CLI: narrow to decisions and blockers, multiple OR terms
agent-handoff-mcp --workspace-root "$(pwd)" handoff-search \
  --query "retry" --query "timeout" \
  --record-types decision --record-types blocker \
  --task-ref <task-ref> --limit 10
```

`run_doctor()` now includes a `checks.handoff_fts_index` entry that reports the presence and row
count of each FTS5 shadow table (`decisions_fts`, `findings_fts`, `blockers_fts`, `actions_fts`).
A count of `-1` for any table means the table is absent and structured search is degraded.

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
