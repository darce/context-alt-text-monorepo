# /handoff-lifecycle

Active skill: `handoff-lifecycle`

Primary entry points:
- `make context`
- `load_session`
- `switch_task`

Execution context: use when starting or resuming a session, switching active tasks, or keeping generated task views aligned after MCP writes.

Loop:
- confirm branch/worktree context
- load the current task state with bounded reads
- record decisions, blockers, and findings in MCP as work happens
- regenerate `CURRENT_TASK.md` after non-atomic writes
- switch tasks safely and archive only after `done`
