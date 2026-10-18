# E12-10. `_shared.py` Module Extraction

> **Metadata**
>
> - **Date**: 2026-03-30
> - **Author**: GitHub Copilot (GPT-5.4); superseding earlier draft by Claude Opus 4.6
> - **Owning Epic**: [docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md](../../../epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: E12
> - **Review Coverage Target**: 2

---

## Status

This plan is no longer the active execution document.

The `_shared.py` refactor has already materially landed in the codebase, and the remaining open work is package-boundary cleanup that belongs to [docs/tasks/12.0/12.1/E12-9-orchestration-physical-separation-task-plan.md](../12.1/E12-9-orchestration-physical-separation-task-plan.md).

Treat E12-10 as historical context only. Use E12-9 as the single active plan for the remaining work.

## Why Consolidation Makes Sense

The original E12-10 draft assumed `_shared.py` extraction had not started yet. That assumption is now stale.

The following focused modules already exist in `packages/agent-handoff-mcp/src/agent_handoff_mcp/`:

- `current_task_rendering.py`
- `shared_write_context.py`
- `shared_schema.py`
- `shared_db_utils.py`
- `shared_archival.py`
- `shared_tool_adapters.py`

`agent_handoff_mcp._shared` now re-exports those extracted surfaces for compatibility. The remaining work is not first-time extraction; it is finishing the package boundary so `agent-orchestrator-mcp` stops depending on handoff-owned compatibility surfaces where ownership is now wrong.

## Landed State

- The extraction clusters described by the original E12-10 plan are already present in dedicated modules.
- `_shared.py` remains a compatibility layer and still contains shared constants and helpers alongside those re-exports.
- `agent-orchestrator-mcp/lanes.py` still imports from `agent_handoff_mcp._shared`; that is the live follow-on work.
- `agent-orchestrator-mcp/api.py` still has script-path indirection and other handoff-internal imports; that also belongs to E12-9.

## Remaining Work After Consolidation

The remaining actionable items are now all boundary-cleanup items and are tracked in E12-9:

- Remove `_scripts_mcp_dir()` and `_import_scripts_mcp_module()` from `agent-orchestrator-mcp/api.py`.
- Move orchestrator imports off `agent_handoff_mcp._shared` re-exports and onto focused modules or an explicit shared seam.
- Re-home orchestration-owned bootstrap or DDL concerns that still sit on the handoff side.
- Complete orchestrator CLI ownership, final verification, and contract updates.

## Disposition

- Use [docs/tasks/12.0/12.1/E12-9-orchestration-physical-separation-task-plan.md](../12.1/E12-9-orchestration-physical-separation-task-plan.md) for all future execution.
- Keep this document only as historical context showing the intended decomposition direction.
- Keep [docs/tasks/tech-debt/agent-handoff-mcp-shared-module-refactoring-evaluation.md](../../tech-debt/agent-handoff-mcp-shared-module-refactoring-evaluation.md) as supporting analysis if further `_shared.py` slimming is needed after E12-9 closes.

## Historical Note

The original E12-10 slice breakdown was useful when `_shared.py` was still a single extraction target. Now that the refactor has already happened, keeping a second active task plan would duplicate state and compete with E12-9 for ownership of the same remaining work.

Consolidation removes that duplication and leaves a single source of truth.
