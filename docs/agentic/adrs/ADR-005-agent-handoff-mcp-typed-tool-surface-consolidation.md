# ADR-005: agent-handoff-mcp Typed Tool Surface Consolidation

## Status

Proposed

## Date

2026-04-02

## Context

The output-contract v2 work fixed the response-shape and state-keeping problems that were making `agent-handoff-mcp` noisy and stale across sessions. One architectural question remained intentionally unresolved: how far the tool surface should be consolidated, and by what typed-schema strategy.

The current surface is large enough to carry real discovery and prompt-cost overhead. The live package exposes 28 tools in the extended profile and 16 in the core profile, as proven by the transport and adapter tests in `packages/agent-handoff-mcp/tests/test_stdio.py` and `packages/agent-handoff-mcp/tests/test_adapters.py`. The large surface is not accidental, however. Many tools have distinct audit semantics, distinct mutation guarantees, or distinct transport expectations, and flattening all of them behind one generic `record/update/list` interface would make the catalog smaller at the cost of weaker schemas and less legible semantics.

The approved output-contract v2 spec already captured two hard constraints:

1. A single opaque `payload: dict` model is not acceptable.
2. Any consolidation must preserve typed MCP schemas per entity family.

This ADR chooses the consolidation model that implementation should follow.

## Current Tool Inventory

The live handoff package currently exposes these tool families:

### Task state and lifecycle

- `set_handoff_state`
- `get_handoff_state`
- `update_task_status`
- `load_session`
- `close_slice`
- `handoff_close_check`
- `generate_current_task_md`
- `export_handoff_state`
- `import_handoff_state`
- `archive_task_state`
- `audit_decision_ids`

### Next actions and event recording

- `list_next_actions`
- `update_next_actions`
- `record_decision`
- `record_test_result`
- `report_blocker`

### Review findings and review runs

- `record_review_finding`
- `batch_record_review_findings`
- `update_review_finding`
- `list_review_findings`
- `record_review_run`
- `list_review_runs`
- `get_review_coverage`

### Artifacts and search

- `record_artifact`
- `search_artifacts`
- `get_artifact`
- `purge_artifacts`
- `search_handoff`

## Downstream Enumerators That Must Be Migrated Together

Any consolidation implementation will have to update these surfaces in the same slice as the code change:

- `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`; live tool registration and descriptions
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`; CLI dispatch and argument exposure
- `packages/agent-handoff-mcp/tests/test_cli.py`; command-surface assertions
- `packages/agent-handoff-mcp/tests/test_stdio.py`; stdio tool enumeration and profile counts
- `packages/agent-handoff-mcp/tests/test_http.py`; HTTP tool enumeration
- `packages/agent-handoff-mcp/tests/test_adapters.py`; adapter expectations and profile counts
- `docs/agentic/contracts/agent-handoff-mcp.md`; published tool contract

This migration scope is one reason the decision must be taken at ADR level rather than improvised inside an implementation task.

## Decision

Adopt a **hybrid domain-tool consolidation model**.

The package will not move to one global `record`, `update`, or `list` tool. Instead, it will consolidate only high-homology domains behind **domain-scoped tools with discriminated typed operation models**, while keeping lifecycle, generator, export/import, and search surfaces explicit.

### Chosen design rules

1. **Keep lifecycle and generator tools explicit.**
   `get_handoff_state`, `set_handoff_state`, `close_slice`, `handoff_close_check`, `generate_current_task_md`, `export_handoff_state`, `import_handoff_state`, `archive_task_state`, `audit_decision_ids`, and `search_handoff` remain explicit because they carry compound behavior, generated artifacts, or lifecycle semantics that should stay obvious in the catalog.

2. **Fold status-only task updates into `set_handoff_state`.**
   `update_task_status` becomes a compatibility alias and is later retired. Its semantics are a subset of `set_handoff_state` rather than an independent domain.

3. **Consolidate event writes behind one domain tool.**
   `record_decision`, `record_test_result`, and `report_blocker` become one domain tool, tentatively named `record_event`, with a discriminated union keyed by event kind. Each event kind retains its own typed payload model.

4. **Consolidate next-action reads and writes by domain, not by generic CRUD verb.**
   `list_next_actions` and `update_next_actions` become one domain tool, tentatively named `next_actions`, with typed operation variants for list, add, update, complete, and skip.

5. **Consolidate review findings by domain, including batch as a first-class typed variant.**
   `record_review_finding`, `update_review_finding`, `batch_record_review_findings`, and `list_review_findings` become one domain tool, tentatively named `review_findings`, with discriminated variants for record, batch record, update, and list. Atomic batch semantics remain explicit in the batch variant schema rather than hiding behind an untyped array.

6. **Consolidate review-run and coverage reads/writes by domain.**
   `record_review_run`, `list_review_runs`, and `get_review_coverage` become one domain tool, tentatively named `review_runs`, with typed variants for record, list, and coverage.

7. **Consolidate artifact operations by domain.**
   `record_artifact`, `search_artifacts`, `get_artifact`, and `purge_artifacts` become one domain tool, tentatively named `artifacts`, with typed variants per operation.

8. **Retire `load_session` after the parameterized read surfaces are in place.**
   `load_session` remains only as a short-lived compatibility alias while clients move to the parameterized read path. It is not part of the long-term consolidated surface.

### Target outcome

The long-term extended surface should land in the **15 to 18 tool** range, not 12 by force. The goal is a smaller, clearer, still-typed catalog; not maximum collapse.

## Why This Decision

### It preserves typed discoverability

The tool catalog remains useful only if clients can see the fields that belong to each operation. Domain-scoped discriminated models preserve that information. A single cross-domain `record/update/list` surface would make every request model look like a grab bag of optional fields.

### It keeps audit semantics legible

`close_slice`, `generate_current_task_md`, and export/import operations mean something materially different from row-level record or list operations. Keeping those tools explicit preserves the current audit vocabulary and makes completion decisions easier to scan.

### It reduces tool count where the structure is genuinely repetitive

The families above already share obvious schema skeletons. Consolidating them by domain is a real simplification. Keeping the non-homologous lifecycle tools explicit avoids false simplification.

### It gives implementation a bounded fallback

If a specific domain tool produces unreadable FastMCP schemas in clients, only that domain needs to split back out. The package does not have to abandon the entire consolidation strategy.

## Alternatives Considered

### 1. One global `record/update/list` tool set across all entities

Rejected.

This was the highest-risk option from the spec review. It optimizes count at the expense of schema quality, audit clarity, and discoverability. It also pushes too much semantic responsibility into freeform documentation rather than the live tool signature.

### 2. Keep the current explicit surface and rely on core versus extended profiles only

Rejected.

Profiles hide tools; they do not remove schema cost for the profile that still exposes them, and they do nothing to reduce conceptual duplication. The current surface remains larger than it needs to be even after the read-parameter work.

### 3. Full domain consolidation, including lifecycle and generator tools

Rejected.

This would make the catalog smaller, but it would blur the distinction between query/mutation row operations and compound lifecycle operations such as `close_slice`, export/import, and render generation. Those boundaries are worth keeping visible.

## Consequences

### Positive

- The implementation target is now clear enough to plan against.
- The package can reduce catalog size materially without giving up typed schemas.
- The migration scope is explicit, including every downstream enumerator that must move together.
- The output-contract v2 spec can now point at a reviewed design instead of a placeholder.

### Negative

- The implementation is still non-trivial; transport tests, CLI dispatch, and the contract doc all move together.
- Discriminated unions across some domains may still prove awkward in some clients.
- The exact final tool names are intentionally left to the implementation task, because schema ergonomics may require small naming adjustments.

### Guardrails For The Follow-On Implementation Task

- No global cross-domain `record/update/list` tool may be introduced.
- Every consolidated domain tool must expose typed operation models, not an opaque `payload: dict`.
- `close_slice`, `generate_current_task_md`, `handoff_close_check`, `export_handoff_state`, `import_handoff_state`, `archive_task_state`, `audit_decision_ids`, and `search_handoff` stay explicit.
- `docs/agentic/contracts/agent-handoff-mcp.md`, `api.py`, `cli.py`, `test_cli.py`, `test_stdio.py`, `test_http.py`, and `test_adapters.py` must be updated in the same implementation slice.
- The implementation task should target a final extended profile count in the 15 to 18 range and justify any deviation.

## References

- Spec: [packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-output-contract-v2-spec.md](../../packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-output-contract-v2-spec.md)
- Task plan: [packages/agent-handoff-mcp/docs/tasks/AHMCP-4-typed-tool-surface-consolidation-adr-task-plan.md](../../packages/agent-handoff-mcp/docs/tasks/AHMCP-4-typed-tool-surface-consolidation-adr-task-plan.md)
- Related task plans:
  - [packages/agent-handoff-mcp/docs/tasks/AHMCP-1-parameterize-handoff-mcp-read-surfaces-task-plan.md](../../packages/agent-handoff-mcp/docs/tasks/AHMCP-1-parameterize-handoff-mcp-read-surfaces-task-plan.md)
  - [packages/agent-handoff-mcp/docs/tasks/AHMCP-2-bounded-current-task-rendering-and-mutation-output-task-plan.md](../../packages/agent-handoff-mcp/docs/tasks/AHMCP-2-bounded-current-task-rendering-and-mutation-output-task-plan.md)
  - [packages/agent-handoff-mcp/docs/tasks/AHMCP-3-response-envelope-and-output-contract-v2-rollout-task-plan.md](../../packages/agent-handoff-mcp/docs/tasks/AHMCP-3-response-envelope-and-output-contract-v2-rollout-task-plan.md)
