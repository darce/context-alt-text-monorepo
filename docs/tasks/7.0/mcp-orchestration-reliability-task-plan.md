# MCP Orchestration Reliability

> **Scope:** Tooling/infrastructure; ancillary to `remaining-sync-workbench-and-retention`. Not tracked in a product roadmap or epic.

## Problem Statement

The MCP daemon orchestration layer (orchestrator daemon, worker daemons, codex-subagent bridge) has multiple reliability failures that prevent autonomous lane execution from completing a full cycle. Workers execute successfully and produce valid result payloads, but the handoff, review, guidance-classification, and error-recovery paths break before the orchestrator can act on the results. The net effect is that every worker run ends in `handoff_failed` or `dormant_entered`, the orchestrator stalls on `guidance_failed` or `terminal_error`, and no lane ever reaches intake.

## Evidence

Log analysis from the `remaining-sync-workbench-and-retention` task across `backend-http`, `wp-proxy`, and orchestrator daemons on 2026-03-19/20. Failure modes are numbered ORD-001 through ORD-008.

### ORD-001: Review schema violates OpenAI structured-output rules

**Symptom:** `review_failed` with HTTP 400: `"'required' is required to be supplied and to be an array including every key in properties. Missing 'line_start'."`

**Root cause:** `REVIEW_OUTPUT_SCHEMA` in `review_runner.py` lists `line_start`, `line_end`, and `fix` as `required` but defines them as nullable types (`["integer", "null"]` and `["string", "null"]` respectively). OpenAI structured outputs require that all properties in `required` be non-nullable; nullable fields must be omitted from `required`.

**Impact:** Every review turn fails on first API call. Workers that complete execution and enter review immediately crash, wasting the entire execution token budget (150k-350k tokens per turn).

### ORD-002: Handoff submission fails silently after `needs_guidance`

**Symptom:** `exec_complete` -> `needs_guidance` -> `handoff_failed` with no error detail in the log.

**Root cause:** `_run_final_handoff()` in `worker_daemon.py` shells out to `lane_result.py handoff`, which builds a `scripts/worktree-lane report --guidance-request` subprocess. The parent captures only the return code (`subprocess.run(cmd, check=False).returncode`), discarding stdout/stderr. When the `worktree-lane report` subprocess fails (MCP binary not reachable, state-dir path wrong, agent-handoff-mcp returns an error), the worker logs `handoff_failed` with no diagnostic information.

**Impact:** Operators cannot diagnose why handoffs fail without manually re-running the subprocess. Every `needs_guidance` result becomes a dead end.

### ORD-003: Worker enters permanent dormancy after one handoff retry

**Symptom:** `handoff_retry_failed` -> `dormant_entered state=handoff_failed` -> worker never retries again.

**Root cause:** The worker main loop in `worker_daemon.py` uses a boolean `handoff_failure_seen_in_process` flag. After one retry attempt, this flag is set to `True` and never reset. On subsequent poll cycles, the retry block is skipped entirely (guarded by `not handoff_failure_seen_in_process`). The worker enters dormant permanently; only a full daemon restart can re-arm the retry.

**Impact:** A single transient handoff failure (network blip, MCP server restart) permanently disables the worker. The orchestrator cannot recover the lane without operator intervention.

### ORD-004: Guidance classifier falls through to `fatal_error` on valid worker messages

**Symptom:** `guidance_detected` -> `guidance_failed error="Unable to classify worker guidance for lane backend-http."` -> `guidance_stall` -> `terminal_error`

**Root cause:** `_classify_guidance()` in `orchestrator_guidance.py` uses three hardcoded marker-string tuples (`_RESOLVED_MARKERS`, `_REMAINING_WORK_MARKERS`, `_ENV_BLOCKER_MARKERS`) matched against the combined text of the worker message and report. If the worker's natural-language description doesn't contain any of these exact substrings, classification falls through to `fatal_error`. The marker lists are narrow (e.g., `_ENV_BLOCKER_MARKERS` has 10 entries like "vendor is a symlink" and "mypy is not available") and miss common worker descriptions like "tests fail", "composer install needed", "vendor/bin/phpunit missing", "no code changes were needed".

**Impact:** Valid worker guidance messages that describe real blockers or completed work are misclassified as fatal errors, stalling the orchestrator.

### ORD-005: `single_pass` mode treats any guidance failure as terminal

**Symptom:** Orchestrator starts with `single_pass=true`, encounters one `guidance_failed`, and immediately returns 1 with `terminal_error reason=guidance_stall`.

**Root cause:** The guidance stall check in `orchestrator_daemon.py` short-circuits on `single_pass`: `if single_pass or stall_count >= GUIDANCE_STALL_THRESHOLD`. In single-pass mode, any unclassifiable guidance message is immediately terminal regardless of the stall threshold (3). The remaining cycle steps (task plan dispatch, merge-ready polling, intake, close check) are never executed.

**Impact:** The orchestrator wastes the entire cycle on worker auto-start but exits before it can intake ready lanes or dispatch new work. Single-pass becomes useless for any task where at least one lane has unclassifiable guidance.

### ORD-006: Lane worktrees lack dependency directories

**Symptom:** wp-proxy worker reports: `"vendor/bin/phpunit is missing in this worktree"`, `"vendor/bin/phpstan is missing in this worktree"`. Tests cannot run; worker produces `needs_guidance` with blockers.

**Root cause:** `scripts/worktree-lane create` runs `git worktree add` but does not install dependencies. `vendor/` and `node_modules/` are gitignored and therefore absent in new worktrees. Neither `worktree-lane create` nor the `lane-open` Makefile target runs `composer install` or `npm install`.

**Impact:** Every PHP and TypeScript lane worktree is broken on creation. Workers waste an execution turn discovering the missing dependencies, produce a blocker, and the guidance classifier can't handle the blocker message (ORD-004), creating a cascading failure.

### ORD-007: Orchestrator log has no rotation

**Symptom:** `logs/daemon/orchestrator.jsonl` grows unbounded. On daemon restart, all historical entries persist and `tail -n 30` returns a mix of old and new entries from different process lifetimes.

**Root cause:** The orchestrator logger in `orchestrator_helpers.py _log()` opens the log file in append mode with no size check or rotation. The worker logger in `worker_daemon.py _log()` has rotation at 1MB (`_MAX_LOG_BYTES`), but the orchestrator does not.

**Impact:** Log tailing becomes unreliable for monitoring. There is no way to distinguish events from different daemon lifetimes without parsing timestamps.

### ORD-008: No `run_id` to distinguish daemon lifetimes

**Symptom:** Log entries from different daemon restarts are interleaved with no process-lifetime marker. The `daemon_start` event is the only restart signal, but identical `daemon_start` entries can appear from repeated rapid restarts.

**Root cause:** Neither daemon emits a unique `run_id` per process lifetime.

**Impact:** Post-mortem log analysis requires manual timestamp correlation. Automated monitoring tools cannot group events by daemon lifetime.

## Proposed Solution

Fix in 4 phases. Each phase is independently shippable and testable.

### Phase 1: Review Schema and Handoff Diagnostics (unblocks worker -> orchestrator flow)

**1a. Fix review output schema (ORD-001)**

In `review_runner.py REVIEW_OUTPUT_SCHEMA`: remove `line_start`, `line_end`, and `fix` from the `required` array in the `findings.items` object. These fields are nullable; OpenAI structured outputs require nullable fields to not appear in `required`.

Functions to change:
- `review_runner.py`: `REVIEW_OUTPUT_SCHEMA` constant

**1b. Capture subprocess diagnostics in handoff (ORD-002)**

In `worker_daemon.py _run_final_handoff()`: pass `capture_output=True` to the `subprocess.run()` call. On non-zero exit, log the stderr/stdout tail (truncated to 500 chars) alongside the `handoff_failed` event.

Functions to change:
- `worker_daemon.py`: `_run_final_handoff()`

### Phase 2: Worker Retry and Dormancy (unblocks recovery without restart)

**2a. Replace boolean flag with bounded retry counter (ORD-003)**

Replace `handoff_failure_seen_in_process: bool` with `handoff_retry_count: int` and a configurable `MAX_HANDOFF_RETRIES` (default 3). On each poll cycle where persisted state is `handoff_failed`, attempt retry if `handoff_retry_count < MAX_HANDOFF_RETRIES`. Add exponential backoff between retries (`poll_interval * 2^retry_count`, capped at 5 minutes). After max retries, enter dormant and log the final state with retry count.

The boolean is used at 6 sites in `worker_loop()`: initialized (line 611), guarded (line 621), and set to `True` at 4 independent handoff-failure branches (lines 632, 859, 979, 1042). All 6 sites must be updated.

Functions to change:
- `worker_daemon.py`: `worker_loop()` -- replace boolean `handoff_failure_seen_in_process` at all 6 usage sites with bounded retry counter

### Phase 3: Guidance Resilience (unblocks orchestrator cycle completion)

**3a. Add fallback classification and widen marker lists (ORD-004)**

In `orchestrator_guidance.py _classify_guidance()`: change the final `fatal_error` fallback to `blocked` when the combined guidance text is non-empty but unclassifiable. Add missing common markers to `_ENV_BLOCKER_MARKERS`: "vendor/bin/phpunit", "vendor/bin/phpstan", "composer install", "npm install", "node_modules", "command not found", "exit with code 127". Add to `_RESOLVED_MARKERS`: "no code changes were needed", "already fixed", "work already done", "verification passed".

Functions to change:
- `orchestrator_guidance.py`: `_classify_guidance()`, `_ENV_BLOCKER_MARKERS`, `_RESOLVED_MARKERS`

**3b. Let single_pass complete remaining cycle steps after guidance failure (ORD-005)**

In `orchestrator_daemon.py orchestrator_loop()`: remove the `single_pass or` prefix from the guidance stall check. In single_pass mode, log the guidance failure but do not return early; let the cycle continue through task plan dispatch, merge polling, intake, and close check. Set a `had_guidance_failure` flag and return 1 at the end of the cycle if the flag is set.

Functions to change:
- `orchestrator_daemon.py`: `orchestrator_loop()` guidance stall check block

### Phase 4: Environment and Observability

**4a. Bootstrap dependencies for newly opened lanes (ORD-006)**

Implement the dependency bootstrap in `mk/lane-lifecycle.mk` `lane-open`, which already has lane-manifest context materialized into Make variables (`owned_paths`, `test_commands`, and worktree location). Keep `scripts/worktree-lane create` focused on worktree creation plus MCP lane registration; it does not know the lane's owned paths.

After `lane-open` creates or reuses the worktree, provision the lane environment for the lane-owned stack. For each owned PHP app path containing `composer.json`, either install dependencies in place or attach the shared dependency directory used by local worktrees. For each owned frontend path containing `package.json`, either install dependencies in place or attach the shared `node_modules` directory. Any shared dependency directories must remain ignored via local exclude config so they never appear in review or staging output. Log the bootstrap step as part of lane-open output so operators can distinguish provisioning failures from worker-code failures.

Functions to change:
- `mk/lane-lifecycle.mk`: `lane-open` target

**4b. Add shared log rotation (ORD-007)**

Extract the rotation logic from `worker_daemon.py _log()` into a shared helper `_rotate_jsonl_if_needed(path: Path, max_bytes: int)` in `orchestrator_helpers.py`. Call it from both `orchestrator_helpers.py _log()` and `worker_daemon.py _log()` (replacing the inline copy). This avoids maintaining two copies of the same rotation code.

Functions to change:
- `orchestrator_helpers.py`: add `_rotate_jsonl_if_needed()`, call it from `_log()`
- `worker_daemon.py`: replace inline rotation in `_log()` with import of shared helper

**4c. Add `run_id` to both daemons (ORD-008)**

Generate a `uuid4` run_id at daemon startup. Include it in every log entry as a top-level field via the existing `**extra` kwargs (no `_log()` signature change needed). Emit `run_id` in the `daemon_start` event for explicit correlation.

Functions to change:
- `orchestrator_daemon.py`: `main()` and `orchestrator_loop()` (generate run_id, pass as kwarg to every `log()` call)
- `worker_daemon.py`: `main()` and `worker_loop()` (generate run_id, pass as kwarg to every `log()` call)

## Patterns to Follow

### Review Schema Fix

```python
# In review_runner.py REVIEW_OUTPUT_SCHEMA
# Before (broken):
"required": ["severity", "category", "file_path", "line_start", "line_end", "description", "fix"],

# After (fixed):
"required": ["severity", "category", "file_path", "description"],
```

### Handoff Diagnostic Capture

```python
# In worker_daemon.py _run_final_handoff()
result = subprocess.run(cmd, check=False, capture_output=True, text=True)
if result.returncode != 0:
    stderr_tail = (result.stderr or "")[-500:]
    stdout_tail = (result.stdout or "")[-500:]
    log("ERROR", "handoff_subprocess_failed",
        exit_code=result.returncode,
        stderr_tail=stderr_tail,
        stdout_tail=stdout_tail)
return result.returncode
```

### Bounded Retry with Backoff

```python
# In worker_daemon.py main loop
MAX_HANDOFF_RETRIES = 3
handoff_retry_count = 0

# In the handoff_failed persisted-state branch:
if handoff_retry_count < MAX_HANDOFF_RETRIES:
    backoff = min(poll_interval * (2 ** handoff_retry_count), 300)
    time.sleep(backoff)
    # attempt retry ...
    handoff_retry_count += 1
else:
    # enter dormant
```

### Guidance Fallback

```python
# In orchestrator_guidance.py _classify_guidance(), replace the final fatal_error:
if combined.strip():
    return GuidanceResolution(
        kind="blocked",
        lane_id=lane_id,
        worker_message_id=worker_message_id,
        latest_report_id=latest_report_id,
        decision=f"Classified unrecognized worker guidance for {lane_id} as blocked (fallback).",
        rationale="Guidance text present but did not match known resolved, redispatch, or environment-blocked patterns.",
        lane_status="blocked",
        lane_notes="Unclassifiable guidance; marked blocked for operator review.",
        dispatch_subject=None,
        dispatch_message=None,
        close_dispatch_ids=close_dispatch_ids,
        error=None,
    )
# Only emit fatal_error when guidance text is truly empty
return GuidanceResolution(kind="fatal_error", ...)
```

## Dependencies

- Phase 1 requires no external changes; pure schema and subprocess argument fixes.
- Phase 2 has no cross-file dependencies.
- Phase 3a and 3b are independent edits within the orchestrator.
- Phase 4a depends on lane-open having lane-manifest context (`owned_paths`, `test_commands`, worktree path) and must preserve the repo's shared-dependency/local-exclude workflow for worker worktrees.
- Phase 4b adds a shared rotation helper that both daemons import; the worker import is a minor refactor.
- Phase 4c is an independent observability improvement.

## Verification

### Phase 1
- Run a real `review_runner.py` structured-output turn via the codex-subagent bridge with a nullable `line_start` / `line_end` / `fix` finding payload and confirm the request no longer fails with HTTP 400
- Optionally serialize the emitted schema and assert the nullable fields are absent from the inner `required` list as a cheap unit-level regression guard
- Trigger a `needs_guidance` handoff failure and confirm stderr appears in the log

### Phase 2
- Start a worker with a pre-seeded `handoff_failed` status file; confirm it retries up to 3 times with increasing intervals
- Confirm dormant is entered only after max retries

### Phase 3
- Send a worker guidance message containing "vendor/bin/phpunit is missing"; confirm it classifies as `blocked` not `fatal_error`
- Send a message with no known markers; confirm it classifies as `blocked` (fallback) not `fatal_error`
- Run orchestrator in single_pass with one blocked lane and one ready lane; confirm the ready lane is still intaked

### Phase 4
- Run `make lane-open TASK=<task-ref> LANE=wp-proxy ENTER_SHELL=0`; confirm the lane's declared PHP test command is runnable immediately afterward without manual dependency repair
- Run `make lane-open TASK=<task-ref> LANE=frontend ENTER_SHELL=0`; confirm the lane's declared frontend test command is runnable immediately afterward without manual dependency repair
- Write 1MB+ to orchestrator.jsonl; confirm rotation kicks in on next log write
- Restart both daemons; confirm `run_id` appears in all log entries and differs between restarts

## Checklist

- [ ] Phase 1a: Remove nullable fields from review schema `required` array
- [ ] Phase 1b: Add `capture_output=True` and diagnostic logging to `_run_final_handoff()`
- [ ] Phase 2a: Replace boolean handoff flag with bounded retry counter and backoff
- [ ] Phase 3a: Widen marker lists and add `blocked` fallback to `_classify_guidance()`
- [ ] Phase 3b: Remove `single_pass or` short-circuit from guidance stall check
- [ ] Phase 4a: Bootstrap lane dependencies via `lane-open` using lane-manifest context
- [ ] Phase 4b: Add log rotation to `orchestrator_helpers.py _log()`
- [ ] Phase 4c: Add `run_id` to both daemon log closures
