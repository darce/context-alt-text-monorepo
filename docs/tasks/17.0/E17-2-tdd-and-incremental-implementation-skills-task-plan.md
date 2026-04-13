# E17-2. TDD and Incremental Implementation Skills

> **Metadata**
>
> - **Date**: 2026-04-13
> - **Author**: Claude Sonnet 4.6
> - **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
> - **Epic Short ID**: E17
> - **Target Branch**: `feature/e17-2`
> - **Review Coverage Target**: 1

---

## Objective

Create the `tdd` and `incremental-implementation` execution skills — the first two Phase 2 deliverables — along with their paired `.claude/commands/` entry points. These skills establish the machine-enforceable TDD gate and vertical-slice decomposition model that all subsequent E17 execution skills depend on.

## Problem Statement

The RED→GREEN→REFACTOR invariant is documented in `development-workflow.md` and `lifecycle-map.md` but has no executable skill that makes it a gated loop an agent follows step-by-step. Without a `tdd` skill, agents can write production code before recording a failing test, bypassing the `slice-start` gate silently. Without an `incremental-implementation` skill, agents decompose work into horizontal domain layers instead of vertical feature slices, deferring integration risk to merge time. Both skills are prerequisites for any E17 Phase 2 execution skill that touches implementation work.

## Constraints

- No code changes (`apps/`, `packages/`). All deliverables are skill files, command files, and docs.
- Each skill must conform to `SKILL_ANATOMY.template.md`: 8-field frontmatter, 10 required sections.
- Each skill's rendered line count must stay within its declared `context_budget`.
- MCP tool names must match the current typed API surface — no pseudo-tool names.
- Command files are ~15 lines each: name the active skill, declare the Makefile entry point, set execution context.
- Both skills declare `tdd_gate: true`.

## Workflow Principles

- Paired delivery: each skill is committed in the same slice as its `.claude/commands/` entry point.
- Skill is the agent-read document; `make slice-start` is the existing Makefile entry point for the `tdd` skill.
- `plan_cursor` from `agent-orchestrator-mcp` is the slice-advance tracker for `incremental-implementation`; document its `require_clean_slice` guard explicitly.

## Terminology

- **TDD gate**: the `make slice-start TEST_CMD="..."` call that records `test_result(passed=false)` in MCP before any implementation edit. The gate is machine-checkable; `handoff_close_check` requires at least one `test_result` evidence entry.
- **Vertical slice**: one end-to-end user path (DB → service → API → UI) delivered and verified as a unit before the next slice begins.
- **Execution skill**: a SKILL.md with `mode: execution` that manages a gated loop with convergence criteria and MCP state writes.

## Current State Analysis

- `.claude/skills/tdd/SKILL.md` and `.claude/skills/incremental-implementation/SKILL.md` now exist and both ship as execution skills with `tdd_gate: true`.
- `.claude/commands/tdd.md` and `.claude/commands/incremental-implementation.md` now exist as the paired slash-command entry points.
- `docs/agentic/instructions.md` now routes both implementation-start and slice-decomposition work to the new skills.
- `mk/handoff.mk` needed a live-surface fix during implementation: `slice-start` now refreshes task output via positional `task "<task-ref>"` instead of the stale `--task-ref` flag.
- `scripts/agentic/slice_commit.py` needed two live-surface fixes during implementation: the default decision id now uses the canonical `cdx_slice_complete_<work_ref>_<slug>` prefix, and slug generation now uses underscores so automated `make slice-commit` writes satisfy the enforced decision-id grammar.
- `plan_cursor` (agent-orchestrator-mcp) is now surfaced explicitly in the `incremental-implementation` skill with its `require_clean_slice` guard documented.

## Target Outcome

A `tdd` execution skill that an agent loads when starting any implementation slice. The skill walks the agent through: choose test → run failing → `make slice-start` → implement → run passing → record `test_result(passed=true)`. A `incremental-implementation` execution skill that enforces vertical-slice decomposition: identify the smallest end-to-end user path, write the failing test first, scaffold minimal signature, implement, keep diff bounded, commit via `make slice-commit`. Both skills have paired slash commands so the agent loads the right skill by typing `/tdd` or `/incremental-implementation` rather than searching prose triggers.

## Context Loading

- Template: `docs/agentic/templates/SKILL_ANATOMY.template.md`
- Epic: `docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md` (Phase 2, `tdd` and `incremental-implementation` entries)
- Lifecycle: `docs/agentic/lifecycle-map.md` (stages I2–I4, `plan_cursor` Quick Reference)
- Workflow: `docs/agentic/rules/development-workflow.md` (Slice Checklist, Scaffolding First, Gradual Layering)
- Exemplar skill: `.claude/skills/review/SKILL.md` (retrofitted execution skill for reference)
- Handoff/MCP state: E17 was archived at merge of E17-1; use `switch_task(task_ref="E17-2", objective="...")` at implementation start to create the E17-2 active task
- External docs via `ctx7` only if: FastMCP tool registration patterns needed for `plan_cursor` schema

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|----------|-------|------------------|-----------------|----------------------|--------------|
| Agent startup injection (`CLAUDE.md`) | repo-wide | Key Triggers section references `investigate` skill | No change — trigger text for `tdd`/`incremental-implementation` added to `docs/agentic/instructions.md` Additional Routing only | No | `grep 'tdd\|incremental-implementation' docs/agentic/instructions.md` |

## Proposed Solution

Two slices, one per skill pair. Each slice: create the `SKILL.md`, create the paired `.claude/commands/<skill>.md`, add routing hint to `instructions.md` Additional Routing table. Skill structure follows the anatomy template. MCP tool references use the typed discriminated union forms.

## Files and Surfaces to Change

| Surface | File | Change |
|---------|------|--------|
| Skill | `.claude/skills/tdd/SKILL.md` | New execution skill (~90 lines) |
| Command | `.claude/commands/tdd.md` | New slash command entry point (~15 lines) |
| Skill | `.claude/skills/incremental-implementation/SKILL.md` | New execution skill (~100 lines) |
| Command | `.claude/commands/incremental-implementation.md` | New slash command entry point (~15 lines) |
| Routing | `docs/agentic/instructions.md` | Add `tdd` and `incremental-implementation` rows to Additional Routing table |
| Workflow helper | `mk/handoff.mk` | Fix `slice-start` task refresh for the live CLI surface |
| Workflow helper | `scripts/agentic/slice_commit.py` | Fix canonical slice-decision id generation for `make slice-commit` |

## Related Files

| File | Note |
|------|------|
| `mk/handoff.mk` | `slice-start` and `slice-commit` targets — the Makefile entry points these skills document |
| `docs/agentic/lifecycle-map.md` | I2–I4 stages that the `tdd` skill maps to |
| `docs/agentic/rules/development-workflow.md` | Slice Checklist steps 2–5 that `tdd` extracts into a gated skill |
| `.claude/skills/review/SKILL.md` | Retrofitted execution skill — use as structural reference |

## Verification Strategy

- Deterministic checks:
  - `grep -c 'tdd_gate: true' .claude/skills/tdd/SKILL.md` → 1
  - `grep -c 'tdd_gate: true' .claude/skills/incremental-implementation/SKILL.md` → 1
  - `grep -c 'mode: execution' .claude/skills/tdd/SKILL.md .claude/skills/incremental-implementation/SKILL.md` → 2
  - `grep -c 'record_event\|plan_cursor' .claude/skills/incremental-implementation/SKILL.md` → ≥2
  - `wc -l .claude/skills/tdd/SKILL.md` → ≤110 (budget 90 + frontmatter overhead)
  - `wc -l .claude/skills/incremental-implementation/SKILL.md` → ≤120
  - Each command file: `wc -l .claude/commands/tdd.md .claude/commands/incremental-implementation.md` → ≤20 each
  - `make lint-task-plans` → passes
- Manual verification:
  - `tdd` skill has all 10 required anatomy sections
  - `incremental-implementation` skill documents `plan_cursor` `require_clean_slice` guard with explanation
  - Command files name the skill, declare the Makefile entry point (`make slice-start` for `tdd`), and set execution context
  - No stale pseudo-tool names in either skill

## Slice Delivery

### Slice 1: `tdd` Skill and Command File

**Goal**: Create the `tdd` execution skill and its `/tdd` slash command, establishing the machine-enforceable RED→GREEN→REFACTOR gate.

Changes:

- Create `.claude/skills/tdd/SKILL.md`:
  - Frontmatter: `name: tdd`, `mode: execution`, `context_budget: 90`, `tdd_gate: true`, `makefile_target: slice-start`, `mcp_tools: [record_event, get_verified_tests, search_handoff]`
  - Trigger: agent starting any implementation slice; any time `make slice-start` is the next step
  - Goal: failing test recorded in MCP before the first production-code edit
  - Core process (gated loop):
    1. Identify the target behavior to test (search prior slices via `search_handoff` if unclear)
    2. Write the failing test
    3. Run it — confirm it fails for the intended reason (not a syntax error)
    4. Run `make slice-start TEST_CMD="<test command>"` — records `test_result(passed=false)`
    5. Implement minimal production code to pass
    6. Run tests — confirm green
    7. Record `record_event(event_kind="test_result", passed=true, command=..., result=...)`
    8. Refactor while tests stay green
    9. Commit via `make slice-commit`
  - Convergence: `test_result(passed=true)` recorded at current HEAD SHA before any commit
  - Common rationalizations: "I'll add the test after I know it works"; "this is just a config change, no test needed"; "the test is obvious, I'll skip slice-start"
  - Red flags: production file edited before `make slice-start` ran; test was written after implementation; `test_result(passed=false)` not in MCP for current slice
- Create `.claude/commands/tdd.md`:
  - Declares active skill: `tdd`
  - Makefile entry point: `make slice-start TEST_CMD="<command>"`
  - Execution context: run at the start of every implementation slice before editing any production file

Proof:

- `grep -c 'tdd_gate: true' .claude/skills/tdd/SKILL.md` → 1
- `grep 'makefile_target: slice-start' .claude/skills/tdd/SKILL.md` → present
- `wc -l .claude/skills/tdd/SKILL.md` → ≤110
- All 10 anatomy sections present

### Slice 2: `incremental-implementation` Skill and Command File

**Goal**: Create the `incremental-implementation` execution skill and its `/incremental-implementation` slash command, enforcing vertical-slice decomposition with `plan_cursor` tracking.

Changes:

- Create `.claude/skills/incremental-implementation/SKILL.md`:
  - Frontmatter: `name: incremental-implementation`, `mode: execution`, `context_budget: 100`, `tdd_gate: true`, `makefile_target: slice-commit`, `mcp_tools: [record_event, search_handoff, generate_current_task_md]`; plus `plan_cursor` (agent-orchestrator-mcp) noted in MCP tools description
  - Trigger: starting any feature implementation slice; when decomposing a task plan into implementation increments
  - Goal: each slice delivers one complete end-to-end user path, independently testable, with a failing test recorded before any edit
  - Core process (gated loop):
    1. Load the task plan — identify the next uncompleted slice
    2. Advance `plan_cursor` to this slice: `plan_cursor(operation="upsert", task_ref=..., plan_item_id="<slice-heading>", require_clean_slice=true)` — gate refuses if the previous slice has open findings
    3. Identify the smallest end-to-end user path for this slice (e.g. one DB column + one service method + one API field + one UI label)
    4. Write the failing test for that path → run `make slice-start TEST_CMD="..."`
    5. Scaffold minimal signatures needed (no implementation bodies yet)
    6. Implement the minimal production code to pass the test
    7. Verify tests pass
    8. Bound the diff: if changes span more than one user path, split the slice
    9. Commit via `make slice-commit MSG="..."`
  - Convergence: `close_slice` recorded; `plan_cursor` advanced to current slice; diff bounded to one user path
  - Common rationalizations: "I'll implement the whole backend first, then wire the frontend"; "these are just types, no test needed yet"; "the slice is almost done, I'll add the test at the end"
  - Red flags: diff touches multiple independent user paths; failing test not recorded before implementation edits; `plan_cursor(require_clean_slice=true)` rejected because previous slice has open findings
- Create `.claude/commands/incremental-implementation.md`:
  - Declares active skill: `incremental-implementation`
  - Makefile entry point: `make slice-commit MSG="..."` (close) / `make slice-start TEST_CMD="..."` (open)
  - Execution context: use when starting any feature implementation; replaces ad-hoc horizontal layering
- Add routing rows to `docs/agentic/instructions.md` Additional Routing table:
  - `Starting an implementation slice` → `tdd` skill + `make slice-start`
  - `Decomposing feature work into slices` → `incremental-implementation` skill

Proof:

- `grep -c 'tdd_gate: true' .claude/skills/incremental-implementation/SKILL.md` → 1
- `grep 'plan_cursor' .claude/skills/incremental-implementation/SKILL.md` → ≥2 lines (usage + `require_clean_slice` explanation)
- `wc -l .claude/skills/incremental-implementation/SKILL.md` → ≤120
- All 10 anatomy sections present
- `grep 'tdd\|incremental' docs/agentic/instructions.md` → routing rows present

---

## Consolidated Checklist

### Task Status

- [x] Implementation complete on `feature/e17-2`
- [x] Task-plan checklist synced to delivered files and helper fixes
- [x] Handoff decision `#1639` verified against commit `6df337d058c75ebb2a66f8cf47b9f7c91656556b`
- [x] Handoff decision `#1643` recorded as the corrected provenance row for the incremental-implementation slice commit `813de5394437b316c14913e7c1dae8fb9481f342`
- [x] Handoff decision `#1644` recorded as the corrected provenance row for the helper-fix commit `11b67e8d1224c723cda5b18f9306b26c2a09f3fd`
- [x] Handoff decision `#1645` verified against task-plan sync commit `da168e4c428039283b8c9ad27042640f8bf7891a`
- [ ] Review/gate sequence still pending before merge
- [ ] Task archival still pending after review and merge

## Context and Ownership

- [x] Loaded `SKILL_ANATOMY.template.md` and reviewed Phase 2 epic entries for `tdd` and `incremental-implementation`
- [x] Confirmed no contract or boundary impact beyond `instructions.md` Additional Routing
- [x] Reviewed `.claude/skills/review/SKILL.md` as structural reference for execution skills

### Checklist for Slice 1: `tdd` Skill and Command File

- [x] Create `.claude/skills/tdd/SKILL.md` with all 8 frontmatter fields
- [x] Verify `mode: execution`, `tdd_gate: true`, `makefile_target: slice-start`
- [x] Include all 10 anatomy sections
- [x] Core process references `make slice-start` as the gate mechanism
- [x] Common rationalizations section names the 3 most common skip excuses
- [x] Create `.claude/commands/tdd.md` (≤20 lines)
- [x] `wc -l .claude/skills/tdd/SKILL.md` ≤ 110
- [x] Record handoff decision with changed files

### Checklist for Slice 2: `incremental-implementation` Skill and Command File

- [x] Create `.claude/skills/incremental-implementation/SKILL.md` with all 8 frontmatter fields
- [x] Verify `mode: execution`, `tdd_gate: true`
- [x] `plan_cursor` with `require_clean_slice` documented in core process with explanation of the guard
- [x] Horizontal-decomposition anti-pattern named explicitly in Common Rationalizations
- [x] Create `.claude/commands/incremental-implementation.md` (≤20 lines)
- [x] Add routing rows to `instructions.md` Additional Routing
- [x] `wc -l .claude/skills/incremental-implementation/SKILL.md` ≤ 120
- [x] Record handoff decision with changed files

## Review Readiness

- [x] Both skills pass anatomy checklist (all 8 frontmatter fields, all 10 sections)
- [x] No stale pseudo-tool names in either skill
- [x] Command files declare skill name, Makefile entry point, and execution context
- [x] `make lint-task-plans` passes

## Success Criteria

- [x] `.claude/skills/tdd/SKILL.md` exists, `mode: execution`, `tdd_gate: true`, within budget
- [x] `.claude/skills/incremental-implementation/SKILL.md` exists, documents `plan_cursor` `require_clean_slice` guard
- [x] `.claude/commands/tdd.md` and `.claude/commands/incremental-implementation.md` exist
- [x] `docs/agentic/instructions.md` Additional Routing references both skills
- [x] E17 Phase 2 first-delivery criteria satisfied: TDD gate skill and vertical-slice skill both shipped
