# Task Plan

> **Metadata**
>
> - **Date**: 2026-03-30
> - **Author**: Claude Opus 4.6
> - **Owning Epic**: [docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md](../../../epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: E12
> - **Review Coverage Target**: 2

---

# E12-10. `_shared.py` Module Extraction

## Objective

Decompose `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py` (2053 lines, 85 definitions) into focused domain modules while keeping `_shared.py` as a required re-export layer. Each extraction slice is independently verifiable against the existing test suite with no behavior changes.

## Problem Statement

Following E12-6 (`core.py` decomposition), `_shared.py` is the package's remaining god-module. It accumulates seven independent responsibility clusters: schema/bootstrap/migration, generic DB helpers, normalization/decoding, git/write-actor resolution, archival summary composition, tool invocation adaptation, and snapshot/rendering. Multiple unrelated change streams (schema additions, rendering changes, git-context changes, tool-wrapper compatibility fixes) all land in this one file, creating high merge-conflict risk, broad diff noise on every change, and difficult regression isolation.

Detailed smell analysis: `docs/tasks/tech-debt/agent-handoff-mcp-shared-module-refactoring-evaluation.md`.

## Constraints

- E12-9 (orchestration physical separation) must be closed before this task begins. Some responsibility clusters in `_shared.py` (write-context, tool invocation) may move to `agent-orchestrator-mcp` during E12-9; extraction targets must be confirmed against the post-E12-9 file state before any slice starts.
- `_shared.py` re-exports are a **hard requirement**, not optional. `agent-orchestrator-mcp/lanes.py` imports directly from `agent_handoff_mcp._shared` (confirmed post-E12-9: `lanes.py` was moved to `agent-orchestrator-mcp` but its imports remain cross-package). Re-exports must remain until a follow-on task migrates the cross-package import. This is a temporary constraint scoped to the current `agent_handoff_mcp._shared` surface; it does not make `_shared.py` an externally-owned module.
- All existing tests must pass after every slice. No test can be deleted or skipped to make an extraction easier. The baseline is 151+ tests across the agent-handoff-mcp suite.
- Slices are behavior-preserving. No functional changes within a slice. Logic that exists in `_shared.py` must behave identically after relocation.
- Deprecated alias callables must remain importable from their current import paths.

## Workflow Principles

- Each slice produces code plus import-parity proof. No file-move-only slices without a test run confirming all tests pass.
- Move code, don't copy. After each move, the source location re-exports the symbol; it does not duplicate the implementation.
- Extract the most isolated cluster first. Start with rendering (lowest coupling to other clusters); defer clusters that interlock with bootstrap or cross-package consumers.
- Confirm E12-9 diff on `_shared.py` before starting Step 2 or Step 3 to avoid invalidated extraction targets.

## Terminology

- **Extraction**: Moving a responsibility cluster from `_shared.py` into a new focused module, with `_shared.py` re-exporting all moved symbols.
- **Re-export layer**: A module that imports from the new home and re-exposes the same names so existing consumers do not need updates.
- **Proof of completion**: A combination of test-pass count and specific test names that must pass for a slice to be considered done.

## Current State Analysis

- `_shared.py`: 2053 lines, 85 top-level defs/classes/protocols (confirmed 2026-03-30).
- Seven responsibility clusters identified; see evaluation doc sections H1-H4, M1-M4.
- Six existing TypedDicts/dataclasses at lines 108-156: `WriteActor`, `ResolvedWriteContext`, `TokenUsage`, `PromptMetrics`, `ReviewFindingDetails`, `LaneMessagePayload`.
- Two long functions (>89 lines each): `_apply_handoff_migrations()` (lines 773-883) and `_render_current_task_md()` (lines 1965-2053).
- Monkeypatch fallback pattern repeated in at least three helpers without a shared extractor.
- E12-9 is currently active; this task cannot start until E12-9 closes.

## Target Outcome

Seven modules replace the monolithic `_shared.py`:

| New Module | Responsibility Cluster |
| --- | --- |
| `current_task_rendering.py` | Snapshot state types, markdown rendering, findings/coverage assembly |
| `shared_write_context.py` | Actor normalization, git context, commit relation classification |
| `shared_schema.py` | DDL SQL strings, migrations, FTS setup, DB connection bootstrap |
| `shared_db_utils.py` | Generic row/count/pagination helpers |
| `shared_archival.py` | `ArchivalSummaryBuilder`, archival count helpers |
| `shared_tool_adapters.py` | `_resolve_awaitable()`, `_invoke_tool()`, wrapper protocols |
| `_shared.py` | Required re-export layer only; all names remain importable here |

`_shared.py` length drops from ~2053 lines to a thin re-export stub. All existing import paths remain valid.

## Context Loading

- Evaluation (primary): `docs/tasks/tech-debt/agent-handoff-mcp-shared-module-refactoring-evaluation.md`
- Rules: `docs/agentic/instructions.md` (rg-013, rg-014)
- Prior work: E12-6 (`docs/tasks/12.0/12.1/E12-6-agent-handoff-mcp-internal-refactoring-task-plan.md`) — core.py decomposition pattern
- Prior work: E12-9 (`docs/tasks/12.0/12.1/E12-9-orchestration-physical-separation-task-plan.md`) — must close first
- Gate check: after E12-9 closes, run `git diff <pre-E12-9-sha> HEAD -- packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py` to confirm which sections were modified before starting any slice

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `agent_handoff_mcp._shared` (in-package) | agent-handoff-mcp | All domain modules import from `_shared` | Re-exports remain; actual defs move to focused modules | Yes; `_shared.py` re-export layer is required | All tests pass; no import errors |
| `agent_handoff_mcp._shared` (cross-package) | agent-handoff-mcp (owned here; consumed by orchestrator) | `agent-orchestrator-mcp/lanes.py` imports from `agent_handoff_mcp._shared` line 11 (E12-9 moved `lanes.py` physically but did not migrate its import) | Re-exports preserved for the duration of this task; cross-package import migration is a follow-on task. Constraint is temporary — expires when `lanes.py` is updated to import from its correct focused module. | Yes; temporary hard requirement | `lanes.py` import still resolves after each slice |

## Proposed Solution

Staged extraction in seven slices ordered by increasing coupling complexity. Each slice moves one cluster, adds `_shared.py` re-exports for all moved symbols, and verifies the full test suite passes before closing. Slices are **behavior-preserving extraction plus localized refactoring**: the primary operation is physical relocation, but Slices 1, 3, and 4 include targeted helper decomposition (Extract Function on overlong functions) and typed-container introduction. These are defined refactors with explicit test coverage; the proof section for each affected slice reflects the elevated verification burden.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| New module (Slice 1) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py` | Create; receive rendering cluster |
| New module (Slice 2) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_write_context.py` | Create; receive write-context cluster |
| New module (Slice 3) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py` | Create; receive schema/bootstrap cluster (ledger-owned DDL only) |
| New module (Slice 4) | `_shared.py` only | Introduce typed containers for snapshot/render state |
| New module (Slice 5) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_tool_adapters.py` | Create; receive tool invocation cluster |
| New module (Slice 6) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_db_utils.py` | Create; receive generic row/count/pagination helpers |
| New module (Slice 7) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_archival.py` | Create; receive `ArchivalSummaryBuilder` and archival count helpers |
| Re-export layer | `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py` | Progressively reduced to re-exports only |
| Tests | `packages/agent-handoff-mcp/tests/` | No behavioral changes; confirm test file imports still resolve after each slice |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Imports many symbols from `_shared`; must remain unmodified per slice contract |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py` | Direct `_shared` consumer |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py` | Direct `_shared` consumer |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/import_export.py` | Direct `_shared` consumer |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py` | Direct `_shared` consumer |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py` | Cross-package consumer; import must remain valid throughout |

## Verification Strategy

- Deterministic tests (after every slice):
  - `cd packages/agent-handoff-mcp && pyenv exec python -m pytest tests/ -q 2>&1 | tee /tmp/pytest_e1210_slice<N>.txt`
  - Baseline: 151+ tests, 0 failures, 0 import errors
- Import-parity check (after every slice):
  - `pyenv exec python -c "from agent_handoff_mcp._shared import *"` — must succeed with no ImportError
  - `pyenv exec python -c "from agent_orchestrator_mcp.lanes import *"` — must succeed with no ImportError
- Long-function extraction (Slice 1):
  - `test_handoff_state.py` and `test_review_findings.py` pass unchanged
  - `test_internal_write_path_includes_task_ref` and `test_internal_write_path_includes_review_coverage` pass unchanged

## Slice Delivery

### Slice 1: Extract rendering cluster into `current_task_rendering.py`

**Goal**: Move the snapshot collection, render-state construction, and `CURRENT_TASK.md` markdown rendering path from `_shared.py` into a new `current_task_rendering.py` module.

**Pre-condition**: E12-9 is closed; rendering section of `_shared.py` is confirmed unmodified by E12-9.

Changes:

- Create `current_task_rendering.py` containing: `_collect_task_snapshot()`, `_build_current_task_state_from_snapshot()`, `_write_current_task_md_for_task()`, `_render_current_task_md()`, and all rendering sub-helpers (`_render_lanes_section()`, `_render_findings_section()`, `_render_coverage_section()`, etc.).
- Apply `Extract Function` and `Split Phase` to `_render_current_task_md()` per H4 recommendation: extract `_build_current_task_header()`, `_render_latest_decision_section()`, `_render_core_sections()`, `_render_non_active_note()` as private helpers within the new module.
- Add `_shared.py` re-exports for all moved symbols.

Proof:

- 151+ tests pass; `test_handoff_state.py` and `test_review_findings.py` pass without modification.
- `test_internal_write_path_includes_task_ref` and `test_internal_write_path_includes_review_coverage` pass.
- `_shared.py` wildcard import resolves without error.
- `_render_current_task_md()` importable from both `current_task_rendering` and `_shared`.

### Slice 2: Extract write-context cluster into `shared_write_context.py`

**Goal**: Move git/actor resolution helpers from `_shared.py` into `shared_write_context.py` and eliminate the repeated monkeypatch fallback pattern.

**Pre-condition**: Confirm after E12-9 that `build_write_actor()`, `_detect_git_write_context()`, `_workspace_git_context()`, `_resolve_write_actor()` remain in `agent-handoff-mcp` (E12-9 may relocate them).

Changes:

- Create `shared_write_context.py` containing: `WriteActor`, `ResolvedWriteContext`, `build_write_actor()`, `_detect_git_write_context()`, `_workspace_git_context()`, `_resolve_write_actor()`.
- Extract `_resolve_core_override(name, fallback)` helper per M1 recommendation; replace the three repeated monkeypatch fallback blocks with calls to it.
- Add `_shared.py` re-exports for all moved symbols.

Proof:

- 151+ tests pass; write-actor and git-context tests in `test_handoff_state.py` pass unchanged.
- `_shared.py` wildcard import resolves without error.
- `WriteActor` importable from both `shared_write_context` and `_shared`.

### Slice 3: Extract schema/bootstrap cluster into `shared_schema.py`

**Goal**: Move DDL SQL strings, migration helpers, FTS bootstrap, and DB connection bootstrap from `_shared.py` into `shared_schema.py`, scoped to ledger-owned tables only.

**Pre-condition**: Before starting this slice, audit `HANDOFF_SCHEMA_SQL` in the current `_shared.py` to confirm which DDL tables are ledger-owned (managed by `agent-handoff-mcp` core) vs. orchestration-owned. Post-E12-9 expected state:

- **Ledger-owned tables** (move into `shared_schema.py`): `handoff_state`, `decisions`, `blockers`, `next_actions`, `review_findings`, `review_runs`, `test_results`, `artifacts`, `handoff_snapshots` — and any FTS virtual tables derived from these.
- **Orchestration-owned tables** (`worktree_lanes`, `lane_messages`, `worker_reports`, `plan_cursors`, `turn_metrics`): if these still appear in `HANDOFF_SCHEMA_SQL` at the time Slice 3 begins (i.e., E12-9 did not remove them), they remain in `shared_schema.py` with a `# TODO(E12-9-followon): move to agent-orchestrator-mcp bootstrap` comment, and their extraction is deferred to the E12-9 follow-on import-migration task. They must NOT be silently dropped.

Changes:

- Create `shared_schema.py` containing: `HANDOFF_SCHEMA_SQL`, `HANDOFF_FTS_SCHEMA_SQL`, `_HANDOFF_FTS_TRIGGERS_SQL`, `_backfill_handoff_fts()`, `_ensure_handoff_fts()`, `_apply_handoff_migrations()`, `_get_db_connection()`.
- Apply `Extract Function` to `_apply_handoff_migrations()` per H4 recommendation: extract `_ensure_legacy_columns()`, `_backfill_review_findings_metadata()`, `_ensure_turn_metrics_schema()`, `_ensure_turn_metrics_indexes()` as private helpers within the new module.
- Add `_shared.py` re-exports for all moved symbols.

Proof:

- 151+ tests pass; DB initialization and migration paths produce identical behavior.
- Both MCP servers start cleanly using the relocated bootstrap module.
- `_shared.py` wildcard import resolves without error.

### Slice 4: Introduce typed containers for snapshot and render state

**Goal**: Replace the raw `dict` plumbing in the snapshot/rendering pipeline with typed `@dataclass` containers (`TaskSnapshot`, `CurrentTaskRenderState`, `ReviewCoverageSummary`).

**Pre-condition**: Slice 1 (rendering extraction) must be complete; containers are defined in `current_task_rendering.py`.

Changes:

- Define `TaskSnapshot`, `CurrentTaskRenderState`, `ReviewCoverageSummary` as `@dataclass` or `TypedDict` with explicit fields and factory constructors from rows/dicts, in `current_task_rendering.py`.
- Update `_collect_task_snapshot()`, `_build_current_task_state_from_snapshot()`, and `_write_current_task_md_for_task()` to produce and consume the typed containers instead of raw dicts.
- Add `_shared.py` re-exports for the three new container types.

Proof:

- 151+ tests pass; no `dict`-key regressions in current-task write path.
- `test_internal_write_path_includes_task_ref` and `test_internal_write_path_includes_review_coverage` pass unchanged.
- `TaskSnapshot` importable from both `current_task_rendering` and `_shared`.

### Slice 5: Isolate tool invocation adapters into `shared_tool_adapters.py`

**Goal**: Move the generic tool invocation trampoline block from `_shared.py` into `shared_tool_adapters.py`.

**Pre-condition**: E12-9 is closed; confirm `_invoke_tool()` and related wrappers remain in `agent-handoff-mcp`.

Changes:

- Create `shared_tool_adapters.py` containing: `_resolve_awaitable()`, `_normalize_tool_result()`, `_unwrap_tool_candidate()`, `_invoke_tool()`, and associated Protocol definitions.
- Add `_shared.py` re-exports for all moved symbols.

Proof:

- 151+ tests pass.
- `_invoke_tool()` importable from both `shared_tool_adapters` and `_shared`.
- `_shared.py` wildcard import resolves without error.

### Slice 6: Extract DB utilities into `shared_db_utils.py`

**Goal**: Move the generic row/count/pagination helpers from `_shared.py` into `shared_db_utils.py`.

**Pre-condition**: Slices 1–5 complete.

Changes:

- Create `shared_db_utils.py` containing: `_fetch_handoff_rows()`, `_paginated_query()`, `_count_task_rows()`, `_resolve_output_path()`, and any narrowly-scoped row-decoding helpers that are purely generic (not domain-specific to rendering, write-context, or schema).
- Add `_shared.py` re-exports for all moved symbols.

Proof:

- 151+ tests pass.
- `_fetch_handoff_rows()` importable from both `shared_db_utils` and `_shared`.
- `_shared.py` wildcard import resolves without error.

### Slice 7: Extract archival cluster into `shared_archival.py`

**Goal**: Move `ArchivalSummaryBuilder` and archival count helpers from `_shared.py` into `shared_archival.py`.

**Pre-condition**: Slices 1–6 complete.

Changes:

- Create `shared_archival.py` containing: `ArchivalSummaryBuilder` class and all `_build_archival_*` helpers.
- Add `_shared.py` re-exports for all moved symbols.

Proof:

- 151+ tests pass.
- `ArchivalSummaryBuilder` importable from both `shared_archival` and `_shared`.
- `_shared.py` now contains only re-export statements; line count is below 150 lines.
- `_shared.py` wildcard import resolves without error.

---

## Consolidated Checklist

## Context and Ownership

- [ ] E12-9 is confirmed closed before starting any slice.
- [ ] Post-E12-9 diff on `_shared.py` reviewed to confirm extraction targets are unmodified.
- [ ] Cross-package import constraint (`agent-orchestrator-mcp/lanes.py`) verified to be preserved after each slice.

## Slice 1: Extract rendering cluster

- [ ] `current_task_rendering.py` created with all rendering defs.
- [ ] `_render_current_task_md()` decomposed into named sub-functions within new module.
- [ ] `_shared.py` re-exports all moved symbols.
- [ ] 151+ tests pass; targeted tests pass unchanged.

## Slice 2: Extract write-context cluster

- [ ] E12-9 post-close check confirms write-context cluster stays in `agent-handoff-mcp`.
- [ ] `shared_write_context.py` created.
- [ ] `_resolve_core_override()` extracted; three monkeypatch fallback blocks replaced.
- [ ] `_shared.py` re-exports all moved symbols.
- [ ] 151+ tests pass; write-actor tests pass unchanged.

## Slice 3: Extract schema/bootstrap cluster

- [ ] E12-9 post-close check confirms schema cluster scope.
- [ ] `shared_schema.py` created.
- [ ] `_apply_handoff_migrations()` decomposed into named sub-functions.
- [ ] `_shared.py` re-exports all moved symbols.
- [ ] 151+ tests pass; MCP servers start cleanly.

## Slice 4: Introduce typed containers

- [ ] Slice 1 complete.
- [ ] `TaskSnapshot`, `CurrentTaskRenderState`, `ReviewCoverageSummary` defined in `current_task_rendering.py`.
- [ ] Snapshot/render pipeline uses typed containers end-to-end.
- [ ] `_shared.py` re-exports new container types.
- [ ] 151+ tests pass; targeted write-path tests pass unchanged.

## Slice 5: Isolate tool invocation adapters

- [ ] E12-9 post-close check confirms tool invocation cluster stays in `agent-handoff-mcp`.
- [ ] `shared_tool_adapters.py` created.
- [ ] `_shared.py` re-exports all moved symbols.
- [ ] 151+ tests pass.

## Slice 6: Extract DB utilities

- [ ] Slices 1–5 complete.
- [ ] `shared_db_utils.py` created with generic row/count/pagination helpers.
- [ ] `_shared.py` re-exports all moved symbols.
- [ ] 151+ tests pass.

## Slice 7: Extract archival cluster

- [ ] Slices 1–6 complete.
- [ ] `shared_archival.py` created with `ArchivalSummaryBuilder` and `_build_archival_*` helpers.
- [ ] `_shared.py` re-exports all moved symbols.
- [ ] `_shared.py` line count verified below 150 lines after this slice.
- [ ] 151+ tests pass.

## Review Readiness

- [ ] `_shared.py` reduced to re-export stub only; no implementation logic remaining.
- [ ] All cross-package import paths verified after final slice.
- [ ] Handoff decision records each slice's change, verification, and any contract implications.

## Stretch Goals

- [ ] Migrate `agent-orchestrator-mcp/lanes.py` cross-package import to the correct focused module (removes the need to maintain `_shared.py` re-exports; separate from this task's scope).

## Success Criteria

- [ ] `_shared.py` contains only re-export statements and its line count is below 150 lines.
- [ ] Each extracted module has a single coherent responsibility matching its name.
- [ ] All 151+ tests pass with zero import errors across both MCP packages after Slice 5.
- [ ] `agent-orchestrator-mcp/lanes.py` import still resolves without modification.
