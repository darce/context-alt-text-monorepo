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

## MCP Servers (Agent Tooling)

Two MCP servers are registered for this workspace. VS Code and Claude Code manage their lifecycles automatically via `.vscode/mcp.json` and `.mcp.json`.

Non-interactive harness rule: committed MCP configs use `PYENV_VERSION=description-service`; use `pyenv activate description-service` only for optional interactive shells.

### Core Ledger Server (`agent-handoff-mcp`)

Handles task state, review findings, exports/imports, close checks, and artifacts (27 tools).

```text
.vscode/mcp.json  →  scripts/mcp/mcp-server.sh run  →  agent-handoff-mcp --workspace-root <repo> serve-stdio
```

### Orchestration Server (`agent-orchestrator-mcp`)

Handles daemons, workers, lane management, plan cursors, and turn metrics (~38 tools).

```text
.vscode/mcp.json  →  python3 packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp_launcher.py --workspace-root <repo> ... serve-stdio
```

Both servers share `handoff.db` and `mcp-artifacts.db` on disk; SQLite WAL mode makes concurrent readers safe. Install both:

```bash
uv tool install "agent-handoff-mcp @ git+ssh://git@github.com/darce/mcp-agent-handoff.git"
uv tool install ./packages/agent-orchestrator-mcp
```

The old repo-intel helpers remain a separate decomposition task and are not part of either package.

### Prerequisites

- VS Code 1.99+ with Copilot (or other MCP-capable client)
- `.vscode/mcp.json` already committed to the repo
- Python 3.11+ environment
- Installed `agent-handoff-mcp` plus the repo-local `packages/agent-orchestrator-mcp/src`
- Python resolved through pyenv or another Python 3.11+ environment with the
  package dependencies installed

### Install Options

Local install from a checked-out repo:

```bash
uv tool install "agent-handoff-mcp @ git+ssh://git@github.com/darce/mcp-agent-handoff.git"
uv tool install /path/to/context-alt-text-monorepo/packages/agent-orchestrator-mcp
```

### Validation

Command Palette → `MCP: List Servers` → both "altcontext-mcp" and "altcontext-orchestrator-mcp" should appear.

```bash
agent-handoff-mcp --workspace-root "$(pwd)" doctor       # 27 tools
agent-orchestrator-mcp --workspace-root "$(pwd)" doctor  # ~38 tools
```

### Available Tools

**`agent-handoff-mcp`** (core ledger, 27 tools): task state, decisions, findings, blockers, tests, actions, artifacts, export/import, close check, `load_session`, `close_slice`, `search_handoff`.

**`agent-orchestrator-mcp`** (~38 tools): daemon lifecycle, workers, lane management, plan cursors, turn metrics, dispatch, backends, cross-task tools (`switch_task`, `get_review_findings_summary`, `reconcile_review_findings`, `get_latest_slice_review_packet`).

Example CLI equivalents:

```bash
# Core ledger
agent-handoff-mcp --workspace-root "$(pwd)" state
agent-handoff-mcp --workspace-root "$(pwd)" dashboard
agent-handoff-mcp --workspace-root "$(pwd)" handoff-close-check

# Orchestration
agent-orchestrator-mcp --workspace-root "$(pwd)" orchestrator-start --task-ref <task-ref> --backend codex-cli --model o3-mini
agent-orchestrator-mcp --workspace-root "$(pwd)" orchestrator-status
agent-orchestrator-mcp --workspace-root "$(pwd)" orchestrator-pause
agent-orchestrator-mcp --workspace-root "$(pwd)" orchestrator-resume
agent-orchestrator-mcp --workspace-root "$(pwd)" orchestrator-stop
agent-orchestrator-mcp --workspace-root "$(pwd)" dispatch \
  --lane-id <lane-id> \
  --task-ref <task-ref> \
  --backend codex-subagent \
  --model gpt-5.4-mini \
  --start-worker
```

For Codex app sessions on the same machine, prefer the checked-in project-scoped
adapter at [`../../.codex/config.toml`](../../.codex/config.toml),
which registers the local stdio server as `altcontext-mcp` with the required
`PYENV_VERSION=description-service` contract and repo-relative startup paths.

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
tunneling or a reverse proxy. See [playbooks/host-adapters/codex-custom-mcp-playbook.md](playbooks/host-adapters/codex-custom-mcp-playbook.md)
for the full attach-to-Codex walkthrough.

### Troubleshooting

If tools don't appear in VS Code:

1. Check `MCP: List Servers` — server should be listed
2. Ensure the selected Python environment has `fastmcp`
3. Test manually: `agent-handoff-mcp --workspace-root "$(pwd)" serve-stdio` (should block on stdin)
4. Check VS Code Output panel → "MCP" for error messages

Handoff guard commands:

- `make handoff-close-check` runs `handoff_close_check(enforce=True, current_commit_sha=<HEAD>)` for the active task and fails if the current commit is missing a structured `slice_complete_*` summary.
- `make handoff-integrity-check` runs the CLI parser/lifecycle guard used by CI.

### Phase 5 Lifecycle

Phase 5 (Verification & Handoff) follows implementation:

1. **5.1 Cross-Lane Verification**: `make check-all` from the root.
2. **5.2 Documentation Audit**: Verify `docs/`, `CURRENT_TASK.json`, and `CHANGELOG`.
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
- Write tools (`record_decision`, `update_next_actions`, `record_test_result`, `report_blocker`, `record_review_finding`, `update_review_finding`) target the active task only.
- To switch between tasks, use `switch_task(task_ref)` on `agent-orchestrator-mcp`. It auto-archives the outgoing task and restores the target's objective from its archive. This replaces the multi-step `archive_task_state` + `set_handoff_state` workflow.
- For in-place updates to the _current_ task (status, objective change), use `set_handoff_state(...)` directly.
- Optional write provenance is passed as `actor={ "agent"?: str, "branch"?: str, "commit_sha"?: str }`.
- Optional review finding details are passed as `details={ "line_start"?: int, "line_end"?: int, "fix"?: str }`.
- `record_review_finding` is unique per `(task_ref, finding_id)`; re-recording the same logical finding updates the existing row and reopens it.
- `update_review_finding` accepts `finding_id` (preferred logical key) or legacy `finding_db_id`; optional `resolution_notes` is required for `wontfix` / `deferred`, and `reopen_reason` is required for non-open -> `open` transitions.
- `update_review_finding` with `status="open"` and `reopen_reason` performs the reopen (the former `reopen_review_finding` wrapper is no longer MCP-exposed).
- `reconcile_review_findings` (on `agent-orchestrator-mcp`) validates state integrity (duplicates, done+open mismatch, stale open findings, provenance completeness, reopen metadata coherence) and can apply safe dedupe fixes.
- `handoff_close_check` runs closure gates, including write-provenance checks and current-commit slice-summary presence, and can fail hard with `enforce=True`.
- Review finding write operations auto-refresh `CURRENT_TASK.json`.
- `CURRENT_TASK.json` is a generated view only; if drift is detected, regenerate from DB state.
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

1. `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/lane_prompt.py` renders an actionable worker prompt from MCP state (open lane messages, pending actions, open blockers, open findings).
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
