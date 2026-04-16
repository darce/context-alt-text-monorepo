# E17-6. Phase 3 Core Retrofit — Skill Anatomy Completion, Harness Protocol Contract, Routing Redirect, and Planning Gate Wiring

- **Date**: 2026-04-16
- **Author**: GPT-5.4
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-6`
- **Review Coverage Target**: 2

---

## Objective

Complete the epic-approved Phase 3 core: retrofit the 11 non-compliant skills to the anatomy template, add a headless `make check-skills` validator, establish a canonical `harness-protocol.yaml` contract for the shared Claude/VS Code behavioral surface, redirect guide-first review routing to skills as the primary execution entry points, and wire `plan-analyze` as a required precheck before `make plan-review` proceeds.

This task intentionally stops at the Phase 3 core. The broader handoff-state evolution, test-trace archive, MCP tool compression, and Codex command-surface normalization work is split into follow-on plan [E17-7](./E17-7-handoff-evolution-and-portable-workflow-task-plan.md).

## Problem Statement

Phase 1 and Phase 2 of E17 created anatomy-compliant skills for the eight core workflows (`tdd`, `incremental-implementation`, `scope`, `branch-lifecycle`, `handoff-lifecycle`, `branch-review`, `planning-review`, `plan-analyze`). Eleven legacy skills still need full or partial anatomy retrofit:

- **No frontmatter**: `refactor`, `security-audit`, `document-sync`
- **Partial frontmatter — Phase 1 retrofits**: `commit2git`, `investigate`, `review`
- **Partial frontmatter**: `daemon-lifecycle`, `worktree-orchestrator`, `worktree-worker`, `rescue-lane`, `subfeature-committer`

Four core Phase 3 gaps remain:

1. **No anatomy enforcement**: there is still no `make check-skills` target, so anatomy compliance is manual.
2. **No canonical shared harness contract**: Claude and VS Code instruction/hook surfaces have converged in places, but parity is still descriptive rather than machine-checked. There is no canonical contract for shared cold-start steps, shared hook matcher intent, or Python fallback imports.
3. **Review routing still conflicts**: `CLAUDE.md` and `instructions.md` now contain portable command routing, but both still retain guide-first review routing for branch/planning review. That conflict means an agent can still bypass the skill entry point and load the full guide directly.
4. **No enforced planning precheck**: `make plan-review` still prints guidance only. It does not verify that a prior `plan-analyze` pass recorded findings for the target document.

## Constraints

- `make check-skills` and `make check-harness-sync` must be headless and CI-safe.
- The known-tools registry in `check_skills.py` must be derived from `docs/agentic/maps/mcp-tool-routing.yaml`, not live MCP introspection.
- Skill retrofit edits add missing anatomy structure without rewriting each skill's core process.
- The routing redirect must remove conflicting execution guidance while keeping rationale/reference material available.
- The planning gate must key off recorded `plan-analyze` findings for the target document, not a surrogate review-run convention.
- This task does **not** own Codex portable-command normalization. Codex command parity is tracked in [E17-7](./E17-7-handoff-evolution-and-portable-workflow-task-plan.md).
- This task does **not** own `agent-handoff-mcp` schema redesign, raw test trace storage, or MCP tool-surface compression. Those are also split to [E17-7](./E17-7-handoff-evolution-and-portable-workflow-task-plan.md).

## Current State Analysis

**Skills directory**: `.claude/skills/` contains 19 skill directories. 8 are anatomy-compliant and 11 still need retrofit.

| Skill                   | Frontmatter state | Missing                                                                                        |
| ----------------------- | ----------------- | ---------------------------------------------------------------------------------------------- |
| `refactor`              | none              | all required fields + required sections                                                        |
| `security-audit`        | none              | all required fields + required sections                                                        |
| `document-sync`         | none              | all required fields + required sections                                                        |
| `commit2git`            | partial           | `tdd_gate`                                                                                     |
| `investigate`           | partial           | `tdd_gate`                                                                                     |
| `review`                | partial           | `tdd_gate`                                                                                     |
| `daemon-lifecycle`      | partial           | `mode`, `tdd_gate`, `context_budget`, `makefile_target`, `mcp_tools`; anatomy section coverage |
| `worktree-orchestrator` | partial           | `mode`, `tdd_gate`, `context_budget`, `makefile_target`, `mcp_tools`; anatomy section coverage |
| `worktree-worker`       | partial           | `mode`, `tdd_gate`, `context_budget`, `makefile_target`, `mcp_tools`; anatomy section coverage |
| `rescue-lane`           | partial           | `mode`, `tdd_gate`, `context_budget`, `makefile_target`, `mcp_tools`; anatomy section coverage |
| `subfeature-committer`  | partial           | `mode`, `tdd_gate`, `context_budget`, `makefile_target`, `mcp_tools`; anatomy section coverage |

**Makefile**: `make check-all` still does not include a skill-anatomy validation target.

**Shared harness surfaces**:

- `.claude/settings.json` currently defines **3** `PreToolUse` hooks and **5** `PostToolUse` hooks.
- `.github/hooks/terminal-guard.json` currently defines **4** `PreToolUse` hooks and **5** `PostToolUse` hooks.
- Both harnesses already contain `regenerate-task-views.sh`; the unresolved issue is lack of a canonical contract plus non-normalized matcher ownership such as Claude-only `validate-mcp-dict-params.py`.

**Routing surfaces**:

- `CLAUDE.md` has a portable command router section, but its review triggers still say to load `branch-review-guide.md` and `planning-review-guide.md` directly.
- `docs/agentic/instructions.md` has portable command routing and Additional Routing entries for the skills, but its later review-routing sections still instruct agents to load the guides directly.

**Planning gate**:

- `mk/handoff.mk` `plan-analyze` currently promises `MCP findings with review_mode=analysis before planning review`.
- `mk/handoff.mk` `plan-review` still performs no precheck.
- The current MCP review-mode enum does not include `analysis`, so the gate implementation must use recorded finding rows and session/file-path evidence instead of a nonexistent `review_mode="analysis"` filter.

## Out of Scope

The following work has been split out of this task and moved to [E17-7](./E17-7-handoff-evolution-and-portable-workflow-task-plan.md):

- Multi-active-task handoff-state registry and task-resolution redesign
- Slice-completion/session-status handoff enhancements
- Raw test trace archive and change-outcome linkage
- MCP tool-surface compression (`generate_md`, `handoff_transfer`, `task_archive`)
- Codex portable-command propagation from `portable_commands.json`
- `make check-agent-workflows`, `make check-codex-command-router`, and `make smoke-agent-workflows` expansion

## Target Outcome

- All 19 skills pass `make check-skills`.
- `make check-skills` is wired into `make check-all`.
- `docs/agentic/contracts/harness-protocol.yaml` defines the shared Claude/VS Code protocol surface and `make check-harness-sync` validates both harness hook files against it.
- `CLAUDE.md` and `docs/agentic/instructions.md` route review work to skills as the primary execution surface; guides are explicitly reference-only.
- `branch-review-guide.md` and `planning-review-guide.md` are labelled as reference appendices.
- `make plan-review DOC=<path>` warns or blocks when no prior `plan-analyze` findings exist for the target document.

## Context Loading

- Anatomy template: `docs/agentic/templates/SKILL_ANATOMY.template.md`
- MCP tool routing: `docs/agentic/maps/mcp-tool-routing.yaml`
- Existing anatomy-compliant reference skill: `.claude/skills/branch-review/SKILL.md`
- Routing surfaces: `CLAUDE.md`, `docs/agentic/instructions.md`
- Planning entry points: `mk/handoff.mk`
- Planning pipeline rules: `docs/agentic/rules/planning-pipeline.md`
- Review guides: `docs/agentic/rules/branch-review-guide.md`, `docs/agentic/rules/planning-review-guide.md`
- Harness hook surfaces: `.claude/settings.json`, `.github/hooks/terminal-guard.json`
- Python API surface: `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py`
- Follow-on split target: [E17-7](./E17-7-handoff-evolution-and-portable-workflow-task-plan.md)

## Contract and Boundary Impact

| Boundary                        | Owner                                 | Current Contract                                 | Expected Change                                                                                | Compatibility Needed?           | Verification                               |
| ------------------------------- | ------------------------------------- | ------------------------------------------------ | ---------------------------------------------------------------------------------------------- | ------------------------------- | ------------------------------------------ |
| `make check-skills`             | `scripts/check_skills.py` (new)       | does not exist                                   | headless anatomy validator                                                                     | n/a — new target                | `make check-skills` exits 0 after retrofit |
| `make check-all`                | root `Makefile`                       | no skill validation step                         | add `check-skills` and `check-harness-sync`                                                    | non-breaking                    | `make check-all` passes                    |
| `harness-protocol.yaml`         | `docs/agentic/contracts/` (new)       | does not exist                                   | canonical shared Claude/VS Code protocol contract                                              | n/a — new file                  | `make check-harness-sync` passes           |
| `make check-harness-sync`       | `scripts/check_harness_sync.py` (new) | does not exist                                   | validates `.claude/settings.json` and `.github/hooks/terminal-guard.json` against the contract | non-breaking                    | intentional drift fails                    |
| `CLAUDE.md`                     | root doc                              | guide-first review triggers                      | redirect to skills as primary entry points                                                     | non-breaking                    | skill-first routing visible                |
| `docs/agentic/instructions.md`  | docs                                  | mixed skill-first and guide-first review routing | remove guide-first conflict; keep portable router + skill entry points                         | non-breaking                    | no conflicting review router remains       |
| `branch-review-guide.md`        | docs                                  | primary execution language                       | add reference-appendix label                                                                   | non-breaking                    | header visible at top                      |
| `planning-review-guide.md`      | docs                                  | primary execution language                       | add reference-appendix label                                                                   | non-breaking                    | header visible at top                      |
| `make plan-review`              | `mk/handoff.mk`                       | informational only                               | add plan-analyze findings precheck                                                             | non-breaking warning by default | warning/block behavior works               |
| `scripts/check_plan_analyze.py` | new                                   | does not exist                                   | query review findings via Python API and filter by `plan-analyze-*` session + target file path | n/a — new file                  | pass/fail paths covered                    |

## Proposed Solution

Five slices deliver the Phase 3 core. They should land in this order:

1. Skill retrofit
2. `check-skills`
3. Harness protocol contract + sync validator
4. Routing redirect / reference-appendix relabeling
5. Planning gate

The broader handoff/tooling/Codex work is intentionally deferred to [E17-7](./E17-7-handoff-evolution-and-portable-workflow-task-plan.md) so this task remains reviewable against the epic-approved Phase 3 scope.

## Files and Surfaces to Change

| Surface               | File                                            | Change                                                               |
| --------------------- | ----------------------------------------------- | -------------------------------------------------------------------- |
| Skill retrofit        | `.claude/skills/refactor/SKILL.md`              | add full frontmatter + anatomy sections                              |
| Skill retrofit        | `.claude/skills/security-audit/SKILL.md`        | add full frontmatter + anatomy sections                              |
| Skill retrofit        | `.claude/skills/document-sync/SKILL.md`         | add full frontmatter + anatomy sections                              |
| Skill retrofit        | `.claude/skills/commit2git/SKILL.md`            | add missing `tdd_gate`                                               |
| Skill retrofit        | `.claude/skills/investigate/SKILL.md`           | add missing `tdd_gate`                                               |
| Skill retrofit        | `.claude/skills/review/SKILL.md`                | add missing `tdd_gate`                                               |
| Skill retrofit        | `.claude/skills/daemon-lifecycle/SKILL.md`      | finish anatomy frontmatter + sections                                |
| Skill retrofit        | `.claude/skills/worktree-orchestrator/SKILL.md` | finish anatomy frontmatter + sections                                |
| Skill retrofit        | `.claude/skills/worktree-worker/SKILL.md`       | finish anatomy frontmatter + sections                                |
| Skill retrofit        | `.claude/skills/rescue-lane/SKILL.md`           | finish anatomy frontmatter + sections                                |
| Skill retrofit        | `.claude/skills/subfeature-committer/SKILL.md`  | finish anatomy frontmatter + sections                                |
| Validator             | `scripts/check_skills.py`                       | new anatomy validator                                                |
| Makefile              | root `Makefile` and/or `mk/handoff.mk`          | add `check-skills` target and wire to `check-all`                    |
| Harness contract      | `docs/agentic/contracts/harness-protocol.yaml`  | new canonical shared harness contract                                |
| Harness validator     | `scripts/check_harness_sync.py`                 | new contract drift validator                                         |
| Guide routing         | `CLAUDE.md`                                     | remove guide-first review triggers; point to skills                  |
| Guide routing         | `docs/agentic/instructions.md`                  | remove guide-first review router conflicts; keep skill-first routing |
| Reference labels      | `docs/agentic/rules/branch-review-guide.md`     | add reference appendix label                                         |
| Reference labels      | `docs/agentic/rules/planning-review-guide.md`   | add reference appendix label                                         |
| Planning gate         | `scripts/check_plan_analyze.py`                 | new plan-analyze findings precheck                                   |
| Planning gate         | `mk/handoff.mk`                                 | call `check_plan_analyze.py` from `plan-review`                      |
| Planning pipeline doc | `docs/agentic/rules/planning-pipeline.md`       | document the pre-review gate                                         |

## Verification Strategy

- `python scripts/check_skills.py` exits 0 after the retrofit.
- `make check-skills` fails on an intentional missing field or section and passes after restore.
- `make check-harness-sync` passes on current files and fails on intentional contract drift.
- `make check-harness-sync --check-api-surface` validates the documented Python imports.
- `CLAUDE.md` and `docs/agentic/instructions.md` no longer present branch/planning review guides as the primary execution surface.
- `branch-review-guide.md` and `planning-review-guide.md` show the reference-appendix label at the top.
- `make plan-review DOC=<path>` warns by default and blocks with `PLAN_ANALYZE_REQUIRED=1` when no prior `plan-analyze` findings exist.
- A recorded `plan-analyze-*` finding for the same document path causes the gate to pass.

## Slice Delivery

### Slice 1: Skill Retrofit

**Goal**: all 11 non-compliant skills satisfy the anatomy template.

Changes:

- Add/complete required frontmatter: `name`, `description`, `mode`, `tdd_gate`, `context_budget`, `makefile_target`, `mcp_tools`.
- Ensure required section headers exist: `## Overview`, `## Trigger`, `## Core Process`, `## Red Flags`, `## Convergence Criteria`.
- Preserve each skill's existing process content; add only the missing anatomy structure.

Proof:

- YAML frontmatter parses for all 19 skills.
- All required section headers appear in all 19 `SKILL.md` files.
- `commit2git`, `investigate`, and `review` retain their current process content while gaining `tdd_gate`.

### Slice 2: `make check-skills` Validator

**Goal**: enforce anatomy compliance headlessly and wire it into `make check-all`.

Changes:

- Add `scripts/check_skills.py` to validate required frontmatter keys, `mode`, `tdd_gate`, required section headers, Makefile target wiring, and `mcp_tools` registry membership.
- Add `make check-skills`.
- Add `check-skills` to `make check-all`.

Proof:

- `make check-skills` passes after Slice 1.
- Intentional frontmatter/section regression fails with a named error.
- `make check-all` includes the new validation without regressing other steps.

### Slice 3: Harness Protocol Contract + Sync Validator

**Goal**: define and validate the shared Claude/VS Code behavioral surface.

Changes:

- Add `docs/agentic/contracts/harness-protocol.yaml` describing:
  - cold-start steps shared by the managed harnesses
  - shared hook matcher intent and script ownership
  - Python API fallback imports from `agent_handoff_mcp`
  - branch-isolation policy shared by the harnesses
- Add `scripts/check_harness_sync.py` to compare the contract against `.claude/settings.json` and `.github/hooks/terminal-guard.json`.
- Normalize any remaining drift required for the contract to pass, including matcher coverage or hook ownership that is currently defined in one harness only.

Proof:

- `make check-harness-sync` passes on the committed surfaces.
- Removing or renaming a contracted hook causes the validator to fail with a named diff.

### Slice 4: Routing Redirect + Reference Appendix Labels

**Goal**: remove guide-first review routing conflicts and make skills the primary execution entry points.

Changes:

- Update `CLAUDE.md` review triggers to point to the relevant skill and Makefile target, not directly to the guide.
- Update `docs/agentic/instructions.md` so its later review-routing sections do not conflict with the portable command router and Additional Routing table.
- Add a reference appendix label to `branch-review-guide.md` and `planning-review-guide.md`.

Proof:

- `CLAUDE.md` no longer instructs agents to load `branch-review-guide.md` or `planning-review-guide.md` as the primary review path.
- `docs/agentic/instructions.md` no longer has conflicting skill-first and guide-first review routing for the same review modes.
- Both guides clearly say they are reference-only.

### Slice 5: Planning Pipeline Exit Gate

**Goal**: require prior `plan-analyze` findings before formal planning review.

Gate semantics:

- `plan-analyze` remains a pre-review triage step.
- The gate checks for recorded findings whose `session` starts with `plan-analyze-` and whose `file_path` matches the target document.
- The gate does **not** require a `review_run` row from `plan-analyze`.

Changes:

- Add `scripts/check_plan_analyze.py`:
  - accepts `--doc` and `--task-ref`
  - queries planning findings via the Python API by calling `list_review_findings(review_mode="planning")`
  - filters the returned rows in Python, because the current review-findings API does not expose `session` or `file_path` as server-side query parameters
  - filters to `session.startswith("plan-analyze-")`
  - filters to findings recorded for the target document path
  - exits `0` on pass, `1` on infrastructure error, `2` when the gate is unmet
- Update `mk/handoff.mk` `plan-review` to call the script and warn/block based on `PLAN_ANALYZE_REQUIRED`.
- Update `docs/agentic/rules/planning-pipeline.md` to document the gate.

Proof:

- `make plan-review DOC=<plan>` warns when no prior analysis findings exist.
- `make plan-review DOC=<plan> PLAN_ANALYZE_REQUIRED=1` blocks when no prior analysis findings exist.
- A prior `plan-analyze-*` finding for the same document causes the gate to pass.

---

## Consolidated Checklist

### Context and Ownership

- [ ] Verify 11 non-compliant skills still need retrofit
- [ ] Confirm `SKILL_ANATOMY.template.md` remains the anatomy authority
- [ ] Confirm [E17-7](./E17-7-handoff-evolution-and-portable-workflow-task-plan.md) now owns the split-out follow-on work

### Checklist for Slice 1: Skill Retrofit

- [ ] All 11 non-compliant skills have full required frontmatter
- [ ] All 11 non-compliant skills have required anatomy section headers
- [ ] `commit2git`, `investigate`, and `review` gain `tdd_gate`
- [ ] Frontmatter parses without YAML errors for all 19 skills

### Checklist for Slice 2: `make check-skills`

- [ ] `scripts/check_skills.py` validates anatomy fields, section headers, Makefile targets, and tool wiring
- [ ] `make check-skills` passes after Slice 1
- [ ] `make check-skills` fails on intentional regression
- [ ] `check-skills` is wired into `make check-all`

### Checklist for Slice 3: Harness Protocol Contract

- [ ] `docs/agentic/contracts/harness-protocol.yaml` defines the shared Claude/VS Code protocol surface
- [ ] `scripts/check_harness_sync.py` validates both managed harness hook files
- [ ] Remaining shared-surface drift required by the contract is resolved
- [ ] `make check-harness-sync` is wired into `make check-all`

### Checklist for Slice 4: Routing Redirect

- [ ] `CLAUDE.md` branch/planning review triggers point to skills, not guides
- [ ] `docs/agentic/instructions.md` no longer has conflicting guide-first review routing
- [ ] `branch-review-guide.md` is labelled reference-only
- [ ] `planning-review-guide.md` is labelled reference-only

### Checklist for Slice 5: Planning Gate

- [ ] `scripts/check_plan_analyze.py` checks recorded `plan-analyze-*` findings for the target document
- [ ] Exit codes are `0` pass, `1` infrastructure error, `2` gate unmet
- [ ] `make plan-review` warns/blocks correctly based on `PLAN_ANALYZE_REQUIRED`
- [ ] `planning-pipeline.md` documents the gate

## Review Readiness

- [ ] `make check-all` stays green after each slice
- [ ] No handoff-schema redesign is included in this task
- [ ] No Codex portable-command work is included in this task

## Success Criteria

- [ ] `make check-skills` exits 0 across all 19 skills
- [ ] All 11 non-compliant skills pass anatomy validation
- [ ] `docs/agentic/contracts/harness-protocol.yaml` is the shared contract for the managed Claude/VS Code surfaces
- [ ] `make check-harness-sync` exits 0 with no drift
- [ ] Review routing points to skills as the primary execution surface
- [ ] Both review guides are explicitly labelled as reference appendices
- [ ] `make plan-review` warns or blocks when no prior `plan-analyze` findings exist for the target document
