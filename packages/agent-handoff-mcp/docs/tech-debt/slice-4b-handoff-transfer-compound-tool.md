# Slice 4B: `handoff_transfer` Compound Tool (Deferred from E17-7)

> **Metadata**
>
> - **Date**: 2026-04-17
> - **Project**: `agent-handoff-mcp`
> - **Status**: Tech-debt note — deferred follow-on to [E17-7 Slice 4](../../../../docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md#slice-4-mcp-tool-surface-compression)
> - **Supersedes**: E17-7 Slice 4B plan line (marked DEFERRED on `c9eff4dd`)
> - **Related tools**: `mcp__agent-handoff-mcp__export_handoff_state`, `mcp__agent-handoff-mcp__import_handoff_state`

## Problem

The MCP tool registry still advertises `export_handoff_state` and `import_handoff_state` as separate tools. Slice 4 of E17-7 originally planned to collapse them into a single compound `handoff_transfer` tool dispatched by `direction="export" | "import"` to reduce the advertised tool count and mitigate the session tool-drop risk documented in [review-runs-tool-bridge-gap-investigation](../../../../docs/assessments/review-runs-tool-bridge-gap-investigation-2026-04-16.md).

Only Slice 4A (`render_handoff`) shipped in E17-7. 4B was deferred because:

- 4A plus the existing bounded-read envelope materially mitigated the tool-count / session-drop risk.
- `export_handoff_state` and `import_handoff_state` are low-frequency lifecycle tools; they do not contribute meaningfully to per-turn token pressure.
- Compressing them adds implementation risk (atomic export/import round-trip semantics) without proportional gain on the measured cost levers.

Revisit only if advertised tool count regresses measurably or a session-drop incident is again traced to the export/import pair.

## Scope When Revived

- Introduce a single `handoff_transfer` MCP tool with discriminated operations:
  - `operation="export"` — current `export_handoff_state(task_refs=..., include_archived=..., ...)` contract.
  - `operation="import"` — current `import_handoff_state(payload=..., strategy=..., ...)` contract.
- Preserve Python-level compatibility aliases (`export_handoff_state`, `import_handoff_state`) so existing callers remain unaffected.
- Update atomic with the rename:
  - `.github/hooks/terminal-guard.json` PostToolUse matchers (`mcp_altcontext-mc_export_handoff_state` → `mcp_altcontext-mc_handoff_transfer`, same for import).
  - `.claude/settings.json` PostToolUse hooks.
  - `.github/copilot-instructions.md` deferred-tool list.
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` — align CLI subcommand naming or document compatibility aliases.
  - `packages/agent-handoff-mcp/README.md` — update the command map.
  - `docs/agentic/contracts/agent-handoff-mcp.md` — update MCP tool surface documentation.
- Preserve the bounded-read envelope contract (`sections`, `detail`, `top_n_*`, `fields`) — no default response enlargement.

## Proof Criteria

- Compound-tool dispatch tests pass for both `operation="export"` and `operation="import"`.
- Python aliases still resolve.
- CLI help/README examples match the final renamed or aliased surface.
- Advertised tool count decreases by exactly one (two tools → one compound tool).
- Hook matchers reference only the new compound tool name; no stale references remain.
- Round-trip test: `handoff_transfer(operation="export", ...)` then `handoff_transfer(operation="import", payload=...)` reproduces the original task state verbatim, including archives and findings.

## Trigger to Revive

- Advertised tool count exceeds the VS Code/Copilot session projection threshold again, or
- A reproducible session-drop incident traced to the export/import pair, or
- A separate workflow requires unified transfer-pipeline semantics (e.g. cross-repo handoff mirroring).

Until then, this remains tech-debt.
