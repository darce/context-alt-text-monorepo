# codex-subagent-bridge

Optional bridge module that satisfies the `codex_subagent_bridge.run_subagent(...)`
contract used by the daemon orchestration layer.

It launches `codex app-server --listen stdio://`, drives a single structured turn,
and returns the final structured payload as a Python `dict`.

## Provisioning

- Editable install: `pip install -e packages/codex-subagent-bridge`
- Import-path injection: add `packages/codex-subagent-bridge/src` to `PYTHONPATH`
- Host injection: pre-populate `sys.modules["codex_subagent_bridge"]`

## Runtime behavior

- The bridge keeps the existing daemon seam: `prompt + schema + cwd + optional env -> dict`
- `env` values are treated as local runtime hints only and become subprocess/session context for `codex app-server`
- `CODEX_REASONING_EFFORT` or `REASONING_EFFORT` map to `turn/start.effort` when set to `low`, `medium`, or `high`
- MCP endpoints and credentials are not forwarded through the bridge
- Build and test commands must still be discoverable from the worktree instruction surface or included in the rendered prompt
- `run_subagent()` is concurrency-safe for parallel calls because each invocation launches and tears down its own app-server process
- Set `CODEX_SUBAGENT_BRIDGE_SESSION_MODE=shared` to opt into a long-lived app-server process that is reused across calls for the same `cwd` and compatible runtime hints. Each call still starts a fresh thread, and the shared client is discarded automatically if a turn fails.

## Adapter note

For a non-Codex host example, see [docs/agentic/contracts/subagent-bridge-interface-note.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/contracts/subagent-bridge-interface-note.md).
