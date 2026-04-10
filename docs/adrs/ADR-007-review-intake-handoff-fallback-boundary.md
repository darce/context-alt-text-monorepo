# ADR-007: Review Intake Handoff Fallback Boundary

> **Metadata**
>
> - **Date**: 2026-04-10
> - **Author**: Claude Opus 4.6
> - **Status**: Proposed
>
> **Purpose:** Resolves the design question of how handoff-only callers access
> review-intake data without reimplementing the orchestrator compound packet.
> The assessment identified that `search_handoff` cannot query `verified_tests`
> and that no deterministic handoff-only fallback path exists for cold-start
> review. This ADR chooses between extending handoff primitives, adding a
> second compound packet on handoff, or extracting shared packet logic.
>
> **Pipeline position:** Assessment -> Spec -> **ADR** -> Task Plan -> Implementation.
> Triggered by assessment finding F3 (handoff-only fallback gap) and F4
> (ownership boundary preservation).

---

## Status

Proposed

## Date

2026-04-10

## Context

Cold-start reviewers who load only `agent-handoff-mcp` (without `agent-orchestrator-mcp`)
cannot perform deterministic review intake. The canonical slice review packet lives on
orchestrator (`get_latest_slice_review_packet`), and the handoff read surface is task-centric
(`load_session`, `search_handoff`, `get_handoff_state`) rather than slice-centric. This forces
handoff-only callers into multi-read archaeology to answer "what changed, what passed, what
findings remain, is this merge-ready?"

The assessment (`packages/agent-handoff-mcp/docs/assessments/agent-handoff-mcp-review-intake-tooling-proposal.md`)
established that:

- **F1:** The canonical packet already exists on orchestrator (contract: `docs/agentic/contracts/agent-orchestrator-mcp.md:56`; implementation: `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/slice_review_packet.py:282`).
- **F2:** `verified_tests` rows are persisted in handoff but not queryable through `search_handoff` (`packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py:132` limits record types to decision, finding, blocker, action).
- **F3:** No deterministic handoff-only fallback path exists for slice-level review.
- **F4:** The ownership boundary (compound/cross-task on orchestrator, primitives on handoff) is explicitly documented in both contracts.
- **F5:** The orchestrator packet builder contains multi-source fallback logic (worker reports, rationale parsing, verified-test lookup) that should not be reimplemented.

### Constraints from prior review

- The handoff/orchestrator boundary established during the packaging epic must not be moved. Compound review-summary tools remain on orchestrator.
- `verified_tests` is already a durable ledger table with the right schema; the gap is queryability, not storage.
- The orchestrator packet already implements deterministic fallback chains (decision JSON -> worker report -> rationale parse for changed files; worker report -> `verified_tests` for test commands). Reimplementing this logic is a regression risk, not a feature.

## Current State Inventory

### Handoff read surfaces (`agent-handoff-mcp`)

| Surface | Type | Returns | Slice-aware? |
|---------|------|---------|--------------|
| `get_handoff_state` | query | Active task state, bounded sections | No |
| `load_session` | compound query | State + open findings | No |
| `search_handoff` | FTS generator | Ranked snippets over 4 record types | No |
| `review_findings(operation="list")` | query | Findings by status/severity | No |
| `handoff_close_check` | generator | Merge-readiness verdict | No (task-level) |

`search_handoff` validates against `_VALID_RECORD_TYPES = frozenset({"decision", "finding", "blocker", "action"})` at `core.py:132`. No FTS table exists for `verified_tests`.

### Orchestrator compound surfaces (`agent-orchestrator-mcp`)

| Surface | Type | Returns | Slice-aware? |
|---------|------|---------|--------------|
| `get_latest_slice_review_packet` | query | Deterministic packet for latest slice-complete decision | Yes |
| `get_review_findings_summary` | generator | Aggregated counts + top open findings | No (task-level) |
| `reconcile_review_findings` | generator | Compares findings with current files | No |

### Downstream surfaces that must migrate together

- `docs/agentic/contracts/agent-handoff-mcp.md` -- contract must document any new record type or read surface
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` -- `_VALID_RECORD_TYPES` and `search_handoff`
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py` -- FTS table creation if `verified_tests` gains FTS
- `docs/agentic/rules/branch-review-guide.md` -- fallback guidance for handoff-only review intake
- `docs/agentic/rules/planning-review-guide.md` -- same fallback guidance

## Decision

**Extend handoff primitives and document a deterministic multi-call fallback sequence. Do not build a second compound packet on handoff.**

Handoff-only callers will use a documented sequence of existing and new primitive reads to reconstruct review-intake context. The orchestrator packet remains the canonical compound surface for callers that have both servers loaded.

### Chosen design rules

1. **Add `verified_test` as a searchable record type in `search_handoff`.** Extend `_VALID_RECORD_TYPES` to include `verified_test`. Create a `verified_tests_fts` FTS5 virtual table over `command || ' ' || COALESCE(result, '')` with the same tokenizer and unindexed scope columns as existing FTS tables. This makes test evidence discoverable through the same search surface reviewers already use.

2. **Add a `get_verified_tests` primitive read to handoff.** A targeted query surface that returns verified-test rows filtered by `task_ref`, optional `lane_id`, optional `branch`, optional `commit_sha`, and optional `passed` status. Ordered by `verified_at DESC` with a configurable `limit` (default 20). This closes the join gap between "a test command was listed in the packet" and "the actual verification row passed on commit X."

3. **Do not build a compound packet on handoff.** The packet assembly logic (multi-source fallback for changed files, worker-report matching, rationale extraction) stays exclusively on orchestrator. Handoff does not import, delegate to, or reimplement any of `_build_packet_for_decision`, `_matching_worker_report`, `_extract_changed_files_from_rationale`, or `_matching_test_commands`.

4. **Document the handoff-only fallback sequence explicitly.** Both review guides gain a "Handoff-only fallback" section that specifies the deterministic multi-call sequence:
   1. `load_session` -- get task state + open findings
   2. `search_handoff(query="slice_complete", record_types=["decision"], limit=1)` -- find the latest slice-complete decision
   3. `get_verified_tests(task_ref=..., commit_sha=<from decision>)` -- get test evidence for that slice
   4. `review_findings(operation="list", status="open")` -- confirm finding state
   This is not a compound tool; it is a documented recipe that any caller can follow.

5. **The orchestrator packet remains the preferred path.** When both servers are loaded, callers should use `get_latest_slice_review_packet` and not the fallback sequence. The fallback is explicitly a degraded path for contexts where orchestrator is unavailable.

### Target outcome

- Handoff-only callers can complete cold-start review intake in 4 deterministic calls (down from unbounded archaeology).
- No new compound tool on handoff; tool surface grows by exactly one new read (`get_verified_tests`) and one new FTS record type.
- Zero packet-assembly logic duplication between the two packages.

## Why This Decision

### Preserves the established ownership boundary

The packaging epic resolved which package owns what. Moving compound review-summary logic back to handoff would re-open that ownership question. By adding only primitives to handoff, each package retains its defined responsibility: handoff owns ledger CRUD, orchestrator owns cross-task aggregation.

### Avoids packet logic drift

The orchestrator packet builder at `slice_review_packet.py` contains 5 internal functions with worker-report scoring, rationale parsing, plan-cursor lookup, and multi-source fallback chains. A second packet builder on handoff would need to replicate or delegate to this logic. Replication drifts; delegation crosses the package boundary in the wrong direction.

### Closes the actual gap with minimal surface growth

The assessment identified two concrete missing primitives: verified-test queryability (F2) and a deterministic handoff-only sequence (F3). Both are addressed by one new read surface and one FTS extension. The documented fallback sequence provides determinism without compound-tool complexity.

## Alternatives Considered

### 1. Lightweight compound packet on handoff (`get_review_intake_summary`)

Rejected.

This would build a simpler packet-shaped response on handoff using only ledger-native data (latest slice-complete decision + verified tests + open findings). While simpler than the full orchestrator packet, it still reimplements the "find latest slice_complete decision and assemble context around it" logic. Over time, callers would expect it to match the orchestrator packet's fields, creating pressure to import orchestrator packet logic into handoff or to maintain two diverging packet shapes. The assessment's F5 finding documents the specific fallback chain that would need duplication.

### 2. Extract shared packet-building library

Rejected.

Moving `_build_packet_for_decision` and its helper functions into a shared package (e.g., `shared-contracts`) would make the logic available to both servers. However, the packet builder depends on worker reports, plan cursors, and lane-specific queries that are orchestrator concerns -- they don't belong in a shared library. The resulting shared package would either be a dumping ground for orchestrator-specific logic or would require complex dependency injection to abstract away the data sources. This trades a simple ownership model for accidental coupling.

### 3. Make orchestrator always loaded

Rejected.

Loading both servers in every context would eliminate the handoff-only fallback problem by definition. But the MCP loading protocol (`docs/agentic/rules/mcp-loading-protocol.md`) deliberately keeps orchestrator on-demand to reduce tool-surface noise in contexts that don't need lane management, worker dispatch, or cross-task queries. Forcing it always-on defeats that design and adds tool surface to every session regardless of need.

## Consequences

### Positive

- Cold-start review intake becomes deterministic for handoff-only callers (4-call documented sequence).
- `verified_tests` become discoverable through the same `search_handoff` FTS surface used for decisions, findings, blockers, and actions.
- Package ownership boundary stays clean: no orchestrator logic migrates to handoff.
- The spec can proceed with Tier 1/2 items without boundary ambiguity -- no Tier 3 ADR-gated items remain for the boundary question.

### Negative

- The handoff-only fallback is 4 calls, not 1. Callers who need single-call review intake must load orchestrator.
- The `get_verified_tests` read surface is narrow (only verified tests, not the full slice context). Callers who want changed files and contract files from the handoff-only path must parse them from the slice-complete decision's rationale text, which is less reliable than the orchestrator packet's structured fields.
- Adding `verified_test` to `search_handoff` requires a new FTS5 virtual table and a schema migration in `shared_schema.py` (though this is a baseline schema edit per the greenfield policy, not a data migration).

### Guardrails for the follow-on implementation task

- **No orchestrator imports in handoff.** The handoff package must not import from `agent_orchestrator_mcp` at any level. The new `get_verified_tests` read and the FTS extension must use only handoff-native data access.
- **FTS table parity.** The new `verified_tests_fts` table must use the same tokenizer (`porter unicode61`) and unindexed column pattern as existing FTS tables in `shared_schema.py`.
- **Contract-first.** Update `docs/agentic/contracts/agent-handoff-mcp.md` to document `get_verified_tests` and the new `verified_test` record type in `search_handoff` before or in the same slice as the implementation.
- **Fallback docs land with the primitives.** The review-guide fallback sections must ship in the same task plan as the handoff primitive changes, not as a deferred documentation follow-up.
- **No compound assembly on handoff.** If a future spec proposes a compound `get_review_packet` on handoff, that proposal must be treated as a new ADR because it reverses this decision's boundary preservation.

## References

- Assessment: `packages/agent-handoff-mcp/docs/assessments/agent-handoff-mcp-review-intake-tooling-proposal.md`
- Handoff contract: `docs/agentic/contracts/agent-handoff-mcp.md`
- Orchestrator contract: `docs/agentic/contracts/agent-orchestrator-mcp.md`
- Packet implementation: `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/slice_review_packet.py`
- Handoff search: `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`
- Handoff schema: `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py`
- MCP loading protocol: `docs/agentic/rules/mcp-loading-protocol.md`
- Packaging epic: `packages/agent-handoff-mcp/docs/epics/agent-handoff-mcp-packaging-epic.md`
- Spec: `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-review-intake-handoff-fallback-spec.md`
- Implementation task plan (Tier 1): `packages/agent-handoff-mcp/docs/tasks/AHMCP-8-verified-test-search-and-read-surfaces-task-plan.md`
- Implementation task plan (Tier 2): `packages/agent-handoff-mcp/docs/tasks/AHMCP-9-review-intake-fallback-adoption-docs-task-plan.md`
