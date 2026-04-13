---
name: tdd
description: Enforce RED -> GREEN -> REFACTOR with a recorded failing-test gate before any implementation edit.
mode: execution
context_budget: 90
makefile_target: slice-start
mcp_tools:
  - record_event
  - get_verified_tests
  - search_handoff
tdd_gate: true
disable-model-invocation: false
---

# TDD

## Overview

Use this skill at the start of any implementation slice. It owns the RED -> GREEN -> REFACTOR loop and is not complete until the failing-test gate and the passing-test evidence are both recorded in handoff.

## Trigger

Use this skill when:

- starting a new implementation slice
- `make slice-start` is the next repo workflow step
- the work needs a new test or a changed test before production edits

Do not use it for planning-only, review-only, or handoff-only work.

## Goal

Record a failing test before any implementation edit, make the smallest change that turns the test green, then leave the slice ready for refactor or `make slice-commit`.

## Canonical Policy

- [../../../docs/agentic/rules/development-workflow.md](../../../docs/agentic/rules/development-workflow.md)
- [../../../docs/agentic/lifecycle-map.md](../../../docs/agentic/lifecycle-map.md)
- [../../../docs/agentic/rules/testing-principles.md](../../../docs/agentic/rules/testing-principles.md)

This skill owns ordering, gate discipline, and required handoff evidence. Stack-specific test commands still come from the linked testing guides.

## Core Process

1. Pick the behavior to change. If the intended slice is unclear, use `search_handoff` to find the latest slice summaries or task-plan language.
2. Write or update the test first. The first runnable artifact must be a failing check for the behavior under change.
3. Run the test and confirm it fails for the intended reason, not for syntax, import, or environment noise.
4. Record the RED gate with `make slice-start TASK=<task-ref> TEST_CMD="<test command>"`. This writes `record_event(test_result, passed=false)` before implementation begins.
5. Make the smallest production change that can satisfy the failing test. Keep the diff on one behavior path.
6. Re-run the targeted test until it passes. Run adjacent checks if the slice touches nearby contracts.
7. Record the GREEN evidence with `record_event(event_kind="test_result", task_ref=..., command=..., passed=true, result=...)`.
8. Refactor only while the test stays green. If refactor creates a new behavior change, stop and start a new slice instead.
9. Hand off to `make slice-commit` when the slice is green, bounded, and reviewable.

## Common Rationalizations

- "I'll add the test after I know the code works."
- "This is just config or glue, so the gate does not matter."
- "The test is obvious; I can skip `make slice-start` once."

## Red Flags

- A production file is edited before the failing test is recorded.
- The first failure is a syntax or import crash unrelated to the intended behavior.
- No passing `test_result` evidence exists after the implementation turns green.
- The diff starts expanding beyond one behavior path.

## Recovery

- If `make slice-start` fails, record the failing test directly in handoff, fix the workflow issue, and do not proceed with unlogged implementation.
- If the test failure is noisy, reduce scope until one clear failing check isolates the behavior.
- If MCP is unavailable, stop implementation and record/report a blocker when access returns.
- If the slice grows beyond one behavior path, keep the current test green, commit or stash safely, then open a new slice.

## Convergence Criteria

- A failing test was recorded before implementation edits.
- A passing `test_result` exists for the behavior the slice changed.
- The implementation diff stays bounded to one behavior path.
- The slice is ready for `make slice-commit` or a clearly separated follow-on slice.

## See Also

- [../incremental-implementation/SKILL.md](../incremental-implementation/SKILL.md)
- [../../../docs/agentic/lifecycle-map.md](../../../docs/agentic/lifecycle-map.md)
- [../../../docs/agentic/rules/development-workflow.md](../../../docs/agentic/rules/development-workflow.md)
