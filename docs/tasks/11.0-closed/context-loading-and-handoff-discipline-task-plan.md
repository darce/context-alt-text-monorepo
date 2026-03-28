# Task Plan Template

> Use this template for all implementation plans under `docs/tasks/`.
> Task plans describe executable work for one bounded objective.
> Task plans use **slices**, not phases:
>
> - **Phases** belong to epics and describe coarse-grained temporal delivery across multiple task plans.
> - **Slices** are reviewable implementation increments that can be completed, verified, and logged independently.
>
> Favor slices that each produce behavior plus proof. Avoid scaffold-only slices that add placeholders, skipped tests, or empty abstractions without executable value.
> See `docs/agentic/instructions.md` and `docs/agentic/rules/planning-review-guide.md` for repo-wide planning rules.

---

# Context Loading and Handoff Discipline

## Objective

Make every agent session start with the right repo context and leave behind the right MCP evidence. Add a cross-boundary change protocol so contract updates, tests, runtime checks, and handoff decisions are tied together in the same slice. Define selective handoff-loading and `ctx7` entry rules so agents spend tokens on relevant context instead of bulk-ingesting docs.

## Problem Statement

Agents entering this repo follow a cold-start role routing table but have no structured startup protocol for mid-task re-entry, cross-boundary work, or evidence collection. Cross-boundary changes (PHP controller touches Python API contract, frontend consumes new REST route) lack a proactive discovery and validation protocol; violations are caught at review time by regression guards, not during implementation. Orchestration and worker skills document lane ownership and MCP recording but do not require evidence justification, contract validation, or structured decision templates. `ctx7` is available for upstream library docs but has no entry criteria; agents either skip it or manually browse. Handoff loading is all-or-nothing; no selective-loading policy keeps the working set compact.

These gaps mean agents start from incorrect assumptions, defer contract updates, produce MCP decisions without structured evidence, and waste tokens loading irrelevant context.

## Constraints

- All changes to `instructions.md` must be additive to existing rules; do not rewrite sections that are already correct.
- Skills must remain thin execution wrappers that route to canonical rules; do not duplicate long policy text in skill files.
- `ctx7` entry rules must work in both VS Code and Codex environments.
- No changes to `packages/agent-handoff-mcp` code in this task; MCP tool changes belong to separate task plans. The protocol surfaces here are document-level guidance that agents follow when calling existing MCP tools.
- Handoff decision templates define guidance for `record_decision` calls; they do not add new MCP tool parameters.
- Cross-boundary change protocol must account for all three runtime stacks (Python, PHP, TypeScript) and the MCP tooling boundary.

## Workflow Principles

- Evidence before claims: every cross-boundary change must cite the contract it touches, the tests it affects, and the verification it produced.
- Selective loading: agents load only the context surfaces relevant to their role, lane, and current slice; broader context is retrieved on demand through MCP search or `ctx7`.
- Protocol over judgment: startup steps and cross-boundary validation are defined as checklists, not advisory prose; agents follow them in order.
- Templates over improvisation: common handoff decisions use a structured template so downstream agents can parse them without re-reading chat history.

## Terminology

- **Startup protocol**: The required sequence of MCP queries, context loads, and contract checks an agent performs before writing code.
- **Cross-boundary change protocol**: The checklist an agent follows when a code change crosses a service, language, or contract boundary.
- **Decision template**: A structured rationale format for `record_decision` calls covering contract changes, breaking changes, and cross-lane dependencies.
- **Selective loading**: Loading only role-specific rules, lane-scoped contracts, and targeted MCP state instead of the full instruction set.
- **ctx7 entry criteria**: The conditions under which an agent should query upstream library documentation through `ctx7` instead of relying on static `tech-stack.md` references.

## Current State Analysis

- `instructions.md` has a role-based routing table for cold-start domain entry, but no startup protocol for agents re-entering mid-task work or inheriting a lane from another agent.
- `instructions.md` has a Plugin Boundary Rule (containment) and regression guards (merge-time checks) but no proactive cross-boundary change protocol for implementation time.
- `development-workflow.md` requires scaffolding-first and cross-layer contract definition but does not define how to discover which contracts must exist or how to validate them before coding.
- `worktree-orchestrator/SKILL.md` and `worktree-worker/SKILL.md` document lane ownership and MCP recording; neither requires evidence justification, contract validation, or structured decision templates.
- The slice completion summary format in `instructions.md` explicitly requires contract change documentation but does not require verification that downstream consumers still work.
- `BOOTSTRAP.md` documents `ctx7` installation and service map but no startup rule or entry criteria for when agents should query it.
- MCP handoff loading is implicit: agents call `get_handoff_state` by instruction but no guidance distinguishes hot state (current task, open findings, latest decisions) from cold state (archived findings, verbose logs).
- No handoff decision templates exist; agents improvise `record_decision` rationale in ad hoc formats.

## Target Outcome

After this task:

1. An agent entering a cold session follows a single documented startup protocol: query MCP state, read lane inbox (if in a lane), load role routing, verify relevant contracts exist, and check for open findings and blockers.
2. An agent making a cross-boundary change follows a discovery, validation, and evidence protocol: identify touched contracts, verify downstream consumers, run targeted tests, and record the change with structured evidence in MCP.
3. Orchestration and worker skills require evidence-oriented handoff: contract validation before dispatch, evidence collection during implementation, and structured decision templates at handoff.
4. `ctx7` has clear entry criteria: use for upstream library/framework docs when modifying library-dependent code; prefer static `tech-stack.md` for version inventory; fall back gracefully when unavailable.
5. Handoff loading is selective: hot state (current task, open findings, blockers, latest verification) is default; warm state (recent decisions, worker reports) is loaded on demand; cold state (archived findings, verbose logs) is retrieved only through targeted search.

## Context Loading

- Rules: `docs/agentic/instructions.md` (Role Selection, MCP Handoff Contract, Cross-Branch Regression Guards)
- Rules: `docs/agentic/rules/development-workflow.md` (Scaffolding First, Orchestrated Task Execution)
- Skills: `docs/agentic/skills/worktree-orchestrator/SKILL.md`
- Skills: `docs/agentic/skills/worktree-worker/SKILL.md`
- Bootstrap: `docs/agentic/BOOTSTRAP.md` (ctx7, MCP server setup)
- Maps: `docs/agentic/maps/tech-stack.md`
- Crosswalk: `docs/epics/v0.3.0/review-guide-hardening-source-crosswalk.md` (expanded rules audit, Phase 1 gap findings)
- Epic: `docs/epics/v0.3.0/agentic-development-process-hardening-epic.md` (Phase 1 deliverables)
- External docs via `ctx7` only if: verifying current MCP SDK patterns for handoff tool usage

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Agent startup protocol | `docs/agentic/instructions.md` | Role Selection table + MCP bootstrap (3 lines) | Add `## Agent Startup Protocol` section with ordered checklist | yes; existing role routing is preserved | `grep_search` for section header; structure review |
| Cross-boundary change protocol | `docs/agentic/rules/development-workflow.md` | Scaffolding First requires contract definition | Add `## Cross-Boundary Change Protocol` checklist | yes; scaffolding-first preserved | `grep_search` for section header; structure review |
| Orchestrator evidence requirements | `docs/agentic/skills/worktree-orchestrator/SKILL.md` | Lane dispatch and review documented | Add evidence checklist and decision template references | yes; existing guidance preserved | `grep_search` for "Evidence" in skill file |
| Worker evidence requirements | `docs/agentic/skills/worktree-worker/SKILL.md` | Lane scope and handoff documented | Add evidence collection and contract validation steps | yes; existing guidance preserved | `grep_search` for "Evidence" in skill file |
| Decision templates | `docs/agentic/templates/` (new files) | None | Add 3 decision templates | n/a; new files | Files exist and are referenced from skills |
| ctx7 entry rules | `docs/agentic/instructions.md` | Mentioned in BOOTSTRAP.md only | Add `ctx7` entry criteria to instructions.md | yes; no existing rules contradicted | `grep_search` for "ctx7" in instructions.md |
| Selective loading policy | `docs/agentic/instructions.md` | MCP Handoff Contract has "Read discipline" | Add selective-loading guidance to MCP Handoff Contract | yes; existing read discipline preserved | Structure review |

## Proposed Solution

Five slices adding protocol sections, decision templates, skill updates, and loading policies. Each slice produces usable guidance plus structural verification. No code changes; all deliverables are documentation and process rules.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Process rules | `docs/agentic/instructions.md` | Add `## Agent Startup Protocol` section; add `ctx7` entry criteria; add selective-loading guidance to MCP Handoff Contract |
| Process rules | `docs/agentic/rules/development-workflow.md` | Add `## Cross-Boundary Change Protocol` section |
| Skill | `docs/agentic/skills/worktree-orchestrator/SKILL.md` | Add evidence checklist and decision template references |
| Skill | `docs/agentic/skills/worktree-worker/SKILL.md` | Add evidence collection steps and contract validation protocol |
| Templates | `docs/agentic/templates/DECISION_CONTRACT_CHANGE.template.md` | New file: contract change decision template |
| Templates | `docs/agentic/templates/DECISION_BREAKING_CHANGE.template.md` | New file: breaking change decision template |
| Templates | `docs/agentic/templates/DECISION_CROSS_LANE.template.md` | New file: cross-lane dependency decision template |

## Related Files

| File | Note |
| --- | --- |
| `docs/agentic/BOOTSTRAP.md` | References ctx7 setup; verify cross-references remain accurate after ctx7 entry criteria are added to instructions.md |
| `docs/agentic/maps/tech-stack.md` | Static library manifest; ctx7 entry criteria should reference this as fallback |
| `docs/agentic/contracts/agent-handoff-mcp.md` | MCP tool documentation; startup protocol references existing tools without changing them |
| `docs/agentic/rules/branch-review-guide.md` | Review Intake section now exists; startup protocol should align with it |
| `docs/agentic/rules/planning-review-guide.md` | Planning Intake section now exists; cross-boundary protocol should reference it |
| `CLAUDE.md` | References role selection and MCP handoff; verify new instructions.md sections do not contradict |

## Verification Strategy

- Deterministic tests:
  - None; this task is docs-only. No pytest/vitest/phpunit changes.
- Structural verification:
  - `grep_search(query="Agent Startup Protocol", includePattern="docs/agentic/instructions.md")` returns 1 match (Codex fallback: `grep -n 'Agent Startup Protocol' docs/agentic/instructions.md`)
  - `grep_search(query="Cross-Boundary Change Protocol", includePattern="docs/agentic/rules/development-workflow.md")` returns 1 match (Codex fallback: `grep -n 'Cross-Boundary Change Protocol' docs/agentic/rules/development-workflow.md`)
  - `grep_search(query="ctx7", includePattern="docs/agentic/instructions.md")` returns at least 3 matches (entry criteria, fallback, selective loading) (Codex fallback: `grep -n 'ctx7' docs/agentic/instructions.md | wc -l` returns 3 or more)
  - `grep_search(query="Evidence", includePattern="docs/agentic/skills/worktree-orchestrator/SKILL.md")` returns at least 1 match (Codex fallback: `grep -n 'Evidence' docs/agentic/skills/worktree-orchestrator/SKILL.md`)
  - `grep_search(query="Evidence", includePattern="docs/agentic/skills/worktree-worker/SKILL.md")` returns at least 1 match (Codex fallback: `grep -n 'Evidence' docs/agentic/skills/worktree-worker/SKILL.md`)
  - Template files exist: `ls docs/agentic/templates/DECISION_*.template.md` returns 3 files (Codex fallback: `find docs/agentic/templates -name 'DECISION_*.template.md' | wc -l` returns 3)
- Manual verification:
  - An agent following the startup protocol from cold start loads exactly: MCP state, lane inbox, role routing, relevant contracts, and open findings; nothing else by default.
  - An agent following the cross-boundary change protocol can discover which contracts must be validated before coding, run targeted tests, and produce a structured decision record.

---

## Slice Delivery

### Slice 1: Agent Startup Protocol in instructions.md

**Goal**: Add a single ordered startup checklist that all agents follow when entering a session, whether cold-start or mid-task re-entry.

Changes:

- Add `## Agent Startup Protocol` section to `instructions.md` after the Role Selection table and before the Critical Rules section.
- The protocol is an ordered checklist:
  1. Query MCP state: `get_handoff_state(task_ref="<task>")` to load current task objective, open blockers, and latest decisions.
  2. If in a lane: poll `make lane-inbox` or equivalent MCP query to load open dispatch messages, latest worker report, and lane activity.
  3. Load role routing: select domain from Role Selection table; load the linked context map, guidelines, and testing guide.
  4. Check open findings: `list_review_findings(status="open")` to avoid re-raising known issues or missing assigned fixes.
  5. Verify relevant contracts: if the task touches a cross-service boundary, confirm the owning contract exists in `docs/agentic/contracts/` and load it.
  6. Check ctx7 need: if modifying library-dependent code, resolve the library id via ctx7 for current upstream docs (see ctx7 entry criteria below).
- Add a note distinguishing cold-start (initialize handoff state if none exists) from mid-task re-entry (load prior slice completion summaries via `search_handoff`).
- Add a fallback note: if MCP handoff is unavailable, read `CURRENT_TASK.md` as a stale human-readable cache and record the MCP unavailability as a blocker.

Proof:

- `grep_search(query="Agent Startup Protocol", includePattern="docs/agentic/instructions.md")` returns 1 match

### Slice 2: Cross-Boundary Change Protocol in development-workflow.md

**Goal**: Add a proactive discovery and validation protocol for changes that cross service, language, or contract boundaries.

Changes:

- Add `## Cross-Boundary Change Protocol` section to `development-workflow.md` after the Scaffolding First section.
- The protocol is an ordered checklist:
  1. **Discover**: Before coding, query `docs/agentic/contracts/` for contracts touching the boundary. If no contract exists and the change adds a cross-service call, scaffold the contract first (per Scaffolding First).
  2. **Validate**: Confirm the current contract matches the implementation. If the contract is stale, update it in the same slice as the code change.
  3. **Test**: Map changed contract fields to downstream test assertions. Mark affected tests for re-run. If no test covers the changed field, add one in the same slice.
  4. **Runtime check**: For remote calls (PHP to Python, frontend to REST), verify the call works under the real runtime path, not only under test stubs. If runtime-parity verification is not possible locally, document the gap as a finding.
  5. **Record**: Use `record_decision` with a structured template (see Decision Templates) citing: which contract changed, what was verified, what downstream consumers were checked, and what assumptions are safe to make.
  6. **Notify**: If the change affects another lane, send a lane message via `make lane-dispatch` or `record_lane_message` with the contract change summary.
- Add a note: this protocol applies whenever a code change touches a cross-service or cross-contract boundary, including single-surface changes that alter or depend on another layer's contract. Use these path families as heuristics for boundary detection: `apps/prototype-description-service/`, `apps/prototype-wp-alt-context/src/`, `apps/prototype-wp-alt-context/js/`, `packages/agent-handoff-mcp/`, `docs/agentic/contracts/`. Any change within one of these stacks that modifies a shared type, endpoint signature, REST route, database schema, or MCP API surface triggers the protocol regardless of how many path families are touched.

Proof:

- `grep_search(query="Cross-Boundary Change Protocol", includePattern="docs/agentic/rules/development-workflow.md")` returns 1 match

### Slice 3: Decision Templates

**Goal**: Create three reusable decision templates for the most common cross-boundary handoff decisions so agents produce structured, parseable rationale instead of ad hoc prose.

Changes:

- Create `docs/agentic/templates/DECISION_CONTRACT_CHANGE.template.md`:
  - Fields: boundary name, contract path, fields changed (added/removed/renamed), tests verifying the change (with pass counts), downstream consumers checked, assumptions safe to make, ctx7 library id if external dependency influenced the change
- Create `docs/agentic/templates/DECISION_BREAKING_CHANGE.template.md`:
  - Fields: what broke, why it is necessary (cite contract or spec), how consumers can migrate, deprecation timeline (or "greenfield; no deprecation needed"), tests proving the new shape, downstream lanes notified
- Create `docs/agentic/templates/DECISION_CROSS_LANE.template.md`:
  - Fields: source lane, target lane, dependency type (contract, schema, type, test fixture), what the target lane needs to do, evidence justifying the dependency (test output, contract diff, type error), urgency (blocking vs informational)

Proof:

- `ls docs/agentic/templates/DECISION_*.template.md` returns 3 files
- Each template has a `## Fields` section listing required and optional fields

### Slice 4: Orchestrator and Worker Skill Updates

**Goal**: Update both worktree skills to require evidence-oriented handoff usage and reference the new decision templates.

Changes:

- In `worktree-orchestrator/SKILL.md`:
  - Add a `## Handoff Evidence Checklist` subsection under the existing workflow guidance:
    - Before dispatching work to a lane: verify that the contract surface the worker will consume exists and is current; cite the contract path in the dispatch message.
    - Before accepting a lane handoff: verify that the worker's slice completion summary cites changed contracts, test counts, and schema changes per the existing summary format.
    - When routing review findings to lanes: include the contract path and verification command in the finding's `fix` field so the worker can act without re-discovering context.
  - Reference the decision templates by path for workers to use at handoff.

- In `worktree-worker/SKILL.md`:
  - Add a `## Evidence Collection` subsection:
    - At implementation start: confirm all contracts touching your lane's owned paths are loaded; if a contract is missing, record a blocker citing the missing contract path.
    - During implementation: when modifying a boundary call (REST endpoint, shared type, database schema), follow the Cross-Boundary Change Protocol in `development-workflow.md`.
    - At handoff: use the appropriate decision template for any contract or cross-lane change; include test pass counts and contract paths in the slice completion summary.
  - Add a note: workers must not hand off without citing at least one verification command result for each changed boundary.

Proof:

- `grep_search(query="Handoff Evidence Checklist|Evidence Collection", includePattern="docs/agentic/skills/**")` returns 2 matches (one per skill file)

### Slice 5: Selective Loading and ctx7 Entry Rules in instructions.md

**Goal**: Add selective handoff-loading guidance and ctx7 entry criteria so agents spend tokens on relevant context instead of bulk-ingesting docs.

Changes:

- Add `## Selective Handoff Loading` subsection to the MCP Handoff Contract section in `instructions.md`:
  - Hot state (always load at startup): current task objective, open findings, open blockers, latest verification, latest 3 decisions.
  - Warm state (load on demand): recent worker reports, recent lane activity, artifacts tagged to current slice.
  - Cold state (retrieve only through targeted search): archived findings, superseded plan cursors, verbose logs, large artifacts.
  - Rule: do not replay full handoff history into prompt context; use `search_handoff` for targeted retrieval of older records.
  - Rule: after MCP tools record a decision or finding, do not re-read the full task state; trust the write confirmation.

- Add `## ctx7 Entry Criteria` subsection to `instructions.md` (near the Role Selection table or in a new "Context Assignment" section):
  - Use ctx7 when: modifying code that depends on an upstream library/framework (FastAPI routes, Radix UI components, WordPress hooks, SQLAlchemy models) and you need current API surface, version-specific behavior, or migration guidance.
  - Do not use ctx7 for: repo-local rules, contracts, handoff state, codebase-specific architecture, or information already in `tech-stack.md`.
  - Fallback: if ctx7 is unavailable, use `tech-stack.md` as the static version manifest and note the unavailability in handoff.
  - Cache: when a ctx7 lookup materially informs an implementation decision, record the resolved library id and query in the handoff decision so future agents do not re-spend tokens.

Proof:

- `grep_search(query="Selective Handoff Loading|ctx7 Entry Criteria", includePattern="docs/agentic/instructions.md")` returns 2 matches
- `grep_search(query="ctx7", includePattern="docs/agentic/instructions.md")` returns at least 3 matches

---

## Lane Decomposition (Multi-Agent)

> This task is docs-only with no cross-lane code dependencies. All five slices can be completed by a single agent in sequential order. Multi-agent decomposition is not warranted.

---

# Consolidated Checklist

## Context and Ownership

- [x] Loaded `instructions.md`, `development-workflow.md`, both worktree skills, `BOOTSTRAP.md`, and the epic's Phase 1 deliverables before editing.
- [x] Confirmed no MCP tool code changes are needed; all deliverables are documentation.
- [x] Verified that existing Role Selection, Plugin Boundary Rule, and MCP Handoff Contract sections are not contradicted by new additions.

## Slice 1: Agent Startup Protocol

- [x] `## Agent Startup Protocol` section added to `instructions.md` after Role Selection, before Critical Rules.
- [x] Ordered checklist covers: MCP state query, lane inbox, role routing, open findings, contract check, ctx7 check.
- [x] Cold-start vs mid-task re-entry distinction documented.
- [x] MCP unavailability fallback documented.
- [x] String-search verification: `grep_search` for "Agent Startup Protocol" returns 1 match.

## Slice 2: Cross-Boundary Change Protocol

- [x] `## Cross-Boundary Change Protocol` section added to `development-workflow.md` after Scaffolding First.
- [x] Protocol covers: discover, validate, test, runtime check, record, notify.
- [x] Boundary trigger paths listed (description-service, wp-alt-context/src, wp-alt-context/js, agent-handoff-mcp, contracts).
- [x] String-search verification: `grep_search` for "Cross-Boundary Change Protocol" returns 1 match.

## Slice 3: Decision Templates

- [x] `DECISION_CONTRACT_CHANGE.template.md` created with required fields.
- [x] `DECISION_BREAKING_CHANGE.template.md` created with required fields.
- [x] `DECISION_CROSS_LANE.template.md` created with required fields.
- [x] All three templates reference the cross-boundary change protocol.
- [x] File existence verified: `ls docs/agentic/templates/DECISION_*.template.md` returns 3 files.

## Slice 4: Orchestrator and Worker Skill Updates

- [x] `worktree-orchestrator/SKILL.md` has `## Handoff Evidence Checklist` subsection.
- [x] `worktree-worker/SKILL.md` has `## Evidence Collection` subsection.
- [x] Both skills reference decision templates by path.
- [x] No policy text duplicated from `instructions.md` or `development-workflow.md`; skills route to canonical sources.
- [x] String-search verification: `grep_search` for "Handoff Evidence Checklist" and "Evidence Collection" returns 1 match each.

## Slice 5: Selective Loading and ctx7 Entry Rules

- [x] `## Selective Handoff Loading` subsection added to MCP Handoff Contract in `instructions.md`.
- [x] Hot/warm/cold state tiers defined with loading rules.
- [x] `## ctx7 Entry Criteria` subsection added to `instructions.md`.
- [x] Entry, exclusion, fallback, and cache rules defined.
- [x] String-search verification: `grep_search` for "Selective Handoff Loading" and "ctx7 Entry Criteria" returns 1 match each.

## Review Readiness

- [x] No new section contradicts existing instructions.md rules or CLAUDE.md triggers.
- [x] Skills remain thin; no duplicated policy text.
- [x] Decision templates are self-contained and reference the cross-boundary protocol.
- [x] Handoff decision records the change, verification, and contract implications.
- [x] `BOOTSTRAP.md` and `tech-stack.md` cross-references verified accurate.

## Success Criteria

- [x] An agent following the startup protocol from cold start loads exactly: MCP state, lane inbox, role routing, relevant contracts, and open findings.
- [x] An agent following the cross-boundary change protocol can discover contracts, run targeted tests, and produce a structured decision with evidence.
- [x] A downstream agent reading a contract-change decision finds: boundary name, fields changed, tests passed, assumptions safe to make.
- [x] `ctx7` is invoked only when modifying library-dependent code; static `tech-stack.md` suffices for version inventory.
- [x] MCP handoff loading distinguishes hot, warm, and cold state; agents do not bulk-replay history.
