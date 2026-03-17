# Daemon 2: Worker Daemon

## Problem Statement

Worker execution is still operator-driven. A human opens the lane, runs Codex, checks the result, and decides whether to hand off or ask for more work. The repo already has the core MCP inbox and handoff plumbing, but it does not have an unattended worker loop that can pick up lane work, iterate locally until review converges, run lane verification, and then record exactly one final handoff.

## Workflow Principles

- **Poll, do not push.** Workers stay pull-based and use `lane_prompt.py --check` for actionable-work detection.
- **Execution before handoff.** The daemon must use a non-reporting implementation primitive for review/fix iterations. Final handoff is recorded only after review convergence and verification.
- **Keep fix cycles local.** Review findings may be recorded in MCP for auditability, but the daemon should not send orchestrator-style `lane-dispatch` messages to itself.
- **One worker per lane.** A per-lane lock prevents concurrent daemon runs.
- **Reuse current handoff tooling.** Final merge-ready or blocked state still flows through `lane_result.py` / `scripts/worktree-lane report`, not a parallel reporting system.

## Terminology

- **Worker daemon**: `scripts/mcp/worker_daemon.py`
- **Implementation pass**: One non-reporting Codex execution against the current lane prompt
- **Review pass**: One `review_runner.py run --record-findings` invocation
- **Fix cycle**: A follow-up implementation pass driven by recorded review findings
- **Final handoff**: The single merge-ready or blocked worker report emitted after the loop settles

## Current State Analysis

- `lane_prompt.py --check` already returns exit code `0` when actionable work exists and `3` when the lane is idle.
- `make lane-run` is a convenience wrapper for humans: it renders the lane prompt, runs Codex, and immediately calls `lane_result.py handoff`. That means it is not a safe inner-loop primitive for autonomous review/fix iteration.
- `scripts/mcp/lane_result.py` already knows how to turn a final structured worker result into either a merge-ready handoff or a blocked guidance report.
- `make lane-check` already runs lane-specific verification commands.
- `make lane-handoff` remains useful for human-driven workflows, but an autonomous daemon should rely on the structured result pipeline instead of mixing `lane-run` and `lane-handoff`.
- Existing MCP helper scripts configure runtime explicitly from the orchestrator root before calling MCP APIs; the worker daemon must follow the same pattern.
- No worker-specific lock or daemon loop exists today.

## Proposed Solution

Split worker automation into two layers:

1. **Non-reporting execution primitive**
   - Add `scripts/mcp/lane_exec.py` as the reusable implementation runner.
   - It should render the same prompt/schema currently used by `make lane-run`, execute Codex, and write a structured result file without reporting anything to MCP.
   - Refactor `make lane-run` to call `lane_exec.py`, then `lane_result.py handoff`, so existing human ergonomics stay unchanged.

2. **Worker daemon loop**
   - Configure MCP runtime from the orchestrator root/worktree pair before polling or recording findings
   - Poll `lane_prompt.py --check`
   - Run `lane_exec.py`
   - If the implementation result already says `needs_guidance`, record that blocked handoff and stop
   - Run `review_runner.py run --record-findings`
   - If review does not converge, build the next implementation prompt locally from the recorded findings and run another implementation pass
   - After convergence, run `make lane-check`
   - If verification passes, submit the final successful structured result through `lane_result.py handoff`
   - If verification fails or the loop exhausts retries, submit a blocked report

This keeps the inner loop local while preserving MCP as the durable audit trail.

## Patterns to Follow

### Exclusive Lock

```python
class WorkerLock:
    def __init__(self, lane_id: str, state_dir: Path) -> None:
        self._lock_path = state_dir / f"worker-{lane_id}.lock"
```

### Implementation Primitive Split

```python
def run_lane_exec(...) -> Path:
    """Run Codex for a lane and write a structured result file without handoff side effects."""

def lane_run(...) -> None:
    result_path = run_lane_exec(...)
    handoff_result(result_path)
```

### Worker Loop

```python
def worker_loop(...) -> None:
    while True:
        lane_state = poll_lane_state(...)
        if lane_state != "actionable":
            _log_dormant_state(...)
            if single_pass:
                return
            time.sleep(poll_interval)
            continue

        final_result_path = None
        for cycle in range(max_review_cycles):
            final_result_path = run_lane_exec(...)
            result = _load_result(final_result_path)
            if result["handoff_action"] == "needs_guidance":
                _run_final_handoff(...)
                break

            review_output = run_review(record_findings=True, ...)
            findings = review_output["findings"]
            if findings_converged(findings):
                if _run_lane_check(...):
                    _run_final_handoff(...)
                else:
                    _patch_result(final_result_path, {"handoff_action": "needs_guidance", ...})
                    _run_final_handoff(...)
                break

            prompt_override = build_fix_prompt(...)
        else:
            _patch_result(final_result_path, {"handoff_action": "needs_guidance", ...})
            _run_final_handoff(...)
```

## Functions to Change

| File                                | Change                                                                                            |
| ----------------------------------- | ------------------------------------------------------------------------------------------------- |
| `scripts/mcp/lane_exec.py`          | New non-reporting worker execution primitive                                                      |
| `scripts/mcp/worker_daemon.py`      | New poll/execute/review/verify/report loop                                                        |
| `mk/lane-worker.mk`                 | Refactor `lane-run` to call `lane_exec.py` + `lane_result.py handoff`                            |
| `mk/handoff.mk`                     | Add `worker-daemon` target and related daemon control targets                                     |
| `packages/agent-handoff-mcp/tests/` | Add daemon tests and result-pipeline coverage                                                     |

## Related Files

| File                           | Note                                                 |
| ------------------------------ | ---------------------------------------------------- |
| `scripts/mcp/lane_prompt.py`   | Existing actionable-work detection                   |
| `scripts/mcp/lane_result.py`   | Final handoff adapter used after convergence         |
| `scripts/mcp/review_runner.py` | Review primitive from daemon-1                       |
| `scripts/worktree-lane`        | Existing report plumbing used by final handoff paths |

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [x] Create `scripts/mcp/lane_exec.py` with CLI args for task, lane, worktree, session, and output path
- [x] Create `scripts/mcp/worker_daemon.py` with CLI args for task, lane, orchestrator root, polling, retries, and dry-run
- [x] Add `worker-daemon` Makefile target and help text
- [x] Verify: `python3 scripts/mcp/worker_daemon.py --help` exits cleanly

## Phase 1: Execution Primitive Refactor

- [x] Move the non-reporting prompt/schema/Codex execution steps out of `make lane-run` into `lane_exec.py`
- [x] Keep `make lane-run` as the human wrapper that runs `lane_exec.py` and then `lane_result.py handoff`
- [x] Ensure result files can be reused by the daemon after review/verification
- [x] Test: `make lane-run` still behaves exactly as it does today for human operators

## Phase 2: Polling and Locking

- [x] Implement per-lane `flock` locking
- [x] Configure MCP runtime before polling or recording findings
- [x] Implement `_has_actionable_work()` using `lane_prompt.py --check`
- [x] Implement `--single-pass`
- [x] Add structured JSONL logging per lane
- [x] Test: second daemon instance exits cleanly when the lock is held

## Phase 3: Review and Fix Loop

- [x] Invoke `review_runner.py run --record-findings`
- [x] Keep recorded findings local to the worker loop when building the next prompt
- [x] Do not call `make lane-dispatch` for worker self-fix cycles
- [x] Stop when review converges or retry budget is exhausted
- [x] Test: non-converged review triggers another local implementation pass

## Phase 4: Verification and Final Handoff

- [x] Run `make lane-check` after review convergence
- [x] Reuse `lane_result.py handoff` for final merge-ready or blocked reporting
- [x] Preserve the final successful result payload for commit message / summary data
- [x] Test: converged + green verification emits one merge-ready handoff
- [x] Test: blocked verification emits one blocked handoff

## Success Criteria

- [x] `make worker-daemon TASK=<task> LANE=<lane> SINGLE_PASS=1` can pick up work, iterate locally, and emit exactly one final handoff
- [x] No worker self-fix loop depends on `lane-dispatch`
- [x] `make lane-run` remains a stable human-facing command after the refactor
- [x] Review findings are recorded before they influence worker retry behavior
