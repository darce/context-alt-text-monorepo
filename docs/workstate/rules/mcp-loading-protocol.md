# MCP Loading Protocol

> **Harness-agnostic.** Single source of truth for *which* MCP servers to surface at session start and *when* to surface them.

## Why this exists

Each loaded MCP server costs prompt tokens for the entire session. Most sessions need only one or two of the three servers (`workstate-handoff-mcp`, `workstate-orchestrator-mcp`, `computer-use`). This protocol uses **declarative routing**: rules in a YAML file, applied mechanically at session start, reproducible across harnesses.

## Where the rules live

- **Routing data**: [`docs/workstate/maps/mcp-tool-routing.yaml`](../maps/mcp-tool-routing.yaml) — the always/on-demand/exclude lists keyed by triggers.
- **This document**: the protocol and rationale.

Harness entry files (`CLAUDE.md`, `AGENTS.md`) **link** here; they do not duplicate the rules.

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
- **`criteria_doc`** — pointer to a separate doc that defines additional gate criteria for a server.

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

- Does not change which servers are *configured* in `.mcp.json` / `.codex/config.toml`. Controls *when* the agent surfaces them, not whether the harness can connect.
- Does not disable `ToolSearch`. Tells the agent *when* to call it.
- Does not enforce loading via a hook. The agent applies rules itself.

## Pattern lineage

Borrowed from CodeRabbit's `.coderabbit.yaml`: glob-gated instruction fragments (trigger-scoped servers), pre-flight exclusion (short-circuit keyword scan), and declarative-over-runtime-negotiation (YAML is the contract).

## Maintaining the routing rules

1. Edit [`docs/workstate/maps/mcp-tool-routing.yaml`](../maps/mcp-tool-routing.yaml).
2. If the change reflects a new pattern, update rationale in this doc.
3. Verify the agent loads the correct server set on next session.
4. Record the change as a handoff `decision`.

Do NOT add server-loading logic to harness-specific files. They link here only.
