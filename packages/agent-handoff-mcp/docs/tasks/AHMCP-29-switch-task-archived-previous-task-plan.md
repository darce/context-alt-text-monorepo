# AHMCP-29. switch_task archived_previous Response Flag

> **Metadata**:
>
> - **Date**: 2026-04-14
> - **Author**: Codex (retroactive)
> - **Project**: agent-handoff-mcp
> - **Task ID**: AHMCP-29
> - **Target Branch**: `feature/ahmcp-29`
> - **Merged**: `41f288d9` on `main`

---

## Objective

Expose whether `switch_task` archived an outgoing active task so callers like `task-start.sh` can report task-transition side effects without re-reading the archive ledger.

## Problem Statement

`switch_task` already performed the right transition semantics when a new task replaced an active one, but callers could not tell from the response whether an outgoing task was archived during the switch. That forced lifecycle scripts to infer side effects indirectly and made startup/transition messaging less precise.

## Constraints

- Preserve `switch_task` as the single owner of task-transition/archive behavior.
- Keep the response additive and backward-compatible for existing callers.
- No schema change should be required.

## Proposed Solution

- Extend the `switch_task` response envelope with an `archived_previous` boolean.
- Set the flag to `true` when the call archived an outgoing active task during the switch and `false` otherwise.
- Update lifecycle coverage so `task-start` callers can assert the flag instead of inferring archive behavior indirectly.

## Files Changed

| File | Change |
|---|---|
| `src/agent_handoff_mcp/core.py` | Thread `archived_previous` through the `switch_task` response |
| `src/agent_handoff_mcp/api.py` | Preserve the additive `switch_task` response shape |
| `scripts/_task_start_inline.py` | Consume/report `archived_previous` when switching tasks |
| `tests/test_lifecycle_scripts.py` | Cover the new response flag in task-start flows |

## Verification

- `cd packages/agent-handoff-mcp && make test-handoff`
- `switch_task(task_ref="new-task")` returns `archived_previous=true` when replacing an active task and `false` when there was no outgoing active task to archive
