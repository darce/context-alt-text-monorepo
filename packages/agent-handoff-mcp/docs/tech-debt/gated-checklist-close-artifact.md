# Gated Checklist as a Close Artifact

## Problem

Task-plan checklists on `main` are hand-edited, so they drift from reality in three directions at once:

- Boxes stay empty long after the slice shipped, merged, and was verified (observed on E15-1, E15-1b, E15-2b — all merged months ago, all boxes still `[ ]`; required a standalone MAINT sync on 2026-04-20 to flip 35 boxes).
- Boxes get ticked optimistically mid-slice and never unticked when scope drops.
- Operators watching `main` have no way to tell "plan merged, work shipped" from "plan merged, work never started" without spelunking slice decisions.

[checklist-vs-evidence-gate.md](checklist-vs-evidence-gate.md) proposes a *reconciliation gate*: markdown stays the source of truth, `handoff_close_check` blocks merges when boxes disagree with the DB. That catches drift at close time, but it still relies on a human (or agent) to re-tick boxes at the end of every feature branch and commit the flip. Every forgotten flip is another MAINT sync later.

## Proposed Change: Regenerated Checklist Section

Flip the source-of-truth relationship. The authoritative state is the handoff DB; the markdown checklist is a *rendered projection* of it, regenerated on every `make task-finish`.

### Shape

Each checklist item in the task-plan template carries a stable id and an evidence tag:

```markdown
- [ ] <!-- id: E15-1-S1-01 evidence: test:test_rate_limiting --> Failing tests written first (`test_rate_limiting.py`)
- [ ] <!-- id: E15-1-S1-02 evidence: decision:slice_complete_rate_limit --> `enforce_rate_limit` dependency implemented in `deps/rate_limit.py`
- [ ] <!-- id: E15-1-S1-03 evidence: manual --> Security contract updated
```

`close_slice` is extended with a `checklist_items: list[str]` field that records which ids the slice satisfied. The decision row persists that list alongside `changed_files`.

### Generator

A new renderer `render_handoff(kind='task_checklist', task_ref=...)` walks the plan, resolves each item id against the DB:

- `evidence: test:<name>` — satisfied if a `verified_test` row matches `<name>` and is tied to an ancestor of HEAD.
- `evidence: decision:<id-prefix>` — satisfied if a `decision` row with that prefix exists on the task.
- `evidence: finding:<tag>` — satisfied if zero `open` findings match the tag.
- `evidence: manual` — satisfied only by an explicit `checklist_items=[...]` entry on a slice-complete decision.

The renderer rewrites the `## Consolidated Checklist` / `## Review Readiness` / `## Success Criteria` sections, flipping `[ ]` ↔ `[x]` and appending a `<!-- verified-at: <sha> at <timestamp> -->` marker.

### Integration with `make task-finish`

The existing teardown order becomes:

1. `handoff_close_check(enforce=True)` — already runs.
2. **New**: `render_handoff(kind='task_checklist', task_ref=...)` on the feature branch worktree.
3. If the renderer changed the plan, auto-commit with message `docs(<task>): regenerate checklist from handoff state at <sha>`.
4. Merge feature → main (the regenerated checklist rides the merge, so `main` reflects reality atomically with the code).
5. Worktree teardown.

Operators on `main` now read a checklist that is guaranteed-consistent with the handoff DB at the SHA the work merged. A ticked box is backed by a decision or verified-test row an auditor can retrieve; an unticked box after a merge is a real scope gap, not a forgotten flip.

## Relationship to the Reconciliation Gate

The two proposals stack:

| Layer | Source of truth | Enforcement point | What it catches |
|---|---|---|---|
| Reconciliation gate ([checklist-vs-evidence-gate.md](checklist-vs-evidence-gate.md)) | Markdown | Close-check | Ticked-without-evidence, unticked-with-evidence, N/A-without-rationale |
| Close artifact (this doc) | Handoff DB | `make task-finish` | Any drift at all — because the markdown is regenerated, drift is not representable |

Ship the reconciliation gate first (it is strictly a validator, no schema changes, no template migration). Then — once every active task plan carries the id/evidence comments — promote to the close-artifact model and delete the reconciliation gate's "unticked-with-evidence" branch, since the renderer makes it impossible.

## Answers the Operator-Visibility Question

The current tension is "task plans on `main` must stay out of code-edit hooks, but checkbox state is derived from gates that only run on the feature branch." The close-artifact model resolves it cleanly:

- The feature branch owns the regeneration (runs inside its own worktree under branch isolation).
- The merge carries the regenerated markdown into `main` as part of the normal close commit.
- `main` never needs to be edited out-of-band for checkbox state.
- Operators on `main` watch the plan; the ticks mean *verified at this SHA*, not *someone clicked a checkbox*.

This also eliminates the "checklist sync MAINT task" pattern that emerged on 2026-04-20, where stale `- [ ]` boxes from merged tasks had to be flipped in a separate branch just to make `main` readable.

## Suggested Task

`AHMCP-N: Gated Checklist Close Artifact`. Depends on the reconciliation-gate task (to define the id/evidence tag syntax). Scope: extend `close_slice` with `checklist_items`, implement `render_handoff(kind='task_checklist')`, wire the regenerate-and-commit step into `make task-finish`, update the task-plan template, migrate one in-flight task plan as a canary.

## Related Tech Debt

- [checklist-vs-evidence-gate.md](checklist-vs-evidence-gate.md) — upstream dependency; validator-only variant of this proposal.
- [guard-task-plan-findings-status-heuristic.md](guard-task-plan-findings-status-heuristic.md) — adjacent plan-vs-DB drift for findings, already solved by the `PreToolUse` hook; the same philosophy (DB authoritative, markdown projection) would apply there if the hook ever needs to render *into* plans rather than just block writes.
- [demote-current-task-rendering.md](demote-current-task-rendering.md) — companion renderer scope.
