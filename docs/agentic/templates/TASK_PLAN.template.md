# Task Plan Template

> **Metadata** — fill in when creating a new doc from this template:
>
> - **Date**: [YYYY-MM-DD HH:MM EST]
> - **Author**: {{MODEL_IDENTITY}}
> - **Owning Epic**: [path/to/epic.md]
> - **Epic Short ID**: [must match the owning epic's declared `Epic Short ID`]
> - **Review Coverage Target**: 2 _(optional — min number of review passes before this plan is considered implementation-ready; omit for spike/research tasks)_
>
> **Review coverage note:** Do not embed mutable review counts, finding totals, or run histories in this file.
> Those are volatile; their canonical home is the handoff DB.
> Use `get_review_coverage(task_ref=...)` or `list_review_runs(task_ref=...)` to query live coverage state.
> The `Review Coverage Target` field above carries only your intent (minimum passes); actual coverage is always DB-generated.
>
> Use this template for all implementation plans under `docs/tasks/`.
> Task plans describe executable work for one bounded objective.
> Task plans use **slices**, not phases:
>
> - **Phases** belong to epics and describe coarse-grained temporal delivery across multiple task plans.
> - **Slices** are reviewable implementation increments that can be completed, verified, and logged independently.
>
> Favor slices that each produce behavior plus proof. Avoid scaffold-only slices that add placeholders, skipped tests, or empty abstractions without executable value.
> See `docs/agentic/instructions.md` and `docs/agentic/rules/planning-review-guide.md` for repo-wide planning rules.
> Task-plan title prefixes are derived from the owning epic's declared `Epic Short ID`. Do not invent ad hoc prefixes or copy example ids from unrelated epics.

---

# [EPIC_SHORT_ID]-[LOCAL_TASK_INDEX]. [TASK_TITLE]

## Objective

[What changes when this task is complete. 2-3 sentences max.]

## Problem Statement

[What behavior, contract, or workflow needs to change, and why the current state is insufficient.]

## Constraints

- [Architectural, policy, or runtime constraint]
- [Cross-boundary or ownership constraint]
- [Testing, rollout, or safety constraint]

## Workflow Principles

- [Behavioral or policy rule that guides implementation decisions]
- [Another principle, such as single contract owner or no compatibility shim in greenfield paths]

## Terminology

- **[Term]**: [Definition as used in this task]

## Current State Analysis

- [What currently works]
- [What is broken or drifting]
- [What assumptions/tests/docs are currently misleading]

## Target Outcome

[Narrative description of the intended behavior and the preferred end-state design.]

## Context Loading

> List the minimum authoritative context an agent should load before implementation.
> Prefer small, role-specific surfaces over broad repo ingestion.

- Rules: `[path/to/rule.md]`
- Contracts: `[path/to/contract.md]`
- Handoff/MCP state: [task ref, findings, or decision surfaces to inspect]
- External docs via `ctx7` only if: [exact dependency/runtime reason]

## Contract and Boundary Impact

> Required for any task that touches a cross-service, cross-language, or tool/client boundary.
> Omit only when the task is strictly local and cannot affect a boundary contract.

| Boundary          | Owner                              | Current Contract        | Expected Change    | Compatibility Needed? | Verification          |
| ----------------- | ---------------------------------- | ----------------------- | ------------------ | --------------------- | --------------------- |
| `[boundary-name]` | [backend / proxy / frontend / MCP] | `[path/to/contract.md]` | [Change or `none`] | [yes/no + why]        | [fixture/schema/test] |

## Proposed Solution

[Concise description of the approach. Keep this high-level. Put implementation sequencing in slices below.]

## Files and Surfaces to Change

| Surface                               | File           | Change            |
| ------------------------------------- | -------------- | ----------------- |
| [backend/frontend/docs/tests/tooling] | `path/to/file` | [Specific change] |

## Related Files

| File           | Note                                         |
| -------------- | -------------------------------------------- |
| `path/to/file` | [Relevant context or likely adjacent impact] |

## Verification Strategy

> Define the evidence bundle before implementation.
> Include deterministic tests first; add runtime-parity or manual verification when they are genuinely required.

- Deterministic tests:
  - `[command]`
- Runtime-parity / environment checks:
  - `[command or workflow]`
- Contract/fixture verification:
  - `[command or assertion]`
- Manual verification:
  - `[UI path or operator action]`

## Slice Delivery

### Slice 1: [Title]

**Goal**: [One sentence.]

Changes:

- [Behavioral change]
- [Docs/contract/test change in same slice]

Proof:

- [Command, fixture, or observable outcome]

### Slice 2: [Title]

**Goal**: [One sentence.]

Changes:

- [Behavioral change]
- [Docs/contract/test change in same slice]

Proof:

- [Command, fixture, or observable outcome]

## Lane Decomposition (Multi-Agent)

> Include this section only when the task naturally splits into independent lanes.
> Omit for single-lane work that one agent can complete in a bounded session.

### Lanes

| Lane ID   | Owned Paths | Upstream Dependencies     | Required Tests |
| --------- | ----------- | ------------------------- | -------------- |
| `lane-id` | `path/**`   | [None or lane dependency] | `[command]`    |

### Merge Order

[List lanes in dependency order.]

### Manifest

```bash
make lane-manifest-init TASK=<task-ref> LANE_IDS='<lane-a lane-b>' TASK_PLAN=docs/tasks/<version>/<this-file>.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with the declared lane ownership and verification boundaries.
- **Shell fallback**: Use repo lane helpers or manual worktrees while preserving the same ownership and evidence requirements.

---

# Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed whether external dependency context requires `ctx7`.
- [ ] Recorded boundary ownership and compatibility expectations if any contract is touched.

## Slice 1: [Title]

- [ ] [Implementation step]
- [ ] [Contract/docs/tests updated in same slice]
- [ ] [Verification evidence captured]

## Slice 2: [Title]

- [ ] [Implementation step]
- [ ] [Contract/docs/tests updated in same slice]
- [ ] [Verification evidence captured]

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [ ] Runtime-parity checks are included where tests can mask real behavior.
- [ ] Handoff decision records the change, verification, and any contract implications.

## Stretch Goals

- [ ] [Nice-to-have that will not block completion]

## Success Criteria

- [ ] [Observable outcome that proves the task is done]
- [ ] [Another observable outcome]
