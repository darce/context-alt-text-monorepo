---
name: incremental-implementation
description: Break implementation into bounded vertical slices that each start with a recorded failing test and end with a reviewable commit.
mode: execution
context_budget: 100
makefile_target: slice-commit
mcp_tools:
  - record_event
  - search_handoff
  - generate_current_task_md
  - plan_cursor
tdd_gate: true
disable-model-invocation: false
---

# Incremental Implementation

## Overview

Use this skill when turning a task plan into code or docs slices. It enforces vertical, test-backed increments so each slice closes one user-visible path instead of spreading unfinished work across layers.

## Trigger

Use this skill when:

- starting feature implementation from a reviewed task plan
- choosing the next slice under an active task
- deciding whether a proposed diff is one slice or several

Do not use it for planning review, branch review, or pure handoff bookkeeping.

## Goal

Advance one bounded plan item with a complete end-to-end slice that starts with a failing test, stays scoped to one behavior path, and ends ready for `make slice-commit`.

## Canonical Policy

- [../../../docs/agentic/rules/development-workflow.md](../../../docs/agentic/rules/development-workflow.md)
- [../../../docs/agentic/lifecycle-map.md](../../../docs/agentic/lifecycle-map.md)
- [../../../docs/tasks/17.0/E17-2-tdd-and-incremental-implementation-skills-task-plan.md](../../../docs/tasks/17.0/E17-2-tdd-and-incremental-implementation-skills-task-plan.md)

This skill owns slice sizing, vertical-path discipline, and plan-item advancement. The `tdd` skill owns the RED -> GREEN gate inside the slice.

## Core Process

1. Load the active task plan and identify the next slice worth shipping. If prior slices are unclear, use `search_handoff` to find the latest slice summaries first.
2. Advance the slice cursor with `plan_cursor(operation="upsert", task_ref=..., plan_item_id=..., require_clean_slice=true)`. The `require_clean_slice` guard means the next slice does not start while open findings still exist on the prior one.
3. Define the smallest end-to-end path that delivers user value. Prefer one behavior path such as one field, one endpoint, one UI state, or one docs workflow step.
4. Open the slice with the `tdd` skill: write the failing test first, run `make slice-start TASK=<task-ref> TEST_CMD="<command>"`, then make the smallest change that turns the check green.
5. Scaffold only the signatures the test needs. Do not pre-build adjacent layers "for later."
6. Implement the minimum to make the path work end to end. Keep each layer thin enough that the test still explains the whole diff.
7. Re-run the targeted checks and record passing evidence with `record_event(event_kind="test_result", passed=true, ...)`.
8. Check the diff boundary. If the change now spans multiple independent user paths, split it before commit.
9. Close the slice with `make slice-commit TASK=<task-ref> MSG="..."`, then refresh task context if more slices remain.

## Common Rationalizations

- "I'll finish the backend first and wire the rest in later."
- "These are only types or scaffolds, so a test-backed slice can wait."
- "The slice is almost done; I'll split it after the big diff lands."

## Red Flags

- The diff touches multiple unrelated user paths.
- `plan_cursor(... require_clean_slice=true)` is rejected because the previous slice still has open findings.
- The first implementation edits happen before the failing test is recorded.
- The slice ends with half-wired layers that cannot be verified together.

## Recovery

- If the next slice is still fuzzy, shrink it until one test can describe the full path.
- If a previous slice still has open findings, resolve or defer them before advancing the cursor.
- If the diff has already sprawled horizontally, stop adding files, separate the current user path, and defer the rest into the next slice.
- If `make slice-commit` fails after the commit lands, record a valid `slice_complete_*` decision for that commit before moving on.

## Convergence Criteria

- The current slice maps to one plan item and one behavior path.
- The failing test was recorded before implementation edits.
- Passing test evidence exists for the slice outcome.
- The diff is small enough to review as one vertical slice.
- The slice is committed and reflected in task context before the next slice begins.

## See Also

- [../tdd/SKILL.md](../tdd/SKILL.md)
- [../../../docs/agentic/lifecycle-map.md](../../../docs/agentic/lifecycle-map.md)
- [../../../docs/agentic/rules/development-workflow.md](../../../docs/agentic/rules/development-workflow.md)
