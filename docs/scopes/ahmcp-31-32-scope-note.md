# AHMCP-31 and AHMCP-32 Scope Note

## Context

`AHMCP-31` and `AHMCP-32` are referenced as package-level sub-tasks from `E17-4`, but they did not previously have standalone task-plan artifacts in `packages/agent-handoff-mcp/docs/tasks/`.

This note captures the `/scope` intake outcome before formal task-plan drafting.

## MVP Scope

### AHMCP-31

- Standalone task plan and branch; not combined with `AHMCP-32`
- Package-only MVP inside `agent-handoff-mcp`
- Add `touched_files` schema/tool surface and `load_session` integration
- Include package-local test coverage

### AHMCP-32

- Standalone task plan and branch; not combined with `AHMCP-31`
- Package-only MVP inside `agent-handoff-mcp`
- Add optional branch-enforcement support and package-local tests
- Keep enforcement env-gated rather than default-on

## Assumptions

- E17-4 remains the parent workflow-integrity task that owns repo-level follow-up wiring
- Package tests are the required verification surface for both tasks
- Formal task plans will be created under `packages/agent-handoff-mcp/docs/tasks/`

## Success Criteria

- Each task gets its own task-plan file
- Each task stays package-local in implementation scope
- Package tests pass for the changed behavior

## Not Doing

### AHMCP-31

- No historical `touched_files` backfill from old slice decisions
- No delete-hook coverage yet
- No repo hook wiring in `.claude/settings.json` or `.github/hooks/terminal-guard.json`

### AHMCP-32

- No default-on branch enforcement
- No shell-export or broader repo rollout work in the same task

## Recorded Intake Decisions

- `1725`: `scope_intake_AHMCP-31_package_only_mvp`
- `1726`: `scope_intake_AHMCP-32_package_only_mvp`