# Planning Pipeline

> Repeatable process: observed problems → reviewed specs → design decisions → task plans.
>
> Related: [planning-review-guide.md](planning-review-guide.md) (review procedures) · [development-workflow.md](development-workflow.md) (implementation workflow).

---

## Pipeline Overview

```
Assessment ──→ Spec ──→ [ADR] ──→ Task Plan ──→ Implementation
  report        spec     ADR      task plan     code + tests
```

Not every stage is required. Small, well-understood changes can skip to a spec or task plan directly. The full pipeline prevents premature implementation of complex or contract-breaking work.

### Planning stays on `main`; implementation branches after approval

**All planning artifacts (assessments, specs, ADRs, task plans) are written and reviewed on `main`.** No feature branch or worktree until the plan is approved and implementation begins.

**Workflow:**

1. **Plan on `main`**: write artifacts, record planning decisions and review findings in MCP.
2. **Review on `main`**: human reviews in normal editor context. Findings via MCP. Plan updated until approved.
3. **Branch when approved**: `make task-start TASK=<id> OBJECTIVE="..."` creates feature branch + worktree + MCP targets.
4. **Implement on the feature branch**: code, tests, slices, pre-merge gate per [development workflow](development-workflow.md).
5. **Merge via the gate**: `handoff_close_check(enforce=True)` passes. Planning artifacts already on `main`; code joins them.

**Use the full pipeline for:** contract/output format changes, tool surface changes, cross-service/cross-package boundary changes, multi-approach architectural decisions, multi-task-plan work.

**Skip stages for:** obvious bug fixes (task plan or direct), small additive features with no contract impact (task plan), docs-only changes (direct).

---

## Stage 1: Assessment

**Artifact:** `*-report.md`, `*-investigation.md`, or `*-audit.md`
**Template:** [ASSESSMENT.template.md](../templates/ASSESSMENT.template.md)
**Location:** Package-local `docs/tech-debt/` or `docs/assessments/`, or monorepo `docs/assessments/`

### Purpose

Inventory what is wrong, trace findings to code, recommend directions — without prescribing solutions.

### Required content

- **Findings** with stable IDs (F1, F2, ...) citing `file:line` in the current codebase
- **Code-verified critique** that challenges the initial findings
- **Priority ordering** (P0-P3) based on impact-to-effort
- **Suggested spec direction** — what should be in scope, deferred, or rejected

### Exit gate → Spec

| Criterion | Required? |
|-----------|-----------|
| Every finding cites current code | Yes |
| Critique section challenges findings honestly | Yes |
| Priority ordering reflects impact-to-effort | Yes |
| Owner has reviewed and resolved disagreements | Recommended |
| Deferred items are named explicitly | Yes |

Findings that fail code verification must be corrected or removed before spec work begins.

---

## Stage 2: Spec

**Artifact:** `*-spec.md`
**Template:** [SPEC.template.md](../templates/SPEC.template.md)
**Location:** Package-local `docs/specs/`

### Purpose

Define concrete, testable changes derived from assessment findings. Each spec item has a stable ID, traceability to findings, before/after code anchored by function name, and machine-verifiable done-when criteria.

### Required content

- **Spec items** with stable IDs (e.g. OC-001) tracing back to assessment findings
- **Before/After** anchored by `file_path::function_name` (line numbers optional, non-durable)
- **Done when** criteria that are testable, not subjective
- **Implementation tiers** grouping items by readiness and dependency
- **Validation snippets** verified against the current package
- **Spec-review gate** section (mandatory in every spec)

### Tier structure

| Tier | Readiness | Action |
|------|-----------|--------|
| **Tier 1** | High certainty, code-verified, independent | Create task plans immediately |
| **Tier 2** | Mechanical but depends on Tier 1 | Create task plans after Tier 1 lands |
| **Tier 3** | Blocked on a design decision | Create an ADR first (Stage 2.5) |

### Exit gate → Task Plan

| Criterion | Required? |
|-----------|-----------|
| At least one planning review pass with findings in MCP | Yes |
| All review findings resolved (fixed, deferred with rationale, or wontfix) | Yes |
| Validation snippets verified against current package | Yes |
| Tier 3 items explicitly marked as ADR-gated | Yes |

**No implementation tasks may be created from a spec until this gate is passed.**

---

## Stage 2.5: ADR (conditional)

**Artifact:** `ADR-NNN-[kebab-case-topic].md`
**Template:** [ADR.template.md](../templates/ADR.template.md)
**Location:** `docs/adrs/`

### When required

Only when a spec item is explicitly design-uncertain — multiple viable approaches with architectural consequences. The spec marks these as "Tier 3 — Blocked on ADR."

ADRs are **not** created before a spec exists, for implementation choices that don't affect contracts/architecture, or as a substitute for assessment work.

### Purpose

Resolve design uncertainty that a spec marks as blocked. Choose one approach, reject alternatives with rationale, set guardrails for implementation.

### Required content

- **Context** referencing the blocked spec item and assessment findings
- **Constraints** from prior spec review that bound the design space
- **Current state inventory** grounded in live code, not memory
- **Decision** with chosen design rules and target outcome
- **Alternatives considered** with concrete rejection reasons
- **Consequences** (positive and negative)
- **Guardrails** for the follow-on implementation task

### Relationship to task plans

The ADR is reviewed first; implementation task plans are derived from the approved ADR. Structured investigation (tool inventory, schema evaluation) belongs in the assessment or spec, not in a wrapper task plan around the ADR.

### Exit gate → Task Plan

| Criterion | Required? |
|-----------|-----------|
| Planning review with findings in MCP | Yes |
| All review findings resolved | Yes |
| Spec updated to reference the ADR and replace unresolved placeholders | Yes |
| Rejected alternatives documented with rationale | Yes |

---

## Stage 3: Task Plan

**Artifact:** `*-task-plan.md`
**Template:** [TASK_PLAN.template.md](../templates/TASK_PLAN.template.md)
**Location:** Package-local `docs/tasks/` or monorepo `docs/tasks/`

### Purpose

Decompose spec items into implementation slices with proof commands, lane ownership, and merge order. Task plans describe how to build and verify, not what to build (that's the spec's job).

### Required content

- **Spec item references** — trace each slice back to a spec item ID
- **Target branch** — the git branch for this task's work (e.g. `feature/ahmcp-2-bounded-rendering`)
- **Slices** with goal, changes, and proof (not phases — see template)
- **Verification strategy** with deterministic test commands
- **Lane decomposition** (optional, for multi-agent work)

### Key principle: reference the spec, don't duplicate it

Reference spec items for code-level detail rather than restating. The Current State Analysis section should add only task-specific context (test-surface observations, lane constraints) not already in the spec.

### Task plan variants

| Variant | Deliverable | Example |
|---------|-------------|---------|
| **Implementation task** | Code + tests + contract docs | AHMCP-2, AHMCP-3 |
| **Design task** | A reviewed ADR | AHMCP-4 |

Design tasks follow the same template but produce investigation and design artifacts instead of code.

### Package-local tasks

For single-package tasks, replace "Owning Epic" with "Project" and "Epic Short ID" with "Task ID". Use the package short name as prefix (e.g. `AHMCP` for `agent-handoff-mcp`).

### Branch-per-task convention

Each task plan declares a **target branch** (`feature/[task-id-slug]`, e.g. `feature/ahmcp-2-bounded-rendering`).

**The branch is not created at plan time.** The plan is committed on `main`. After approval, `make task-start TASK=<id>` creates the branch, links the worktree, and registers `target_branch` on MCP. PRs map 1:1 to task plans.

### Exit gate → Implementation

| Criterion | Required? |
|-----------|-----------|
| Slices trace back to reviewed spec items | Yes |
| Target branch declared in task plan metadata | Recommended |
| Proof commands verified against current test suite | Yes |
| Contract/docs changes included in same slices as behavior changes | Yes |

---

## Stage 4: Implementation

Implementation follows the standard [development workflow](development-workflow.md).

### Task start workflow

The task plan is already on `main` (committed and reviewed). Implementation begins:

0. **Verify the task plan is committed on `main`.** Before running `make task-start`,
   confirm the task plan document is discoverable:
   ```bash
   TASK_LOWER="$(echo "<id>" | tr '[:upper:]' '[:lower:]')"
   git log main --oneline -- "docs/tasks/**/*${TASK_LOWER}*" \
     "packages/*/docs/tasks/**/*${TASK_LOWER}*"
   ```
   If nothing is returned, commit the task plan on `main` first. For ad-hoc work, see [Retroactive task plans](#retroactive-task-plans).
1. **Commit or finish current work** before switching (see safe switching below)
2. Run `make task-start TASK=<id> OBJECTIVE="..."` from the root worktree (creates branch + worktree + MCP target in one shot).
3. `cd` to the linked worktree and run `make context` to verify alignment.
4. Load the task plan (visible from linked worktree via shared git index) and begin slice work.

### Slice workflow

Each completed slice records a `slice_complete_*` decision in MCP with:
- Changes made
- Verification evidence
- Schema/contract changes (if any)
- Open threads

### Task completion workflow

1. Final slice recorded with `close_slice`
2. PR created from task branch to `main`
3. PR maps 1:1 to the task plan — reviewable as a unit

### Retroactive task plans

When work proceeds directly to implementation without planning, a minimal task plan must be retrofitted on `main` before the feature branch merges. Required content:

- **Objective**: one paragraph explaining why the work was done
- **Scope**: packages and files touched
- **Handoff reference**: MCP task ref and slice decision ID(s)

No separate planning review pass required unless the work is large or contract-breaking. Commit on `main` while the feature branch is open.

### Safe branch switching

Always **commit before switching** — never stash. WIP commits are visible in `git log`, referenceable by SHA, and squashable before PR. Stashes are unnamed and invisible to MCP.

**Switching procedure:**
1. `git add -A && git commit -m "wip: <brief description>"`
2. `switch_task(task_ref="<new-task>")` if changing tasks
3. `git checkout <target_branch>` (or `git checkout -b <target_branch> main` if new)

**Returning to a task:**
1. `git checkout <target_branch>`
2. `switch_task(task_ref="<task-ref>")`
3. Resume from last WIP commit

---

## Pipeline Traceability

Every artifact should trace back to its upstream source:

```
Assessment finding F2
  └── Spec item OC-001 (Trace: F2)
        └── Task plan AHMCP-2 / Slice 1 (implements OC-001)
              └── Decision #1234 (references OC-001)
```

---

## Exemplars

Output-contract-v2 pipeline artifacts:

| Stage | Artifact | Path |
|-------|----------|------|
| Assessment | Output state-keeping report | `packages/agent-handoff-mcp/docs/assessments/agent-handoff-mcp-output-state-keeping-report.md` |
| Spec | Output contract v2 spec | `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-output-contract-v2-spec.md` |
| ADR | Typed tool surface consolidation | `docs/adrs/ADR-005-agent-handoff-mcp-typed-tool-surface-consolidation.md` |
| Task plan (Tier 1) | Bounded rendering + mutation output | `packages/agent-handoff-mcp/docs/tasks/AHMCP-2-bounded-current-task-rendering-and-mutation-output-task-plan.md` |
| Task plan (Tier 2) | Response envelope rollout | `packages/agent-handoff-mcp/docs/tasks/AHMCP-3-response-envelope-and-output-contract-v2-rollout-task-plan.md` |
| Task plan (design) | Tool surface consolidation ADR | `packages/agent-handoff-mcp/docs/tasks/AHMCP-4-typed-tool-surface-consolidation-adr-task-plan.md` |
