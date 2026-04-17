# Slice 4C: `task_archive` Compound Tool (Deferred from E17-7)

> **Metadata**
>
> - **Date**: 2026-04-17
> - **Project**: `agent-handoff-mcp`
> - **Status**: Tech-debt note — deferred follow-on to [E17-7 Slice 4](../../../../docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md#slice-4-mcp-tool-surface-compression)
> - **Supersedes**: E17-7 Slice 4C plan line (marked DEFERRED on `c9eff4dd`)
> - **Related tools**: `mcp__agent-handoff-mcp__archive_task_state`, `mcp__agent-handoff-mcp__get_archived_task`

## Problem

The MCP tool registry still advertises `archive_task_state` and `get_archived_task` as separate tools. Slice 4 of E17-7 originally planned to collapse them into a single compound `task_archive` tool dispatched by `operation="archive" | "get"` to reduce the advertised tool count and mitigate the session tool-drop risk documented in [review-runs-tool-bridge-gap-investigation](../../../../docs/assessments/review-runs-tool-bridge-gap-investigation-2026-04-16.md).

Only Slice 4A (`render_handoff`) shipped in E17-7. 4C was deferred because:

- Both tools are rarely-called lifecycle endpoints — `archive_task_state` fires once per task close, `get_archived_task` only on explicit lookup.
- 4A plus the existing bounded-read envelope already pushed the tool count below the session-drop threshold observed in the investigation.
- Compressing a write-once / read-rare pair yields diminishing token-budget returns relative to implementation + migration cost.

Revisit only if tool-count pressure reappears.

## Scope When Revived

- Introduce a single `task_archive` MCP tool with discriminated operations:
  - `operation="archive"` — current `archive_task_state(task_ref=..., ...)` contract.
  - `operation="get"` — current `get_archived_task(task_ref=..., ...)` contract.
- Preserve Python-level compatibility aliases (`archive_task_state`, `get_archived_task`) so existing callers remain unaffected.
- Update atomic with the rename:
  - `.github/hooks/terminal-guard.json` PostToolUse matchers (`mcp_altcontext-mc_archive_task_state` → `mcp_altcontext-mc_task_archive`, same for get).
  - `.claude/settings.json` PostToolUse hooks.
  - `.github/copilot-instructions.md` deferred-tool list.
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` — align CLI subcommand naming or document compatibility aliases.
  - `packages/agent-handoff-mcp/README.md` — update the command map.
  - `docs/agentic/contracts/agent-handoff-mcp.md` — update MCP tool surface documentation.
- Coordinate with `make task-finish` (which calls archive today) — CLI wrapper / Makefile should follow the rename atomically.
- Preserve the bounded-read envelope contract on the `get` operation.

## Proof Criteria

- Compound-tool dispatch tests pass for both `operation="archive"` and `operation="get"`.
- Python aliases still resolve.
- CLI help/README examples match the final renamed or aliased surface.
- Advertised tool count decreases by exactly one (two tools → one compound tool).
- Hook matchers reference only the new compound tool name; no stale references remain.
- `make task-finish TASK=<ref>` continues to archive the task and leaves `DASHBOARD.txt` current.
- `task_archive(operation="get", task_ref=<archived>)` returns the same snapshot shape that `get_archived_task` currently returns.

## Trigger to Revive

- Advertised tool count exceeds the VS Code/Copilot session projection threshold again, or
- A reproducible session-drop incident traced to the archive/get pair, or
- A parallel-review or multi-task coordinator needs to resurrect archived task snapshots at high frequency.

Until then, this remains tech-debt.
