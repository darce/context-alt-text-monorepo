# Daemon 3: Orchestrator Daemon

## Problem Statement

The orchestrator still advances work manually: inspect handoff state, dispatch open issues, intake merge-ready lanes, refresh dependents, and run cross-lane verification. The repo needs an unattended root-side loop that can keep those steps moving without inventing a second coordination system.

## Workflow Principles

- **Root owns routing and intake.** Only the orchestrator daemon dispatches work and merges lane output.
- **One routing source of truth.** Lane routing and merge order should come from a checked-in task manifest shared by `review_dispatch.py` and the orchestrator daemon. The daemon should not scrape `make -p`.
- **Dispatch stays idempotent.** Running dispatch every cycle must remain safe.
- **Verify before advance.** Intake continues to rely on the existing scratch-worktree verification path.
- **One orchestrator at a time.** A lock file prevents duplicate intake/dispatch loops.

## Terminology

- **Orchestrator daemon**: `scripts/mcp/orchestrator_daemon.py`
- **Routing manifest**: A checked-in task config defining lane routes and merge order
- **Merge order**: The ordered list of lanes eligible for intake sequencing
- **Downstream refresh**: Updating lanes that depend on newly intaken work
- **Single-pass mode**: Run exactly one orchestration cycle and exit

## Current State Analysis

- `make handoff-inbox` already exposes worker reports and open guidance requests from MCP.
- `make handoff-dispatch` already routes findings, blockers, and next actions via `scripts/mcp/lane_manifest.py`, which loads a checked-in manifest from `config/lane-orchestration/<task-ref>.json`.
- `make lane-intake` already performs scratch-worktree verification before merge.
- `make lane-refresh` already synchronizes worker worktrees against the orchestrator branch.
- `config/lane-orchestration/phase-5-retention-export-and-audit-controls.json` already defines routing prefixes, merge order, lane ownership (owned paths, test commands, commit paths), and route hints. The manifest is the routing source of truth; Makefile lane variables now duplicate it for backward compat.
- Existing MCP scripts such as `review_dispatch.py` already configure runtime explicitly from the orchestrator root; the daemon can reuse that pattern.
- No orchestrator daemon or lock exists today.

## Proposed Solution

Introduce two pieces:

1. **Reuse existing routing manifest** (`config/lane-orchestration/<task-ref>.json`)
   - Already stores lane route prefixes (`routing`), merge order (`merge_order`), lane ownership (`lanes`), and route hints
   - Already consumed by `review_dispatch.py` via `lane_manifest.route_patterns()`
   - Add `downstream` dependency declarations if not already present in the manifest

2. **Orchestrator daemon**
   - Acquire `.task-state/orchestrator.lock`
   - Configure MCP runtime from the orchestrator root
   - Run `make handoff-dispatch`
   - Query merge-ready worker reports
   - Intake lanes in manifest order
   - Resolve worker guidance messages
   - Derive the next dispatchable slice from the task plan when backlog routing is otherwise empty
   - Refresh downstream lanes declared by the same manifest
   - Run cross-lane verification after each successful intake
   - Record decisions/tests for each cycle and persist daemon status

Because workers are already polling, the orchestrator daemon does not need a special wake-up message system in the first version.

## Patterns to Follow

### Routing Manifest

```json
{
  "merge_order": ["backend-domain", "backend-http", "wp-proxy", "frontend"],
  "routing": [
    {
      "prefix": "apps/prototype-description-service/recognition/domain/",
      "lane": "backend-domain"
    },
    {
      "prefix": "apps/prototype-description-service/recognition/interface_adapters/http/",
      "lane": "backend-http"
    },
    { "prefix": "apps/prototype-wp-alt-context/src/", "lane": "wp-proxy" },
    { "prefix": "apps/prototype-wp-alt-context/js/", "lane": "frontend" }
  ],
  "downstream": {
    "backend-domain": ["backend-http", "wp-proxy", "frontend"],
    "backend-http": ["wp-proxy", "frontend"],
    "wp-proxy": ["frontend"],
    "frontend": []
  }
}
```

### Orchestrator Loop

```python
def orchestrator_loop(...) -> None:
    while True:
        if _is_paused(...):
            _sleep(...)
            continue

        _dispatch_open_items(...)
        ready_lanes = _poll_merge_ready_lanes(...)
        for lane_id in _sort_by_manifest_merge_order(ready_lanes, manifest):
            if _intake_lane(..., lane_id):
                _refresh_downstream(..., lane_id, manifest)
                _run_cross_lane_verify(...)
        _resolve_guidance_cycle(...)
        _dispatch_from_task_plan(...)
        _log_cycle_status(...)
        if single_pass:
            return
        _sleep(...)
```

### Locking

```python
class OrchestratorLock:
    def __init__(self, state_dir: Path) -> None:
        self._lock_path = state_dir / "orchestrator.lock"
```

## Functions to Change

| File                                        | Change                                                                                  |
| ------------------------------------------- | --------------------------------------------------------------------------------------- |
| `config/lane-orchestration/<task-ref>.json` | Existing routing and merge-order manifest; add `downstream` declarations if needed      |
| `scripts/mcp/orchestrator_daemon.py`        | New root-side poll/dispatch/intake loop                                                 |
| `scripts/mcp/orchestrator_lanes.py`         | Shared intake, refresh, and lane-capacity helpers used by the daemon                    |
| `mk/handoff.mk`                             | Add `orchestrator-daemon`, `daemon-pause`, `daemon-resume`, and `daemon-status` targets |

## Related Files

| File                             | Note                                                                                                |
| -------------------------------- | --------------------------------------------------------------------------------------------------- |
| `Makefile`                       | Existing `handoff-dispatch`, `lane-intake`, and `lane-refresh` targets remain the execution surface |
| `scripts/mcp/review_dispatch.py` | First consumer of the new routing manifest                                                          |
| `scripts/mcp/worker_daemon.py`   | Worker-side counterpart from daemon-2                                                               |
| `packages/agent-handoff-mcp/`    | MCP APIs for worker reports, findings, blockers, actions, and decisions                             |

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [x] Create `scripts/mcp/orchestrator_daemon.py` with CLI args for task, root path, poll interval, single-pass, and dry-run
- [x] Implement `.task-state/orchestrator.lock`
- [x] Configure MCP runtime from the orchestrator root before any MCP API call
- [x] Add `orchestrator-daemon`, `daemon-pause`, `daemon-resume`, and `daemon-status` targets
- [x] Verify: `python3 scripts/mcp/orchestrator_daemon.py --help` exits cleanly

## Phase 1: Routing Manifest

- [x] `config/lane-orchestration/<task-ref>.json` exists with routing, merge order, and lane config
- [x] `review_dispatch.py` loads the manifest via `lane_manifest.route_patterns()`
- [x] Add `downstream` dependency declarations to the manifest if not already present
- [x] Add a `lane_manifest.downstream_lanes(task_ref, lane_id)` accessor for the daemon
- [x] Test: `make handoff-dispatch` still routes the current Phase 5 findings correctly

## Phase 2: Polling and Intake

- [x] Implement `make handoff-dispatch` invocation from the daemon
- [x] Poll merge-ready reports from MCP
- [x] Intake in manifest merge order
- [x] Record an MCP decision for each successful or failed intake
- [x] Test: single-pass mode intakes only eligible ready lanes

## Phase 3: Downstream Refresh and Verification

- [x] Refresh downstream lanes from the manifest after successful intake
- [x] Run cross-lane verification after each intake
- [x] Record verification commands/results in MCP
- [x] Test: downstream refresh only touches declared dependents

## Phase 4: Operator Surface

- [x] Wire pause/resume via `.task-state/daemon-paused`
- [x] Make `daemon-status` show lock ownership, latest cycle, and last verification result
- [x] Add JSONL logging under `logs/daemon/orchestrator.jsonl`
- [x] Document single-pass and long-running usage in operator docs

## Success Criteria

- [x] `make orchestrator-daemon TASK=<task> SINGLE_PASS=1` dispatches open work and intakes merge-ready lanes in the declared order
- [x] Routing for tasks beyond Phase 5 is driven by checked-in manifest data rather than Makefile scraping
- [x] Orchestrator restarts safely because MCP remains the source of truth
- [x] No duplicate orchestrator loop can run while the lock is held
