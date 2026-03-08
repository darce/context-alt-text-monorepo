# Agent Handoff MCP

Portable MCP server for agent handoff state, review findings, exports, and close checks.

## Scope

This package only handles handoff state. It does not include the old WordPress, React, or repo-intel helpers from the monorepo `unified_server.py`.

The non-handoff helpers have been classified separately in [`repo-intel-mcp-candidates.md`](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/contracts/repo-intel-mcp-candidates.md). Most are intentionally dropped because they duplicate native search and file-navigation capabilities. The only current future candidate is the cross-boundary `trace_api_endpoint` workflow.

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

Run the fallback CLI:

```bash
agent-handoff-mcp --workspace-root /path/to/repo doctor
agent-handoff-mcp --workspace-root /path/to/repo state
agent-handoff-mcp --workspace-root /path/to/repo review-list
```

Repo-local development without installing still works:

```bash
PYTHONPATH=packages/agent-handoff-mcp/src python -m agent_handoff_mcp --workspace-root /path/to/repo serve-stdio
```

## Adapter Shape

Example client adapter:

```json
{
  "name": "agent-handoff",
  "command": "agent-handoff-mcp",
  "args": ["--workspace-root", "/path/to/repo", "serve-stdio"]
}
```

## Client Adapters

VS Code workspace adapter:

```json
{
  "servers": {
    "context-alt-text": {
      "command": "agent-handoff-mcp",
      "args": ["--workspace-root", "${workspaceFolder}", "serve-stdio"]
    }
  }
}
```

The checked-in VS Code adapter now launches `agent-handoff-mcp` directly. The shell shim remains available only as a local fallback for development and diagnostics.

Codex / generic stdio client:

```json
{
  "name": "agent-handoff",
  "command": "agent-handoff-mcp",
  "args": ["--workspace-root", "/path/to/repo", "serve-stdio"]
}
```

Claude / Gemini style wrapper config follows the same shape:

- keep the client registration name explicit
- launch `agent-handoff-mcp`
- pass `--workspace-root <repo> serve-stdio`
- update any tool-prefix assumptions if the registration name changes
