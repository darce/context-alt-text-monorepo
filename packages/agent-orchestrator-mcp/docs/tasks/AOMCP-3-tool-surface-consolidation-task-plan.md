# AOMCP-3. Orchestrator MCP Tool Surface Consolidation

> **Metadata**
>
> - **Date**: 2026-04-07 23:55 EST
> - **Author**: Claude Opus 4.6 (1M context)
> - **Project**: `agent-orchestrator-mcp`
> - **Task ID**: `AOMCP-3`
> - **Target Branch**: `feature/aomcp-3-tool-surface-consolidation`
> - **Review Coverage Target**: 2
> - **Source Assessment**: [`packages/agent-orchestrator-mcp/docs/tech-debt/tool-surface-consolidation-assessment.md`](../tech-debt/tool-surface-consolidation-assessment.md)

## Objective

Apply the AHMCP-6 discriminated-tool pattern and AHMCP-1 bounded-read shapes to
`agent-orchestrator-mcp` so that the public tool surface drops from **38 tools
to 16** (−22, ~58 %) without changing handler behavior, breaking in-repo
callers, or splitting the test surface. The work adds **six** brand-new
discriminated wrappers (`manage_worktree_lane`, `lane_communication`,
`worker_reports`, `plan_cursor`, `turn_metrics`, `manage_orchestrator`), then
**extends the existing `manage_worker`** wrapper to absorb the six dedicated
`worker_*` tools — `manage_worker` is not a new registration; it already
ships in the 38-tool baseline as a half-finished discriminator. **Twenty-eight**
legacy `ToolEntry` rows are removed across all the consolidated clusters; the
final surface is 9 untouched tools + the existing extended `manage_worker` + 6
new wrappers = 16. When complete the legacy registrations are gone, the
orchestrator README references the package-owned token-efficient guide, and
every in-repo caller and test is on the new tools.

## Problem Statement

The orchestrator MCP currently registers 38 tools across 11 clusters in
`api.py::_build_tool_registry`. The capability advertisement on every cold
start runs roughly 10 000–18 000 tokens, and several clusters already overlap
themselves (the existing `api.py::manage_worker` half-collapse over the six
dedicated `worker_*` tools is the most visible). The
[tool-surface-consolidation-assessment](../tech-debt/tool-surface-consolidation-assessment.md)
catalogued the candidates and tradeoffs but, per planning-review finding
`AOMCP-1-PLAN-10`, the executable rollout sequence and priority queue do not
belong inside the assessment. This task plan owns that sequencing.

The current state also leaves bounded-read parameters
(`sections=`/`detail=`/`fields=`/`top_n_*`) absent from every orchestrator
list endpoint, so list-call payloads cannot be shaped the way AHMCP-1 already
allows on the handoff side.

## Constraints

- **Pure surface consolidation, not a contract redesign.** Each new
  discriminated tool must wrap the existing handlers field-for-field; renames
  or schema changes belong in a separate task plan.
- **In-repo only.** This monorepo has no external API consumers for
  `agent-orchestrator-mcp`. Caller migration and tool removal can ship in the
  same release window. The standalone `darce/mcp-agent-handoff` checkout is
  out of scope; it does not consume orchestrator tools.
- **No split test surface.** Every consolidation slice that touches a tool
  must update its tests in the same slice — never leave legacy + new test
  paths active in parallel.
- **Greenfield policy applies.** No backward-compatibility shims; once a
  legacy tool is deleted, its registration is gone — handlers may stay as
  private helpers if the discriminated wrapper delegates to them.
- **Deprecation window required for additivity, not for compatibility.** The
  `deprecated_since` window exists so callers (in-repo agents, lane workers,
  scripts) can migrate inside one slice; it is not a long-lived contract.

## Workflow Principles

- Wrap existing handlers; do not invent new field names. Every snippet in the
  source assessment was reviewed against `lanes.py` / `api.py` to confirm field
  parity (PLAN-08 / PLAN-09 fixes).
- Land discriminated tools **alongside** the legacy tools first (Slice A);
  remove legacy registrations only after callers and tests have moved.
- Consolidation slices include their own test migration. Never split a slice
  into "ship the tool" and "fix the tests later".
- Bounded-read parameters are additive with `full` defaults. They never change
  the existing behavior of any caller that does not pass them.
- `list_lane_briefs` is **not** receiving bounded-read parameters: it is
  removed in Slice D, and any brief-shape filtering is expressed via
  `list_lane_messages` (`direction`/`subject_prefix`) or via the new
  `lane_communication` discriminated tool.

## Terminology

- **Discriminated tool**: A single MCP tool that takes one structured
  top-level parameter (`lane=`, `worker=`, `daemon=`, …) carrying an
  `operation` discriminator inside it. The handler dispatches on the
  discriminator and validates operation-specific fields.
- **Wrapper handler**: The new tool's body, which is a thin dispatcher that
  delegates to the existing private handler with no field renames.
- **Legacy registration**: The `ToolEntry(...)` row in
  `_build_tool_registry()` for an old tool. Removing it removes the tool from
  the public surface; the underlying function may still exist as a private
  helper.

## Current State Analysis

- `agent_orchestrator_mcp.api::_build_tool_registry` registers 38 tools across
  11 clusters: lane registration (3), lane activity (1), turn metrics (3),
  lane communication (5), worker reports (2), plan cursors (3),
  cross-task/review (4), orchestrator daemons (6), worker daemons (7),
  dispatch/backends (3), metrics summary (1).
- `api.py::manage_worker` already takes an `action` discriminator that handles
  `start`/`stop`/`resume`/`status` but does **not** deprecate the six
  dedicated `worker_*` registrations that overlap it. This is the most
  embarrassing half-state and the cheapest first slice.
- `lanes.py::record_lane_message`, `lanes.py::update_lane_message`,
  `lanes.py::list_lane_messages`, `lanes.py::record_lane_brief`, and
  `lanes.py::list_lane_briefs` are five distinct registrations that all back
  onto the same `lane_messages` table, with briefs being an
  `orchestrator_to_worker` subtype keyed off the `brief:` subject prefix.
- `lanes.py::upsert_plan_cursor`, `lanes.py::get_plan_cursor`, and
  `lanes.py::list_plan_cursors` use `plan_item_id` (not `plan_item_ref`),
  `state ∈ {dispatched, completed, skipped, escalated}` (not `complete`), and
  the upsert path carries optional `mcp_action_id`, `worker_message_id`,
  `source_heading`, `summary`, and `require_clean_slice`.
- AHMCP-1 bounded-read parameters do not exist on the orchestrator list
  endpoints. The biggest payload offenders are `list_lane_messages`,
  `list_turn_metrics`, `list_worker_reports`, and `get_lane_activity`.
- AOMCP-1 has already landed shaped handoff reads on the orchestrator caller
  side via `handoff_read_shapes.py`; the consumer pattern is established.

## Target Outcome

- The orchestrator MCP registers 16 tools at cold start: 9 untouched + 1
  extended `manage_worker` (already in the baseline; absorbs the 6 dedicated
  `worker_*` tools) + 6 brand-new discriminated wrappers (`manage_worktree_lane`,
  `lane_communication`, `worker_reports`, `plan_cursor`, `turn_metrics`,
  `manage_orchestrator`).
- Every in-repo caller (orchestrator daemons, scripts, lane workers, tests)
  uses the new discriminated tools. No legacy `record_lane_message`,
  `worker_start`, `upsert_plan_cursor`, etc. call sites remain.
- `list_lane_messages`, `list_turn_metrics`, `list_worker_reports`,
  `list_plan_cursors`, and `get_lane_activity` accept the AHMCP-1 bounded-read
  parameters with `full` defaults, and at least one caller in the orchestrator
  package opts into a non-default shape to prove the parameter actually works
  end-to-end.
- `packages/agent-orchestrator-mcp/README.md` carries a short
  "Token-efficient usage" pointer to
  `packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md`. No new
  orchestrator-local token-efficiency guide is created (per AOMCP-1 ownership
  table and PLAN-03 from this same review session).
- `tools/list` cold-start cost drops from 10 000–18 000 tokens to 4 500–8 000
  tokens, measured against the orchestrator MCP's recorded `tools/list`
  response. The measurement is captured as a `record_event(test_result)` row
  on this task ref so the savings are auditable.

## Context Loading

- Source assessment: [`packages/agent-orchestrator-mcp/docs/tech-debt/tool-surface-consolidation-assessment.md`](../tech-debt/tool-surface-consolidation-assessment.md)
- Sibling AHMCP playbook: [`packages/agent-orchestrator-mcp/docs/tech-debt/mcp-token-optimization-assessment.md`](../tech-debt/mcp-token-optimization-assessment.md)
- Live registry: `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py::_build_tool_registry`
- Live lane handlers: `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py` (`record_lane_message`, `update_lane_message`, `list_lane_messages`, `record_lane_brief`, `list_lane_briefs`, `upsert_plan_cursor`, `get_plan_cursor`, `list_plan_cursors`, `record_worker_report`, `list_worker_reports`, `upsert_worktree_lane`, `close_worktree_lane`, `list_worktree_lanes`, `record_turn_metric`, `list_turn_metrics`, `get_turn_metrics_summary`, `get_lane_activity`)
- Rules: `docs/agentic/rules/development-workflow.md`,
  `docs/agentic/rules/backend-python-guidelines.md`,
  `docs/agentic/rules/testing-python.md`
- Contract surface: `docs/agentic/contracts/agent-handoff-mcp.md` for the
  underlying `_json_response` shape, plus the orchestrator-side response path
  in `api.py` (which returns via `core._json_response(...)`) and `lanes.py`
  (which calls the locally re-exported `_json_response(...)`). Orchestrator
  handlers do **not** route through `_envelope()`; AHMCP envelope tests do
  not cover this surface.
- Handoff/MCP state: `AOMCP-3` task ref, plus AOMCP-1 fix-plan-findings task
  history for the precedent the assessment fixes set
- External docs via `ctx7` only if: FastMCP's discriminated-union schema
  rendering changes again and the local AHMCP-6 pattern stops applying

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `agent-orchestrator-mcp` MCP tool surface | orchestrator package | `_build_tool_registry()` lists 38 tools | Add 6 brand-new discriminated wrappers, extend the existing `manage_worker` to absorb the 6 dedicated `worker_*` tools, then remove the 28 legacy `ToolEntry` rows after every in-repo caller has moved | No external consumers; in-repo callers must migrate in lockstep with each slice | Test suite under `packages/agent-orchestrator-mcp/tests/` (`test_lanes_and_handoff_state.py`, `test_orchestrator_lanes.py`, `test_plan_cursor_gate.py`, `test_orchestrator_tools.py`, `test_orchestrator_daemon.py`, `test_worker_daemon.py`) plus a `tools/list` token-count snapshot recorded as `test_result` |
| `agent-orchestrator-mcp` list-endpoint shapes | orchestrator package | List endpoints return full payloads only | Add `sections=` / `detail=` / `fields=` / `top_n_*` parameters with `full` defaults | Yes — defaults must keep every existing caller's behavior identical | Unit tests on each list endpoint asserting both the default-full path and the bounded-read path |
| Orchestrator response shape | orchestrator package | Orchestrator handlers return via `core._json_response(...)` (in `api.py` daemon tools) and via `lanes._json_response(...)` (in `lanes.py` lane surfaces). They do **not** call `agent_handoff_mcp._shared._envelope()` directly. After AHMCP-10 the underlying `_json_response` returns a native `dict`. | No new envelope work in this task; the wrappers must preserve `core._json_response(...)` / `lanes._json_response(...)` semantics field-for-field. | Yes — wrapper response shape must match the legacy handler response shape for the same operation. | Orchestrator-specific tests under `packages/agent-orchestrator-mcp/tests/` (`test_orchestrator_tools.py`, `test_orchestrator_build.py`, plus the per-surface tests above) — explicit round-trip equality assertions per wrapper. AHMCP envelope tests do **not** cover this surface. |
| Orchestrator README docs | orchestrator package | README has no token-efficient guidance section | Add a pointer to `packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md` (no new content) | No | Doc review |

## Proposed Solution

Implement the consolidation in five slices that mirror the AHMCP-6 sequencing
exactly. Each slice ships the discriminated tool, the in-repo caller migration
for that tool, and the test migration for that tool — never split across
slices. Slices are independently mergeable and independently revertible.

The seven discriminated tools land in three additive slices (Slice A1: the
`manage_worker` finish-up, since it removes the most embarrassing overlap and
is the cheapest; Slice A2: `lane_communication`, the largest single cluster
collapse; Slice A3: the remaining five wrappers in one slice because each is
a small mechanical wrapper). Bounded-read parameters land in Slice B as a
single additive change. Slice C is the legacy-removal slice, gated on every
in-repo caller having moved. Slice D is the README doc pointer.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| tool registry | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` (function `_build_tool_registry`) | Add 6 brand-new discriminated `ToolEntry` rows; extend the existing `manage_worker` row in place; mark all 28 legacy entries `deprecated_since="0.4.0"`; in Slice C delete those 28 legacy registrations |
| lane handlers | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py` | Add `lane_communication`, `plan_cursor`, `worker_reports`, `manage_worktree_lane`, `turn_metrics` discriminated wrappers that delegate to the existing handlers (`record_lane_message`, `update_lane_message`, `list_lane_messages`, `record_lane_brief`, `list_lane_briefs`, `upsert_plan_cursor`, `get_plan_cursor`, `list_plan_cursors`, `record_worker_report`, `list_worker_reports`, `upsert_worktree_lane`, `close_worktree_lane`, `list_worktree_lanes`, `record_turn_metric`, `list_turn_metrics`, `get_turn_metrics_summary`) without field renames |
| daemon handlers | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` (or new `daemons.py` if size warrants) | Add `manage_orchestrator` discriminated wrapper covering `start`/`status`/`stop`/`pause`/`resume`/`single_cycle`; extend `manage_worker` to absorb `event_history` and `start_all` (the existing `manage_worker` already handles `start`/`stop`/`resume`/`status`) |
| list endpoints | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py` | Add `sections=` / `detail=` / `fields=` / `top_n_*` parameters to `list_lane_messages`, `list_turn_metrics`, `list_worker_reports`, `list_plan_cursors`, and `get_lane_activity` (NOT `list_lane_briefs`, which is deleted in Slice C) |
| in-repo callers | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/*.py` | Update every call site that names a legacy tool to use the discriminated wrapper instead, in the same slice that introduces the wrapper |
| in-repo callers | `scripts/mcp/**` and any harness bridge that names orchestrator tools | Same |
| orchestrator tests | `packages/agent-orchestrator-mcp/tests/test_lanes_and_handoff_state.py` and `packages/agent-orchestrator-mcp/tests/test_orchestrator_lanes.py` | Existing modules — extend in place to assert `lane_communication` wrapper behavior and remove direct `record_lane_message` / `update_lane_message` / `list_lane_messages` / `record_lane_brief` / `list_lane_briefs` test usages |
| orchestrator tests | `packages/agent-orchestrator-mcp/tests/test_plan_cursor_gate.py` and `packages/agent-orchestrator-mcp/tests/test_lanes_and_handoff_state.py` | Existing modules — extend to assert `plan_cursor` wrapper preserves `plan_item_id` / `state="completed"` / `summary` and the optional linkage fields, and remove direct `upsert_plan_cursor` / `get_plan_cursor` / `list_plan_cursors` test usages |
| orchestrator tests | `packages/agent-orchestrator-mcp/tests/test_worker_daemon.py` and `packages/agent-orchestrator-mcp/tests/test_orchestrator_tools.py` | Existing modules — extend to verify the extended `manage_worker` covers `event_history` and `start_all` and that the legacy `worker_*` tools are gone after Slice C |
| orchestrator tests | `packages/agent-orchestrator-mcp/tests/test_orchestrator_daemon.py` | Existing module — extend to assert `manage_orchestrator` wrapper covers all six daemon operations after Slice A3 |
| docs | `packages/agent-orchestrator-mcp/README.md` | Add "Token-efficient usage" pointer to the package-owned `agent-handoff-mcp` guide (Slice D) |
| planning | `packages/agent-orchestrator-mcp/docs/tasks/AOMCP-3-tool-surface-consolidation-task-plan.md` | This file |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-orchestrator-mcp/docs/tech-debt/tool-surface-consolidation-assessment.md` | Source assessment; sections 1–4, 6, 8 are still authoritative for inventory and tradeoffs |
| `packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md` | Canonical caller guidance; Slice D's README pointer references this |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/handoff_read_shapes.py` | Precedent helper from AOMCP-1; demonstrates the caller-side shaped-read pattern |
| `packages/agent-orchestrator-mcp/docs/tasks/AOMCP-1-token-efficient-handoff-adoption-task-plan.md` | Sibling task plan that already shaped the orchestrator's handoff reads; AOMCP-3 does the same for the orchestrator's own tool surface |

## Verification Strategy

- Deterministic tests:
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-orchestrator-mcp/tests -q`
  - Each slice must add at least one wrapper-specific test and at least one
    test that asserts the new bounded-read parameters return a strict subset
    of the full payload.
- Runtime-parity / environment checks:
  - Boot the orchestrator MCP and capture `tools/list` response. Confirm the
    tool count matches the expected post-slice value, accounting for the fact
    that **deprecation does not change the tool count** — only adding wrappers
    or deleting registrations does. Per-slice expectations:
    - Slice A1 (extend `manage_worker`, deprecate the 6 dedicated `worker_*` tools): **38 → 38** (no count change; `manage_worker` already exists in the baseline and the deprecated tools stay registered until Slice C).
    - Slice A2 (add `lane_communication`, deprecate the 5 lane-message/brief tools): **38 → 39** (one new wrapper).
    - Slice A3 (add the remaining 5 wrappers `manage_worktree_lane`, `worker_reports`, `plan_cursor`, `turn_metrics`, `manage_orchestrator`, deprecate 17 more legacy tools): **39 → 44**.
    - Slice B (bounded-read parameters, no registration changes): **44 → 44**.
    - Slice C (delete all 28 deprecated `ToolEntry` rows): **44 → 16**.
    - Slice D (README pointer, no registration changes): **16 → 16**.
  - Record the `tools/list` token count as a `test_result` event under
    `task_ref="AOMCP-3"` so the cold-start savings are auditable.
- Contract/fixture verification:
  - Each new discriminated tool must round-trip through the existing
    `core._json_response` / `lanes._json_response` path without invented
    fields. Add an assertion that the wrapper's response shape equals the
    legacy handler's response shape for at least one representative operation
    per discriminator. AHMCP envelope tests do not cover this surface; the
    orchestrator-side tests must include these round-trip checks.
- Manual verification:
  - Inspect the `tools/list` schema for each new wrapper to confirm the
    `oneOf` branches enumerate every operation-specific field and that no
    field is named differently from the underlying handler.

## Slice Delivery

### Slice A1: Finish `manage_worker` Collapse

**Goal**: Extend the existing partial `manage_worker` discriminator to absorb
`worker_event_history` and `worker_start_all`, then deprecate (`deprecated_since="0.4.0"`)
all six dedicated `worker_*` registrations and migrate every in-repo caller
in the same slice. `manage_worker` already exists in the 38-tool baseline as
a half-finished discriminator that handles `start`/`stop`/`resume`/`status`;
this slice extends it in place — no new `ToolEntry` row.

Changes:

- Extend `manage_worker()` in `api.py` to handle `operation ∈ {start, stop, resume, status, event_history, start_all}`.
- Mark `worker_start`, `worker_stop`, `worker_resume`, `worker_status`,
  `worker_event_history`, `worker_start_all` with `deprecated_since="0.4.0"`
  in `_build_tool_registry()`.
- Update every in-repo caller of those six tools to use `manage_worker(...)`.
- Extend `tests/test_worker_daemon.py` and `tests/test_orchestrator_tools.py`
  to assert the new operations on `manage_worker` and remove any direct
  legacy-tool tests.
- Record a `test_result` event with `tools/list` count after the slice
  (**expected: 38** — deprecation does not change the count; `manage_worker`
  already exists, so no new wrapper is added).

Proof:

- `pytest packages/agent-orchestrator-mcp/tests/test_worker_daemon.py packages/agent-orchestrator-mcp/tests/test_orchestrator_tools.py -q` passes.
- A grep across the monorepo for `worker_start(`, `worker_stop(`,
  `worker_resume(`, `worker_status(`, `worker_event_history(`,
  `worker_start_all(` returns zero in-repo call sites (only the legacy
  registrations themselves, which are still present but deprecated).

### Slice A2: Land `lane_communication`

**Goal**: Replace the five `lane_messages` / `lane_briefs` tools with a single
`lane_communication` discriminator wrapper that preserves field names
verbatim per the assessment Section 3.2 (revised under PLAN-08).

Changes:

- Add `lane_communication` to `lanes.py` (or a new
  `lanes_communication_wrapper.py`) with `kind ∈ {message, brief}` and
  `operation ∈ {record, update, list}` discriminators.
- Wrapper delegates to `record_lane_message`, `update_lane_message`,
  `list_lane_messages`, `record_lane_brief`, `list_lane_briefs` with no field
  renames. For `kind="brief"` list, the wrapper supplies
  `direction="orchestrator_to_worker"` and `subject_prefix="brief:"`
  automatically.
- Mark the five legacy registrations `deprecated_since="0.4.0"`.
- Migrate every in-repo caller to `lane_communication(...)` in the same slice.
- Extend `tests/test_lanes_and_handoff_state.py` and
  `tests/test_orchestrator_lanes.py` to assert the wrapper's behavior and
  remove direct legacy-tool tests.
- Record `tools/list` count (**expected: 39** — one new wrapper added on top
  of the 38 baseline; the five legacy tools are deprecated but still
  registered).

Proof:

- `pytest packages/agent-orchestrator-mcp/tests/test_lanes_and_handoff_state.py packages/agent-orchestrator-mcp/tests/test_orchestrator_lanes.py -q` passes.
- Wrapper round-trip test: every legacy operation produces the same response
  shape via the wrapper as via the legacy tool (parametrized on at least one
  representative payload per operation).

### Slice A3: Land Remaining Five Wrappers

**Goal**: Add `manage_worktree_lane`, `worker_reports`, `plan_cursor`,
`turn_metrics`, and `manage_orchestrator` discriminated wrappers in one slice
since each is a small mechanical wrapper, deprecate the 17 legacy
registrations they replace, and migrate callers + tests.

Changes:

- `manage_worktree_lane(lane={"operation": "upsert"|"close"|"list", ...})`
  wrapping `upsert_worktree_lane`, `close_worktree_lane`, `list_worktree_lanes`
  (3 legacy tools).
- `worker_reports(report={"operation": "record"|"list", ...})` wrapping
  `record_worker_report`, `list_worker_reports` (2 legacy tools).
- `plan_cursor(cursor={"operation": "upsert"|"get"|"list", ...})` using the
  **live** field vocabulary from `lanes.py::upsert_plan_cursor` /
  `lanes.py::get_plan_cursor` / `lanes.py::list_plan_cursors`
  (`plan_item_id`, `state ∈ {dispatched, completed, skipped, escalated}`,
  optional `mcp_action_id`, `worker_message_id`, `source_heading`, `summary`,
  `require_clean_slice`). The wrapper preserves all of these per the PLAN-09
  assessment fix (3 legacy tools).
- `turn_metrics(metric={"operation": "record"|"list"|"summary", ...})`
  wrapping `record_turn_metric`, `list_turn_metrics`, `get_turn_metrics_summary`
  (3 legacy tools).
- `manage_orchestrator(daemon={"operation": "start"|"status"|"stop"|"pause"|"resume"|"single_cycle", ...})`
  wrapping the six `orchestrator_*` daemon tools (6 legacy tools).
- Total legacy registrations marked `deprecated_since="0.4.0"` in this slice:
  3 + 2 + 3 + 3 + 6 = **17**.
- Migrate every in-repo caller in the same slice.
- Update tests in the same slice — no parallel test surface. Touched modules:
  `tests/test_lanes_and_handoff_state.py` (lane registration + plan cursor),
  `tests/test_orchestrator_lanes.py` (worker reports + turn metrics),
  `tests/test_orchestrator_daemon.py` (`manage_orchestrator` daemon
  operations), `tests/test_plan_cursor_gate.py` (`plan_cursor` field
  preservation).
- Record `tools/list` count (**expected: 44** — Slice A2's 39 plus the 5 new
  wrappers from this slice; the 17 newly-deprecated tools and the 6 deprecated
  in Slice A1 are still registered until Slice C).

Proof:

- Full orchestrator pytest suite passes.
- Each new wrapper has at least one round-trip test against the legacy
  handler's response shape.

### Slice B: Bounded-Read Parameters

**Goal**: Add `sections=` / `detail=` / `fields=` / `top_n_*` parameters to
the orchestrator list endpoints with `full` defaults so callers can opt into
narrower payloads, mirroring AHMCP-1.

Changes:

- Add the parameters to `list_lane_messages`, `list_turn_metrics`,
  `list_worker_reports`, `list_plan_cursors`, `get_lane_activity` in
  `lanes.py`. Default to `full` so every existing caller's behavior is
  preserved.
- **Do not** add bounded-read parameters to `list_lane_briefs` — it is
  removed in Slice C and any brief-shape filtering should already go through
  `lane_communication(kind="brief", operation="list", ...)`.
- Add at least one orchestrator-side caller that opts into a non-default
  shape, to prove the parameter is wired end-to-end (e.g. lane prompt
  assembly shrinks `list_lane_messages` to `detail="summary"` plus a
  `subject_prefix` filter).
- Add unit tests asserting both the default-full path and the bounded-read
  path for each touched endpoint.

Proof:

- New unit tests pass.
- A `test_result` event records the payload-size delta on the chosen caller.

### Slice C: Removal

**Goal**: Delete every legacy `ToolEntry(...)` registration that has been
deprecated by Slices A1–A3 and verify the public surface drops to 16 tools.

Changes:

- Delete all **28** legacy `ToolEntry(...)` rows from `_build_tool_registry()`:
  6 dedicated `worker_*` tools (Slice A1), 5 lane-message/brief tools (Slice
  A2), and the 17 lane-registration / worker-report / plan-cursor /
  turn-metric / orchestrator-daemon tools (Slice A3). Their underlying handler
  functions stay as private helpers if the wrapper delegates to them.
- Delete `list_lane_briefs` and `record_lane_brief` registrations
  specifically as part of this removal — `lane_communication(kind="brief")`
  already replaces them and Slice B explicitly skipped adding shaping
  parameters to the brief list endpoint.
- Re-record the `tools/list` count as a `test_result` event (must equal **16**:
  Slice A3's 44 minus the 28 deleted legacy registrations = 16).
- Run the full pytest suite under `packages/agent-orchestrator-mcp/tests` to
  confirm no test still references a deleted tool name.

Proof:

- `tools/list` returns exactly 16 tools.
- `pytest packages/agent-orchestrator-mcp/tests -q` passes.
- A grep for any deleted tool name across `packages/agent-orchestrator-mcp/`
  and `scripts/mcp/` returns zero results outside this task plan.

### Slice D: README Pointer

**Goal**: Add a short "Token-efficient usage" pointer in the orchestrator
README that references the package-owned
`packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md`. Do not
fork a duplicate guide (per AOMCP-1 ownership table and finding
`AOMCP-1-PLAN-03`).

Changes:

- Add a section to `packages/agent-orchestrator-mcp/README.md` with a single
  paragraph and a link to the AHMCP guide. Capture only orchestrator-specific
  caller decisions inline if they cannot live in the AHMCP guide; otherwise
  the pointer is the entire change.

Proof:

- Doc review confirms the pointer exists, the link target resolves, and no
  duplicated parameter semantics were copied into the orchestrator README.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the source assessment, the live `api.py` registry, and `lanes.py`
  before drafting wrappers.
- [ ] Confirmed no external `agent-orchestrator-mcp` consumers exist in this
  monorepo or in `darce/mcp-agent-handoff`.
- [ ] Recorded that the AHMCP envelope is inherited unchanged; this task does
  no envelope work.

### Checklist for Slice A1: Finish `manage_worker` Collapse

- [ ] `manage_worker` operation set extended to include `event_history` and
  `start_all` (the existing wrapper already handles `start`/`stop`/`resume`/`status`).
- [ ] Six legacy `worker_*` registrations marked `deprecated_since="0.4.0"`.
- [ ] All in-repo callers of the six legacy worker tools migrated to
  `manage_worker`.
- [ ] `tests/test_worker_daemon.py` and `tests/test_orchestrator_tools.py`
  updated; no parallel test surface.
- [ ] `tools/list` snapshot recorded as `test_result` (**expected: 38** —
  deprecation does not change the count; `manage_worker` already exists).

### Checklist for Slice A2: Land `lane_communication`

- [ ] `lane_communication` wrapper added with `kind` + `operation`
  discriminators per assessment Section 3.2 (PLAN-08-revised).
- [ ] Wrapper delegates to existing handlers with **no** field renames.
- [ ] Five legacy `lane_message` / `lane_brief` registrations marked
  `deprecated_since="0.4.0"`.
- [ ] All in-repo callers migrated to `lane_communication`.
- [ ] Round-trip test: legacy vs wrapper response equality for at least one
  operation per `kind`, asserted in
  `tests/test_lanes_and_handoff_state.py` and `tests/test_orchestrator_lanes.py`.
- [ ] `tools/list` snapshot recorded (**expected: 39** — one new wrapper added).

### Checklist for Slice A3: Remaining Five Wrappers

- [ ] `manage_worktree_lane`, `worker_reports`, `plan_cursor`, `turn_metrics`,
  `manage_orchestrator` wrappers added.
- [ ] `plan_cursor` uses `plan_item_id`, `state ∈ {dispatched, completed,
  skipped, escalated}`, and preserves `mcp_action_id`, `worker_message_id`,
  `source_heading`, `summary`, `require_clean_slice` per PLAN-09-revised.
- [ ] 17 legacy registrations marked `deprecated_since="0.4.0"`
  (3 lane-registration + 2 worker-report + 3 plan-cursor + 3 turn-metric +
  6 orchestrator-daemon).
- [ ] All in-repo callers migrated.
- [ ] Per-wrapper round-trip tests added in
  `tests/test_lanes_and_handoff_state.py`,
  `tests/test_orchestrator_lanes.py`,
  `tests/test_plan_cursor_gate.py`, and
  `tests/test_orchestrator_daemon.py`.
- [ ] `tools/list` snapshot recorded (**expected: 44** — five new wrappers
  added on top of Slice A2's 39; the 17 newly-deprecated tools and Slice A1's
  6 deprecated tools are still registered until Slice C).

### Checklist for Slice B: Bounded-Read Parameters

- [ ] `sections=` / `detail=` / `fields=` / `top_n_*` added to
  `list_lane_messages`, `list_turn_metrics`, `list_worker_reports`,
  `list_plan_cursors`, `get_lane_activity` with `full` defaults.
- [ ] No bounded-read parameters added to `list_lane_briefs` (it is removed
  in Slice C).
- [ ] At least one orchestrator caller opts into a non-default shape.
- [ ] Per-endpoint default-full and bounded-read tests added.
- [ ] Payload-size delta recorded as a `test_result` event for the migrated
  caller.

### Checklist for Slice C: Removal

- [ ] **28** legacy `ToolEntry(...)` rows deleted from `_build_tool_registry()`
  (Slice A1's 6 + Slice A2's 5 + Slice A3's 17).
- [ ] `list_lane_briefs` and `record_lane_brief` registrations deleted.
- [ ] `tools/list` returns exactly **16** tools (Slice A3's 44 minus the 28
  deletions), verified and recorded as `test_result`.
- [ ] Full pytest suite passes with zero references to deleted tool names.
- [ ] Repo-wide grep for deleted tool names returns no in-repo callers.

### Checklist for Slice D: README Pointer

- [ ] `packages/agent-orchestrator-mcp/README.md` carries a "Token-efficient
  usage" section pointing at
  `packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md`.
- [ ] No duplicated parameter semantics from the AHMCP guide.
- [ ] Doc review pass recorded in MCP.

## Review Readiness

- [ ] No slice leaves a parallel test surface.
- [ ] Every wrapper round-trips the legacy handler's response shape for at
  least one representative operation.
- [ ] `tools/list` snapshots are recorded as `test_result` events on
  `task_ref="AOMCP-3"` so the token-cost reduction is auditable.
- [ ] No new orchestrator-local token-efficient guide is created (the README
  pointer is the only docs change).
- [ ] Handoff decision records each slice's behavioral changes, the legacy
  tools removed, and the recorded `tools/list` count.

## Stretch Goals

- [ ] Add a `make tools-list-snapshot` target that boots the orchestrator
  MCP, captures `tools/list`, and writes the response (and token count) to
  `.task-state/tools-list-snapshot.json` so future drift can be measured by
  diffing snapshots, not by re-running the full integration suite.

## Success Criteria

- [ ] `_build_tool_registry()` returns exactly 16 tools after Slice C.
- [ ] Every in-repo caller and every test under
  `packages/agent-orchestrator-mcp/` uses the new discriminated tools; no
  references to any of the **28** deleted tool names remain in the package or
  in `scripts/mcp/`.
- [ ] Every new discriminated tool wraps the existing handler field-for-field;
  no schema renames or contract trims happen in this task.
- [ ] `list_lane_messages`, `list_turn_metrics`, `list_worker_reports`,
  `list_plan_cursors`, and `get_lane_activity` accept the AHMCP-1 bounded-read
  parameters with `full` defaults and have at least one caller exercising a
  non-default shape.
- [ ] `tools/list` cold-start token count drops from the recorded baseline
  (10 000–18 000 tokens) into the 4 500–8 000 token range, captured as a
  `test_result` event on `AOMCP-3`.
- [ ] `packages/agent-orchestrator-mcp/README.md` points at the package-owned
  `agent-handoff-mcp` token-efficient guide; no duplicate guide is created.
