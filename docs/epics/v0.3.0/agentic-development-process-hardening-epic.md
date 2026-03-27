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
- Recent handoff history shows recurring classes of failure:
  - fabricated boundary metadata and duplicate contract adaptation
  - runtime autoload/parity gaps hidden by PHPUnit bootstrap behavior
  - malformed proxy responses caused by protocol/header forwarding drift
  - optimistic empty-state degradation that masked real backend failure
  - remediation plans and audit docs that needed repeated corrections to match the actual code

## Target Architecture

The end-state process is an evidence-driven workflow with clear ownership at every seam:

1. **Plan before code**: planning reviews compare proposed work against current code, contracts, and adjacent docs; findings are logged in MCP before implementation.
2. **Load only the right context**: agents identify the active role, required contracts, required rules, and relevant skills before editing.
3. **Change one boundary once**: every cross-service change has one contract owner, one same-slice contract update, and one set of contract fixtures or schema checks.
4. **Prove runtime behavior, not just test behavior**: runtime-parity checks sit alongside unit tests and type checks for boundaries with custom loading, proxying, or environment-specific bootstrap.
5. **Make handoff the review memory**: decisions, findings, tests, blockers, and worker reports become the authoritative trail; docs summarize policy and scope, not live review state.
6. **Automate the dangerous checks**: MCP tooling, review prompts, CI, and templates enforce the high-value rules so agents are not expected to remember them ad hoc.

### Design Decisions

| Decision | Rationale |
| --- | --- |
| Keep MCP handoff as the canonical review ledger | The recent incident showed that chat memory and doc prose are too lossy for multi-session debugging. |
| Enforce single contract owner per boundary | Duplicate adaptation logic was a direct source of drift and false compatibility. |
| Require same-slice contract updates for cross-boundary changes | Contract drift became expensive because behavior changed first and docs followed later. |
| Prefer runtime-parity tests over test-only confidence | PHPUnit/bootstrap and proxy/runtime mismatches hid real failures until manual debugging. |
| Treat tests, contracts, and handoff decisions as one evidence bundle | The system needs durable proof of behavior, not isolated green checks or narrative claims. |
| Keep skills thin and task-specific | Skills should route agents into the right process, not become hidden secondary policy stores. |

### Data Model

This epic is process-focused rather than product-schema-focused. The important information flow is:

- planning docs define scope and phase intent
- contracts define boundary ownership and payload shape
- rules define mandatory review and workflow gates
- skills define task entrypoints and bounded execution behavior
- MCP handoff stores decisions, findings, tests, blockers, and lane communication
- CI/runtime verification produces evidence that is referenced from MCP decisions and review findings

## Phased Delivery

### Phase 1: Context Loading and Handoff Discipline -- not-started

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Make every agent session start with the right repo context and leave behind the right MCP evidence.

Deliverables:

- tighten `instructions.md` so boundary work has an explicit startup protocol: role docs, contracts, rules, and handoff state must be loaded before edits
- add a concise "cross-boundary change protocol" that ties contract updates, tests, runtime checks, and handoff decisions together
- update worktree/orchestration skills so they explicitly require evidence and handoff logging, not just lane ownership
- define a handoff decision template for code, docs-only, review, and remediation-plan updates

Exit criteria:

- an agent can start from cold context and follow one documented startup path for planning, implementation, and review
- MCP decision entries for cross-boundary changes consistently include changed boundary, verification, and contract/doc status

### Phase 2: Contract Ownership and Documentation Sync -- not-started

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Stop contract drift by making boundary ownership explicit and same-slice synchronization mandatory.

Deliverables:

- add a repo-level contract change checklist under `docs/agentic/contracts/` or `docs/agentic/rules/`
- classify each major boundary by owner: backend, WP proxy, frontend adapter, MCP surface
- add requirements for canonical enums/constants and golden fixtures on cross-service payloads
- define how remediation plans, audits, and epics must reference current contracts and implementation evidence

Exit criteria:

- every major cross-service boundary has a declared owner and documented adaptation point
- a boundary change cannot be considered complete unless the owning contract changed in the same slice or the decision explicitly records why it did not need to

### Phase 3: Runtime Parity and Test Fidelity Gates -- not-started

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Catch production-only breakage earlier by aligning tests, bootstrap paths, and review gates with real runtime behavior.

Deliverables:

- define runtime-parity requirements for WordPress class loading, proxy header forwarding, malformed payload handling, and environment-specific boot paths
- require contract fixtures/golden payload tests for backend -> WP and WP -> TS boundaries
- document stub/fake standards so tests cannot silently mask real runtime behavior
- add review guidance for "masking failures into empty success" and "test bootstrap differs from runtime bootstrap"

Exit criteria:

- branch review and testing guidance require runtime-parity checks for every boundary class known to diverge in this repo
- at least one deterministic verification path exists for each high-risk boundary failure mode: malformed payloads, missing runtime load path, header/protocol drift, and masked upstream failure

### Phase 4: MCP and Tooling Automation -- not-started

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Move the highest-value process rules out of memory and into tools, templates, and automated review surfaces.

Deliverables:

- extend MCP guidance so planning review, branch review, and remediation updates share clearer required record types and evidence fields
- evaluate new MCP helpers or wrappers for common operations such as startup checks, boundary-change checklists, and handoff close readiness
- add CI or scripted checks where feasible for doc/contract co-change, stale path detection, and runtime-parity test presence
- refine skills so they point to the canonical rules and avoid duplicating long policy text

Exit criteria:

- the most dangerous process omissions are caught by tooling or generated prompts rather than depending on memory alone
- agents can discover required startup, review, and closeout behavior from a small set of authoritative surfaces

### Phase 5: Evaluation and Release Audit Layer -- not-started

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Add a repeatable process-evaluation layer so the repo can measure whether the hardening work is improving execution quality.

Deliverables:

- define process health metrics: contract co-change rate, runtime-parity coverage, reopened-finding rate, planning-review drift rate, and handoff completeness
- add a release-style audit pass for cross-boundary changes modeled on the multi-lens approach from `product-deploy-agents`
- define periodic review of rules and skills so they evolve from evidence, not accumulation

Exit criteria:

- the repo can evaluate whether process changes reduced drift and reopened findings over time
- major cross-boundary work can run through a repeatable pre-merge audit rather than ad hoc retrospective cleanup

## External Dependencies

| Dependency | Owner | Status | Blocks |
| --- | --- | --- | --- |
| Agreement on canonical cross-boundary checklist surface | Repo maintainers | Not started | Phase 1 exit criteria |
| MCP/tooling enhancements in `packages/agent-handoff-mcp` if new helpers are added | Tooling maintainers | Not started | Phase 4 automation deliverables |
| CI appetite for new docs/contract/runtime gates | Repo maintainers | Not started | Phase 3 and Phase 4 exit criteria |

## Code Anchors

| Layer | File | Note |
| --- | --- | --- |
| Process | `docs/agentic/instructions.md` | Canonical cold-start rules and MCP contract guidance; likely primary policy surface for Phase 1. |
| Process | `docs/agentic/rules/planning-review-guide.md` | Defines plan-review expectations; Phase 1 and Phase 2 should tighten boundary and evidence checks here. |
| Process | `docs/agentic/rules/branch-review-guide.md` | Holds universal review heuristics; Phase 3 should add stronger runtime-parity and masking checks. |
| Process | `docs/agentic/rules/development-workflow.md` | TDD and review pipeline guidance; should align with evidence-gate workflow. |
| Contract | `docs/agentic/contracts/agent-handoff-mcp.md` | Canonical MCP surface and runtime model; Phase 4 should align usage guidance and possible helper additions. |
| Tooling | `packages/agent-handoff-mcp/README.md` | Operator-facing MCP runtime guidance; should stay aligned with the contract and repo instructions. |
| Skill | `docs/agentic/skills/worktree-orchestrator/SKILL.md` | Multi-agent orchestration entrypoint; Phase 1 should make evidence and handoff expectations more explicit. |
| Skill | `docs/agentic/skills/worktree-worker/SKILL.md` | Worker execution guidance; should load the same core process rules without policy drift. |
| Incident evidence | `docs/tasks/10.0/10.3/recognition-service-502-audit-2026-03-26.md` | Concrete example of how drift across boundaries and tooling complicated debugging. |
| Incident evidence | `docs/tasks/10.0/10.3/recognition-502-remediation-plan.md` | Shows where plan drift, runtime-parity gaps, and contract updates had to be corrected in-flight. |

---

# Consolidated Checklist

## Phase 1: Context Loading and Handoff Discipline -- not-started

- [ ] Define the startup protocol for cross-boundary work in `instructions.md`
- [ ] Add a cross-boundary change protocol tying contracts, tests, runtime checks, and handoff decisions together
- [ ] Update orchestration/worker skills to require evidence-oriented handoff usage
- [ ] Define reusable handoff decision templates

## Phase 2: Contract Ownership and Documentation Sync -- not-started

- [ ] Declare boundary owners for the major backend, WP proxy, frontend, and MCP seams
- [ ] Add a contract-change checklist and co-change guidance
- [ ] Define contract fixture/golden-payload expectations
- [ ] Align remediation-plan and audit-doc expectations with the contract workflow

## Phase 3: Runtime Parity and Test Fidelity Gates -- not-started

- [ ] Document runtime-parity requirements for high-risk boundary classes
- [ ] Add guidance for golden payload tests and malformed-shape tests
- [ ] Define stub/fake fidelity rules to prevent test-only masking
- [ ] Tighten review heuristics around empty-state masking and bootstrap drift

## Phase 4: MCP and Tooling Automation -- not-started

- [ ] Define which startup/review/closeout checks can move into MCP helpers or wrappers
- [ ] Add feasible CI/scripted guards for doc/contract/runtime evidence
- [ ] Reduce policy duplication across skills and README surfaces
- [ ] Keep `agent-handoff-mcp` contract and operator docs synchronized

## Phase 5: Evaluation and Release Audit Layer -- not-started

- [ ] Define process health metrics and how they are measured
- [ ] Create a multi-lens pre-merge audit model for cross-boundary changes
- [ ] Add a periodic rule/skill review loop driven by evidence

## Deferred (Post-v0.3.0)

- [ ] Deep MCP productization beyond repo needs, such as generalized dashboards or external distribution changes not required to enforce this repo's workflow
- [ ] Repo-wide eval infrastructure that measures model quality rather than process quality
