# /branch-lifecycle

Active skill: `branch-lifecycle`

Makefile entry points:
- start: `make task-start TASK=<task-ref> OBJECTIVE="..."`
- review gate: `make review-ready` then `make handoff-close-check`
- finish: `make task-finish TASK=<task-ref>`

Execution context: use when moving a task through branch start, review readiness, close-check, merge, and teardown.

Loop:
- create or enter the task branch/worktree
- verify alignment with `make context`
- advance slices through `tdd` and `incremental-implementation`
- clear review-ready blockers and pass `handoff-close-check`
- finish with the invariant close sequence and task teardown
