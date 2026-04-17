# Task Plan

> **Metadata**
>
> - **Date**: 2026-04-10 22:00 EST
> - **Author**: Claude Opus 4.6
> - **Project**: agent-handoff-mcp + agent-orchestrator-mcp
> - **Task ID**: AHMCP-23
> - **Target Branch**: `feature/ahmcp-23-observatory-dashboard`

---

## AHMCP-23. Observatory Dashboard Split

## Objective

Split CURRENT_TASK.json into two generated files: a slim agent-scoped task view and a human-scoped observatory dashboard.  Introduce a `DashboardExtension` callback protocol so the orchestrator can inject lane/worker health into the dashboard without creating an upward dependency from handoff-mcp.

## Problem Statement

CURRENT_TASK.json currently serves two audiences with conflicting needs:

1. **Agents** need focused context about their active task.  Cross-task findings, the All Tasks table, and deferred/wontfix findings from completed work are noise that costs ~1.2K tokens per cold-start read with no actionability benefit.
2. **Humans** need panoramic observability: what's broken everywhere, what's stale, who owns what.  The current rendering constrains this view to stay within agent context budgets, making it too sparse for real oversight.

Handoff.db analysis (2026-04-10) confirmed:
- 6 open + 2 wontfix findings across 4 non-active tasks rendered into every CURRENT_TASK.json
- The "All Tasks" table renders 20 rows regardless of which task is active
- No "needs attention" aggregation — the human must scan each row to find what's broken

## Constraints

- **Dependency direction is sacred**: handoff-mcp MUST NOT import from orchestrator-mcp.  The extension pattern must be callback-based (handoff defines the protocol, orchestrator registers an implementation).
- **Data collection functions are shared**: `_collect_dashboard_rows`, `_collect_all_open_findings`, `_collect_all_deferred_findings` already exist in `current_task_rendering.py` and should be reused, not duplicated.
- **Greenfield policy applies**: No backward-compatibility shims for the old combined format.  CURRENT_TASK.json changes shape; consumers adapt.
- **Both files are generated from the same DB**: `.task-state/handoff.db` remains the single source of truth.

## Workflow Principles

- Single contract owner: handoff-mcp owns the data, the rendering protocol, and CURRENT_TASK.json.  The orchestrator is a dashboard extension provider, not a co-owner.
- No speculative abstraction: the extension protocol supports exactly the use case we have (orchestrator adds sections).  No plugin registry, no versioned APIs.  Extensions use an `order` int for section placement relative to other extensions; core sections are fixed and always render first.
- Delete over flag: the cross-task findings and All Tasks table are removed from CURRENT_TASK.json, not hidden behind a parameter.
- CLI graceful degradation: `make dashboard` loads only handoff-mcp and renders core sections (Needs Attention, All Tasks, Findings).  Extension sections (Lane Health, Worker Status) appear only when orchestrator-mcp is loaded and has registered its callback.  The CLI path must not import orchestrator-mcp.

## Terminology

- **CURRENT_TASK.json**: Agent-scoped generated file.  Contains only active-task data after this change.
- **DASHBOARD.md**: Human-scoped generated file.  Contains the All Tasks table, cross-task findings, needs-attention summary, and orchestrator extension sections.
- **DashboardExtension**: A callable that receives a `DashboardContext` TypedDict (pre-queried data) and returns a list of `DashboardSection` dicts.  Defined in handoff-mcp, implemented in orchestrator-mcp.
- **DashboardContext**: A TypedDict passed to extensions containing pre-queried data they need (lane rows, worker report rows, turn metric rows), so extensions never touch the DB directly.
- **Needs Attention**: A computed section that aggregates tasks with open high/medium findings, blocked status, or stale activity.

## Current State Analysis

- `current_task_rendering.py` (762 lines) handles all rendering in one module.  Data collection (`_collect_*`) and rendering (`_render_*`) are cleanly separated within the module.
- `_render_current_task_md()` builds one monolithic markdown string with dashboard table, active-task detail, cross-task findings, and token summary.
- `_build_current_task_render_state()` assembles a `CurrentTaskRenderState` TypedDict that includes `dashboard_tasks`, `related_findings_open`, and `related_findings_deferred` as `NotRequired` fields — these are the cross-task fields to move to the dashboard.
- Orchestrator-mcp already has `dashboard_live.py` and `dashboard_tui.py` for lane-specific polling dashboards.  These use a different data path (subprocess MCP calls) and render lane health, not task/finding health.  The new dashboard is complementary, not a replacement.
- `api.py` exposes `generate_current_task_md()` as an MCP tool; orchestrator re-exports it.  The same pattern applies to the new `generate_dashboard_md()`.

## Target Outcome

After this task:

1. `CURRENT_TASK.json` contains only active-task data: objective, focus, status, blockers, actions, decisions, tests, findings for THIS task, lanes, coverage.  No All Tasks table.  No cross-task findings.  ~40-60% smaller for typical tasks.
2. `DASHBOARD.md` contains the human observatory: Needs Attention summary, All Tasks table, cross-task open findings grouped by task, deferred/wontfix findings, and any registered extension sections.
3. `generate_dashboard_md()` is exposed as an MCP tool in both handoff-mcp and orchestrator-mcp.
4. Orchestrator-mcp registers a `DashboardExtension` callback that adds lane health and worker status sections when the orchestrator is active.
5. `make dashboard` generates DASHBOARD.md from the repo root.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md` (session state with MCP Handoff, pre-merge gate)
- Contracts: `docs/agentic/contracts/agent-handoff-mcp.md`
- Source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py`
- Source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`
- Source: `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py`
- Handoff/MCP state: AHMCP-23 task ref, open findings from all tasks

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `generate_current_task_md` MCP tool | handoff-mcp | `contracts/agent-handoff-mcp.md` | Output shape changes (removes cross-task sections) | No (greenfield) | Existing tests updated |
| `generate_dashboard_md` MCP tool | handoff-mcp | `contracts/agent-handoff-mcp.md` | New tool added | N/A | New tests |
| `DashboardExtension` protocol | handoff-mcp | New (defined in this task) | New protocol | N/A | New tests |
| Orchestrator re-export | orchestrator-mcp | `api.py` | Re-exports `generate_dashboard_md` | N/A | Integration test |

## Proposed Solution

### Architecture

```
agent-handoff-mcp (owns protocol + core rendering)
├── dashboard_rendering.py        # NEW: DashboardExtension protocol + render
├── current_task_rendering.py     # MODIFIED: remove cross-task sections
└── api.py                        # MODIFIED: expose generate_dashboard_md

agent-orchestrator-mcp (provides extension)
├── orchestration/
│   └── dashboard_extension.py    # NEW: lane/worker sections for dashboard
└── api.py                        # MODIFIED: register extension + re-export
```

### Extension Protocol

```python
# In handoff-mcp: dashboard_rendering.py

class DashboardContext(TypedDict):
    """Pre-queried data passed to extensions so they never touch the DB."""
    worktree_lanes: list[dict]       # from worktree_lanes table
    worker_reports: list[dict]       # from worker_reports table
    turn_metrics: list[dict]         # from turn_metrics table (last 20)

class DashboardSection(TypedDict):
    heading: str       # e.g. "Lane Health"
    content: str       # Pre-rendered ASCII/markdown content
    order: int         # Lower = higher among extension sections.
                       # Core sections are always rendered first regardless.

DashboardExtension = Callable[[DashboardContext], list[DashboardSection]]

_extensions: list[DashboardExtension] = []

def register_dashboard_extension(ext: DashboardExtension) -> None:
    _extensions.append(ext)

def clear_dashboard_extensions() -> None:
    """Reset the extension registry.  Use in test fixtures to prevent leakage."""
    _extensions.clear()
```

Handoff-mcp defines the protocol.  Orchestrator-mcp calls `register_dashboard_extension()` at import time — one explicit registration, no discovery.  `clear_dashboard_extensions()` is exported for test teardown (same pattern as `reset_runtime_config()` in `runtime.py`).

### Dashboard Layout

```
# DASHBOARD
_Generated from .task-state/handoff.db_

## Needs Attention                          # order 0
  ⚠ AOMCP-4      1 open (medium)
  ⚠ LANE-ORCH    4 open (low)
  ○ 3 stale worktrees

## All Tasks                                # order 10
  [ASCII table — moved from CURRENT_TASK.json]

## Open Findings                            # order 20
  [Grouped by task_ref, severity-ordered]

## Deferred / Won't Fix                     # order 30
  [Grouped by task_ref]

## Lane Health                              # order 50 (from extension)
  [Only present when orchestrator registered]

## Worker Status                            # order 60 (from extension)
  [Only present when orchestrator registered]
```

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| Rendering (new) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/dashboard_rendering.py` | New module: extension protocol, needs-attention query, dashboard render |
| Rendering (modify) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py` | Remove cross-task sections from `_render_current_task_md`, remove `related_findings_*` from state assembly, make `_collect_dashboard_rows` / `_collect_all_open_findings` / `_collect_all_deferred_findings` public |
| API (modify) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Add `generate_dashboard_md` tool |
| Public surface | `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` | Export `generate_dashboard_md`, `register_dashboard_extension`, `DashboardSection`, `DashboardExtension` |
| Extension (new) | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_extension.py` | Lane health + worker status sections |
| Orchestrator API | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` | Re-export `generate_dashboard_md`, register extension |
| Contract | `docs/agentic/contracts/agent-handoff-mcp.md` | Document new tool + extension protocol |
| Makefile | `Makefile` (root) | Add `make dashboard` target |
| Tests | `packages/agent-handoff-mcp/tests/test_dashboard_rendering.py` | New: dashboard rendering, extension registration, needs-attention logic |
| Tests | `packages/agent-handoff-mcp/tests/test_current_task_rendering.py` | Update: verify cross-task sections are gone |

## Related Files

| File | Note |
|---|---|
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_live.py` | Existing lane polling dashboard — complementary, not replaced |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/ace_metrics.py` | Metrics snapshot — may feed future dashboard extension |
| `docs/agentic/rules/development-workflow.md` | References CURRENT_TASK.json in Session State section — update references |

## Verification Strategy

- Deterministic tests:
  - `cd packages/agent-handoff-mcp && make test-handoff`
  - `cd packages/agent-orchestrator-mcp && make test-orchestrator`
- Contract verification:
  - `generate_current_task_md()` output contains NO `## All Tasks` heading
  - `generate_current_task_md()` output contains NO `## Open Review Findings` for non-active tasks
  - `generate_dashboard_md()` output contains `## Needs Attention`, `## All Tasks`, `## Open Findings`
  - Extension sections appear only when registered
- Runtime-parity:
  - `make dashboard` produces a valid `DASHBOARD.md` from the live DB
  - `generate_current_task_md` via MCP produces a slimmer output than before

## Slice Delivery

### Slice 1: Dashboard rendering module + extension protocol

**Goal**: Create `dashboard_rendering.py` with the extension protocol, needs-attention query, and full dashboard render function.

Changes:
- New `dashboard_rendering.py` in handoff-mcp with `DashboardSection`, `DashboardExtension`, `register_dashboard_extension()`, `generate_dashboard_md()`
- Needs-attention logic: open findings aggregated by task with severity counts, blocked tasks, stale tasks (no activity in >24h from `_collect_dashboard_rows` timestamps)
- Reuse `_collect_dashboard_rows`, `_collect_all_open_findings`, `_collect_all_deferred_findings` from `current_task_rendering.py` — promote to public by renaming without `_` prefix or adding public wrapper functions
- New `test_dashboard_rendering.py` covering: render with no data, render with findings, render with extension, needs-attention aggregation

Proof:
- `cd packages/agent-handoff-mcp && make test-handoff` — new tests pass
- `DASHBOARD.md` generated from test fixtures contains expected sections

### Slice 2: Slim CURRENT_TASK.json

**Goal**: Remove cross-task data from CURRENT_TASK.json rendering.

Changes:
- Modify `_build_current_task_render_state()` to stop collecting `related_findings_open`, `related_findings_deferred`, and `dashboard_tasks`
- Modify `_render_current_task_md()` to stop rendering the dashboard table and cross-task finding sections
- Remove `_render_dashboard_section` from current_task_rendering (moved to dashboard_rendering in Slice 1)
- Update existing tests that assert on cross-task content in CURRENT_TASK.json

Proof:
- `cd packages/agent-handoff-mcp && make test-handoff` — updated tests pass
- `generate_current_task_md()` output is measurably smaller (assert line count or char count is below threshold)

### Slice 3: MCP tool + orchestrator integration

**Goal**: Expose `generate_dashboard_md` as an MCP tool, wire orchestrator extension, add `make dashboard`.

Changes:
- Add `generate_dashboard_md` tool to handoff-mcp `api.py` and `__init__.py`
- Create `orchestration/dashboard_extension.py` in orchestrator-mcp with lane health and worker status sections
- Register extension in orchestrator-mcp `api.py` startup path
- Re-export `generate_dashboard_md` from orchestrator-mcp `api.py`
- Add `make dashboard` target to root Makefile
- Update `docs/agentic/contracts/agent-handoff-mcp.md` with new tool + protocol

Proof:
- `cd packages/agent-orchestrator-mcp && make test-orchestrator` — new integration test passes
- `make dashboard` produces valid DASHBOARD.md with core sections only (no orchestrator imported)
- Extension sections appear in output when `register_dashboard_extension` has been called (test with explicit registration before calling `generate_dashboard_md`)
- `make dashboard` output contains NO import of `agent_orchestrator_mcp`

---

## Consolidated Checklist

### Context and Ownership

- [x] Loaded current_task_rendering.py, api.py, and orchestrator api.py before editing
- [x] Confirmed extension protocol does not create upward dependency
- [x] Recorded boundary ownership in Contract and Boundary Impact table

### Checklist for Slice 1: Dashboard rendering module + extension protocol

- [x] `dashboard_rendering.py` created with DashboardSection, DashboardExtension types
- [x] `register_dashboard_extension()` and `generate_dashboard_md()` implemented
- [x] Needs-attention logic aggregates open findings by severity, blocked tasks, stale tasks
- [x] Data collection functions promoted to public API (or wrapped)
- [x] `test_dashboard_rendering.py` covers render, extension, needs-attention
- [x] Verification: `make test-handoff` passes

### Checklist for Slice 2: Slim CURRENT_TASK.json

- [x] `_build_current_task_render_state()` stops collecting cross-task data
- [x] `_render_current_task_md()` stops rendering All Tasks table and cross-task findings
- [x] Dashboard-specific render helpers moved to dashboard_rendering.py
- [x] Existing tests updated for new CURRENT_TASK.json shape
- [x] Verification: `make test-handoff` passes, output is measurably smaller

### Checklist for Slice 3: MCP tool + orchestrator integration

- [x] `generate_dashboard_md` exposed as MCP tool in handoff-mcp
- [x] `dashboard_extension.py` created in orchestrator with lane/worker sections
- [x] Extension registered at orchestrator startup
- [x] Re-exported from orchestrator api.py
- [x] `make dashboard` target added to root Makefile
- [x] Contract doc updated
- [x] Verification: `make test-handoff`, `make test-orchestrator`, `make dashboard` all pass

### Review Readiness

- [x] No boundary-touching implementation left without matching contract/doc/fixture evidence
- [x] Extension protocol tested with and without registered extensions
- [x] Handoff decision records the change, verification, and contract implications

## Stretch Goals

- [ ] `make context` auto-regenerates DASHBOARD.md alongside CURRENT_TASK.json on session start
- [ ] Dashboard includes a "Stale Tasks" section (no activity in >48h) with recommended actions
- [ ] Dashboard includes task ownership derived from `actor.agent_id` on most recent decisions

## Success Criteria

- [x] `CURRENT_TASK.json` contains zero cross-task findings and no All Tasks table
- [x] `DASHBOARD.md` contains Needs Attention, All Tasks, Open Findings, Deferred/Won't Fix sections
- [x] Orchestrator extension sections (Lane Health, Worker Status) appear in DASHBOARD.md when orchestrator is loaded
- [x] `generate_dashboard_md()` is callable as an MCP tool from both servers
- [x] No import from `agent_orchestrator_mcp` exists anywhere in `agent_handoff_mcp`
