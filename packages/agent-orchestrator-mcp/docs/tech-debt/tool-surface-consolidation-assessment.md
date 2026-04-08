# Orchestrator MCP Tool Surface Consolidation Assessment

**Date:** 2026-04-07
**Scope:** Apply the agent-handoff-mcp tool-surface-reduction and token-optimization
learnings (AHMCP-1 / AHMCP-3 / AHMCP-6 / AHMCP-7) to `agent-orchestrator-mcp`.
**Sibling document:** [`mcp-token-optimization-assessment.md`](./mcp-token-optimization-assessment.md)
covers the AHMCP-side rationale and outcomes; this document is the orchestrator
counterpart.

---

## 1. Background — What AHMCP Did

`agent-handoff-mcp` reduced its public tool surface and per-call payload through
four overlapping efforts:

| Ref | Pattern | Result |
|-----|---------|--------|
| **AHMCP-6** | **Discriminated-union tools.** Collapsed siblings behind a single tool that takes a structured `event=` / `review=` parameter with an internal `event_kind` / `operation` discriminator. | `record_decision`/`record_test_result`/`report_blocker` → `record_event(event={event_kind:..., ...})`. `record_review_finding`/`update_review_finding`/`list_review_findings`/`batch_record_review_findings` → `review_findings(review={operation:..., ...})`. |
| **AHMCP-3 + AHMCP-7** | **v2 envelope + dict-return.** `_envelope()` builds a single nested `data` block; the legacy top-level mirror is gated and on its way out. Every handler returns a real `dict` (via `_make_dict_wrapper`) instead of a JSON-encoded string, eliminating FastMCP's `structured_content={"result": "<escaped JSON>"}` double-serialization. | 30–50 % payload reduction once the mirror is removed; native dicts on the wire. |
| **AHMCP-1** | **Bounded read shapes.** `get_handoff_state` / `load_session` accept `sections=`, `detail="full"\|"summary"`, `top_n_*=`, and `fields=` so callers can opt into a 1 KB identity-only view instead of a 30 KB full state fetch. | `sections="identity"` drops a state read from 15–50 KB to ~1 KB (95 %+). `detail="summary"` strips verbose rationale/result fields. |

The combined effect is a smaller capability advertisement at server start *and*
smaller per-call responses, which matters because every connected agent pays the
tool-list cost on every cold start.

---

## 2. Current Orchestrator Surface (Inventory)

`agent_orchestrator_mcp.api._build_tool_registry()` (api.py:147–209) currently
registers **38 tools** across eleven clusters. The cluster breakdown:

| # | Cluster | Tools | Count |
|---|---------|-------|------:|
| 1 | Lane registration | `upsert_worktree_lane`, `close_worktree_lane`, `list_worktree_lanes` | 3 |
| 2 | Lane activity | `get_lane_activity` | 1 |
| 3 | Turn metrics | `record_turn_metric`, `list_turn_metrics`, `get_turn_metrics_summary` | 3 |
| 4 | Lane communication | `record_lane_message`, `update_lane_message`, `list_lane_messages`, `record_lane_brief`, `list_lane_briefs` | 5 |
| 5 | Worker reports | `record_worker_report`, `list_worker_reports` | 2 |
| 6 | Plan cursors | `upsert_plan_cursor`, `get_plan_cursor`, `list_plan_cursors` | 3 |
| 7 | Cross-task / review | `switch_task`, `get_latest_slice_review_packet`, `reconcile_review_findings`, `get_review_findings_summary` | 4 |
| 8 | Orchestrator daemons | `orchestrator_start`, `orchestrator_status`, `orchestrator_stop`, `orchestrator_pause`, `orchestrator_resume`, `orchestrator_single_cycle` | 6 |
| 9 | Worker daemons | `worker_start`, `worker_status`, `worker_event_history`, `worker_stop`, `worker_resume`, `worker_start_all`, `manage_worker` | 7 |
| 10 | Dispatch / backends | `run_structured_turn`, `dispatch_lane_work`, `list_available_backends` | 3 |
| 11 | Metrics summary | `get_metrics_summary` | 1 |

Note that cluster 9 already contains a half-finished consolidation: `manage_worker`
takes `action="start"|"stop"|"resume"|"status"` and overlaps the six dedicated
`worker_*` tools without deprecating them. This is exactly the kind of additive
discriminated tool AHMCP-6 introduced — but AHMCP follows through and removes the
duplicates. Orchestrator should do the same.

---

## 3. Consolidation Candidates

Each candidate below mirrors the AHMCP-6 discriminated-tool pattern: one tool, one
top-level structured parameter (`lane=`, `metric=`, `daemon=`, …) with an
`operation` discriminator inside it. Existing handler logic moves under the
discriminator with no behavioural change — this is a surface refactor, not a
rewrite.

### 3.1 `manage_worktree_lane` — collapses cluster 1 (3 → 1)

```python
manage_worktree_lane(lane={
    "operation": "upsert" | "close" | "list",
    # operation-specific fields:
    "lane_id": "...",       # upsert/close
    "branch": "...",        # upsert
    "worktree_path": "...", # upsert
    "status": "...",        # upsert/close
    "task_ref": "...",      # list (optional)
})
```

### 3.2 `lane_communication` — collapses cluster 4 (5 → 1)

Lane messages and lane briefs share the same underlying `lane_messages` table;
briefs are an `orchestrator_to_worker` subtype keyed off a `brief:` subject
prefix (see `record_lane_brief` / `list_lane_briefs` in
`packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py`). The
discriminator is a thin wrapper that **preserves the existing field names** for
each underlying handler, not a brief-schema redesign:

```python
lane_communication(message={
    # discriminator
    "kind": "message" | "brief",
    "operation": "record" | "update" | "list",

    # ----- record (kind=message): wraps record_lane_message() -----
    "lane_id": "...",                # required
    "session": "...",                # required
    "direction": "orchestrator_to_worker" | "worker_to_orchestrator",
    "message": "...",                # required body text
    "subject": "...",                # optional
    "status": "open" | "closed" | "ack",  # default "open"
    "payload": { ... },              # optional structured payload

    # ----- record (kind=brief): wraps record_lane_brief() -----
    # All record-message fields above EXCEPT direction (briefs are always
    # orchestrator_to_worker), plus the structured brief contract:
    "source_lane": "...",            # required
    "reason": "...",                 # required
    "summary": "...",                # required
    "required_actions": [...],       # optional
    "artifacts": [...],              # optional
    # `message` (the freeform body) stays optional for kind=brief

    # ----- update (kind=message only): wraps update_lane_message() -----
    "message_id": int,               # required target
    "status": "open" | "closed" | "ack",

    # ----- list (kind=message): wraps list_lane_messages() -----
    "task_ref": "...",               # optional override
    "status": "open" | "closed" | "ack" | "all",  # default "all"
    "limit": int, "offset": int,
    "direction": "...",              # optional filter
    "subject_prefix": "...",         # optional; e.g. "brief:" subsumes list_lane_briefs

    # ----- list (kind=brief): wraps list_lane_briefs() -----
    # Same as list-message but the wrapper supplies direction="orchestrator_to_worker"
    # and subject_prefix="brief:" automatically. Defaults: status="open", limit=20.
})
```

This is the largest cluster collapse and the one most analogous to AHMCP-6's
`review_findings` consolidation. The wrapper does **no** schema migration: it
hands every field through to the existing handler, validates the discriminator,
and surfaces handler errors verbatim. Any rename or field-set change would be a
separate task plan, not part of this consolidation.

### 3.3 `worker_reports` — collapses cluster 5 (2 → 1)

```python
worker_reports(report={
    "operation": "record" | "list",
    "lane_id": "...",
    "summary": "...",
    "changed_files": [...],
    "blockers": [...],
    "merge_ready": bool,
})
```

### 3.4 `plan_cursor` — collapses cluster 6 (3 → 1)

Wraps `upsert_plan_cursor()` / `get_plan_cursor()` / `list_plan_cursors()` in
`packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py` with no
field renames. Note the live state vocabulary is
`dispatched | completed | skipped | escalated` (not "complete"), the identifier
is `plan_item_id` (not `plan_item_ref`), and the upsert path carries optional
linkage and gate fields that the wrapper preserves verbatim:

```python
plan_cursor(cursor={
    "operation": "upsert" | "get" | "list",

    # ----- upsert: wraps upsert_plan_cursor() -----
    "plan_item_id": "...",           # required
    "state": "dispatched" | "completed" | "skipped" | "escalated",
    "summary": "...",                # required when creating a new cursor
    "lane_id": "...",                # optional
    "mcp_action_id": int,            # optional linkage
    "worker_message_id": int,        # optional linkage
    "source_heading": "...",         # optional provenance
    "require_clean_slice": bool,     # optional gate; default False

    # ----- get: wraps get_plan_cursor() -----
    "plan_item_id": "...",           # required

    # ----- list: wraps list_plan_cursors() -----
    "state": "all" | "dispatched" | "completed" | "skipped" | "escalated",
    "lane_id": "...",                # optional filter
    "limit": int, "offset": int,     # default limit=50

    # all operations
    "task_ref": "...",               # optional override
})
```

If a future task plan wants to drop any of the optional linkage/gate fields,
that decision belongs in the task plan that consolidates the wrapper, not in
this assessment — the surface goal here is the wrapper, not a contract trim.

### 3.5 `turn_metrics` — collapses cluster 3 (3 → 1)

```python
turn_metrics(metric={
    "operation": "record" | "list" | "summary",
    "lane_id": "...", "backend": "...", "model": "...", "phase": "...",
    "tokens_in": int, "tokens_out": int, "latency_ms": int,
})
```

### 3.6 `manage_orchestrator` — collapses cluster 8 (6 → 1)

```python
manage_orchestrator(daemon={
    "operation": "start" | "status" | "stop" | "pause" | "resume" | "single_cycle",
    "force": bool,  # stop
})
```

### 3.7 `manage_worker` — finishes the existing collapse (7 → 1)

`manage_worker` already exists with a partial action discriminator. Extend it to
cover `event_history` and `start_all`, then **delete** the six dedicated `worker_*`
tools. This is the cleanest demonstration of the AHMCP-6 follow-through that the
orchestrator currently lacks.

```python
manage_worker(worker={
    "operation": "start" | "stop" | "resume" | "status"
                 | "event_history" | "start_all",
    "task_ref": "...",
    "lane_id": "...",
    "force": bool,
    "event_filter": "...",  # event_history
})
```

### 3.8 Untouched (intentionally)

- `get_lane_activity`, `switch_task`, `get_latest_slice_review_packet`,
  `reconcile_review_findings`, `get_review_findings_summary` — single-purpose,
  no siblings to collapse with.
- `run_structured_turn`, `dispatch_lane_work`, `list_available_backends` —
  distinct verbs against distinct subsystems.
- `get_metrics_summary` — already a singular summary tool.

---

## 4. Surface and Token Impact

### 4.1 Tool count

| State | Tools |
|-------|------:|
| Today | **38** |
| After collapses 3.1–3.7 | **16** |
| Reduction | **−22 tools / ~58 %** |

Untouched tools: `get_lane_activity`, `switch_task`,
`get_latest_slice_review_packet`, `reconcile_review_findings`,
`get_review_findings_summary`, `run_structured_turn`, `dispatch_lane_work`,
`list_available_backends`, `get_metrics_summary` (9). Plus the seven new
discriminated tools (`manage_worktree_lane`, `lane_communication`,
`worker_reports`, `plan_cursor`, `turn_metrics`, `manage_orchestrator`,
extended `manage_worker`) = **16**. `manage_worker` absorbs `event_history` and
`start_all` rather than keeping them separate; the count above assumes that
follow-through.

### 4.2 Capability advertisement

FastMCP serializes every registered tool's name, description, and JSON Schema on
the initial `tools/list` exchange. Empirically each orchestrator tool runs
~250–500 tokens of schema once parameter docs are included. Going from 38 → 16
tools cuts the cold-start advertisement by roughly:

| Metric | Today | After consolidation | Δ |
|--------|------:|--------------------:|--:|
| Tools | 38 | 16 | −58 % |
| Estimated `tools/list` tokens | 10 000 – 18 000 | 4 500 – 8 000 | **~50–55 %** |

The discriminated-union schemas are individually larger than their predecessors
(more fields, more `oneOf` branches), so the reduction is *not* linear with tool
count — which is exactly what AHMCP observed.

### 4.3 Per-call envelope

Orchestrator handlers return through `agent_handoff_mcp._shared._envelope()` (the
re-exported AHMCP envelope), so they inherit any AHMCP-7 mirror removal for
free. **No orchestrator-side envelope work is required**; once AHMCP-7 lands the
schema_version=3 dict-return mirror removal, every orchestrator response also
shrinks 30–50 %.

### 4.4 Bounded reads

The AHMCP-1 `sections=`/`detail=`/`fields=`/`top_n_*=` parameters do not yet
exist on the orchestrator list endpoints. The biggest wins are:

- `list_lane_messages` / `list_lane_briefs` → support `detail="summary"` to strip
  full message bodies; support `fields=` to return only id/status/lane_id.
- `list_turn_metrics` → support `top_n_*=` and `fields=` to bound row count and
  column width when used as a routine sanity check.
- `list_worker_reports` → same — full reports include changed-file lists that
  blow up payload size.
- `get_lane_activity` → already large; should accept `sections=` so callers can
  ask for just `blockers` or just `messages` instead of the full bundle.

These are additive parameters with `full` defaults — safe to ship under the same
"compatibility-managed parameterization" rule AHMCP-1 follows.

---

## 5. Migration Approach

> **Pipeline note:** The detailed slice sequence, deprecation strategy, removal
> timing, caller-migration scope, and prioritized rollout queue are owned by the
> follow-on task plan, not this assessment. See
> [`packages/agent-orchestrator-mcp/docs/tasks/AOMCP-3-tool-surface-consolidation-task-plan.md`](../tasks/AOMCP-3-tool-surface-consolidation-task-plan.md).
> Per [`docs/agentic/rules/planning-review-guide.md`](../../../../docs/agentic/rules/planning-review-guide.md),
> assessments surface problems and tradeoffs; executable slices live in a task
> plan after the assessment review gate.

At assessment level the migration only needs to commit to two principles:

- **Additive first, removal last.** New discriminated tools must land alongside
  the legacy tools so callers can migrate before any registration is deleted.
  This follows the AHMCP-6 sequencing that has already proven safe in this
  repo.
- **In-repo callers move in lockstep with the tools.** The orchestrator does
  not have external API consumers in this monorepo, so caller migration and
  tool deprecation can ship in the same release window. Tests under
  `packages/agent-orchestrator-mcp/tests/` must move with the consolidation
  rather than splitting the test surface.

Everything else — slice boundaries, the exact P1..PN sequence, removal timing,
docs, and verification commands — is the task plan's responsibility.

---

## 6. Risks and Open Questions

- **Schema bloat.** Discriminated unions with many `oneOf` branches can produce
  *larger* per-tool schemas if every operation's full field set is inlined.
  AHMCP mitigated this by keeping operation-specific fields optional and
  validating inside the handler instead of in JSON Schema. Orchestrator should
  follow the same pattern.
- **Test migration.** Existing tests under
  `packages/agent-orchestrator-mcp/tests/` call the legacy tool names directly.
  Each consolidation slice must update those tests as part of the same PR; do
  not leave a split test surface.
- **Cross-repo callers.** The standalone `darce/mcp-agent-handoff` checkout and
  any consumer outside this monorepo will see the deprecated tools at
  `tools/list` and need to migrate. Treat the `deprecated_since` window as the
  contract for those consumers — do not delete legacy registrations until at
  least one tagged release has shipped with the deprecation warning visible.
- **`manage_worker` half-state.** The current `manage_worker` overlaps the six
  `worker_*` tools but doesn't deprecate them. Decide up front whether to
  finish the collapse (recommended) or remove `manage_worker` and keep the
  granular tools. Half-states are the worst outcome for token cost *and*
  cognitive load.
- **Capability discovery for new agents.** A 60 % tool reduction is great for
  token cost but means new agents must learn the discriminator pattern. The
  inline `TOOL_DESCRIPTIONS` and per-discriminator schema enums are the place
  to teach it — do not assume callers will read external docs.

---

## 7. Forward Pointer

The prioritized action queue, slice boundaries, deprecation windows, caller
migration plan, and verification commands now live in the executable task plan:

- [`packages/agent-orchestrator-mcp/docs/tasks/AOMCP-3-tool-surface-consolidation-task-plan.md`](../tasks/AOMCP-3-tool-surface-consolidation-task-plan.md)

This assessment intentionally does not duplicate that ordering. If a sequencing
or priority decision changes, update the task plan; this assessment only changes
when the underlying inventory, candidates, tradeoffs, or risks shift.

---

## 8. Summary

The orchestrator MCP can absorb the same four AHMCP learnings — discriminated
tools (AHMCP-6), v2 envelope dict-return (AHMCP-3 / AHMCP-7, **already inherited
for free**), and bounded reads (AHMCP-1) — and shrink its public surface from
**38 tools to 16** (−22 / ~58 %) while cutting the cold-start `tools/list` cost
roughly in half. The pattern is proven, the migration is sliceable, and the most
embarrassing half-state (`manage_worker` overlapping the granular `worker_*`
tools) is also the cheapest first slice. The work is additive in Slice A so it
can land behind a deprecation window without breaking external consumers.
