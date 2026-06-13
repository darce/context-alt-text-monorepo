# /branch-lifecycle

Active skill: `branch-lifecycle`

Makefile entry point: `make task-start TASK=<task-ref> OBJECTIVE="..."`

Execution context: use when moving a plan-backed task through branch start, review readiness, close-check, merge, and teardown.

Loop:
- accept the reviewed task plan with `make plan-accept` before task-start
- create or enter the task branch/worktree
- verify alignment with `make context`
- advance slices through `tdd` and `incremental-implementation`
- clear review-ready blockers and pass handoff-close-check
- finish with the invariant close sequence and task teardown
