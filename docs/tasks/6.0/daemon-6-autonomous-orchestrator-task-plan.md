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
- **Persistent daemons, disposable execution cycles.** One long-lived worker daemon should remain resident per lane. Each work cycle may spawn a short-lived execution child (today `codex exec`, later other backends), but orchestrator/worker round-trips should clean up MCP messages, temp/result artifacts, and stale child processes rather than tearing down and recreating the daemon itself.
- **Agent-agnostic execution.** The orchestration and communication layers (MCP handoff, lane manifests, worktree isolation, merge ordering) must not depend on a specific agent runtime. The execution layer (`lane_exec.py`, `review_runner.py`) is the only surface that knows how to invoke an agent. New execution backends (Codex subagents, other LLM runtimes) plug in at that seam without touching orchestration logic.

## Current State Analysis

### What already works

The daemon's Python code is correctly multi-lane within a single-task singleton process:

- `_dispatch_from_task_plan()` scans unchecked plan items, selects the next dispatchable item, routes it to a lane via the manifest, and then returns after one dispatch. It respects lane capacity (one active assignment per lane) and escalates ambiguous items.
- `_resolve_guidance_cycle()` processes worker-to-orchestrator messages across all lanes, deduplicating per lane.
- `_poll_merge_ready_lanes()` discovers all merge-ready lanes and sorts them by `merge_order`.
- Intake, refresh, and cross-lane verification all iterate over the manifest's lane set.

### What was broken

1. **Guard chain required LANE.** Fixed in Phase 1: `lane-orchestrator-guard` now depends on `task-guard`, so `make orchestrator-daemon` no longer needs a dummy lane.

2. **No orchestrator-specific guard.** Fixed in Phase 1: `task-guard` now validates TASK + manifest existence without requiring LANE.

3. **Task inference was fragile from orchestrator root.** Fixed in Phase 2: Makefile layer falls back through explicit `TASK`, MCP active task, then `SOLE_TASK`, and the Python CLI mirrors that chain via `_resolve_task_ref()`.

4. **CLI required explicit `--task-ref`.** Fixed in Phase 2: `orchestrator_daemon.py run` accepts an omitted task ref and resolves it from MCP state or a sole manifest before failing with a clear task listing.

5. **Lifecycle commands were inconsistent about singleton semantics.** Fixed in Phase 3: `daemon-pause`, `daemon-resume`, and `daemon-status` consistently operate on `ORCHESTRATOR_ROOT` and expose singleton-root status paths.

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

### Phase 5: Subagent execution backend

Codex desktop app now offers in-process subagents as an alternative to `codex exec` subprocess invocation. This phase adds a backend abstraction to the execution layer so both subprocess and subagent execution are supported without touching orchestration or communication.

Codex subagents are the first alternate backend, not the permanent shape of the abstraction. The intent is to name and preserve an execution seam that can eventually support non-Codex runtimes without rewriting MCP coordination, lane topology, or worktree automation.

#### Architectural context

The current execution coupling to Codex CLI is narrow and confined to two files:

- `lane_exec.py`: `find_codex()` (binary lookup), `run_lane_exec()` (subprocess invocation via `codex exec -C <worktree> --output-schema <schema> -o <result> -`), `_run_codex_process()` (heartbeat wrapper)
- `review_runner.py`: `run_review()` (subprocess invocation with review prompt + output schema)

Everything above these two files -- MCP handoff, lane manifests, worker daemon loop, orchestrator dispatch/intake/refresh, prompt rendering, schema definition, result parsing, and the handoff pipeline -- is already agent-independent. The prompt-in/JSON-out contract is the stable interface.

#### What subagents replace vs what stays

| Concern                             | Stays as-is                                   | Changes                                                       |
| ----------------------------------- | --------------------------------------------- | ------------------------------------------------------------- |
| MCP handoff coordination            | Yes                                           | --                                                            |
| Lane manifests + merge ordering     | Yes                                           | --                                                            |
| Worktree isolation (git worktree)   | Yes -- subagents don't provide file isolation | --                                                            |
| Prompt rendering (`lane_prompt.py`) | Yes                                           | --                                                            |
| Schema contracts (`lane_result.py`) | Yes                                           | --                                                            |
| Execution transport                 | --                                            | New backend behind `run_lane_exec()` and `run_review()`       |
| Binary discovery (`find_codex()`)   | --                                            | Conditional on backend; skip for subagent backend             |
| Heartbeat/progress reporting        | --                                            | Adapted per backend (subprocess timeout vs subagent callback) |
| Result file lifecycle               | --                                            | Subagent may return JSON directly instead of writing to disk  |

#### Design constraints

- **Do not over-abstract.** The subagent API is not stable. A `backend` parameter on `run_lane_exec()` with two code paths (`codex-cli` vs `codex-subagent`) is sufficient. Do not build a plugin registry or ABC hierarchy.
- **Do not give subagents direct MCP write access.** The current design where `lane_exec` is "non-reporting" and the _caller_ (worker daemon) decides what to record in MCP is correct. Subagents should return structured JSON; the caller handles handoff recording.
- **Worktree lanes remain essential.** Subagents do not eliminate the need for `git worktree` isolation. Two agents editing the same codebase concurrently still need separate working directories. The lane manifest, merge ordering, downstream refresh, and intake pipeline are orthogonal to execution transport.
- **Bounded, stateless invocations only.** The current architecture treats each codex invocation as stateless (prompt in, JSON out, no conversation memory). Subagents should follow the same contract. Good candidates: implementation cycles, self-review, guidance classification. Bad candidate: anything requiring multi-turn state within a single invocation.
- **Keep backend naming at the seam, not in the orchestration model.** Manifest schema, MCP records, lane lifecycle, and task-plan routing should not learn the term "subagent." Only execution entrypoints and their CLI flags should know which backend implementation ran.

#### Implementation approach

1. Add a `backend` parameter to `run_lane_exec()` defaulting to `"codex-cli"`. Use explicit implementation names such as `"codex-cli"` and `"codex-subagent"` rather than generic transport labels. When `"codex-subagent"`, invoke the Codex subagent API with the same prompt text and output schema, receive JSON directly, write it to the result file path.
2. Add a parallel `backend` parameter to `run_review()` in `review_runner.py` with the same contract.
3. `_run_codex_process()` stays as-is for the `codex-cli` backend. A new `_run_subagent()` function handles the subagent path with equivalent progress callbacks.
4. `find_codex()` is called only for the `codex-cli` backend. The `codex-subagent` backend uses the host app's API directly.
5. Worker daemon and orchestrator daemon gain a `--backend` CLI flag that threads through to `run_lane_exec()` and `run_review()`. Default: `codex-cli` for backward compatibility.
6. Manifest or environment-level backend selection (e.g., per-lane backend override in `config/lane-orchestration/*.json`) is deferred until the subagent API stabilizes.

#### Bridge contract

The current `codex-subagent` backend is intentionally bridge-based rather than desktop-app-specific. The execution layer expects a host-provided Python module named `codex_subagent_bridge` with a callable:

```python
run_subagent(prompt: str, schema: dict, cwd: str, env: dict | None = None) -> dict | str
```

Contract details:

- `prompt` is the fully rendered worker or review prompt text.
- `schema` is the parsed JSON schema object that the backend must satisfy.
- `cwd` is the target worktree path where the backend should execute.
- `env` is an optional runtime hint map carrying the same lane-scoped temp-dir and interpreter context that `codex exec` receives today. Bridges may ignore it, but new bridge implementations should accept it.
- Return value must be either:
  - a Python `dict` matching the relevant structured-output contract, or
  - a JSON string that parses into that dict.
- For lane execution, the returned object must match the `lane_result.py` schema.
- For review execution, the returned object must match `REVIEW_OUTPUT_SCHEMA` in `review_runner.py`.
- The daemon will attempt `env=...` first and falls back to the legacy three-argument call shape for backward compatibility with older bridges.
- If the bridge module is missing or does not expose `run_subagent`, the daemon raises `RuntimeError`. Automatic fallback to `codex-cli` is intentionally out of scope for this task because silent fallback would obscure which execution backend actually ran.

Provisioning of the bridge is host-owned. Acceptable mechanisms include `PYTHONPATH` injection, pre-populating `sys.modules`, or packaging the bridge as an installable module. This task does not standardize the delivery mechanism beyond the import contract above.

#### Runtime topology

`codex-subagent` is only usable when the Python daemon process can reach a host that knows how to satisfy the `codex_subagent_bridge` contract.

Two topologies are supported conceptually:

- **Embedded-host topology.** The daemon is launched from within an environment that already injects the bridge module and can talk to the live Codex runtime in-process or through host-owned hooks.
- **External-bridge topology.** The daemon is still a standalone Python process, but the imported bridge module forwards calls over some separate IPC transport such as a socket, pipe, or HTTP shim to a long-lived Codex desktop session.

This task targets the seam, not a specific transport implementation. In other words: the daemon side is complete once it can call the bridge contract; the concrete desktop-app bridge implementation is deferred to the host/runtime layer. Operators should treat `BACKEND=codex-subagent` as available only in environments where that bridge has been provisioned.

#### Future: semantic guidance classification

`_classify_guidance()` in `orchestrator_guidance.py` currently uses string matching against marker lists (`_RESOLVED_MARKERS`, `_ENV_BLOCKER_MARKERS`, `_REMAINING_WORK_MARKERS`). A subagent could do semantic classification here as a bounded, stateless call. This is not in scope for this task but is a natural follow-on once the execution backend abstraction exists.

## Functions to Change

| File                                 | Target                                         | Change                                                                                       | Phase |
| ------------------------------------ | ---------------------------------------------- | -------------------------------------------------------------------------------------------- | ----- |
| `mk/lane-guards.mk`                  | `task-guard`                                   | New guard: validates TASK + TASK_LANES only                                                  | 1     |
| `mk/lane-guards.mk`                  | `lane-orchestrator-guard`                      | Depend on `task-guard` instead of `lane-guard`                                               | 1     |
| `mk/handoff.mk`                      | `orchestrator-daemon`                          | Omit `--task-ref` when `TASK` is empty so CLI inference can run; no `LANE` requirement       | 2     |
| `mk/handoff.mk`                      | `daemon-pause`                                 | Use `ORCHESTRATOR_ROOT` consistently under global singleton semantics                        | 3     |
| `mk/handoff.mk`                      | `daemon-resume`                                | Use `ORCHESTRATOR_ROOT` consistently under global singleton semantics                        | 3     |
| `mk/handoff.mk`                      | `daemon-status`                                | Use `ORCHESTRATOR_ROOT` consistently under global singleton semantics                        | 3     |
| `mk/handoff.mk`                      | `list-tasks`                                   | New target: prints `SUPPORTED_TASKS`                                                         | 2     |
| `Makefile`                           | TASK inference                                 | Add sole-manifest fallback (`SOLE_TASK`) after `ACTIVE_TASK`                                 | 2     |
| `scripts/mcp/orchestrator_daemon.py` | `_parse_args`                                  | Make `--task-ref` optional; add fallback chain                                               | 2     |
| `scripts/mcp/orchestrator_daemon.py` | `_resolve_task_ref`                            | New function: CLI arg, then MCP active task, then sole manifest, then fail with listing      | 2     |
| `scripts/mcp/orchestrator_daemon.py` | `orchestrator_loop`                            | Log discovered lanes at startup                                                              | 4     |
| `scripts/mcp/orchestrator_daemon.py` | `_dispatch_plan_item`                          | Include `lane` field in dispatch result dict                                                 | 4     |
| `scripts/mcp/orchestrator_lanes.py`  | `_intake_lane`                                 | After successful intake, close open `orchestrator_to_worker` dispatch messages for that lane | 4     |
| `scripts/mcp/worker_daemon.py`       | `_cleanup_result_file`                         | New function: delete consumed result JSON after successful handoff                           | 4     |
| `scripts/mcp/worker_daemon.py`       | `worker_loop`                                  | Call `_cleanup_result_file` after `_run_final_handoff()` returns 0                           | 4     |
| `mk/lane-lifecycle.mk`               | `lane-dispatch`                                | Add `lane-guard` prerequisite alongside `lane-orchestrator-guard`                            | 1     |
| `mk/lane-maintenance.mk`             | `lane-commits`, `lane-intake`                  | Add `lane-guard` prerequisite alongside `lane-orchestrator-guard`                            | 1     |
| `scripts/mcp/lane_exec.py`           | `run_lane_exec`                                | Add `backend` parameter (`codex-cli` / `codex-subagent`); new `_run_subagent()` code path    | 5     |
| `scripts/mcp/review_runner.py`       | `run_review`                                   | Add `backend` parameter mirroring `lane_exec.py` contract                                    | 5     |
| `scripts/mcp/worker_daemon.py`       | `_parse_args`, `worker_loop`                   | Thread `--backend` flag through to `run_lane_exec` and `run_review`                          | 5     |
| `scripts/mcp/orchestrator_daemon.py` | `_parse_args`, `main`                          | Thread `--backend` flag for orchestrator-invoked review/execution                            | 5     |

## Related Files (reference, no changes expected)

| File                                   | Role                                                                                                 |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `scripts/mcp/orchestrator_guidance.py` | Worker guidance classification and resolution; future subagent candidate for semantic classification |
| `scripts/mcp/lane_manifest.py`         | Manifest loading, `task_plan_path`, `merge_order`                                                    |
| `scripts/mcp/lane_config.py`           | `infer-task`, `infer-lane`, `list-tasks` CLI                                                         |
| `config/lane-orchestration/*.json`     | Lane manifests (source of truth for lane topology)                                                   |
| `scripts/mcp/lane_prompt.py`           | Worker prompt generation (downstream of dispatch)                                                    |
| `scripts/mcp/task_plan_parser.py`      | Task plan parsing, normalization, lane mapping                                                       |
| `scripts/mcp/lane_result.py`           | Result schema definition and handoff command; shared contract for both backends                      |

## Consolidated Checklist

### Phase 1: Guard fix

- [x] Add `task-guard` to `mk/lane-guards.mk` that validates TASK and TASK_LANES without requiring LANE
- [x] Change `lane-orchestrator-guard` to depend on `task-guard` instead of `lane-guard`
- [x] Verify `make orchestrator-daemon TASK=phase-5-retention-export-and-audit-controls SINGLE_PASS=1 DRY_RUN=1` works without LANE
- [x] Verify `make lane-intake`, `make lane-commits`, and other `lane-orchestrator-guard` consumers still work with LANE (they inherit it from their own prerequisites or callers)

### Phase 2: Task inference

- [x] Add sole-manifest fallback to Makefile TASK resolution: when `ACTIVE_TASK` is empty and exactly one manifest exists, use its `task_ref` -- implemented as `SOLE_TASK` variable in Makefile
- [x] Make `--task-ref` optional in `orchestrator_daemon.py _parse_args`; add inference chain: CLI arg, then MCP active task, then sole manifest, then fail with listing -- implemented as `_resolve_task_ref()` function
- [x] Update `mk/handoff.mk` so `make orchestrator-daemon` only passes `--task-ref` when `TASK` is non-empty
- [x] Add `make list-tasks` target that prints the already-computed `SUPPORTED_TASKS`
- [x] Verify `make orchestrator-daemon SINGLE_PASS=1 DRY_RUN=1` works with no explicit TASK when the active MCP task is set
- [x] Verify the daemon errors clearly when no task can be inferred and multiple manifests exist

### Phase 3: Lifecycle commands

- [x] Update `daemon-pause`, `daemon-resume`, and `daemon-status` to use `ORCHESTRATOR_ROOT` consistently and work from any worktree under global singleton semantics
- [x] Verify lifecycle documentation, Make targets, and daemon status output all describe singleton orchestrator behavior consistently

### Phase 4: Operational polish

- [x] Add `lanes_discovered` log line at daemon startup listing all manifest lanes
- [x] Verify `task_plan_dispatch` log line includes the target `lane` field
- [x] Verify a single pass dispatches the next eligible plan item cleanly
- [x] Keep `orchestrator_to_worker` dispatch-message ownership on the orchestrator side only
- [x] Delete result JSON artifacts after successful handoff from `worker_daemon.py` -- implemented as `_cleanup_result_file()`
- [x] Close stale dispatch messages during the intake path (`_intake_lane` or its caller), not only during guidance resolution
- [x] Add JSONL log rotation policy for `logs/worker-daemon/worker-{lane_id}.jsonl` -- rotate current file to `.jsonl.1` when it exceeds 1 MB
- [x] Verify stale `codex exec` child processes cannot accumulate under a long-lived worker daemon -- confirmed safe: `proc.communicate()` blocks until child exits
- [x] Keep single-dispatch-per-cycle semantics explicit for this task; batched multi-lane dispatch remains out of scope and is covered by regression tests

### Phase 5: Subagent execution backend

- [x] Add `backend` parameter to `run_lane_exec()` in `lane_exec.py` (`codex-cli` default, `codex-subagent` alternative)
- [x] Implement `_run_subagent()` function in `lane_exec.py` that invokes the Codex subagent API with prompt + schema, returns JSON result
- [x] Add `backend` parameter to `run_review()` in `review_runner.py` with equivalent contract
- [x] Add `--backend` CLI flag to `worker_daemon.py` and thread through to `run_lane_exec` and `run_review`
- [x] Add `--backend` CLI flag to `orchestrator_daemon.py` for orchestrator-invoked operations
- [x] Test `codex-cli` backend still works identically (regression guard)
- [x] Test `codex-subagent` backend produces valid structured JSON matching `lane_result.py` schema
- [x] Test `codex-subagent` backend produces valid structured JSON matching `review_runner.py` schema
- [x] Verify `find_codex()` is only called for `codex-cli` backend
- [x] Verify subagent backend progress callbacks work (equivalent to heartbeat reporting)
