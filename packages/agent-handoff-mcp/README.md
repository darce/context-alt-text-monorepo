# Agent Handoff MCP

Portable MCP server for agent handoff state, review findings, exports, close checks, and lane-scoped worker/orchestrator coordination.

## Scope

This package owns handoff state and related workflow primitives:

- task state, decisions, blockers, and next actions
- review findings and review runs
- generated `CURRENT_TASK.md` snapshots
- lane registration, lane activity, worker reports, and lane messages
- artifact indexing and derived metrics snapshots

It does not include unrelated repo-intel or UI helpers.

## Runtime State

By default, runtime state lives under the workspace you point the CLI at:

- SQLite DB: `.task-state/handoff.db`
- exports: `.task-state/exports/`
- generated markdown: `CURRENT_TASK.md`

Override these with CLI flags or `AGENT_HANDOFF_*` environment variables.

## Installation

### Standalone repository or local checkout

From the package root:

```bash
python -m pip install -e ".[dev]"
```

To install the CLI as a tool instead:

```bash
uv tool install /path/to/agent-handoff-mcp
```

### Current monorepo checkout

Until extraction is complete, the same package-root workflow works from the monorepo copy:

```bash
cd /path/to/context-alt-text-monorepo/packages/agent-handoff-mcp
python -m pip install -e ".[dev]"
```

### VCS install after extraction

```bash
python -m pip install "agent-handoff-mcp @ git+ssh://git@github.com/<org>/agent-handoff-mcp.git@v0.1.0"
```

## Development

All package-local development commands are intended to run from the package root:

```bash
make lint-handoff
make fix-lint-handoff
make format-handoff
make mypy-handoff
make test-handoff
make check-handoff
```

The Makefile automatically adds a sibling `../codex-subagent-bridge/src` to `PYTHONPATH` when that checkout exists. In a fully extracted repo, that fallback is unnecessary once dependencies are installed normally.

Direct commands also work:

```bash
PYTHONPATH=src python -m ruff check src tests
PYTHONPATH=src python -m mypy src
PYTHONPATH=src python -m pytest tests -q
```

## Usage

Run the MCP server over stdio:

```bash
agent-handoff-mcp --workspace-root /path/to/workspace serve-stdio
```

Run the MCP server over HTTP:

```bash
agent-handoff-mcp --workspace-root /path/to/workspace serve-http
```

FastMCP's current HTTP defaults are:

- host: `127.0.0.1`
- port: `8000`
- path: `/mcp`

Useful CLI checks:

```bash
agent-handoff-mcp --workspace-root /path/to/workspace doctor
agent-handoff-mcp --workspace-root /path/to/workspace state
agent-handoff-mcp --workspace-root /path/to/workspace review-list
agent-handoff-mcp --workspace-root /path/to/workspace lane-list
agent-handoff-mcp --workspace-root /path/to/workspace switch <task_ref>
```

Source-tree execution without installation:

```bash
PYTHONPATH=src python -m agent_handoff_mcp --workspace-root /path/to/workspace serve-stdio
```

## Client Adapter Shape

Installed console-script adapter:

```json
{
  "name": "altcontext-mcp",
  "command": "agent-handoff-mcp",
  "args": ["--workspace-root", "/path/to/workspace", "serve-stdio"]
}
```

Source checkout adapter:

```json
{
  "name": "altcontext-mcp",
  "command": "python3",
  "args": [
    "-m",
    "agent_handoff_mcp",
    "--workspace-root",
    "/path/to/workspace",
    "serve-stdio"
  ],
  "cwd": "/path/to/agent-handoff-mcp",
  "env": {
    "PYTHONPATH": "/path/to/agent-handoff-mcp/src"
  }
}
```

## Multi-Worktree Workflow

Create a lane for each worker worktree:

```bash
agent-handoff-mcp --workspace-root /path/to/workspace lane-upsert \
  --lane-id backend-http \
  --worktree-path /path/to/workspace-backend-http \
  --branch codex/backend-http \
  --status active
```

Submit a structured handback:

```bash
agent-handoff-mcp --workspace-root /path/to/workspace lane-report \
  --lane-id backend-http \
  --session backend-http \
  --summary "Retention router slice is merge-ready." \
  --changed-file src/example.py \
  --test-command "pytest tests/test_example.py -q" \
  --merge-ready
```

Send an explicit lane message:

```bash
agent-handoff-mcp --workspace-root /path/to/workspace lane-message \
  --lane-id backend-http \
  --session backend-http \
  --direction worker_to_orchestrator \
  --subject "Ready for review" \
  --message "Backend HTTP lane is ready for branch review."
```

Inspect one lane without replaying the whole task history:

```bash
agent-handoff-mcp --workspace-root /path/to/workspace lane-activity --lane-id backend-http
```

## Tool Surface

Common lane and handoff commands include:

- `lane-upsert`
- `lane-list`
- `lane-activity`
- `lane-report`
- `lane-report-list`
- `lane-message`
- `lane-message-update`
- `lane-message-list`
- `switch`

For callers, the surface is easiest to reason about in three classes:

- `action`: mutates canonical state; do not blind-retry
- `query`: read-only inspection of canonical state; usually safe to retry
- `generator`: derived output such as close checks, markdown renders, and metrics summaries

## Troubleshooting

The fastest first check is still:

```bash
agent-handoff-mcp --workspace-root /path/to/workspace doctor
```

If startup succeeds but calls fail, check the workspace paths first: `--workspace-root`, `--state-dir`, `--current-task-path`, and `--exports-dir` must all point at the same workspace state.
