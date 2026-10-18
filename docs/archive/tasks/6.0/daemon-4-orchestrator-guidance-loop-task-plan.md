# Daemon 4: Orchestrator Guidance Loop

## Problem Statement

Worker daemons can now detect blocked or already-resolved assignments, emit `needs_guidance` handoffs, and go dormant while waiting for an orchestrator response. The missing piece is an unattended orchestrator loop that consumes those guidance handoffs, records the decision, responds in MCP, wakes the correct lane, and exits cleanly when the task is complete or when an unrecoverable orchestration error occurs.

## Workflow Principles

- **Workers ask, orchestrator answers.** A `worker_to_orchestrator` guidance handoff must always be consumed by the orchestrator, never left as open noise.
- **MCP remains the source of truth.** Guidance handling, dispatch decisions, lane status changes, and completion/error state must all be reflected in handoff state rather than inferred from local logs.
- **One active assignment per lane.** The orchestrator should close or supersede stale dispatches before issuing a new one so workers see a single actionable message.
- **Closed-loop automation with safe exits.** The daemon should keep polling while work is still moving, exit successfully when the task is actually ready to close, and exit non-zero when orchestration cannot proceed without operator intervention.
- **Policy first, heuristics second.** The daemon may classify common guidance cases automatically, but it should escalate ambiguous cases instead of inventing work.

## Terminology

- **Guidance handoff**: An open `worker_to_orchestrator` lane message created when a worker reports `needs_guidance`.
- **Waiting lane**: A worker lane that has handed control back and should remain dormant until the orchestrator responds.
- **Guidance resolver**: The orchestrator-side logic that classifies an open guidance handoff and decides whether to close, redispatch, or escalate it.
- **Terminal success**: The point where the MCP `handoff-close-check` command returns `ready_to_close=true` after orchestration work for the current cycle is complete.
- **Terminal error**: An unrecoverable daemon state such as repeated MCP failures, repeated guidance loops with no state change, or intake/dispatch failure that requires operator attention.

## Current State Analysis

- `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py` already distinguishes `actionable`, `idle`, and `waiting` lane states and logs `dormant_entered` when the lane is waiting for orchestrator input.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py` already suppresses worker action when a newer open `worker_to_orchestrator` message exists for the lane.
- `mk/handoff.mk` already exposes `make handoff-inbox`, which shows open worker handoff messages and the latest blocked or merge-ready worker reports.
- `scripts/mcp/orchestrator_daemon.py` already handles dispatch, merge-ready polling, lane intake, downstream refresh, and cross-lane verification.
- `scripts/mcp/orchestrator_daemon.py` does **not** yet poll and resolve open worker guidance handoffs, so workers can go dormant indefinitely even when the orchestrator could respond automatically.
- Lane state can become misleading when a stale dispatch remains open after the worker proves the assignment is already resolved or blocked for environmental reasons.
- There is no terminal loop policy in the orchestrator daemon yet: it does not know when to exit because the task is done, and it does not surface persistent guidance-loop failures as a daemon error.

## Proposed Solution

Extend `scripts/mcp/orchestrator_daemon.py` with a dedicated guidance-resolution phase that runs every cycle after generic open-work dispatch and before merge-ready intake. The exact cycle order should be:

1. run `_run_handoff_dispatch()` to stamp newly opened findings/blockers/actions to lanes
2. resolve open worker guidance handoffs, including closing stale dispatches for any lane being actively resolved
3. poll merge-ready lanes
4. intake ready lanes in manifest merge order
5. refresh downstream lanes and run cross-lane verification
6. run `handoff-close-check`
7. either sleep, exit successfully, or exit with a terminal error

Daemon-5 later extends this cycle with a task-plan dispatch step between guidance resolution and merge-ready polling. This daemon-4 plan still owns the guidance-resolution semantics; task-plan-derived dispatch is a later layer.

The daemon should poll open `worker_to_orchestrator` messages and recent blocked reports, classify each lane’s request, and then take exactly one of four actions:

1. **Close stale work** when the worker demonstrates the assignment is already satisfied.
2. **Redispatch the next slice** when the current task is resolved but the lane still has a clearly defined next assignment.
3. **Escalate environment/operator blockers** when progress requires a writable shell, dependency installation, or a human decision.
4. **Mark the task complete and exit** when `handoff-close-check` succeeds after dispatch/intake/guidance processing.

`Redispatch the next slice` does **not** imply the current lane manifest can auto-derive ordered sub-slices today. In the first implementation, redispatch should use one of these sources, in order:

1. an already-open pending action explicitly stamped to the lane
2. an explicit orchestrator policy helper in `orchestrator_daemon.py` for the active task
3. the lane’s current objective/notes as a fallback

Manifest-driven per-lane sub-slice ordering is a Stretch Goal, not an assumption of the initial daemon implementation.

The daemon should record each guidance decision in MCP, update the lane status, close consumed guidance messages, and ensure the lane prompt wakes only when a new orchestrator message exists. It should also track repeated no-progress cycles and stop with a clear non-zero error if the same guidance item is reprocessed without any state change.

## Patterns to Follow

### Guidance Resolution Loop

```python
def _resolve_guidance_cycle(...) -> dict[str, Any]:
    open_messages = _list_open_worker_guidance(...)
    results = []
    for message in open_messages:
        classification = classify_guidance(message, latest_report, lane_state, task_manifest)
        result = apply_guidance_resolution(classification, message)
        record_decision(result)
        results.append(result)
    return {"resolved": results}
```

### MCP/Helper Mapping

| Pseudocode / Responsibility    | Existing API vs New Helper            | Concrete Implementation Surface                                                                                                                                                                     |
| ------------------------------ | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_list_open_worker_guidance()` | New helper                            | Wrap `agent_handoff_mcp lane-message-list --status open`, then filter in-process to `direction=="worker_to_orchestrator"` because the MCP API does not currently expose a direction query parameter |
| `classify_guidance()`          | New helper                            | Pure Python function inside `scripts/mcp/orchestrator_daemon.py`                                                                                                                                    |
| `close_message()`              | Existing MCP CLI/API                  | `agent_handoff_mcp lane-message-update --message-id <id> --status closed`                                                                                                                           |
| `close_stale_dispatches()`     | New helper using existing MCP CLI/API | List open `orchestrator_to_worker` messages for a lane and close the superseded ones                                                                                                                |
| `send_lane_message()`          | Existing MCP CLI/API                  | `agent_handoff_mcp lane-message --direction orchestrator_to_worker ...`                                                                                                                             |
| `set_lane_status()`            | Existing MCP CLI/API                  | `agent_handoff_mcp lane-upsert --status <status> --notes <notes> ...`                                                                                                                               |
| `record_decision()`            | Existing MCP CLI/API                  | `agent_handoff_mcp decision ...`                                                                                                                                                                    |
| `run_handoff_close_check()`    | Existing MCP CLI/API                  | `agent_handoff_mcp handoff-close-check --task-ref <task>`                                                                                                                                           |
| `resolve_next_assignment()`    | New helper                            | Read lane-stamped pending actions first, then task-specific policy helper, then lane objective fallback                                                                                             |

### Safe Lane Wake-Up

```python
if resolution.kind == "redispatch":
    close_message(worker_guidance_id)
    close_stale_dispatches(lane_id)
    send_lane_message(lane_id, direction="orchestrator_to_worker", ...)
    set_lane_status(lane_id, "active")
elif resolution.kind == "review":
    close_message(worker_guidance_id)
    set_lane_status(lane_id, "review")
```

### Terminal Exit Policy

```python
def _should_exit_successfully(...) -> bool:
    close_check = run_handoff_close_check(...)
    return close_check["ready_to_close"] is True

def _should_exit_with_error(loop_state) -> bool:
    return (
        loop_state.repeated_guidance_without_progress
        or loop_state.repeated_mcp_failures
        or loop_state.repeated_dispatch_failures
    )
```

### Close-Check Invocation

```python
def run_handoff_close_check(orchestrator_root: Path, task_ref: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "agent_handoff_mcp",
        "--workspace-root", str(orchestrator_root),
        "--state-dir", str(orchestrator_root / ".task-state"),
        "--current-task-path", str(orchestrator_root / "CURRENT_TASK.md"),
        "--exports-dir", str(orchestrator_root / ".task-state" / "exports"),
        "handoff-close-check",
        "--task-ref", task_ref,
    ]
    ...
```

`ready_to_close=true` means all of the current MCP close-check conditions already implemented in `agent_handoff_mcp.core.handoff_close_check()` are satisfied:

- target task is the active handoff task
- active task status is `done`
- no open blockers remain
- no pending next actions remain
- no open review findings remain
- review integrity checks are healthy
- write-provenance integrity checks are healthy
- `CURRENT_TASK.md` is in sync with the handoff DB snapshot

Both long-running and `--single-pass` orchestrator runs should execute this close-check. `--single-pass` should exit `0` only if the cycle itself succeeds; it should not claim terminal success unless `ready_to_close=true`.

## Functions to Change

| File                                                           | Function / Target                                                          | Change                                                                                                       |
| -------------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `scripts/mcp/orchestrator_daemon.py`                           | `_run_handoff_dispatch`, `orchestrator_loop`, `main`                        | Integrate guidance polling/resolution, close-check invocation, repeated-loop tracking, and terminal exit behavior. |
| `scripts/mcp/orchestrator_guidance.py`                         | guidance helpers and resolution loop                                        | Own guidance classification, resolution application, stale-dispatch cleanup, and pending-action completion.  |
| `scripts/mcp/orchestrator_guidance_policy.py`                  | fallback assignment policy                                                   | Own manifest-driven fallback assignment rules used during redispatch.                                         |
| `scripts/mcp/orchestrator_helpers.py`                          | shared helper surface                                                        | Provide shared text/logging/JSON helpers used by extracted guidance logic.                                    |
| `scripts/mcp/handoff_guidance_summary.py`                      | operator summary surface                                                     | Provide an operator-facing summary of unresolved guidance state.                                               |
| `mk/handoff.mk`                                                | `handoff-inbox`, optional new daemon status/help target                    | Add an operator-facing summary surface for unresolved guidance items and daemon terminal state.              |
| `packages/agent-handoff-mcp/tests/test_orchestrator_daemon.py` | existing orchestrator-daemon test module                                   | Add coverage for guidance polling, stale-dispatch cleanup, success exit, and repeated-loop error behavior.   |

## Related Files

| File                                          | Note                                                                                                                                      |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`                | Worker-side waiting/dormant behavior already exists and must stay compatible with the new orchestrator loop.                              |
| `scripts/mcp/orchestrator_guidance.py`        | Extracted guidance classifier/resolution layer used by the orchestrator main loop.                                                         |
| `scripts/mcp/orchestrator_guidance_policy.py` | Manifest-driven fallback assignment rules; not the primary daemon-4 logic surface.                                                         |
| `scripts/mcp/orchestrator_helpers.py`         | Shared JSON/text/logging helpers used by the extracted guidance modules.                                                                    |
| `scripts/worktree-lane`                       | Guidance handoffs are emitted here via `report --guidance-request`; the orchestrator loop consumes those messages.                        |
| `scripts/mcp/lane_result.py`                  | Structured `needs_guidance` handoffs already map into MCP reports/messages that the orchestrator will classify.                           |
| `config/lane-orchestration/<task-ref>.json`   | Existing manifest still provides lane ownership, routing, merge order, and worktree metadata; it does not yet provide ordered sub-slices. |
| `docs/agentic/contracts/agent-handoff-mcp.md` | The contract should stay aligned with automatic guidance resolution and terminal orchestrator behavior.                                   |

---

# Consolidated Checklist

## Completed

- [x] Worker daemons can submit `needs_guidance` handoffs and enter dormant waiting mode.
- [x] `make handoff-inbox` surfaces open worker guidance messages and blocked reports for the orchestrator.
- [x] `scripts/mcp/orchestrator_daemon.py` already handles dispatch, intake, downstream refresh, and cross-lane verification.

## Phase 0: Scaffolding

- [x] Add orchestrator-daemon helpers for listing open `worker_to_orchestrator` guidance messages and correlating them with recent lane reports.
- [x] Add typed guidance-classification/result structures with explicit outcomes: `review`, `redispatch`, `blocked`, `fatal_error`.
- [x] Add JSONL logging events for `guidance_detected`, `guidance_resolved`, `guidance_redispatched`, `guidance_escalated`, `task_complete`, and `terminal_error`.
- [x] Verify scaffolds compile: `python3 -m py_compile scripts/mcp/orchestrator_daemon.py`.

## Phase 1: Guidance Polling and Classification

- [x] Poll open `worker_to_orchestrator` messages each cycle before merge-ready intake.
- [x] Correlate each open guidance message with the latest blocked or merge-ready worker report for the same lane/session.
- [x] Classify common guidance cases: already-resolved assignment, environment-blocked verification, pending-action redispatch, and ambiguous/manual review required.
- [x] Record an MCP decision for each classification result.

## Phase 2: Response and Lane Wake-Up

- [x] Close consumed worker guidance messages after a successful orchestrator response.
- [x] Close or supersede stale orchestrator-to-worker messages when a new dispatch replaces them.
- [x] Update lane status/notes to `active`, `review`, `blocked`, `merged`, or `closed` according to the resolution.
- [x] Send exactly one fresh orchestrator-to-worker dispatch when more lane work remains.
- [x] Verify the existing waiting semantics in `lane_prompt.py` remain correct when the orchestrator closes a worker guidance message and sends a new dispatch in the same cycle.

## Phase 3: Terminal Loop Control

- [x] Run `handoff-close-check` after guidance resolution, dispatch, and intake to determine whether the task is complete.
- [x] Exit `0` when the task is ready to close and no unresolved guidance/intake work remains.
- [x] Track repeated no-progress guidance loops and exit non-zero after a bounded retry threshold.
- [x] Exit non-zero on repeated MCP/runtime failures instead of sleeping forever.

## Phase 4: Tests

- [x] Unit tests in `packages/agent-handoff-mcp/tests/test_orchestrator_daemon.py` should mock MCP/subprocess calls and exercise guidance classification and response helpers in isolation.
- [x] Integration-style tests should use a temporary handoff DB with seeded lane/message/report state and validate: worker guidance -> orchestrator redispatch, worker guidance -> review/close, and stale dispatch cleanup.
- [x] Test that `--single-pass` exits `0` when the task becomes ready to close.
- [x] Test that repeated unresolved guidance loops produce a terminal error exit.

## Stretch Goals

- [x] Add a manifest-driven guidance policy section so tasks can declare per-lane ordered “next slice” fallbacks without hardcoding them in the daemon.
- [x] Add operator notifications or dashboard summaries for escalated guidance that requires a writable environment or manual decision.
- [x] Add automated closure of stale pending actions when the orchestrator verifies the underlying lane work is already complete.

## Success Criteria

- [x] A worker lane that emits `needs_guidance` is automatically consumed by the orchestrator daemon on the next cycle.
- [x] Workers no longer remain dormant indefinitely when the orchestrator can safely answer with a close, review, or redispatch action.
- [x] `make orchestrator-daemon TASK=<task>` exits successfully when the task is truly complete and exits non-zero when orchestration is stuck or broken.
- [x] Each lane inbox shows one current actionable assignment at most, with stale guidance and stale dispatches cleaned up by the orchestrator loop.
