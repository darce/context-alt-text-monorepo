# Refactoring Evaluation: `agent_handoff_mcp/_shared.py`

> Cross-referencing Fowler/Beck *Refactoring: Improving the Design of Existing Code* (2nd Ed., 2019) against `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py` to identify concrete refactoring opportunities, likely split seams, and a safe extraction order.

**Date:** 2026-03-30
**Scope:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py`
**Method:** Review the current file structure, function inventory, major responsibility clusters, and the Fowler/Beck smell/refactoring catalog to identify high-payoff internal refactorings without changing external behavior.
**Status:** Pending implementation; see [Sequencing Constraints](#sequencing-constraints) before starting.

**Related Plans:**
- [E12-6. agent-handoff-mcp Internal Refactoring](../12.0/12.1/E12-6-agent-handoff-mcp-internal-refactoring-task-plan.md) — closed 2026-03-29; split `core.py` into domain modules. This evaluation is a follow-on for `_shared.py`, which was outside E12-6's scope. No active implementation plan exists yet.
- E12-9 (orchestration split) — currently active; extractions that touch `_shared.py`'s import surface must wait for E12-9 to complete. See [Sequencing Constraints](#sequencing-constraints).

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [Methodology](#methodology)
- [Current Structure Snapshot](#current-structure-snapshot)
- [High-Impact Findings](#high-impact-findings)
  - [H1: Large Class adapted to a god-module; `_shared.py` mixes at least six responsibilities](#h1-large-class-adapted-to-a-god-module-_sharedpy-mixes-at-least-six-responsibilities)
  - [H2: Divergent Change; unrelated features force edits in the same file](#h2-divergent-change-unrelated-features-force-edits-in-the-same-file)
  - [H3: Primitive Obsession / Data Clumps; raw `dict` state flows dominate snapshot and rendering paths](#h3-primitive-obsession--data-clumps-raw-dict-state-flows-dominate-snapshot-and-rendering-paths)
  - [H4: Long Function; `_apply_handoff_migrations()` and `_render_current_task_md()` are doing multi-phase work inline](#h4-long-function-_apply_handoff_migrations-and-_render_current_task_md-are-doing-multi-phase-work-inline)
- [Medium-Impact Findings](#medium-impact-findings)
  - [M1: Duplicated Code; repeated core-module monkeypatch fallback logic](#m1-duplicated-code-repeated-core-module-monkeypatch-fallback-logic)
  - [M2: Feature Envy / Boundary Drift; rendering helpers know too much about handoff record shapes](#m2-feature-envy--boundary-drift-rendering-helpers-know-too-much-about-handoff-record-shapes)
  - [M3: Speculative Generality risk; generic tool invocation trampoline is useful but isolated poorly](#m3-speculative-generality-risk-generic-tool-invocation-trampoline-is-useful-but-isolated-poorly)
  - [M4: Shotgun Surgery risk around schema/bootstrap work](#m4-shotgun-surgery-risk-around-schemabootstrap-work)
- [Low-Impact Findings](#low-impact-findings)
  - [L1: Mysterious Name; `_shared.py` understates how much policy and orchestration it now owns](#l1-mysterious-name-_sharedpy-understates-how-much-policy-and-orchestration-it-now-owns)
  - [L2: Comments as boundary markers are compensating for missing module boundaries](#l2-comments-as-boundary-markers-are-compensating-for-missing-module-boundaries)
- [Sequencing Constraints](#sequencing-constraints)
- [Recommended Refactoring Sequence](#recommended-refactoring-sequence)
- [Suggested Target Layout](#suggested-target-layout)
- [Bottom Line](#bottom-line)

---

## Executive Summary

Yes; `_shared.py` can be improved materially.

The file is not just long. It is carrying too many unrelated reasons to change:

- schema SQL and migrations
- DB connection/bootstrap
- generic DB/query helpers
- normalization and serialization helpers
- git/write-actor resolution
- archival summary composition
- generic tool invocation wrappers
- task snapshot construction
- `CURRENT_TASK.md` rendering

This is a classic Fowler/Beck **Large Class** smell adapted to a Python module rather than a single class. The stronger associated smell is **Divergent Change**: schema work, rendering changes, git-context changes, and tool-wrapper compatibility work all land in the same file.

The highest-payoff improvement is not micro-cleanup. It is a controlled extraction into a small set of focused modules while keeping `_shared.py` as a compatibility re-export seam during transition.

**Top 3 payoff refactorings:**

1. **Extract Class / Extract Module** for schema/bootstrap, actor/git resolution, and rendering paths
2. **Introduce Parameter Object / Encapsulate Record** for snapshot/rendering state instead of raw `dict` plumbing
3. **Extract Function / Replace Inline Code with Function Call / Split Phase** for migration/bootstrap and markdown rendering flows

---

## Methodology

### Book Concepts Applied

From Fowler/Beck Chapter 3, the most relevant smells for this file are:

- **Large Class**; adapted here as an oversized utility module
- **Divergent Change**; multiple unrelated feature changes land in one file
- **Shotgun Surgery**; one conceptual change requires edits across scattered helper clusters
- **Long Function**; multi-step procedures carry too much inline policy
- **Primitive Obsession**; raw `dict` and string-key state dominate important flows
- **Data Clumps**; repeated `(conn, task_ref, lane_id)` and `state[...]` field groups recur across helpers
- **Duplicated Code**; repeated wrapper fallback patterns and decoder/control logic
- **Feature Envy**; rendering code reaches deeply into generic row dictionaries
- **Mysterious Name**; `_shared.py` no longer describes the true scope of the file

### Key Refactorings Referenced

| Refactoring | Book Reference | Likely Use In `_shared.py` |
| --- | --- | --- |
| Extract Class | Ch. 7 | Split responsibility clusters into focused modules/classes |
| Extract Function | Ch. 6 | Break migration and rendering procedures into smaller steps |
| Introduce Parameter Object | Ch. 6 | Replace free-form snapshot/render state dicts |
| Encapsulate Record | Ch. 7 | Wrap row/state dictionaries with typed access |
| Replace Primitive with Object | Ch. 7 | Optional; promote snapshot/render state from raw dicts |
| Move Function | Ch. 8 | Relocate rendering/bootstrap/git helpers to cohesive homes |
| Replace Inline Code with Function Call | Ch. 8 | Remove repeated monkeypatch-fallback and decode logic |
| Split Phase | Ch. 6 | Separate data collection from rendering/output formatting |
| Remove Middle Man | Ch. 7 | Only selectively; keep `_shared.py` as a temporary compatibility seam |

---

## Current Structure Snapshot

`_shared.py` is currently functioning as a multi-domain utility hub rather than a small shared helper file.

Notable structure points:

- typed dicts / dataclasses begin near lines 108-156
- workspace path helpers at lines 169-177
- schema SQL string begins at line 184 and runs through large embedded DDL/FTS trigger blocks
- FTS/bootstrap/migration helpers run roughly lines 579-905
- generic DB and normalization helpers run roughly lines 907-1466
- archival summary helpers and `ArchivalSummaryBuilder` run roughly lines 1475-1641
- generic tool invocation wrappers run roughly lines 1649-1752
- snapshot and `CURRENT_TASK.md` rendering paths run roughly lines 1760-2051

Function inventory is also high for a supposedly shared utility module:

- ~70+ functions/classes/protocols are defined or re-exported in one file
- multiple sections have their own internal abstraction style and change cadence

This is a strong indicator that the file has become the system’s “overflow boundary” rather than a coherent module.

---

## High-Impact Findings

### H1: Large Class adapted to a god-module; `_shared.py` mixes at least six responsibilities

**Smell:** Large Class
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py`
**Lines:** ~2,000+ lines; ~70+ defs/classes/protocols

**Description:** `_shared.py` carries too many unrelated responsibilities to remain a healthy utility module. The problem is not merely file length. The problem is that multiple independently evolving subsystems have accumulated in one place.

**Responsibility clusters visible today:**

1. **Schema/bootstrap/migration**
   - `HANDOFF_SCHEMA_SQL`, `HANDOFF_FTS_SCHEMA_SQL`, `_HANDOFF_FTS_TRIGGERS_SQL`
   - `_backfill_handoff_fts()`, `_ensure_handoff_fts()`, `_apply_handoff_migrations()`, `_get_db_connection()`
2. **Generic DB/query helpers**
   - `_resolve_task_ref()`, `_fetch_handoff_rows()`, `_paginated_query()`, `_count_task_rows()`
3. **Normalization / decoding / serialization**
   - `_normalize_optional_text()`, `_normalize_lane_message_payload()`, `_decode_turn_metric_row_dict()`
4. **Git / write-actor resolution**
   - `build_write_actor()`, `_detect_git_write_context()`, `_workspace_git_context()`, `_resolve_write_actor()`
5. **Archival summary composition**
   - `_count_by_value()`, `ArchivalSummaryBuilder`, `_build_archival_*()`
6. **Tool invocation adaptation**
   - `_resolve_awaitable()`, `_normalize_tool_result()`, `_unwrap_tool_candidate()`, `_invoke_tool()`
7. **Snapshot and rendering**
   - `_collect_task_snapshot()`, `_build_current_task_state_from_snapshot()`, `_write_current_task_md_for_task()`, `_render_current_task_md()`

This is enough scope for several modules, not one.

**Recommended refactoring:** Apply **Extract Class** as an “Extract Module” program:

- `schema_runtime.py` or `schema_bootstrap.py`
- `db_utils.py`
- `write_context.py`
- `archival_summary.py`
- `tool_adapters.py`
- `current_task_rendering.py`

Keep `_shared.py` temporarily as a re-export seam so `core.py` and tests do not need a flag day migration.

**Risk:** Medium but manageable. Imports are broad, so the extraction should preserve public names and use a staged re-export approach rather than renaming everything at once.

**Cross-package constraint:** `agent-orchestrator-mcp/lanes.py` imports directly from `agent_handoff_mcp._shared` (line 11). This makes the `_shared.py` re-export layer a **hard requirement**, not a temporary convenience shim. The re-exports must remain in place until `agent-orchestrator-mcp` is updated to import from the new module locations in a coordinated slice.

### H2: Divergent Change; unrelated features force edits in the same file

**Smell:** Divergent Change
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py`

**Description:** Multiple unrelated changes necessarily land in `_shared.py` today:

- new review schema or indexes
- FTS bootstrap behavior
- `CURRENT_TASK.md` formatting changes
- write-actor provenance changes
- git commit relation checks
- tool wrapper compatibility behavior

This means the file changes for unrelated reasons, which increases merge risk, review cost, and surprise regressions.

Concrete recent examples already show this pattern:

- review-coverage support touches snapshot/rendering code
- current-task fixes touched internal snapshot writing and rendering state
- schema additions for review runs and turn metrics naturally live here as well

**Recommended refactoring:** Apply **Move Function** and **Split Phase** so each change domain has a smaller home:

- schema changes affect schema/bootstrap module only
- renderer changes affect rendering module only
- git/write-actor changes affect write-context module only

**Risk:** Low if the first step is pure file movement with re-exports; higher if mixed with behavior changes.

### H3: Primitive Obsession / Data Clumps; raw `dict` state flows dominate snapshot and rendering paths

**Smell:** Primitive Obsession + Data Clumps
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py`
**Key areas:** `_collect_task_snapshot()`, `_build_current_task_state_from_snapshot()`, `_render_current_task_md()`

**Description:** Important internal flows rely on loosely structured `dict` objects indexed by string keys:

- snapshot objects
- render state objects
- row dictionaries
- related findings maps
- review coverage payloads

This produces several problems:

- hidden coupling between collection and rendering phases
- fragile string-key assumptions such as `state["decisions_recent"]`, `row["updated_at"]`
- partial states that are easy to construct incorrectly
- difficult-to-locate regressions when one producer silently stops populating a field

Recent bugs in internal current-task writes are consistent with this design pressure: the render pipeline relied on keys such as `task_ref` and `review_coverage` being present, but the internal snapshot path did not always hydrate them.

**Recommended refactoring:** Apply **Introduce Parameter Object** or **Encapsulate Record**:

- `TaskSnapshot`
- `CurrentTaskRenderState`
- `ReviewCoverageSummary`

These can be small `@dataclass` containers with explicit fields and factory constructors from rows/dicts.

This does not require converting the entire module at once. The best starting point is the snapshot/rendering path, because it already behaves like a two-phase pipeline.

**Relationship to existing typed containers:** `_shared.py` already defines six typed structures at lines 108-156 (`WriteActor`, `ResolvedWriteContext`, `TokenUsage`, `PromptMetrics`, `ReviewFindingDetails`, `LaneMessagePayload`). These belong to the write-context and normalization clusters, not the snapshot/rendering path. During extraction: `WriteActor` and `ResolvedWriteContext` move with `shared_write_context.py`; `TokenUsage` and `PromptMetrics` move with `shared_db_utils.py` or remain near their primary consumers; `ReviewFindingDetails` and `LaneMessagePayload` move with the normalization module. The three new containers proposed here belong in `current_task_rendering.py` and do not overlap with the existing six.

**Risk:** Medium. There is a lot of dictionary-based caller/test habit to unwind, but the render path is a good incremental seam.

### H4: Long Function; `_apply_handoff_migrations()` and `_render_current_task_md()` are doing multi-phase work inline

**Smell:** Long Function
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py`

**Description:** Two functions stand out as multi-step workflows embedded inline:

1. `_apply_handoff_migrations()`
   - column-existence checks
   - backfill decisions
   - table creation
   - index creation
   - lock-aware exception policy

2. `_render_current_task_md()`
   - decide active vs non-active task mode
   - compute display variants
   - format decisions/tests/actions
   - append multiple sections conditionally
   - contain local formatting policy like command truncation and token suffixing

Both functions are doing phase changes inside one body rather than delegating to named substeps.

**Recommended refactoring:** Apply **Extract Function**, **Replace Inline Code with Function Call**, and **Split Phase**.

For `_apply_handoff_migrations()`:

- `_ensure_legacy_columns()`
- `_backfill_review_findings_metadata()`
- `_ensure_turn_metrics_schema()`
- `_ensure_turn_metrics_indexes()`

For `_render_current_task_md()`:

- `_build_current_task_header()`
- `_render_latest_decision_section()`
- `_render_core_sections()`
- `_render_non_active_note()`

This would make the code read as a rendering pipeline rather than a large templating procedure.

**Risk:** Low. This is classic no-behavior-change extraction work backed by existing tests.

---

## Medium-Impact Findings

### M1: Duplicated Code; repeated core-module monkeypatch fallback logic

**Smell:** Duplicated Code
**Key functions:** `_workspace_git_context()`, `_annotate_review_finding()`, `_resolve_write_actor()`

**Description:** Several helpers repeat the same pattern:

- import `sys`
- find `agent_handoff_mcp.core` in `sys.modules`
- probe for an override function on the core module
- fall back to the local implementation

This repetition exists to preserve test monkeypatching behavior, which is valid, but the pattern itself is duplicated.

**Recommended refactoring:** Apply **Replace Inline Code with Function Call** by extracting a helper such as:

- `_resolve_core_override(name: str, fallback: Callable[..., T]) -> Callable[..., T]`

That keeps the monkeypatch seam but eliminates repeated local boilerplate.

**Risk:** Low.

### M2: Feature Envy / Boundary Drift; rendering helpers know too much about handoff record shapes

**Smell:** Feature Envy
**Key functions:** `_render_lanes_section()`, `_render_findings_section()`, `_render_coverage_section()`, `_render_current_task_md()`

**Description:** Rendering helpers reach directly into generic rows and state dicts for many field names and formatting rules. This couples markdown generation tightly to low-level storage shape.

Examples:

- findings format severity, location, and descriptions directly from row dicts
- lane sections know open-message filtering rules and dispatch direction semantics
- test rendering includes command truncation policy inline

**Recommended refactoring:** Apply **Move Function** plus **Encapsulate Record** so row interpretation happens before rendering. The renderer should consume view-model style objects rather than raw DB-shaped dicts.

**Risk:** Medium; best done after introducing a parameter object for render state.

### M3: Speculative Generality risk; generic tool invocation trampoline is useful but isolated poorly

**Smell:** Speculative Generality (borderline) / Divergent Change
**Key functions:** `_resolve_awaitable()`, `_normalize_tool_result()`, `_unwrap_tool_candidate()`, `_invoke_tool()`

**Description:** The tool invocation block supports several wrapper shapes (`fn`, `function`, `func`, `run(arguments)`), async resolution, and result normalization. This may be justified, but it is conceptually very different from schema and rendering work.

The primary issue is placement, not necessarily existence.

**Recommended refactoring:** Apply **Extract Class** or module extraction into a dedicated `tool_adapters.py` or `invocation.py`. That keeps generic compatibility logic isolated and testable.

**Risk:** Low.

### M4: Shotgun Surgery risk around schema/bootstrap work

**Smell:** Shotgun Surgery
**Key areas:** schema SQL, FTS triggers, migrations, connection bootstrap

**Description:** Any new persisted concept can require edits in multiple places inside the same file:

- base schema SQL
- migration helper
- indexes
- optional FTS integration
- row decoders or snapshot collectors

This is not yet a bug by itself, but the file layout increases the odds of missing one step because the work is distributed across distant sections in one large module.

**Recommended refactoring:** Use **Split Phase** and **Move Function** to group schema responsibilities into one dedicated module and snapshot/render responsibilities into another. This reduces the number of unrelated sections a contributor must scan for one conceptual schema change.

**Risk:** Medium.

---

## Low-Impact Findings

### L1: Mysterious Name; `_shared.py` understates how much policy and orchestration it now owns

**Smell:** Mysterious Name

The name suggests a thin utility layer. The actual file includes schema ownership, bootstrap behavior, rendering, git context, tool adaptation, and archival summarization.

**Recommended refactoring:** After extraction, reserve `_shared.py` for truly cross-cutting re-exports or rename the compatibility seam more explicitly.

### L2: Comments as boundary markers are compensating for missing module boundaries

**Smell:** Comments

The section banners are helpful, but they are doing work that proper module boundaries should do. They are effectively standing in for a package structure.

**Recommended refactoring:** Keep the comments during transition, but treat them as evidence for extractable modules rather than a final organizational solution.

---

## Sequencing Constraints

**E12-9 must complete before this refactoring begins** (or individual steps must be cleared as safe in parallel with explicit confirmation).

E12-9 is physically separating orchestration code from `agent-handoff-mcp` to `agent-orchestrator-mcp`. This directly affects `_shared.py`'s import surface; some responsibility clusters may relocate or be removed. Concurrent structural changes to the same package risk merge conflicts and invalidated extraction targets.

Safe-to-start analysis per step:

| Step | Safe before E12-9? | Reason |
| ---- | ------------------ | ------ |
| 1. Rendering extraction | Possibly; verify | Rendering code is unlikely to move in E12-9, but confirm after E12-9 closes |
| 2. Write-context extraction | No | Git/actor helpers are candidates for orchestrator relocation |
| 3. Schema/bootstrap extraction | No | DB bootstrap is shared across packages; extraction targets may shift |
| 4. Typed state/view models | After Step 1 | Depends on rendering module landing zone |
| 5. Tool invocation adapters | After E12-9 | Tool invocation trampolines may cross to the orchestrator package |

Recommended gate: after E12-9 closes, diff `_shared.py` against the pre-E12-9 baseline to confirm which sections were modified before starting any step.

---

## Recommended Refactoring Sequence

### 1. Extract pure rendering first

Why first:

- low risk
- already conceptually isolated near the bottom of the file
- recent regressions touched this path, so better local structure has immediate payoff

Refactorings:

- **Extract Function**
- **Split Phase**
- **Introduce Parameter Object** for render state

Target outcome:

- a dedicated rendering module handling `CURRENT_TASK.md`
- snapshot collection and render formatting no longer interleaved conceptually

Proof of completion:

- all 151+ tests pass with no import changes in consuming modules
- `test_handoff_state.py` and `test_review_findings.py` pass without modification
- `_shared.py` re-exports the rendering symbols for backward compatibility
- no new import errors at server startup

### 2. Extract write-context and git helpers

Why second:

- self-contained responsibility cluster
- repeated monkeypatch fallback logic can be eliminated cleanly

Refactorings:

- **Move Function**
- **Replace Inline Code with Function Call**

Target outcome:

- a dedicated write-context module with actor normalization, git detection, and commit relation helpers

Proof of completion:

- all tests pass with no changes to consuming module imports
- write-actor and git-context tests in `test_handoff_state.py` pass unchanged
- `_shared.py` re-exports write-context symbols

### 3. Extract schema/bootstrap/migration logic

Why third:

- highest payoff, but more sensitive because it touches DB initialization
- benefits from being isolated before further schema work lands

Refactorings:

- **Extract Class** / module extraction
- **Extract Function**
- **Split Phase**

Target outcome:

- one module owns DDL, migrations, FTS setup, and DB connection bootstrap

Proof of completion:

- all tests pass; DB initialization and migration paths produce identical results
- MCP servers start cleanly using the new bootstrap module
- `_shared.py` re-exports schema/bootstrap symbols

### 4. Introduce typed state/view models for snapshot and rendering

Why fourth:

- safer after rendering is extracted
- avoids mixing structural movement with semantic representation change too early

Refactorings:

- **Introduce Parameter Object**
- **Encapsulate Record**
- optionally **Replace Primitive with Object** for render-state payloads

Proof of completion:

- all tests pass; no `dict`-access regressions in current-task write path
- `_write_current_task_md_for_task()` uses typed `CurrentTaskRenderState` instead of raw dict
- `test_internal_write_path_includes_task_ref` and `test_internal_write_path_includes_review_coverage` pass unchanged

### 5. Isolate generic tool invocation adapters

Why last:

- least urgent
- easiest to do once the rest of the file has stopped growing

Refactorings:

- **Extract Class** / module extraction

Proof of completion:

- all tests pass
- `_invoke_tool()` and related functions importable from new module
- `_shared.py` re-exports them for backward compatibility

---

## Suggested Target Layout

One reasonable end state:

- `shared_schema.py`
  - schema SQL strings
  - migrations
  - FTS setup
  - DB bootstrap
- `shared_db_utils.py`
  - generic row/count/pagination helpers
- `shared_write_context.py`
  - actor normalization
  - git context helpers
  - commit relation classification
- `shared_archival.py`
  - `ArchivalSummaryBuilder`
  - archival count helpers
- `shared_tool_adapters.py`
  - `_resolve_awaitable()`
  - `_invoke_tool()`
  - wrapper protocols
- `current_task_rendering.py`
  - snapshot state types
  - markdown rendering
  - related findings and review coverage assembly
- `_shared.py`
  - **required** re-export layer; in-package consumers (`core.py`, `handoff_state.py`, `decisions.py`, `import_export.py`, `review_findings.py`) and cross-package consumer (`agent-orchestrator-mcp/lanes.py`) all import from here. Re-exports cannot be removed until the cross-package dependency is migrated in a coordinated step.

This preserves the current public import surface while reducing the working-set size for any single change.

---

## Bottom Line

`_shared.py` is improvable in a meaningful way, and the file is a strong refactoring candidate by Fowler/Beck standards.

The core issue is not just that it is over 2k lines. The core issue is that it has become a convergence point for too many different change streams. The best response is a staged extraction, not cosmetic cleanup.

If only one improvement is funded, prioritize extracting the `CURRENT_TASK.md` snapshot/rendering path plus a typed render-state object. That delivers the best mix of immediate readability improvement, lower regression risk, and clearer future seams for the rest of the file.