# Agentic Development Process Hardening (v0.3.0)

## Objective

Harden the repo's agentic development process so cross-service debugging, implementation, and review stay aligned with the real system instead of drifting across chat memory, stale docs, optimistic adapters, and test-only behavior. When this epic is complete, agents should have a single reliable workflow for planning, contract changes, MCP handoff usage, runtime verification, and review evidence.

## Problem Statement

The recent recognition debugging and remediation work exposed a process failure, not just a product bug. Documentation, contracts, MCP handoff usage, review rules, runtime behavior, and tests diverged enough that agents repeatedly shipped or reasoned from incorrect assumptions:

- boundary adapters invented or normalized contract metadata instead of enforcing a single owner
- backward-compatibility logic survived in a greenfield system and obscured the real contract
- PHPUnit/bootstrap behavior and local test stubs masked runtime WordPress loading failures
- proxy behavior drifted from backend semantics, including malformed JSON and empty-state masking
- documentation and remediation plans lagged behind implementation and required repeated audit corrections
- handoff was useful, but the repo still lacked stronger guardrails that force evidence, runtime parity, and same-slice contract updates

This made debugging materially slower, increased regression risk, and pushed incident understanding into chat reconstruction instead of durable process artifacts.

## UX Vision

Agents working in this repo should be able to start from a cold session, load the right context quickly, change one boundary safely, and leave behind a trustworthy trail. Plans should match the codebase before implementation starts. Cross-boundary changes should update the owning contract, tests, and handoff decision in the same slice. Review should catch runtime-parity gaps and masking behavior before they reach manual QA. Operators should be able to understand what changed, why, and how it was verified by reading MCP state plus a small set of canonical docs.

## Constraints

- MCP handoff remains the canonical coordination and review-tracking surface; planning docs must not duplicate live findings.
- This repo is greenfield by default, so process guidance should bias toward clean contract ownership and removal of backward-compatibility shims.
- Recommendations must improve day-to-day agent execution, not add ceremonial documentation with no enforcement path.
- Cross-service work spans Python, PHP, and TypeScript; process changes must account for runtime parity across all three.

## Terminology

- **Boundary owner**: The single layer allowed to adapt a payload shape between systems.
- **Contract fixture**: A golden request/response example or schema assertion used across layers to keep a boundary honest.
- **Runtime parity**: Verification that production bootstrap/load paths behave the same way as tests and local tooling.
- **Evidence gate**: A required verification artifact that blocks review or completion when missing.
- **Handoff decision**: The MCP record that summarizes a code/docs change and how it was verified.

## Current State

- `docs/agentic/instructions.md` contains strong rules, but several important guardrails were added only after incident damage had already happened.
- `docs/agentic/contracts/` documents many boundaries, but contract updates are still too easy to defer until after implementation.
- `docs/agentic/rules/branch-review-guide.md` and `docs/agentic/rules/planning-review-guide.md` catch many failure modes, yet there is no unified cross-boundary change protocol tying planning, implementation, tests, and handoff together.
- `packages/agent-handoff-mcp` gives strong state coordination primitives, but current usage depends too much on agent judgment instead of required workflows and automated checks.
- `docs/agentic/skills/` provides orchestration guidance, but skills do not consistently encode required evidence, contract-loading steps, or handoff expectations for boundary work.
- Recent handoff history shows repeated fabricated boundary metadata and duplicate contract adaptation.
- Recent handoff history shows runtime autoload/parity gaps hidden by PHPUnit bootstrap behavior.
- Recent handoff history shows malformed proxy responses caused by protocol/header forwarding drift.
- Recent handoff history shows optimistic empty-state degradation that masked real backend failure.
- Recent handoff history shows remediation plans and audit docs that needed repeated corrections to match the actual code.
- MCP-002 through MCP-006 daemon lifecycle fixes are implemented in code (`packages/agent-handoff-mcp/`), but no `daemon-lifecycle` skill encodes the safe-startup, signal-stop, and stale-lock-recovery procedures for agents.
- `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json` is missing `is_pinned` and `representative_id` despite all three service layers using these fields in production; cross-boundary contract tests for the backend to WP to TS pipeline do not exist.
- Finding IDs RSWR-IMPL-008, R-TOPO-02, and R-TOPO-11 were documentation-only debt markers; Phase 2 now requires verifying their MCP state and documenting or closing them explicitly so they do not linger as silent technical debt.
- The FTS5 sanitization fix (P-FTS-SANITIZE-01 in `core.py` and `artifact_index.py`) is in production, but no property-based tests exercise edge-case special characters or injection sequences.
- No rescue workflow or skill exists; the commit convention for cherry-pick-based rescue is undocumented, making recovery from lane regressions ad hoc.
- `make lane-intake` does not auto-regenerate `CURRENT_TASK.json` after a successful intake, leaving the active-task mirror stale for the next agent session.

## Applied Concepts from Sources

The following concepts from the literature are directly applicable to this repo's process hardening work.

| Source                                                                                                                      | Concept                                                                                                                     | Process-hardening application                                                                                                                                                                                                |
| --------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/literature/process/Agentic_Design_Patterns.txt`                                                                       | Planning, reflection, exception handling, human-in-the-loop, and multi-agent coordination as explicit control structures    | Turn planning, review, recovery, and escalation into named workflow stages instead of relying on conversational judgment. Add explicit re-plan and escalation paths for cross-boundary uncertainty.                          |
| `docs/literature/process/agentfactory-book/ch-66-mcp-fundamentals-drilldown-summary.md`                                     | Tool/resource/prompt separation, transport discipline, server evaluation, and debugging by failure layer                    | Clarify which repo capabilities belong in MCP tools versus resources versus prompt templates, and add a cleaner startup/discovery/execution troubleshooting model for process tooling.                                       |
| `docs/literature/process/agentfactory-book/ch-43-ten-axioms-of-programming-in-ai-driven-development-drilldown-summary.md`   | Tests as specification, git as memory, verification as a pipeline, observability as post-deploy verification                | Treat contracts, tests, commits, MCP decisions, CI, and runtime checks as one verification chain. Reinforce that git and MCP together are the durable memory, not chat recap.                                                |
| `docs/literature/process/agentfactory-book/ch-67-custom-mcp-servers-summary.md`                                             | Structured protocol errors, progress/log visibility, retry-safe recovery, specification-first MCP design                    | Tighten MCP and boundary guidance so failures remain typed and actionable. Add better startup, progress, and failure semantics to process tooling rather than free-form agent narration.                                     |
| `docs/literature/process/agentfactory-book/ch-68-agent-skills-mcp-code-execution-drilldown-v2.md`                           | Skills as policy wrappers around raw tools, explicit triggers/constraints/recovery rules, convergence criteria              | Define repo skills and MCP wrappers as execution patterns with clear activation rules, safety boundaries, completion checks, and escalation points instead of long advisory prose.                                           |
| `docs/literature/process/agentfactory-book/ch-69-multi-agent-reliability-drilldown-summary.md`                              | Structured error propagation, escalation calibration, context preservation, provenance, and review at the right granularity | Require stable provenance from plans to decisions to reviews, and define when agents must escalate or stop rather than guess across boundaries.                                                                              |
| `docs/literature/process/agentfactory-book/ch-76-tdd-for-agents-drilldown-v2.md`                                            | Deterministic TDD for owned code, evals separated from code-correctness tests, realistic mocks, CI enforcement              | Strengthen the repo rule that contract changes must come with deterministic boundary tests and runtime-parity checks, not just manual QA or narrative validation.                                                            |
| `docs/literature/process/agentfactory-book/ch-99-evaluation-quality-gates-drilldown-v2.md`                                  | Explicit thresholds, saved reports, release-blocking quality gates, regression discipline                                   | Define measurable process gates for planning drift, contract co-change, runtime-parity coverage, and reopened findings.                                                                                                      |
| `docs/literature/process/product-deploy-agents/README.md`                                                                   | Multi-lens staged audit pipeline with hard gates and distinct reviewer roles                                                | Add a branch-scoped pre-merge audit layer for cross-boundary work so architecture, QA, UX, compliance/safety, and release concerns are checked intentionally instead of informally.                                          |
| `docs/literature/process/gstack/README.md`                                                                                  | Branch-scoped review/QA/ship flow, documentation-drift correction, review readiness before landing                          | Borrow the idea of explicit branch stages and repo-local automation, but keep this repo's MCP handoff and worktree-lane model as the system of record.                                                                       |
| `docs/literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt` | Schema evolution, read-after-write expectations, dual-write hazards, provenance, and queue/backpressure awareness           | Strengthen the process around single ownership of facts, explicit contract evolution, derived-data provenance, and making overload or inconsistency visible instead of masking it behind empty success states.               |
| `docs/literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt`                            | Latency as a distribution, Little's law, queue-aware diagnosis, and tail-latency focus                                      | Require performance evidence to include p50/p95/p99, queue depth, pool wait, and concurrency budgets so the repo optimizes tail behavior instead of chasing averages.                                                        |
| `docs/literature/extracted/refactoring/Refactoring-TypeScript_Keeping-your-code-healthy.txt`                                | Small targeted refactors, strong type contracts, lower coupling, guard clauses, and read/write separation                   | Push process guidance toward incremental refactors that simplify boundary adapters, reduce condition-heavy orchestration hooks, and separate query/read models from mutation/write models where the codebase keeps drifting. |
| `docs/literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt`          | Behavior-preserving refactors, smells-to-tests workflow, and continuous cleanup                                             | Treat process hardening as a steady stream of small reversible improvements backed by tests and handoff evidence, not occasional large cleanup campaigns after incidents.                                                    |
| `docs/literature/extracted/refactoring/Refactoring-UI.txt`                                                                  | Smallest useful version, systems-first UI, empty-state discipline, and short feedback cycles                                | Require UI-facing workflow changes to define degraded/loading/empty/error states explicitly, keep component systems consistent, and prefer smaller verifiable slices over large speculative redesigns.                       |

## Git Workflow Assessment

A git-based workflow would help here, but only if it is applied as a **repo-native stage gate** rather than adopted wholesale from another framework.

What is worth borrowing:

- from `gstack`: branch-scoped stage progression such as `plan -> review -> qa -> ship`, review-readiness checks, and an explicit documentation-drift pass before landing
- from `agentfactory-book`: git as durable memory paired with tests, CI, and observability rather than as a passive backup
- from `product-deploy-agents`: staged audits with hard gates before release or merge

What should **not** be adopted directly:

- vendoring `gstack` as the repo's primary workflow engine
- replacing MCP handoff with CLAUDE.md-centric or chat-centric status tracking
- importing unrelated browser, telemetry, or deploy automation just because it exists in the external framework

The right move for this repo is to strengthen the existing **branch + worktree + MCP** workflow:

1. keep small reviewable commits and task-scoped branches/worktrees as the execution unit
2. make planning review, contract co-change, runtime-parity verification, and branch review required branch gates
3. add a repo-native "review readiness" or "process gate" command that summarizes whether a branch is safe to review or merge
4. add a docs-drift pass before merge so contract and workflow docs do not lag code
5. reserve release-style audits for cross-boundary or incident-driven changes, not every trivial edit

## Target Architecture

The end-state process is an evidence-driven workflow with clear ownership at every seam:

1. **Plan before code**: planning reviews compare proposed work against current code, contracts, and adjacent docs; findings are logged in MCP before implementation.
2. **Load only the right context**: agents identify the active role, required contracts, required rules, and relevant skills before editing.
3. **Change one boundary once**: every cross-service change has one contract owner, one same-slice contract update, and one set of contract fixtures or schema checks.
4. **Prove runtime behavior, not just test behavior**: runtime-parity checks sit alongside unit tests and type checks for boundaries with custom loading, proxying, or environment-specific bootstrap.
5. **Make handoff the review memory**: decisions, findings, tests, blockers, and worker reports become the authoritative trail; docs summarize policy and scope, not live review state.
6. **Automate the dangerous checks**: MCP tooling, review prompts, CI, and templates enforce the high-value rules so agents are not expected to remember them ad hoc.
7. **Prefer healthy data patterns**: one boundary owns each fact, derived metadata records provenance, and contract evolution is explicit rather than inferred from tolerant adapters.
8. **Optimize for tail behavior**: process and runtime evaluation must measure queueing, contention, retries, and p95/p99 latency, not just green tests or average response time.
9. **Keep process memory selective**: always-visible handoff state stays small and current; older detail is summarized, filtered, or retrieved on demand instead of being replayed by default.

### Design Decisions

| Decision                                                                            | Rationale                                                                                                                                                             |
| ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Keep MCP handoff as the canonical review ledger                                     | The recent incident showed that chat memory and doc prose are too lossy for multi-session debugging.                                                                  |
| Enforce single contract owner per boundary                                          | Duplicate adaptation logic was a direct source of drift and false compatibility.                                                                                      |
| Require same-slice contract updates for cross-boundary changes                      | Contract drift became expensive because behavior changed first and docs followed later.                                                                               |
| Prefer runtime-parity tests over test-only confidence                               | PHPUnit/bootstrap and proxy/runtime mismatches hid real failures until manual debugging.                                                                              |
| Treat tests, contracts, and handoff decisions as one evidence bundle                | The system needs durable proof of behavior, not isolated green checks or narrative claims.                                                                            |
| Keep skills thin and task-specific                                                  | Skills should route agents into the right process, not become hidden secondary policy stores.                                                                         |
| Use a repo-native git/worktree gate instead of importing `gstack` wholesale         | The branch-stage ideas are useful, but the repo already has MCP handoff, worktree lanes, and its own rules surface.                                                   |
| Prefer schema-on-write style contract ownership over tolerant downstream adaptation | Drift got worse when multiple layers silently accepted multiple shapes instead of rejecting ambiguity.                                                                |
| Treat dual writes and fabricated derived fields as process failures                 | Cross-boundary metadata must have an explicit source of truth and provenance, or be rejected.                                                                         |
| Measure performance with tail-latency and queue-health evidence                     | Saturation, retries, and queueing were operationally important long before simple pass/fail checks showed trouble.                                                    |
| Use `ctx7` selectively for external dependency docs, never for repo-local truth     | It can reduce token use during context assignment, but project rules, contracts, and handoff state must remain local and authoritative.                               |
| Shape MCP handoff like selective memory, not a chat transcript dump                 | Chapter 75's lesson applies directly here: durable state is valuable only when it is ranked, compressed, and retrieved in the cheapest useful form.                   |
| Gate contract changes with blocking evidence, not narrative intent                  | The repo needs release-style blocking rules for contract ownership, schema fixtures, and implementation parity before cross-boundary work is considered review-ready. |

### Data Model

This epic is process-focused rather than product-schema-focused. The important information flow is:

- planning docs define scope and phase intent
- contracts define boundary ownership and payload shape
- contract fixtures, canonical enums, and schema evolution notes define the schema-on-write truth for cross-boundary payloads
- rules define mandatory review and workflow gates
- skills define task entrypoints and bounded execution behavior
- MCP handoff stores decisions, findings, tests, blockers, and lane communication
- MCP handoff should be tiered like a memory system:
  - hot state: current task summary, open blockers, open findings, next actions, latest verification
  - warm state: recent decisions, recent worker reports, recent artifacts, compact progress summaries
  - cold state: archived findings, superseded plans, verbose logs, and large artifacts retrievable on demand
- CI/runtime verification produces evidence that is referenced from MCP decisions and review findings
- performance evidence includes latency distributions, queue depth, pool wait, retry behavior, and overload/backpressure signals for high-risk paths

## Phased Delivery

### Phase 1: Context Loading and Handoff Discipline -- complete

> **Status**: complete (implemented by docs/tasks/11.0/context-loading-and-handoff-discipline-task-plan.md; evidence recorded in decisions 829 and 830)
> **Task plans**: `docs/tasks/11.0/context-loading-and-handoff-discipline-task-plan.md`

**Goal**: Make every agent session start with the right repo context and leave behind the right MCP evidence.

Deliverables:

- tighten `instructions.md` so boundary work has an explicit startup protocol: role docs, contracts, rules, and handoff state must be loaded before edits
- add a concise "cross-boundary change protocol" that ties contract updates, tests, runtime checks, and handoff decisions together
- update worktree/orchestration skills so they explicitly require evidence and handoff logging, not just lane ownership
- define boundary-oriented handoff decision templates for cross-boundary work: contract-change, breaking-change, and cross-lane dependency; task plan intentionally narrows to these boundary-focused categories; general update-category templates (code, docs-only, review, remediation-plan) are deferred to Phase 4
- define a context-assignment policy that prefers repo-local rules/contracts/handoff for project truth and uses `ctx7` only for current external library/framework documentation
- define a selective-memory policy for handoff loading:
  - start from active task summary, open findings, open blockers, and latest decisions
  - pull older artifacts only through targeted search or explicit resource reads
  - summarize stale lane chatter and archive verbose evidence rather than keeping it in the default working set
- define concrete `ctx7` entry criteria:
  - use it when the needed information is upstream library/framework behavior, current API surface, or version-specific docs
  - do not use it for repo rules, local contracts, handoff state, or codebase-specific architecture
  - require a short note in handoff or plan state when a `ctx7` lookup materially changed the implementation or design decision

Exit criteria:

- an agent can start from cold context and follow one documented startup path for planning, implementation, and review
- MCP decision entries for cross-boundary changes consistently include changed boundary, verification, and contract/doc status

### Phase 2: Contract Ownership and Documentation Sync -- complete

> **Status**: complete
> **Task plans**: `docs/tasks/11.0/contract-ownership-and-documentation-sync-task-plan.md`

**Goal**: Stop contract drift by making boundary ownership explicit and same-slice synchronization mandatory.

Deliverables:

- add a repo-level contract change checklist under `docs/agentic/contracts/` or `docs/agentic/rules/`
- classify each major boundary by owner: backend, WP proxy, frontend adapter, MCP surface
- add requirements for canonical enums/constants and golden fixtures on cross-service payloads
- define how remediation plans, audits, and epics must reference current contracts and implementation evidence
- define healthy data-pattern rules for boundaries: one writer per fact, explicit provenance for derived metadata, no silent dual-write drift, and documented read-after-write/consistency expectations
- require schema-evolution notes whenever a boundary payload changes, including whether compatibility is required and who owns it
- update `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json` to include `is_pinned` and `representative_id` on the cluster item definition; add a planning-review-guide check: if the change touches a boundary field, is the shared schema updated in the same slice?
- add cross-boundary contract tests for the backend to WP to TS pipeline covering at minimum the recognition cluster snapshot shape
- audit and close or archive finding IDs with zero codebase references (confirmed unresolvable: RSWR-IMPL-008, R-TOPO-02, R-TOPO-11); add a note to the contract-change checklist that every finding ID cited in a remediation plan must resolve to a located code site before implementation starts
- define a blocking contract-change gate for cross-boundary work:
  - no review-ready status if a boundary implementation changed without an owning contract update, explicit no-change rationale, or matching fixture/schema evidence
  - no merge-ready status if handoff lacks the boundary owner, verification path, and current contract references
- add a small contract-intake template for each change:
  - which boundary changed
  - who owns the contract
  - whether compatibility is required
  - what fixture/schema/test proves the new shape
  - what downstream adapters are allowed to assume

Exit criteria:

- every major cross-service boundary has a declared owner and documented adaptation point
- a boundary change cannot be considered complete unless the owning contract changed in the same slice or the decision explicitly records why it did not need to

### Phase 3: Runtime Parity and Test Fidelity Gates -- complete

> **Status**: complete
> **Task plans**: `docs/tasks/11.0/runtime-parity-and-test-fidelity-gates-task-plan.md`; partial prior coverage from `docs/tasks/11.0/review-guide-hardening-task-plan.md`

**Goal**: Catch production-only breakage earlier by aligning tests, bootstrap paths, and review gates with real runtime behavior.

Deliverables:

- define runtime-parity requirements for WordPress class loading, proxy header forwarding, malformed payload handling, and environment-specific boot paths
- require contract fixtures/golden payload tests for backend -> WP and WP -> TS boundaries
- document stub/fake standards so tests cannot silently mask real runtime behavior
- add review guidance for "masking failures into empty success" and "test bootstrap differs from runtime bootstrap"
- add performance-verification guidance for high-risk flows: p50/p95/p99 latency, queue depth, connection-pool wait, retry counts, and backpressure behavior must be observable and reviewable
- require incident and remediation work to distinguish average latency improvements from tail-latency or saturation improvements
- add property-based tests using Hypothesis for FTS5 query-input sanitization in `packages/agent-handoff-mcp/tests/`, exercising Unicode edge cases, injection sequences, and all FTS5 special characters against the existing phrase-quoting (`core.py`) and regex-stripping (`artifact_index.py`) fixes; no hand-written test suite can exhaustively cover the input space that a motivated or accidental bad input could exercise

Exit criteria:

- branch review and testing guidance require runtime-parity checks for every boundary class known to diverge in this repo
- at least one deterministic verification path exists for each high-risk boundary failure mode: malformed payloads, missing runtime load path, header/protocol drift, and masked upstream failure

### Phase 4: MCP and Tooling Automation -- complete

> **Status**: complete
> **Task plans**: `docs/tasks/11.0/mcp-and-tooling-automation-task-plan.md`, `docs/tasks/12.0/slice-review-packet-and-cross-agent-review-task-plan.md`

**Goal**: Move the highest-value process rules out of memory and into tools, templates, and automated review surfaces.

Deliverables:

- extend MCP guidance so planning review, branch review, and remediation updates share clearer required record types, evidence fields, and failure categories
- define a repo-specific MCP surface map inspired by Chapter 66: which capabilities should be `tool`-like actions, which should behave like read-only `resources`, and which should be standardized prompt templates instead of ad hoc prose
- document an MCP troubleshooting ladder for process tooling: startup failure, capability discovery failure, runtime execution failure, and evidence-write failure, with the expected inspection command or dashboard surface for each
- add structured progress and error semantics for long-running process helpers so agents get typed status (`starting`, `blocked`, `awaiting_review`, `complete`) instead of free-form narration
- evaluate new MCP helpers or wrappers for common operations such as startup checks, boundary-change checklists, handoff close readiness, and review-readiness summaries
- normalize MCP write provenance so handoff `actor` is consistently structured and auto-populated rather than hand-authored:
  - define one canonical actor shape for handoff writes (`agent`, `branch`, `commit_sha`, optional `lane_id`)
  - add helper or wrapper flows for common MCP writes so decisions, tests, blockers, and finding updates do not hand-build actor payloads ad hoc
  - tighten contract/examples so minimal valid payloads always show the canonical actor object shape and stale string-form examples are removed
- define skill-wrapper rules from Chapter 68 so repo skills state explicit triggers, owned outputs, safety constraints, retry/recovery rules, and convergence criteria
- create `docs/agentic/skills/daemon-lifecycle/SKILL.md` encoding safe-start, signal-stop, stale-lock-recovery, pause/resume, and lane-health-check procedures; this skill should encapsulate the patterns already hardened in `api.py`, `orchestrator_daemon.py`, `worker_daemon.py`, and `worker_daemon_ctl.py` so agents are not expected to rediscover safe daemon interaction through code archaeology
- create `docs/agentic/skills/rescue-lane/SKILL.md` encoding the rescue-lane protocol: (a) create rescue branch from the last known-good commit, (b) cherry-pick fix commits with `git cherry-pick`, (c) diff contract surfaces between the rescue branch and the broken lane, (d) run lane test pack plus targeted regression test, (e) update MCP state with a rescue decision record, (f) regenerate `CURRENT_TASK.json`; note: `.agent/workflows/` was removed 2026-03-27; the canonical location for repo-native skills is `docs/agentic/skills/`
- add a post-intake `check-all` gate to `make lane-intake` in `mk/lane-maintenance.mk` so cross-lane regression tests run automatically after a lane is merged into the orchestrator branch
- preserve and verify the existing `CURRENT_TASK.json` regeneration path at the end of a successful `make lane-intake` so the active-task mirror is never stale for the next agent session
- add a repo-native branch/worktree "review readiness" command inspired by `gstack` that checks plan review, contract co-change, verification evidence, docs drift, and open handoff blockers before review
- add CI or scripted checks where feasible for doc/contract co-change, stale path detection, and runtime-parity test presence
- refine skills so they point to the canonical rules and avoid duplicating long policy text
- add a `ctx7` usage policy and helper flow for context assignment: prefer `ctx7` for current external docs, capture the resolved library id in handoff or plan notes when it materially informs implementation, and avoid replaying large external docs into prompts when a targeted query will do
- evaluate MCP helpers for performance-evidence capture so latency distributions, queue-health signals, and saturation notes can be attached to handoff decisions without ad hoc formatting
- add selective-memory MCP surfaces inspired by Chapter 75:
  - a small read-only "active task brief" resource for current task, blockers, open findings, and latest verification
  - targeted search helpers for archived decisions/findings/artifacts instead of replaying full handoff history
  - summary-generation helpers that compress long lane activity into durable task summaries before archival
  - archive/retention rules so stale details leave the hot working set without becoming inaccessible
- add a repo helper for external-doc context assignment:
  - resolve `ctx7` library ids for approved upstream dependencies
  - prefer narrow doc queries over broad manual browsing
  - cache the resolved library id and last useful query in handoff or a lightweight task note so later sessions do not re-spend tokens rediscovering the same source
- add an automated contract-gate helper that can fail review readiness when boundary-touching files changed without matching contract/doc/fixture evidence
- add packet-backed cross-agent review intake so "review the latest completed slice" resolves file scope, review kind, and evidence from MCP state instead of current branch diff heuristics

Exit criteria:

- the most dangerous process omissions are caught by tooling or generated prompts rather than depending on memory alone
- agents can tell whether a process capability should be exposed as a raw MCP action, a read-only context surface, or a reusable prompt/template
- repo skills and MCP wrappers expose explicit start, retry, escalate, and stop behavior rather than advisory-only descriptions
- agents can discover required startup, review, and closeout behavior from a small set of authoritative surfaces
- context assignment uses less prompt space for upstream references because external docs are retrieved through targeted `ctx7` or MCP reads instead of bulk-ingested prose
- the default handoff payload for a task stays compact enough to load quickly because archival detail is summarized or retrieved only when needed

### Phase 5: Evaluation and Release Audit Layer -- complete

> **Status**: complete
> **Task plans**: `docs/tasks/11.0/evaluation-and-release-audit-layer-task-plan.md`

**Goal**: Add a repeatable process-evaluation layer so the repo can measure whether the hardening work is improving execution quality.

Deliverables:

- define process health metrics: contract co-change rate, runtime-parity coverage, reopened-finding rate, planning-review drift rate, handoff completeness, and performance-evidence coverage on high-risk changes
- add a release-style audit pass for cross-boundary changes modeled on the multi-lens approach from `product-deploy-agents`
- define periodic review of rules and skills so they evolve from evidence, not accumulation
- define periodic review of data-pattern health and latency health: fabricated-field incidents, dual-write exceptions, queue-saturation incidents, and tail-latency regressions should feed back into rules and tooling
- define handoff-memory health metrics:
  - hot-state size and load cost
  - percentage of sessions resolved from active-task brief plus targeted retrieval
  - stale-artifact/archive rate
  - frequency of repeated context rediscovery that should have been captured once
- define `ctx7` adoption metrics:
  - external-doc retrievals served through `ctx7` instead of manual bulk ingestion
  - repeated library-id reuse across sessions
  - token-cost reduction for context assignment on dependency-heavy work

Exit criteria:

- the repo can evaluate whether process changes reduced drift and reopened findings over time
- major cross-boundary work can run through a repeatable pre-merge audit rather than ad hoc retrospective cleanup

## External Dependencies

| Dependency                                                                           | Owner               | Status      | Blocks                            |
| ------------------------------------------------------------------------------------ | ------------------- | ----------- | --------------------------------- |
| Agreement on canonical cross-boundary checklist surface                              | Repo maintainers    | Not started | Phase 1 exit criteria             |
| MCP/tooling enhancements in `packages/agent-handoff-mcp` if new helpers are added    | Tooling maintainers | Not started | Phase 4 automation deliverables   |
| CI appetite for new docs/contract/runtime gates                                      | Repo maintainers    | Not started | Phase 3 and Phase 4 exit criteria |
| Decision on how much `git`/worktree workflow automation to formalize in repo tooling | Repo maintainers    | Not started | Phase 4 branch-gate deliverables  |

## Code Anchors

| Layer             | File                                                                                                                      | Note                                                                                                                                                                                                                                  |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Process           | `docs/agentic/instructions.md`                                                                                            | Canonical cold-start rules and MCP contract guidance; likely primary policy surface for Phase 1.                                                                                                                                      |
| Process           | `docs/agentic/rules/planning-review-guide.md`                                                                             | Defines plan-review expectations; Phase 1 and Phase 2 should tighten boundary and evidence checks here.                                                                                                                               |
| Process           | `docs/agentic/rules/branch-review-guide.md`                                                                               | Holds universal review heuristics; Phase 3 should add stronger runtime-parity and masking checks.                                                                                                                                     |
| Process           | `docs/agentic/rules/development-workflow.md`                                                                              | TDD and review pipeline guidance; should align with evidence-gate workflow.                                                                                                                                                           |
| Contract          | `docs/agentic/contracts/agent-handoff-mcp.md`                                                                             | Canonical MCP surface and runtime model; Phase 4 should align usage guidance and possible helper additions.                                                                                                                           |
| Tooling           | `packages/agent-handoff-mcp/README.md`                                                                                    | Operator-facing MCP runtime guidance; should stay aligned with the contract and repo instructions.                                                                                                                                    |
| Skill             | `docs/agentic/skills/worktree-orchestrator/SKILL.md`                                                                      | Multi-agent orchestration entrypoint; Phase 1 should make evidence and handoff expectations more explicit.                                                                                                                            |
| Skill             | `docs/agentic/skills/worktree-worker/SKILL.md`                                                                            | Worker execution guidance; should load the same core process rules without policy drift.                                                                                                                                              |
| Skill             | `docs/agentic/skills/daemon-lifecycle/SKILL.md`                                                                           | Daemon lifecycle procedures (to be created in Phase 4); encodes safe-start, signal-stop, stale-lock-recovery, and lane-health-check patterns from `api.py`, `orchestrator_daemon.py`, `worker_daemon.py`, and `worker_daemon_ctl.py`. |
| Skill/Rule        | `docs/agentic/skills/rescue-lane/SKILL.md` or `docs/agentic/rules/rescue-workflow.md`                                     | Rescue-lane workflow (to be created in Phase 4); covers cherry-pick, contract diff, regression tests, MCP decision, and `CURRENT_TASK.json` regeneration. _(`.agent/workflows/` directory removed 2026-03-27; relocate here.)_          |
| Contract          | `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json`                                              | Shared cluster snapshot schema; known gap: missing `is_pinned` and `representative_id`. Update required in Phase 2.                                                                                                                   |
| Literature        | `docs/literature/process/product-deploy-agents/README.md`                                                                 | Source for staged multi-lens audit and hard-gate recommendations.                                                                                                                                                                     |
| Literature        | `docs/literature/process/gstack/README.md`                                                                                | Source for branch-scoped review/readiness/documentation workflow ideas that may be selectively adapted.                                                                                                                               |
| Literature        | `docs/literature/process/agentfactory-book/ch-66-mcp-fundamentals-drilldown-summary.md`                                   | Source for tool/resource/prompt separation, transport discipline, and MCP debugging-by-layer.                                                                                                                                         |
| Literature        | `docs/literature/process/agentfactory-book/ch-43-ten-axioms-of-programming-in-ai-driven-development-drilldown-summary.md` | Source for tests-as-specification, git-as-memory, verification pipeline, and observability guidance.                                                                                                                                  |
| Literature        | `docs/literature/process/agentfactory-book/ch-67-custom-mcp-servers-summary.md`                                           | Source for structured MCP errors, progress visibility, and retry-safe recovery.                                                                                                                                                       |
| Literature        | `docs/literature/process/agentfactory-book/ch-68-agent-skills-mcp-code-execution-drilldown-v2.md`                         | Source for MCP-wrapping skills, execution-pattern design, and convergence/safety rules.                                                                                                                                               |
| Literature        | `docs/literature/process/agentfactory-book/ch-69-multi-agent-reliability-drilldown-summary.md`                            | Source for escalation, provenance, context preservation, and multi-agent reliability guidance.                                                                                                                                        |
| Literature        | `docs/literature/process/agentfactory-book/ch-76-tdd-for-agents-drilldown-v2.md`                                          | Source for deterministic TDD, realistic mocks, and CI-enforced test discipline.                                                                                                                                                       |
| Literature        | `docs/literature/process/agentfactory-book/ch-99-evaluation-quality-gates-drilldown-v2.md`                                | Source for explicit process thresholds and quality-gate thinking.                                                                                                                                                                     |
| Literature        | `docs/literature/process/Agentic_Design_Patterns.txt`                                                                     | Source for planning, reflection, exception handling, human-in-the-loop, and multi-agent control-pattern ideas.                                                                                                                        |
| Incident evidence | `docs/tasks/10.0/10.3/recognition-service-502-audit-2026-03-26.md`                                                        | Concrete example of how drift across boundaries and tooling complicated debugging.                                                                                                                                                    |
| Incident evidence | `docs/tasks/10.0/10.3/recognition-502-remediation-plan.md`                                                                | Shows where plan drift, runtime-parity gaps, and contract updates had to be corrected in-flight.                                                                                                                                      |

---

## Completed Tasks

| Task Ref | Task                                      | Scope                                                                                                                                                                                            | Date       |
| -------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------- |
| 11.0     | Review Guide Hardening                    | Hardened 4 review guides (intake, evidence, escalation, resolution); added 3 MCP tool upgrades (`require_fresh_tests`, `review_mode`, `require_clean_slice`); source crosswalk fully implemented | 2026-03-27 |
| 11.0     | Context Loading and Handoff Discipline    | Startup protocol, cross-boundary change protocol, selective handoff-loading, `ctx7` entry criteria, handoff decision templates, orchestration/worker skill updates                               | 2026-03-27 |
| 11.0     | Contract Ownership and Documentation Sync | 9 boundary owners declared, contract-change checklist, golden fixture + 3 cross-boundary tests, contract-change gate in review guides, MCP write-signature discipline, schema gap closure        | 2026-03-27 |
| 11.0     | Runtime Parity and Test Fidelity Gates    | Python review parity rules, stub-fidelity and runtime-parity testing guidance, performance-evidence requirements, and Hypothesis property tests for FTS5 sanitization                            | 2026-03-27 |

---

# Consolidated Checklist

## Phase 1: Context Loading and Handoff Discipline -- complete

- [x] Define the startup protocol for cross-boundary work in `instructions.md`.
- [x] Add a cross-boundary change protocol tying contracts, tests, runtime checks, and handoff decisions together.
- [x] Update orchestration and worker skills to require evidence-oriented handoff usage.
- [x] Define reusable handoff decision templates.
- [x] Define selective handoff-loading and `ctx7` entry rules.

## Phase 2: Contract Ownership and Documentation Sync -- complete

- [x] Declare boundary owners for the major backend, WP proxy, frontend, and MCP seams.
- [x] Add a contract-change checklist and co-change guidance.
- [x] Define contract fixture and golden-payload expectations.
- [x] Define blocking contract-gate requirements for review-ready and merge-ready status.
- [x] Align remediation-plan and audit-doc expectations with the contract workflow.
- [x] Update `recognition-cluster-snapshot.schema.json` to add `is_pinned` and `representative_id`.
- [x] Add cross-boundary contract tests for the backend to WP to TS cluster snapshot pipeline.
- [x] Audit and close or archive RSWR-IMPL-008, R-TOPO-02, R-TOPO-11 (zero codebase references confirmed).

## Phase 3: Runtime Parity and Test Fidelity Gates -- complete

- [x] Document runtime-parity requirements for high-risk boundary classes.
- [x] Add guidance for golden payload tests and malformed-shape tests.
- [x] Define stub and fake fidelity rules to prevent test-only masking.
- [x] Add performance-evidence expectations for latency, queueing, and retry behavior.
- [x] Tighten review heuristics around empty-state masking and bootstrap drift. _(Completed by review-guide-hardening task 11.0: branch-review-php.md now has degradation semantics and bootstrap parity; branch-review-typescript.md has UI state matrix and API-boundary payload validation.)_
- [x] Add fresh-evidence requirements to `branch-review-python.md` parallel to TS and PHP modules.
- [x] Add Hypothesis property-based tests for FTS5 query-input sanitization in `packages/agent-handoff-mcp/tests/`.

## Phase 4: MCP and Tooling Automation -- complete

- [x] Define which startup, review, and closeout checks can move into MCP helpers or wrappers.
- [x] Define which repo capabilities should be modeled as MCP actions, read-only resources, or reusable prompt templates.
- [x] Define structured progress, error, and status semantics for process automation surfaces.
- [x] Normalize handoff `actor` provenance so MCP writes use one canonical structured actor shape with helper/wrapper support.
- [x] Add trigger, recovery, and convergence requirements to repo skills and MCP wrappers.
- [x] Create `docs/agentic/skills/daemon-lifecycle/SKILL.md` (safe-start, signal-stop, stale-lock-recovery, lane-health-check).
- [x] Create a rescue-lane protocol document (branch, cherry-pick, contract diff, test pack, MCP decision, regenerate `CURRENT_TASK.json`). _(Originally scoped to `.agent/workflows/rescue.md`; `.agent/workflows/` directory was removed 2026-03-27 after Gemini/Antigravity phase-off. Relocate to `docs/agentic/skills/` or `docs/agentic/rules/`.)_
- [x] Add post-intake `check-all` gate to `make lane-intake` in `mk/lane-maintenance.mk`.
- [x] Preserve and verify the existing `CURRENT_TASK.json` regeneration path at the end of successful `make lane-intake`.
- [x] Add selective-memory MCP surfaces for active-task briefs, targeted retrieval, and archival summaries.
- [x] Add reusable `ctx7` helpers and caching guidance for external-doc retrieval.
- [x] Decide what repo-native branch and worktree gate should exist before review or merge.
- [x] Add feasible CI and scripted guards for doc, contract, and runtime evidence.
- [x] Reduce policy duplication across skills and README surfaces.
- [x] Add packet-backed latest-slice review intake so cross-agent review can use MCP-recorded slice scope instead of branch-diff inference.
- [x] Keep `agent-handoff-mcp` contract and operator docs synchronized.

## Phase 5: Evaluation and Release Audit Layer -- complete

- [x] Define the initial process-health metrics and how they are measured.
- [x] Create a multi-lens pre-merge audit model for cross-boundary changes.
- [x] Add initial handoff-memory and `ctx7` adoption guidance.
- [x] Add a periodic rule and skill review loop driven by evidence.
- [x] Add runtime-parity coverage, planning-review drift rate, and performance-evidence coverage metrics. _(Planning drift is now measured directly; runtime-parity and performance-evidence coverage are explicitly documented as deferred instrumentation until the handoff schema carries typed verification categories and perf-evidence links.)_
- [x] Add the deferred data-pattern and latency-health review loop.
- [x] Add the resolved-from-hot-state ratio and stale-artifact/archive-rate metrics. _(Stale-artifact and archive-rate metrics are implemented; resolved-from-hot-state remains explicitly deferred pending retrieval telemetry.)_
- [x] Add a credible `ctx7` token-cost reduction measurement or explicitly narrow that deliverable. _(`ctx7` adoption and reuse are now measured; token-cost reduction is explicitly narrowed out until prompt/tooling telemetry exists.)_

## Deferred (Post-v0.3.0)

Deferred items from this epic are consolidated in [../../deferred-features/agentic-process-hardening-post-v0.3.0.md](../../deferred-features/agentic-process-hardening-post-v0.3.0.md).

- [ ] Deep MCP productization beyond repo needs, such as generalized dashboards or external distribution changes not required to enforce this repo's workflow
- [ ] TUI monitoring task: 9 open findings (H-GAP-TUI-01 through L-GAP-TUI-09) in `docs/tasks/9.0/orchestration-tui-monitoring-task-plan.md`; deferred until Phase 4 tooling automation work establishes the review-readiness and MCP-surface patterns the TUI should reflect; the plan's slice structure and runtime model section should be re-evaluated at that point using the template improvements added in Phase 1.
- [ ] Repo-wide eval infrastructure that measures model quality rather than process quality
