# Refactoring Evaluation: agent-handoff-mcp Package

> Cross-referencing Fowler/Beck "Refactoring: Improving the Design of Existing Code" (2nd Ed., 2019) against the `packages/agent-handoff-mcp` MCP server to identify areas that would benefit from systematic refactoring.

**Date:** 2026-03-28
**Scope:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/` (all modules)
**Method:** Codebase exploration guided by the code smells catalog from Chapter 3, supplemented by the refactoring catalog (Chapters 6-12). Special focus on `core.py` as the dominant module.

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [Methodology](#methodology)
- [Size Inventory](#size-inventory)
- [High-Impact Findings](#high-impact-findings)
  - [H1: Large Class; core.py (4,360 lines, 110 functions)](#h1-large-class-corepy-4360-lines-110-functions)
  - [H2: Long Function; update_review_finding (209 lines)](#h2-long-function-update_review_finding-209-lines)
  - [H3: Long Function; _import_snapshot (130 lines)](#h3-long-function-_import_snapshot-130-lines)
  - [H4: Shotgun Surgery; adding a new MCP tool requires 4 files](#h4-shotgun-surgery-adding-a-new-mcp-tool-requires-4-files)
  - [H5: Long Parameter List; record_turn_metric (22 params)](#h5-long-parameter-list-record_turn_metric-22-params)
  - [H6: Large Class; cli.py main() 483-line if/elif chain](#h6-large-class-clipy-main-483-line-ifelif-chain)
- [Medium-Impact Findings](#medium-impact-findings)
  - [M1: Long Function; _render_current_task_md (169 lines)](#m1-long-function-_render_current_task_md-169-lines)
  - [M2: Long Function; handoff_close_check (116 lines)](#m2-long-function-handoff_close_check-116-lines)
  - [M3: Long Function; upsert_plan_cursor (142 lines)](#m3-long-function-upsert_plan_cursor-142-lines)
  - [M4: Duplicated Code; list pagination boilerplate](#m4-duplicated-code-list-pagination-boilerplate)
  - [M5: Middle Man; api.py re-export layer](#m5-middle-man-apipy-re-export-layer)
  - [M6: Data Clumps; _build_archival_*_summary family](#m6-data-clumps-_build_archival_summary-family)
  - [M7: Long Function; orchestrator_daemon.py orchestrator_loop (300+ lines)](#m7-long-function-orchestrator_daemonpy-orchestrator_loop-300-lines)
  - [M8: Long Function; worker_daemon.py worker_loop (500+ lines)](#m8-long-function-worker_daemonpy-worker_loop-500-lines)
- [Low-Impact Findings](#low-impact-findings)
  - [L1: Duplicated Code; list_lane_messages and list_lane_briefs near-identical structure](#l1-duplicated-code-list_lane_messages-and-list_lane_briefs-near-identical-structure)
  - [L2: Data Clumps; lane_prompt.py formatter family](#l2-data-clumps-lane_promptpy-formatter-family)
  - [L3: Long Parameter List; worker_daemon.py _record_observability (15 params)](#l3-long-parameter-list-worker_daemonpy-_record_observability-15-params)
  - [L4: Data Clumps; artifact_index.py source metadata](#l4-data-clumps-artifact_indexpy-source-metadata)
  - [L5: Feature Envy; orchestrator_daemon reaching across 5 modules](#l5-feature-envy-orchestrator_daemon-reaching-across-5-modules)
- [Architectural Observations](#architectural-observations)
- [Recommended Refactoring Sequence](#recommended-refactoring-sequence)

---

## Executive Summary

The agent-handoff-mcp package is a functional, well-tested MCP server (788 tests) that has grown organically to 21,329 Python lines across 43 files. The primary tech debt still concentrates in one monolithic module (`core.py` at 4,360 lines containing 110 top-level functions) and a shotgun-surgery pattern that makes adding new MCP tools a 4-file change.

| Category            | Count              | Highest Severity |
| ------------------- | ------------------ | ---------------- |
| Large Class         | 3 (core, cli, daemons) | High         |
| Long Function       | 8 instances (>80 lines) | High         |
| Shotgun Surgery     | 1 systemic pattern | High             |
| Long Parameter List | 3 instances (>10 params) | High        |
| Duplicated Code     | 3 patterns         | Medium           |
| Middle Man          | 1 instance         | Medium           |
| Data Clumps         | 3 groups           | Medium           |
| Feature Envy        | 1 instance         | Low              |

**Top 3 payoff refactorings:**

1. **Extract Class** on `core.py` (4,360 lines to 6-7 domain modules of ~300-900 lines each); eliminates the largest maintenance drag and unlocks independent testing
2. **Replace Conditional with Polymorphism / Introduce Parameter Object** on the tool registration pipeline (api.py + cli.py + core.py); eliminates the shotgun surgery that makes every new MCP tool a 4-file change
3. **Extract Function** on `update_review_finding` (209 lines to ~70 lines + 3 guard helpers); makes the review finding state machine comprehensible and individually testable

---

## Methodology

### Book Concepts Applied

From Fowler/Beck Chapter 3 ("Bad Smells in Code"), each smell was evaluated against the package:

- **Large Class** (Ch. 3, p. 82) -- module/class with too many responsibilities or too much code
- **Long Function** (Ch. 3, p. 73) -- functions that do too much; heuristic: >50 lines worth examining, >80 lines smell strongly
- **Long Parameter List** (Ch. 3, p. 74) -- functions taking >5 parameters where a structure would clarify
- **Duplicated Code** (Ch. 3, p. 72) -- identical structure in multiple places
- **Shotgun Surgery** (Ch. 3, p. 76) -- one conceptual change requiring edits across many modules
- **Middle Man** (Ch. 3, p. 81) -- module that mostly delegates to another
- **Data Clumps** (Ch. 3, p. 78) -- groups of data items that travel together
- **Feature Envy** (Ch. 3, p. 77) -- function accessing another module's data more than its own
- **Divergent Change** (Ch. 3, p. 76) -- one module changed for multiple unrelated reasons

### Key Refactorings Referenced

| Refactoring                            | Book Reference | Applied To         |
| -------------------------------------- | -------------- | ------------------ |
| Extract Class                          | Ch. 7, p. 182  | H1, M7, M8        |
| Extract Function                       | Ch. 6, p. 106  | H2, H3, M1, M2, M3 |
| Introduce Parameter Object             | Ch. 6, p. 140  | H5, L3            |
| Replace Conditional with Polymorphism  | Ch. 10, p. 272 | H4, H6            |
| Remove Middle Man                      | Ch. 7, p. 192  | M5                 |
| Combine Functions into Class           | Ch. 6, p. 144  | M6, L2            |
| Parameterize Function                  | Ch. 11, p. 310 | M4, L1            |
| Move Function                          | Ch. 8, p. 198  | L5                 |
| Split Phase                            | Ch. 6, p. 154  | H2, M1             |

---

## Size Inventory

### Root-Level Modules

| File             | Lines | Functions | Primary Responsibility                          |
| ---------------- | ----- | --------- | ----------------------------------------------- |
| core.py           | 4,360 | 110       | Handoff CRUD, schema, rendering, validation     |
| api.py            | 1,114 | ~50       | MCP tool registration + thin wrappers           |
| cli.py            | 935   | 3         | Argument parsing + command dispatch             |
| artifact_index.py | 685   | ~15       | FTS5 artifact search + chunk management         |
| enums.py          | 158   | 0 (enums) | Status/type enums                               |
| __init__.py       | 141   | ~5        | Package exports                                 |
| config.py         | 70    | 1         | RuntimeConfig dataclass                         |
| runtime.py        | 24    | 1         | Singleton config access                         |
| slice_decision.py | 31    | 2         | Slice decision ID parsing/validation helpers    |
| __main__.py       | 5     | 0         | CLI entrypoint                                  |
| **Subtotal**      | **7,523** |       |                                                 |

### Orchestration Core Modules

| File                        | Lines | Primary Responsibility                  |
| --------------------------- | ----- | --------------------------------------- |
| ace_metrics.py              | 1,601 | ACE metrics collection and summarizing  |
| worker_daemon.py            | 1,588 | Worker polling + review + verification  |
| orchestrator_daemon.py      | 1,230 | Orchestrator state machine              |
| lane_prompt.py              | 1,070 | Prompt construction + context budgeting |
| lane_exec.py                | 652   | Backend subprocess execution            |
| review_runner.py            | 622   | Review execution and aggregation        |
| lane_manifest.py            | 535   | Lane manifest parsing + validation      |
| orchestrator_guidance.py    | 501   | Guidance resolution                     |
| ace_reflect.py              | 500   | ACE reflection pipeline                 |
| worker_daemon_ctl.py        | 487   | Worker lifecycle management             |
| dashboard_live.py           | 390   | Live dashboard rendering                |
| review_dispatch.py          | 352   | Review routing                          |
| dashboard_tui.py            | 343   | TUI dashboard rendering                 |
| lane_config.py              | 330   | Lane configuration loading              |
| handoff_integrity_guard.py  | 320   | Pre-merge integrity checks              |
| slice_review_packet.py      | 319   | Slice review data assembly              |
| _env.py                     | 275   | Environment/bootstrap helpers           |
| review_ready.py             | 260   | Review readiness assessment             |
| backend_registry.py         | 241   | Backend registration                    |
| lane_result.py              | 238   | Worker result parsing                   |
| orchestrator_lanes.py       | 235   | Lane CRUD helpers                       |
| bootstrap_lane.py           | 170   | Lane bootstrap helpers                  |
| task_plan_parser.py         | 152   | Markdown plan parsing                   |
| generate_lane_manifest.py   | 134   | Lane manifest generation                |
| backend_adapter.py          | 119   | Backend adapter protocol                |
| handoff_guidance_summary.py | 98    | Guidance summary rendering              |
| orchestrator_helpers.py     | 74    | Misc orchestrator utilities             |
| generate_agent_config.py    | 59    | Agent config generation                 |
| orchestrator_guidance_policy.py | 44 | Policy enum                            |
| **Subtotal**                | **12,928** |                                    |

### Orchestration Adapters

| File                    | Lines | Primary Responsibility               |
| ----------------------- | ----- | ------------------------------------ |
| adapters/codex_cli.py   | 290   | Codex CLI backend adapter            |
| adapters/claude_code.py | 240   | Claude Code backend adapter          |
| adapters/local_model.py | 188   | Local model backend adapter          |
| adapters/codex_subagent.py | 160 | Codex subagent backend adapter     |
| **Subtotal**            | **878** |                                    |

### Package Total

| Scope | Files | Lines |
| ----- | ----- | ----- |
| Root-level modules | 10 | 7,523 |
| Orchestration core modules | 29 | 12,928 |
| Orchestration adapters | 4 | 878 |
| **Total** | **43** | **21,329** |

### Concentration Risk

**core.py alone is 20.4% of the total package code and contains 100% of handoff state logic.** Every MCP tool, every database query, every validation rule, and the entire CURRENT_TASK.md renderer live in this single 4,360-line module. This is the defining code smell of the package.

---

## High-Impact Findings

### H1: Large Class; core.py (4,360 lines, 110 functions)

**Smell:** Large Class (Ch. 3, p. 82)
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`
**Lines:** 4,360 total; 110 top-level public/private functions, 0 meaningful classes

**Description:** `core.py` is a god module containing at least 9 distinct responsibility areas:

1. **Schema & Migration** (~300 lines): DDL, `_apply_handoff_migrations`, `_has_column`, `_has_index`
2. **Normalization & Utilities** (~200 lines): `_normalize_optional_text`, `_coerce_string_list`, `_normalize_review_mode`, etc.
3. **Git Context Detection** (~120 lines): `_detect_git_write_context`, `_git_is_ancestor`, `_classify_commit_relation`
4. **FTS & Search** (~180 lines): `_ensure_handoff_fts`, `_backfill_handoff_fts`, `search_handoff`
5. **Markdown Rendering** (~200 lines): `_render_current_task_md`, `_format_token_suffix`, `_truncate_command`
6. **Handoff State CRUD** (~250 lines): `set_handoff_state`, `get_handoff_state`, `switch_task`, `archive_task_state`
7. **Review Findings State Machine** (~400 lines): `record_review_finding`, `update_review_finding`, guards, integrity checks
8. **Lane & Worker Coordination** (~300 lines): `upsert_worktree_lane`, `record_worker_report`, `record_lane_message`, etc.
9. **Import/Export** (~200 lines): `_import_snapshot`, `export_handoff_state`, `import_handoff_state`

Every other module in the package (`api.py`, `cli.py`, all orchestration modules) imports from this single file, creating a dependency hub.

**Applicable Refactorings:**

- **Extract Class** (Ch. 7, p. 182): Split into domain-focused modules:
  - `handoff_state.py` -- singleton state CRUD (set, get, switch, archive)
  - `review_findings.py` -- finding CRUD + guards + integrity
  - `decisions.py` -- record_decision, update_next_actions, validation
  - `lanes.py` -- lane CRUD, worker reports, lane messages
  - `rendering.py` -- CURRENT_TASK.md rendering
  - `import_export.py` -- snapshot collection, import, export
  - `schema.py` -- DDL, migrations, FTS setup
  - `core.py` -- shared handoff CRUD helpers, DB connection, normalization, git context (reduced to ~500 lines and still compliant with `rg-013`)
- **Preserve Whole Object** (Ch. 11, p. 319): Functions like `_resolve_write_actor` return 7-element tuples that callers unpack; return a `WriteContext` dataclass instead.

**Risk:** HIGH. The monolithic structure means any change to any tool risks side effects across unrelated tools. Test navigation is also affected; finding relevant tests for a specific tool requires scanning the entire 3,100-line test file.

**Estimated effort:** Large (multi-session refactoring with Extract Class). Can be parallelized across concern areas since they have clear boundaries.

---

### H2: Long Function; update_review_finding (209 lines)

**Smell:** Long Function (Ch. 3, p. 73)
**File:** `core.py`, `update_review_finding` function
**Lines:** ~209

**Description:** This function contains four distinct responsibilities interleaved:

1. **Input validation** (~30 lines): normalize IDs, check status, validate lengths
2. **Reopen escalation guard** (~20 lines): check `reopen_count >= threshold`, require evidence
3. **Batch-close detection guard** (~25 lines): count recent fixes in time window, block rapid closures
4. **Commit relation guard** (~50 lines): classify commit relation, enforce descendant-ack rules with `verified_commit_sha`
5. **UPDATE execution + response** (~30 lines)

The guards are individually testable policies but are deeply nested inside one function, making them hard to test in isolation.

**Applicable Refactorings:**

- **Extract Function** (Ch. 6, p. 106): Extract three guard functions:
  - `_check_reopen_escalation_guard(existing, verification_evidence) -> dict | None`
  - `_check_batch_close_guard(conn, task_ref, existing_id) -> dict | None`
  - `_check_commit_relation_guard(existing, commit_sha, verified_commit_sha, branch, resolution_notes) -> dict | None`
- **Split Phase** (Ch. 6, p. 154): Separate validation phase (returns error dict or None) from execution phase (UPDATE + response).

**Risk:** HIGH. The function's guard logic has had bugs in the past (batch-close timing issues, commit relation edge cases). Extracting guards makes each independently testable.

---

### H3: Long Function; _import_snapshot (130 lines)

**Smell:** Long Function (Ch. 3, p. 73) + Duplicated Code (Ch. 3, p. 72)
**File:** `core.py`, `_import_snapshot` function
**Lines:** ~130

**Description:** This function iterates over 10 different table types (blockers, actions, decisions, tests, findings, lanes, reports, messages, plan_cursors, turn_metrics), each with a nearly identical pattern:

```python
for row in items:
    agent, branch, commit_sha, ... = _resolve_import_row_actor(row, ...)
    conn.execute("INSERT INTO <table> (...) VALUES (...)", (...))
```

The INSERT statements vary only in column names and field mappings. The function is essentially 10 copies of the same pattern with different column lists.

**Applicable Refactorings:**

- **Extract Function** (Ch. 6, p. 106): Extract a per-table import helper:
  - `_import_blockers(conn, task_ref, rows, defaults)`
  - `_import_decisions(conn, task_ref, rows, defaults)`
  - etc.
- **Parameterize Function** (Ch. 11, p. 310): Define table-specific column mappings as data (list of `(column_name, row_key, default_value)` tuples) and use a single generic inserter for the simpler tables.

**Risk:** MEDIUM. The function works and is exercised by import tests, but its length makes it fragile when new columns are added to any table (a change must update this function even though it conceptually belongs to the table's domain).

---

### H4: Shotgun Surgery; adding a new MCP tool requires 4 files

**Smell:** Shotgun Surgery (Ch. 3, p. 76)
**Files:** `core.py`, `api.py`, `cli.py`

**Description:** Adding a new MCP tool (e.g., a hypothetical `list_decisions`) requires coordinated changes in:

| Step | File    | Change                                        | Lines |
| ---- | ------- | --------------------------------------------- | ----- |
| 1    | core.py | Implement the function with SQL + validation   | 30-80 |
| 2    | api.py  | Add thin wrapper OR re-export the function     | 5-20  |
| 3    | api.py  | Register the tool in `build_handoff_mcp()`     | 5-10  |
| 4    | cli.py  | Add subparser in `_build_parser()` (~20 lines) | 20    |
| 5    | cli.py  | Add if/elif handler in `main()` (~5 lines)     | 5     |

That is 5 coordinated edits across 3 files for every new tool. Removing a tool requires the same 5-point reverse process. This is the textbook definition of shotgun surgery.

**Applicable Refactorings:**

- **Replace Conditional with Polymorphism** (Ch. 10, p. 272): Replace the if/elif chain in `main()` with a command registry that maps tool names to handler functions.
- **Introduce Parameter Object** (Ch. 6, p. 140): Define tool metadata (name, arguments, handler, description) as a data structure that drives both `build_handoff_mcp()` tool registration and CLI argument parsing.
- Alternatively, adopt a decorator-based pattern: each tool function declares its own CLI arguments and MCP schema via decorators, and a single registry loop wires everything.

**Risk:** HIGH friction. Every new tool is a known multi-file change. This is the most common change type in this package and the most error-prone due to coordination.

---

### H5: Long Parameter List; record_turn_metric (22 params)

**Smell:** Long Parameter List (Ch. 3, p. 74)
**File:** `core.py`, `record_turn_metric` function
**Lines:** ~86

**Description:** This function accepts 22 parameters:

```python
def record_turn_metric(
    session, phase, backend,  # 3 context
    task_ref, lane_id,  # 2 scope
    cycle, model, thread_id, turn_id,  # 4 identity
    input_tokens, output_tokens, cached_input_tokens,
    reasoning_output_tokens, total_tokens,  # 5 token fields
    usage_source,  # 1 source
    model_context_window, prompt_tokens, prompt_chars,
    prompt_token_source,  # 4 prompt fields
    utilization_ratio, domain_signal_ratio, pressure_level,  # 3 analytics
    attribution, section_sizes, raw_usage,  # 3 JSON payloads
    actor,  # 1 actor
)
```

This parameter list contains at least 3 cohesive groups that should be typed objects.

**Applicable Refactorings:**

- **Introduce Parameter Object** (Ch. 6, p. 140): Create dataclasses:
  - `TokenUsage(input_tokens, output_tokens, cached_input_tokens, reasoning_output_tokens, total_tokens, usage_source)`
  - `PromptMetrics(model_context_window, prompt_tokens, prompt_chars, prompt_token_source, utilization_ratio, domain_signal_ratio, pressure_level)`
  - These reduce the parameter list from 22 to ~10.

**Risk:** MEDIUM. The wide parameter list makes callers error-prone (positional argument mistakes, forgotten fields). Typed objects also enable validation at construction time.

---

### H6: Large Class; cli.py main() 483-line if/elif chain

**Smell:** Large Class (Ch. 3, p. 82) + Repeated Switches (Ch. 3, p. 79)
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`
**Lines:** `_build_parser()` ~379 lines; `main()` ~483 lines

**Description:** The CLI module contains two mega-functions:

1. `_build_parser()` (~379 lines): Creates 40+ subparsers. Each subparser setup repeats the same argument patterns (`--task-ref`, `--lane-id`, `--session`) 20+ times.
2. `main()` (~483 lines): A sequential if/elif chain with 40+ branches, one per command. Each branch unpacks args and calls the corresponding api.py function.

This is the textbook Repeated Switches smell from Fowler Ch. 3: the same dispatch logic (match command name to handler) appears implicitly in the parallel structures of `_build_parser()` and `main()`.

**Applicable Refactorings:**

- **Replace Conditional with Polymorphism** (Ch. 10, p. 272): Replace the if/elif chain with a command registry:
  ```python
  COMMANDS = {
      "set": {"handler": api.set_handoff_state, "args": [task_ref_arg, objective_arg, ...]},
      "get": {"handler": api.get_handoff_state, "args": [task_ref_arg, ...]},
  }
  ```
- **Extract Function** (Ch. 6, p. 106): Factor out common argument groups:
  - `_add_task_ref_arg(parser)` -- shared by 35+ subparsers
  - `_add_lane_args(parser)` -- shared by 10+ subparsers
  - `_add_actor_args(parser)` -- shared by all write commands

**Risk:** MEDIUM. The if/elif chain works but grows linearly with tool count. Each new tool adds ~20 lines to `_build_parser()` and ~5 lines to `main()`.

---

## Medium-Impact Findings

### M1: Long Function; _render_current_task_md (169 lines)

**Smell:** Long Function (Ch. 3, p. 73)
**File:** `core.py`, `_render_current_task_md` function
**Lines:** ~169

**Description:** This function builds the CURRENT_TASK.md document from a state dict. It renders 8+ sections (Objective, Focus, Active Status, Latest Decision, Open Blockers, Pending Actions, Recent Decisions, Latest Tests, Open Findings, Lane Status, Token Tallies). Each section follows the same pattern: check if data exists, format items, append to lines list.

The function defines two nested closures (`_decision_line`, `_truncate_command`) and uses a loop-driven section renderer for 4 sections. While readable, the length pushes the limits. Adding a new section (like the recently added "Current Focus") requires modifying this single function.

**Applicable Refactorings:**

- **Extract Function** (Ch. 6, p. 106): Extract per-section renderers:
  - `_render_objective_section(active)` -> `list[str]`
  - `_render_findings_section(findings)` -> `list[str]`
  - `_render_token_summary_section(turn_metrics)` -> `list[str]`

---

### M2: Long Function; handoff_close_check (116 lines)

**Smell:** Long Function (Ch. 3, p. 73)
**File:** `core.py`, `handoff_close_check` function
**Lines:** ~116

**Description:** Performs 8 independent validation checks (active task match, status=done, open blockers, pending actions, open findings, review integrity, write provenance, CURRENT_TASK.md sync), each building a sub-dict in the response payload. The checks are independent and could be composed from smaller functions.

**Applicable Refactorings:**

- **Extract Function** (Ch. 6, p. 106): Each check becomes a callable that returns a `(name, check_result, failure_message | None)` tuple. The main function composes them.

---

### M3: Long Function; upsert_plan_cursor (142 lines)

**Smell:** Long Function (Ch. 3, p. 73)
**File:** `core.py`, `upsert_plan_cursor` function
**Lines:** ~142

**Description:** Mixes three concerns: (1) input normalization, (2) `require_clean_slice` gate checking (open HIGH findings + fresh test counts), (3) INSERT or UPDATE SQL execution. The gate logic (~40 lines) is an independent policy that could be extracted.

**Applicable Refactorings:**

- **Extract Function** (Ch. 6, p. 106): Extract `_evaluate_clean_slice_gate(conn, task_ref, lane_id, since) -> dict | None`

---

### M4: Duplicated Code; list pagination boilerplate

**Smell:** Duplicated Code (Ch. 3, p. 72)
**File:** `core.py`, across 6+ list functions

**Description:** Functions `list_plan_cursors`, `list_lane_messages`, `list_lane_briefs`, `list_worker_reports`, `list_review_findings`, `list_turn_metrics` all share the same boilerplate pattern:

```python
limit = max(1, limit)
offset = max(0, offset)
# ... build WHERE clause from optional filters ...
total = conn.execute(f"SELECT COUNT(*) ...").fetchone()["count"]
rows = conn.execute(f"SELECT * ... LIMIT ? OFFSET ?", ...).fetchall()
return _json_response({
    "ok": True,
    "total_matching": total,
    "returned": len(rows),
    "has_more": offset + len(rows) < total,
    ...
})
```

This pattern appears 6+ times with minor variations (different table names, filters, row decoders).

**Applicable Refactorings:**

- **Parameterize Function** (Ch. 11, p. 310): Extract a generic paginated query helper:
  ```python
  def _paginated_query(conn, table, where_sql, params, limit, offset, row_decoder=dict) -> dict
  ```

---

### M5: Middle Man; api.py re-export layer

**Smell:** Middle Man (Ch. 3, p. 81)
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`
**Lines:** ~60 lines of pure re-exports (lines 25-60)

**Description:** The first ~60 lines of `api.py` are direct re-exports of `core.py` functions:

```python
from .core import set_handoff_state
from .core import get_handoff_state
from .core import record_decision
...
```

These re-exports add no behavior, no argument transformation, and no error handling. They exist solely so that `cli.py` can `import api` instead of `import core`. The MCP tool registration in `build_handoff_mcp()` is the only value `api.py` adds beyond re-exports.

**Applicable Refactorings:**

- **Remove Middle Man** (Ch. 7, p. 192): Keep `core.py` focused on handoff-state CRUD per `rg-013`, and either (a) have `cli.py` import the CRUD functions it needs directly while leaving MCP registration in `api.py`, or (b) extract MCP registration into a dedicated `mcp_registry.py`.
- Alternatively, if `api.py` is kept, it should add value (validation, response shaping, auth) rather than being a pass-through.

---

### M6: Data Clumps; _build_archival_*_summary family

**Smell:** Data Clumps (Ch. 3, p. 78)
**File:** `core.py`, 5 functions (lines ~1640-1760)

**Description:** Five functions (`_build_archival_decision_summary`, `_build_archival_report_summary`, `_build_archival_test_summary`, `_build_archival_message_summary`, `_build_archival_lane_activity_summary`) all take the same parameter group: `(conn, *, task_ref, lane_id)`. They follow the same pattern (query -> aggregate -> return dict). The composite function `_build_archival_lane_activity_summary` simply calls the other four.

**Applicable Refactorings:**

- **Combine Functions into Class** (Ch. 6, p. 144): Create an `ArchivalSummaryBuilder` class that holds `conn`, `task_ref`, `lane_id` as instance state and exposes `decisions()`, `reports()`, `tests()`, `messages()`, `full()` methods.

---

### M7: Long Function; orchestrator_daemon.py orchestrator_loop (300+ lines)

**Smell:** Long Function (Ch. 3, p. 73) + Divergent Change (Ch. 3, p. 76)
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/orchestrator_daemon.py`
**Lines:** ~300+

**Description:** `orchestrator_loop()` is a 300+ line while loop managing 5 independent subsystems: dispatch, guidance resolution, plan dispatch, worker management, and lane intake. Modifying any one subsystem requires understanding the entire loop.

**Applicable Refactorings:**

- **Extract Class** (Ch. 7, p. 182): Create phase objects (`DispatchPhase`, `GuidancePhase`, `IntakePhase`) that the loop orchestrates via a common interface.
- **Extract Function** (Ch. 6, p. 106): At minimum, extract each phase as a standalone function that receives a shared context object.

---

### M8: Long Function; worker_daemon.py worker_loop (500+ lines)

**Smell:** Long Function (Ch. 3, p. 73) + Long Parameter List (Ch. 3, p. 74)
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`
**Lines:** ~500+; `worker_loop` takes 14 parameters

**Description:** `worker_loop()` is a 500-line while loop managing poll, execute, review, verify, and handoff phases. It also takes 14 parameters (`orchestrator_root`, `task_ref`, `lane_id`, `session`, `worktree_path`, `max_review_cycles`, `poll_interval`, `single_pass`, `backend`, `session_mode`, `reasoning_effort`, `model`, `codex_bin`, `codex_args`).

**Applicable Refactorings:**

- **Introduce Parameter Object** (Ch. 6, p. 140): Create `WorkerConfig` dataclass grouping the 14 parameters.
- **Extract Class** (Ch. 7, p. 182): Break phases into `ExecutionPhase`, `ReviewPhase`, `VerificationPhase` classes.

---

## Low-Impact Findings

### L1: Duplicated Code; list_lane_messages and list_lane_briefs near-identical structure

**Smell:** Duplicated Code (Ch. 3, p. 72)
**File:** `core.py`, `list_lane_messages` (~29 lines) and `list_lane_briefs` (~28 lines)

**Description:** These two functions share ~90% of their structure. `list_lane_briefs` is essentially `list_lane_messages` with a fixed `direction = "orchestrator_to_worker"` filter and a `subject LIKE "brief:%"` condition. The pagination, validation, and response formatting are identical.

**Applicable Refactorings:**

- **Parameterize Function** (Ch. 11, p. 310): Make `list_lane_messages` accept optional `direction` and `subject_prefix` filters; `list_lane_briefs` becomes a thin wrapper.

---

### L2: Data Clumps; lane_prompt.py formatter family

**Smell:** Data Clumps (Ch. 3, p. 78) + Duplicated Code (Ch. 3, p. 72)
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py`
**Lines:** ~42 functions, many following the same `_format_*()` pattern

**Description:** Functions like `_format_message()`, `_format_action()`, `_format_blocker()`, `_format_finding()`, `_format_test()` all follow the pattern: extract ID, extract status, format description into a string line. The common structure could be generalized.

**Applicable Refactorings:**

- **Combine Functions into Class** (Ch. 6, p. 144): Create a `PromptFormatter` class with a generic `format_row(kind, row)` method and kind-specific overrides for extra fields.

---

### L3: Long Parameter List; worker_daemon.py _record_observability (15 params)

**Smell:** Long Parameter List (Ch. 3, p. 74)
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`
**Lines:** `_record_observability()` takes 15 parameters

**Description:** Many of these parameters are observability-specific (cycle, phase, backend, model, requested_reasoning_effort, effective_reasoning_effort, telemetry, context_utilization). They form a natural `ObservabilityContext` object.

**Applicable Refactorings:**

- **Introduce Parameter Object** (Ch. 6, p. 140): Create `ObservabilityContext` dataclass.

---

### L4: Data Clumps; artifact_index.py source metadata

**Smell:** Data Clumps (Ch. 3, p. 78)
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/artifact_index.py`
**Lines:** ~685

**Description:** Artifact source metadata (`source_id`, `source_label`, `content_type`, `metadata_json`) appears across `upsert_source`, `search_artifacts`, `get_artifact_source`, `list_artifact_sources`, `purge_artifacts` as raw dict access. A `ArtifactSource` dataclass would centralize validation.

**Applicable Refactorings:**

- **Replace Primitive with Object** (Ch. 6, p. 174): Introduce `ArtifactSource` dataclass.

---

### L5: Feature Envy; orchestrator_daemon reaching across 5 modules

**Smell:** Feature Envy (Ch. 3, p. 77)
**File:** `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/orchestrator_daemon.py`

**Description:** `orchestrator_loop()` imports and calls functions from 5+ peer modules: `core.*`, `lane_manifest.*`, `task_plan_parser.*`, `orchestrator_lanes.*`, `orchestrator_guidance.*`. It accesses their internal data structures (manifest dicts, plan item dicts) rather than delegating decisions to those modules.

**Applicable Refactorings:**

- **Move Function** (Ch. 8, p. 198): Move data transformation logic to the modules that own the data.
- Introduce an `OrchestrationContext` facade that encapsulates cross-module state.

---

## Architectural Observations

### 1. Pure Functions Returning JSON Strings

Every public function in `core.py` returns `str` (a JSON-serialized response). This means:
- Internal callers (orchestration modules) must `json.loads()` the response to extract data.
- Error handling is via checking `result["ok"]` after parsing, rather than exceptions.
- This is appropriate for the MCP transport layer but creates overhead for internal consumption.

**Observation:** If core.py is split (H1), the extracted modules could expose typed returns internally while the MCP-facing layer remains JSON-string.

### 2. Well-Extracted Enum Layer

The `enums.py` module (158 lines) centralizes all status/type enums with proper StrEnum/IntEnum. This follows the project's sr-007 rule and is a positive architectural pattern. The frozenset constants in core.py (`HANDOFF_ACTIVE_STATUSES`, `REVIEW_FINDING_STATUSES`, etc.) built from these enums are a good validation surface.

### 3. The _resolve_write_actor Pattern

Every write function in `core.py` unpacks a 7-tuple from `_resolve_write_actor`:
```python
agent, branch, commit_sha, lane_id, model, model_label, reasoning_level = _resolve_write_actor(conn, actor)
```

This is a classic **Preserve Whole Object** (Ch. 11, p. 319) opportunity. A `ResolvedWriteContext` dataclass would eliminate the 7-element unpacking that appears 15+ times.

### 4. Orchestration Modules Are Well-Decomposed

Unlike `core.py`, the `orchestration/` subpackage has reasonable decomposition: `lane_exec.py`, `review_runner.py`, `slice_review_packet.py` each have focused responsibilities. The main concerns are the two daemon loops (`orchestrator_loop` at 300+ lines, `worker_loop` at 500+ lines), which are inherently complex state machines but would still benefit from phase extraction.

### 5. Test Coverage Strength

The package has 788 tests, providing a strong safety net for refactoring. The test suite itself is concentrated in two files (`test_handoff_state.py` at ~3,100+ lines and `test_review_findings.py`), which would benefit from splitting alongside `core.py`.

---

## Recommended Refactoring Sequence

Ordered by payoff and safety. Each phase can be completed independently. All phases benefit from the existing 788-test safety net.

### Phase 1: Extract Guards from update_review_finding (H2)

**Scope:** `core.py` only
**Effort:** Small
**Risk:** Low (behavior-preserving; tests cover all guard paths)

Extract three guard functions from `update_review_finding`:
1. `_check_reopen_escalation_guard()`
2. `_check_batch_close_guard()`
3. `_check_commit_relation_guard()`

This reduces `update_review_finding` from ~209 lines to ~70 lines and makes each guard independently testable. The guards are already logically separated by comments.

### Phase 2: Introduce Parameter Objects (H5, L3)

**Scope:** `core.py`, `worker_daemon.py`
**Effort:** Small-Medium
**Risk:** Low

1. Create `TokenUsage` and `PromptMetrics` dataclasses for `record_turn_metric` (22 -> ~10 params).
2. Create `ResolvedWriteContext` dataclass to replace the 7-tuple from `_resolve_write_actor` (eliminates 15+ unpacking sites).
3. Create `WorkerConfig` for `worker_loop` (14 -> 1 config param + 2-3 state params).

### Phase 3: Extract Pagination Helper (M4)

**Scope:** `core.py`
**Effort:** Small
**Risk:** Low

Extract the repeated pagination boilerplate into `_paginated_query()`. Apply to 6+ list functions. Direct line reduction: ~120 lines.

### Phase 4: Extract core.py into Domain Modules (H1)

**Scope:** Major restructuring
**Effort:** Large
**Risk:** Medium (requires updating all imports; safe with grep + test suite)

Split `core.py` into 6-7 focused modules. Suggested extraction order:
1. `schema.py` (DDL, migrations, FTS setup) -- standalone, no callers to update
2. `rendering.py` (CURRENT_TASK.md) -- single caller in each write function
3. `import_export.py` (snapshot, import, export) -- used by 2-3 callers
4. `review_findings.py` -- self-contained state machine
5. `lanes.py` -- lane CRUD, worker reports, messages
6. `handoff_state.py` -- singleton state CRUD

Keep `core.py` as a ~500-line handoff helper module (DB connection, normalization, write actor resolution, git-context helpers) without moving MCP registration or orchestration concerns into it, preserving `rg-013`.

### Phase 5: Tool Registration Pipeline (H4, H6)

**Scope:** `packages/agent-handoff-mcp/` — `api.py`, `cli.py`
**Effort:** Medium
**Risk:** Medium (CLI interface changes require careful backward compatibility)

> **Note (post-E12-5):** `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` (921 lines, created by E12-5) has the same H4 tool-registration pattern at comparable scale. Phase 5 should assess and remediate both packages simultaneously, or explicitly defer the orchestrator package as Phase 5b.

1. Define a tool registry data structure mapping tool names to handlers, argument specs, and descriptions.
2. Generate both `build_handoff_mcp()` registrations and CLI subparsers from the same registry.
3. Replace the 483-line if/elif in `main()` with a registry lookup.

### Phase 6: Daemon Loop Decomposition (M7, M8)

**Scope:** `orchestrator_daemon.py`, `worker_daemon.py`
**Effort:** Medium-Large
**Risk:** Medium (state machine refactoring requires careful integration testing)

Extract loop phases into phase classes or standalone functions with a shared context object. This is lower priority because the daemons are operationally stable and change less frequently than the core CRUD tools.
