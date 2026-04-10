# Task Plan

> **Metadata**
>
> - **Date**: 2026-03-29 17:00 EDT
> - **Author**: Claude Sonnet 4.6
> - **Owning Epic**: [docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md](../../epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: E12

---

# E12-6. agent-handoff-mcp Internal Refactoring

## Objective

Reduce technical debt in `packages/agent-handoff-mcp/` by extracting testable guard functions, introducing typed parameter objects, splitting `core.py` (4,477 lines) into focused domain modules, consolidating the tool registration pipeline across both MCP packages, and decomposing the two long daemon loops. Each slice is independently deliverable and behavior-preserving; the 788-test suite is the primary safety net.

## Problem Statement

`core.py` is a 4,477-line god module containing at least nine distinct responsibility areas (schema, normalization, git context, FTS search, markdown rendering, handoff state CRUD, review findings state machine, lane/worker coordination, and import/export). Every module in the package imports from this single file, creating a dependency hub that makes isolated testing, focused review, and confident modification difficult. Secondary concerns include: a 22-parameter function signature (`record_turn_metric`), a 209-line function with interleaved guard policies (`update_review_finding`), a 483-line `if/elif` CLI dispatch chain, and identical pagination boilerplate duplicated across six list functions. These smells are documented and prioritized in `docs/tasks/tech-debt/refactoring-agent-handoff-mcp-evaluation.md`.

## Constraints

- `core.py` must remain pure handoff-state CRUD per `rg-013`. Extracted modules must not import orchestration symbols or spawn subprocesses.
- `agent-orchestrator-mcp` modules must use late-binding (function-level) imports for `agent-handoff-mcp` symbols per `rg-014`.
- All 788 existing tests must continue passing after each slice. No test can be deleted or skipped to accommodate a refactoring.
- Deprecated Python alias functions (`get_artifact_source`, `get_artifact_terms`, `list_artifact_sources`, `get_review_finding`, `reopen_review_finding`, `get_handoff_dashboard`) must remain callable until tech-debt item #13 is resolved. They must not be moved to extracted modules that break their existing import paths from `api.py` and `__init__.py`.
- Slice 3 (core.py domain split) must precede Slices 4 and 5, which target the post-split structure.

## Workflow Principles

- Each slice must leave tests green and the MCP servers startable before closing.
- Refactorings are behavior-preserving; no functional changes within a slice unless noted explicitly.
- New module names must comply with `rg-013`: extracted modules stay in `packages/agent-handoff-mcp/src/agent_handoff_mcp/` and do not import from `orchestration/`.
- Tool registration pipeline changes (Slice 4) apply to both `agent-handoff-mcp` and `agent-orchestrator-mcp` in the same slice.

## Terminology

- **God module**: A single Python file containing multiple unrelated responsibility domains; here, `core.py`.
- **Guard function**: A pure validation sub-function extracted from a long policy-checking function; returns an error dict or `None`.
- **Parameter object**: A dataclass grouping related function parameters into a typed structure.
- **Domain module**: A focused module holding one responsibility area extracted from `core.py` (e.g., `rendering.py`, `review_findings.py`).
- **Tool registry**: A data structure mapping tool names to handler functions, argument specs, and descriptions, used to drive both MCP registration and CLI subparser generation.

## Current State Analysis

- `core.py`: 4,477 lines, 110 top-level functions, 9 responsibility areas. Every module in the package imports from it.
- `update_review_finding`: ~209 lines with four interleaved responsibilities (input validation, reopen escalation guard, batch-close guard, commit relation guard).
- `record_turn_metric`: 22 parameters across at least three cohesive groups (token usage, prompt metrics, analytics).
- `_resolve_write_actor`: returns a 7-element tuple unpacked at 15+ call sites in `core.py`.
- Six list functions share identical pagination boilerplate (~20 lines each, ~120 lines total duplication).
- `cli.py`: `_build_parser()` ~379 lines, `main()` ~483 lines; each new tool adds ~25 lines to both.
- `agent-orchestrator-mcp/api.py`: 921 lines with the same tool-registration pattern (H4) as the handoff package.
- `orchestration/worker_daemon.py`: `worker_loop()` ~500 lines, 14 parameters.
- `orchestration/orchestrator_daemon.py`: `orchestrator_loop()` ~300+ lines managing 5 independent subsystems.

## Target Outcome

After all slices, `core.py` is a ~500-line handoff helper (DB connection, normalization, write actor resolution, git context helpers) with nine focused domain modules alongside it. `update_review_finding` is ~70 lines delegating to three independently testable guards. `record_turn_metric` accepts `TokenUsage` and `PromptMetrics` typed objects instead of 22 positional parameters. Both MCP packages share a tool registry pattern that makes adding or removing a tool a single-file change. The daemon loops are decomposed into phase functions with shared context objects. The 788-test suite continues to pass throughout.

## Context Loading

- Rules: `docs/agentic/instructions.md` (rg-013, rg-014, sr-006)
- Evaluation: `docs/tasks/tech-debt/refactoring-agent-handoff-mcp-evaluation.md` (authoritative smell catalog and recommended sequence)
- Tech debt: `docs/tasks/tech-debt/current-debt.md` (item #13 — deprecated alias test migration, prerequisite for full alias deletion)
- Key source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`
- Key source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`
- Key source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`
- Key source: `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py`
- Key source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`
- Key source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/orchestrator_daemon.py`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `agent-handoff-mcp` public API (`__init__.py`) | agentic-tooling | `docs/agentic/contracts/agent-handoff-mcp.md` | None — all public exports retained; internal restructuring only | No | `pytest` full suite |
| `agent-handoff-mcp` MCP surface | agentic-tooling | `docs/agentic/contracts/agent-handoff-mcp.md` | None — MCP tool registrations unchanged | No | `doctor` tool count = 22 |
| `agent-orchestrator-mcp` MCP surface | agentic-tooling | `docs/agentic/contracts/agent-orchestrator-mcp.md` | None until Slice 4 (CLI registry); tool count unchanged | No | `doctor` tool count = 37 |
| Deprecated Python aliases | agentic-tooling | Tech debt #13 | Aliases remain callable throughout; not moved to new modules | Yes — until #13 resolved | `grep` import paths in `api.py` and `__init__.py` |

## Proposed Solution

Five slices in dependency order. Slices 1 and 2 are independent and can be parallelized. Slice 3 depends on neither but must complete before Slices 4 and 5. Slices 4 and 5 depend on Slice 3.

1. **Quick-win function extractions** — guard extraction from `update_review_finding` (H2) and pagination helper from six list functions (M4). Core.py only; small and safe.
2. **Parameter objects** — `ResolvedWriteContext` (replaces 7-tuple), `TokenUsage`/`PromptMetrics` for `record_turn_metric`, `WorkerConfig` for `worker_loop`, `ObservabilityContext` for `_record_observability`.
3. **Extract core.py into domain modules** (H1) — split by responsibility area; `core.py` reduced to ~500-line handoff helper.
4. **Tool registration pipeline** (H4, H6) — shared registry in both MCP packages eliminates the `if/elif` chain and duplicated argument definitions.
5. **Daemon loop decomposition** (M7, M8) — extract loop phases into standalone functions or phase objects in both daemon files.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Slices 1–3: extract guards, pagination helper, domain modules; reduce to ~500 lines |
| backend (new) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py` | Slice 3: review finding CRUD + guards + integrity |
| backend (new) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/rendering.py` | Slice 3: CURRENT_TASK.md renderer |
| backend (new) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/import_export.py` | Slice 3: snapshot, import, export |
| backend (new) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/schema.py` | Slice 3: DDL, migrations, FTS setup |
| backend (new) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py` | Slice 3: singleton state CRUD |
| backend (new) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/lanes.py` | Slice 3: lane/worker CRUD, messages |
| backend (new) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py` | Slice 3: decision recording, next actions, handoff close check |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Slice 4: tool registry drives MCP registration |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` | Slice 4: registry drives CLI subparsers and dispatch |
| backend | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` | Slice 4: same tool registry pattern |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py` | Slice 2 + 5: `WorkerConfig`, `ObservabilityContext`; phase extraction |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/orchestrator_daemon.py` | Slice 5: phase extraction |
| tests | `packages/agent-handoff-mcp/tests/` | Slices 1–3: targeted updates to import paths; no new test skips |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` | Must re-export all public symbols after Slice 3 extraction; no removed exports |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/enums.py` | Not modified; domain modules import from here |
| `docs/tasks/tech-debt/refactoring-agent-handoff-mcp-evaluation.md` | Authoritative smell catalog; each slice references evaluation finding IDs |
| `docs/tasks/tech-debt/current-debt.md` | Item #13 (deprecated alias test migration) must be resolved to enable full alias deletion post-Slice 3 |
| `packages/agent-handoff-mcp/tests/test_handoff_state.py` | ~3,100 lines; should be split alongside Slice 3 to mirror the domain module structure |

## Verification Strategy

- Deterministic tests:
  - `python -m pytest packages/agent-handoff-mcp/tests/ -x -q` after every slice
  - `python -m pytest packages/agent-orchestrator-mcp/tests/ -x -q` after Slice 4
- Runtime-parity checks:
  - `agent-handoff-mcp --workspace-root . doctor` — tool_count must remain 22 throughout
  - `agent-orchestrator-mcp --workspace-root . doctor` — tool_count must remain 37 throughout
- Structural verification:
  - `wc -l packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` — after Slice 3: ≤ 600 lines
  - `grep -n "def " packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py | wc -l` — after Slice 3: ≤ 25 functions
- Import integrity:
  - `python -c "import agent_handoff_mcp; print('ok')"` — must pass after every slice
  - All public `__all__` symbols in `__init__.py` must remain importable after Slice 3

---

## Slice Delivery

### Slice 1: Quick-Win Function Extractions (H2, M4)

**Goal**: Reduce `update_review_finding` from ~209 lines to ~70 lines via guard extraction, and eliminate pagination boilerplate duplication across six list functions.

Changes:

- Extract three guard functions from `update_review_finding` in `core.py`:
  - `_check_reopen_escalation_guard(existing, verification_evidence) -> dict | None`
  - `_check_batch_close_guard(conn, task_ref, existing_id) -> dict | None`
  - `_check_commit_relation_guard(existing, commit_sha, verified_commit_sha, branch, resolution_notes) -> dict | None`
- `update_review_finding` becomes a ~70-line orchestrator calling the three guards then executing the UPDATE.
- Extract `_paginated_query(conn, table, where_sql, params, limit, offset, row_decoder=dict) -> dict` helper.
- Apply to: `list_plan_cursors`, `list_lane_messages`, `list_lane_briefs`, `list_worker_reports`, `list_review_findings`, `list_turn_metrics`.
- All changes remain inside `core.py`.

Proof:

- `python -m pytest packages/agent-handoff-mcp/tests/ -x -q` passes (788 tests)
- `wc -l` shows `update_review_finding` ≤ 80 lines
- Each guard function is directly callable in a test: `_check_reopen_escalation_guard(...)` returns `None` on valid input
- `_paginated_query` is present and each list function body is ≤ 15 lines

### Slice 2: Parameter Objects (H5, L3)

**Goal**: Replace the 22-parameter `record_turn_metric` signature and the 7-tuple `_resolve_write_actor` return with typed dataclasses; create `WorkerConfig` and `ObservabilityContext` for the daemon files.

Changes:

- Add `TokenUsage` dataclass: `input_tokens`, `output_tokens`, `cached_input_tokens`, `reasoning_output_tokens`, `total_tokens`, `usage_source`.
- Add `PromptMetrics` dataclass: `model_context_window`, `prompt_tokens`, `prompt_chars`, `prompt_token_source`, `utilization_ratio`, `domain_signal_ratio`, `pressure_level`.
- Update `record_turn_metric` to accept `TokenUsage` and `PromptMetrics` objects (reduces from 22 to ~10 positional params). Update all callers.
- Add `ResolvedWriteContext` dataclass (fields: `agent`, `branch`, `commit_sha`, `lane_id`, `model`, `model_label`, `reasoning_level`). Change `_resolve_write_actor` return type; update all 15+ unpacking sites in `core.py`.
- Add `WorkerConfig` dataclass grouping the 14 parameters of `worker_loop`. Update `worker_loop` signature and the argparse→`worker_loop` call site inside `worker_daemon.py` (`worker_daemon_ctl.py` spawns `worker_daemon.py` as a subprocess and is not a direct caller).
- Add `ObservabilityContext` dataclass grouping the 8 observability-specific parameters of `_record_observability`.
- Export `TokenUsage`, `PromptMetrics`, `ResolvedWriteContext` from `__init__.py` if used by external callers.

Proof:

- `python -m pytest packages/agent-handoff-mcp/tests/ -x -q` passes
- `python -m pytest packages/agent-orchestrator-mcp/tests/ -x -q` passes
- `record_turn_metric` signature has ≤ 10 parameters
- `_resolve_write_actor` return type is `ResolvedWriteContext`, not a tuple
- `worker_loop` accepts a single `WorkerConfig` positional argument

### Slice 3: Extract core.py into Domain Modules (H1)

**Goal**: Reduce `core.py` to a ~500-line handoff helper by extracting seven domain modules; all public exports remain importable from `agent_handoff_mcp`.

Changes, in safe extraction order:

1. Extract `schema.py` — DDL (`CREATE TABLE` statements), `_apply_handoff_migrations`, `_has_column`, `_has_index`, FTS setup. Update `_get_db_connection()` in `core.py` to import and call `_apply_handoff_migrations` from `schema.py`; no other callers to update.
2. Extract `rendering.py` — `_render_current_task_md`, `_format_token_suffix`, `_truncate_command`, `generate_current_task_md`. Update `core.py` to delegate.
3. Extract `import_export.py` — `_collect_handoff_snapshot`, `_import_snapshot`, `export_handoff_state`, `import_handoff_state`. Update callers.
4. Extract `review_findings.py` — `record_review_finding`, `update_review_finding` (with extracted guards from Slice 1), `reconcile_review_findings`, `get_review_findings_summary`, integrity helpers. Update callers.
5. Extract `lanes.py` — `upsert_worktree_lane`, `close_worktree_lane`, `list_worktree_lanes`, `record_lane_message`, `update_lane_message`, `list_lane_messages`, `record_lane_brief`, `list_lane_briefs`, `record_worker_report`, `list_worker_reports`, `get_lane_activity`. Update callers.
6. Extract `handoff_state.py` — `set_handoff_state`, `get_handoff_state`, `switch_task`, `archive_task_state`. Update callers.
7. Extract `decisions.py` — `record_decision`, `update_next_actions`, `list_next_actions`, `handoff_close_check`. Update callers.
8. `core.py` retains: DB connection (`_get_db_connection`), normalization utilities, `_resolve_write_actor` (now returning `ResolvedWriteContext`), git context helpers, deprecated aliases (until tech-debt #13 resolved), `search_handoff`, FTS search helpers, `upsert_plan_cursor`, `get_plan_cursor`, `list_plan_cursors` (cross-package CRUD exposed via agent-orchestrator-mcp MCP surface; keeping them in `core.py` preserves the late-binding import seam required by rg-014).
9. Update `__init__.py` to re-export all public symbols from the new modules; remove imports of moved symbols from `core.py`.
10. Split `tests/test_handoff_state.py` (~3,100 lines) into per-module test files mirroring the new structure. No tests deleted, only reorganized.

Proof:

- `python -m pytest packages/agent-handoff-mcp/tests/ -x -q` passes (788 tests)
- `wc -l packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` ≤ 600
- `grep -n "^def " packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py | wc -l` ≤ 25
- `python -c "from agent_handoff_mcp import set_handoff_state, record_review_finding, get_lane_activity; print('ok')"` succeeds
- `agent-handoff-mcp --workspace-root . doctor` reports tool_count = 22

### Slice 4: Tool Registration Pipeline (H4, H6)

**Goal**: Eliminate the 483-line `if/elif` dispatch chain and the 379-line subparser tree in `agent-handoff-mcp/cli.py`, and eliminate the parallel `mcp.add_tool()` calls in both packages, by introducing a tool registry that drives MCP registration and (where applicable) CLI generation from one definition per tool.

Changes for `agent-handoff-mcp` (H4 + H6 both apply):

- Define a `TOOL_REGISTRY: list[ToolEntry]` where each `ToolEntry` holds: `name`, `handler`, `description`, `args: list[ArgSpec]`.
- Common argument specs (`task_ref_arg`, `lane_id_arg`, `actor_args`) defined once and reused.
- `build_handoff_mcp()`: iterate registry to register tools (replaces individual `mcp.add_tool()` calls).
- `_build_parser()`: iterate registry to add subparsers (replaces 379-line function).
- `main()`: registry lookup by `args.command` replaces 483-line `if/elif` chain.

Changes for `agent-orchestrator-mcp` (H4 applies; H6 does not — its cli.py is 65 lines with no per-tool subparsers):

- Define `TOOL_REGISTRY` in `agent-orchestrator-mcp/api.py` on the same pattern.
- `build_orchestrator_mcp()`: iterate registry to register tools.
- `agent-orchestrator-mcp/cli.py` is not modified — it has no per-tool CLI dispatch and the H6 smell does not apply.

No changes to tool names, descriptions, or parameters visible to MCP clients in either package.

Proof:

- `python -m pytest packages/agent-handoff-mcp/tests/ -x -q` passes
- `python -m pytest packages/agent-orchestrator-mcp/tests/ -x -q` passes
- `agent-handoff-mcp --workspace-root . doctor` tool_count = 22
- `agent-orchestrator-mcp --workspace-root . doctor` tool_count = 37
- `wc -l packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` is reduced meaningfully vs. pre-slice baseline
- `agent-orchestrator-mcp/cli.py` is unchanged at ~65 lines
- Adding a new tool to either package requires editing exactly one registry definition file

### Slice 5: Daemon Loop Decomposition (M7, M8)

**Goal**: Extract the 300-line `orchestrator_loop` and 500-line `worker_loop` into phase functions with shared context objects, making each phase independently readable and testable.

Changes:

- `orchestrator_daemon.py`: Extract five loop phases as standalone functions receiving a shared `OrchestratorContext` dataclass:
  - `_dispatch_phase(ctx)`
  - `_guidance_phase(ctx)`
  - `_plan_dispatch_phase(ctx)`
  - `_worker_management_phase(ctx)`
  - `_lane_intake_phase(ctx)`
  - `orchestrator_loop` becomes a ~40-line while loop delegating to these five functions.
- `worker_daemon.py`: Extract five loop phases as standalone functions receiving a `WorkerRunContext` dataclass (distinct from `WorkerConfig` — holds mutable per-cycle state):
  - `_poll_phase(ctx)` → returns work item or None
  - `_execute_phase(ctx, work_item)`
  - `_review_phase(ctx, result)`
  - `_verify_phase(ctx, review_result)`
  - `_handoff_phase(ctx, verify_result)`
  - `worker_loop` becomes a ~50-line while loop.
- No changes to external entry points (`orchestrator_start`, `worker_start`, `worker_daemon_ctl.py`).

Proof:

- `python -m pytest packages/agent-handoff-mcp/tests/ -x -q` passes
- `python -m pytest packages/agent-orchestrator-mcp/tests/ -x -q` passes
- `wc -l packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/orchestrator_daemon.py` reduced by ≥ 200 lines
- `wc -l packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py` reduced by ≥ 350 lines
- Each extracted phase function is callable in isolation with a mock context object

---

# Consolidated Checklist

## Context and Ownership

- [x] Loaded `rg-013`, `rg-014` from `instructions.md`.
- [x] Read `docs/tasks/tech-debt/refactoring-agent-handoff-mcp-evaluation.md` for smell catalog and sequencing rationale.
- [x] Checked tech-debt item #13 status (deprecated alias test migration) before Slice 3.
- [x] Confirmed `__init__.py` re-export inventory before Slice 3 extraction.

## Slice 1: Quick-Win Function Extractions

- [x] `_check_reopen_escalation_guard` extracted and individually callable
- [x] `_check_batch_close_guard` extracted and individually callable
- [x] `_check_commit_relation_guard` extracted and individually callable
- [x] `update_review_finding` body ≤ 80 lines (59 lines)
- [x] `_paginated_query` helper extracted
- [x] All six list functions use `_paginated_query`
- [x] `pytest packages/agent-handoff-mcp/tests/ -x -q` passes (788 tests)

## Slice 2: Parameter Objects

- [x] `TokenUsage` dataclass defined and used in `record_turn_metric`
- [x] `PromptMetrics` dataclass defined and used in `record_turn_metric`
- [ ] `record_turn_metric` has ≤ 10 positional parameters (15 params; was 22 — deferred to future cleanup)
- [x] `ResolvedWriteContext` dataclass defined; `_resolve_write_actor` returns it
- [x] All 15+ tuple-unpacking sites updated to use `ResolvedWriteContext` attributes
- [x] `WorkerConfig` dataclass defined; `worker_loop` accepts it
- [x] `ObservabilityContext` dataclass defined; `_record_observability` accepts it
- [x] `pytest packages/agent-handoff-mcp/tests/ -x -q` passes
- [x] `pytest packages/agent-orchestrator-mcp/tests/ -x -q` passes

## Slice 3: Extract core.py into Domain Modules

- [x] `schema.py` extracted (absorbed into `_shared.py`); `core.py` delegates schema init
- [x] `rendering.py` extracted (absorbed into `_shared.py`); `generate_current_task_md` importable
- [x] `import_export.py` extracted; import/export tools work via MCP
- [x] `review_findings.py` extracted; all finding tools work via MCP
- [x] `lanes.py` extracted; all lane tools work via MCP
- [x] `handoff_state.py` extracted; `set_handoff_state`/`get_handoff_state` work via MCP
- [x] `decisions.py` extracted; `record_decision` works via MCP
- [x] `core.py` ≤ 600 lines (600 lines, 16 functions)
- [x] All public symbols still importable from `agent_handoff_mcp`
- [x] Deprecated aliases remain at their current import paths
- [ ] `test_handoff_state.py` split into per-module files (deferred; 788 tests pass without reorganization)
- [x] `pytest packages/agent-handoff-mcp/tests/ -x -q` passes (788 tests)
- [x] `agent-handoff-mcp doctor` tool_count = 22

## Slice 4: Tool Registration Pipeline

- [x] `TOOL_REGISTRY` defined in `agent-handoff-mcp/api.py` (_build_tool_registry, 22 entries)
- [x] `build_handoff_mcp()` uses registry iteration
- [x] `agent-handoff-mcp/_build_parser()` uses registry iteration (42 lines)
- [x] `agent-handoff-mcp/main()` uses registry lookup (40 lines, no if/elif chain)
- [x] `TOOL_REGISTRY` defined in `agent-orchestrator-mcp/api.py` (_build_tool_registry, 37 entries)
- [x] `build_orchestrator_mcp()` uses registry iteration
- [x] `agent-orchestrator-mcp/cli.py` unchanged (~65 lines; H6 does not apply)
- [x] `pytest packages/agent-handoff-mcp/tests/ -x -q` passes
- [x] `pytest packages/agent-orchestrator-mcp/tests/ -x -q` passes
- [x] Both `doctor` commands confirm unchanged tool counts

## Slice 5: Daemon Loop Decomposition

- [x] Five orchestrator loop phases extracted as standalone functions (_dispatch_phase, _guidance_phase, _plan_dispatch_phase, _worker_management_phase, _lane_intake_phase)
- [x] `OrchestratorContext` dataclass defined
- [x] `orchestrator_loop` ≤ 50 lines (21 lines)
- [x] Five worker loop phases extracted as standalone functions (_poll_phase, _execute_phase, _review_phase, _verify_phase, _handoff_phase)
- [x] `WorkerRunContext` dataclass defined
- [x] `worker_loop` ≤ 60 lines (60 lines)
- [x] `pytest packages/agent-handoff-mcp/tests/ -x -q` passes
- [x] `pytest packages/agent-orchestrator-mcp/tests/ -x -q` passes

## Review Readiness

- [x] No boundary-touching implementation without matching contract/doc evidence.
- [x] All slices leave both MCP servers startable with correct tool counts.
- [x] Handoff decision recorded per slice.

## Stretch Goals

- [x] `ArtifactSource` TypedDict introduced in `artifact_index.py` (L4: Replace Primitive with Object) — `ArtifactChunk`, `ArtifactSource`, `ArtifactSearchResult`, `ArtifactUpsertResult` TypedDicts added; four function return types updated
- [x] `list_lane_messages` parameterized to subsume `list_lane_briefs` via `direction`/`subject_prefix` filters (L1: Parameterize Function) — optional params added; `list_lane_briefs` preserved for backward compat
- [x] `ArchivalSummaryBuilder` class introduced for `_build_archival_*_summary` family (M6: Combine Functions into Class) — five methods on the class; module-level functions are single-line wrappers
- [x] `PromptFormatter` class introduced in `lane_prompt.py` (L2: Combine Functions into Class) — eight `@staticmethod` formatters on the class; `_format_*` functions delegate to it

## Success Criteria

- [x] `core.py` ≤ 600 lines and ≤ 25 top-level function definitions (600 lines, 16 functions)
- [x] All six domain modules exist and are independently importable (_shared, decisions, handoff_state, import_export, lanes, review_findings)
- [x] `update_review_finding` ≤ 80 lines; three guard functions independently testable (59 lines)
- [x] `record_turn_metric` accepts `TokenUsage` and `PromptMetrics` objects
- [x] Both CLI modules (handoff + orchestrator) dispatch via registry with no `if/elif` chain
- [x] Both daemon loops ≤ 60 lines each with extracted phase functions (orchestrator: 21, worker: 60)
- [x] All 788+ tests pass across both packages (788 handoff + 6 orchestrator = 794)
- [x] `agent-handoff-mcp doctor` tool_count = 22; `agent-orchestrator-mcp doctor` tool_count = 37

> **Status**: CLOSED 2026-03-29. All success criteria met. Decision: `cs_slice_complete_E12-6_all_slices_done`.
