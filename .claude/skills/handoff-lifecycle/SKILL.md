---
name: handoff-lifecycle
scope: harness
description: Use when entering, resuming, switching, or ending a task session. Triggers
  on `make context`, `load_session`, and task-to-task transitions.
mode: execution
context_budget: 100
makefile_target: null
mcp_tools:
- load_session
- get_handoff_state
- record_event
- set_handoff_state
- render_handoff
- switch_task
tdd_gate: false
disable-model-invocation: false
---

# Handoff Lifecycle

## Overview

Use this skill for the session-scoped handoff loop: enter the right task, load only the needed state, keep generated task views current after writes, and switch tasks safely when the session focus changes.

## Trigger

Use this skill when:

- starting or resuming a work session
- verifying task / branch alignment with `make context`
- switching from one task to another mid-session
- ending a session after recording decisions, blockers, or findings

Do not use it for branch review execution or the TDD loop inside a slice.

## Goal

Keep MCP task state, shell context, and generated task views aligned throughout the session so another agent can resume work without reconstructing intent from chat.

## Canonical Policy

- [../../../docs/agentic/instructions.md](../../../docs/agentic/instructions.md)
- [../../../docs/agentic/rules/development-workflow.md](../../../docs/agentic/rules/development-workflow.md)
- [../../../docs/agentic/lifecycle-map.md](../../../docs/agentic/lifecycle-map.md)

This skill owns hot-state loading, safe task switching, and the rule that generated task views are regenerated rather than edited by hand.

## Core Process

1. At session start, run `make context` and load hot state with `load_session`. Use bounded reads unless you truly need full task history.
2. Confirm the active task, branch, and worktree align. If they do not, switch shells or fix task state before editing.
3. During work, record decisions, blockers, tests, and findings through MCP writes instead of chat-only notes.
4. After each state-changing write that does not already regenerate views server-side, run `render_handoff(kind='dashboard')` so the operator-facing cross-task view stays current. Use `render_handoff(kind='current_task')` only as an on-demand fallback when a task-scoped machine snapshot is specifically needed. Treat generated task views as outputs, never as hand-edited logs.
5. When changing task focus mid-session, use `switch_task` as the safe transition path so the outgoing task is archived before the new task becomes active.
6. Only archive completed work after `set_handoff_state(status="done", status_only=True)`. Never archive a task that is still `in_progress`.
7. End the session with task state aligned to reality: active task correct, blockers explicit, generated task view current.
8. In the user-facing close-out, print a compact MCP write receipt with row ids from the tool responses. Use this shape: `MCP writes: <summary>; test_result id <id>; decision id <id> (<decision_key>); review_run id <id>. DASHBOARD.txt refreshed. Handoff updated: decision <decision_key> recorded.` Omit clauses that do not apply, but do not replace ids with a prose-only "recorded" claim.

## Common Rationalizations

| Rationalization | Why it fails | Required action |
|---|---|---|
| "I already know the state, so I don't need `load_session`." | Session memory drifts and other agents may have written new findings or blockers. Skipping the read turns shared state into guesswork. | Load the current task state before acting on assumptions. |
| "I'll archive while the task is still in progress so I can clean things up later." | Archiving an active task lies to the dashboard and breaks safe task switching. Downstream agents will assume the task is closed or restorable from the wrong snapshot. | Leave it active until `set_handoff_state(status="done", status_only=True)` is true, then archive. |
| "I'll just update `CURRENT_TASK.json` directly." | Generated task views drift immediately from MCP when hand-edited and disappear on the next regeneration. | Regenerate the appropriate view from MCP instead of editing it. |

## Red Flags

Each flag is a re-entry trigger. Stop and re-enter at the step shown.

| Flag | Re-entry point |
|---|---|
| `make context` shows branch or worktree drift | Step 1: realign shell context before continuing. |
| Task write made, but `DASHBOARD.txt` still reflects old state | Step 4: regenerate the dashboard view. |
| Session switches tasks by calling `set_handoff_state` directly over another active task | Step 5: switch with `switch_task` so the outgoing task archives safely. |
| Archive requested while status is still `in_progress` | Step 6: set status truthfully first, then archive only when done. |

## Recovery

- If session context is stale, rerun `make context` and `load_session` instead of guessing what changed.
- If a write landed on the wrong task, stop and repair task state before continuing with more writes.
- If `DASHBOARD.txt` or `CURRENT_TASK.json` is stale, regenerate it; do not patch the markdown manually.
- If a task was switched unsafely, restore the intended active task and archive state through `switch_task` / `set_handoff_state(status_only=True)` in canonical order.

## Convergence Criteria

- Session started from aligned task, branch, and worktree context.
- Relevant MCP writes are recorded for work performed in the session.
- The response names the MCP row ids written during the session.
- `render_handoff(kind='dashboard')` was run after non-atomic state-changing writes, with `render_handoff(kind='current_task')` reserved for on-demand task snapshots.
- Task switches happened through `switch_task`, not by overwriting the active row ad hoc.
- Archive operations only happened after `set_handoff_state(status="done", status_only=True)`.

## See Also

- [../branch-lifecycle/SKILL.md](../branch-lifecycle/SKILL.md)
- [../../../docs/agentic/lifecycle-map.md](../../../docs/agentic/lifecycle-map.md)
- [../../../docs/agentic/instructions.md](../../../docs/agentic/instructions.md)
