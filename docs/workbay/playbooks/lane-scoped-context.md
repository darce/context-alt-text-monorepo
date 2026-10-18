# Lane-Scoped Context

Use this guide when operating the multi-lane orchestrator and worker daemons. The goal is to keep each worker's context as narrow as possible while still making cross-lane coordination durable and understandable.

## Architecture

- MCP is the shared control plane for task state, worker reports, blockers, findings, lane messages, and cross-lane briefs.
- Worktree boundaries provide filesystem isolation between lanes.
- The worker prompt is rebuilt from lane-local MCP state plus lane-local files on every turn. It should not depend on inherited full-thread chat history.
- Visible app windows are optional operator UX only. They are not the isolation boundary.

## Prompt Contract

The default worker prompt envelope should contain only:

- header: task ref, lane id, worktree path, branch, objective
- prompt budget: compact counts/character estimates for each included context slice
- assignment: open orchestrator messages, pending lane actions, open findings, open blockers
- runtime guidance: lane-local workflow, owned paths, tests, preflight notes
- dependency briefs: unresolved `brief:*` lane messages with compact structured payloads
- latest report: the most recent lane report when it helps the next turn
- reporting contract: how to hand off merge-ready or blocked results

The default prompt should exclude:

- unrelated lanes' transcripts
- broad task-wide history unless explicitly escalated
- raw terminal scrollback
- stale review chatter that is already summarized in MCP

## Context Budget Rules

- Prefer the latest structured MCP record over replaying older chat.
- Cap assignment and brief sections so the prompt stays bounded.
- Use the "Prompt Budget" section to decide whether escalation is justified before widening the prompt.
- Escalate to `--include-lane-history` only when recent lane-local decisions or verification history are required to unblock a turn.
- Escalate to `--include-global-context` only when lane-local state plus dependency briefs are insufficient.

## Session Modes

- `fresh_turn`: the default mode. Each worker turn gets a fresh bridge session, maximizing isolation.
- `shared_lane`: reuses the same bridge session only within one lane worker so repeated continuity can help, while still keeping worktree and lane boundaries intact.

Use `shared_lane` selectively for long-running or iterative lanes. It should not be used to share context across different lanes.

## Briefs Versus Guidance

Use a downstream brief when:

- the upstream lane already produced a merge-ready result
- the orchestrator intook that lane successfully
- the downstream lane only needs a concise summary, affected artifacts, and next actions

Escalate to orchestrator guidance instead of issuing a brief when:

- the upstream lane is blocked
- the upstream report is not merge-ready
- the dependency is ambiguous or needs human prioritization
- replaying the dependency naively would risk sending partial or misleading state downstream

## Worker States

`worker_status(...)` should be interpreted from these fields together: `running`, `worker_state`, `attention_required`, and `state_summary`.

Important durable states:

- `idle`: no actionable lane work exists right now
- `waiting_for_orchestrator`: the worker already submitted a handoff and is waiting for intake or redispatch
- `handoff_failed`: the worker finished the implementation/review turn, but the final handoff/report step failed and must be retried without rerunning the assignment
- `paused`: the worker process is stopped and can be resumed
- `stopped`: no worker daemon is currently running for the lane

## Operator Guidance

- In MCP-capable hosts, prefer `orchestrator_start(...)` with the default `worker_start_mode="mcp"` so the orchestrator can auto-start missing actionable workers.
- Use `worker_start_all(..., session_mode=...)` when you want explicit MCP fan-out; it now respects manifest dependency order and skips lanes whose upstream dependencies are still unresolved.
- Use `worker_start_mode="manual"` when the host should keep worker startup in shell space and only use MCP for state visibility and dispatch.
- If a lane reports `handoff_failed`, fix the MCP/handoff problem first and then restart or retry the worker so it can replay the saved result instead of re-executing the lane.
