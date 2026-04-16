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
2. **Inconsistent skill formality.** The repo now contains 19 skills total: 11 pre-epic legacy skills plus 8 Phase 2 additions. The legacy set still varies from 64-line checklists (`rescue-lane`) to 291-line playbooks (`refactor`). None of those pre-epic skills originally had context budgets, consistent advisory vs execution tags, or Makefile/MCP declarations as their API surface.
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
4. `generate_dashboard_md()` — regenerate the operator-facing cross-task view with the archived status (`generate_current_task_md()` on demand for task-scoped snapshots)

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

- Core workflow skills now exist in `.claude/skills/` with anatomy frontmatter, mode tags, and context budgets; the remaining legacy skills still need the Phase 3 retrofit pass.
- `.claude/commands/` now contains the Phase 2 command adapters, but `.github/prompts/` is still empty and Codex still relies on root-instruction routing rather than a generated command adapter surface.
- 80+ Makefile targets exist across 5 included modules, covering task/lane lifecycle, testing, linting, and orchestration.
- 35 MCP tools at epic open across `agent-handoff-mcp` (19) and `agent-orchestrator-mcp` (16); see Phase 4 for the planned AHMCP-31/AHMCP-32 additions.
- 13 templates in `docs/agentic/templates/`.
- Review guides are 250+ lines each and loaded in bulk.
- Planning validation now has an agent-assisted `plan-analyze` path, but it is not yet wired into the planning pipeline exit gates.
- `docs/agentic/constitution.md` now exists as the canonical rule source; the remaining Phase 3 work is to finish routing and validation integration around it.
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
| Phases 1-3 compose existing MCP tools; Phase 4 adds two narrow handoff extensions | The existing 35 tools covered the original skill-formalization scope. Phase 4 later introduced AHMCP-31 (`record_file_touch`, `get_touched_files`) and AHMCP-32 (`BranchMismatchError` enforcement path) as focused workflow-integrity exceptions rather than a change to the core design direction. |

### Data Model

No schema changes. The constitution is a new markdown document. Skills are new SKILL.md files. Makefile targets are new or extended. All state flows through existing handoff DB tables.

## Phased Delivery

### Phase 1: Skill Anatomy Template and Constitution -- done

> **Status**: done
> **Task plans**: [E17-1](../../tasks/17.0/E17-1-skill-anatomy-template-and-constitution-task-plan.md)

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

### Phase 2: Core Workflow Skills -- done

> **Status**: done
> **Task plans**: [E17-2](../../tasks/17.0/E17-2-tdd-and-incremental-implementation-skills-task-plan.md) · [E17-3](../../tasks/17.0/E17-3-core-workflow-skills-task-plan.md)

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
  - MCP tools: `record_event`, `search_handoff`, `generate_dashboard_md`; `plan_cursor` (agent-orchestrator-mcp — tracks which plan item each slice advances; `require_clean_slice` guard refuses upsert if open findings exist, enforcing the TDD integrity gate)
  - Context budget: ~100 lines of skill

- **`branch-lifecycle` skill** (`mode: execution`, `tdd_gate: true`)
  - Extracts the task-start → slice-work → task-finish lifecycle from `development-workflow.md` and `planning-pipeline.md`
  - Core process: `make task-start` → `make slice-start` → implementation loop (TDD) → `make slice-commit` → `make review-ready` → review → `make task-finish`
  - MCP tools: `set_handoff_state`, `record_event`, `close_slice`, `handoff_close_check`, `archive_task_state`, `generate_dashboard_md`; `manage_worktree_lane` (agent-orchestrator-mcp — register lane at task-start, close as part of invariant finish sequence), `switch_task` (agent-orchestrator-mcp)
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
  - References the existing agent-assisted `make plan-review` stub as its Makefile entry point
  - MCP tools: `review_findings`, `review_runs`, `record_event`, `search_handoff`
  - Context budget: ~120 lines of skill + loaded plan + code anchors

- **`plan-analyze` skill** (`mode: advisory`, `tdd_gate: false`)
  - Implements the six spec-kit detection passes as a structured prompt
  - Core process: load plan + constitution + code anchors → run duplication/ambiguity/underspecification/constitution-alignment/coverage-gap/terminology-drift passes → produce findings table → record findings in MCP with `review_mode="analysis"`
  - References the existing agent-assisted `make plan-analyze` stub as its Makefile entry point
  - MCP tools: `review_findings(batch_record)` for finding recording
  - Context budget: ~200 lines of skill + loaded plan + constitution
  - **Gate semantics**: `plan-analyze` is a pre-review triage step, not a substitute for the required planning review pass. Its findings are recorded with `review_mode="analysis"` (distinct from `review_mode="planning"`). It does NOT record a review run via `review_runs(record)` — only `planning-review` does that. The planning pipeline exit gate still requires at least one `planning`-mode review run.

- **`handoff-lifecycle` skill** (`mode: execution`, `tdd_gate: false`)
  - Extracts the session-start → work → handoff → resume pattern from `instructions.md` agent startup protocol
  - Core process: `make context` → `load_session` → verify alignment → work loop → record decisions → `generate_dashboard_md` after each state write (CURRENT_TASK.md on demand) → session end; documents that `archive_task_state` must only be called after `update_task_status(status="done")`; documents that `switch_task` is the safe entry point for transitioning between tasks mid-session
  - MCP tools: `load_session`, `get_handoff_state`, `record_event`, `generate_dashboard_md`, `generate_current_task_md`; `switch_task` (agent-orchestrator-mcp — proper task transitions that verify current task status before switching)
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

Each command file is ~15 lines: names the active skill, declares the Makefile entry point, and sets the execution context. In Phase 2 this delivered the first host adapter for Claude. Phase 4 extends that into a truly portable workflow surface: one canonical command manifest, generated `.claude/commands/*.md` and `.github/prompts/*.prompt.md` adapters, and root-instruction routing for Codex so `/branch-review` means the same thing everywhere.

Dashboard auto-refresh hook:

- **PostToolUse hook** in `.claude/settings.json` that runs `regenerate-task-views.sh` after `record_event`, `review_findings`, `review_runs`, `set_handoff_state`, and `update_task_status` calls. The hook reads the tool payload from stdin and uses a Python filter to fire only on state-changing writes (read operations — `list`, `get`, `coverage` — exit early). On a covered write: calls `agent-handoff-mcp write-dashboard` (DASHBOARD.md only). CURRENT_TASK.md is NOT regenerated by the hook — agents call `generate_current_task_md` on demand when a task-scoped machine snapshot is specifically needed. The server-side path (`close_slice`, `archive_task_state`) already regenerates views atomically; this hook closes the gap for the remaining write operations. The `handoff-lifecycle` skill documents that `archive_task_state` must only be called after `update_task_status(status="done")` — archiving a task that is still `in_progress` causes the dashboard to render a permanent `active` fallback status.

Exit criteria:

- All 8 skills exist, pass the anatomy checklist, and reference their Makefile targets and MCP tools (`tdd`, `incremental-implementation`, `scope`, `branch-lifecycle`, `handoff-lifecycle`, `branch-review`, `planning-review`, `plan-analyze`)
- Each Phase 2 skill has a paired `.claude/commands/<skill>.md` entry point committed in the same slice
- `make plan-analyze` runs the six detection passes against a sample task plan and produces a findings table
- `make plan-review` invokes the planning-review skill
- `make slice-start` records a failing-test gate before implementation begins
- `make slice-commit` creates a commit and records a slice-complete decision against the new HEAD
- Each skill's context budget is under its declared target when measured against a representative invocation
- Dashboard auto-refresh hook is wired; DASHBOARD.md regenerates within one tool call of any state-changing `record_event`, `review_findings`, `review_runs`, `set_handoff_state`, or `update_task_status` write (read-only ops filtered; CURRENT_TASK.md is on-demand only)

Architectural decisions recorded during Phase 2:

- **Decision #1676 (cdx_decision_E17-3_choose_task_plan_progress_sync_architecture)**: `agent-orchestrator-mcp` (plan_cursors) owns task-plan progress sync. Consolidated checklist items become complete only after related handoff review findings are resolved — not just on commit. Implementation of the sync/check tool and pre-merge gate hook is out of Phase 2 scope (requires code change to `agent-orchestrator-mcp`); deferred to Phase 3 or a follow-on task.

### Phase 3: Retrofit and Integration -- not-started

> **Status**: not-started
> **Task plans**: [E17-6](../../tasks/17.0/E17-6-phase3-retrofit-task-plan.md) · [E17-7](../../tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md)

**Goal**: Complete the Phase 3 core retrofit and planning-gate integration, then land the approved follow-on handoff/tooling work without collapsing it back into one oversized task plan.

**Scope note**: Phase 3 is now split into two task plans. `E17-6` carries the core retrofit/gating/routing work required to finish the original Phase 3 deliverables: anatomy retrofit, `check-skills`, harness contract + sync validation, review-routing cleanup, and the `plan-analyze` pre-review gate. `E17-7` carries the approved follow-on work that was split out to keep `E17-6` reviewable: handoff-state evolution for concurrent tasks, raw test-trace storage, MCP tool-surface compression, and portable workflow normalization that brings Codex onto the same manifest-driven command contract as Claude and VS Code. `E17-6` lands first; `E17-7` follows after the core passes review.

Deliverables:

- Retrofit remaining 8-9 skills to the new anatomy (add frontmatter fields, mode tags, context budgets, rationalizations, red flags)
- Wire `make plan-analyze` into the planning pipeline exit gate (Assessment -> Spec, Spec -> Task Plan) as an automated pre-check
- Add `make check-skills` target that validates all SKILL.md files have required frontmatter fields
- Update `CLAUDE.md` key triggers to reference skills instead of bulk guide loading
- Update `instructions.md` routing table to point to skills as primary entry points, guides as reference
- Mark `branch-review-guide.md` and `planning-review-guide.md` as reference appendices once their execution skills ship; move executable checklists into the skills and leave heuristics/rationale in the guides
- After the core lands, complete the approved follow-on in `E17-7`: concurrent active-task support in handoff state, raw test-trace storage, MCP tool-surface compression, and manifest-driven portable workflow normalization that includes Codex router generation and validation

Exit criteria:

- All skills pass `make check-skills` anatomy validation
- Planning pipeline exit gates include automated constitution-alignment check
- `CLAUDE.md` and `instructions.md` reference skills as the primary workflow entry points
- `branch-review-guide.md` and `planning-review-guide.md` are explicitly labelled as reference appendices, not primary execution surfaces
- End-to-end test: cold-start agent -> `make context` -> `make plan-analyze` on a sample plan -> findings recorded in MCP -> `make plan-review` -> verdict recorded -> `make task-start` -> implementation -> `make task-finish` -> clean main

### Phase 4: Workflow Integrity and Session Continuity -- in_progress

> **Status**: in_progress
> **Task plans**: [E17-4](../../tasks/17.0/E17-4-workflow-integrity-task-plan.md) · [E17-5](../../tasks/17.0/E17-5-dashboard-redesign-task-plan.md)

**Goal**: Close four failure classes identified in practice that undermine workflow discipline and cold-start reliability.

Started before Phase 3 because these failure classes were discovered while landing Phase 2 work and were actively blocking current delivery quality. `E17-5` is grouped here because it fixes operator-visible dashboard defects uncovered alongside `E17-4`, even though its rendering scope is orthogonal to the branch/workflow integrity fixes.

**Root-cause findings** (investigation 2026-04-14):

1. **Orphan branches** — `feature/ahmcp-8-verified-test-search-and-read-surfaces` and `feature/slr-003-suppress-cleanup` were left behind because their tasks were archived from a different branch (or after a manual merge to main), with no mechanism to detect or require cleanup. Neither `make context` nor `make check-all` flag branches that have no registered handoff task.

2. **Ad-hoc main changes without logging** — The branch-isolation guard blocks code edits on main, but does not require an active handoff task before any file edit. Docs, Makefiles, and config files accumulate uncommitted on main with no MCP provenance. At investigation time: 8 files dirty on main with no active task.

3. **File-touch state gap at cold start** — Agents reconstruct what was changed by running raw `git diff --name-only` or `git log --name-only` commands. The handoff DB stores changed-file lists as free text inside `## Changes` sections of slice decisions — structured enough for humans, not queryable as data. `load_session` returns no file-level change state. The result is every cold start re-derives what the last agent did from git rather than from handoff.

4. **Branch-delete not enforced after archive** — `make task-finish` deletes the feature branch, but tasks archived manually (e.g. `archive_task_state` called from main after a manual merge) leave their `target_branch` dangling. No guard enforces deletion as part of the invariant close sequence.

Deliverables:

- **Orphan branch audit** (`make worktree-audit`): Python script cross-references `git branch --list 'feature/*'` and `git branch --list 'codex/*'` against active `handoff_state.target_branch` and archived task snapshot `target_branch`; flags branches with no registration. (`task_archives.archived_branch` is not authoritative — use the snapshot field.) Included in `make check-all`.

- **Main-change guard extension** (`scripts/hooks/guard-main-branch.sh` + `.claude/settings.json`): PreToolUse hook warns when an Edit/Write is attempted with no active handoff task, regardless of file type. Introduces the **maintenance-task pattern** as a first-class workflow primitive: `set_handoff_state(task_ref='MAINT-<slug>', objective='...')` before any ad-hoc main-branch edit. `make context` reports when main is dirty with no active task.

- **Branch-delete enforcement** (`scripts/_task_finish_inline.py` + `development-workflow.md`): `make task-finish` extended to verify `target_branch` is deleted after archive; warns if branch persists. New rule in `development-workflow.md`: when `archive_task_state` is called for a task whose `target_branch != main`, the archiving agent must also delete the branch as part of the close sequence.

- **File-touch tracking** (requires **AHMCP-31** as sub-task — AHMCP-29 was reassigned to `switch_task archived_previous` flag, merged at `befbdce8`):
  - New `touched_files` table in handoff.db: `(task_ref, file_path, change_kind, session, commit_sha, touched_at)`
  - New MCP tool `record_file_touch(task_ref, file_path, change_kind)` — agents call when they edit files; PostToolUse hook auto-calls it after every Edit/Write
  - New MCP query `get_touched_files(task_ref)` — returns structured `(file_path, change_kind)` list
  - `load_session` response includes `touched_files` for the active task — replaces `git diff` at cold start

- **`make context` enhancement**: when main is dirty and no active task is registered, print the list of modified files and the maintenance-task registration command.

- **CLAUDE.md and `development-workflow.md` updates**: document maintenance-task pattern, orphan-audit rule, and branch-delete requirement explicitly.

- **Portable workflow surface** (E17-4 Slice 8): define workflow command ids once in `config/agent-workflows/portable_commands.json`, generate `.claude/commands/*.md` and `.github/prompts/*.prompt.md` from that manifest, and add root-instruction routing so Codex honors the same `/command` syntax. Validation target `make check-agent-workflows` fails on adapter drift. `scripts/generate_agent_workflows.py` validates `portable_commands.json` structurally at load time before rendering any adapter file, so malformed manifest entries fail fast with a descriptive error.

Exit criteria:

- `make worktree-audit` reports zero orphan branches on a clean repo; `make check-all` includes the orphan pass
- `make context` warns when main is dirty with no active task and prints affected files
- PreToolUse hook warns on Edit/Write with no active handoff task
- CLAUDE.md documents maintenance-task pattern; `development-workflow.md` documents branch-delete invariant
- `make task-finish` warns if `target_branch` is not deleted after archive
- AHMCP-31 delivered: `record_file_touch`, `get_touched_files`, `load_session` includes `touched_files`
- Cold-start test: fresh session → `load_session` returns what previous agent edited without running `git diff`
- `make context` exits 0 on drift (cascade-safe); startup batch `Bash(make context)` + `ToolSearch` completes without cancellation (E17-4 Slice 5)
- `make task-plan-audit` exits 0 when all tagged commits on `main` have plan files; exits 1 on gap; included in `make check-all` (E17-4 Slice 6)
- AHMCP-32 delivered: `agent-handoff-mcp` raises `BranchMismatchError` when `AGENT_HANDOFF_ENFORCE_BRANCH=1` and write comes from wrong branch (E17-4 Slice 7)
- `/branch-review`, `/planning-review`, and the other workflow command ids resolve through one canonical manifest with generated Claude and VS Code adapters plus Codex instruction routing; `make check-agent-workflows` catches drift (E17-4 Slice 8)
- DASHBOARD rendered as plain ASCII (no `.md` extension, no code fences); TEST STATUS scoped to active epic only (E17-5 Slices 1–2)

---

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
| Makefile | `Makefile`, `mk/*.mk` | New and extended targets; Phase 4 adds `worktree-audit` |
| Review guides | `docs/agentic/rules/branch-review-guide.md` | Preserved as reference; executable subset extracted to skills |
| Review guides | `docs/agentic/rules/planning-review-guide.md` | Preserved as reference; executable subset extracted to skills |
| Workflow | `docs/agentic/rules/development-workflow.md` | Preserved as reference; Phase 4 adds branch-delete invariant and maintenance-task pattern |
| Pipeline | `docs/agentic/rules/planning-pipeline.md` | Preserved as reference; exit gates wired to plan-analyze |
| Instructions | `docs/agentic/instructions.md` | Rules extracted to constitution; routing updated to skills |
| Portable workflow manifest | `config/agent-workflows/portable_commands.json` | Phase 4: canonical slash-command contract for all hosts |
| VS Code prompt adapters | `.github/prompts/*.prompt.md` | Phase 4: generated workspace prompt files mirroring portable workflow commands |
| Hooks | `scripts/hooks/guard-main-branch.sh` | Phase 4: extended to warn on Edit/Write with no active task |
| Task finish | `scripts/_task_finish_inline.py` | Phase 4: extended to verify branch deletion after archive |
| MCP handoff | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Phase 4 (AHMCP-31): `record_file_touch`, `get_touched_files`, `load_session` touched_files |
| MCP orchestrator | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` | Existing tools composed by skills; no changes expected |

---

# Consolidated Checklist

## Phase 1: Skill Anatomy Template and Constitution -- done

- [x] Create `docs/agentic/templates/SKILL_ANATOMY.template.md` with all required sections
- [x] Define frontmatter schema: `name`, `description`, `mode`, `context_budget`, `makefile_target`, `mcp_tools`
- [x] Create `docs/agentic/constitution.md` as the single canonical source for all `[sr-NNN]` and `[rg-NNN]` rules
- [x] Update `instructions.md` and `CLAUDE.md` to reference `constitution.md` by path instead of duplicating rule text
- [x] Retrofit `commit2git` skill to new anatomy
- [x] Retrofit `review` skill to new anatomy
- [x] Retrofit `investigate` skill to new anatomy
- [x] Verify retrofitted skills have: frontmatter, mode tag, context budget, convergence criteria, rationalizations, red flags

## Phase 2: Core Workflow Skills -- done

- [x] Create `scope` advisory skill with question-first intake process (3–5 `AskUserQuestion` calls, Q&A as MCP decisions, `docs/ideas/` one-pager output)
- [x] Create `branch-review` execution skill
- [x] Create `planning-review` execution skill
- [x] Create `plan-analyze` advisory skill with six detection passes
- [x] Create `branch-lifecycle` execution skill
- [x] Create `handoff-lifecycle` execution skill
- [x] Add `make plan-review` Makefile target
- [x] Add `make plan-analyze` Makefile target
- [x] Verify each skill references its Makefile targets and MCP tools in frontmatter
- [x] Verify each skill's context budget is under its declared target
- [x] Create paired `.claude/commands/<skill>.md` for each Phase 2 skill (7 files total; Phase 4 Slice 8 replaces these with generated adapters, so they are no longer hand-edited after that slice ships)
- [x] Add PostToolUse hook in `.claude/settings.json` to auto-regenerate DASHBOARD.md (only) after state-changing `record_event`, `review_findings`, `review_runs`, `set_handoff_state`, `update_task_status` writes (read ops filtered; CURRENT_TASK.md on-demand)

## Phase 3: Retrofit and Integration -- not-started (E17-6)

- [ ] Retrofit remaining skills to new anatomy
- [ ] Add `make check-skills` validation target
- [ ] Wire `make plan-analyze` into planning pipeline exit gates
- [ ] Update `CLAUDE.md` key triggers to reference skills
- [ ] Update `instructions.md` routing to point to skills as primary entry points
- [ ] End-to-end validation of cold-start -> plan-analyze -> review -> implement -> finish flow

## Phase 4: Workflow Integrity and Session Continuity -- in_progress

- [ ] Write `scripts/worktree_audit.py`: cross-reference local `feature/*` and `codex/*` branches against active `handoff_state.target_branch` and archived snapshot `target_branch`; exit non-zero if orphans found
- [ ] Add `make worktree-audit` Makefile target; include in `make check-all`
- [ ] Extend `scripts/hooks/guard-main-branch.sh`: warn (non-blocking) when Edit/Write invoked with no active handoff task; print maintenance-task registration command
- [ ] Update `make context` output: report dirty main files + active-task status together
- [ ] Document maintenance-task pattern in `CLAUDE.md` Critical Rules and `docs/agentic/rules/development-workflow.md`
- [ ] Extend `scripts/_task_finish_inline.py`: after archive, verify `target_branch` deleted; warn if branch still exists
- [ ] Document branch-delete invariant in `development-workflow.md § Invariant Close Sequence`
- [ ] AHMCP-31 (not AHMCP-29): `touched_files` schema migration, `record_file_touch` MCP tool, `get_touched_files` MCP query
- [ ] AHMCP-31: `load_session` response includes `touched_files` for active task
- [ ] Wire PostToolUse hook to auto-call `record_file_touch` after Edit/Write in `.claude/settings.json` and `.github/hooks/terminal-guard.json`
- [ ] Cold-start verification: `load_session` returns `touched_files` without `git diff`
- [ ] `check-task-context.py` drift exit changed from `sys.exit(2)` to `sys.exit(0)` — cascade-safe (E17-4 Slice 5)
- [ ] `CLAUDE.md` Agent Startup Protocol: no-parallel-batch rule added (E17-4 Slice 5)
- [ ] `scripts/task_plan_audit.py` written; `make task-plan-audit` added; included in `make check-all` (E17-4 Slice 6)
- [ ] AHMCP-32: `BranchMismatchError` in `shared_write_context.py`; `AGENT_HANDOFF_ENFORCE_BRANCH=1` env gate (E17-4 Slice 7)
- [ ] Portable workflow manifest added; `.claude/commands/*` and `.github/prompts/*` generated from one source; Codex root instructions route the same `/command` ids (E17-4 Slice 8)
- [ ] E17-5 Slice 1: DASHBOARD written as plain ASCII (no `.md` extension, no code fences in ALL TASKS table)
- [ ] E17-5 Slice 2: TEST STATUS section scoped to active epic prefix only (`_collect_task_test_status(epic_ref)` filter)

## Deferred (Post-v0.4.0)

- [ ] `validate_constitution` MCP tool for programmatic constitution checking (only if LLM-powered prompt approach proves insufficient)
- [ ] Skill composition graph visualization (which skills chain to which)
- [ ] Automated context-budget enforcement via linter (flag skills that load more than their declared budget)
