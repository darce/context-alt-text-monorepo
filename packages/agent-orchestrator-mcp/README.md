# Agent Orchestrator MCP

MCP server for orchestration, lane management, worker daemons, review dispatch, and ACE metrics.

## Installation

### Standalone repository or local checkout

From the package root:

```bash
python -m pip install -e ".[dev]"
```

`agent-handoff-mcp` is a required dependency. `codex-subagent-bridge` remains optional unless you want the local bridge backend.

### Current monorepo checkout

Until extraction is complete, use the same package-root workflow from the monorepo copy:

```bash
cd /path/to/context-alt-text-monorepo/packages/agent-orchestrator-mcp
python -m pip install -e ".[dev]"
```

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

The package Makefile automatically adds sibling `../agent-handoff-mcp/src` and `../codex-subagent-bridge/src` paths when those checkouts exist. That keeps the current monorepo copy working while still allowing a clean standalone repo once dependencies are installed normally.

Direct commands also work:

```bash
PYTHONPATH=src python -m ruff check src tests
PYTHONPATH=src python -m mypy src
PYTHONPATH=src python -m pytest tests -q
```

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

If you are testing against sibling checkouts instead of installed dependencies, extend `PYTHONPATH` with those sibling `src` directories as needed.
