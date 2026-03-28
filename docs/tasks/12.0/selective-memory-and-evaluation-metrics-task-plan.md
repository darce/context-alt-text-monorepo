# Selective Memory and Evaluation Metrics Hardening

## Objective

Finish the remaining in-scope work from Phase 4 (3 unchecked items) and Phase 5 (4 unchecked items) of the agentic process-hardening epic. When complete, the epic should have no remaining active implementation items outside confirmed post-v0.3.0 deferrals.

## Problem Statement

Phase 4 has three open implementation items: (1) no structured progress/error/status semantics for process automation surfaces; status values are inline string literals in SQLite CHECK constraints with no Python-side enum types, (2) handoff actor provenance lacks a centralized builder; callers construct `WriteActor` dicts inline despite `_resolve_write_actor()` existing, and (3) no selective-memory MCP surfaces for archival summaries or lane-activity compression. Phase 5 has four open items for evaluation metrics and review loops that have no derivation paths defined.

Critically, `get_handoff_state` (core.py L1276) already accepts configurable `top_n_*` parameters and IS the active-task brief surface. A separate "active-brief" tool would duplicate it. The real gaps are: (a) lane-activity compression for archival, (b) status enum consolidation, (c) actor-construction helper, and (d) metrics with concrete derivation paths from existing DB schema.

## Constraints

- Preserve backward compatibility for existing MCP callers. New metrics and retrieval helpers must be additive, not breaking changes to current `agent-handoff-mcp` surfaces.
- Keep selective-memory helpers grounded in current handoff state and artifact storage rather than inventing a second memory system beside MCP.
- Do not turn deferred post-v0.3.0 items into silent scope creep. Repo-wide model-quality evals, generalized dashboards, and TUI follow-on work stay in `docs/deferred-features/`.

## Workflow Principles

- Measure process behavior through durable state and proof, not chat impressions.
- Add the cheapest useful retrieval surface first: active-task brief, targeted retrieval, then archival summary.
- Keep each slice behavior-plus-proof complete: metrics, docs, and tests must land together.

## Terminology

- **Active-task brief**: A compact MCP-generated summary optimized for session start and hot-state loading.
- **Archival summary**: A compressed, retrieval-friendly view of older task state that replaces replaying full cold history.
- **Planning-review drift**: A measurable mismatch between planned contract/scope statements and actual implementation or review findings.
- **Performance-evidence coverage**: Whether high-risk changes include the expected latency, queue, retry, or contention proof.

## Current State Analysis

- Phase 4 still has two unchecked implementation items: no selective-memory MCP surfaces for active-task briefs, targeted retrieval, and archival summaries; and no structured progress/error/status semantics for those process-automation surfaces.
- Phase 5 now has the initial metrics and audit workflow, but still lacks runtime-parity coverage, planning-review drift, performance-evidence coverage, resolved-from-hot-state ratio, stale-artifact/archive-rate metrics, and a narrowed or measurable `ctx7` token-cost outcome.
- The epic’s post-v0.3.0 items are true deferred work, not the next active task, and already live under `docs/deferred-features/`; the remaining active work is to finish the still-open Phase 4/5 implementation items and then perform an honest final epic sync.

## Target Outcome

The MCP layer exposes small, intentional memory surfaces for session startup and archival lookup, and the ACE metrics snapshot can report the remaining process-health signals that matter for this repo’s workflow. The epic retains only active implementation work in its in-progress phases, while true post-v0.3.0 backlog is documented separately under `docs/deferred-features/`.

## Context Loading

- Rules: `docs/agentic/instructions.md`, `docs/agentic/rules/development-workflow.md`, `docs/agentic/rules/branch-review-guide.md`, `docs/agentic/rules/planning-review-guide.md`
- Contracts: `docs/agentic/contracts/agent-handoff-mcp.md`
- Handoff/MCP state: task ref `agentic-development-process-hardening-epic`, recent decisions from MCP handoff state for the current branch, and any open findings before implementation starts
- External docs via `ctx7` only if: current SQLite FTS5 or MCP SDK behavior must be verified for a new retrieval surface

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| MCP selective-memory surfaces | agentic-tooling | `docs/agentic/contracts/agent-handoff-mcp.md` | Add additive active-brief / archival-summary style helpers or documented compact presets, with explicit status/error semantics | Yes; current handoff tools must continue to work unchanged | MCP tests + contract doc |
| ACE metrics snapshot | agentic-tooling | `docs/agentic/contracts/agent-handoff-mcp.md` | Add additive metrics for planning drift, runtime-parity coverage, evidence coverage, and archive health where derivable from existing state | Yes; existing snapshot keys preserved | `test_ace_metrics.py` + live snapshot |
| Epic/deferred backlog sync | agentic-tooling | `docs/epics/v0.3.0/agentic-development-process-hardening-epic.md`, `docs/deferred-features/README.md` | Reuse the existing deferred-features note and leave the epic in a truthful final state | No; docs-only | manual doc consistency review |

## Proposed Solution

Land the remaining work in four slices. First, add selective-memory MCP helpers plus the missing structured status/error semantics and the contract/docs that explain them. Second, extend the metrics snapshot with only the remaining process signals that can be derived from existing state, and explicitly scope any needed new collection signals. Third, wire the data-pattern/latency review loop and narrow the `ctx7` deliverable to something this repo can actually observe. Fourth, perform the last epic/deferred-features sync check so the remaining active work is truthful after Slices 1-3 land.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| tooling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Add/select selective-memory generator/query surfaces for active-task briefs and archival summaries, plus structured progress/error/status semantics where new helpers are introduced |
| tooling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Register any new additive MCP surfaces |
| tooling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_metrics.py` | Add remaining measurable process-health and selective-memory metrics |
| test | `packages/agent-handoff-mcp/tests/` | Add or extend tests for new MCP surfaces and metrics |
| contract | `docs/agentic/contracts/agent-handoff-mcp.md` | Document new retrieval/metrics surfaces and output shapes |
| rules | `docs/agentic/instructions.md` | Add the final data-pattern/latency review loop and narrowed `ctx7` evaluation language |
| docs | `docs/epics/v0.3.0/agentic-development-process-hardening-epic.md` | Remove active/deferred ambiguity after implementation |
| docs | `docs/deferred-features/agentic-process-hardening-post-v0.3.0.md` | Hold true deferred backlog items from this epic |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_reflect.py` | Existing process-evidence collector that should stay aligned with the new pruning/evaluation loop |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_ready.py` | Useful source for boundary/evidence semantics when measuring coverage |
| `packages/agent-handoff-mcp/README.md` | Must stay in sync with any new MCP retrieval or metrics surface |
| `docs/deferred-features/README.md` | Needs the new deferred-features entry for this epic |

## Verification Strategy

- Deterministic tests:
  - `PYTHONPATH=packages/agent-handoff-mcp/src PYENV_VERSION=description-service python3 -m pytest packages/agent-handoff-mcp/tests/test_ace_metrics.py -q`
  - `PYTHONPATH=packages/agent-handoff-mcp/src PYENV_VERSION=description-service python3 -m pytest packages/agent-handoff-mcp/tests/test_review_ready.py -q`
- Runtime-parity / environment checks:
  - `PYTHONPATH=packages/agent-handoff-mcp/src PYENV_VERSION=description-service python3 -m agent_handoff_mcp.orchestration.ace_metrics --task-ref agentic-development-process-hardening-epic --state-dir .task-state --logs-dir logs --output-format json`
- Contract/fixture verification:
  - Verify `docs/agentic/contracts/agent-handoff-mcp.md` matches any new MCP surface and snapshot keys
- String-search verification:
  - Confirm every Slice 3 guidance reference resolves with `rg` against the referenced MCP tools, rule anchors, and deferred-features paths
- Manual verification:
  - Review the epic and deferred-features docs together to confirm active work is kept in the task plan and true deferred work is only in `docs/deferred-features/`

## Slice Delivery

### Slice 1: Selective-Memory MCP Surfaces

**Goal**: Add MCP-native selective-memory surfaces so agents can retrieve the cheapest useful handoff context without replaying full task history, and make their status/error semantics explicit.

Changes:

- Add an additive active-task brief surface that returns a compact startup payload:
  - `task_ref`, `objective`, `status`, `current_lane`
  - blocker/action/finding/test counts
  - compact summaries of recent decisions, open findings, and recent tests
- Add an additive archival-summary surface that returns a compressed, retrieval-friendly view of archived task state instead of replaying full exported snapshots
- If the active brief is implemented as a preset or wrapper over `get_handoff_state`, document that explicitly and keep the value-add focused on smaller defaults and stable compact shape rather than duplicating hot-state fields
- Define structured progress/error/status semantics for any new helper surface so callers can distinguish `ok`, `not_found`, `no_archive`, and malformed or unsupported input outcomes without inferring from prose
- Document the new retrieval surfaces in the MCP contract and README
- Add deterministic tests covering payload shape and fallback behavior

Proof:

- New MCP tests pass
- Contract doc and README describe the new surfaces without breaking existing ones

### Slice 2: Remaining Process-Health Metrics

**Goal**: Add the remaining measurable evaluation signals to the ACE metrics snapshot.

Changes:

- Add only the remaining process-health metrics that have a concrete derivation path from existing state, and document each derivation in code/comments/tests:
  - `runtime_parity_coverage`
    Data source: `verified_tests.command` plus repo test-command conventions
    Derivation: ratio of boundary-touching slices whose verification commands include the runtime-parity checks required by the rules
    Empty semantics: `null` / `data_available=false`
  - `planning_review_drift_rate`
    Data source: review findings and decisions explicitly tagged as planning-review outputs
    Derivation: ratio of reviewed plans with at least one planning-review finding to reviewed plans in the evaluation window
    Empty semantics: `null` / `data_available=false`
  - `performance_evidence_coverage`
    Data source: verification evidence in decisions/tests for slices marked performance-sensitive by plan/review rules
    Derivation: ratio of performance-sensitive slices whose recorded proof includes required latency/queue/retry evidence
    Empty semantics: `null` / `data_available=false`
  - `stale_artifact_rate`
    Data source: `mcp-artifacts.db` timestamps
    Derivation: ratio of artifact sources older than the configured stale threshold
    Empty semantics: `0.0` when no artifacts exist
- Do not implement `resolved_from_hot_state_ratio` in this slice unless a real collection signal is added first; if current state cannot support it without new logging, leave it as an explicit follow-on instrumentation task rather than inventing a fake metric
- Keep the metrics additive and backward-compatible
- Add deterministic tests and live snapshot proof for the new sections

Proof:

- `test_ace_metrics.py` passes with new metric coverage
- Live metrics snapshot emits non-null values or explicit `n/a` semantics for the new keys

### Slice 3: Data-Pattern, Latency, and ctx7 Evaluation Loop

**Goal**: Finish the process guidance for data-pattern health, latency review, and the narrowed `ctx7` deliverable.

Changes:

- Add the deferred data-pattern/latency health review loop to `instructions.md`
- Narrow the `ctx7` deliverable to a credible observable outcome for this repo, or explicitly state the boundary where token-cost reduction cannot be measured locally
- Cross-link the evaluation guidance back to pruning and review workflows

Proof:

- `rg` or equivalent string checks confirm every referenced MCP tool, file path, and rule anchor exists
- The guidance is executable from cold start without inventing new tooling
- The epic language no longer promises a measurement this repo cannot actually produce

### Slice 4: Final Epic Sync

**Goal**: Leave the epic in a stable, truthful state after Slices 1-3 land.

Changes:

- Reuse the existing deferred-features note created in decision `887`; do not recreate it
- Synchronize the epic so only genuinely active remaining work is tracked in the in-progress phases after this task lands
- Verify that no active/deferred ambiguity remains between the epic and the deferred-features note

Proof:

- The epic’s remaining incomplete items map cleanly to active task work
- True deferred items remain documented in `docs/deferred-features/` and no longer mixed into active execution planning

---

# Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed whether external dependency context requires `ctx7`.
- [ ] Recorded boundary ownership and compatibility expectations if any contract is touched.

## Slice 1: Selective-Memory MCP Surfaces

- [ ] Added active-brief and archival-summary MCP surfaces with explicit payload/status semantics.
- [ ] Updated MCP contract and README in the same slice.
- [ ] Captured deterministic verification for the new surfaces.

## Slice 2: Remaining Process-Health Metrics

- [ ] Added the remaining measurable process-health metrics with documented derivation paths.
- [ ] Kept the metrics snapshot backward-compatible.
- [ ] Captured focused metric tests and live snapshot verification.

## Slice 3: Data-Pattern, Latency, and ctx7 Evaluation Loop

- [ ] Added the data-pattern and latency review loop to instructions.
- [ ] Narrowed or clarified the `ctx7` measurement deliverable.
- [ ] Captured deterministic doc-proof that the guidance is executable from cold start.

## Slice 4: Final Epic Sync

- [ ] Reused the existing deferred-features note without duplicating prior work.
- [ ] Updated the epic so active remaining work stays in active phases only.
- [ ] Captured consistency verification across epic, task plan, and deferred-features docs.

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [ ] Runtime-parity checks are included where tests can mask real behavior.
- [ ] Handoff decision records the change, verification, and any contract implications.

## Stretch Goals

- [ ] Add compact markdown examples or CLI examples for the new selective-memory surfaces if the contract shape is otherwise hard to discover.

## Success Criteria

- [ ] Agents can load a compact active-task brief and targeted archival summary without replaying full handoff history.
- [ ] The ACE metrics snapshot covers the remaining measurable process-quality signals still called for by the epic.
- [ ] The epic cleanly separates active work from true post-v0.3.0 deferred backlog.
