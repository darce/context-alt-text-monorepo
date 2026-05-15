# ADR-010: Agentic Plugin Distribution

> **Metadata**
>
> - **Date**: 2026-05-15
> - **Author**: GitHub Copilot
> - **Status**: Accepted
> - **Decided on**: 2026-05-15
> - **Accepting decision**: `codex_accept_adr010_agentic_plugin_distribution_20260515`
>
> **Purpose:** Decide how shared agentic skills, command registrations, and MCP server registrations are distributed to Claude Code and Codex consumers without continuing the in-repo symlink/bootstrap-adapter model.

---

## Status

Accepted

## Date

2026-05-15

## Decision Date

2026-05-15

## Accepting Decision

`codex_accept_adr010_agentic_plugin_distribution_20260515`

## Context

The E17 workflow system currently ships shared agentic surfaces through repo-local files: `.claude/skills/`, `.claude/commands/`, `.codex/skills/`, generated prompt/router files, and hand-synced instruction surfaces. The older hoist scope selected a symlink plus bootstrap-CLI model, but current harness behavior makes plugin-native distribution a better fit: Claude Code supports `.claude-plugin/plugin.json`, Codex exposes plugin installation/discovery surfaces, and both harnesses can consume copied `SKILL.md` bodies from a plugin cache.

The E17-15 spec records the current constraints:

- `agentic-protocol-monorepo` is the canonical remote implementation repo for shared skills, plugin manifests, generator code, emitted plugin trees, and distribution documentation.
- `context-alt-text-monorepo` stages and reviews the planning bundle first because E17 handoff/review state lives here.
- `darce/mcp-agent-handoff` and `darce/mcp-agent-orchestrator` remain private source repos, but plugin manifests launch the existing runtime packages through the current `uvx` pins: `mcp-agent-handoff==0.11.2` and `mcp-agent-orchestrator==0.4.6`.
- VS Code Copilot has no equivalent plugin manifest in scope; its current generated instruction path remains separate.

## Decision

Adopt a **plugin-native, single-source skill distribution** model for Claude Code and Codex.

1. Canonical cross-harness skill bodies live in `agentic-protocol-monorepo/packages/agentic-system/skills/<name>/SKILL.md`.
2. `agentic-protocol-monorepo` owns a registration manifest and deterministic generator that emits Claude and Codex plugin trees from the same inputs.
3. Emitted plugin manifests include skill registrations, command/slash-command registrations, and `mcpServers` entries that preserve the current `uvx` package-pin launch form for the MCP servers.
4. Consumer repos install the private plugin through harness-native plugin mechanisms and do not author or vendor shared skill bodies locally.
5. Project-local overrides must use distinct local skill names. They do not shadow plugin-shipped shared skills.
6. This decision supersedes the hoist scope's symlink plus bootstrap-CLI model for shared skill/command distribution. Bootstrap-style installation may still exist as a helper for consumer setup, but it is no longer the source-of-truth distribution architecture for shared skills.

## Why This Decision

### It removes duplicated picker surfaces

The current repo-local model can expose both skill bodies and generated command adapters for the same workflow. A plugin tree gives each harness one registration surface per shared skill.

### It matches harness ownership

Claude and Codex already cache or install plugin contents in harness-owned locations. Generating plugin manifests and copied skill bodies lets the harness own discovery while keeping authoring centralized.

### It preserves MCP runtime behavior

This ADR does not change MCP server packaging. The plugin registers how to launch the existing MCP packages; it does not repackage or publish MCP server code.

### It keeps consumer cleanup bounded

The monorepo can remove shared skill/command/prompt copies only after a remote plugin tree is installable. Until then, current harness surfaces remain as the working fallback.

## Alternatives Considered

### 1. Keep the symlink plus bootstrap-CLI model

Rejected.

Symlink overlays remain useful for some setup flows, but they fight harness plugin caches and do not solve duplicate picker entries as cleanly as native plugin manifests.

### 2. Publish MCP servers or skills to public marketplaces

Rejected.

The current requirement is private Daniel-owned repos and no new public marketplace or package publication work.

### 3. Generate skill bodies from a higher-level schema

Rejected.

The current `SKILL.md` bodies are human-authored operational guidance. Determinism belongs at the registration and emitted-tree layer, not at a body-generation layer.

### 4. Include VS Code Copilot plugin distribution now

Rejected.

Copilot has no equivalent first-party plugin manifest in this workflow. Its generated instruction surface remains outside this ADR.

## Consequences

### Positive

- One canonical authored skill body can feed both Claude and Codex.
- Consumer repos stop carrying shared skill bodies once they install the plugin.
- MCP server startup remains compatible with current `uvx` package-pin launchers.
- The remote implementation owner is clear: `agentic-protocol-monorepo`.

### Negative

- Consumer migration cannot happen until the remote plugin tree is built and installable.
- Claude and Codex schema differences must be resolved in the generator and validated against live plugin behavior.
- VS Code Copilot remains on a separate generated-instructions path.

## Verification

- `agentic-protocol-monorepo` generator emits Claude and Codex plugin trees deterministically.
- Emitted Claude and Codex skill body copies are byte-identical.
- Emitted `mcpServers` entries launch `mcp-agent-handoff==0.11.2` and `mcp-agent-orchestrator==0.4.6` through `uvx`.
- Consumer monorepo migration verifies Claude and Codex discover each shared skill once from the plugin install path.

## Related Artifacts

- [docs/specs/agentic-plugin-distribution-spec.md](../specs/agentic-plugin-distribution-spec.md)
- [docs/tasks/17.0/E17-15-agentic-plugin-distribution-task-plan.md](../tasks/17.0/E17-15-agentic-plugin-distribution-task-plan.md)
- [docs/scopes/hoist-agentic-system-to-remote-scope.md](../scopes/hoist-agentic-system-to-remote-scope.md)