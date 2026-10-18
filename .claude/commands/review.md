# /review

Active skill: `review`

Makefile entry point: `make review-dispatch`

Execution context: use when asked to review a branch diff, task plan, PR, epic, or ADR. Activates on: "review", "audit", "flag gaps/bugs", "propose improvements".

Loop:
- determine review mode (branch or planning) from target paths
- load handoff state and prior review runs
- run the full checklist from the selected guide — never skip sections
- record every finding in MCP before mentioning it in chat
- record verdict decision and review-run entry
- regenerate the operator view with `render_handoff(kind='dashboard')`; call `render_handoff(kind='current_task')` only when a task-scoped snapshot is explicitly needed
