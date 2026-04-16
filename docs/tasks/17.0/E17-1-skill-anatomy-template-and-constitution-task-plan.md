# E17-1. Skill Anatomy Template and Constitution

> **Metadata**
>
> - **Date**: 2026-04-13
> - **Author**: Claude Opus 4.6
> - **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
> - **Epic Short ID**: E17
> - **Target Branch**: `feature/e17-1`
> - **Review Coverage Target**: 2

---

## Objective

Establish the skill anatomy standard and the constitution document that all subsequent E17 skills will reference. When this task is complete, a SKILL_ANATOMY template defines the canonical structure, `constitution.md` is the single authoritative source for `[sr-NNN]` and `[rg-NNN]` rules, and three existing skills demonstrate the retrofitted anatomy.

## Problem Statement

The 11 existing skills in `.claude/skills/` vary in structure: `commit2git` has partial frontmatter (name, description) but no mode or context budget; `review` and `investigate` have no frontmatter at all. None declare context budgets, MCP tools, or Makefile targets. The `[sr-NNN]` and `[rg-NNN]` rules are duplicated in both `CLAUDE.md` and `docs/agentic/instructions.md` — there is no single canonical source, so rule drift across the two files is undetectable. Phase 2 of E17 (core workflow skills) cannot proceed without a template to build against and a constitution to validate against.

## Constraints

- No code changes (`apps/`, `packages/`). All deliverables are documentation and skill files.
- `constitution.md` must be the single authoritative source for rule *authoring*. `CLAUDE.md` retains full inline rules (it is the injected startup surface and cannot depend on an external load step), but is explicitly marked as a derived copy. `instructions.md` replaces its copy with a path reference. This reduces from three independent copies to one canonical source, one derived injection surface, and one reference pointer.
- Skill retrofit must preserve existing *functional intent* (triggers, process goals, recovery paths) but must normalize stale pseudo-tool names to the current typed MCP API surface. Preserving non-executable guidance defeats the epic's stated goal.
- Template must be agent-agnostic (no model-specific assumptions).
- No new Makefile targets in this task (`make check-skills` is Phase 3).

## Workflow Principles

- Canonical source with derived injection surface. `constitution.md` is the authoring source; `CLAUDE.md` is a derived copy that must stay in sync. `instructions.md` references by path. When editing rules, edit `constitution.md` first, then sync `CLAUDE.md`.
- Same-slice consistency: when the constitution is created, both `CLAUDE.md` (mark as derived) and `instructions.md` (replace with reference) must be updated in the same slice.
- Normalize on retrofit. When restructuring a skill into the anatomy, update stale tool names to the current MCP API surface — don't preserve non-executable call signatures.

## Terminology

- **Skill anatomy**: The standardized SKILL.md structure: frontmatter, overview, triggers, core process, common rationalizations, red flags, verification/convergence, see-also.
- **Constitution**: `docs/agentic/constitution.md` — a machine-loadable document formalizing `[sr-NNN]` and `[rg-NNN]` rules as checkable constraints.
- **Retrofit**: Adding required frontmatter and reorganizing an existing skill into the anatomy sections without changing its functional behavior.

## Current State Analysis

### What currently works

- 11 skills exist in `.claude/skills/`, each in its own directory with a `SKILL.md` file.
- All 11 have convergence criteria sections.
- `commit2git` has partial YAML frontmatter (`name`, `description`, `disable-model-invocation`).
- `review` (224 lines) and `investigate` (191 lines) are well-structured with phased processes, recovery sections, and MCP tool usage.
- 10 `[sr-NNN]` rules (sr-001 through sr-010) and 15 `[rg-NNN]` rules (rg-001 through rg-010, rg-013 through rg-017) exist in both `CLAUDE.md` and `instructions.md`.

### What is broken or drifting

- No skill has all required anatomy fields: `mode`, `context_budget`, `makefile_target`, `mcp_tools` are absent from every skill.
- `review` and `investigate` have no frontmatter at all.
- Rules are duplicated across `CLAUDE.md` and `instructions.md` with no canonical source — edits to one file can silently diverge from the other.
- No template exists to guide new skill creation — Phase 2 skill authors would have to reverse-engineer the pattern from existing skills.

## Target Outcome

A `SKILL_ANATOMY.template.md` in `docs/agentic/templates/` that defines the canonical section structure and frontmatter schema for all skills. A `constitution.md` in `docs/agentic/` that is the canonical authoring source for all 25 `[sr/rg-NNN]` rules. Three existing skills (`commit2git`, `review`, `investigate`) retrofitted to the new anatomy with stale tool names normalized to the current MCP API. `CLAUDE.md` retains full inline rules but is marked as derived from `constitution.md`; `instructions.md` replaces inline rules with a path reference.

## Context Loading

- Rules: `docs/agentic/rules/planning-pipeline.md` (pipeline stage gates)
- Rules: `docs/agentic/rules/development-workflow.md` (slice checklist)
- Epic: `docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md` (Phase 1 deliverables and exit criteria)
- Assessment: `docs/assessments/agent-skills-vs-spec-kit-evaluation.md` (anatomy patterns)
- Handoff/MCP state: task ref `E17`, findings `E17-PLAN-*` (all fixed)
- External docs via `ctx7` only if: `addyosmani/agent-skills` patterns need verification against upstream examples

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|----------|-------|------------------|-----------------|----------------------|--------------|
| Agent startup injection (`CLAUDE.md`) | repo-wide | `CLAUDE.md` Short Rules + Cross-Branch Regression Guards sections | Mark inline rules as derived from `constitution.md` (retain full text for injection visibility); add provenance header | No — CLAUDE.md retains full rules; only the authoring source changes | Provenance header present; rule text matches `constitution.md` |
| Agent routing doc (`instructions.md`) | repo-wide | `instructions.md` Short Rules + Regression Guards sections | Replace inline rule text with path reference to `constitution.md` | No — instructions.md is loaded on demand, not injected | Grep confirms full rule text replaced with path reference |

## Proposed Solution

Three slices in dependency order:

1. **Skill anatomy template** — create the template, establishing the frontmatter schema and section structure that the retrofit slice and all Phase 2 skills will follow.
2. **Constitution extraction** — create `constitution.md` as the canonical authoring source for all 25 rules; mark `CLAUDE.md` inline rules as derived from constitution.md; replace `instructions.md` inline rules with a path reference.
3. **Skill retrofit** — retrofit `commit2git`, `review`, and `investigate` to the new anatomy, proving the template works against skills of varying complexity and structure.

## Files and Surfaces to Change

| Surface | File | Change |
|---------|------|--------|
| Template | `docs/agentic/templates/SKILL_ANATOMY.template.md` | New file — canonical skill structure |
| Constitution | `docs/agentic/constitution.md` | New file — single source for 25 rules |
| Agent startup | `CLAUDE.md` | Mark inline rules as derived from `constitution.md`; add provenance header |
| Agent routing | `docs/agentic/instructions.md` | Replace inline rule text with path reference to `constitution.md` |
| Skill | `.claude/skills/commit2git/SKILL.md` | Add frontmatter, reorganize to anatomy |
| Skill | `.claude/skills/review/SKILL.md` | Add frontmatter, reorganize to anatomy, normalize stale tool names |
| Skill | `.claude/skills/investigate/SKILL.md` | Add frontmatter, reorganize to anatomy, normalize stale tool names |

## Related Files

| File | Note |
|------|------|
| `docs/assessments/agent-skills-vs-spec-kit-evaluation.md` | Source of anatomy patterns and hybrid extraction recommendation |
| `.claude/skills/*/SKILL.md` (remaining 8) | Phase 3 retrofit candidates — not touched in this task |
| `docs/agentic/rules/planning-review-guide.md` | Will be referenced by the `planning-review` skill in Phase 2 |
| `docs/agentic/rules/branch-review-guide.md` | Will be referenced by the `branch-review` skill in Phase 2 |

## Verification Strategy

- Deterministic checks:
  - `grep -c '\[sr-[0-9]*\]' docs/agentic/constitution.md` returns 10
  - `grep -c '\[rg-[0-9]*\]' docs/agentic/constitution.md` returns 15
  - `grep 'constitution.md' CLAUDE.md` returns provenance header lines
  - `grep 'constitution.md' docs/agentic/instructions.md` returns path reference
  - `grep -c 'record_review_finding\|record_review_run\|list_review_runs\|batch_record_review_findings\|record_decision\|report_blocker\|update_review_finding' .claude/skills/review/SKILL.md .claude/skills/investigate/SKILL.md` returns 0
  - `make lint-task-plans` passes (no pasted findings)
- Manual verification:
  - SKILL_ANATOMY template has all required sections: frontmatter, overview, triggers, core process, rationalizations, red flags, convergence, see-also
  - Each retrofitted skill has frontmatter with: `name`, `description`, `mode`, `context_budget`, `makefile_target`, `mcp_tools`
  - `CLAUDE.md` retains full inline rules with provenance header pointing to `constitution.md`
  - `instructions.md` replaces inline rule text with path reference to `constitution.md`
  - Rule text in `CLAUDE.md` matches `constitution.md` (manual diff)
  - No broken internal links in modified files

## Slice Delivery

### Slice 1: Skill Anatomy Template

**Goal**: Create the canonical SKILL.md template that defines the frontmatter schema and section structure for all current and future skills.

Changes:

- Create `docs/agentic/templates/SKILL_ANATOMY.template.md` with:
  - YAML frontmatter schema: `name` (string), `description` (string), `mode` (`advisory`|`execution`), `context_budget` (integer, line count target), `makefile_target` (string, optional), `mcp_tools` (list of strings, optional), `tdd_gate` (boolean, optional — `true` for execution skills that enforce RED→GREEN→REFACTOR; defaults to `true` for `mode: execution`, `false` for `mode: advisory`), `disable-model-invocation` (boolean, optional)
  - Required sections: Overview, Trigger, Goal, Canonical Policy, Core Process, Common Rationalizations, Red Flags, Recovery, Convergence Criteria, See Also
  - Inline guidance for each section explaining its purpose and content expectations
  - Distinction between advisory and execution skill templates (execution skills require convergence gates and MCP state writes)

Proof:

- File exists at `docs/agentic/templates/SKILL_ANATOMY.template.md`
- Template contains all 7 frontmatter fields and all 10 required sections
- Template is referenced in the templates directory listing

### Slice 2: Constitution Extraction and Canonical Source Establishment

**Goal**: Create `constitution.md` as the canonical authoring source for all `[sr-NNN]` and `[rg-NNN]` rules; mark `CLAUDE.md` as a derived injection surface; replace `instructions.md` inline rules with a path reference.

**Design rationale**: `CLAUDE.md` is injected into every agent conversation automatically — it is the only file guaranteed to be in context. Removing rule text from it would make rules invisible to agents unless a separate loader step exists, and no such loader is scoped in Phase 1. Therefore `CLAUDE.md` retains full inline rules but is explicitly marked as derived from `constitution.md`. `instructions.md` is loaded on demand (not injected), so it can safely reference `constitution.md` by path without losing visibility. This reduces the authoring surface from two independent copies to one canonical source (`constitution.md`) + one derived copy (`CLAUDE.md`) + one pointer (`instructions.md`). Phase 3 can add a `make check-constitution-sync` target to detect drift between the canonical and derived surfaces.

Changes:

- Create `docs/agentic/constitution.md` with:
  - All 10 `[sr-NNN]` rules (sr-001 through sr-010) extracted from `instructions.md`, structured as numbered checkable constraints with rule ID, scoring, and full text
  - All 15 `[rg-NNN]` rules (rg-001 through rg-010, rg-013 through rg-017) extracted similarly
  - Organized into two sections: Short Rules and Cross-Branch Regression Guards
  - Each rule retains its stable ID, `helpful`/`harmful` scoring, and full constraint text
- Update `CLAUDE.md`:
  - Add a provenance header to the Short Rules and Cross-Branch Regression Guards sections: `> Canonical source: [docs/agentic/constitution.md](docs/agentic/constitution.md). Edit rules there; sync here.`
  - Retain full inline rule text (required for injection visibility)
  - Do NOT add per-rule summaries or secondary index — the full text IS the injection surface
- Update `docs/agentic/instructions.md`:
  - Replace the Short Rules and Cross-Branch Regression Guards section bodies with a path reference to `constitution.md`
  - Remove full inline rule text (instructions.md is loaded on demand, not injected)

Proof:

- `grep -c '\[sr-[0-9]*\]' docs/agentic/constitution.md` >= 10
- `grep -c '\[rg-[0-9]*\]' docs/agentic/constitution.md` >= 15
- `grep 'constitution.md' CLAUDE.md` returns provenance header lines
- `grep 'constitution.md' docs/agentic/instructions.md` returns path reference
- Full rule text in `CLAUDE.md` matches `constitution.md` content (manual diff or future `make check-constitution-sync`)
- `instructions.md` no longer contains full `::` definition bodies — only the path reference

### Slice 3: Existing Skill Retrofit

**Goal**: Retrofit `commit2git`, `review`, and `investigate` skills to the new anatomy template, proving the template works for skills of varying structure and complexity. Normalize stale pseudo-tool names to the current typed MCP API surface.

**Design rationale**: The `review` skill currently references `list_review_runs(...)`, `record_review_run(...)`, `record_decision(...)`, and `record_review_finding(...)` — pseudo-tool names that do not match the actual MCP API. The real tools are `review_runs(review={operation: "list"|"record", ...})`, `record_event(event={event_kind: "decision", ...})`, and `review_findings(review={operation: "record"|"batch_record", ...})`. Similarly, `investigate` references `report_blocker(...)` and `update_review_finding(...)` — the real tools are `record_event(event={event_kind: "blocker", ...})` and `review_findings(review={operation: "update", ...})`. Preserving these stale names would produce skills that cite non-existent tools, violating [rg-006] (documented commands must run as written). The retrofit normalizes them.

Changes:

- `.claude/skills/commit2git/SKILL.md` (currently 182 lines, has partial frontmatter):
  - Extend frontmatter: add `mode: advisory`, `context_budget: 200`, `mcp_tools: []` (no MCP tools used), `makefile_target: null`
  - Add formal "Common Rationalizations" section (e.g., "I'll just commit everything in one go")
  - Add formal "Red Flags" section (e.g., staged diff tells more than one story)
  - Add "See Also" section linking to related skills (`subfeature-committer`)
- `.claude/skills/review/SKILL.md` (currently 224 lines, no frontmatter):
  - Add frontmatter: `name: review`, `description: ...`, `mode: execution`, `context_budget: 250`, `mcp_tools: [review_findings, review_runs, record_event, get_handoff_state, generate_current_task_md, get_latest_slice_review_packet, handoff_close_check, search_handoff]`, `makefile_target: review-run`
  - Normalize stale tool references: `record_review_finding(...)` / `batch_record_review_findings(...)` → `review_findings(review={operation: "record"|"batch_record", ...})`; `list_review_runs(...)` / `record_review_run(...)` → `review_runs(review={operation: "list"|"record", ...})`; `record_decision(...)` → `record_event(event={event_kind: "decision", ...})`
  - Add formal "Common Rationalizations" section
  - Add formal "Red Flags" section
  - Add "See Also" section linking to review guides
- `.claude/skills/investigate/SKILL.md` (currently 191 lines, no frontmatter):
  - Add frontmatter: `name: investigate`, `description: ...`, `mode: execution`, `context_budget: 200`, `mcp_tools: [review_findings, record_event, search_handoff, get_handoff_state, generate_current_task_md]`, `makefile_target: null`
  - Normalize stale tool references: `report_blocker(...)` → `record_event(event={event_kind: "blocker", ...})`; `update_review_finding(...)` → `review_findings(review={operation: "update", ...})`; `record_decision(...)` → `record_event(event={event_kind: "decision", ...})`
  - Promote inline "Red flags" (currently in Phase 3) to a formal top-level "Red Flags" section
  - Add formal "Common Rationalizations" section
  - Add "See Also" section linking to review guide bug-finding heuristics

Proof:

- Each of the 3 retrofitted skills has YAML frontmatter with all required fields: `name`, `description`, `mode`, `context_budget`
- `commit2git` has `mode: advisory`; `review` and `investigate` have `mode: execution`
- Each skill has "Common Rationalizations", "Red Flags", "Convergence Criteria", and "See Also" sections
- Existing functional intent (triggers, process goals, recovery paths) is preserved
- No stale pseudo-tool names remain: `grep -c 'record_review_finding\|record_review_run\|list_review_runs\|batch_record_review_findings\|record_decision\|report_blocker\|update_review_finding' .claude/skills/{review,investigate}/SKILL.md` returns 0

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the epic (E17) Phase 1 deliverables and exit criteria.
- [x] Loaded the `agent-skills-vs-spec-kit-evaluation.md` assessment for anatomy patterns.
- [x] Confirmed no contract or boundary impact beyond the agent startup injection surface (`CLAUDE.md`, `instructions.md`).

### Checklist for Slice 1: Skill Anatomy Template

- [x] Create `docs/agentic/templates/SKILL_ANATOMY.template.md`
- [x] Include all 7 frontmatter fields with types and descriptions (including `tdd_gate` added in planning review pass)
- [x] Include all 10 required sections with inline guidance
- [x] Document `advisory` vs `execution` mode distinction with examples (Core Process section)
- [x] Verify template is discoverable in the templates directory

### Checklist for Slice 2: Constitution Extraction

- [x] Create `docs/agentic/constitution.md` with all 10 `[sr-NNN]` rules
- [x] Include all 15 `[rg-NNN]` rules in `constitution.md`
- [x] Verify rule count: `grep -c '\[sr-' constitution.md` == 10, `grep -c '\[rg-' constitution.md` == 15
- [x] Add provenance header to `CLAUDE.md` Short Rules and Regression Guards sections pointing to `constitution.md`
- [x] Retain full inline rule text in `CLAUDE.md` (required for injection visibility)
- [x] Replace `instructions.md` inline rule text with path reference to `constitution.md`
- [ ] Verify `CLAUDE.md` rule text matches `constitution.md` content (manual diff; pending `make check-constitution-sync` Phase 3)
- [ ] Verify no broken internal links in `CLAUDE.md` or `instructions.md` (pending `make check-skills` Phase 3)

### Checklist for Slice 3: Skill Retrofit

- [x] Retrofit `commit2git`: extend frontmatter, add Rationalizations/Red Flags/See Also
- [x] Retrofit `review`: add full frontmatter, normalize stale tool names, add Rationalizations/Red Flags/See Also
- [x] Retrofit `investigate`: add full frontmatter, normalize stale tool names, promote Red Flags, add Rationalizations/See Also
- [x] Verify each skill has: `name`, `description`, `mode`, `context_budget` in frontmatter
- [x] Verify no stale pseudo-tool names remain in retrofitted skills (`grep` returns 0)
- [x] Verify functional intent is preserved (triggers, process goals, recovery paths unchanged)
- [x] Record handoff decision with changed files and verification evidence

## Review Readiness

- [x] Constitution contains all 25 rules with stable IDs preserved.
- [x] `CLAUDE.md` retains full inline rules with provenance header; `instructions.md` references `constitution.md` by path.
- [x] Three retrofitted skills pass the anatomy checklist with current MCP tool names.
- [x] Handoff decision records the change, verification, and any open threads.

## Success Criteria

- [x] `docs/agentic/templates/SKILL_ANATOMY.template.md` exists with full frontmatter schema and section structure
- [x] `docs/agentic/constitution.md` exists with all 25 `[sr/rg-NNN]` rules as the canonical authoring source
- [x] `CLAUDE.md` retains full rules with provenance header; `instructions.md` references by path — authoring source is unambiguous
- [x] 3 existing skills retrofitted to new anatomy with required frontmatter fields and current MCP tool names
- [x] E17 Phase 1 exit criteria (from epic) are satisfied
