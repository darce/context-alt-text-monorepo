# Evaluation and Release Audit Layer

## Objective

Add a repeatable process-evaluation layer so the repo can measure whether the hardening work from Phases 1-4 is improving execution quality, and define a structured multi-lens pre-merge audit model for cross-boundary changes.

## Problem Statement

Phases 1-4 of the agentic development process hardening epic added context-loading protocols, contract ownership, runtime-parity gates, review-readiness commands, skills, and MCP tooling. These surfaces enforce process discipline at the point of execution, but three evaluation-level gaps remain:

1. **No measurable process health baseline.** The repo cannot answer "did the hardening work reduce contract drift, reopened findings, or planning-review mismatch?" because no metrics are defined or tracked. `ace_metrics.py` already collects token burn, context pressure, lane health, FTS5 retrieval, and ACE documentation fitness, but process-quality signals (contract co-change rate, reopened-finding rate, handoff completeness, runtime-parity test coverage) are not captured.
2. **No structured multi-lens audit for cross-boundary changes.** The branch review guide applies one reviewer perspective. Cross-boundary changes that touch backend, proxy, frontend, and contracts together would benefit from a staged audit with distinct architecture, QA/state-matrix, and contract/compliance lenses, modeled on the `product-deploy-agents` pipeline. Currently, whether a second lens is applied depends on ad hoc reviewer judgment.
3. **No periodic rule and skill pruning loop.** Rules and skills accumulate. `instructions.md` already has ACE strategy-bullet counters (`helpful`/`harmful`) and an `ace_reflect` tool, but no defined cadence, trigger, or workflow for pruning low-value rules or evolving skills based on handoff evidence. Skills added in Phase 4 have no feedback path for measuring whether they actually improved execution.

Additionally, two evaluation-adjacent gaps are deferred from Phase 4:

- Handoff-memory health metrics (hot-state size, stale-artifact rate, context-rediscovery frequency) are defined in the epic but have no collection surface.
- `ctx7` adoption metrics (retrieval count, library-id reuse, token-cost reduction) are defined in the epic but are not tracked.

## Constraints

- Process health metrics must be derivable from existing MCP handoff state, `ace_metrics.py` output, and git history. Do not require new runtime instrumentation or external analytics services.
- The multi-lens audit model is a documented workflow, not a new tool. It uses existing review-finding and decision-recording MCP tools. Automated multi-agent dispatch is out of scope (that is an orchestration task, not an evaluation task).
- Rule and skill pruning is a periodic human-triggered workflow, not an automated system. The deliverable is the workflow definition and trigger criteria, not a daemon.
- Metrics collection may extend `ace_metrics.py` with new snapshot sections, but must not break existing `get_metrics_summary` callers.
- `ctx7` metrics are guidance-only in this task; token-cost reduction requires external billing data that the repo does not own.

## Workflow Principles

- Measure what matters for process quality, not just execution volume: a high token count is neutral; a high reopened-finding rate or low contract co-change rate is a signal.
- Audit depth should scale with change risk: single-layer docs-only changes get lightweight review; cross-boundary behavior changes get multi-lens audit.
- Rules and skills earn their place through evidence, not seniority: a rule with `helpful=0 harmful>=2` is a pruning candidate regardless of when it was added.
- Evaluation surfaces should close the loop: metrics inform pruning, pruning simplifies guidance, simpler guidance improves metrics.

## Terminology

- **Process health metric**: A measurable signal derived from handoff state, review findings, or git history that indicates whether a process rule is being followed and whether it is effective.
- **Multi-lens audit**: A structured review workflow where distinct reviewer perspectives (architecture, QA/state-matrix, contract/compliance) are applied sequentially to the same diff, with findings recorded independently.
- **Rule pruning**: Removing or demoting a process rule whose evidence counters show it has not prevented real failures or has caused unnecessary friction.
- **Evaluation cadence**: A defined trigger (time-based, task-count-based, or milestone-based) for running the process health evaluation and pruning workflow.

## Current State Analysis

- `ace_metrics.py` collects 6 snapshot sections: token burn, context pressure, FTS5 retrieval, lane health, phase timing, and ACE documentation fitness. Snapshots are appended to `.task-state/metrics.jsonl` and exposed via `get_metrics_summary` MCP tool.
- `ace_reflect.py` parses strategy-bullet counters from instruction files and can apply pending counter updates from `.task-state/ace_reflect_log.jsonl`. The orchestrator daemon emits a warning when unprocessed reflect entries exist.
- `branch-review-guide.md` has an "Escalate To Multi-Lens Audit When" section that lists trigger conditions (security, deploy, architecture, multi-service state machines, persistence, broad UI) but does not define the audit workflow, lens responsibilities, or how findings are recorded per lens.
- `review_ready.py` checks open findings, open blockers, contract co-change, CURRENT_TASK sync, and test evidence, but does not produce process-health trend data.
- `handoff_close_check` evaluates close readiness but not process quality.
- `get_review_findings_summary` returns aggregate counts by status and severity but not rates over time.
- Finding `reopen_count` is tracked per finding in `core.py` but not aggregated into a process metric.
- No metrics exist for contract co-change rate, handoff-decision completeness, or ctx7 reuse.
- No periodic pruning workflow is documented for rules or skills.

## Target Outcome

The repo has a defined set of process health metrics that can be collected from existing handoff state and git history. A multi-lens audit workflow is documented in the review rules so cross-boundary changes receive structured multi-perspective review. A periodic rule and skill pruning workflow exists with defined triggers, evidence thresholds, and handoff documentation. Operators can run `make ace-metrics` or `get_metrics_summary` and see process-quality signals alongside execution metrics. The evaluation layer closes the feedback loop between process rules and their observed impact.

## Context Loading

- Rules: `docs/agentic/rules/branch-review-guide.md` (Escalate To Multi-Lens Audit section), `docs/agentic/instructions.md` (ACE playbook, strategy bullets, curation rules)
- Tooling: `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_metrics.py`, `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_reflect.py`
- Contract: `docs/agentic/contracts/agent-handoff-mcp.md` (get_metrics_summary, get_review_findings_summary, handoff_close_check surfaces)
- Literature: `docs/literature/process/product-deploy-agents/README.md` (multi-lens audit model), `docs/literature/process/agentfactory-book/ch-99-evaluation-quality-gates-drilldown-v2.md` (quality gates)
- Handoff/MCP state: task ref `agentic-development-process-hardening-epic`; Phase 5 checklist status
- External docs via `ctx7` only if: upstream Hypothesis or SQLite FTS5 behavior needs verification during metrics collection

## Contract and Boundary Impact

| Boundary                        | Owner           | Current Contract                                        | Expected Change                                                  | Compatibility Needed?                 | Verification                                  |
| ------------------------------- | --------------- | ------------------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------- | --------------------------------------------- |
| `get_metrics_summary` MCP tool  | agentic-tooling | `docs/agentic/contracts/agent-handoff-mcp.md`           | Add process-health sections to snapshot output                   | Yes; existing snapshot keys preserved | Existing callers still parse current sections |
| Review guide escalation surface | agentic-tooling | `docs/agentic/rules/branch-review-guide.md`             | Expand multi-lens audit from trigger list to workflow definition | No; additive                          | Manual review                                 |
| ACE reflect / pruning surface   | agentic-tooling | `docs/agentic/instructions.md` (curation rules section) | Add periodic pruning workflow and trigger criteria               | No; additive                          | Manual review                                 |

## Proposed Solution

Five slices delivered in dependency order. Slice 1 defines metrics and extends `ace_metrics.py`. Slice 2 adds the multi-lens audit workflow to the review guide. Slice 3 defines the rule and skill pruning workflow. Slice 4 adds handoff-memory and ctx7 evaluation guidance. Slice 5 updates the epic checklist and synchronizes documentation.

## Files and Surfaces to Change

| Surface  | File                                                                            | Change                                                                                                                                    |
| -------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_metrics.py` | Add process-health metric collectors: reopened-finding rate, contract co-change signal, handoff completeness, finding-resolution velocity |
| test     | `packages/agent-handoff-mcp/tests/test_ace_metrics.py`                          | Extend existing suite with unit tests for process-health metric computation                                                               |
| contract | `docs/agentic/contracts/agent-handoff-mcp.md`                                   | Update `get_metrics_summary` description to include process-health sections                                                               |
| rules    | `docs/agentic/rules/branch-review-guide.md`                                     | Expand "Escalate To Multi-Lens Audit" into a full workflow with lens definitions, finding conventions, and completion criteria            |
| rules    | `docs/agentic/instructions.md`                                                  | Add periodic pruning workflow section near existing curation rules                                                                        |
| docs     | `packages/agent-handoff-mcp/README.md`                                          | Synchronize metrics description after snapshot shape changes                                                                              |
| docs     | `docs/agentic/instructions.md`                                                  | Add handoff-memory and ctx7 evaluation guidance                                                                                           |
| docs     | `docs/epics/v0.3.0/agentic-development-process-hardening-epic.md`               | Update Phase 5 checklist items to checked                                                                                                 |

## Related Files

| File                                                                                       | Note                                                                                          |
| ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_reflect.py`            | Strategy-bullet parser and counter updater; pruning workflow references this                  |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_ready.py`           | Review-readiness gate; audit escalation may reference its output                              |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`                                 | Source of truth for finding `reopen_count`, finding status transitions, and close-check logic |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/dashboard_live.py`         | Existing dashboard that imports ace_reflect; may need alignment with new metrics              |
| `docs/literature/process/product-deploy-agents/README.md`                                  | Multi-lens audit pipeline model                                                               |
| `docs/literature/process/agentfactory-book/ch-99-evaluation-quality-gates-drilldown-v2.md` | Quality-gate design principles                                                                |
| `Makefile`                                                                                 | `ace-reflect` and `ace-metrics` targets                                                       |

## Verification Strategy

- Deterministic tests:
  - `cd packages/agent-handoff-mcp && PYENV_VERSION=description-service python3 -m pytest tests/test_ace_metrics.py -q 2>&1 | tee /tmp/pytest_ace_metrics.txt`
- Contract/fixture verification:
  - Verify `get_metrics_summary` output includes new process-health sections without breaking existing section keys
  - Verify `ace_metrics.py` snapshot schema is backward-compatible (new keys added, none removed)
- Manual verification:
  - `make ace-metrics TASK=agentic-development-process-hardening-epic` produces a snapshot with process-health data from current handoff state
  - Multi-lens audit workflow in branch-review-guide is actionable from cold start
  - Pruning workflow triggers and thresholds are clear enough to execute without interpretation

## Slice Delivery

### Slice 1: Process Health Metrics

**Goal**: Define and implement process-quality metric collectors so `get_metrics_summary` includes signals beyond execution volume.

Changes:

- Add a `process_health` section to the `ace_metrics.py` snapshot with these collectors:
  - `reopened_finding_rate`: ratio of findings with `reopen_count >= 1` to total findings, queried from `handoff.db`
  - `finding_resolution_velocity`: median time from finding creation to `fixed` status, in hours
  - `handoff_decision_completeness`: ratio of decisions with structured slice-completion format (contains all four mandatory headings: `## Changes`, `## Verification`, `## Schema / Contract Changes`, and `## Open Threads`) to total decisions; docs-only slices must still include `- none.` placeholders for empty sections
  - `contract_co_change_signal`: boolean per recent boundary-touching commit; derived from `review_ready.py`'s `BOUNDARY_PREFIXES` and `CONTRACT_PREFIXES` against the diff
- Extend existing `test_ace_metrics.py` with unit tests for each collector using synthetic handoff.db data
- Update `get_metrics_summary` contract description in `agent-handoff-mcp.md`
- Synchronize README metrics section

Proof:

- `pytest tests/test_ace_metrics.py` passes with existing tests plus 4+ new tests covering each new collector
- `get_metrics_summary` output includes `process_health` section with non-null values against current task state

### Slice 2: Multi-Lens Audit Workflow

**Goal**: Expand the branch review guide's escalation trigger list into a documented audit workflow with distinct lens responsibilities and finding conventions.

Changes:

- Replace the "Escalate To Multi-Lens Audit When" bullet list in `branch-review-guide.md` with a full "Multi-Lens Audit Workflow" section containing:
  - **Trigger criteria**: unchanged from current list (security, deploy, architecture, multi-service, persistence, broad UI)
  - **Lens definitions**: architecture/reliability, QA/state-matrix, contract/compliance; each with scope, checklist focus, and finding-category bias
  - **Execution flow**: sequential lens application; each lens records findings independently using `review_mode=release_audit` and a lens-specific finding-ID prefix convention (e.g., `ARCH-<id>`, `QA-<id>`, `CONTRACT-<id>`) to classify which lens produced each finding
  - **Completion criteria**: all lenses applied, all HIGH findings resolved or deferred with rationale, summary decision recorded in MCP
  - **Scope limitation**: the audit adds review perspectives, not new tools; it uses existing `record_review_finding` with `review_mode=release_audit` and existing `record_decision` for the summary; per-lens classification is conveyed through finding-ID prefixes, not through new `review_mode` enum values
- Add a brief cross-reference in `development-workflow.md` pointing to the new audit workflow section

Proof:

- The workflow section is actionable by an agent starting from cold context
- Finding-ID prefix conventions are compatible with existing `record_review_finding` parameters; `review_mode=release_audit` is a valid existing value
- No changes to MCP tooling required (verify `review_mode` parameter exists on `record_review_finding`)

### Slice 3: Rule and Skill Pruning Workflow

**Goal**: Define a periodic evidence-driven pruning workflow for process rules and skills so guidance evolves from evidence, not accumulation.

Changes:

- Add a "Periodic Pruning Workflow" section to `instructions.md` adjacent to the existing "Curation rules" section, containing:
  - **Triggers**: after each epic phase completion; after any task with 5+ review findings referencing rules; after 30 calendar days without a pruning pass
  - **Workflow steps**: (1) run `get_metrics_summary` for current process health; (2) run `make ace-reflect` to apply pending counter updates; (3) review pruning candidates (`helpful=0 harmful>=2`); (4) for each candidate, check recent handoff decisions and findings for the rule ID; (5) delete confirmed dead rules, demote marginal rules to a "watch" annotation; (6) review skills for coverage gaps (skills referenced in 0 handoff decisions over the evaluation period are candidates for retirement or consolidation); (7) record a pruning decision in MCP
  - **Evidence thresholds**: rules with `helpful=0 harmful>=2` are automatic pruning candidates; rules with `helpful>=3 harmful=0` are confirmed keepers; everything else is reviewed on case merit
  - **Skill evaluation criteria**: trigger frequency (referenced in decisions/findings), coverage (does the skill's scope overlap with another skill?), freshness (does the skill reference current tooling?), and convergence (do agents using the skill reach completion faster?)
- Update the existing "Curation rules" section to cross-reference the new periodic workflow

Proof:

- The workflow can be executed by running existing `make ace-reflect` + `get_metrics_summary` + handoff queries
- Trigger criteria are observable from MCP state (phase completion, finding count, last pruning date)
- No new tooling or Make targets required

### Slice 4: Handoff-Memory and ctx7 Evaluation Guidance

**Goal**: Define how handoff-memory health and ctx7 adoption are evaluated so the selective-memory and context-assignment policies from Phases 1 and 4 have a feedback path.

Changes:

- Add a "Handoff Memory Health" subsection to the periodic pruning workflow in `instructions.md` with these evaluation questions:
  - Is hot-state load cost growing? (measure: `get_handoff_state` response size trend from `metrics.jsonl`)
  - Are sessions resolving from hot state + targeted search, or replaying full history? (measure: ratio of `search_handoff` calls to `get_handoff_state` calls in worker JSONL logs)
  - Are stale artifacts being archived? (measure: artifact age distribution from `mcp-artifacts.db`)
  - Is context rediscovery happening? (measure: repeated `ctx7` library-id lookups for the same dependency across decisions in the same task)
- Add a `handoff_memory` section to `ace_metrics.py` snapshot that collects:
  - `hot_state_size_bytes`: byte length of `get_handoff_state` JSON response for the active task
  - `total_decisions`: count of decisions in the active task
  - `total_findings`: count of findings in the active task
  - `artifact_source_count`: count of indexed artifact sources
- Add matching tests in `test_ace_metrics.py`
- Add a "ctx7 Adoption" subsection to the periodic pruning workflow with evaluation questions (guidance-only; no automated collection):
  - Are `ctx7` library ids being reused across sessions? (check: search handoff decisions for `ctx7 library id:` strings)
  - Are bulk doc copies still appearing in instruction files or plans? (check: instruction file line count trend)
  - Is targeted retrieval preferred over broad browsing? (check: qualitative review of recent ctx7-referencing decisions)

Proof:

- `ace_metrics.py` `handoff_memory` section produces non-null values from current state
- `test_ace_metrics.py` covers handoff-memory collectors
- Guidance sections reference existing tools and handoff query patterns

### Slice 5: Epic Completion and Documentation Sync

**Goal**: Update the epic Phase 5 checklist to reflect implementation state and synchronize cross-references.

Changes:

- Update `agentic-development-process-hardening-epic.md` Phase 5 checklist and status to match the implemented subset honestly
- Keep Phase 5 marked `in-progress` until the remaining evaluation deliverables are implemented
- Ensure `packages/agent-handoff-mcp/README.md` metrics section reflects the final snapshot shape
- Ensure `docs/agentic/contracts/agent-handoff-mcp.md` `get_metrics_summary` description reflects the final snapshot shape
- Record handoff decision for Slice 5

Proof:

- Epic checklist and Phase 5 status match implementation state
- README and contract doc are synchronized with `ace_metrics.py` snapshot output
- `git diff --check` clean on all modified files

---

# Consolidated Checklist

## Context and Ownership

- [x] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [x] Confirmed `ace_metrics.py` snapshot schema before extending it.
- [x] Verified `record_review_finding` supports `review_mode` parameter before defining audit conventions.

## Slice 1: Process Health Metrics

- [x] Added `process_health` section to `ace_metrics.py` snapshot.
- [x] Implemented `reopened_finding_rate` collector from `handoff.db` finding data.
- [x] Implemented `finding_resolution_velocity` collector.
- [x] Implemented `handoff_decision_completeness` collector.
- [x] Implemented `contract_co_change_signal` collector.
- [x] Extended existing `test_ace_metrics.py` with unit tests for each new collector.
- [x] Updated `get_metrics_summary` description in contract doc.
- [x] Synchronized README metrics section.
- [x] Handoff decision recorded for Slice 1.

## Slice 2: Multi-Lens Audit Workflow

- [x] Expanded "Escalate To Multi-Lens Audit" into full workflow section in `branch-review-guide.md`.
- [x] Defined architecture/reliability, QA/state-matrix, and contract/compliance lens scopes.
- [x] Defined finding-ID prefix conventions for per-lens classification (e.g., `ARCH-`, `QA-`, `CONTRACT-`).
- [x] Defined completion criteria for multi-lens audits.
- [x] Added cross-reference in `development-workflow.md`.
- [x] Verified `review_mode=release_audit` is a valid value on `record_review_finding`.
- [x] Handoff decision recorded for Slice 2.

## Slice 3: Rule and Skill Pruning Workflow

- [x] Added "Periodic Pruning Workflow" section to `instructions.md`.
- [x] Defined trigger criteria (phase completion, finding count, calendar threshold).
- [x] Defined evidence thresholds for pruning candidates and confirmed keepers.
- [x] Defined skill evaluation criteria (trigger frequency, coverage, freshness, convergence).
- [x] Updated existing "Curation rules" section to cross-reference pruning workflow.
- [x] Handoff decision recorded for Slice 3.

## Slice 4: Handoff-Memory and ctx7 Evaluation Guidance

- [x] Added `handoff_memory` section to `ace_metrics.py` snapshot.
- [x] Added handoff-memory health evaluation questions to `instructions.md`.
- [x] Added ctx7 adoption evaluation guidance to `instructions.md`.
- [x] Added tests for `handoff_memory` collectors in `test_ace_metrics.py`.
- [x] Handoff decision recorded for Slice 4.

## Slice 5: Epic Completion and Documentation Sync

- [x] Updated epic Phase 5 checklist to match the implemented subset.
- [x] Updated epic Phase 5 status to in-progress.
- [x] Removed the overstated Completed Tasks row for Phase 5.
- [x] Synchronized README and contract doc with final snapshot shape.
- [x] Handoff decision recorded for Slice 5.

## Review Readiness

- [x] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [x] `ace_metrics.py` snapshot is backward-compatible (new keys added, none removed).
- [x] Handoff decision records the change, verification, and any contract implications.

## Success Criteria

- [x] `get_metrics_summary` includes process-health and handoff-memory sections with non-null values from current handoff state.
- [x] Multi-lens audit workflow in `branch-review-guide.md` is executable from cold start without additional context.
- [x] Periodic pruning workflow has clear triggers, thresholds, and steps that reference existing tooling.
- [x] Epic Phase 5 checklist accurately reflects implementation state.
