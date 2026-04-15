# E17-6. Phase 3 Retrofit — Skill Anatomy Completion, Routing Redirect, and Planning Gate Wiring

- **Date**: 2026-04-14
- **Author**: Claude Sonnet 4.6
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-6`
- **Review Coverage Target**: 2

---

## Objective

Retrofit the 8 pre-E17 legacy skills to the anatomy template, add a headless `make check-skills` validator that enforces anatomy compliance in CI, redirect `CLAUDE.md` and `instructions.md` triggers to skills as primary entry points (removing inline prose that duplicates skill content), and wire `plan-analyze` as a required precheck before `make plan-review` can proceed. When this task is complete, every skill in `.claude/skills/` passes `make check-skills`, agents are routed to skills rather than bulk guide loading for every major workflow trigger, and the planning pipeline has a machine-enforced pre-review analysis gate.

## Problem Statement

Phase 1 and Phase 2 of E17 created anatomy-compliant skills for the eight core workflows (tdd, incremental-implementation, scope, branch-lifecycle, handoff-lifecycle, branch-review, planning-review, plan-analyze) and retrofitted three early legacy skills (commit2git, review, investigate). Eight pre-E17 skills were left with either no frontmatter or partial frontmatter and missing anatomy sections:

- **No frontmatter**: refactor, security-audit, document-sync
- **Partial frontmatter** (missing mode, tdd_gate, context_budget, makefile_target, mcp_tools): daemon-lifecycle, worktree-orchestrator, worktree-worker, rescue-lane, subfeature-committer

Three structural gaps remain from the Phase 3 scope:

1. **No anatomy enforcement**: There is no `make check-skills` target. Whether a skill is anatomy-compliant is checked manually. Any new skill can ship without required frontmatter.
2. **Routing is still guide-first**: `CLAUDE.md` Key Triggers and `instructions.md` role routing still point agents at `branch-review-guide.md` and `planning-review-guide.md` as primary execution surfaces. Agents load 250+ lines of guide when the 150-line skills cover the executable path. The context bloat problem the skills were built to solve remains in the routing surface.
3. **No planning gate**: `make plan-review` does not verify that a `plan-analyze` run has been recorded for the target document. The skill prompts agents to run plan-analyze first, but nothing enforces it.

## Constraints

- `make check-skills` must be headless and CI-safe (no agent, no MCP, no network). Exit 0 on all-pass, non-zero on any failure.
- The wiring check in `make check-skills` uses a hardcoded known-tools registry (derived from `docs/agentic/maps/mcp-tool-routing.yaml`) rather than live MCP introspection — no runtime dependency on a running MCP server.
- Skill body edits (adding rationalizations, red flags, convergence criteria) must preserve existing process content. The retrofit adds anatomy sections; it does not rewrite the skill's core process.
- CLAUDE.md and instructions.md edits remove prose that duplicates skill content. Prose that provides rationale, edge cases, or context not covered by the skill is kept.
- The planning exit gate warns rather than hard-blocks on the first rollout. Hard enforcement (exit non-zero) is opt-in via `PLAN_ANALYZE_REQUIRED=1`. See Constraints note on slice 4.
- No new MCP tools (per epic constraint). The plan-analyze precheck queries existing MCP review findings via the Python API.
- No changes to skill execution logic or MCP handoff protocol.

## Terminology

- **Anatomy retrofit**: adding the required frontmatter fields (name, description, mode, tdd_gate, context_budget, makefile_target, mcp_tools) and required section headers (Overview, Trigger, Core Process, Red Flags, Convergence Criteria) to a legacy skill that predates the anatomy template.
- **Known-tools registry**: a hardcoded list of MCP tool names derived from `docs/agentic/maps/mcp-tool-routing.yaml`, embedded in the `check-skills` script and used to validate `mcp_tools` frontmatter values without a live MCP connection.
- **Wiring check**: the `check-skills` validator step that confirms each skill's declared `makefile_target` appears as a target in the root `Makefile` (or `mk/` includes) and each `mcp_tools` entry appears in the known-tools registry.
- **Reference appendix**: a guide labelled explicitly as reference documentation (not the execution surface) once a discrete execution skill covers its executable path. Agents are directed to the skill; the guide is linked for rationale and edge cases.
- **Planning exit gate**: a precheck step in `make plan-review` that verifies at least one `plan-analyze` review run with recorded findings exists for the target document before the planning-review skill proceeds.

## Current State Analysis

**Skills directory**: `.claude/skills/` contains 19 skill directories. 11 are anatomy-compliant (full frontmatter + section headers). 8 are not:

| Skill | Frontmatter state | Missing |
|---|---|---|
| refactor | none | all fields + all sections |
| security-audit | none | all fields + all sections |
| document-sync | none | all fields + all sections |
| daemon-lifecycle | partial (name, description, argument-hint) | mode, tdd_gate, context_budget, makefile_target, mcp_tools; section headers |
| worktree-orchestrator | partial (name, description) | mode, tdd_gate, context_budget, makefile_target, mcp_tools; section headers |
| worktree-worker | partial (name, description) | mode, tdd_gate, context_budget, makefile_target, mcp_tools; section headers |
| rescue-lane | partial (name, description, disable-model-invocation) | mode, tdd_gate, context_budget, makefile_target, mcp_tools; section headers |
| subfeature-committer | partial (name, description, disable-model-invocation) | mode, tdd_gate, context_budget, makefile_target, mcp_tools; section headers |

**Makefile**: No `check-skills` target exists. `make check-all` runs lint, tests, hooks validation, task-plan lint, and worktree audit (E17-4), but not skill anatomy validation.

**CLAUDE.md**: The Key Triggers section points agents at `branch-review-guide.md` and `planning-review-guide.md` by file path. The Role Selection table does not reference skills. The Branch Review and Planning Review trigger descriptions do not mention the `/branch-review` or `/planning-review` slash commands or their skill files.

**instructions.md**: Role routing table references guides as primary execution surfaces. Planning pipeline routing (Assessment → Spec → Task Plan) does not reference the `plan-analyze` skill as a required pre-step.

**`mk/handoff.mk` plan-review target**: prints the skill name and expected output but performs no precheck. An agent can run `make plan-review` on a document with no prior `plan-analyze` findings.

## Target Outcome

- `make check-skills` exits 0 on a clean `.claude/skills/` run and non-zero with a named failure list on any anatomy violation. Integrated into `make check-all`.
- All 19 skills in `.claude/skills/` pass `make check-skills`.
- A cold-start agent reading `CLAUDE.md` Key Triggers is routed to a named skill and slash command — not to a guide file — for every major workflow trigger.
- `branch-review-guide.md` and `planning-review-guide.md` carry an explicit "Reference Appendix" label at the top.
- Running `make plan-review DOC=<path>` without a prior `plan-analyze` run (or with `PLAN_ANALYZE_REQUIRED=1`) prints a warning/block naming the missing analysis run.

## Context Loading

- Anatomy template: `docs/agentic/templates/SKILL_ANATOMY.template.md`
- MCP tool routing: `docs/agentic/maps/mcp-tool-routing.yaml`
- Existing anatomy-compliant skill for reference: `.claude/skills/branch-review/SKILL.md`
- Routing surfaces to change: `CLAUDE.md` § Key Triggers, `docs/agentic/instructions.md` § Role Routing
- Planning entry point: `mk/handoff.mk` plan-review and plan-analyze targets
- Planning pipeline rules: `docs/agentic/rules/planning-pipeline.md`
- Review guides: `docs/agentic/rules/branch-review-guide.md`, `docs/agentic/rules/planning-review-guide.md`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `make check-skills` | `scripts/check_skills.py` (new) | Does not exist | New headless validator; exit 0 on pass, non-zero on failure | n/a — new target | `make check-skills` exits 0 after retrofit |
| `make check-all` | root `Makefile` | Runs lint, tests, hooks, task-plan lint, worktree-audit | Add `check-skills` step | non-breaking — additive | `make check-all` completes without regression |
| `make plan-review` | `mk/handoff.mk` | Prints skill + checklist info; no precheck | Prints plan-analyze gate status; warns if analysis run absent | non-breaking — warning only on default; block on opt-in | `make plan-review DOC=... PLAN_ANALYZE_REQUIRED=1` blocks when no analysis run exists |
| `CLAUDE.md` | root `CLAUDE.md` | Key Triggers reference guides by path | Redirect to skill slash commands; remove duplicate inline prose | non-breaking for agents — new routing is clearer | Agent cold-start routes to skill, not guide |
| `docs/agentic/instructions.md` | docs | Role routing table references guides | Add skill as primary entry point; guide becomes reference link | non-breaking — additive | Manual review |
| `branch-review-guide.md` | docs | Primary execution surface | Add "Reference Appendix" header | non-breaking — additive | File header present after slice |
| `planning-review-guide.md` | docs | Primary execution surface | Add "Reference Appendix" header | non-breaking — additive | File header present after slice |

## Proposed Solution

Four slices deliver Phase 3. Slices 1 and 2 are independent and can be implemented in either order; Slice 3 depends on Slice 2 (routing redirect benefits from check-skills being in CI first); Slice 4 is independent.

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| Skill retrofit | `.claude/skills/refactor/SKILL.md` | Add full frontmatter + section headers |
| Skill retrofit | `.claude/skills/security-audit/SKILL.md` | Add full frontmatter + section headers |
| Skill retrofit | `.claude/skills/document-sync/SKILL.md` | Add full frontmatter + section headers |
| Skill retrofit | `.claude/skills/daemon-lifecycle/SKILL.md` | Add missing frontmatter fields + section headers |
| Skill retrofit | `.claude/skills/worktree-orchestrator/SKILL.md` | Add missing frontmatter fields + section headers |
| Skill retrofit | `.claude/skills/worktree-worker/SKILL.md` | Add missing frontmatter fields + section headers |
| Skill retrofit | `.claude/skills/rescue-lane/SKILL.md` | Add missing frontmatter fields + section headers |
| Skill retrofit | `.claude/skills/subfeature-committer/SKILL.md` | Add missing frontmatter fields + section headers |
| Check script | `scripts/check_skills.py` | New: validate frontmatter fields + section headers + wiring |
| Makefile target | `mk/handoff.mk` or root `Makefile` | Add `check-skills` target; wire into `check-all` |
| Routing surface | `CLAUDE.md` | Redirect Key Triggers to skills; remove inline prose duplicating skill content |
| Routing surface | `docs/agentic/instructions.md` | Redirect role routing table to skills as primary entry points |
| Reference label | `docs/agentic/rules/branch-review-guide.md` | Add "Reference Appendix" header block at top |
| Reference label | `docs/agentic/rules/planning-review-guide.md` | Add "Reference Appendix" header block at top |
| Planning gate | `mk/handoff.mk` plan-review target | Add plan-analyze precheck via Python query |
| Planning gate script | `scripts/check_plan_analyze.py` | New: query MCP review findings for analysis-mode run on target document |
| Planning pipeline doc | `docs/agentic/rules/planning-pipeline.md` | Add: plan-analyze is required before plan-review; document gate semantics |

## Related Files

| File | Note |
|---|---|
| `docs/agentic/templates/SKILL_ANATOMY.template.md` | Reference for required frontmatter fields and section structure |
| `docs/agentic/maps/mcp-tool-routing.yaml` | Source for known-tools registry in check-skills wiring check |
| `.claude/skills/branch-review/SKILL.md` | Reference anatomy-compliant skill for retrofit comparison |
| `docs/agentic/constitution.md` | Loaded by plan-analyze; referenced in planning gate |

## Verification Strategy

- Deterministic tests:
  - `python scripts/check_skills.py` exits 0 after all 8 skills are retrofitted
  - `make check-skills` exits 0; included in `make check-all` without breaking existing steps
  - `make check-skills` exits non-zero when a skill is missing a required field (manual: temporarily remove a field, verify failure, restore)
- Runtime-parity checks:
  - `make plan-review DOC=<path>` with no prior `plan-analyze` findings → prints gate warning; with `PLAN_ANALYZE_REQUIRED=1` → exits non-zero
  - `make plan-review DOC=<path>` after a recorded `plan-analyze` run → gate is silent
- Manual verification:
  - Cold-start read of `CLAUDE.md` Key Triggers → routing points to skill and slash command, not guide file path
  - Open `branch-review-guide.md` → "Reference Appendix" header visible at top
  - Open `planning-review-guide.md` → "Reference Appendix" header visible at top

## Slice Delivery

### Slice 1: Skill Retrofit

**Goal**: All 8 legacy skills pass the anatomy checklist after this slice. `make check-skills` (from Slice 2) exits 0 across all 19 skills.

Changes — for each of the 8 skills:

- Add or complete frontmatter: `name`, `description`, `mode` (advisory or execution), `tdd_gate` (true or false), `context_budget` (line count), `makefile_target` (null if no Makefile entry), `mcp_tools` (list of MCP tool names the skill composes, empty list if none).
- Ensure these section headers exist in the body: `## Overview`, `## Trigger`, `## Core Process`, `## Red Flags`, `## Convergence Criteria`. Add stubs where absent; do not rewrite existing content.
- Add `## Common Rationalizations` where the skill is complex enough to have known rationalization failure modes (at minimum: refactor, worktree-orchestrator, worktree-worker, daemon-lifecycle).

Anatomy values by skill (to be confirmed against current body content during implementation):

| Skill | mode | tdd_gate | makefile_target | mcp_tools |
|---|---|---|---|---|
| refactor | advisory | false | null | [] |
| security-audit | advisory | false | null | [] |
| document-sync | advisory | false | null | [] |
| daemon-lifecycle | execution | false | mcp-start | mcp__agent-orchestrator-mcp__manage_orchestrator, mcp__agent-orchestrator-mcp__manage_worker |
| worktree-orchestrator | execution | false | null | mcp__agent-orchestrator-mcp__manage_worktree_lane, mcp__agent-orchestrator-mcp__dispatch_lane_work, mcp__agent-handoff-mcp__record_event |
| worktree-worker | execution | true | null | mcp__agent-handoff-mcp__record_event, mcp__agent-handoff-mcp__close_slice, mcp__agent-orchestrator-mcp__worker_reports |
| rescue-lane | execution | false | null | mcp__agent-handoff-mcp__record_event |
| subfeature-committer | advisory | false | null | [] |

> **Implementation note**: confirm current body content before setting mode and mcp_tools — the table above is a best-estimate from the current SKILL.md headers. Do not invent tool usage that the skill body does not describe.

Proof:

- Each retrofitted skill's frontmatter renders without YAML parse errors (`python -c "import yaml; yaml.safe_load(open('.claude/skills/<name>/SKILL.md').read().split('---')[1])"`)
- All required section headers present in each file (`grep -l "## Convergence Criteria" .claude/skills/*/SKILL.md` returns all 19 paths)

### Slice 2: `make check-skills` Validator

**Goal**: Headless CI-safe validator that enforces anatomy compliance across all skills in `.claude/skills/`. Integrated into `make check-all`.

Changes:

- New `scripts/check_skills.py`:
  - Discovers all `SKILL.md` files under `.claude/skills/` recursively.
  - For each skill, validates:
    1. **Frontmatter fields**: `name`, `description`, `mode`, `tdd_gate`, `context_budget`, `makefile_target`, `mcp_tools` are all present (values may be null/empty but keys must exist).
    2. **`mode` value**: must be `advisory` or `execution`.
    3. **`tdd_gate` value**: must be boolean.
    4. **Section headers**: `## Overview`, `## Trigger`, `## Core Process`, `## Red Flags`, `## Convergence Criteria` all appear in the body.
    5. **Wiring check — `makefile_target`**: if non-null, the declared target appears in the root `Makefile` or any `mk/*.mk` include (grep check; no Makefile parsing).
    6. **Wiring check — `mcp_tools`**: each tool name in the list appears in the known-tools registry (hardcoded dict derived from `docs/agentic/maps/mcp-tool-routing.yaml` at script authoring time; the script documents where the registry was sourced and when it was last updated).
  - Outputs: one line per failure with skill name, check type, and detail. Exits 0 on all-pass; exits 1 on any failure.
  - Flag `--fix-missing-sections` (optional): adds stub section headers to skills missing them, for use during the retrofit pass only.
- New `check-skills` target in `mk/handoff.mk`:
  - `python scripts/check_skills.py`
- Add `check-skills` step to `check-all` in root `Makefile`.

Proof:

- `make check-skills` exits 0 after Slice 1 (all skills retrofitted).
- Temporarily remove `## Convergence Criteria` from one skill → `make check-skills` exits 1 and names the skill; restore the header → exits 0 again.
- Temporarily add an unknown tool name to one skill's `mcp_tools` → wiring check fails with the tool name and skill named; remove it → exits 0.
- `make check-all` completes without regression on other steps.

### Slice 3: CLAUDE.md + instructions.md Routing Redirect

**Goal**: Key Triggers and role routing in both documents point agents to skills as the primary execution entry point. Inline prose that duplicates skill content is removed. Both review guides are labelled as reference appendices.

Changes:

- `CLAUDE.md` § Key Triggers:
  - Replace the current file-path references to `branch-review-guide.md` and `planning-review-guide.md` with skill and slash-command references (e.g. "run `/branch-review` skill" → `.claude/skills/branch-review/SKILL.md`, Makefile entry: `make review-run`).
  - Remove inline prose that restates the skill's Core Process or check sequence (any block that would cause an agent to follow CLAUDE.md steps instead of the skill).
  - Keep: trigger conditions (what patterns invoke the skill), the mandatory gate notes, and cross-references to guides "for rationale and edge cases."
- `docs/agentic/instructions.md` § Role Routing table:
  - Add a "Primary skill" column (or equivalent note) pointing to the relevant `.claude/skills/<name>/SKILL.md` for branch review and planning review rows.
  - Note that guides are reference appendices, not execution surfaces.
- `docs/agentic/rules/branch-review-guide.md`:
  - Add at top (before any existing content):
    ```
    > **Reference Appendix** — This guide is the rationale and edge-case reference for the branch review process. The executable entry point is the [`branch-review` skill](./../../../.claude/skills/branch-review/SKILL.md) via `make review-run`. Agents should load the skill, not this guide, unless they need rationale for a specific judgment call.
    ```
- `docs/agentic/rules/planning-review-guide.md`: same treatment with `planning-review` skill and `make plan-review`.

Proof:

- Open `CLAUDE.md` Key Triggers → no mention of guide file paths as primary instructions; skill paths and slash commands present.
- Open `branch-review-guide.md` → "Reference Appendix" block visible as the first content element.
- Manual agent cold-start check: reading CLAUDE.md, an agent sees `make review-run` → `.claude/skills/branch-review/SKILL.md` without needing to load the 250-line guide.

### Slice 4: Planning Pipeline Exit Gate

**Goal**: `make plan-review` verifies that a `plan-analyze` run with recorded findings exists for the target document before the agent proceeds. Warning by default; hard block with `PLAN_ANALYZE_REQUIRED=1`.

**Gate semantics** (from epic decision): `plan-analyze` is a pre-review triage step. Its findings carry `review_mode="analysis"`. The gate checks for at least one such finding for the target document — it does not verify finding resolution (that is the planning-review skill's job). A planning-review run (review_mode="planning") satisfies its own gate separately.

Changes:

- New `scripts/check_plan_analyze.py`:
  - Accepts `--doc <path>` and `--task-ref <ref>` as arguments.
  - Queries `review_runs(review={"operation":"list", "review_mode":"planning", "subject_path":<doc>, "task_ref":<ref>})` via the `agent_handoff_mcp` Python API. Note: `review_mode="analysis"` is not a valid enum value — valid values are `branch`, `release_audit`, `planning`. `plan-analyze` records runs with `review_mode="planning"`.
  - Filters the returned runs to those whose `session` field starts with `plan-analyze`. This discriminates plan-analyze runs from full planning-review runs against the same document. Session naming convention: `plan-analyze-<doc-slug>-<date>`.
  - Exits 0 if at least one matching run is found; exits 1 on API/infrastructure errors (import failure, DB unavailable); exits 2 if the gate is not met — no matching plan-analyze run for the document.
  - Prints: "plan-analyze gate: PASS (N runs for <doc>)" or "plan-analyze gate: MISSING — run `make plan-analyze DOC=<doc>` before plan-review."
- Extend `plan-review` target in `mk/handoff.mk`:
  - After the DOC/file existence checks, run `python scripts/check_plan_analyze.py --doc $(DOC) --task-ref $(TASK)`.
  - If script exits 2 and `PLAN_ANALYZE_REQUIRED` is not set: print the gate warning and continue (print the existing plan-review info block as before).
  - If script exits 2 and `PLAN_ANALYZE_REQUIRED=1`: exit 1 before printing the plan-review info block.
  - TASK parameter defaults to the active task inferred from MCP identity if not provided (script handles the fallback).
- `docs/agentic/rules/planning-pipeline.md`:
  - Add under the Assessment → Spec and Spec → Task Plan transitions: "Before running `make plan-review`, the reviewing agent must run `make plan-analyze DOC=<path>` and ensure analysis findings are recorded in MCP. `make plan-review` checks for this and warns (or blocks with `PLAN_ANALYZE_REQUIRED=1`) when the gate is unmet."

Proof:

- `make plan-review DOC=<any plan without prior analysis run>` → prints gate warning, then proceeds to print the plan-review info block.
- `make plan-review DOC=<same plan> PLAN_ANALYZE_REQUIRED=1` → exits 1 before printing the plan-review block.
- Record a `plan-analyze` review run for the document via `review_runs(operation="record", review_mode="planning", session="plan-analyze-<slug>-<date>", subject_path=<doc>)` → `make plan-review DOC=<that doc>` → gate passes silently.
- `make plan-review DOC=<doc> TASK=E17-6` (explicit task ref) → check runs against the named task's findings.
