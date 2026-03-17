# Daemon 5: Task-Plan-Driven Orchestrator

## Problem Statement

The orchestrator daemon can now dispatch MCP-stamped work, consume worker guidance, and keep the lane loop moving. What it still does not do is continuously read the task plan itself and derive the next slice of work when MCP does not already contain an explicit pending action or review finding.

## Workflow Principles

- **The task plan is planning truth; MCP is runtime truth.** The daemon should derive candidate next slices from the task plan, then record the chosen slice into MCP before dispatching it.
- **Never guess across lane boundaries.** Any auto-derived slice must map cleanly to one owning lane from the lane manifest, or it must escalate for orchestrator review.
- **Dispatch only actionable unchecked work.** Checked items, blocked items, and already-closed slices must not be re-issued.
- **One active assignment per lane.** The orchestrator should not pile multiple competing slices onto the same lane when one clear next step exists.
- **Human-readable plans, machine-safe extraction.** Parsing can use heuristics, but it should normalize into a structured slice model before orchestration decisions are made.
- **Capacity is explicit.** A lane has capacity only when it has zero open `orchestrator_to_worker` lane messages and zero pending MCP next actions already assigned to that lane.

## Terminology

- **Task plan item**: A checklist entry or explicitly labeled implementation step in `docs/tasks/...`.
- **Derived slice**: A structured candidate assignment inferred from a task-plan item and lane manifest metadata.
- **Plan cursor**: The orchestrator’s persisted view of which plan items have already been dispatched, completed, skipped, or escalated.
- **Dispatchable item**: A task-plan item that is unchecked, lane-owned, not already represented by an open MCP action/finding/message, and specific enough to assign.

## Current State Analysis

- `scripts/mcp/orchestrator_daemon.py` can already dispatch work from MCP findings, blockers, and next actions.
- The orchestrator daemon is now split into four modules:
  - `scripts/mcp/orchestrator_daemon.py` for the main loop, lock, and CLI
  - `scripts/mcp/orchestrator_helpers.py` for shared logging/JSON/text helpers
  - `scripts/mcp/orchestrator_guidance.py` for worker-guidance classification and response
  - `scripts/mcp/orchestrator_lanes.py` for dispatch/intake/refresh/lane worktree helpers
- `scripts/mcp/orchestrator_guidance_policy.py` is currently a thin fallback assignment policy layer, not a full planning/parser surface, and is not modified by daemon-5 plan parsing work.
- Task plans under `docs/tasks/6.0/` are still treated as human-only planning artifacts.
- The orchestrator does not continuously scan unchecked checklist items to create the next actionable lane slice.
- This means work can stall once explicit MCP backlog is exhausted, even when the task plan still has clearly sequenced unchecked items.
- There is no structured persistence layer yet for “this task-plan item has already been dispatched/reviewed/completed”.
- The missing task-plan-driven logic does not belong in one monolith anymore:
  - parsing and normalization should live in a dedicated parser module
  - lane-capacity and dispatch helpers should live with other lane operations
  - guidance and plan-derived redispatch must share one deduped assignment path
  - durable suppression state must be added to MCP storage and surfaced through explicit helpers

## Proposed Solution

Add a dedicated task-plan parsing layer beside the orchestrator daemon. Introduce a new `scripts/mcp/task_plan_parser.py` module that owns markdown parsing, stable item IDs, heading context, lane hint extraction, and normalization. On each cycle, after handling existing MCP backlog and before declaring the task idle, the daemon should:

1. parse the configured task-plan markdown for the active task
2. extract unchecked actionable items into normalized structured records
3. filter candidates through manifest `merge_order` / `downstream` so only phase-appropriate items are dispatchable
4. map each remaining candidate item to exactly one lane using explicit plan metadata plus the task manifest
5. suppress any item already represented by open MCP state or a recorded plan cursor using exact `plan_item_id` correlation
6. record a new MCP next action/decision for the chosen slice
7. dispatch that slice to the owning lane

The daemon must not simply pick the first unchecked checkbox. Dispatch order must respect manifest sequencing:

- only lanes whose upstream dependencies are satisfied are eligible
- when multiple unchecked items exist, prefer the earliest dispatchable item within the earliest eligible lane in `merge_order`
- cross-lane or ambiguous items must be escalated instead of dispatched optimistically

Lane mapping cannot rely on fuzzy prose matching alone. The parser should use this precedence:

1. explicit inline plan annotation, for example ``[lane:backend-http]``
2. heading-to-lane mapping declared in the task manifest
3. exact manifest plan-routing hints
4. otherwise escalate for manual review

To bootstrap the real Phase 5 plan, daemon-5 must not rely on inline lane annotations appearing magically. Phase 0 should seed task-plan metadata in the Phase 5 manifest:

- top-level `task_plan_path: docs/tasks/6.0/phase-5-retention-export-and-audit-controls-task-plan.md`
- top-level `heading_to_lane` entries for:
  - `Phase 1: Backend -- Tenant Policy Model and Audit Event Storage` -> `backend-domain`
  - `Phase 2: Backend -- Export and Purge Service Layer` -> `backend-domain`
  - `Phase 3: Backend -- Policy, Export, Purge, and Audit HTTP Endpoints` -> `backend-http`
  - `Phase 4: Plugin -- Retention Status Proxy and Admin Surface` -> `wp-proxy`
  - `Phase 5: Frontend -- Retention and Audit Admin Surface` -> `frontend`
- top-level `plan_routing_hints` entries for the mixed `Phase 6: Integration Tests` section:
  - `Backend integration test:` -> `backend-domain`
  - `PHP integration test:` -> `wp-proxy`
  - `Vitest integration test:` -> `frontend`

The remaining `Phase 6` checklist item (`All backend pytest, PHP PHPUnit/PHPStan, TypeScript type checks, and Vitest/ESLint checks pass.`) is intentionally cross-lane and should escalate unless a later manifest rule explicitly decomposes it.

Stable IDs must be deterministic. The `plan_item_id` scheme should be:

- explicit `<!-- plan-id: ... -->` comment when present
- otherwise `phase_slug::heading_slug::checklist_ordinal`

Cursor persistence is the critical new capability and must be concrete. Add a new MCP-backed `plan_cursors` table through `_apply_handoff_migrations()` with at least:

- `id INTEGER PRIMARY KEY`
- `task_ref TEXT NOT NULL`
- `plan_item_id TEXT NOT NULL`
- `state TEXT NOT NULL CHECK(state IN ('dispatched', 'completed', 'skipped', 'escalated'))`
- `lane_id TEXT`
- `mcp_action_id INTEGER`
- `worker_message_id INTEGER`
- `source_heading TEXT`
- `summary TEXT NOT NULL`
- `dispatch_count INTEGER NOT NULL DEFAULT 0`
- `dispatched_at TEXT`
- `completed_at TEXT`
- `created_at TEXT NOT NULL DEFAULT datetime('now')`
- `updated_at TEXT`

Migration requirements:

- create the table in `_apply_handoff_migrations()` if it does not exist
- add a unique index on `(task_ref, plan_item_id)`
- add an index on `(task_ref, state, lane_id)` for daemon polling
- treat existing tasks as having an empty cursor set on first startup; no backfill is required

Public API surface should be explicit. Add internal MCP/runtime helpers for:

- `upsert_plan_cursor(task_ref, plan_item_id, state, lane_id=None, mcp_action_id=None, worker_message_id=None, source_heading=None, summary=None)`
- `get_plan_cursor(task_ref, plan_item_id)`
- `list_plan_cursors(task_ref, state=None)`
- `complete_plan_cursor(task_ref, plan_item_id, worker_message_id=None)`
- `find_open_plan_cursor_by_lane(task_ref, lane_id)`

API boundary:

- `core.py` owns SQL schema, migrations, and row-level CRUD
- `api.py` exposes JSON wrappers for `get_plan_cursor`, `list_plan_cursors`, and `upsert_plan_cursor`
- `orchestrator_daemon.py` and parser code should call the MCP wrappers, not raw SQL
- `complete_plan_cursor()` and `find_open_plan_cursor_by_lane()` may stay daemon-internal wrappers if they compose existing public helpers

Lane capacity must also be concrete. For daemon-5, a lane has capacity only when all of the following are true:

- no open `orchestrator_to_worker` lane message exists for that lane
- no `plan_cursors.state='dispatched'` row exists for that lane
- no pending MCP next action already assigned to that lane exists

This keeps the one-active-assignment rule machine-checkable across daemon restarts.

This should make the orchestrator capable of continuously feeding workers from the task plan itself, while still using MCP as the durable audit trail for what was actually assigned.

## Patterns to Follow

### Parse Then Normalize

```python
items = task_plan_parser.parse_task_plan(task_plan_path)
unchecked = [item for item in items if not item.checked]
normalized = [task_plan_parser.normalize_plan_item(item) for item in unchecked]
```

### Explicit Plan ID and Cursor

```python
plan_item_id = task_plan_parser.derive_plan_item_id(item)
cursor_row = api.get_plan_cursor(task_ref=task_ref, plan_item_id=plan_item_id)
if cursor_row and cursor_row.state in {"dispatched", "completed", "skipped"}:
    return None
```

### Manifest-Governed Lane Mapping

```python
lane_id = task_plan_parser.map_plan_item_to_lane(
    normalized_item,
    manifest=load_manifest(task_ref),
)
if lane_id is None:
    orchestrator_daemon.escalate_plan_item(normalized_item)
```

### Exact-ID MCP Suppression

```python
if orchestrator_daemon.has_open_plan_action(plan_item_id) or orchestrator_daemon.has_open_plan_message(plan_item_id):
    return None

api.upsert_plan_cursor(task_ref=task_ref, plan_item_id=plan_item_id, state="dispatched", lane_id=lane_id)
update_next_actions(
    operation="add",
    action=f"[plan:{plan_item_id}] {normalized_item.summary}",
    priority=normalized_item.priority,
)
record_lane_message(subject=f"{lane_id} next assignment", message=f"[plan:{plan_item_id}] ...")
```

### Safe Fallback

```python
if not dispatchable_items:
    log("INFO", "task_plan_no_dispatchable_items")
    return []
```

### Dependency-Aware Dispatch

```python
lane_order = manifest["merge_order"]
upstream_lanes = set(lane_order[: lane_order.index(candidate_lane)])
blocked_by_upstream = any(
    item.lane_id in upstream_lanes
    and item.cursor_state not in {"completed", "skipped", "escalated"}
    for item in unchecked_plan_items
)
if blocked_by_upstream:
    continue
```

For daemon-5, "upstream dependencies are satisfied" means: every unchecked plan item that maps to a lane earlier in `merge_order` is already in a terminal cursor state (`completed`, `skipped`, or `escalated`). Dispatched or undispatched upstream work blocks downstream lane dispatch.

### Module Ownership

- `task_plan_parser.parse_task_plan()` -> `scripts/mcp/task_plan_parser.py`
- `task_plan_parser.normalize_plan_item()` -> `scripts/mcp/task_plan_parser.py`
- `task_plan_parser.derive_plan_item_id()` -> `scripts/mcp/task_plan_parser.py`
- `task_plan_parser.map_plan_item_to_lane()` -> `scripts/mcp/task_plan_parser.py`
- `api.get_plan_cursor()` / `api.list_plan_cursors()` / `api.upsert_plan_cursor()` -> `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`
- `orchestrator_daemon.has_open_plan_action()` / `has_open_plan_message()` / `escalate_plan_item()` -> `scripts/mcp/orchestrator_daemon.py`
- lane-capacity checks and dispatch helpers -> `scripts/mcp/orchestrator_lanes.py`
- guidance dedupe / shared redispatch path -> `scripts/mcp/orchestrator_guidance.py`

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `scripts/mcp/task_plan_parser.py` | n/a | New parser/normalizer module for markdown checklist extraction, stable IDs, heading context, and plan annotations. |
| `scripts/mcp/orchestrator_daemon.py` | n/a | Add task-plan-derived dispatch phase, dependency-aware candidate selection, exact-ID suppression, and cursor updates. |
| `scripts/mcp/orchestrator_lanes.py` | n/a | Add lane-capacity helpers and any plan-dispatch lane-side selection utilities. |
| `scripts/mcp/orchestrator_guidance.py` | n/a | Keep guidance redispatch and plan-derived redispatch aligned so only one canonical lane assignment is emitted. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | n/a | Add durable plan-cursor persistence support keyed by `task_ref` + `plan_item_id`. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | n/a | Expose internal/runtime helpers for plan cursor reads/writes if daemon code should avoid raw SQL access. |
| `scripts/mcp/lane_manifest.py` | n/a | Add validation/accessors for `task_plan_path`, `heading_to_lane`, and `plan_routing_hints`, including bootstrap metadata for existing plans. |
| `Makefile` / `mk/handoff.mk` | n/a | Expose operator-facing dry-run or status surfaces for task-plan-derived dispatches if needed. |
| `packages/agent-handoff-mcp/tests/test_task_plan_parser.py` | n/a | New parser-specific unit tests. |
| `packages/agent-handoff-mcp/tests/test_orchestrator_daemon.py` | n/a | Add coverage for dependency-aware selection, exact-ID suppression, and plan-driven dispatch behavior. |

## Related Files

| File | Note |
| --- | --- |
| `docs/tasks/6.0/phase-5-retention-export-and-audit-controls-task-plan.md` | Primary real-world example of a plan the daemon should mine for unchecked work, including cross-lane phase ordering. |
| `docs/tasks/6.0/daemon-4-orchestrator-guidance-loop-task-plan.md` | Daemon-4 established the closed-loop guidance behavior that daemon-5 should extend. |
| `config/lane-orchestration/<task-ref>.json` | Lane ownership/routing metadata that constrains which plan items can be auto-dispatched; add `task_plan_path` and plan-mapping metadata here. |
| `scripts/mcp/review_dispatch.py` | Existing route/stamp behavior to keep aligned with plan-derived dispatches. |

---

# Consolidated Checklist

## Completed

- [x] Orchestrator daemon can dispatch from MCP findings, blockers, and next actions.
- [x] Orchestrator daemon can consume worker guidance and redispatch lanes.
- [x] Task manifests already provide lane ids, owned paths, worktree paths, and route hints.

## Phase 0: Scaffolding

- [x] Add a new `scripts/mcp/task_plan_parser.py` module that extracts checklist items and headings from markdown plans under `docs/tasks/`.
- [x] Define a normalized `PlanItem` / `DerivedSlice` structure with stable IDs, text summary, checklist state, heading context, and candidate lane.
- [x] Extend the task manifest with an explicit optional `task_plan_path` field for the primary plan file.
- [x] Add optional manifest metadata for `heading_to_lane` mapping and explicit `plan_routing_hints`.
- [x] Update `lane_manifest.py` validation/accessors so the new optional top-level and lane-level planning fields are accepted and normalized.
- [x] Define the durable cursor store as MCP-backed plan-cursor state keyed by `(task_ref, plan_item_id)`.
- [x] Verify scaffolds compile and import cleanly.

## Phase 1: Parsing and Mapping

- [x] Parse unchecked checklist items from the active task plan.
- [x] Preserve enough heading/phase context to generate meaningful dispatch summaries.
- [x] Derive stable `plan_item_id` values using explicit `plan-id` comments or the fallback `phase_slug::heading_slug::checklist_ordinal` scheme.
- [x] Map each candidate item to a single lane using explicit annotations, heading-to-lane mapping, and manifest hints in that order.
- [x] Bootstrap the Phase 5 manifest with `task_plan_path`, `heading_to_lane`, and `plan_routing_hints` so the current plan is dispatchable before any markdown annotations are added.
- [x] Escalate ambiguous or cross-lane items instead of auto-dispatching them.

## Phase 2: MCP Cursor and Suppression

- [x] Prevent redispatch of plan items already represented by open MCP actions, findings, or lane messages using exact `plan_item_id` correlation, not fuzzy summary matching.
- [x] Persist a durable plan cursor so completed or superseded plan-derived slices are not reissued.
- [x] Close or mark satisfied plan-derived actions when the corresponding lane handoff is verified complete.

## Phase 3: Continuous Dispatch Loop

- [x] Insert task-plan-derived dispatching into the orchestrator daemon cycle after existing MCP backlog handling.
- [x] Respect manifest `merge_order` and `downstream` dependencies when choosing the next dispatchable unchecked slice.
- [x] Define and enforce the lane-capacity predicate before dispatching a new plan-derived slice.
- [x] Dispatch the next best unchecked slice to the correct lane when the lane has capacity and no newer assignment.
- [x] Continue looping until no unchecked dispatchable plan items remain and MCP close-check passes.
- [x] Exit non-zero if the daemon repeatedly cannot classify or dispatch remaining unchecked plan items.

## Phase 4: Tests

- [x] Unit tests in `packages/agent-handoff-mcp/tests/test_task_plan_parser.py` for markdown parsing, normalization, and stable ID generation.
- [x] Unit tests for plan-item-to-lane mapping, dependency ordering, and ambiguity handling.
- [x] Orchestrator-daemon tests that verify plan-derived dispatch is suppressed when equivalent MCP work already exists.
- [x] Integration-style test proving the daemon can advance from one unchecked task-plan item to the next across multiple cycles.

## Stretch Goals

- [ ] Support richer plan annotations such as explicit lane tags, priority markers, or `blocked-by:` metadata in markdown.
- [ ] Auto-update task-plan checklist state when orchestrator verifies a dispatched slice is complete, but only from the orchestrator root on a clean working tree with a single-writer policy.
- [ ] Render a dashboard summary of remaining unchecked plan items by lane and phase.

## Success Criteria

- [ ] When MCP backlog is empty but the task plan still has unchecked lane-owned work, the orchestrator daemon dispatches the next slice automatically.
- [ ] The daemon never assigns the same task-plan item twice unless it was explicitly reopened.
- [ ] Workers can make forward progress from the task plan without requiring manual orchestrator decomposition for every remaining slice.
- [ ] Task-plan-derived dispatch remains execution-backend-agnostic: daemon-5 emits MCP state, and worker execution transport is chosen independently by daemon-6 (`codex-cli` or `codex-subagent`).
