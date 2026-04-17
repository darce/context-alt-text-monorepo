# Checklist-vs-Evidence Pre-Merge Gate

## Problem

Task-plan markdown checklists and the handoff DB (`handoff.db`) are separate sources of truth. Today they drift silently:

- **Ticked-but-unsatisfied**: a checkbox says a step is done, but no `decision`, `test_result`, or finding resolution backs it. The pre-merge gate (`handoff_close_check`) never sees the checkbox, so the drift escapes review.
- **Unticked-but-satisfied**: work landed, tests passed, findings closed, but the checkbox was never ticked. The plan looks like nothing shipped. Observed repeatedly at E17-7 close: Slice 3 and Slice 4 items were satisfied in the DB but the plan still showed empty boxes.
- **Misscoped items**: items that were never actionable (e.g. E17-7 item 388 referencing a deferred-tool list in `.github/copilot-instructions.md` that is actually runtime-injected by VS Code). The plan should record these as `N/A` with rationale, not leave them unticked forever.

The enforcement rule in `CLAUDE.md` (“Enforce task plan checklist on close”) is prose-only. Prose cannot fail a merge.

## Proposed Gate

Extend `handoff_close_check(enforce=True)` (and `make handoff-close-check`) with a checklist reconciliation pass:

1. Resolve the task's `plan_path` (new field on `handoff_state.active` or inferred from `docs/tasks/**/<task_ref>-*.md`).
2. Parse the markdown checklist. Each `- [ ]` / `- [x]` item becomes a reconciliation row keyed by a stable item id (line anchor or explicit `<!-- id:... -->` trailer).
3. For each item, classify evidence required:
   - `decision` tag — satisfied by a recorded slice-complete or decision whose id matches a configured pattern.
   - `test` tag — satisfied by a `verified_test` row on the current HEAD SHA matching a configured name regex.
   - `finding` tag — satisfied by zero open findings for the tag.
   - `manual` — requires an explicit `N/A: <rationale>` or `done: <decision_id>` comment alongside the checkbox.
4. Emit a `CHECKLIST` section in the close-check payload:
   - `ticked_without_evidence: [...]` — blocks merge.
   - `untickedevidence_present: [...]` — blocks merge (forces the agent to either tick and commit, or explain).
   - `na_without_rationale: [...]` — blocks merge.
5. `enforce=True` fails the gate when any of the three lists is non-empty. `enforce=False` returns advisory only (dev-loop convenience).

## Why This Belongs Outside E17-8

E17-8 (`branch-isolation-edit-guard-hardening`) is a filesystem-edge hook epic driven by `harness-protocol.yaml`. Its enforcement runs as `PreToolUse` on Edit/Write. Checklist-vs-evidence runs at close-check time against DB + markdown state. Different subsystem, different failure surface, different tests. Bundling them dilutes both.

## Suggested Task

`E17-9: Checklist-vs-Evidence Pre-Merge Gate`. Scope: spec the item-id anchor format, implement the parser, extend `handoff_close_check`, add regression tests, document the new tag syntax in the task-plan template.

## Related Tech Debt

- [guard-task-plan-findings-status-heuristic.md](guard-task-plan-findings-status-heuristic.md) — adjacent plan-vs-DB drift (findings, not checkboxes).
- [working-tree-integrity-and-coordination-assessment.md](working-tree-integrity-and-coordination-assessment.md) — broader worktree/plan hygiene.

## Origin

Surfaced during E17-7 close when the user noted Slice 4 checkbox staleness and required that task status be enforced mechanically, not suggested in prose.
