# Agent Handoff MCP

Portable MCP server for agent handoff state, review findings, exports, and close checks.

The metrics snapshot surface also reports derived process-health signals such as reopened-finding rate, structured handoff decision completeness, and contract co-change signal, plus handoff-memory health such as hot-state size and artifact-source count, alongside the existing execution metrics.

It also supports multi-worktree coordination primitives for orchestrator/worker setups:

- registered worktree lanes
- lane-scoped activity queries
- structured worker reports
- explicit lane message threads

## Scope

This package only handles handoff state. It does not include the old WordPress, React, or repo-intel helpers from the monorepo `unified_server.py`.

The non-handoff helpers have been classified separately in [../../docs/agentic/contracts/repo-intel-mcp-candidates.md](../../docs/agentic/contracts/repo-intel-mcp-candidates.md). Most are intentionally dropped because they duplicate native search and file-navigation capabilities. The only current future candidate is the cross-boundary `trace_api_endpoint` workflow.

## Runtime State

By default, handoff state belongs to the workspace:

- SQLite DB: `.task-state/handoff.db`
- exports: `.task-state/exports/`
- generated markdown: `CURRENT_TASK.md`

Use CLI args or `AGENT_HANDOFF_*` env vars to override these paths.

## Installation

### Local beta install

Install directly from the checked-out repo:

```bash
uv tool install /path/to/context-alt-text-monorepo/packages/agent-handoff-mcp
```

or:

```bash
python -m pip install /path/to/context-alt-text-monorepo/packages/agent-handoff-mcp
```

### Versioned install from a pinned git tag

For multi-machine beta use, install from a tagged monorepo revision and the package subdirectory:

```bash
uv tool install "git+ssh://git@github.com/<org>/context-alt-text-monorepo.git@agent-handoff-mcp-v0.1.0#subdirectory=packages/agent-handoff-mcp"
```

or:

```bash
python -m pip install "agent-handoff-mcp @ git+ssh://git@github.com/<org>/context-alt-text-monorepo.git@agent-handoff-mcp-v0.1.0#subdirectory=packages/agent-handoff-mcp"
```

`pyproject.toml` is the correct packaging entrypoint for this. The install target is the package subdirectory, and the git tag pins the deployed version without requiring a separate package registry.

## Usage

Run the MCP server over stdio:

```bash
agent-handoff-mcp --workspace-root /path/to/repo serve-stdio
```

Run the MCP server over HTTP:

```bash
agent-handoff-mcp --workspace-root /path/to/repo serve-http
```

Current HTTP defaults:

- host: `127.0.0.1`
- port: `8000`
- endpoint path: `/mcp`

This package's CLI does not currently expose dedicated `--host`, `--port`, or `--path` flags; `serve-http` uses FastMCP's current defaults.

Run the fallback CLI:

```bash
agent-handoff-mcp --workspace-root /path/to/repo doctor
agent-handoff-mcp --workspace-root /path/to/repo state
agent-handoff-mcp --workspace-root /path/to/repo review-list
agent-handoff-mcp --workspace-root /path/to/repo lane-list
agent-handoff-mcp --workspace-root /path/to/repo switch <task_ref>
```

Repo-local development without installing still works:

```bash
PYTHONPATH=packages/agent-handoff-mcp/src python -m agent_handoff_mcp --workspace-root /path/to/repo serve-stdio
```

## Adapter Shape

Example client adapter:

```json
{
  "name": "altcontext-mcp",
  "command": "agent-handoff-mcp",
  "args": ["--workspace-root", "/path/to/repo", "serve-stdio"]
}
```

## Client Adapters

VS Code workspace adapter:

```json
{
  "servers": {
    "altcontext-mcp": {
      "command": "python3",
      "args": [
        "${workspaceFolder}/packages/agent-handoff-mcp/src/agent_handoff_mcp_launcher.py",
        "--workspace-root",
        "${workspaceFolder}",
        "--state-dir",
        "${workspaceFolder}/.task-state",
        "--current-task-path",
        "${workspaceFolder}/CURRENT_TASK.md",
        "--exports-dir",
        "${workspaceFolder}/.task-state/exports",
        "serve-stdio"
      ],
      "env": {
        "PYENV_VERSION": "description-service",
        "PYTHONPATH": "${workspaceFolder}/packages/agent-handoff-mcp/src:${workspaceFolder}/packages/codex-subagent-bridge/src"
      }
    }
  }
}
```

The checked-in VS Code adapter now launches the repo-local Python entrypoint so
workspace state and pyenv selection stay explicit. The shell shim remains
available only as a local fallback for development and diagnostics.

Codex / generic stdio client:

```json
{
  "name": "altcontext-mcp",
  "command": "python3",
  "args": [
    "/path/to/repo/packages/agent-handoff-mcp/src/agent_handoff_mcp_launcher.py",
    "--workspace-root",
    "/path/to/repo",
    "--state-dir",
    "/path/to/repo/.task-state",
    "--current-task-path",
    "/path/to/repo/CURRENT_TASK.md",
    "--exports-dir",
    "/path/to/repo/.task-state/exports",
    "serve-stdio"
  ],
  "cwd": "/path/to/repo",
  "env": {
    "PYENV_VERSION": "description-service",
    "PYTHONPATH": "/path/to/repo/packages/agent-handoff-mcp/src:/path/to/repo/packages/codex-subagent-bridge/src"
  }
}
```

Claude / Gemini style wrapper config follows the same shape:

- keep the client registration name explicit
- launch `agent-handoff-mcp`
- pass `--workspace-root <repo> serve-stdio`
- update any tool-prefix assumptions if the registration name changes

## Multi-Worktree Workflow

When one orchestrator coordinates multiple worker worktrees:

1. Create a lane for each worker branch/worktree:

```bash
agent-handoff-mcp --workspace-root /path/to/repo lane-upsert \
  --lane-id backend-http \
  --worktree-path /path/to/repo-p5-backend-http \
  --branch codex/p5-backend-http \
  --status active
```

2. Workers record normal activity with `actor.lane_id=...` from MCP clients, or use the lane-specific CLI helpers below.

3. Workers submit structured handbacks:

```bash
agent-handoff-mcp --workspace-root /path/to/repo lane-report \
  --lane-id backend-http \
  --session phase5-http \
  --summary "Retention router slice is merge-ready." \
  --changed-file apps/prototype-description-service/recognition/interface_adapters/http/routers/retention.py \
  --test-command "pytest recognition/tests/api/test_retention_api.py" \
  --merge-ready
```

4. Either side can use explicit lane messages when direct client-to-client chat is unavailable:

```bash
agent-handoff-mcp --workspace-root /path/to/repo lane-message \
  --lane-id backend-http \
  --session phase5-http \
  --direction worker_to_orchestrator \
  --subject "Ready for review" \
  --message "Backend HTTP lane is ready for branch review."
```

5. The orchestrator can inspect one lane without reading the whole task history:

```bash
agent-handoff-mcp --workspace-root /path/to/repo lane-activity --lane-id backend-http
```

## Tool Summary

Additional lane/worktree CLI commands:

- `lane-upsert`
- `lane-list`
- `lane-activity`
- `lane-report`
- `lane-report-list`
- `lane-message`
- `lane-message-update`
- `lane-message-list`
- `switch` -- atomically archive the current task and activate a different one

## MCP Surface Classes

For agent callers, the live tool surface falls into three behavior classes:

- `action`: mutates handoff state, daemon state, lane state, or artifact state. Do not blind-retry.
- `query`: read-only inspection of canonical state. Safe to retry for transient transport/runtime failures.
- `generator`: derived output such as dashboards, search results, close checks, or rendered markdown. Usually safe to retry unless the tool also writes a file.

The canonical per-tool catalog lives in [../../docs/agentic/contracts/agent-handoff-mcp.md](../../docs/agentic/contracts/agent-handoff-mcp.md). Keep the contract doc and this README synchronized whenever the tool surface changes.

## Troubleshooting

Use the contract doc's troubleshooting ladder for four failure layers:

1. startup failure
2. capability discovery failure
3. runtime execution failure
4. evidence-write failure

The fastest first check is still:

```bash
agent-handoff-mcp --workspace-root /path/to/repo doctor
```
