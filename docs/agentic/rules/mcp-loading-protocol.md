# MCP Loading Protocol

> **Harness-agnostic.** This protocol applies to any agent (Claude Code, Codex, future) that connects to the project's MCP servers. It is the single source of truth for *which* MCP servers to surface at session start and *when* to surface them.

## Why this exists

Every MCP server an agent loads costs prompt tokens — the server's tool schemas are advertised in the initial tool list and stay in context for the whole session. The project has multiple MCP servers (`agent-handoff-mcp`, `agent-orchestrator-mcp`, `context7`, `computer-use`), and most sessions only need one or two of them. Eager-loading all of them at every session start wastes thousands of tokens and degrades the agent's effective context window.

The opposite extreme — leaving every server deferred and forcing the agent to discover what it needs in the moment — is brittle: the agent has to guess, mistakes are silent, and the rules drift over time.

This protocol splits the difference with **declarative routing**: the rules live in a YAML file, the agent applies them mechanically at session start, and the decision is reproducible across harnesses.

## Where the rules live

- **Routing data**: [`docs/agentic/maps/mcp-tool-routing.yaml`](../maps/mcp-tool-routing.yaml) — the always/on-demand/exclude lists keyed by triggers.
- **This document**: the protocol and rationale.

Harness-specific entry files (`CLAUDE.md`, `AGENTS.md`, future) **link** to this document; they do not duplicate the rules. Updates to the routing model happen in the YAML and this doc, then propagate everywhere.

## Loading model

Three categories per server:

| Category | Meaning | When to load |
|---|---|---|
| `always` | The server is needed in essentially every dev session. | Eagerly, at session start. |
| `on_demand` | The server is needed only when a trigger fires. | Lazily, the moment a keyword / path / role / criteria match is observed. |
| `exclude` | The server is *guaranteed* unnecessary if the changed-file scope matches the listed paths. | Never, even if a keyword trigger would otherwise match. |

Triggers under `on_demand.<server>`:

- **`keywords`** — substrings to scan in the user prompt and the active task objective/focus.
- **`paths`** — globs against the changed-file list (or the active worktree's scope).
- **`roles`** — symbolic role names from the [Role Selection table](../instructions.md#role-selection).
- **`criteria_doc`** — pointer to a separate doc that defines additional gate criteria (e.g. `context7`'s entry criteria).

A server is loaded when **any** trigger matches AND **no** exclusion applies.

## Session-start algorithm

```
1. Load every server in `always`.
2. Read the user prompt + active task identity (target_branch, target_worktree_path, role).
3. Compute the changed-file scope (git diff --name-only against the merge base).
4. For each server in `on_demand`:
     a. If `exclude.<server>` is defined and ALL changed files match an exclude glob,
        skip this server entirely.
     b. Otherwise scan triggers in order:
          - keywords: scan user prompt + task objective + task focus (case-insensitive).
          - paths: glob the changed-file scope.
          - roles: match against the active role from CLAUDE.md role routing.
          - criteria_doc: read the linked criteria doc and apply its gate.
        If any trigger matches, load the server's tools immediately.
        Concretely on Claude Code: `ToolSearch select:mcp__<server>__*` to surface the
        deferred tool schemas. On Codex: the equivalent activation call for the harness.
5. Proceed with the rest of the Agent Startup Protocol.
```

## What this protocol does NOT do

- It does not change which servers are *configured* in `.mcp.json` or `.codex/config.toml`. Those files still list every server. The protocol controls *when the agent surfaces them*, not whether the harness can connect.
- It does not disable harness features like Claude Code's `ToolSearch`. The protocol is layered on top of `ToolSearch`; it tells the agent *when to call it*, not *whether to call it*.
- It does not enforce loading via a hook. The agent reads the YAML at session start and applies the rules itself. A hook-based enforcement layer is a possible future extension.

## Pattern lineage

The model is borrowed from CodeRabbit's `.coderabbit.yaml` configuration, specifically:

- **Glob-gated instruction fragments** — CodeRabbit's `path_instructions[]` injects per-glob review rules into the per-file prompt; rules for `src/api/**` never appear when reviewing `tests/**`. Here we apply the same shape: trigger-gated MCP servers that surface only when their scope matches.
- **Pre-flight exclusion** — CodeRabbit drops ~100 binary/lockfile glob patterns before tokenizing. The `exclude` block here mirrors that: definitive "never load this server for this scope" rules that short-circuit the keyword scan.
- **Declarative > runtime negotiation** — CodeRabbit's gating is YAML-driven and evaluated per file. There is no runtime "session start handshake" — the YAML *is* the contract. We do the same: the routing YAML is the contract, the agent reads it and applies it.

What we explicitly do NOT borrow:

- CodeRabbit's two-pass cheap-model triage. We don't have a separate classifier model; `load_session` is the closest analog and is already cheap enough.
- CodeRabbit's token-budgeted greedy packing. With four MCP servers the constraint is binary (load / don't), not packing under a budget.

## Maintaining the routing rules

When you add or remove an MCP server, or when you discover a missing trigger:

1. Edit [`docs/agentic/maps/mcp-tool-routing.yaml`](../maps/mcp-tool-routing.yaml).
2. If the change reflects a new pattern (not just a new keyword), update the rationale in this doc.
3. Test on the next session: confirm the agent loads the right server set for a representative prompt.
4. Record the change as a handoff `decision` so the routing change is auditable.

Do NOT add server-loading logic to harness-specific files (`CLAUDE.md`, `AGENTS.md`, etc.). Those files should only link here.
