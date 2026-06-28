# Worktree Orchestration Playbook

This playbook is the canonical agent-agnostic procedure for multi-lane worktree orchestration in this repo. Any orchestrator agent or human operator can follow it regardless of which execution backend is in use.

For Codex-specific bootstrap, backend configuration, model/reasoning-effort settings, and app-server session setup, see [host-adapters/worktree-codex-playbook.md](host-adapters/worktree-codex-playbook.md).

---

## Model

Three durable layers underpin lane orchestration:

- **MCP shared state**: canonical truth for task state, lane registrations, assignments, findings, blockers, and worker reports. Accessed through `workbay-handoff-mcp` and `workbay-orchestrator-mcp`.
- **Lane manifest**: each task's orchestration config at `config/lane-orchestration/<task-ref>.json`. Source of truth for lane IDs, branch names, owned paths, commit scope, verification commands, merge order, and resource hints.
- **Worktree isolation**: each lane runs on its own `codex/*` branch in a sibling worktree. Lanes cannot see each other's uncommitted work.

## Terminology

- **orchestrator root**: the main repo checkout, e.g. `${REPO_ROOT:-$PWD}`
- **worker worktree**: a sibling checkout created for one lane
- **task ref**: the active MCP task, e.g. `phase-5-retention-export-and-audit-controls`
- **lane id**: the worker slice name — vertical feature slice by default, e.g. `create-alt-text`, `edit-alt-text`; horizontal domain lanes (`backend-domain`, `frontend`) only for hard runtime isolation boundaries
- **lane manifest**: `config/lane-orchestration/<task-ref>.json`, source of truth for owned paths and branch names

## Lane Decomposition Strategy

**Default: vertical feature slices, not domain lanes.**

A lane owns a complete end-to-end path for one user-visible behavior (DB schema → service layer → API endpoint → UI component). Each lane can be independently tested and validated before merge. Horizontal domain lanes defer integration risk to merge time and prevent end-to-end validation until both lanes land.

| Pattern | Example lane ids | When to use |
|---------|-----------------|-------------|
| **Vertical (default)** | `create-alt-text`, `edit-alt-text`, `delete-alt-text` | Feature work crossing multiple layers |
| **Horizontal (exception)** | `backend-domain`, `frontend`, `wp-proxy` | Hard runtime isolation — separate service, no shared test surface |

When horizontal lanes are unavoidable, name them after the feature delivered (`auth-api-cleanup`), not the layer touched (`backend`).

**TDD within every lane:** every slice starts with a failing test via `make slice-start TEST_CMD="..."` before any implementation edit. See [lifecycle-map.md](../lifecycle-map.md) stages I2–I4.

## Task Manifests

Each task that uses lane automation defines its orchestration config at `config/lane-orchestration/<task-ref>.json`.

Initialize with:

```bash
make lane-manifest-init TASK=<task-ref> LANE_IDS='create-alt-text edit-alt-text' TASK_PLAN=docs/tasks/...md
```

The manifest drives:

- lane ids and branch names
- worktree path templates
- owned paths and commit scope
- required docs and verification commands
- merge order and dispatch routing hints
- `token_burn_threshold`: cumulative token ceiling before `token_burn_warning` events fire
- `model_context_window`: model context window size used for context utilization scoring

When a lane declares `app_root`, `owned_paths`, or `tooling_paths` that resolve to an app with `composer.json` or `package.json`, the lane runtime treats that as bootstrap/preflight metadata. New lanes inherit default dependency checks from those paths even when a manifest does not manually spell out `preflight_commands`.

## Command Surface

All `lane-*` commands work from the repo root and from app subdirectories via forwarding Makefiles. New lane targets never need to be registered in app Makefiles; `lane-%:` pattern rules auto-forward them.

### Orchestrator commands (run from orchestrator root)

```bash
make lane-open TASK=<task> LANE=<lane>                         # Create/open a lane
make lane-manifest-init TASK=<task> LANE_IDS='lane-a lane-b'   # Scaffold task manifest
make lane-dispatch TASK=<task> LANE=<lane> MESSAGE="..."       # Assign work
make handoff-dispatch TASK=<task>                              # Route findings/blockers/next actions to lanes
make handoff-inbox TASK=<task>                                 # Poll worker handoffs
make lane-commits TASK=<task> LANE=<lane>                      # Preview intake
make lane-intake TASK=<task> LANE=<lane>                       # Merge a lane
make lane-refresh TASK=<task> LANE=<lane>                      # Sync lane to root
make lane-list                                                 # List all lanes
make state                                                     # Full MCP state
make dashboard                                                 # Generate DASHBOARD.txt (human observatory view)
make orchestrator-daemon [TASK=<task>] [BACKEND=<backend>] [MODEL=<model>]
make artifact-list TASK=<task> [LANE=<lane>]                   # List indexed evidence
make artifact-search TASK=<task> QUERY="schema missing"        # Search indexed evidence
```

### Worker commands (run from worker worktree)

```bash
make lane-inbox                                                # Poll assignments
make lane-prompt                                               # Render actionable prompt
make lane-prompt EXTRA_ARGS=--include-lane-history             # Include recent lane decisions
make lane-prompt EXTRA_ARGS=--include-global-context           # Include compact task-wide context
make lane-check                                                # Run lane tests
make worker-daemon TASK=<task> LANE=<lane> [BACKEND=<backend>] [MODEL=<model>]
make worker-daemon-status                                      # Inspect lock/PID/log state
make worker-daemon-stop
make worker-daemon-resume
make worker-daemon-tail                                        # Tail the lane daemon log
make lane-handoff                                              # Commit + report + hand off
make lane-report STATUS=blocked MERGE_READY=0 SUMMARY="..." MESSAGE="..."
```

For MCP-capable hosts, the orchestration control surface is available directly via `workbay-orchestrator-mcp`:

- `orchestrator_start(task_ref, backend, poll_interval, single_pass, model=None)`
- `orchestrator_status()`, `orchestrator_stop()`, `orchestrator_pause()`, `orchestrator_resume()`
- `worker_start(task_ref, lane_id, backend, poll_interval, single_pass, session_mode, ...)`
- `worker_status(task_ref, lane_id)` — use `running`, `worker_state`, `attention_required`, `state_summary` together
- `dispatch_lane_work(task_ref, lane_id, model=None, backend=None, reasoning_effort=None)`
- `worker_event_history(task_ref, lane_id, limit=20)`

## Default Lane Split

Standard lane boundaries for this repo:

- `backend-domain`: `apps/prototype-description-service/db/**`, `recognition/domain/**`, `recognition/infrastructure/**`
- `backend-http`: `apps/prototype-description-service/recognition/interface_adapters/http/**`
- `wp-proxy`: `apps/prototype-wp-alt-context/src/**`, `apps/prototype-wp-alt-context/tests/Unit/**`
- `frontend`: `apps/prototype-wp-alt-context/js/**`

## Scope Enforcement

Scope enforcement is a runtime gate, not advisory. After each worker execution turn, `lane_exec.py` validates the diff against the lane's `effective_owned_paths` before submitting for review. A scope violation skips review entirely and emits a `scope_violation` JSONL event.

The orchestrator can narrow scope for a specific dispatch by embedding `effective_owned_paths` as an override artifact in the dispatch lane message. The worker should record a blocker or lane message for the orchestrator if it detects an out-of-scope need instead of editing files outside the lane.

## Lane Health

`lane_exec.py` and the orchestrator daemon score each lane as `healthy`, `degraded`, or `unhealthy`:

- **Exhaustion streak** (`exhaustion_streak >= 2`): lane is auto-gated; requires an explicit operator decision before work resumes. Recommended actions: `promote_model`, `split_lane`, `close_lane`, `fresh_worktree`.
- **Cumulative token burn** exceeding `token_burn_threshold`: emits `token_burn_warning` and sets `attention_required`.
- **Context pressure** (`utilization_ratio = prompt_tokens / model_context_window`): `normal` < 0.6, `elevated` 0.6-0.8, `high` > 0.8. Elevated pressure suggests trimming non-essential prompt sections; high risks truncation.

Health transitions emit `lane_health_changed` JSONL events.

## Worker Observability Events

The worker daemon emits structured JSONL events to `logs/worker-daemon/worker-<lane>.jsonl`:

| Event | Trigger |
| --- | --- |
| `scope_violation` | Files outside `owned_paths` detected post-execution |
| `exhaustion_streak` | Consecutive non-converged review cycles |
| `token_burn_warning` | Cumulative tokens exceed `token_burn_threshold` |
| `worker_stopped` | Clean shutdown with lock cleanup |
| `context_pressure` | Prompt consuming unsafe fraction of context window |
| `lane_health_changed` | Health state transition (healthy/degraded/unhealthy) |

Use `worker_event_history(task_ref, lane_id, limit=20)` via MCP to query recent events without tailing log files.

## Worker States

Interpret `worker_status(...)` from these fields together: `running`, `worker_state`, `attention_required`, `state_summary`.

| State | Meaning |
| --- | --- |
| `idle` | No actionable lane work exists right now |
| `waiting_for_orchestrator` | Worker submitted a handoff; waiting for intake or redispatch |
| `handoff_failed` | Execution turn completed; final handoff/report step failed and must be retried |
| `paused` | Worker process stopped; can be resumed |
| `stopped` | No worker daemon running for this lane |

`handoff_failed` is sticky. Fix the MCP/handoff problem first, then restart the daemon. A fresh lane message alone does not reliably clear the saved-result state.

## Recipes

### Open a lane

```bash
make lane-open TASK=<task-ref> LANE=<lane>
# Verifies/creates lane in MCP, prints brief, polls inbox, opens subshell in worktree
```

To stay in the orchestrator root:

```bash
make lane-open TASK=<task-ref> LANE=<lane> ENTER_SHELL=0
```

### Dispatch work

```bash
make lane-dispatch TASK=<task-ref> LANE=<lane> MESSAGE="Wire the retention router and verify pytest + mypy."
```

Workers see it on the next `make lane-inbox`. After recording findings or blockers from root, route them with:

```bash
make handoff-dispatch TASK=<task-ref>
```

Poll for worker-to-orchestrator messages with:

```bash
make handoff-inbox TASK=<task-ref>
```

### Preview and intake a lane

```bash
make lane-commits TASK=<task-ref> LANE=<lane>  # review diff before merging
make lane-intake TASK=<task-ref> LANE=<lane>   # merge and close lane
```

### Prompt shaping

`make lane-prompt` is narrow by default: assignment inbox, runtime guidance, compact dependency briefs, latest report, and a "Prompt Budget" section.

- Escalate to `--include-lane-history` only when recent lane-local decisions or verification history are required to unblock a turn.
- Escalate to `--include-global-context` only when lane-local state plus briefs are insufficient.
- Send a compact orchestrator brief instead of replaying whole transcripts into the worker prompt when cross-lane context is needed.

---

## Canonical Policy

- [instructions.md](../instructions.md): task startup and handoff policy
- [rules/development-workflow.md](../rules/development-workflow.md): cross-boundary, slice, and review-readiness rules
- [lane-scoped-context.md](lane-scoped-context.md): prompt budget and context rules for workers
