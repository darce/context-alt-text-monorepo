# CURRENT_TASK.json Template

> Copy this template to the **monorepo root** as `CURRENT_TASK.json` when starting a multi-session task.
> Location: `/context-alt-text-monorepo/CURRENT_TASK.json`

---

# Current Task: [TASK_TITLE]

**Started**: [DATE]
**Task Doc**: [Link to docs/tasks/X.Y/task-plan.md if applicable]
**Status**: [IN_PROGRESS | COMPLETE | BLOCKED]

## Objective

[1-2 sentence description of what we're trying to accomplish]

## Context

[Brief background that a new agent session needs to understand the task]

- Why this matters: [user impact or technical debt being addressed]
- Related issue/PR: [link if applicable]

## Latest Decision

[Most recent decision summary and why it mattered]

## Progress

### Completed

- [x] [Completed item with brief note]
- [x] [Completed item with brief note]

### In Progress

- [ ] [Current work item] ← **ACTIVE**

### Remaining

- [ ] [Future item]
- [ ] [Future item]

## Key Files

| File | Purpose |
|------|---------|
| `path/to/file.py` | [What this file does in context of the task] |
| `path/to/file.ts` | [What this file does in context of the task] |

## Technical Notes

[Any implementation details, decisions made, or gotchas discovered during work]

## Verification Commands

```bash
# How to verify the current state
cd apps/prototype-description-service
pytest tests/unit/test_relevant_file.py -v

# Type checking
PYENV_VERSION=description-service mypy .
```

## Next Agent Instructions

[Specific instructions for the next session, e.g.:]

1. Read [specific file] lines X-Y to understand the current implementation
2. Continue from [specific function/method]
3. Run [specific test] to verify before proceeding

---

## Session Log

### [DATE] - Session N

- What was done
- What was discovered
- What blocked progress (if anything)
