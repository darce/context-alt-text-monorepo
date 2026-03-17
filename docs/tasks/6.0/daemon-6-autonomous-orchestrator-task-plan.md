# Daemon 6: Autonomous Multi-Lane Orchestrator

## Problem Statement

The orchestrator daemon already handles multi-lane dispatch, intake, refresh, and verification internally. However, the Makefile guard chain and CLI interface still require explicit `TASK=` and `LANE=` arguments, creating a contradiction: the daemon that orchestrates all lanes cannot start without naming a single lane it does not use.

This makes the daemon unusable without memorizing implicit arguments:

```
make orchestrator-daemon TASK=phase-5-retention-export-and-audit-controls SINGLE_PASS=1

  LANE is required.
  No lane could be inferred from branch feature/6.0.2-retention-export.
```

The workaround is passing an arbitrary LANE that the daemon ignores, which is confusing and error-prone. The daemon should infer its task from context and not require a lane at all.

## Workflow Principles

- **One orchestrator per task, zero lane affinity.** The daemon discovers all lanes from the task manifest and assigns work based on manifest routing, capacity, and merge order. It must never be scoped to a single lane.
- **Task inference from context.** The orchestrator should resolve its task from (1) an explicit `TASK=` override, (2) the MCP active task, or (3) the sole manifest in `config/lane-orchestration/`. Failing all three, it should exit with a clear error listing available tasks.
- **Lane routing is the daemon's job.** Every dispatched slice is routed to a lane by the manifest's `heading_to_lane`, `plan_routing_hints`, and `routing` tables. The operator never specifies which lane receives work.
- **Segmented context over monolithic windows.** The orchestrator decomposes a task plan into lane-appropriate slices so each worker agent operates on a bounded context window scoped to its domain, not the entire codebase.
- **Persistent daemons, disposable execution cycles.** One long-lived worker daemon should remain resident per lane. Each work cycle may spawn a short-lived `codex exec` child, but orchestrator/worker round-trips should clean up MCP messages, temp/result artifacts, and stale child processes rather than tearing down and recreating the daemon itself.

## Current State Analysis

### What already works

The daemon's Python code is correctly multi-lane within a single-task singleton process:

- `_dispatch_from_task_plan()` scans unchecked plan items, selects the next dispatchable item, routes it to a lane via the manifest, and then returns after one dispatch. It respects lane capacity (one active assignment per lane) and escalates ambiguous items.
- `_resolve_guidance_cycle()` processes worker-to-orchestrator messages across all lanes, deduplicating per lane.
- `_poll_merge_ready_lanes()` discovers all merge-ready lanes and sorts them by `merge_order`.
- Intake, refresh, and cross-lane verification all iterate over the manifest's lane set.

### What is broken

1. **Guard chain requires LANE.** The `orchestrator-daemon` Makefile target depends on `lane-orchestrator-guard`, which inherits from `lane-guard`. `lane-guard` unconditionally requires `LANE`. The daemon never uses LANE.

2. **No orchestrator-specific guard.** There is no guard that validates just TASK + orchestrator-root without also requiring LANE. Every orchestrator-only target that needs TASK but not LANE must work around this.

3. **Task inference is fragile from orchestrator root.** The Makefile resolves `TASK` as `ACTIVE_TASK` (the MCP singleton) when `IN_ORCHESTRATOR_ROOT=1`. If the singleton points at a different task (e.g., after switching active tasks for a code review), the daemon targets silently pick up the wrong task.

4. **CLI requires explicit `--task-ref`.** The `orchestrator_daemon.py run` command declares `--task-ref` as `required=True`. It could fall back to the MCP active task or infer from available manifests.

5. **`daemon-pause`, `daemon-resume`, and `daemon-status` are under-guarded and inconsistently wrapped.** They currently have no Makefile guard prerequisites and still use `WORKTREE_ROOT_REAL` for the Python script path, even though they correctly use `ORCHESTRATOR_ROOT` for `--state-dir` and `--log-dir`. The main gap is operational consistency from any worktree, not broken state-dir resolution.

## Proposed Solution

### Phase 1: Makefile guard fix (the critical path)

Create a new `task-guard` that validates only TASK (not LANE):

```makefile
task-guard:
	@if [ -z "$(TASK)" ]; then \
		echo "TASK is required."; \
		echo "No active task could be inferred from MCP state."; \
		echo "Supported tasks: $(SUPPORTED_TASKS)"; \
		exit 1; \
	fi
	@if [ -z "$(TASK_LANES)" ]; then \
		echo "Unsupported TASK: $(TASK)"; \
		echo "Supported task manifests: $(SUPPORTED_TASKS)"; \
		exit 1; \
	fi
```

Redefine `lane-orchestrator-guard` to depend on `task-guard` instead of `lane-guard`:

```makefile
lane-orchestrator-guard: task-guard
	@if [ "$(IN_ORCHESTRATOR_ROOT)" != "1" ]; then \
		echo "This command must run from the orchestrator root."; \
		exit 1; \
	fi
```

This unblocks `make orchestrator-daemon` without LANE while preserving the LANE requirement for worker targets that actually need it.

### Phase 2: Robust task inference

Improve the Makefile's TASK resolution chain for the orchestrator root:

1. Explicit `TASK=...` override (highest priority)
2. MCP active task via `ACTIVE_TASK`
3. Sole manifest auto-select: if `config/lane-orchestration/` contains exactly one manifest, use its `task_ref`

Add a `list-tasks` diagnostic to the Makefile so operators can see available tasks. This is only a thin wrapper around existing `lane_config.py list-tasks` / `SUPPORTED_TASKS` plumbing:

```
make list-tasks
  phase-5-retention-export-and-audit-controls
```

The Python CLI should mirror this: make `--task-ref` optional with fallback to MCP active task, then sole-manifest auto-select. Fail with a clear listing when ambiguous. The `make orchestrator-daemon` wrapper must also omit `--task-ref` when `TASK` is empty, otherwise the CLI fallback chain can never run.

### Phase 3: Daemon lifecycle commands

Commit this phase to **singleton daemon semantics**.

- `daemon-pause`, `daemon-resume`, and `daemon-status` stay global to the orchestrator root.
- They should use `ORCHESTRATOR_ROOT` consistently and work from any worktree.
- They should not claim per-task disambiguation in this task.

If task-scoped orchestrator daemons are ever needed later, that should be a separate task that explicitly introduces task-scoped lock, pause-sentinel, and log paths.

### Phase 4: Operational polish

- Add a dedicated `lanes_discovered` startup log line listing all manifest lanes: `[INFO] lanes_discovered lanes=backend-domain,backend-http,wp-proxy,frontend`
- Keep the existing per-dispatch logging and ensure it includes the target lane: `[INFO] task_plan_dispatch lane=backend-domain plan_item_id=...`
- `make list-lanes TASK=<task>` already exists through `lane_config.py list-lanes`. Do not duplicate it with a second `--list-lanes` subcommand in this task unless a richer topology view is explicitly required.
- Define and implement round-trip cleanup for each orchestrator/worker cycle:
  - **Dispatch-message ownership stays with the orchestrator.** Workers do not close `orchestrator_to_worker` messages. The orchestrator closes them in guidance resolution and after successful intake so there is a single owner for dispatch lifecycle.
  - Prune result JSON artifacts after successful handoff -- `worker_daemon.py` owns deleting `final_result_path` after `_run_final_handoff()` returns, guarded for `FileNotFoundError`
  - Verify that stale child `codex exec` processes cannot accumulate under a long-lived worker daemon (currently `proc.communicate()` blocks until the child exits, so this is already safe for normal operation; edge case is daemon SIGKILL, handled by `daemon_stop --force` recursive tree kill)
  - Close stale dispatch messages during the intake path (`_intake_lane` or its caller), not only during the guidance resolution path
  - Optional: add JSONL log rotation policy (truncate at startup or cap file size) to prevent unbounded growth of `logs/worker-daemon/worker-{lane_id}.jsonl`

## Functions to Change

| File | Target | Change |
| --- | --- | --- |
| `mk/lane-guards.mk` | `task-guard` | New guard: validates TASK + TASK_LANES only |
| `mk/lane-guards.mk` | `lane-orchestrator-guard` | Depend on `task-guard` instead of `lane-guard` |
| `mk/handoff.mk` | `orchestrator-daemon` | Omit `--task-ref` when `TASK` is empty so CLI inference can run; no `LANE` requirement |
| `mk/handoff.mk` | `daemon-pause` | Use `ORCHESTRATOR_ROOT`; either keep global singleton semantics or pass task-scoped state paths if Phase 3 chooses task-scoped daemons |
| `mk/handoff.mk` | `daemon-resume` | Use `ORCHESTRATOR_ROOT`; either keep global singleton semantics or pass task-scoped state paths if Phase 3 chooses task-scoped daemons |
| `mk/handoff.mk` | `daemon-status` | Use `ORCHESTRATOR_ROOT`; either keep global singleton semantics or pass task-scoped state paths if Phase 3 chooses task-scoped daemons |
| `Makefile` | TASK inference | Add sole-manifest fallback after `ACTIVE_TASK` |
| `scripts/mcp/orchestrator_daemon.py` | `_parse_args` | Make `--task-ref` optional; add fallback chain |
| `scripts/mcp/orchestrator_daemon.py` | `orchestrator_loop` | Log discovered lanes at startup; keep single-dispatch-per-cycle semantics unless batched dispatch is explicitly added |
| `scripts/mcp/orchestrator_lanes.py` | `_intake_lane` or caller cleanup | After successful intake, close open `orchestrator_to_worker` messages for that lane so direct intake matches guidance-resolution cleanup |
| `scripts/mcp/worker_daemon.py` | `worker_loop` | Delete consumed result JSON files after `_run_final_handoff()` returns; keep worker read-only on dispatch-message lifecycle |

## Related Files (reference, no changes expected)

| File | Role |
| --- | --- |
| `scripts/mcp/orchestrator_guidance.py` | Worker guidance classification and resolution |
| `scripts/mcp/lane_manifest.py` | Manifest loading, `task_plan_path`, `merge_order` |
| `scripts/mcp/lane_config.py` | `infer-task`, `infer-lane`, `list-tasks` CLI |
| `config/lane-orchestration/*.json` | Lane manifests (source of truth for lane topology) |
| `scripts/mcp/lane_prompt.py` | Worker prompt generation (downstream of dispatch) |
| `scripts/mcp/task_plan_parser.py` | Task plan parsing, normalization, lane mapping |

## Consolidated Checklist

### Phase 1: Guard fix

- [ ] Add `task-guard` to `mk/lane-guards.mk` that validates TASK and TASK_LANES without requiring LANE
- [ ] Change `lane-orchestrator-guard` to depend on `task-guard` instead of `lane-guard`
- [ ] Verify `make orchestrator-daemon TASK=phase-5-retention-export-and-audit-controls SINGLE_PASS=1 DRY_RUN=1` works without LANE
- [ ] Verify `make lane-intake`, `make lane-commits`, and other `lane-orchestrator-guard` consumers still work with LANE (they inherit it from their own prerequisites or callers)

### Phase 2: Task inference

- [ ] Add sole-manifest fallback to Makefile TASK resolution: when `ACTIVE_TASK` is empty and exactly one manifest exists, use its `task_ref`
- [ ] Make `--task-ref` optional in `orchestrator_daemon.py _parse_args`; add inference chain: CLI arg, then MCP active task, then sole manifest, then fail with listing
- [ ] Update `mk/handoff.mk` so `make orchestrator-daemon` only passes `--task-ref` when `TASK` is non-empty
- [ ] Add `make list-tasks` target that prints the already-computed `SUPPORTED_TASKS`
- [ ] Verify `make orchestrator-daemon SINGLE_PASS=1 DRY_RUN=1` works with no explicit TASK when the active MCP task is set
- [ ] Verify the daemon errors clearly when no task can be inferred and multiple manifests exist

### Phase 3: Lifecycle commands

- [ ] Update `daemon-pause`, `daemon-resume`, and `daemon-status` to use `ORCHESTRATOR_ROOT` consistently and work from any worktree under global singleton semantics
- [ ] Verify lifecycle documentation, Make targets, and daemon status output all describe singleton orchestrator behavior consistently

### Phase 4: Operational polish

- [ ] Add `lanes_discovered` log line at daemon startup listing all manifest lanes
- [ ] Verify `task_plan_dispatch` log line includes the target `lane` field
- [ ] Verify a single pass dispatches the next eligible plan item cleanly
- [ ] Keep `orchestrator_to_worker` dispatch-message ownership on the orchestrator side only
- [ ] Delete result JSON artifacts after successful handoff from `worker_daemon.py`
- [ ] Close stale dispatch messages during the intake path (`_intake_lane` or its caller), not only during guidance resolution
- [ ] Optional: add JSONL log rotation policy for `logs/worker-daemon/worker-{lane_id}.jsonl`
- [ ] Verify stale `codex exec` child processes cannot accumulate under a long-lived worker daemon
- [ ] If batched multi-lane dispatch in one cycle is desired, add it explicitly to scope and cover it with tests
