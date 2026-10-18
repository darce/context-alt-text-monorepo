# Orchestration Hardening: Scope Enforcement, Convergence Policy, and Observability

## Problem Statement

The backend-domain lane failure on 2026-03-21 exposed three layers of orchestration weakness: (1) workers can write outside their owned paths without detection, causing contaminated worktrees that poison subsequent cycles; (2) the daemon re-dispatches into exhausted lanes without escalation, burning 7M+ tokens in non-converging loops; (3) operators have no live view of lane health, token burn, or convergence trends, forcing manual MCP queries to diagnose stalls. These failures are structural; a single task plan addresses all three layers because the daemon policy fixes produce the events that the observability surface consumes.

## Workflow Principles

- **Scope enforcement is a hard gate, not advisory.** If a worker modifies files outside `owned_paths`, the turn is rejected before review. No exceptions without explicit orchestrator override.
- **Exhaustion is a routing event, not a silent outcome.** After N non-converged review cycles, the daemon must pause and require an explicit orchestrator decision. Blind re-dispatch into the same state is never correct.
- **Effort goes up on failure, not down.** If a run exhausts at a given reasoning effort, the next attempt should escalate, not lower. Small models at low effort cannot self-correct scope drift.
- **Token burn is a first-class health signal.** Cumulative token spend per lane per session must be tracked and surfaced. Anomalous burn (>2M tokens without convergence) should trigger automatic `attention_required`.
- **Fresh substrates for narrow retries (stretch goal).** Redispatch into a contaminated worktree reproduces the contamination. Narrow retries should prefer clean worktrees; automated fresh-worktree provisioning is a stretch goal, not part of this task's core scope.
- **Worker stop means stopped.** All state artifacts (lock, PID, status) must be consistent after stop. No contradictory signals.
- **Context freshness is the primary orchestration advantage.** The whole point of spawning subagents is to give them a clean context window unburdened by prior operational noise. If the prompt itself consumes a large fraction of the context window with MCP metadata, stale findings, or cross-domain history, the subagent loses its advantage over a long-running conversation. Measure context utilization; warn when it degrades.

## Terminology

- **Scope violation**: A worker turn that modified files outside the lane's `effective_owned_paths`. Detected post-execution, pre-review.
- **Exhaustion streak**: Consecutive `review_exhausted` outcomes within a worker daemon session (identified by `run_id`) without intervening convergence. Scoped per session, not per dispatch; the counter accumulates across multiple assignments delivered to the same running worker and resets to zero when a new worker session starts.
- **Effective owned paths**: The narrowed scope for a specific dispatch, which may be tighter than the lane manifest's `owned_paths`. Stored as a JSON-encoded string in the `artifacts` list of the dispatch lane message, e.g. `artifacts: ['{"type":"owned_paths_override","paths":[...]}']`. The MCP normalizer's `_coerce_string_list()` preserves string items but silently drops non-string items like dicts, so the override must be serialized to a string before dispatch. `lane_exec.py` reads it from the most recent `orchestrator_to_worker` message via `list_lane_messages`, iterating `artifacts` and attempting `json.loads()` on each string to find the entry with `type == "owned_paths_override"`.
- **Worker session boundary**: The point at which a worker daemon session starts. Exhaustion streak and cumulative token burn counters are scoped per worker daemon session (identified by `run_id`) and reset to zero on session start. The orchestrator delivers new assignments via `record_lane_message` without restarting the worker, so counters are intentionally per-session rather than per-assignment; a long-running worker that receives multiple assignments in one session accumulates counts across them.
- **Token burn rate**: Cumulative tokens consumed per lane per session (scoped by `run_id`). Tracked in the status file and surfaced as a health signal. See **Worker session boundary** for why counters are per-session rather than per-assignment.
- **Composite lane state**: A derived human-readable status combining lane record status and worker runtime status (e.g., `closed / stale-lock anomaly`).
- **Salvage-and-close**: An orchestration path that freezes a failed lane, classifies its changed files, extracts safe product slices, and closes the lane while preserving the worktree as evidence.
- **Context utilization ratio**: The fraction of the model's context window consumed by the injected prompt (system + user message) before the model produces its first token. A ratio above 0.4 means the worker has less than 60% of its window for reasoning, tool output, and generation.
- **Domain signal ratio**: The proportion of the injected prompt that is domain-relevant (task brief, code context, owned-path file content) versus operational overhead (MCP metadata, prior findings, test history, reporting contracts). A healthy prompt has domain signal > 60%.
- **Context pressure**: A derived health signal combining context utilization ratio and domain signal ratio. High utilization + low domain signal = the prompt is bloated with operational noise.

## Current State Analysis

- `lane_exec.py` loads `owned_paths` from the lane manifest but never validates the worktree diff against them. Scope enforcement only exists at commit time in `mk/lane-worker.mk`.
- `worker_daemon.py` emits `review_exhausted` after 3 cycles (configurable via `--max-review-cycles`) but the orchestrator daemon does not listen for or react to this event. The worker enters `waiting_for_orchestrator` and the orchestrator sees it as a stalled non-merge-ready lane.
- `_env.py` contains `resolve_auto_reasoning_effort()` which auto-tunes effort based on lane structure, but has no signal for "previous run exhausted." The backend-domain lane was lowered from medium to low after exhaustion; the opposite of what was needed.
- `worker_daemon_ctl.py` `daemon_stop()` signals the process and updates the status file but does not clear the lock file. After SIGKILL, `lock.held: true` persists with a stale PID, confusing both operators and the orchestrator.
- The orchestrator daemon has a `plan_stall_threshold` (3 cycles of no progress) but no per-lane health scoring. It cannot distinguish "lane is working but slow" from "lane is churning without progress."
- Token observability data exists in worker status (per-turn and cumulative totals) but requires manual aggregation. The backend-domain lane burned 151K-7M tokens across individual turns with no automated warning.
- The TUI plan (`orchestration-tui-monitoring-task-plan.md`) addresses the presentation layer but assumes the daemon already emits the right events. It does not; scope violations, exhaustion streaks, and token burn anomalies are not events today.
- `lane_prompt.py` bounds context by item count (`MAX_ASSIGNMENT_ITEMS=12`, `MAX_BRIEF_ITEMS=6`, etc.) but never measures the resulting prompt size against the model's context window. A prompt with 12 assignments and 6 briefs and global context could consume 30-50% of a 128K window before the worker reads a single file. The bridge (`codex_subagent_bridge.py`) reports `model_context_window` and per-turn token usage, but this telemetry is captured after the turn completes; it is never fed back to the prompt construction step.
- In `shared_lane` session mode, `_run_subagent_shared()` reuses the initialized app-server client for a given lane key but starts a **fresh Codex thread per call**. There is no accumulated per-call message history across daemon cycles at the bridge level; the relevant context concern is per-turn prompt size, not cumulative thread history.
- No `context_pressure` signal exists. Operators cannot see when a single-turn prompt is consuming an unsafe fraction of the model's context window before the worker has a chance to reason or call tools.

## Proposed Solution

Implement hardening across three layers in dependency order:

**Layer 1 (Daemon Policy):** Add scope enforcement in `lane_exec.py`, exhaustion-streak tracking and auto-escalation in `worker_daemon.py`, effort inversion logic in `_env.py`, and lock cleanup in `worker_daemon_ctl.py`. Fresh-worktree redispatch is a stretch goal addressed separately.

**Layer 2 (Event Enrichment):** New structured events (`scope_violation`, `token_burn_warning`, `exhaustion_streak`, `worker_stopped`) emitted by the daemon and consumed by both MCP tools and the observability surface. Token burn thresholds configurable in the lane manifest.

**Layer 3 (Observability Surface):** A `make dashboard-live` polling script (50-100 LOC) that prints per-lane composite state, token burn, convergence history, and scope health every N seconds using existing MCP tools. This is the immediate payoff; a full Textual TUI is deferred until the event vocabulary from Layers 1-2 stabilizes.

**Layer 4 (Context Freshness):** Measure prompt size before dispatch against the model's reported context window. Compute context utilization ratio and domain signal ratio. Emit `context_pressure` events when utilization exceeds configurable thresholds. Surface context utilization in the dashboard and in lane health scoring. Auto-compact and session-reset are out of scope; the bridge already starts a fresh thread per turn, so per-turn prompt size is the only lever to tune.

Terminal file-tailing is sufficient for the observability surface. The JSONL logs are local, `kqueue` watchers are native on macOS, and the operator is co-located. An HTTP/WebSocket stream adds a second event transport with its own reliability story (reconnect, ordering, missed events) and is only justified for a future browser-based remote dashboard.

## Patterns to Follow

### Scope Enforcement Guard

```python
# lane_exec.py — new function, called after execution, before review
# Mirrors _changed_files() in review_runner.py: captures staged, unstaged, and untracked.
def _check_scope_violations(
    worktree_path: Path,
    owned_paths: list[str],
    orchestrator_root: Path,
) -> list[str]:
    """Return list of changed files outside owned_paths. Empty = compliant."""
    # Tracked modifications (staged + unstaged + deleted relative to HEAD)
    diff_result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=worktree_path, capture_output=True, text=True, check=True,
    )
    # Newly created files not yet tracked
    untracked_result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=worktree_path, capture_output=True, text=True, check=True,
    )
    changed = (
        set(diff_result.stdout.strip().splitlines())
        | set(untracked_result.stdout.strip().splitlines())
    )
    violations = [f for f in sorted(changed) if not _matches_any_owned_path(f, owned_paths)]
    return violations
```

### Exhaustion Streak Tracking

```python
# worker_daemon.py — in the review loop, after review_exhausted
def _update_exhaustion_streak(status_path: Path, lane_id: str, run_id: str) -> int:
    """Increment and return the exhaustion streak counter."""
    status = _read_status(status_path)
    streak = status.get("exhaustion_streak", 0) + 1
    status["exhaustion_streak"] = streak
    status["last_exhaustion_run_id"] = run_id
    if streak >= 2:
        status["attention_required"] = True
    _write_status(status_path, status)
    return streak
```

### Token Burn Warning

```python
# worker_daemon.py — after _record_observability()
def _check_token_burn(
    cumulative_tokens: int,
    threshold: int,  # default 2_000_000; configurable in manifest
    lane_id: str,
) -> bool:
    """Emit token_burn_warning if cumulative exceeds threshold."""
    if cumulative_tokens > threshold:
        log("WARNING", "token_burn_warning",
            lane=lane_id, cumulative_tokens=cumulative_tokens,
            threshold=threshold)
        return True
    return False
```

### Effort Inversion After Exhaustion

```python
# _env.py — extend resolve_auto_reasoning_effort()
EFFORT_LADDER = ("low", "medium", "high", "xhigh")

def _escalate_effort(current: str) -> str | None:
    """Return one level higher, or None if already at max."""
    idx = EFFORT_LADDER.index(current) if current in EFFORT_LADDER else 0
    if idx < len(EFFORT_LADDER) - 1:
        return EFFORT_LADDER[idx + 1]
    return None
```

### Authoritative Lock Cleanup

```python
# worker_daemon_ctl.py — in daemon_stop(), after signaling
def _cleanup_lock(state_dir: Path, lane_id: str) -> None:
    lock = state_dir / f"worker-{lane_id}.lock"
    lock.unlink(missing_ok=True)
```

### Dashboard-Live Polling Script

```python
# scripts/mcp/dashboard_live.py — standalone polling script
import time, json, subprocess, sys

def poll_lane_status(task_ref: str, lane_ids: list[str]) -> list[dict]:
    """Query MCP worker_status for each lane, return summary dicts."""
    results = []
    for lane_id in lane_ids:
        raw = subprocess.run(
            ["agent-handoff-mcp", "--workspace-root", ".",
             "worker-status", "--task-ref", task_ref, "--lane-id", lane_id],
            capture_output=True, text=True,
        )
        status = json.loads(raw.stdout) if raw.returncode == 0 else {"error": raw.stderr}
        results.append(_summarize(lane_id, status))
    return results

def _summarize(lane_id: str, status: dict) -> dict:
    obs = status.get("observability", {}).get("latest", {})
    return {
        "lane": lane_id,
        "state": f"{status.get('worker_state', '?')}",
        "cycle": status.get("status_record", {}).get("cycle", "?"),
        "model": obs.get("model", "?"),
        "effort": obs.get("effective_reasoning_effort", "?"),
        "tokens": obs.get("token_usage_totals", {}).get("total_tokens", 0),
        "attention": status.get("attention_required", False),
        "stale_lock": status.get("stale_lock", False),
    }

def main():
    task_ref = sys.argv[1]
    lane_ids = sys.argv[2:]
    while True:
        rows = poll_lane_status(task_ref, lane_ids)
        # clear + print table
        print("\033[2J\033[H")  # clear screen
        print(f"Task: {task_ref}  |  {time.strftime('%H:%M:%S')}")
        print(f"{'Lane':<25} {'State':<20} {'Cycle':<6} {'Model':<16} {'Effort':<8} {'Tokens':>10} {'Attn':>5}")
        print("-" * 95)
        for r in rows:
            attn = "!!!" if r["attention"] or r["stale_lock"] else ""
            print(f"{r['lane']:<25} {r['state']:<20} {r['cycle']:<6} {r['model']:<16} {r['effort']:<8} {r['tokens']:>10,} {attn:>5}")
        time.sleep(10)
```

### Context Utilization Measurement

```python
# lane_prompt.py -- new function, called at the end of _build_prompt()
def _measure_context_utilization(
    rendered_prompt: str,
    model_context_window: int,  # from lane manifest or default 128_000
    section_sizes: dict[str, int],  # {"assignment": N, "briefs": N, "guidance": N, ...}
) -> dict:
    """Compute context utilization and domain signal metrics."""
    prompt_tokens = len(rendered_prompt) // 4  # rough char-to-token estimate
    utilization_ratio = prompt_tokens / model_context_window if model_context_window else 0.0

    domain_keys = {"assignment", "briefs", "task_brief"}
    overhead_keys = {"guidance", "test_history", "decision_history",
                     "global_context", "reporting_contract"}
    domain_chars = sum(section_sizes.get(k, 0) for k in domain_keys)
    overhead_chars = sum(section_sizes.get(k, 0) for k in overhead_keys)
    total = domain_chars + overhead_chars
    domain_signal_ratio = domain_chars / total if total else 1.0

    return {
        "prompt_tokens_approx": prompt_tokens,
        "model_context_window": model_context_window,
        "utilization_ratio": round(utilization_ratio, 3),
        "domain_signal_ratio": round(domain_signal_ratio, 3),
        "pressure": "high" if utilization_ratio > 0.4 and domain_signal_ratio < 0.5
                    else "elevated" if utilization_ratio > 0.3
                    else "normal",
    }
```

### Note: No Auto-Compact Needed

The bridge already starts a fresh Codex thread on every `_run_subagent_shared()` call; only the app-server client is reused across daemon cycles. There is no accumulated per-call message history to compact. The `_should_reset_session()` helper is therefore not implemented in this task. The relevant concern is per-turn prompt size, which is addressed by `_measure_context_utilization()`.

## Functions to Change

| File                                 | Function / Target                           | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------------------ | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_exec.py`           | `run_lane_exec()` ~L299                     | Add `_check_scope_violations()` call after execution completes, before returning result. If violations found, set `result["scope_violation"] = True` and `result["scope_violations"] = [files]`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_exec.py`           | new `_check_scope_violations()`             | Diff worktree `HEAD` against `owned_paths`, return list of out-of-scope changed files.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_exec.py`           | new `_matches_any_owned_path()`             | Glob match a file path against owned_paths patterns.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`       | review loop ~L999-1065                      | After `review_exhausted`, call `_update_exhaustion_streak()`. If streak >= 2, set `attention_required`. If streak >= 3, force `needs_orchestrator_decision` and skip further cycles.                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`       | review loop ~L999                           | Before entering review, check result for `scope_violation`. If true, skip review, emit `scope_violation` event, mark turn as failed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`       | after `_record_observability()` ~L656       | Call `_check_token_burn()` with cumulative token total and configurable threshold (default 2M). Emit `token_burn_warning` event and set `attention_required` if exceeded.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`       | new `_update_exhaustion_streak()`           | Read/write exhaustion streak counter in status file. Reset on convergence.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`       | new `_check_token_burn()`                   | Compare cumulative tokens against threshold, emit warning event.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `scripts/mcp/_env.py`                | `resolve_auto_reasoning_effort()` ~L145-243 | Add `previous_run_exhausted` parameter. If true, call `_escalate_effort(current)` to return one level higher. Add "escalated after exhaustion" to reasons list.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `scripts/mcp/_env.py`                | new `_escalate_effort()`                    | Return next level in `EFFORT_LADDER`, or None at max.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `scripts/mcp/worker_daemon_ctl.py`   | `daemon_stop()` ~L380-418                   | After signaling process, call `_cleanup_lock()` to delete lock file. Emit `worker_stopped` JSONL event with timestamp.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `scripts/mcp/worker_daemon_ctl.py`   | new `_cleanup_lock()`                       | Delete lock file at `state_dir / f"worker-{lane_id}.lock"`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `scripts/mcp/worker_daemon_ctl.py`   | new `_emit_stopped_event()`                 | Append `{"event": "worker_stopped", "lane": lane_id, "ts": now}` to worker JSONL log.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `scripts/mcp/orchestrator_daemon.py` | `_ensure_lane_workers()` ~L685              | Before starting a worker, read lane status for `exhaustion_streak`. If >= 2, skip auto-start and emit `lane_unhealthy` event. Require explicit orchestrator decision.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `scripts/mcp/orchestrator_daemon.py` | new `_check_lane_health()`                  | Compute per-lane health score from exhaustion streak, token burn, scope violations, context pressure, open message count. Return health enum: `healthy / degraded / unhealthy`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `scripts/mcp/orchestrator_daemon.py` | `_dispatch_from_task_plan()` ~L180-279      | When dispatching a narrowed scope, store `effective_owned_paths` as a JSON-encoded string in the `artifacts` list of the dispatch lane message, e.g. `artifacts=[json.dumps({"type": "owned_paths_override", "paths": [...]})]`. The `artifacts` field accepts `list[str]`; the normalizer's `_coerce_string_list()` preserves strings but silently drops non-string items, so the override dict must be serialized before dispatch.                                                                                                                                                                                                                               |
| `scripts/mcp/lane_manifest.py`       | `get_lane_config()` ~L320-360               | Add `token_burn_threshold` field (default 2000000) read from manifest JSON. Add `effective_owned_paths` override: **Note: the owned_paths override is actually implemented in `lane_exec._get_effective_owned_paths()`, not in `get_lane_config()`.** `get_lane_config()` returns static manifest fields only; `lane_exec._get_effective_owned_paths()` reads the most recent `orchestrator_to_worker` lane message via `list_lane_messages`, iterates its `artifacts` list attempting `json.loads()` on each string, and returns the `paths` list from the first parsed object with `type == "owned_paths_override"`. Non-parseable strings are skipped silently. |
| `scripts/mcp/dashboard_live.py`      | new file                                    | Polling dashboard script: queries MCP `worker_status` per lane, prints table with composite state, token burn, cycle count, attention flags.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `mk/lane-worker.mk`                  | new `dashboard-live` target                 | Launch `scripts/mcp/dashboard_live.py` with task-ref and lane-ids from manifest.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py`         | `_build_prompt()` ~L540-615                 | After building the prompt, call `_measure_context_utilization()` to compute utilization and domain signal ratios. Return metrics as a second value alongside the rendered prompt string so `worker_daemon.py` can record them directly without relying on prompt-comment extraction.                                                                                                                                                                                                                                                                                                                                                                               |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py`         | new `_measure_context_utilization()`        | Compute `prompt_tokens_approx`, `utilization_ratio`, `domain_signal_ratio`, and `pressure` level from the rendered prompt and section sizes.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py`         | `_prompt_budget_section()` ~L362-535        | Track per-section character counts in a dict and pass to `_measure_context_utilization()`. Already computes `_approx_chars()` per section; collect into a return value.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`       | `_record_observability()` ~L646-656         | Include `context_utilization` metrics (utilization_ratio, domain_signal_ratio, pressure) received from `_build_prompt()` return value in the observability record.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `scripts/mcp/lane_manifest.py`       | `get_lane_config()` ~L320-360               | Add `model_context_window` field (default 128000) read from manifest JSON.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |

## Related Files

| File                                                                            | Note                                                                                                                                                                                         |
| ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/archive/retrospectives/backend-domain-lane-closure-and-orchestration-retrospective.md` | Root cause analysis and 9 recommendations that motivated this plan.                                                                                                                          |
| `docs/tasks/8.0/orchestration-tui-monitoring-task-plan.md`                      | Full Textual TUI plan; deferred until this plan's event vocabulary stabilizes. Shares the event aggregation model.                                                                           |
| `logs/worker-daemon/`                                                           | Existing JSONL event stream; new events (`scope_violation`, `token_burn_warning`, `worker_stopped`, `exhaustion_streak`) append here.                                                        |
| `logs/daemon/orchestrator.jsonl`                                                | Orchestrator event stream; new `lane_unhealthy` events append here.                                                                                                                          |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`                       | MCP tools that surface worker status; `worker_stop()` delegates to `daemon_stop()` which this plan fixes.                                                                                    |
| `packages/agent-handoff-mcp/tests/test_worker_daemon.py`                        | Existing test `test_daemon_status_marks_stale_lock()` validates stale detection; new tests needed for lock cleanup on stop.                                                                  |
| `config/lane-orchestration/`                                                    | Lane manifest JSON files; add `token_burn_threshold` field.                                                                                                                                  |
| `mk/lane-worker.mk`                                                             | Scope checking at commit time (line ~160-195); this plan adds scope checking at execution time.                                                                                              |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py`                                                    | Prompt construction with bounded item limits and `_approx_chars()` sizing. Context utilization measurement hooks into this file.                                                             |
| `docs/agentic/playbooks/lane-scoped-context.md`                                 | Architecture doc defining session modes (`fresh_turn`, `shared_lane`) and context budget rules. Context freshness additions must stay consistent with this doc.                              |
| `packages/codex-subagent-bridge/src/codex_subagent_bridge.py`                   | Bridge that manages Codex sessions and reports `model_context_window` and per-turn token usage. Each `_run_subagent_shared()` call starts a fresh thread; no session-reset changes required. |

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID               | Owned Paths                                                                                                                                     | Upstream Dependencies                             | Required Tests                                                                                                   |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `daemon-policy`       | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`, `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_exec.py`, `scripts/mcp/_env.py`, `scripts/mcp/lane_manifest.py`, `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py` | None                                              | `PYENV_VERSION=description-service pytest scripts/mcp/tests/ -k "scope or exhaust or burn or effort or context"` |
| `worker-ctl`          | `scripts/mcp/worker_daemon_ctl.py`, `packages/agent-handoff-mcp/tests/test_worker_daemon.py`                                                    | None                                              | `PYENV_VERSION=description-service pytest packages/agent-handoff-mcp/tests/test_worker_daemon.py`                |
| `orchestrator-health` | `scripts/mcp/orchestrator_daemon.py`, `scripts/mcp/orchestrator_guidance_policy.py`                                                             | `daemon-policy` (event vocabulary)                | `PYENV_VERSION=description-service pytest scripts/mcp/tests/ -k "orchestrator or health"`                        |
| `dashboard`           | `scripts/mcp/dashboard_live.py`, `mk/lane-worker.mk`                                                                                            | `daemon-policy`, `worker-ctl` (events to display) | Manual smoke test against a live task with active + stale lanes                                                  |

### Merge Order

`daemon-policy` + `worker-ctl` (parallel, no overlap) -> `orchestrator-health` -> `dashboard`

### Manifest

Initialize the lane manifest for this task:

```bash
make lane-manifest-init TASK=orchestration-hardening LANE_IDS='daemon-policy worker-ctl orchestrator-health dashboard' TASK_PLAN=docs/tasks/8.0/orchestration-hardening-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred)**: Use MCP worker lifecycle tools with `backend="codex-subagent"`. The `daemon-policy` and `worker-ctl` lanes are narrow enough for `gpt-5.4-mini` at `medium` effort. The `orchestrator-health` lane should use `high` effort since it involves cross-module reasoning.
- **Shell fallback**: Use `make lane-open`, `make lane-run`, `make lane-handoff`, and `make lane-intake` from the orchestrator root.
- **Self-dogfooding**: Once `dashboard` is merged, use `make dashboard-live` to monitor the remaining lanes of this very task.

---

# Consolidated Checklist

## Completed

- [x] Backend-domain lane closed; retrospective published at `docs/archive/retrospectives/backend-domain-lane-closure-and-orchestration-retrospective.md`.
- [x] TUI monitoring plan reviewed; 9 findings recorded in MCP handoff under `orchestration-tui-monitoring` task.
- [x] Root cause analysis identified scope drift, exhaustion loops, effort inversion, and stale locks as the four structural failures.

## Phase 0: Scaffolding

- [x] Add `_check_scope_violations()` and `_matches_any_owned_path()` stubs in `lane_exec.py` with `raise NotImplementedError`.
- [x] Add `_update_exhaustion_streak()` and `_check_token_burn()` stubs in `worker_daemon.py`.
- [x] Add `_escalate_effort()` stub in `_env.py`.
- [x] Add `_cleanup_lock()` and `_emit_stopped_event()` stubs in `worker_daemon_ctl.py`.
- [x] Add `_check_lane_health()` stub in `orchestrator_daemon.py`. _(Full implementation added, not just a stub.)_
- [x] Add `token_burn_threshold` field to lane manifest schema in `lane_manifest.py`.
- [x] Add `model_context_window` field to lane manifest schema in `lane_manifest.py`.
- [x] Add `_measure_context_utilization()` stub in `lane_prompt.py` with `raise NotImplementedError`.
- [x] Create hardening test coverage for scope enforcement, exhaustion streak, token burn, effort escalation, lock cleanup, and context utilization in `scripts/mcp/tests/test_hardening.py`.
- [x] Verify hardening modules import cleanly via `pytest -q scripts/mcp/tests/test_hardening.py`.

## Phase 1: Scope Enforcement

- [x] Implement `_check_scope_violations()` in `lane_exec.py`: collect staged, unstaged, and untracked changes using `git diff --name-only HEAD` plus `git ls-files --others --exclude-standard` (matching `review_runner.py::_changed_files()` semantics), match against `effective_owned_paths` (falling back to `owned_paths`), return violation list.
- [x] Implement `_matches_any_owned_path()`: glob-match file path against owned_paths patterns, handle `**` and trailing `/`.
- [x] In `run_lane_exec()`, call scope check after execution completes. If violations found, set `scope_violation: true` and `scope_violations: [files]` in result dict.
- [x] In `worker_daemon.py` review loop, before entering review: if result has `scope_violation`, skip review, emit `scope_violation` JSONL event with file list, mark turn as failed with structured blocker. _(Scope violation gate at ~L1018; event is JSONL log not structured observability; see L-GAP-REVIEW-03.)_
- [x] In `orchestrator_daemon.py` `_dispatch_from_task_plan()`, store `effective_owned_paths` as a JSON-encoded string in the `artifacts` list of the dispatch lane message, e.g. `artifacts=[json.dumps({"type": "owned_paths_override", "paths": [...]})]`, when dispatching a narrowed scope. The `artifacts` field accepts `list[str]`; `_coerce_string_list()` preserves strings but silently drops non-string items like dicts.
- [x] In `lane_exec.py`, read `effective_owned_paths` by calling `list_lane_messages` for the lane, filtering to the most recent `orchestrator_to_worker` message, iterating its `artifacts` list and attempting `json.loads()` on each string to find the first parsed object with `type == "owned_paths_override"`; prefer its `paths` list over the manifest `owned_paths` when present. Non-parseable artifact strings are skipped.
- [x] Tests: scope violation detected for out-of-scope file; no violation for in-scope file; glob patterns match correctly; `effective_owned_paths` override works.

## Phase 2: Convergence Policy

- [x] Implement `_update_exhaustion_streak()` in `worker_daemon.py`: read/increment counter in status file, reset on convergence.
- [x] Reset `exhaustion_streak` and cumulative token burn counters in the status file when the worker daemon starts a new session (identified by a new `run_id`). Counters are scoped per daemon session; the orchestrator delivers new assignments via `record_lane_message` without restarting the worker, so counter scope is per-session, not per-assignment. A long-running session with multiple assignments accumulates counts across them -- this is acceptable because exhaustion and burn anomalies in a long session are still real health signals.
- [x] After `review_exhausted` event, call `_update_exhaustion_streak()`. If streak >= 2, set `attention_required: true`. If streak >= 3, force transition to `needs_orchestrator_decision` and stop further cycles. _(Streak tracking at ~L1214; forced stop is via orchestrator gate, not worker self-stop.)_
- [x] Emit `exhaustion_streak` JSONL event with streak count, run*id, and lane_id. *(~L1217)\_
- [x] Implement `_check_token_burn()`: compare cumulative token total against `token_burn_threshold` from lane config (default 2M). Emit `token_burn_warning` event if exceeded. Set `attention_required: true`.
- [x] Call `_check_token_burn()` after each `_record_observability()` call in the main loop.
- [x] Implement `_escalate_effort()` in `_env.py`. Extend `resolve_auto_reasoning_effort()` to accept `previous_run_exhausted: bool`. If true, escalate one level and add reason "escalated after exhaustion."
- [x] In `worker_daemon.py`, pass `previous_run_exhausted` state to `_fetch_mcp_lane_params()` / effort resolution at each cycle start. _(Fixed by M-GAP-REVIEW-01; wired at worker_daemon.py:829.)_
- [x] In `orchestrator_daemon.py` `_ensure_lane_workers()`, read lane status for `exhaustion_streak >= 2`. If unhealthy, skip auto-start, emit `lane_unhealthy`, require orchestrator decision.
- [x] Tests: streak increments on exhaustion, resets on convergence; attention flag set at streak 2; forced stop at streak 3; effort escalates after exhaustion; token burn warning fires at threshold; orchestrator skips unhealthy lane auto-start. _(TestExhaustionStreak 4, TestCheckTokenBurn 3, TestEscalateEffort 8, TestEnsureLaneWorkersExhaustionGate 2, TestExhaustionStreakEvent 2. Forced-stop test is coverage of the log emission only.)_

## Phase 2.5: Context Freshness

- [x] In `lane_prompt.py` `_prompt_budget_section()`, collect per-section character counts into a dict instead of only printing them. Return the dict alongside the rendered section.
- [x] Implement `_measure_context_utilization()` in `lane_prompt.py`: estimate prompt token count (chars / 4), compute `utilization_ratio` against `model_context_window` from lane config, compute `domain_signal_ratio` from section sizes, derive `pressure` level (`normal` / `elevated` / `high`).
- [x] In `_build_prompt()`, call `_measure_context_utilization()` after assembly. Return metrics as a second value alongside the rendered prompt string; do not embed them in the prompt itself.
- [x] Emit `context_pressure` JSONL event when pressure is `elevated` or `high`, including `utilization_ratio`, `domain_signal_ratio`, `prompt_tokens_approx`, and `model_context_window`.
- [x] In `_record_observability()`, include `context_utilization` sub-dict (utilization*ratio, domain_signal_ratio, pressure) received from the `_build_prompt()` return value. *(Implemented; \_record*observability accepts context_utilization param, passed through post-exec at ~L946.)*
- [x] In `lane_manifest.py` `get_lane_config()`, read `model_context_window` (default 128000) from manifest JSON.
- [x] Tests: context utilization computed correctly for known prompt sizes; pressure transitions at thresholds; observability record includes context metrics received from `_build_prompt()` return value. _(TestMeasureContextUtilization 5 tests + TestObservabilityContextUtilization 3 tests + TestPressureLabels 4 tests.)_

## Phase 3: Worker Stop Integrity

- [x] Implement `_cleanup_lock()` in `worker_daemon_ctl.py`: delete `worker-{lane_id}.lock` from state_dir.
- [x] Call `_cleanup_lock()` in `daemon_stop()` after signaling the process.
- [x] Implement `_emit_stopped_event()`: append `{"event": "worker_stopped", "lane": lane_id, "ts": iso_now, "signal": sig_name}` to worker JSONL log.
- [x] Call `_emit_stopped_event()` in `daemon_stop()` after cleanup.
- [x] Update `daemon_status()` to return consistent state: if status file says "stopped" and lock file is absent, report `lock.held: false`.
- [x] Tests: lock file removed after `daemon_stop()`; `worker_stopped` event in JSONL; `daemon_status()` reports `lock.held: false` after stop; stale lock detected when process dies without clean stop. _(TestCleanupLock 4 tests cover lock cleanup and emit_stopped_event.)_

## Phase 4: Dashboard

- [x] Create `scripts/mcp/dashboard_live.py` with polling loop: query `worker_status` per lane via `agent-handoff-mcp` CLI, print formatted table.
- [x] Table columns include lane, state, health, cycle, model, effort, tokens, context pressure, exhaustion streak. _(L-GAP-REVIEW-04 fixed: CYC and MODEL columns added. Attention/stale-lock flags omitted as separate columns; HEALTH column covers those states.)_
- [x] Add `make dashboard-live` target in `mk/lane-worker.mk`.
- [ ] Smoke test against a live task with at least one active lane. _(Deferred: manual verification; will be exercised during context-retrieval task execution.)_

## Phase 5: Lane Health Scoring (orchestrator-side)

- [x] Implement `_check_lane_health()` in `orchestrator_daemon.py`: compute health from exhaustion streak, scope violation history, context pressure. _(orchestrator_daemon.py:511)_
- [x] Return health enum: `healthy` / `degraded` / `unhealthy`.
- [x] Route `unhealthy` lanes to orchestrator decision queue with recommended action (`split_lane`, `close_lane`, `promote_model`, `fresh_worktree`). _(via \_ensure_lane_workers unhealthy gate)_
- [x] Emit `lane_health_changed` event when health transitions. _(Added in this session: tracks prev_health per lane, emits on change.)_
- [x] Surface lane health in `dashboard_live.py` output. _(HEALTH column implemented.)_
- [x] Tests: health degrades on exhaustion streak; health degrades on scope violations; health degrades on sustained high context pressure; recommended actions match conditions. _(TestCheckLaneHealth 9 tests + TestLaneHealthChangedEvent 3 tests.)_

## Phase 6: Tests

- [x] Unit test `_check_scope_violations()`: in-scope, out-of-scope, mixed, empty (no owned*paths). *(TestCheckScopeViolations 4 tests; uses real git repo, not mocked output; mixed test added this session.)\_
- [x] Unit test `_matches_any_owned_path()` with glob patterns: `**`, trailing `/`, nested paths. _(Added test_sibling_prefix_not_matched for M-PREFIX-01 fix; 66 tests pass.)_
- [x] Unit test `_update_exhaustion_streak()`: increment, reset, threshold behavior.
- [x] Unit test `_check_token_burn()`: below threshold, at threshold, above threshold.
- [x] Unit test `_escalate_effort()`: each level, already at max.
- [x] Unit test `_cleanup_lock()`: file exists, file already absent.
- [x] Unit test `_emit_stopped_event()`: event structure, JSONL append.
- [x] Unit test `_check_lane_health()`: healthy, degraded, unhealthy transitions. _(TestCheckLaneHealth 9 tests.)_
- [x] Unit test `_measure_context_utilization()`: known prompt sizes produce correct ratios; pressure thresholds fire correctly.
- [x] ~~Integration test: full daemon cycle with scope violation injected.~~ _(Moved to orchestration-context-retrieval-task-plan.md Phase 6; requires mocking the full run_worker_daemon() monolith. Unit coverage: TestCheckScopeViolations + TestScopeViolationEventName.)_
- [x] ~~Integration test: full daemon cycle exhausting 3 times.~~ _(Moved to orchestration-context-retrieval-task-plan.md Phase 6; same reason. Unit coverage: TestExhaustionStreak + TestExhaustionStreakEvent + TestEnsureLaneWorkersExhaustionGate.)_

## Stretch Goals

- [x] Add `salvage_and_close` MCP action: freeze lane, classify changed files by ownership, generate salvage candidate groups, close lane with preserved worktree.
- [x] Add `redispatch_mode: fresh_worktree` to orchestrator: create clean sibling worktree from root, replay only accepted files.
- [x] Add `effective_owned_paths` per-dispatch narrowing in MCP lane dispatch tools (would require extending `LaneMessagePayload.artifacts` to support structured objects natively, avoiding the JSON-string envelope workaround).
- [x] Add review-finding diff across runs: compare finding IDs between consecutive runs to distinguish "new issues found" from "same issues re-found."
- [x] Promote `dashboard_live.py` to a Textual TUI with interactive panes (per `orchestration-tui-monitoring-task-plan.md`), once event vocabulary is stable.

## Success Criteria

- [x] A worker that modifies files outside `owned_paths` gets its turn rejected with a `scope_violation` event before review runs. _(Scope violation gate at ~L1018 skips review; event is JSONL log.)_
- [x] After 2 consecutive `review_exhausted` runs, the lane is flagged `attention_required` and the orchestrator does not auto-start it.
- [x] After exhaustion, the next run's reasoning effort is automatically one level higher than the exhausted run's.
- [x] `worker-stop` leaves lock cleared, PID nulled, and `worker_stopped` event in the JSONL log. No contradictory state.
- [x] `make dashboard-live` shows per-lane composite state, token burn, and attention flags updating every 10 seconds. _(Dashboard implemented; column set differs from spec; see L-GAP-REVIEW-04.)_
- [x] Cumulative token spend exceeding 2M per lane triggers `token_burn_warning` event and `attention_required` flag.
- [x] The orchestrator daemon skips auto-start for lanes with `exhaustion_streak >= 2` and emits `lane_unhealthy`.
- [x] Every dispatched prompt's `_build_prompt()` call computes context-utilization metrics (`utilization_ratio`, `domain_signal_ratio`, `pressure`) via `_measure_context_utilization()`. These metrics are recorded in the `context_utilization` sub-dict of observability records without embedding anything in the prompt string. _(Metrics computed in lane_prompt.py, recorded via \_record_observability with context_utilization param.)_
- [x] Context pressure of `high` (utilization > 40% AND domain signal < 50%) contributes to lane health degradation. _(`_check_lane_health` returns `degraded`/`split_lane` for pressure==`high`.)_
- [x] `make dashboard-live` shows context pressure per lane alongside token burn.
