# Investigation: review_runs MCP Tool Not Exposed in VS Code/Copilot Session

**Date:** 2026-04-16
**Task ref:** E17-6
**MCP decision:** #1854 (`claude_investigate_E17-6_review-runs-tool-bridge-gap`)
**MCP finding:** E17-6-INV-02 (closed, wontfix)

## Symptom

During E17-6 implementation, the `review_runs` MCP tool was unavailable in the VS Code/Copilot chat session. Adjacent tools from the same server (`review_findings`, `record_event`, `get_handoff_state`) were all available. The agent had to fall back to the Python API for review-run operations.

## Investigation Trace

### Layer 1: MCP Server Registration

`.vscode/mcp.json` registers `altcontext-mcp` via stdio transport with no per-tool allowlist. All tools advertised by the server should be projected into the session.

### Layer 2: Package Tool Registry

`packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` (lines 1348-1368) registers `review_runs` as a `ToolEntry` with:
- `cli_name="review-runs"`
- `surface_class="action"`
- `entity_family="review_runs"`

### Layer 3: Package Exports

`packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` exports `review_runs`, `record_review_run`, and `list_review_runs` at the package root.

### Layer 4: Smoke Tests

`packages/agent-handoff-mcp/tests/test_stdio.py` asserts `"review_runs" in tool_names`, confirming the stdio server advertises the tool.

### Layer 5: Harness Hook References

Both harness configurations reference the tool:
- `.github/hooks/terminal-guard.json`: `mcp_altcontext-mc_review_runs` in the regenerate-task-views matcher
- `.claude/settings.json`: `mcp__agent-handoff-mcp__review_runs` in the PostToolUse hook

### Layer 6: VS Code/Copilot Session Bridge

This is where the tool disappears. The Copilot MCP integration projects a subset of server-advertised tools into the chat session. The projection mechanism is opaque; it may involve caching, batching, or a tool-count limit. No repo-side configuration controls this layer.

## Root Cause

The gap is in the live VS Code/Copilot session bridge, not in the repository. All layers under repo control (server code, package exports, tests, harness hooks) correctly include `review_runs`. The tool's absence is a session-level artifact of the Copilot MCP tool projection layer, possibly due to:

- Stale tool cache from a previous server version that lacked the tool
- Tool-count batching that deprioritized the tool
- A transient deserialization issue on the client side

## Workaround

1. **Reload MCP session**: force tool re-introspection by reloading the Copilot chat window or restarting VS Code
2. **Python API fallback**: use `from agent_handoff_mcp import review_runs, record_review_run, list_review_runs` via terminal

## Resolution

Closed as wontfix. No repo-side fix is possible; the defect is in the VS Code/Copilot session bridge. The Python API fallback is reliable and sufficient.
