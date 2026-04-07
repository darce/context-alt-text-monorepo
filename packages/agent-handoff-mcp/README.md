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
agent-handoff-mcp --workspace-root /path/to/workspace review-findings --operation list
agent-handoff-mcp --workspace-root /path/to/workspace handoff-close-check
```

Source-tree execution without installation:

```bash
PYTHONPATH=src python -m agent_handoff_mcp --workspace-root /path/to/workspace serve-stdio
```

## Token-Efficient Usage

The v2 envelope is already compact, but callers still save the most tokens by shaping read responses deliberately:

- Use `get_handoff_state(sections="identity")` for routine task checks instead of a full state fetch.
- Use `detail="summary"` on read surfaces such as `get_handoff_state`, `load_session`, `review_findings`, `search_handoff`, and `artifacts` when truncated text is acceptable.
- Use `top_n_*`, `limit=`, and `fields=` to cap read size instead of trimming large payloads client-side.
- Read from the canonical `data` block rather than expecting legacy top-level mirrors.

Package-local guidance and examples live in [docs/guides/token-efficient-usage.md](docs/guides/token-efficient-usage.md).

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

## Tool Surface

`agent-handoff-mcp` now exposes a single **17-tool** MCP surface.

Legacy `--tool-profile all|core|extended` inputs are still accepted for compatibility, but they all expose the same tool set:

```bash
agent-handoff-mcp --workspace-root /path/to/workspace --tool-profile core serve-stdio
```

### Unified surface (17 tools)

| CLI name | MCP tool |
| --- | --- |
| `state` | `get_handoff_state` |
| `set` | `set_handoff_state` |
| `event` | `record_event` |
| `next-actions` | `next_actions` |
| `review-findings` | `review_findings` |
| `review-runs` | `review_runs` |
| `handoff-close-check` | `handoff_close_check` |
| `task` | `generate_current_task_md` |
| *(no CLI)* | `load_session` |
| *(no CLI)* | `close_slice` |
| `audit-decisions` | `audit_decision_ids` |
| `export` | `export_handoff_state` |
| `import` | `import_handoff_state` |
| `archive` | `archive_task_state` |
| `task-status` | `update_task_status` |
| `artifacts` | `artifacts` |
| `handoff-search` | `search_handoff` |

`record_event` uses a typed `event` payload with `event_kind="decision" | "test_result" | "blocker"` so each variant keeps its own required fields.
`next_actions` uses `operation="list" | "add" | "update" | "complete" | "skip"`.
`review_findings` uses `operation="record" | "batch_record" | "update" | "list"`.
`review_runs` uses `operation="record" | "list" | "coverage"`.

CLI-only extras (not part of MCP registry): `artifact-list`, `artifact-terms`.

Surface classes:

- `action`: mutates canonical state; do not blind-retry
- `query`: read-only inspection of canonical state; usually safe to retry
- `generator`: derived output such as close checks, markdown renders, and metrics summaries

## Troubleshooting

The fastest first check is still:

```bash
agent-handoff-mcp --workspace-root /path/to/workspace doctor
```

If startup succeeds but calls fail, check the workspace paths first: `--workspace-root`, `--state-dir`, `--current-task-path`, and `--exports-dir` must all point at the same workspace state.
