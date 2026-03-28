# Selective Memory and Evaluation Metrics Hardening

## Objective

Finish the remaining in-scope work from Phase 4 (3 unchecked items) and Phase 5 (4 unchecked items) of the agentic process-hardening epic. When complete, the epic should have no remaining active implementation items outside confirmed post-v0.3.0 deferrals.

## Problem Statement

Phase 4 has three open implementation items: (1) no structured progress/error/status semantics for process automation surfaces; status values are inline string literals in SQLite CHECK constraints with no Python-side enum types, (2) handoff actor provenance lacks a centralized builder; callers construct `WriteActor` dicts inline despite `_resolve_write_actor()` existing, and (3) no selective-memory MCP surfaces for archival summaries or lane-activity compression. Phase 5 has four open items for evaluation metrics and review loops that have no derivation paths defined.

Critically, `get_handoff_state()` in core.py already accepts configurable `top_n_*` parameters and IS the active-task brief surface. A separate "active-brief" tool would duplicate it. The real gaps are: (a) lane-activity compression for archival, (b) status enum consolidation, (c) actor-construction helper, and (d) metrics with concrete derivation paths from existing DB schema.

## Constraints

- Additive changes only to `agent-handoff-mcp`; existing MCP callers must not break.
- No second memory system; build on existing handoff DB + artifact store.
- Deferred post-v0.3.0 items stay in `docs/deferred-features/`. Three items confirmed deferred by decision #887: Deep MCP Productization, TUI Monitoring Follow-On, Repo-Wide Model-Quality Eval.
- Metrics that cannot be derived from existing DB schema must be explicitly narrowed, not faked with heuristics.

## Workflow Principles

- Each slice produces behavior plus proof; no scaffold-only slices.
- Derive metrics from existing DB tables before proposing schema extensions.
- Document what is NOT measurable as clearly as what is.

## Terminology

- **Active-task brief**: The existing `get_handoff_state` output with appropriate `top_n_*` limits. Not a new surface.
- **Archival summary**: A compressed, retrieval-friendly response format of `get_lane_activity` suitable for storing before archival. Not a separate tool or function.
- **Planning drift**: Ratio of dispatched plan items (via `plan_cursors`) that reached `completed` or `skipped` vs. total dispatched, within an evaluation window.
- **WriteActor**: `TypedDict` (defined in `core.py` near the status-set constants) with fields `agent`, `branch`, `commit_sha`, `lane_id`.

## Current State Analysis

- Phase 4 has three unchecked items:
  1. "Define structured progress, error, and status semantics" -- status values are inline string sets (`HANDOFF_ACTIVE_STATUSES`, `REVIEW_FINDING_STATUSES`, etc. near the top of core.py) and SQLite CHECK constraints. Worker JSONL event names (`cycle_start`, `exec_complete`, etc.) are free-form strings.
  2. "Normalize handoff actor provenance" -- `WriteActor` TypedDict and `_resolve_write_actor()` exist, but no public `build_write_actor()` factory for callers. The provenance integrity validator validates post-hoc but callers still build dicts inline.
  3. "Add selective-memory MCP surfaces" -- `get_handoff_state` already serves as active-task brief with configurable limits. Missing: lane-activity compression helper, retention rules documentation. `archive_task_state()` and `purge_artifacts()` exist but have no documented retention policy.
- Phase 5 has four unchecked items. The `build_snapshot()` function in ace_metrics.py has 8 sections (token_burn, context_pressure, fts5_retrieval, lane_health, process_health, handoff_memory, phase_timing, ace_documentation). The missing metrics are:
  - `planning_drift`: derivable from `plan_cursors` table (dispatched vs completed/skipped ratio)
  - `stale_artifact_rate`: derivable from `artifact_sources.created_at`/`updated_at` timestamps
  - `archive_rate`: derivable from `task_archives.archived_at` timestamps
  - `ctx7_adoption`: derivable by scanning `decisions.rationale` for "ctx7 library id:" prefix
  - `runtime_parity`: NOT directly derivable; no `test_kind` column on `verified_tests`
  - `performance_evidence`: NOT directly derivable; no structured field linking tests to perf benchmarks
  - `resolved_from_hot_state`: NOT derivable; DB does not record agent retrieval strategy

## Target Outcome

Status values consolidated as Python StrEnums. Actor construction centralized. Lane-activity compression helper available for archival workflows. ACE metrics snapshot covers planning drift, artifact staleness, archive rate, and ctx7 adoption. Metrics that require DB schema extensions or agent telemetry are explicitly documented as future instrumentation work, not faked. Epic checklist fully resolved with no active/deferred ambiguity.

## Context Loading

- Rules: `docs/agentic/instructions.md`, `docs/agentic/rules/development-workflow.md`
- Contracts: `docs/agentic/contracts/agent-handoff-mcp.md`
- Handoff/MCP state: task ref `agentic-development-process-hardening-epic`; load recent decisions from MCP handoff (do not hardcode decision ID ranges)
- Prior review findings: load current open findings from MCP handoff for `agentic-development-process-hardening-epic`; do not hardcode finding IDs in the plan
- External docs via `ctx7` only if: StrEnum backward compatibility or SQLite FTS5 behavior needs verification

## Contract and Boundary Impact

| Boundary                    | Owner           | Current Contract                                                  | Expected Change                                                                             | Compatibility Needed?                                     | Verification                          |
| --------------------------- | --------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------- |
| Status enums + actor helper | agentic-tooling | `docs/agentic/contracts/agent-handoff-mcp.md`                     | Add `enums.py` module; add public `build_write_actor()` factory                             | Yes; existing string values preserved as StrEnum `.value` | pytest + mypy                         |
| Lane-activity summary       | agentic-tooling | `docs/agentic/contracts/agent-handoff-mcp.md`                     | Add archival compression preset over existing `get_lane_activity`; document retention rules | Yes; additive response format on existing tool            | pytest + contract doc                 |
| ACE metrics snapshot        | agentic-tooling | `docs/agentic/contracts/agent-handoff-mcp.md`                     | Add `planning_drift`, `stale_artifact_rate`, `archive_rate`, `ctx7_adoption` sections       | Yes; existing snapshot keys preserved                     | `test_ace_metrics.py` + live snapshot |
| Epic/deferred sync          | agentic-tooling | `docs/epics/v0.3.0/agentic-development-process-hardening-epic.md` | Check all remaining items or defer with rationale                                           | No; docs-only                                             | manual consistency review             |

## Proposed Solution

Land the remaining work in four slices. First, consolidate status values as StrEnums with a public actor-construction helper (Phase 4 items 1-2). Second, add lane-activity compression and document retention rules (Phase 4 item 3). Third, add the derivable ACE metrics with concrete data-source paths (Phase 5 items 1, 3). Fourth, define the data-pattern review loop, narrow the ctx7 deliverable, and close out the epic (Phase 5 items 2, 4).

## Files and Surfaces to Change

| Surface  | File                                                                            | Change                                                                                                                                                                                              |
| -------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/enums.py`                     | New module; StrEnum types for all status domains (HandoffStatus, BlockerStatus, ActionStatus, FindingStatus, FindingSeverity, ReviewMode, LaneStatus, ReportStatus, MessageStatus, PlanCursorState) |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`                      | Replace inline `*_STATUSES` sets with enum references; add public `build_write_actor()` factory; extend `get_lane_activity()` with archival format                                                  |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`                       | No direct changes needed; bare alias `= core.get_lane_activity` auto-inherits the updated core.py signature via MCP auto-schema generation                                                          |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_metrics.py` | Add `_planning_drift()`, `_stale_artifact_metrics()`, `_archive_rate()`, `_ctx7_adoption()` collectors                                                                                              |
| test     | `packages/agent-handoff-mcp/tests/test_enums.py`                                | New; enum round-trip and string-value parity tests                                                                                                                                                  |
| test     | `packages/agent-handoff-mcp/tests/test_ace_metrics.py`                          | Extend with new metric collector tests                                                                                                                                                              |
| contract | `docs/agentic/contracts/agent-handoff-mcp.md`                                   | Document retention rules, new metric keys, narrowed scope for non-derivable metrics                                                                                                                 |
| rules    | `docs/agentic/instructions.md`                                                  | Add data-pattern/latency review loop; update ctx7 evaluation language                                                                                                                               |
| docs     | `docs/epics/v0.3.0/agentic-development-process-hardening-epic.md`               | Remove active/deferred ambiguity after implementation                                                                                                                                               |
| docs     | `docs/deferred-features/agentic-process-hardening-post-v0.3.0.md`               | Hold true deferred backlog items from this epic                                                                                                                                                     |

## Related Files

| File                                                                             | Note                                                                             |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_reflect.py`  | Existing strategy bullet evolution; should stay aligned with new evaluation loop |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_ready.py` | Boundary/evidence semantics source                                               |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_exec.py`    | `_compress_large_result_details()` is an existing compression pattern            |
| `packages/agent-handoff-mcp/README.md`                                           | Must stay in sync with new MCP surfaces                                          |
| `docs/deferred-features/agentic-process-hardening-post-v0.3.0.md`                | Already indexes 3 confirmed deferred items (decision #887)                       |

## Verification Strategy

- Deterministic tests:
  - `make test-handoff` (runs the full MCP test suite from monorepo root; executes `PYTHONPATH="$(MCP_PYTHONPATH)" $(PYTHON) -m pytest packages/agent-handoff-mcp/tests -q`)
  - For focused runs, replicate the same environment manually: `PYTHONPATH="packages/agent-handoff-mcp/src:packages/codex-subagent-bridge/src" python -m pytest packages/agent-handoff-mcp/tests/test_enums.py -q` (the Makefile target does not accept a `PYTEST_ARGS` override; focused runs must invoke pytest directly with the same `PYTHONPATH`)
- Type checking:
  - `make test-handoff` runs pytest only; it does not include mypy. For standalone type checking: `PYTHONPATH="packages/agent-handoff-mcp/src:packages/codex-subagent-bridge/src" python -m mypy packages/agent-handoff-mcp/src/agent_handoff_mcp/ --ignore-missing-imports`
- Contract/fixture verification:
  - Verify `docs/agentic/contracts/agent-handoff-mcp.md` documents all new metric keys and retention rules
- Doc consistency:
  - grep-verify every MCP tool, file path, and rule anchor referenced in Slice 3/4 guidance actually exists

## Slice Delivery

### Slice 1: Status Enum Consolidation and Actor Helper

**Goal**: Replace inline string sets with Python StrEnums and add a public `build_write_actor()` factory so callers stop constructing `WriteActor` dicts ad hoc.

Changes:

- Create `packages/agent-handoff-mcp/src/agent_handoff_mcp/enums.py` with StrEnum types for every status domain currently enforced by SQLite CHECK constraints:
  - `HandoffStatus`: `in_progress`, `blocked`, `review`, `done`
  - `BlockerStatus`: `open`, `resolved`
  - `ActionStatus`: `pending`, `done`, `skipped`
  - `FindingStatus`: `open`, `fixed`, `wontfix`, `deferred`
  - `FindingSeverity`: `high`, `medium`, `low`
  - `ReviewMode`: `branch`, `release_audit`
  - `LaneStatus`: `planned`, `active`, `blocked`, `review`, `merged`, `closed`
  - `ReportStatus`: `submitted`, `acknowledged`, `superseded`
  - `MessageStatus`: `open`, `acknowledged`, `closed`
  - `PlanCursorState`: `dispatched`, `completed`, `skipped`, `escalated`
- Replace `HANDOFF_ACTIVE_STATUSES`, `REVIEW_FINDING_STATUSES`, `REVIEW_FINDING_SEVERITIES`, `REVIEW_MODES` status sets in core.py with references to the new enums
- Add a public `build_write_actor(agent=None, branch=None, commit_sha=None, lane_id=None)` factory in core.py as a simple dict constructor that returns a `WriteActor` from explicit args. This does NOT wrap the internal `_resolve_write_actor()` DB-lookup cascade; callers who want auto-resolution (git detection, env fallback) continue using the internal path implicitly through MCP write operations
- Add `tests/test_enums.py` with: enum string-value parity against CHECK constraints, round-trip serialization, `build_write_actor()` happy path and fallback behavior

Proof:

- `pytest tests/test_enums.py` passes
- `mypy` clean on `enums.py` and `core.py`
- Existing test suite still passes (no regressions from set-to-enum migration)

### Slice 2: Lane-Activity Archival Compression and Retention Rules

**Goal**: Add an archival compression response format to the existing `get_lane_activity` tool and document retention rules for artifacts and task archives. `get_lane_activity` already owns the lane-scoped summary boundary; the archival format is an additive preset, not a separate helper.

Changes:

- Extend `get_lane_activity(lane_id, task_ref=None, ...)` with an optional `format` parameter (default: `full`, new: `archival`):
  - `archival` format returns a compressed summary shape:
    - decision count + most recent decision rationale excerpt
    - finding counts by status (open/fixed/wontfix/deferred)
    - worker report count + latest merge_ready status
    - message count by direction and status
    - total verified tests + pass rate
  - Pattern after `_compress_large_result_details()` in lane_exec.py for compression strategy
  - Existing `full` format unchanged (backward compatible)
- Document retention rules in contract doc:
  - artifact staleness threshold (default: 30 days since last `updated_at`)
  - auto-purge behavior on `archive_task_state()`
  - relationship between `purge_artifacts()` scoping params and retention policy
- Add tests for archival format shape, empty-lane edge case, and multi-lane isolation

Proof:

- `pytest` on archival-format tests passes
- Contract doc has a "Retention Rules" section with the threshold and auto-purge semantics
- `get_lane_activity` full-format output unchanged (backward compatible)
- `get_handoff_state` remains unchanged (no active-brief duplication per SMEM-PLAN-03)

### Slice 3: Derivable ACE Metrics

**Goal**: Add the remaining evaluation signals that have concrete derivation paths from existing DB schema; explicitly narrow non-derivable metrics.

Changes:

- Add to `ace_metrics.py build_snapshot()`:
  - `_planning_drift()` section:
    - Data source: `plan_cursors` table (`state` column: dispatched/completed/skipped/escalated)
    - Derivation: `total = count(*) from plan_cursors within window; terminal = count(*) WHERE state IN ('completed', 'skipped'); drift = 1.0 - terminal / total`. The denominator is all plan_cursors rows in the window (regardless of current state), not only rows currently in `dispatched` state
    - Empty semantics: `null` when no `plan_cursors` rows exist in the window
  - `_stale_artifact_metrics()` section (note: reads from sidecar `mcp-artifacts.db`, not `handoff.db`; must open the artifact-index DB path separately, matching the access pattern in `artifact_index.py`):
    - Data source: `artifact_sources.created_at`, `artifact_sources.updated_at` from `mcp-artifacts.db`
    - Derivation: count and ratio of sources with `updated_at` older than configurable threshold (default 30 days)
    - Empty semantics: `{ "total": 0, "stale_count": 0, "stale_rate": 0.0 }`
  - `_archive_rate()` section:
    - Data source: `task_archives.archived_at` timestamps
    - Derivation: count of archives within evaluation window; mean interval between archives
    - Empty semantics: `{ "total_archives": 0, "in_window": 0 }`
  - `_ctx7_adoption()` section:
    - Data source: `decisions.rationale` text (scan for "ctx7 library id:" prefix)
    - Derivation: count of decisions referencing ctx7; count of unique library ids; reuse ratio (references / unique ids)
    - Empty semantics: `{ "decisions_with_ctx7": 0, "unique_library_ids": 0, "reuse_ratio": null }`
- Document these as NOT derivable from current schema (explicitly deferred to future instrumentation):
  - `runtime_parity`: requires `test_kind` column on `verified_tests` or structured test classification
  - `performance_evidence`: requires structured field linking test results to perf benchmarks
  - `resolved_from_hot_state`: requires agent self-reporting of retrieval strategy (new telemetry event)
- Add per-collector unit tests in `test_ace_metrics.py`

Proof:

- `pytest tests/test_ace_metrics.py` passes with new metric collectors
- Live snapshot includes the 4 new sections with correct empty/populated semantics
- Non-derivable metrics are documented in contract doc under "Deferred Instrumentation"

### Slice 4: Review Loop, ctx7 Narrowing, and Epic Sync

**Goal**: Define the data-pattern/latency review loop, narrow the ctx7 deliverable, and close out the epic checklist.

Changes:

- Add data-pattern/latency health review section to `instructions.md` periodic pruning workflow:
  - Fabricated-field incidents: scan recent findings for `ANTIPATTERN` category with field-fabrication keywords
  - Dual-write exceptions: check for boundary changes without matching contract co-change evidence
  - Queue-saturation incidents: review worker daemon logs for repeated `context_pressure` events above threshold
  - Tail-latency regressions: check `phase_timing` metrics for regression in exec/review mean/max
- Narrow ctx7 deliverable: the repo can measure ctx7 library-id reuse ratio from handoff decisions (Slice 3 `_ctx7_adoption()` metric). Token-cost reduction cannot be measured locally without a prompt-level instrumentation layer; document this boundary explicitly instead of promising a measurement.
- Update epic Phase 4 + Phase 5 checklist items:
  - Check off all 3 remaining Phase 4 items (structured semantics, actor provenance, selective-memory)
  - Check off all 4 remaining Phase 5 items (3 metrics items checked with scope narrowing documented; ctx7 narrowed to adoption metric)
- Verify deferred-features doc (decision #887) remains accurate; no new deferrals needed
- Cross-link the evaluation guidance back to existing pruning workflow and ACE metrics snapshot

Proof:

- grep-verify every MCP tool name, file path, and rule anchor referenced in new instructions.md sections exists
- Epic Phase 4 and Phase 5 checklists have no unchecked items except confirmed post-v0.3.0 deferrals
- Deferred-features doc unchanged or minimally updated (no scope creep)

---

# Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed whether external dependency context requires `ctx7`.
- [ ] Recorded boundary ownership and compatibility expectations if any contract is touched.

## Slice 1: Status Enum Consolidation and Actor Helper

- [ ] Created `enums.py` with StrEnum types for all 10 status domains.
- [ ] Replaced inline `*_STATUSES` / `*_SEVERITIES` / `*_MODES` sets in core.py with enum references.
- [ ] Added public `build_write_actor()` factory in core.py.
- [ ] Added `test_enums.py` with string-value parity, round-trip, and actor factory tests.
- [ ] `mypy` clean on changed files.
- [ ] Full test suite passes (no regressions).

## Slice 2: Lane-Activity Summary and Retention Rules

- [ ] Extended `get_lane_activity()` with `format="archival"` response preset.
- [ ] Documented retention rules (staleness threshold, auto-purge semantics) in contract doc.
- [ ] Added tests for archival format shape, empty-lane edge case, multi-lane isolation.
- [ ] Verified `get_handoff_state` unchanged (no active-brief duplication per SMEM-PLAN-03).

## Slice 3: Derivable ACE Metrics

- [ ] Added `_planning_drift()` collector with plan_cursors derivation.
- [ ] Added `_stale_artifact_metrics()` collector with artifact_sources derivation.
- [ ] Added `_archive_rate()` collector with task_archives derivation.
- [ ] Added `_ctx7_adoption()` collector with decision-keyword derivation.
- [ ] Documented non-derivable metrics (runtime_parity, performance_evidence, resolved_from_hot_state) as deferred instrumentation.
- [ ] Added per-collector unit tests.

## Slice 4: Review Loop, ctx7 Narrowing, and Epic Sync

- [ ] Added data-pattern/latency review section to instructions.md.
- [ ] Narrowed ctx7 deliverable to adoption metric; documented token-cost measurement boundary.
- [ ] Checked off all remaining Phase 4 items in epic.
- [ ] Checked off all remaining Phase 5 items in epic (with scope narrowing documented).
- [ ] Verified deferred-features doc remains accurate.

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [ ] Runtime-parity checks are included where tests can mask real behavior.
- [ ] Handoff decision records the change, verification, and any contract implications.

## Stretch Goals

- [ ] Add worker JSONL event name enums (currently free-form strings like `cycle_start`, `exec_complete`).
- [ ] Add compact markdown examples for `get_lane_activity(format="archival")` response shape in contract doc.

## Success Criteria

- [ ] All status domains use StrEnums; callers use `build_write_actor()` instead of inline dicts.
- [ ] Lane-activity archival compression available via `get_lane_activity(format="archival")`; retention rules documented in contract.
- [ ] ACE metrics snapshot covers planning_drift, stale_artifact_rate, archive_rate, ctx7_adoption.
- [ ] Non-derivable metrics explicitly documented as deferred instrumentation (not faked).
- [ ] Epic Phase 4 and Phase 5 checklists fully resolved; no active/deferred ambiguity.
