# E17-3. Core Workflow Skills — Lifecycle, Review, and Planning

> **Metadata**
>
> - **Date**: 2026-04-13
> - **Author**: Claude Sonnet 4.6
> - **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
> - **Epic Short ID**: E17
> - **Target Branch**: `feature/e17-3`
> - **Review Coverage Target**: 1
>
> **Prerequisites:** E17-3 is blocked until **E17-2 merges**. Verify before starting:
> `ls .claude/commands/tdd.md .claude/commands/incremental-implementation.md` must both exist.
> Without E17-2, 2 of the 8 target command files are absent and the success criteria at line 282 cannot be satisfied.

---

## Objective

Create the remaining six Phase 2 execution/advisory skills (`scope`, `branch-lifecycle`, `handoff-lifecycle`, `branch-review`, `planning-review`, `plan-analyze`), their paired `.claude/commands/` entry points, path-verification of the existing `plan-review` and `plan-analyze` Makefile stubs (already in `mk/handoff.mk`), and the PostToolUse dashboard auto-refresh hook. When complete, every major development workflow has a discoverable skill with a slash command entry point — including a question-first intake skill that elicits requirements before any planning artifact is written — and CURRENT_TASK.md + DASHBOARD.md regenerate automatically after every state-changing MCP write.

## Problem Statement

After E17-2, three workflow categories remain without skills: the task lifecycle (task-start through task-finish with the invariant close sequence), the review workflows (branch review, planning review, and plan analysis), and requirements intake for new features (the reversal/question-first pattern that should precede any planning artifact). Agents loading the 250-line `branch-review-guide.md` or the `planning-review-guide.md` in full is the dominant context-bloat pattern this epic targets. Similarly, `CURRENT_TASK.md` regeneration after `record_event` and `review_findings` writes is advisory only — no hook enforces it, causing stale dashboard state between agent writes.

## Constraints

- No code changes (`apps/`, `packages/`). All deliverables are skill files, command files, Makefile targets, settings, and docs.
- Each skill must conform to `SKILL_ANATOMY.template.md`.
- `plan-analyze` is advisory (`mode: advisory`, `tdd_gate: false`); all others are execution skills.
- `plan-analyze` does NOT record a review run — only `planning-review` does. The distinction must be explicit in the `plan-analyze` skill to prevent agents from confusing the two.
- The PostToolUse hook runs `generate_current_task_md` + `generate_dashboard_md` as a shell command after `record_event`, `review_findings`, and `review_runs` writes. It must not introduce circular regeneration loops.
- New Makefile targets (`plan-review`, `plan-analyze`) are agent-assisted — they print context and point to the skill; they do not run headless.

## Workflow Principles

- Each skill paired with its command file in the same slice and the same commit.
- `branch-lifecycle` documents the Worktree Status Integrity invariant close sequence from the epic as its completion criteria.
- `handoff-lifecycle` documents `switch_task` as the safe task-transition path and `archive_task_state`-after-`update_task_status(done)` as the mandatory order.
- `branch-review` pre-triage step uses `get_review_findings_summary` + `reconcile_review_findings` (orchestrator-mcp) before running detection passes.
- `plan-analyze` findings use `review_mode="analysis"` — distinct from `review_mode="planning"` — so they don't pollute the planning review run count.

## Terminology

- **Agent-assisted target**: a Makefile target that prints environment context and points to a skill; requires an active agent session to execute the skill logic.
- **Detection pass**: one of six analysis checks run by `plan-analyze` (duplication, ambiguity, underspecification, constitution alignment, coverage gaps, terminology drift).
- **Review run**: a recorded `review_runs(operation="record")` entry — only `branch-review` and `planning-review` skills produce these; `plan-analyze` does not.

## Current State Analysis

- No `scope`, `branch-lifecycle`, `handoff-lifecycle`, `branch-review`, `planning-review`, or `plan-analyze` skills exist.
- **Prerequisite: E17-2 merged.** When E17-3 starts, `.claude/commands/tdd.md` and `.claude/commands/incremental-implementation.md` already exist (delivered by E17-2). Five command files remain to be created by this task.
- `make plan-review` and `make plan-analyze` exist as stubs in `mk/handoff.mk`, pointing to Phase 2 skill files that do not yet exist. This task creates the skills those stubs reference; the targets themselves need no changes unless their guidance text needs refinement.
- No PostToolUse hook regenerates views after `record_event`/`review_findings`/`review_runs` writes. `close_slice`, `update_task_status`, and `archive_task_state` already regenerate atomically server-side; this hook closes the remaining gap.
- `scripts/_task_start_inline.py` task-transition semantics were repaired in AHMCP-28: it now archives the outgoing task before activating the new one. The `handoff-lifecycle` skill here documents the already-corrected behavior; no further repair to `_task_start_inline.py` is in scope.
- `branch-review-guide.md` (≥250 lines) and `planning-review-guide.md` are loaded in full today; skills will extract the executable subset.

## Target Outcome

Six skills exist in `.claude/skills/`. Six command files exist in `.claude/commands/`. Typing `/scope` before any new feature ask elicits 3–5 questions before any plan is generated. Typing `/branch-review` loads the review skill directly instead of the 250-line guide. `make plan-analyze DOC=<path>` prints guidance pointing the agent to the `plan-analyze` skill. `make plan-review DOC=<path>` does the same for `planning-review`. CURRENT_TASK.md and DASHBOARD.md regenerate within one tool call of any `record_event`, `review_findings`, or `review_runs` write.

## Context Loading

- Template: `docs/agentic/templates/SKILL_ANATOMY.template.md`
- Epic: `docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md` (Phase 2, remaining 6 skill entries including `scope`)
- Lifecycle: `docs/agentic/lifecycle-map.md` (I1–I7 stage map, orchestrator Quick Reference)
- Review guide (reference): `docs/agentic/rules/branch-review-guide.md` (executable subset to extract)
- Planning review guide (reference): `docs/agentic/rules/planning-review-guide.md` (executable subset to extract)
- Workflow: `docs/agentic/rules/development-workflow.md` (Pre-Merge Gate, Slice Checklist)
- Pipeline: `docs/agentic/rules/planning-pipeline.md` (Stage 1–4 exit gates)
- Constitution: `docs/agentic/constitution.md` (validation reference for `plan-analyze` detection passes)
- Settings: `.claude/settings.json` (existing PostToolUse hooks — must not duplicate or conflict)
- Makefile: `mk/handoff.mk` (existing target patterns to follow for new targets)
- Handoff/MCP state: start fresh task `E17-3` at implementation start; E17-2 must be merged first

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|----------|-------|------------------|-----------------|----------------------|--------------|
| `.claude/settings.json` PostToolUse | repo-wide | Existing hooks: `review_findings` → `ace-detect.py`; `get_handoff_state`/`load_session` → `slim-handoff-response.py`; `Bash` → `filter-test-output.py` | Add new PostToolUse hook matching `record_event\|review_findings\|review_runs` → regeneration script | No conflict — new matcher is additive; `review_findings` already has a hook, new hook adds a second handler | Manual: verify both hooks fire on `review_findings`; `CURRENT_TASK.md` and `DASHBOARD.md` updated after write |
| Agent routing (`instructions.md`) | repo-wide | Additional Routing table has no skill references for review/lifecycle | Add rows for all 6 new skills (2 in Slice 1: branch-lifecycle, handoff-lifecycle; 4 in Slice 2: scope, branch-review, planning-review, plan-analyze) | No | `grep 'scope\|branch-lifecycle\|handoff-lifecycle\|branch-review\|planning-review\|plan-analyze' docs/agentic/instructions.md` |

## Proposed Solution

Three slices in dependency order: lifecycle skills first (lowest dependency), then review/planning skills (reference lifecycle state), then infrastructure (hook + Makefile targets). Command files committed with their skill in the same slice.

## Files and Surfaces to Change

| Surface | File | Change |
|---------|------|--------|
| Skill | `.claude/skills/scope/SKILL.md` | New advisory skill (~60 lines) |
| Command | `.claude/commands/scope.md` | New slash command (~15 lines) |
| Skill | `.claude/skills/branch-lifecycle/SKILL.md` | New execution skill (~150 lines) |
| Command | `.claude/commands/branch-lifecycle.md` | New slash command (~15 lines) |
| Skill | `.claude/skills/handoff-lifecycle/SKILL.md` | New execution skill (~100 lines) |
| Command | `.claude/commands/handoff-lifecycle.md` | New slash command (~15 lines) |
| Skill | `.claude/skills/branch-review/SKILL.md` | New execution skill (~150 lines) |
| Command | `.claude/commands/branch-review.md` | New slash command (~15 lines) |
| Skill | `.claude/skills/planning-review/SKILL.md` | New execution skill (~120 lines) |
| Command | `.claude/commands/planning-review.md` | New slash command (~15 lines) |
| Skill | `.claude/skills/plan-analyze/SKILL.md` | New advisory skill (~200 lines) |
| Command | `.claude/commands/plan-analyze.md` | New slash command (~15 lines) |
| Makefile | `mk/handoff.mk` | Verify existing `plan-review` and `plan-analyze` stub targets reference the correct skill paths |
| Settings | `.claude/settings.json` | Add PostToolUse hook for `record_event\|review_findings\|review_runs` |
| Script | `scripts/hooks/regenerate-task-views.sh` | New shell script: calls `agent-handoff-mcp task` + `agent-handoff-mcp dashboard` |
| Routing | `docs/agentic/instructions.md` | Add rows for all 5 skills to Additional Routing table |

## Related Files

| File | Note |
|------|------|
| `docs/agentic/rules/branch-review-guide.md` | Preserved as reference; executable subset extracted to `branch-review` skill |
| `docs/agentic/rules/planning-review-guide.md` | Preserved as reference; executable subset extracted to `planning-review` skill |
| `docs/agentic/constitution.md` | Loaded by `plan-analyze` as the validation reference for constitution-alignment detection pass |
| `mk/handoff.mk` | Existing `review-run` pattern to follow for new agent-assisted targets |
| `.github/hooks/terminal-guard.json` | VS Code parallel hook surface — verify new PostToolUse hook pattern is consistent |

## Verification Strategy

- Deterministic checks:
  - `grep -c 'mode: execution' .claude/skills/branch-lifecycle/SKILL.md .claude/skills/handoff-lifecycle/SKILL.md .claude/skills/branch-review/SKILL.md .claude/skills/planning-review/SKILL.md` → 4
  - `grep -c 'mode: advisory' .claude/skills/scope/SKILL.md .claude/skills/plan-analyze/SKILL.md` → 2
  - `grep 'AskUserQuestion' .claude/skills/scope/SKILL.md` → present
  - `grep 'tdd_gate: false' .claude/skills/branch-review/SKILL.md .claude/skills/plan-analyze/SKILL.md .claude/skills/planning-review/SKILL.md .claude/skills/handoff-lifecycle/SKILL.md` → 4 matches
  - `grep 'tdd_gate: true' .claude/skills/branch-lifecycle/SKILL.md` → 1
  - `grep 'review_mode.*analysis' .claude/skills/plan-analyze/SKILL.md` → present (confirming plan-analyze uses analysis mode)
  - `grep 'review_runs' .claude/skills/plan-analyze/SKILL.md` → 0 (plan-analyze must NOT record a review run)
  - `grep 'update_task_status.*done.*archive_task_state\|archive.*update_task_status' .claude/skills/handoff-lifecycle/SKILL.md` → present (ordering rule documented)
  - `grep 'plan-review\|plan-analyze' mk/handoff.mk` → 2 targets present
  - `grep 'regenerate-task-views\|record_event.*review_findings.*review_runs' .claude/settings.json` → PostToolUse hook present
  - `make lint-task-plans` → passes
- Manual verification:
  - `branch-lifecycle` convergence criteria include the 4-step invariant close sequence
  - `branch-review` core process starts with `get_review_findings_summary` + `reconcile_review_findings` pre-triage
  - `plan-analyze` explicitly states it is NOT a substitute for a `planning-review` pass
  - PostToolUse hook does not conflict with existing `ace-detect.py` hook on `review_findings`

## Slice Delivery

### Slice 1: Lifecycle Skills

**Goal**: Create `branch-lifecycle` and `handoff-lifecycle` execution skills with paired command files, covering the full task-start → task-finish lifecycle and the session-start → session-end handoff pattern.

Changes:

- Create `.claude/skills/branch-lifecycle/SKILL.md`:
  - Frontmatter: `mode: execution`, `context_budget: 150`, `tdd_gate: true`, `makefile_target: task-start`, `mcp_tools: [set_handoff_state, record_event, close_slice, handoff_close_check, archive_task_state, generate_current_task_md]`; note `manage_worktree_lane`, `switch_task` (agent-orchestrator-mcp) in tools description
  - Core process: `make task-start` → `make context` → TDD implementation loop (I2–I4) → `make review-ready` → review → `make handoff-close-check` → `make task-finish`
  - Convergence: `handoff_close_check(enforce=True)` passes; task archived; both views regenerated; branch deleted; root on `main`
  - Worktree Status Integrity: documents the invariant close sequence: `update_task_status(done)` → `manage_worktree_lane(close)` when lanes used → `archive_task_state` → `generate_dashboard_md`
  - Common rationalizations: "I'll archive first then update status"; "the worktree is already gone so the close sequence doesn't matter"; "I'll skip handoff_close_check this once"
- Create `.claude/commands/branch-lifecycle.md`
- Create `.claude/skills/handoff-lifecycle/SKILL.md`:
  - Frontmatter: `mode: execution`, `context_budget: 100`, `tdd_gate: false`, `makefile_target: null`, `mcp_tools: [load_session, get_handoff_state, record_event, generate_current_task_md]`; note `switch_task` (agent-orchestrator-mcp)
  - Core process: `make context` → `load_session` (hot state) → verify alignment (branch matches task target_branch) → work loop → record decisions → `generate_current_task_md` after every state write → session end
  - Documents: `switch_task` as safe task-transition entry point; `archive_task_state` must only run after `update_task_status(done)`; CURRENT_TASK.md is a generated view — never hand-edit
  - Common rationalizations: "I'll archive while in_progress, it's fine"; "I already know what state I'm in, I don't need load_session"; "I'll update CURRENT_TASK.md directly instead of regenerating"
- Create `.claude/commands/handoff-lifecycle.md`
- Add routing rows to `docs/agentic/instructions.md` Additional Routing

Proof:

- `grep 'tdd_gate: true' .claude/skills/branch-lifecycle/SKILL.md` → 1
- `grep 'invariant.*close\|close.*sequence\|update_task_status.*done' .claude/skills/branch-lifecycle/SKILL.md` → present
- `grep 'switch_task\|archive.*done\|done.*archive' .claude/skills/handoff-lifecycle/SKILL.md` → present
- All 10 anatomy sections in both skills

### Slice 2: Review, Planning, and Intake Skills

**Goal**: Create `scope`, `branch-review`, `planning-review`, and `plan-analyze` skills with paired command files and new `make plan-review` / `make plan-analyze` agent-assisted Makefile targets.

Changes:

- Create `.claude/skills/scope/SKILL.md`:
  - Frontmatter: `mode: advisory`, `context_budget: 60`, `tdd_gate: false`, `makefile_target: null`, `mcp_tools: [record_event, artifacts]`
  - Trigger: new feature requests, new epic scoping, new capability planning. NOT triggered by bug fixes, tech debt tasks, or tasks derived from approved specs.
  - Core process (reversal pattern): ask 3–5 questions via `AskUserQuestion` **before generating any output** → categories: scope, completion signals, edge cases, non-functional constraints, not-doing → record each Q&A as `record_event(event_kind="decision")` → output `docs/ideas/[slug].md` one-pager (MVP scope, assumptions, Not-Doing list, success criteria)
  - Common rationalizations: "I already know the scope"; "the user's prompt is clear enough"; "I'll ask questions later if I get stuck"
  - Convergence: ≥3 questions asked and answered; Q&A recorded as MCP decisions; Not-Doing list present
- Create `.claude/commands/scope.md`
- Add routing row to `docs/agentic/instructions.md` Additional Routing
- Create `.claude/skills/branch-review/SKILL.md`:
  - Frontmatter: `mode: execution`, `context_budget: 150`, `tdd_gate: false`, `makefile_target: review-run`, `mcp_tools: [get_latest_slice_review_packet, review_findings, review_runs, record_event, handoff_close_check]`; note `get_review_findings_summary`, `reconcile_review_findings` (agent-orchestrator-mcp)
  - Core process: `get_review_findings_summary` + `reconcile_review_findings` (pre-triage) → `get_latest_slice_review_packet` → `review_runs(list)` (check prior passes) → detection passes (per `branch-review-guide.md` categories) → `review_findings(batch_record)` → `review_runs(record)` → verify zero open findings → `record_event(decision, verdict)`
  - Convergence: zero open findings; verdict decision recorded; review run recorded; `handoff_close_check` will pass
- Create `.claude/commands/branch-review.md`
- Create `.claude/skills/planning-review/SKILL.md`:
  - Frontmatter: `mode: execution`, `context_budget: 120`, `tdd_gate: false`, `makefile_target: plan-review`, `mcp_tools: [review_findings, review_runs, record_event, search_handoff]`
  - Core process: load planning doc + code anchors → `review_runs(list)` → run planning checklist passes (current state accuracy, slice traceability, verification completeness, constraint coverage) → `review_findings(batch_record)` → `review_runs(record)` → verify convergence → `record_event(decision, verdict)`
  - Convergence: ≥1 review run recorded with `review_mode="planning"`; zero open findings
- Create `.claude/commands/planning-review.md`
- Create `.claude/skills/plan-analyze/SKILL.md`:
  - Frontmatter: `mode: advisory`, `context_budget: 200`, `tdd_gate: false`, `makefile_target: plan-analyze`, `mcp_tools: [review_findings]`
  - Core process: load plan + `constitution.md` + relevant code anchors → run six detection passes (duplication, ambiguity, underspecification, constitution alignment, coverage gaps, terminology drift) → produce findings table → `review_findings(batch_record, review_mode="analysis")`
  - Explicit gate semantics: does NOT record a review run via `review_runs`; findings use `review_mode="analysis"` (distinct from `review_mode="planning"`); is a pre-review triage step, not a substitute for `planning-review`
  - Convergence: findings table produced and recorded in MCP; recommendation (proceed to planning-review / revise first) stated
- Create `.claude/commands/plan-analyze.md`
- Verify `plan-review` and `plan-analyze` targets in `mk/handoff.mk` (already exist as stubs):
  - Confirm each target validates `DOC` is set, prints the doc path, and references the correct skill path
  - Update the skill path references if the stubs point to placeholder paths — the real skills will now exist at `.claude/skills/plan-analyze/SKILL.md` and `.claude/skills/planning-review/SKILL.md`
  - No new Makefile targets needed
- Add routing rows to `docs/agentic/instructions.md` Additional Routing

Proof:

- `grep 'mode: advisory' .claude/skills/scope/SKILL.md` → 1
- `grep 'AskUserQuestion' .claude/skills/scope/SKILL.md` → present
- `grep 'Not-Doing\|not.doing' .claude/skills/scope/SKILL.md` → present (convergence criterion)
- `grep 'review_mode.*analysis' .claude/skills/plan-analyze/SKILL.md` → present
- `grep 'review_runs' .claude/skills/plan-analyze/SKILL.md` → 0
- `grep 'get_review_findings_summary\|reconcile_review_findings' .claude/skills/branch-review/SKILL.md` → present
- `grep 'plan-review\|plan-analyze' mk/handoff.mk` → 2 existing stub targets present

### Slice 3: PostToolUse Dashboard Hook

**Goal**: Wire a PostToolUse hook in `.claude/settings.json` that regenerates CURRENT_TASK.md and DASHBOARD.md after every `record_event`, `review_findings`, and `review_runs` write, closing the auto-refresh gap for these tools.

Changes:

- Create `scripts/hooks/regenerate-task-views.sh`:
  - Calls `agent-handoff-mcp --workspace-root "$CLAUDE_PROJECT_DIR" task` to regenerate CURRENT_TASK.md
  - Calls `agent-handoff-mcp --workspace-root "$CLAUDE_PROJECT_DIR" dashboard` to regenerate DASHBOARD.md
  - Exits 0 regardless — regeneration failure must not block the triggering tool call
  - Suppress output to avoid polluting the tool response
- Update `.claude/settings.json` PostToolUse:
  - Add new hook: `matcher: "mcp__agent-handoff-mcp__record_event|mcp__agent-handoff-mcp__review_findings|mcp__agent-handoff-mcp__review_runs"`, `command: "bash \"$CLAUDE_PROJECT_DIR/scripts/hooks/regenerate-task-views.sh\""`
  - Place after existing PostToolUse hooks (additive, no ordering constraint with `ace-detect.py`)

Proof:

- `grep 'regenerate-task-views' .claude/settings.json` → present in PostToolUse
- Manual: trigger `record_event` write; confirm CURRENT_TASK.md and DASHBOARD.md timestamps update
- `bash scripts/hooks/regenerate-task-views.sh` exits 0 from repo root

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded `SKILL_ANATOMY.template.md`, epic Phase 2 entries for all 6 remaining skills (including `scope`)
- [ ] Read `branch-review-guide.md` and `planning-review-guide.md` to identify executable subset to extract
- [ ] Reviewed `.claude/settings.json` existing PostToolUse hooks to confirm no conflict
- [ ] Confirmed E17-2 is merged before starting (2 command files already exist)

### Checklist for Slice 1: Lifecycle Skills

- [ ] Create `branch-lifecycle` skill with invariant close sequence in convergence criteria
- [ ] Create `handoff-lifecycle` skill with `switch_task` and archive-after-done invariant documented
- [ ] Both command files created and paired
- [ ] `instructions.md` routing rows added for both skills
- [ ] All 10 anatomy sections in each skill
- [ ] Record handoff decision

### Checklist for Slice 2: Review, Planning, and Intake Skills

- [ ] Create `scope` skill — verify `AskUserQuestion` present, Not-Doing convergence criterion present
- [ ] Create `scope` command file and pair with skill in same commit
- [ ] Create `branch-review` skill with pre-triage step (orchestrator tools)
- [ ] Create `planning-review` skill
- [ ] Create `plan-analyze` skill — verify `review_runs` absent, `review_mode="analysis"` present
- [ ] All 4 command files created and paired
- [ ] Verify `make plan-review` and `make plan-analyze` stub targets reference correct skill paths
- [ ] `instructions.md` routing rows added for all 4 skills added in Slice 2 (scope, branch-review, planning-review, plan-analyze); Slice 1 covers the other 2
- [ ] Record handoff decision

### Checklist for Slice 3: PostToolUse Dashboard Hook

- [ ] Create `scripts/hooks/regenerate-task-views.sh` (exits 0, suppresses output)
- [ ] Add PostToolUse hook entry to `.claude/settings.json`
- [ ] Verify hook fires after `record_event` — CURRENT_TASK.md and DASHBOARD.md update
- [ ] Verify hook does not conflict with existing `ace-detect.py` on `review_findings`
- [ ] Record handoff decision

## Review Readiness

- [ ] All 6 skills pass anatomy checklist
- [ ] `scope` skill has `AskUserQuestion` in core process and Not-Doing as a convergence criterion
- [ ] `plan-analyze` explicitly states it does not substitute for `planning-review`
- [ ] PostToolUse hook exits 0 on failure — no tool-call blocking
- [ ] No stale pseudo-tool names in any skill
- [ ] `make lint-task-plans` passes

## Success Criteria

- [ ] All 6 skills exist with correct `mode`, `tdd_gate`, frontmatter, and 10 anatomy sections
- [ ] All 8 `.claude/commands/*.md` files exist (6 new + 2 from E17-2)
- [ ] `make plan-review` and `make plan-analyze` run from repo root without error
- [ ] PostToolUse hook regenerates both views after any `record_event` write
- [ ] E17 Phase 2 exit criteria fully satisfied
