# Agent Orchestrator MCP

MCP server for orchestration, lane management, worker daemons, review dispatch, and ACE metrics.

## Installation

### Standalone repository or local checkout

From the package root:

```bash
python -m pip install "agent-handoff-mcp @ git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0"
python -m pip install -e ".[dev]"
```

`agent-handoff-mcp` is a required dependency. `codex-subagent-bridge` remains optional unless you want the local bridge backend.

## Development

Run package-local commands from the package root:

```bash
make lint-orchestrator
make fix-lint-orchestrator
make format-orchestrator
make mypy-orchestrator
make test-orchestrator
make check-orchestrator
```

The package Makefile keeps `codex-subagent-bridge` as an optional sibling source path for local bridge-backend development, but it expects `agent-handoff-mcp` to be installed as a normal package dependency.

Direct commands also work:

```bash
PYTHONPATH=src python -m ruff check src tests
PYTHONPATH=src python -m mypy src
PYTHONPATH=src python -m pytest tests -q
```

## Token-Efficient Usage

For bounded reads and compact caller patterns, follow the shared guide in [`packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md`](../agent-handoff-mcp/docs/guides/token-efficient-usage.md). The orchestrator package reuses that guidance instead of maintaining a separate copy of the same parameter semantics.

## Runtime Notes

This package orchestrates work against a target workspace. The workspace you point it at still needs the expected task state and orchestration inputs, such as:

- `.task-state/`
- lane manifests
- task plans or other orchestration docs the lane logic references

Those assets belong to the workspace being orchestrated, not to the package checkout itself.

## Backends

The orchestration layer supports multiple execution backends, including:

- `codex-cli`
- `codex-subagent`
- `claude-code`
- `local-model-openai`

Some backends are optional and require host-specific tooling to be installed separately.

## Source Checkout Usage

For local source execution without installation:

```bash
PYTHONPATH=src python -m agent_orchestrator_mcp --help
```

If you are testing against a sibling `codex-subagent-bridge` checkout instead of an installed bridge dependency, extend `PYTHONPATH` with that sibling `src` directory as needed.
