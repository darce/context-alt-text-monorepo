# E17. Skill Formalization and Process Automation (v0.4.0)

> **Epic Short ID**: E17

- **Date**: 2026-04-12
- **Author**: Claude Opus 4.6
- **Predecessor**: [Agentic Development Process Hardening (v0.3.0)](../v0.3.0/agentic-development-process-hardening-epic.md)

## Objective

Formalize the branch review, planning review, handoff lifecycle, and branch lifecycle processes into discrete, gated execution skills following agent-skills anatomy conventions; wire each skill to Makefile targets backed by MCP tools; and introduce automated spec/plan validation that feeds findings directly into the handoff DB. When this epic is complete, every major development workflow is a discoverable, executable skill with convergence criteria, context budgets, and Makefile entry points — not prose a model has to interpret from a 500-line guide.

## Problem Statement

The process hardening epic (v0.3.0) built the durable substrate: handoff DB, review findings, pre-merge gate, branch isolation, worktree lanes. But agents still interact with that substrate through long-form prose guides (`branch-review-guide.md`, `planning-review-guide.md`, `planning-pipeline.md`, `development-workflow.md`) that are loaded in bulk and interpreted ad hoc. This creates four failure modes:

1. **Context bloat.** Agents load 500-line review guides when they need a 20-step execution skill. The guide's educational value is high; its per-invocation token cost is also high.
2. **Inconsistent skill formality.** The 11 existing skills vary from 64-line checklists (`rescue-lane`) to 291-line playbooks (`refactor`). None have context budgets. None distinguish advisory guidance from gated execution loops. None reference Makefile targets or MCP tools as their API surface.
3. **Manual planning validation.** The planning-review checklist is entirely human-driven. The spec-kit evaluation (see `docs/assessments/agentic/agent-skills-vs-spec-kit-evaluation.md`) confirmed that spec-kit's analysis methodology — duplication, ambiguity, underspecification, constitution alignment, coverage gaps, terminology drift — is an LLM-powered prompt template, not a Python library. This means it can be adopted as a skill with zero runtime dependencies.
4. **No machine-checkable constitution.** The repo's `[sr-NNN]` and `[rg-NNN]` rules are prose counters in `instructions.md`. They are not loadable as a validation reference that a plan-analyze skill can check against.

The v0.3.0 epic built the engine. This epic builds the cockpit.

## UX Vision

An agent starting a new feature or epic runs `/scope` first. The skill asks 3–5 questions before generating anything — scope, completion signals, edge cases, non-functional constraints, and explicit not-doing. Each answer is recorded in MCP as a decision, surviving across sessions and agents. The resulting one-pager seeds the assessment instead of the agent guessing at scope.

An agent starting a branch review runs `make review-run` (agent-assisted target). The target sets up the environment; the agent reads the `branch-review` skill and follows its gated process: load review packet from MCP, run detection passes, record findings via `review_findings(batch_record)`, record the review run, and stop when convergence criteria are met. The agent never reads `branch-review-guide.md` in full — the skill extracts the executable subset.

An agent reviewing a task plan first runs `make plan-analyze` (agent-assisted target) for automated triage, then `make plan-review` for the canonical review pass. The analyzer loads the plan plus `constitution.md` and runs six detection passes; the reviewer resolves analyzer findings and adds judgment-requiring findings. Both targets require an active agent session — the LLM executes the skill's structured process against the loaded artifacts.

An agent starts each implementation slice with `make slice-start TEST_CMD="..."` to record the failing-test gate, then lands the slice with `make slice-commit MSG="..."` so the commit and `close_slice` write happen in one step. An agent finishing a task runs `make task-finish`. The skill runs `handoff_close_check`, merges, cleans up the worktree, archives the task, and regenerates the dashboard. The Makefile target is the entry point; the skill defines the loop; the MCP tools enforce the gates.

Structural validation — frontmatter schema, rule formatting, skill anatomy compliance — runs headlessly via `make check-skills` and `make check-all`, with no agent required.

## Constraints

- **MCP handoff remains the state substrate.** Skills invoke MCP tools; they do not maintain parallel state.
- **No new Python runtime dependencies.** The spec-kit analysis methodology is adopted as a skill prompt, not as a vendored Python package.
- **Guides become reference, skills become executable.** The existing review guides are not deleted — they become the reference documentation that skills link to for edge cases and rationale. The skill is the executable subset; the guide is the manual.
- **Agent-agnostic.** Skills must work for Claude Code, Codex, and any future agent that can read `.claude/skills/` and invoke Makefile targets. No model-specific assumptions in skill definitions.
- **Backward-compatible with existing Makefile surface.** New targets extend the Makefile; existing targets (`review-ready`, `task-start`, `task-finish`, `check-all`) keep their current behavior but may be wrapped by skills.

## Implementation Paradigm

> **Mandatory for all E17 implementation work. The default for all new task plans going forward.**

### TDD — mandatory, not advisory

Every implementation slice begins with a failing test. No production code may be written before `make slice-start TEST_CMD="..."` records `test_result(passed=false)` in handoff. The sequence is invariant:

1. **RED** — write the failing test → `make slice-start` records the gate before any edit
2. **GREEN** — implement minimal code to pass → record `test_result(passed=true)`
3. **REFACTOR** — clean without breaking → `make slice-commit`

Execution skills that gate implementation work declare `tdd_gate: true` in their frontmatter. Advisory skills default to `tdd_gate: false`. A slice that does not start with a recorded failing test is invalid; the pre-merge gate enforces this via `handoff_close_check`.

### Vertical slices — the default decomposition unit

Implementation is decomposed into vertical feature slices, not horizontal domain layers. A slice delivers a complete end-to-end path (DB schema → service layer → API endpoint → UI component) for one user-visible behavior. This allows each slice to be independently testable, demoable, and mergeable before the next begins.

**Horizontal decomposition** (`backend` lane, `frontend` lane, `wp-proxy` lane) is an exception path only for hard runtime isolation boundaries (separate service, no shared test surface, no cross-layer contract coupling). When horizontal lanes are unavoidable, name them after the feature they deliver (`auth-api-cleanup`), not the layer they touch (`backend`). See [playbooks/worktree-orchestration-playbook.md](../playbooks/worktree-orchestration-playbook.md#lane-decomposition-strategy) for the full strategy.

### Worktree status integrity — invariant close sequence

The most common source of stale `active` dashboard entries is tasks archived before their handoff status reaches `done`. The full close sequence is:

1. `update_task_status(task_ref=..., status="done")` — mark the task done in handoff DB
2. `manage_worktree_lane(action="close", ...)` — close the orchestrator lane registration (agent-orchestrator-mcp; applies when orchestrated lanes were opened at task-start)
3. `archive_task_state(task_ref=...)` — archive the task snapshot
4. `generate_current_task_md()` + `generate_dashboard_md()` — regenerate both views with the archived status

**Current implementation** (`make task-finish` → `scripts/_task_finish_inline.py`): steps 1, 3, and 4 are executed today. Step 2 (`manage_worktree_lane(close)`) is an agent-directed MCP call; the `branch-lifecycle` skill (Phase 2) will document it as a required step when orchestrated lanes are in use.

`manage_worktree_lane(close)` marks the lane closed in the orchestrator but does **not** update the handoff task status. Always run `update_task_status(done)` before both `manage_worktree_lane(close)` and `archive_task_state`.

`switch_task` (agent-orchestrator-mcp) provides the safe task-transition entry point when starting a new task while another is in flight: it verifies the current task status before switching, preventing mid-flight switches that leave the previous task orphaned as `in_progress`.

---

## Terminology

- **Skill anatomy**: The standardized structure for a SKILL.md file: frontmatter, overview, triggers, core process, common rationalizations, red flags, verification/convergence, see-also.
- **Execution skill**: A skill with `mode: execution` that manages a gated loop with convergence criteria and MCP state writes. May not be exited until convergence or explicit abort.
- **Advisory skill**: A skill with `mode: advisory` that recommends actions without managing a loop. Used for investigation, analysis, and guidance.
- **Constitution**: A machine-loadable document (`docs/agentic/constitution.md`) that formalizes the repo's `[sr-NNN]` and `[rg-NNN]` rules as checkable constraints for plan validation.
- **Detection pass**: One of six analysis checks (duplication, ambiguity, underspecification, constitution alignment, coverage gaps, terminology drift) run against planning artifacts.

## Current State

- 11 skills exist in `.claude/skills/`, all with convergence criteria sections, none with context budgets or mode tags.
- `.claude/commands/` is empty — no slash commands are defined.
- 80+ Makefile targets exist across 5 included modules, covering task/lane lifecycle, testing, linting, and orchestration.
- 35 current MCP tools across `agent-handoff-mcp` (19) and `agent-orchestrator-mcp` (16).
- 13 templates in `docs/agentic/templates/`.
- Review guides are 250+ lines each and loaded in bulk.
- Planning validation is entirely manual (checklist in `planning-review-guide.md`).
- No constitution document exists; rules are scattered as `[sr-NNN]`/`[rg-NNN]` counters in `instructions.md`.
- The `superpowers-evaluation.md` and `agent-skills-vs-spec-kit-evaluation.md` assessments both recommend pattern extraction over wholesale vendoring.

## Applied Concepts from Sources

| Source | Concept | Epic application |
|--------|---------|------------------|
| `addyosmani/agent-skills` | Skill anatomy: frontmatter, triggers, gated process, rationalizations, red flags, verification | Standardize all `.claude/skills/` definitions to this anatomy |
| `addyosmani/agent-skills` | Advisory vs execution skill distinction | Tag every skill with `mode: advisory\|execution` to clarify loop ownership |
| `addyosmani/agent-skills` | Context budget discipline (~2,000 lines target) | Add `context_budget` field to skill frontmatter |
| `addyosmani/agent-skills` | `idea-refine` reversal pattern: ask 3–5 questions before generating any output | `scope` intake skill: question-first before any planning artifact; Q&A recorded as MCP decisions |
| `github/spec-kit` | Six detection passes for plan validation (prompt-based, not code) | Adopt as the `plan-analyze` skill's core process |
| `github/spec-kit` | Constitution-driven alignment checking | Create `constitution.md` from `[sr/rg-NNN]` rules as machine-loadable validation reference |
| `github/spec-kit` | Before/after lifecycle hooks for stage transitions | Wire planning exit gates as hookable Makefile targets |
| `docs/assessments/agentic/agent-skills-vs-spec-kit-evaluation.md` | Hybrid extraction recommendation | This epic implements the three-part recommendation from that assessment |

## Target Architecture

```
User / Agent
     |
     v
 Makefile target (entry point)
     |
     v
 Skill (execution logic + convergence gate)
     |
     v
 MCP tools (state reads/writes)
     |
     v
 handoff.db (durable state)
```

Every major workflow is a three-layer stack: **Makefile target** (invocation) -> **Skill** (logic) -> **MCP tool** (state). The skill is the new layer this epic adds between the existing Makefile surface and the existing MCP surface.

### Runtime Model: How Make Targets and Skills Connect

Skills are **agent-read documents**, not scripts. A Makefile target does not directly invoke a SKILL.md file. The two layers connect through distinct runtime modes:

**Agent-assisted targets** (e.g., `make plan-analyze`, `make review-run`, `make plan-review`): The Makefile target handles environment setup (worktree detection, path validation, context file printing) and prints guidance pointing the agent to the relevant skill. The agent reads the skill's structured process and executes it using MCP tools. These targets require an active agent session — they are not headless CI checks. The "automation" is that the skill replaces ad-hoc checklist interpretation with a gated procedure the agent follows deterministically. This is the same model as the existing `make review-run` target.

**Deterministic targets** (e.g., `make check-skills`, `make lint-task-plans`): The Makefile target invokes a real shell script or Python module that runs without an agent. These are CI-safe and produce pass/fail exit codes. `make check-skills` validates SKILL.md frontmatter schema; it does not execute skill logic.

The planning exit gates wire `plan-analyze` as a required agent-executed step (an agent must run the skill and record findings before the plan is considered review-ready), not as a headless pre-merge check. The headless layer is `make check-skills` for structural validation only.

### Design Decisions

| Decision | Rationale |
|----------|-----------|
| Skills are `.claude/skills/*/SKILL.md` files, not Python code | Agent-agnostic; works for any model that reads markdown. No runtime dependency. |
| Agent-assisted vs deterministic target distinction | Skills that require LLM judgment (review, analysis) run inside agent sessions. Structural checks (frontmatter schema, lint) run headless. Neither pretends to be the other. Resolves [rg-006]: documented commands run as written because the runtime model is explicit. |
| Constitution is a markdown document, not a YAML/JSON schema | Keeps the validation LLM-powered (consistent with spec-kit's approach). Machine-loadable means structured markdown, not necessarily machine-parseable. |
| Constitution is the single canonical source for `[sr/rg-NNN]` rules | `docs/agentic/constitution.md` becomes authoritative. Both `instructions.md` and `CLAUDE.md` reference it by path instead of duplicating rule text. This prevents three-way drift. |
| Guides are preserved as reference docs, not replaced | Skills extract the executable path; guides retain rationale, edge cases, and context for human readers and complex scenarios. |
| Makefile targets are the canonical invocation surface | Already the repo convention. Skills document what the target does; the target handles environment setup (PYTHONPATH, worktree detection, etc.). |
| No new MCP tools in this epic | The existing 35 tools cover the state operations. Skills compose existing tools, not add new ones. Exception: if plan-analyze needs a `validate_constitution` helper, that would be a Phase 3 stretch. |

### Data Model

No schema changes. The constitution is a new markdown document. Skills are new SKILL.md files. Makefile targets are new or extended. All state flows through existing handoff DB tables.

## Phased Delivery

### Phase 1: Skill Anatomy Template and Constitution -- not-started

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Establish the skill anatomy standard and the constitution document that all subsequent skills will reference.

Deliverables:

- Skill anatomy template (`docs/agentic/templates/SKILL_ANATOMY.template.md`) based on agent-skills patterns, adapted for this repo's MCP + Makefile stack
- `mode: advisory|execution` field in frontmatter
- `context_budget` field in frontmatter (line count target for context the skill loads)
- `makefile_target` field in frontmatter (the Makefile entry point, if any)
- `mcp_tools` field in frontmatter (the MCP tools the skill composes)
- Constitution document (`docs/agentic/constitution.md`) as the **single authoritative source** for `[sr-NNN]` and `[rg-NNN]` rules, extracted from `instructions.md` and structured as numbered checkable constraints. Both `instructions.md` and `CLAUDE.md` are updated in the same slice to reference `constitution.md` by path instead of duplicating rule text, so there is exactly one canonical copy — not three.
- Retrofit 2-3 existing skills to the new anatomy as proof (candidates: `commit2git`, `review`, `investigate`)

Exit criteria:

- Skill anatomy template exists and is referenced from `docs/agentic/templates/`
- Constitution document exists with all current `[sr-NNN]` and `[rg-NNN]` rules formatted as checkable constraints
- `instructions.md` and `CLAUDE.md` reference `constitution.md` by path for rule definitions; inline rule text is replaced with references
- At least 2 existing skills pass the anatomy checklist (frontmatter fields present, mode tagged, convergence criteria, context budget)

### Phase 2: Core Workflow Skills -- not-started

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Create the discrete execution skills that replace bulk guide loading for the four core workflows.

> **Delivery order: `tdd` and `incremental-implementation` ship first.** They establish the TDD gate and vertical slice model that all other execution skills operate within. No implementation-facing execution skill is marked complete until its delivering agent has demonstrated TDD compliance on at least one slice.

Deliverables:

- **`scope` skill** (`mode: advisory`, `tdd_gate: false`) — _deliver with `planning-review`_
  - Elicits requirements before any planning artifact is written (reversal/question-first pattern)
  - Core process: ask 3–5 targeted questions via `AskUserQuestion` (scope, completion signals, edge cases, non-functional constraints, not-doing) → record each Q&A pair as `record_event(event_kind="decision")` → output `docs/ideas/[slug].md` one-pager (MVP scope, assumptions, Not-Doing list, success criteria)
  - Required for: new features, new epics, new capabilities. Exempt: bug fixes, tech debt tasks, spec-derived tasks.
  - MCP tools: `record_event`, `artifacts`
  - Context budget: ~60 lines of skill

- **`tdd` skill** (`mode: execution`, `tdd_gate: true`) — _deliver first_
  - Enforces RED → GREEN → REFACTOR ordering at slice start; establishes the machine-enforceable gate all other execution skills depend on
  - Core process: choose target test → run failing test → record `record_event(test_result, passed=false)` via `make slice-start` → only then allow implementation → record `test_result(passed=true)` after passing
  - MCP tools: `record_event`, `get_verified_tests`, `search_handoff`
  - Context budget: ~90 lines of skill

- **`incremental-implementation` skill** (`mode: execution`, `tdd_gate: true`) — _deliver second_
  - Enforces vertical, test-backed slice increments (DB → service → API → UI in one slice) instead of horizontal implementation waves; defines the default decomposition model for all feature work
  - Core process: choose the smallest end-to-end user path → write failing test → scaffold → implement → re-run tests → keep diff bounded → `make slice-commit`
  - MCP tools: `record_event`, `search_handoff`, `generate_current_task_md`; `plan_cursor` (agent-orchestrator-mcp — tracks which plan item each slice advances; `require_clean_slice` guard refuses upsert if open findings exist, enforcing the TDD integrity gate)
  - Context budget: ~100 lines of skill

- **`branch-lifecycle` skill** (`mode: execution`, `tdd_gate: true`)
  - Extracts the task-start → slice-work → task-finish lifecycle from `development-workflow.md` and `planning-pipeline.md`
  - Core process: `make task-start` → `make slice-start` → implementation loop (TDD) → `make slice-commit` → `make review-ready` → review → `make task-finish`
  - MCP tools: `set_handoff_state`, `record_event`, `close_slice`, `handoff_close_check`, `archive_task_state`, `generate_current_task_md`; `manage_worktree_lane` (agent-orchestrator-mcp — register lane at task-start, close as part of invariant finish sequence), `switch_task` (agent-orchestrator-mcp)
  - Context budget: ~150 lines of skill

- **`branch-review` skill** (`mode: execution`, `tdd_gate: false`)
  - Extracts the executable review loop from `branch-review-guide.md`
  - Core process: load review packet → pre-triage via `get_review_findings_summary` + `reconcile_review_findings` → check prior review runs via `review_runs(list)` → run detection passes → record findings via `review_findings(batch_record)` → record review run via `review_runs(record)` → verify convergence (zero unaddressed findings) → record verdict decision
  - References `make review-ready` and `make review-run` as Makefile entry points
  - MCP tools: `get_latest_slice_review_packet`, `review_findings`, `review_runs`, `record_event`, `handoff_close_check`; `get_review_findings_summary`, `reconcile_review_findings` (agent-orchestrator-mcp — pre-review triage: summarize and dedup existing findings before starting detection passes)
  - Context budget: ~150 lines of skill + loaded review packet (not the full 250-line guide)

- **`planning-review` skill** (`mode: execution`, `tdd_gate: false`)
  - Extracts the executable review loop from `planning-review-guide.md`
  - Core process: load planning document + code anchors → check prior review runs via `review_runs(list)` → run planning checklist passes → record findings via `review_findings(batch_record)` → record review run via `review_runs(record)` → verify convergence → record verdict
  - References `make plan-review` (new target) as Makefile entry point
  - MCP tools: `review_findings`, `review_runs`, `record_event`, `search_handoff`
  - Context budget: ~120 lines of skill + loaded plan + code anchors

- **`plan-analyze` skill** (`mode: advisory`, `tdd_gate: false`)
  - Implements the six spec-kit detection passes as a structured prompt
  - Core process: load plan + constitution + code anchors → run duplication/ambiguity/underspecification/constitution-alignment/coverage-gap/terminology-drift passes → produce findings table → record findings in MCP with `review_mode="analysis"`
  - References `make plan-analyze` (new target, agent-assisted) as Makefile entry point
  - MCP tools: `review_findings(batch_record)` for finding recording
  - Context budget: ~200 lines of skill + loaded plan + constitution
  - **Gate semantics**: `plan-analyze` is a pre-review triage step, not a substitute for the required planning review pass. Its findings are recorded with `review_mode="analysis"` (distinct from `review_mode="planning"`). It does NOT record a review run via `review_runs(record)` — only `planning-review` does that. The planning pipeline exit gate still requires at least one `planning`-mode review run.

- **`handoff-lifecycle` skill** (`mode: execution`, `tdd_gate: false`)
  - Extracts the session-start → work → handoff → resume pattern from `instructions.md` agent startup protocol
  - Core process: `make context` → `load_session` → verify alignment → work loop → record decisions → `generate_current_task_md` → session end; documents that `archive_task_state` must only be called after `update_task_status(status="done")`; documents that `switch_task` is the safe entry point for transitioning between tasks mid-session
  - MCP tools: `load_session`, `get_handoff_state`, `record_event`, `generate_current_task_md`; `switch_task` (agent-orchestrator-mcp — proper task transitions that verify current task status before switching)
  - Context budget: ~100 lines of skill

New Makefile targets:

- `plan-review` — invoke the planning-review skill with the target document
- `plan-analyze` — invoke the plan-analyze skill with the target document and constitution
- `slice-start` — record the failing-test gate for the current slice before implementation begins
- `slice-commit` — commit staged changes and record `close_slice` in one step
- Existing `review-ready`, `review-run`, `task-start`, `task-finish` remain; skills document their usage

New command files (one per skill, committed in the same slice as the skill):

- `.claude/commands/branch-review.md` — `/branch-review` slash command entry point
- `.claude/commands/planning-review.md` — `/planning-review` slash command entry point
- `.claude/commands/plan-analyze.md` — `/plan-analyze` slash command entry point
- `.claude/commands/branch-lifecycle.md` — `/branch-lifecycle` slash command entry point
- `.claude/commands/tdd.md` — `/tdd` slash command entry point
- `.claude/commands/incremental-implementation.md` — `/incremental-implementation` slash command entry point
- `.claude/commands/handoff-lifecycle.md` — `/handoff-lifecycle` slash command entry point

Each command file is ~15 lines: names the active skill, declares the Makefile entry point, and sets the execution context. This is the agent-agnostic invocation surface — a human or agent types `/branch-review` instead of relying on prose triggers in CLAUDE.md to load a 570-line guide.

Dashboard auto-refresh hook:

- **PostToolUse hook** in `.claude/settings.json` that runs `$(MCP_CMD) task` after every `record_event`, `review_findings`, and `review_runs` write. Ensures `CURRENT_TASK.md` and `DASHBOARD.md` are regenerated after state-changing writes without requiring an explicit agent call. The server-side path (`close_slice`, `update_task_status`, `archive_task_state`) already regenerates views atomically; this hook closes the gap for the remaining write operations. The `handoff-lifecycle` skill documents that `archive_task_state` must only be called after `update_task_status(status="done")` — archiving a task that is still `in_progress` causes the dashboard to render a permanent `active` fallback status.

Exit criteria:

- All 8 skills exist, pass the anatomy checklist, and reference their Makefile targets and MCP tools (`tdd`, `incremental-implementation`, `scope`, `branch-lifecycle`, `handoff-lifecycle`, `branch-review`, `planning-review`, `plan-analyze`)
- Each Phase 2 skill has a paired `.claude/commands/<skill>.md` entry point committed in the same slice
- `make plan-analyze` runs the six detection passes against a sample task plan and produces a findings table
- `make plan-review` invokes the planning-review skill
- `make slice-start` records a failing-test gate before implementation begins
- `make slice-commit` creates a commit and records a slice-complete decision against the new HEAD
- Each skill's context budget is under its declared target when measured against a representative invocation
- Dashboard auto-refresh hook is wired; CURRENT_TASK.md and DASHBOARD.md regenerate within one tool call of any state write

### Phase 3: Retrofit and Integration -- not-started

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Retrofit remaining skills to the anatomy template, wire constitution validation into planning exit gates, and verify end-to-end flow.

Deliverables:

- Retrofit remaining 8-9 skills to the new anatomy (add frontmatter fields, mode tags, context budgets, rationalizations, red flags)
- Wire `make plan-analyze` into the planning pipeline exit gate (Assessment -> Spec, Spec -> Task Plan) as an automated pre-check
- Add `make check-skills` target that validates all SKILL.md files have required frontmatter fields
- Update `CLAUDE.md` key triggers to reference skills instead of bulk guide loading
- Update `instructions.md` routing table to point to skills as primary entry points, guides as reference
- Mark `branch-review-guide.md` and `planning-review-guide.md` as reference appendices once their execution skills ship; move executable checklists into the skills and leave heuristics/rationale in the guides

Exit criteria:

- All skills pass `make check-skills` anatomy validation
- Planning pipeline exit gates include automated constitution-alignment check
- `CLAUDE.md` and `instructions.md` reference skills as the primary workflow entry points
- `branch-review-guide.md` and `planning-review-guide.md` are explicitly labelled as reference appendices, not primary execution surfaces
- End-to-end test: cold-start agent -> `make context` -> `make plan-analyze` on a sample plan -> findings recorded in MCP -> `make plan-review` -> verdict recorded -> `make task-start` -> implementation -> `make task-finish` -> clean main

## External Dependencies

| Dependency | Owner | Status | Blocks |
|-----------|-------|--------|--------|
| None | — | — | — |

This epic has no external dependencies. All work is internal to the repo's agentic tooling surface.

## Code Anchors

| Layer | File | Note |
|-------|------|------|
| Skills | `.claude/skills/*/SKILL.md` | All existing and new skill definitions |
| Templates | `docs/agentic/templates/SKILL_ANATOMY.template.md` | New template (Phase 1) |
| Constitution | `docs/agentic/constitution.md` | New document (Phase 1) |
| Makefile | `Makefile`, `mk/*.mk` | New and extended targets |
| Review guides | `docs/agentic/rules/branch-review-guide.md` | Preserved as reference; executable subset extracted to skills |
| Review guides | `docs/agentic/rules/planning-review-guide.md` | Preserved as reference; executable subset extracted to skills |
| Workflow | `docs/agentic/rules/development-workflow.md` | Preserved as reference; lifecycle extracted to skills |
| Pipeline | `docs/agentic/rules/planning-pipeline.md` | Preserved as reference; exit gates wired to plan-analyze |
| Instructions | `docs/agentic/instructions.md` | Rules extracted to constitution; routing updated to skills |
| MCP handoff | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Existing tools composed by skills; no changes expected |
| MCP orchestrator | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` | Existing tools composed by skills; no changes expected |

---

# Consolidated Checklist

## Phase 1: Skill Anatomy Template and Constitution -- not-started

- [ ] Create `docs/agentic/templates/SKILL_ANATOMY.template.md` with all required sections
- [ ] Define frontmatter schema: `name`, `description`, `mode`, `context_budget`, `makefile_target`, `mcp_tools`
- [ ] Create `docs/agentic/constitution.md` as the single canonical source for all `[sr-NNN]` and `[rg-NNN]` rules
- [ ] Update `instructions.md` and `CLAUDE.md` to reference `constitution.md` by path instead of duplicating rule text
- [ ] Retrofit `commit2git` skill to new anatomy
- [ ] Retrofit `review` skill to new anatomy
- [ ] Retrofit `investigate` skill to new anatomy
- [ ] Verify retrofitted skills have: frontmatter, mode tag, context budget, convergence criteria, rationalizations, red flags

## Phase 2: Core Workflow Skills -- not-started

- [ ] Create `scope` advisory skill with question-first intake process (3–5 `AskUserQuestion` calls, Q&A as MCP decisions, `docs/ideas/` one-pager output)
- [ ] Create `branch-review` execution skill
- [ ] Create `planning-review` execution skill
- [ ] Create `plan-analyze` advisory skill with six detection passes
- [ ] Create `branch-lifecycle` execution skill
- [ ] Create `handoff-lifecycle` execution skill
- [ ] Add `make plan-review` Makefile target
- [ ] Add `make plan-analyze` Makefile target
- [ ] Verify each skill references its Makefile targets and MCP tools in frontmatter
- [ ] Verify each skill's context budget is under its declared target
- [ ] Create paired `.claude/commands/<skill>.md` for each Phase 2 skill (7 files total)
- [ ] Add PostToolUse hook in `.claude/settings.json` to auto-regenerate CURRENT_TASK.md + DASHBOARD.md after `record_event`, `review_findings`, `review_runs` writes

## Phase 3: Retrofit and Integration -- not-started

- [ ] Retrofit remaining skills to new anatomy
- [ ] Add `make check-skills` validation target
- [ ] Wire `make plan-analyze` into planning pipeline exit gates
- [ ] Update `CLAUDE.md` key triggers to reference skills
- [ ] Update `instructions.md` routing to point to skills as primary entry points
- [ ] End-to-end validation of cold-start -> plan-analyze -> review -> implement -> finish flow

## Deferred (Post-v0.4.0)

- [ ] `validate_constitution` MCP tool for programmatic constitution checking (only if LLM-powered prompt approach proves insufficient)
- [ ] Skill composition graph visualization (which skills chain to which)
- [ ] Automated context-budget enforcement via linter (flag skills that load more than their declared budget)
- [ ] Archive guard: `archive_task_state` rejects tasks with status `in_progress` (or emits hard warning) to prevent permanent `active` fallback in dashboard — AHMCP scope
