# Task Plan

> **Metadata**
>
> - **Date**: 2026-03-30 21:15 EDT
> - **Author**: Claude Opus 4.6
> - **Owning Epic**: [docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md](../../../epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: E12
> - **Review Coverage Target**: 2

---

## E12-11. CURRENT_TASK.md Dashboard View

## Objective

Make `CURRENT_TASK.md` include a cross-task dashboard summary as its default header so that switching task context no longer destroys visibility into other active tasks.

## Problem Statement

`CURRENT_TASK.md` is a single-slot generated file. `switch_task` and `generate_current_task_md` overwrite it each time, replacing the previous task's rendered state. When multiple external agents (Codex, Claude Code, etc.) are working on different tasks concurrently, the file reflects only whichever task was touched last. Cold-starting agents lose at-a-glance context about what else is in flight, what has open findings, and what is blocked.

The MCP state layer has no data loss — `handoff.db` is durable and `get_handoff_state(view="dashboard")` already returns cross-task aggregation. The gap is purely in the rendered file surface: the dashboard data exists but is not included in the generated Markdown.

## Constraints

- `CURRENT_TASK.md` must remain a single generated file. No per-task file proliferation.
- The dashboard section must be rendered from the same DB queries that `get_handoff_state(view="dashboard")` already uses. No parallel state tracking.
- `rg-013` applies: `core.py` must remain pure handoff-state CRUD. Rendering logic stays in `current_task_rendering.py`.
- The active task's detail section must remain unchanged in structure. The dashboard is additive — prepended above the existing content.
- Archived tasks should appear in the dashboard only when `include_archived` is true (matching the existing dashboard view behavior).

## Workflow Principles

- Prefer reusing the existing dashboard query (`_get_handoff_dashboard_view`) over building a parallel aggregation.
- The dashboard section should be compact enough that the active task's detail is still visible without excessive scrolling.
- The active task row in the dashboard table should be visually marked so operators can identify it at a glance.

## Terminology

- **Dashboard section**: The new cross-task summary table prepended to `CURRENT_TASK.md`.
- **Detail section**: The existing per-task rendering (objective, focus, status, decisions, findings, etc.).
- **Active task**: The task currently occupying the `handoff_state` row (id=1) — the one whose detail section is rendered.

## Current State Analysis

_Note: Slice 1 of this task is already implemented. The analysis below reflects the post-implementation state._

- `_render_current_task_md` in `current_task_rendering.py` renders the active task's state and calls `_render_dashboard_section` when `dashboard_tasks` is present. It receives a `CurrentTaskRenderState` dict and returns a Markdown string.
- `_collect_dashboard_rows` in `current_task_rendering.py` owns the dashboard aggregation SQL CTE. `_get_handoff_dashboard_view` in `handoff_state.py` delegates to it. Dependency direction: `_collect_dashboard_rows` is the source; `_get_handoff_dashboard_view` calls it (inverted from the original plan's "reusing the CTE from `_get_handoff_dashboard_view`" description).
- `generate_current_task_md` in `api.py` already queries dashboard rows and includes them in the render state.
- `_write_current_task_md_for_task` in `current_task_rendering.py` is the internal write path used by `close_slice` and other compound tools. It already queries and passes dashboard data.
- The dashboard query is a single SQL CTE that completes in <10ms on the current DB size. Performance impact is negligible.

## Target Outcome

Every `CURRENT_TASK.md` regeneration — whether via `generate_current_task_md`, `close_slice`, `switch_task`, or `_write_current_task_md_for_task` — includes a compact dashboard table at the top showing all active tasks with their status, open findings, blockers, and last activity. The active task row is marked with `**bold**` or `->` prefix. The existing per-task detail section follows unchanged below a horizontal rule.

Example rendered output:

```markdown
# CURRENT_TASK

_DO NOT EDIT: generated from .task-state/handoff.db. Last generated: 2026-03-30 21:10 UTC_

## All Tasks

|     | Task     | Status      | Findings | Blockers | Actions | Last Activity |
| --- | -------- | ----------- | -------- | -------- | ------- | ------------- |
| ->  | E12-9    | in_progress | 0        | 0        | 0       | 20:50         |
|     | E12-10   | in_progress | 7 open   | 0        | 0       | 20:59         |
|     | **repo** | —           | 0        | 0        | 0       | 04:52         |

---

## Objective

Finish the physical separation between...
```

## Context Loading

- Rules: [docs/agentic/rules/development-workflow.md](../../../agentic/rules/development-workflow.md)
- Contracts: [docs/agentic/contracts/agent-handoff-mcp.md](../../../agentic/contracts/agent-handoff-mcp.md)
- Handoff/MCP state: `get_handoff_state(view="dashboard")` for data shape; E12-10 decisions for `current_task_rendering.py` extraction context
- External docs via `ctx7` only if: none needed

## Contract and Boundary Impact

| Boundary                        | Owner           | Current Contract                                                                               | Expected Change                                            | Compatibility Needed?                                                             | Verification                            |
| ------------------------------- | --------------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------- | --------------------------------------- |
| `CURRENT_TASK.md` format        | agentic-tooling | [docs/agentic/rules/development-workflow.md](../../../agentic/rules/development-workflow.md)   | Additive: dashboard table prepended above existing content | yes — existing parsers/consumers see the same detail section below the new header | handoff close check + manual inspection |
| `generate_current_task_md` tool | agentic-tooling | [docs/agentic/contracts/agent-handoff-mcp.md](../../../agentic/contracts/agent-handoff-mcp.md) | No signature change; output includes dashboard section     | yes — tool signature unchanged                                                    | pytest                                  |

## Proposed Solution

Add a `_render_dashboard_section` function to `current_task_rendering.py` that accepts the dashboard task list and the active task_ref, returns a list of Markdown lines containing the summary table. Call this function at the top of `_render_current_task_md` (or from the write paths that feed it) so the dashboard section is always included.

The dashboard data is fetched via a lightweight SQL query (reusing the CTE from `_get_handoff_dashboard_view` or calling it directly) in the write paths that already have a DB connection. The rendering function itself remains a pure function that takes data and returns strings.

## Files and Surfaces to Change

| Surface | File                                                                         | Change                                                                                                                                  |
| ------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py` | Add `_render_dashboard_section(tasks, active_task_ref)` function; add `DashboardTaskRow` TypedDict; call from `_render_current_task_md` |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py` | Update `_write_current_task_md_for_task` to query dashboard data and pass to renderer                                                   |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py` | Update `CurrentTaskRenderState` to include optional `dashboard_tasks` field                                                             |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`                    | Update `generate_current_task_md` to query dashboard data and include in state                                                          |
| docs    | `docs/agentic/contracts/agent-handoff-mcp.md`                                | Note that `CURRENT_TASK.md` now includes a dashboard header                                                                             |
| tests   | `packages/agent-handoff-mcp/tests/`                                          | Add test for dashboard section rendering; verify existing tests still pass                                                              |

## Related Files

| File                                                                | Note                                                                       |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py` | Contains `_get_handoff_dashboard_view` with the existing dashboard SQL CTE |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py`       | Re-exports rendering functions for backward compatibility                  |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`          | Re-exports `_render_current_task_md`; must not gain new logic per `rg-013` |
| `CURRENT_TASK.md`                                                   | The generated output file                                                  |

## Verification Strategy

- Deterministic tests:
  - `PYENV_VERSION=description-service pytest packages/agent-handoff-mcp/tests/ -x -q`
- Contract/fixture verification:
  - `_render_dashboard_section` returns valid Markdown table for 0, 1, and N tasks
  - Active task row is marked with `->` indicator
  - Archived tasks show `archived` in the status column
  - Dashboard section appears before the detail section in the rendered output
  - Existing `_render_current_task_md` output for the detail section is unchanged (diff only adds lines above)
- Runtime-parity checks:
  - `agent-handoff-mcp --workspace-root . doctor`
  - Generate `CURRENT_TASK.md` and verify dashboard section appears with real task data
- Manual verification:
  - Switch between two tasks; confirm both appear in the dashboard section each time

## Slice Delivery

### Slice 1: Dashboard Rendering

**Goal**: Add the dashboard section renderer and wire it into the existing render pipeline.

Changes:

- Add `DashboardTaskRow` TypedDict to `current_task_rendering.py` with fields: `task_ref`, `last_activity`, `open_blockers`, `pending_actions`, `open_findings`, `archived_at`.
- Add `_collect_dashboard_rows(conn) -> list[DashboardTaskRow]` that runs the dashboard aggregation query (extracted from or matching the CTE in `_get_handoff_dashboard_view`).
- Add `_render_dashboard_section(tasks: list[DashboardTaskRow], active_task_ref: str | None) -> list[str]` that returns Markdown lines for the summary table.
- Add optional `dashboard_tasks: NotRequired[list[DashboardTaskRow]]` field to `CurrentTaskRenderState`.
- Update `_render_current_task_md` to call `_render_dashboard_section` when `dashboard_tasks` is present, inserting the table between the header and the detail section.
- Update `_write_current_task_md_for_task` to call `_collect_dashboard_rows(conn)` and include results in the state dict.
- Update `generate_current_task_md` in `api.py` to query dashboard rows and include in state.

Proof:

- New unit test: `_render_dashboard_section` with 0, 1, 3 tasks produces valid Markdown.
- New unit test: active task row has `->` marker.
- New unit test: archived task shows `archived` status.
- Existing test suite passes unchanged (detail section output is identical).
- `generate_current_task_md` produces a file with the dashboard section visible at the top.

### Slice 2: Contract and Integration

**Goal**: Update docs and verify end-to-end behavior across all write paths.

Changes:

- Update `docs/agentic/contracts/agent-handoff-mcp.md` to note that `CURRENT_TASK.md` now includes a cross-task dashboard header.
- Update `docs/agentic/rules/development-workflow.md` to note the dashboard section exists and that `CURRENT_TASK.md` no longer loses cross-task context on switch.
- Verify `close_slice` (which calls `_write_current_task_md_for_task` internally) includes the dashboard section.
- Verify `switch_task` (on `agent-orchestrator-mcp`) triggers regeneration that includes the dashboard section.

Proof:

- Automated: `test_close_slice_writes_dashboard_header_on_success` proves `close_slice` regenerates `CURRENT_TASK.md` with the dashboard section.
- Automated: `test_switch_task_regenerates_current_task_with_dashboard` proves task switches preserve cross-task visibility in regenerated output.
- Contract doc accurately describes the new output format.

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the `current_task_rendering.py` module and understood the render pipeline.
- [x] Confirmed `_get_handoff_dashboard_view` SQL CTE shape matches the data needed for the table.
- [x] Confirmed `rg-013`: no new logic added to `core.py`.

### Checklist: Slice 1 Dashboard Rendering

- [x] `DashboardTaskRow` TypedDict defined.
- [x] `_collect_dashboard_rows(conn)` implemented using the dashboard CTE.
- [x] `_render_dashboard_section(tasks, active_task_ref)` renders a valid Markdown table.
- [x] `CurrentTaskRenderState` extended with optional `dashboard_tasks` field.
- [x] `_render_current_task_md` calls `_render_dashboard_section` when data is present.
- [x] `_write_current_task_md_for_task` queries and passes dashboard rows.
- [x] `generate_current_task_md` queries and passes dashboard rows.
- [x] Unit tests cover 0/1/N tasks, active marker, archived status.
- [x] Existing test suite passes unchanged.

### Checklist: Slice 2 Contract and Integration

- [x] Contract doc (`agent-handoff-mcp.md`) updated.
- [x] Workflow doc (`development-workflow.md`) updated.
- [x] `close_slice` write path produces dashboard section.
- [x] `switch_task` regeneration produces dashboard section.
- [ ] Handoff decision recorded with slice-complete template.

## Review Readiness

- [x] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [x] The detail section output is byte-identical to pre-change output (dashboard is purely additive).
- [ ] Handoff decision records the change, verification, and contract update.

## Success Criteria

- [x] Every `CURRENT_TASK.md` regeneration includes a cross-task dashboard table at the top.
- [x] The active task row is visually marked in the table.
- [x] Switching tasks preserves visibility of all other tasks in the dashboard section.
- [x] No new files are created; the dashboard renders inside the existing `CURRENT_TASK.md`.
- [ ] Existing tests, close checks, and contract expectations are unbroken.
