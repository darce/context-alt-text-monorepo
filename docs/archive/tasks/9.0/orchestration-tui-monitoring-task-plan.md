# Orchestration TUI Monitoring

## Status Snapshot

This task is partially implemented. The current codebase already ships a usable monitoring surface under `packages/agent-orchestrator-mcp`, so this plan is no longer a greenfield proposal for a brand-new `scripts/mcp/orchestration_tui/` stack.

Shipped baseline:

- `dashboard_live.py` already provides a polling dashboard for lane health, stale-lock detection, token burn, pressure, model, reasoning effort, cycle count, artifact count, and optional ACE metrics.
- `dashboard_tui.py` already provides a local operator dashboard that uses Textual when available and falls back to rich/live or plain-text polling when it is not.
- `worker_daemon_ctl.py` already provides `daemon_status()` and `daemon_event_history()`, including PID liveness checks, stale-lock detection, and recent worker event history.
- `api.py` already provides `dispatch_lane_work()`, `worker_start()`, and `worker_resume()`, so the operator control plane does not need a new mutation path.

The remaining work is to align the operator workflow, enrich the current dashboard with more context and safe actions, and document a stable startup path.

## Problem Statement

Operators still need a single, documented surface for lane monitoring and intervention. The shipped dashboard solves the basic "is this lane still alive?" problem, but it does not yet provide the richer context and safe control affordances needed to replace ad hoc status checks, JSONL tailing, and manual command lookup.

## Workflow Principles

- **Daemon and MCP helpers remain the source of truth.** The dashboard must reuse existing status, event-history, and dispatch helpers rather than inventing a shadow state machine.
- **Runtime model is explicit.** The dashboard runs as a separate, on-demand local process in its own terminal or tmux pane. It does not replace, wrap, or embed the orchestrator or worker daemons.
- **Polling first, push later.** The shipped dashboard already proves a polling model; keep extending that model until a concrete UX gap justifies a push or streaming layer.
- **Read-mostly, action-safe control plane.** Monitoring should be continuous, but actions must still route through existing MCP and orchestrator validation surfaces.
- **Model and token telemetry are first-class.** Operators need model, reasoning effort, token burn, cycle count, and stale-worker context without opening raw logs.

## Terminology

- **Lane**: A scoped worktree execution unit with owned paths, worker lifecycle state, and handoff records.
- **Worker event**: A structured JSONL record emitted by the worker daemon or orchestrator daemon describing lifecycle transitions such as `exec_spawned` or `review_exhausted`.
- **Derived lane state**: A UI-facing status computed from lock state, PID liveness, last event, MCP worker state, and handoff metadata.
- **Action rail**: The dashboard control surface for safe operator commands such as refresh, dispatch update, start, resume, stop, or open handoff.

## Current State Analysis

- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_live.py` already implements the simpler polling dashboard that earlier planning feedback recommended as the first milestone.
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_tui.py` already implements the operator-facing runtime model: a separate local process that renders once or continuously, with Textual, rich/live, and plain-text modes.
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon_ctl.py` already centralizes stale-worker detection, lock and PID liveness, status summaries, and recent event history. The dashboard should keep consuming those helpers instead of re-parsing logs independently.
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` already exposes dispatch, worker start, and worker resume surfaces that can power a future action rail, including per-lane model and reasoning-effort overrides.
- Existing tests cover the dashboard import surface and metrics summary helpers, but the operator-facing behavior is still under-tested.
- Remaining gaps are mostly additive: richer event/details panes, explicit action affordances, startup and playbook documentation, and a stable command target.

## Proposed Solution

Extend the shipped dashboard in place under `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/`. Treat `dashboard_live.py` as the shipped Phase 0 baseline and `dashboard_tui.py` as the current UI shell. New work should reuse `daemon_status()`, `daemon_event_history()`, and MCP query surfaces on each refresh cycle, only adding new helper functions when a concrete field is missing from the source-of-truth modules.

Do not create a second event-aggregation stack unless polling against the existing status and history helpers proves insufficient. The next milestone is a richer local operator dashboard, not a new orchestration subsystem.

## Patterns to Follow

### Runtime Model

```python
def launch_dashboard(orchestrator_root: Path, task_ref: str) -> None:
    """Run as a separate local operator process."""
    lane_ids = _resolve_lane_ids(orchestrator_root, task_ref, requested=None)
    dashboard = _build_textual_app(orchestrator_root, task_ref, lane_ids, interval=10)
    dashboard.run()
```

### Monitoring Data Flow

```python
def load_lane_snapshot(orchestrator_root: Path, task_ref: str, lane_id: str) -> dict[str, Any]:
    status = daemon_status(
        state_dir=orchestrator_root / ".task-state",
        log_dir=orchestrator_root / "logs/worker-daemon",
        lane_id=lane_id,
        task_ref=task_ref,
    )
    events = daemon_event_history(
        state_dir=orchestrator_root / ".task-state",
        log_dir=orchestrator_root / "logs/worker-daemon",
        lane_id=lane_id,
        task_ref=task_ref,
        limit=10,
    )
    return {"status": status, "events": events["events"]}
```

### Action Routing

```python
def update_lane_settings(task_ref: str, lane_id: str, model: str | None, effort: str | None) -> None:
    dispatch_lane_work(
        task_ref=task_ref,
        lane_id=lane_id,
        model=model,
        reasoning_effort=effort,
        start_worker=False,
    )


def restart_stopped_lane(task_ref: str, lane_id: str) -> None:
    worker_start(task_ref=task_ref, lane_id=lane_id)


def resume_paused_lane(task_ref: str, lane_id: str) -> None:
    worker_resume(task_ref=task_ref, lane_id=lane_id)
```

The dashboard must keep these actions distinct. Updating the next-turn model, starting a stopped worker, and resuming a paused worker are different operations with different preconditions.

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_live.py` | existing | Keep as the shared polling baseline; extend reusable snapshot, formatting, and summary helpers only where the dashboard needs more context. |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_tui.py` | existing | Add richer panes, selection state, safe action bindings, and model or effort controls on top of the shipped shell. |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon_ctl.py` | existing | Reuse `daemon_status()` and `daemon_event_history()` as the primary monitoring inputs; only extend them if the dashboard needs a missing source-of-truth field. |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` | existing | Use existing dispatch and worker lifecycle APIs for action routing; extend response payloads only if the dashboard cannot otherwise render needed state. |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/cli.py` | existing | Optionally add a stable dashboard launcher command if the package should own the operator entrypoint. |
| `Makefile` or `mk/*.mk` | TBD | Optionally add a `make dashboard-tui` or equivalent stable startup target once the command is settled. |
| `docs/agentic/playbooks/worktree-codex-playbook.md` | TBD | Document how operators run the dashboard alongside orchestrator and worker daemons. |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_live.py` | Current polling dashboard baseline. |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_tui.py` | Current Textual or rich operator dashboard shell. |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon_ctl.py` | Source-of-truth worker status and event-history helpers. |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` | Existing dispatch, start, and resume action surfaces. |
| `packages/agent-orchestrator-mcp/tests/test_hardening.py` | Current importability and one-shot rich rendering coverage for the dashboard shell. |
| `packages/agent-orchestrator-mcp/tests/test_ace_reflect.py` | Current metrics summary coverage used by `dashboard_live.py`. |
| `docs/agentic/playbooks/worktree-codex-playbook.md` | Operator workflow that should eventually reference the dashboard. |

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `runtime-status` | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon_ctl.py`, `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py`, `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/cli.py` | None | `PYENV_VERSION=description-service pytest packages/agent-orchestrator-mcp/tests/ -q` |
| `dashboard-surface` | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_live.py`, `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_tui.py`, `packages/agent-orchestrator-mcp/tests/**` | `runtime-status` | `PYENV_VERSION=description-service pytest packages/agent-orchestrator-mcp/tests/ -q` |
| `operator-docs` | `docs/agentic/**`, `docs/tasks/9.0/**`, `Makefile`, `mk/**` | `dashboard-surface` (behavior only) | docs review |

### Merge Order

`runtime-status` -> `dashboard-surface` -> `operator-docs`

### Manifest

Initialize the lane manifest for this task:

```bash
make lane-manifest-init TASK=orchestration-tui-monitoring LANE_IDS='runtime-status dashboard-surface operator-docs' TASK_PLAN=docs/tasks/9.0/orchestration-tui-monitoring-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with `backend="codex-subagent"` so the same telemetry the dashboard consumes is exercised during implementation.
- **Shell fallback**: Use `make lane-open`, `make lane-run`, `make lane-handoff`, and `make lane-intake` from the orchestrator root if MCP worker lifecycle tools are unavailable.

---

## Consolidated Checklist

## Completed

- [x] `dashboard_live.py` provides a polling lane-health dashboard with stale-lock, token, pressure, model, effort, cycle, and artifact visibility.
- [x] `dashboard_tui.py` provides a local Textual dashboard with rich/live and plain-text fallbacks.
- [x] `daemon_status()` and `daemon_event_history()` already expose the lock, PID, stale, summary, and recent event signals needed for operator monitoring.
- [x] Existing action surfaces already support dispatch updates, worker start, and worker resume.

## Phase 0: Plan Alignment and Shared Baseline

- [x] Track the existing packaged dashboard modules instead of a new `scripts/mcp/orchestration_tui/` stack.
- [x] Define the runtime model explicitly: separate local dashboard process, separate daemon processes.
- [ ] Decide whether the package should expose a stable CLI launcher or whether a `make` target is sufficient.

## Phase 1: Monitoring Enrichment

- [ ] Add a details pane showing recent worker events, latest test result, and current handoff or finding summary for the selected lane.
- [ ] Add an event feed that reuses `daemon_event_history()` rather than re-parsing JSONL logs independently.
- [ ] Surface blocker and finding counts from MCP alongside the existing worker status summary.
- [ ] Preserve clear stale, paused, waiting, blocked, and executing distinctions using the existing status helpers.

## Phase 2: Operator Actions

- [ ] Add explicit actions for refresh, update next-turn model or reasoning effort, start stopped worker, resume paused worker, and open latest handoff.
- [ ] Keep dispatch updates, worker start, and worker resume as separate guarded actions.
- [ ] Add confirmation guards for high-impact actions.
- [ ] Surface command results and failures in the dashboard without hiding stderr or stdout context.

## Phase 3: Observability and Ergonomics

- [ ] Add filter or sort controls for active, blocked, stale, and attention-required lanes.
- [ ] Add operator-friendly timing metadata such as last-event age and run duration.
- [ ] Add a compact task summary row for pending actions, blockers, and findings by severity.
- [ ] Keep the shared polling formatter usable in Textual, rich/live, and plain-text modes.

## Phase 4: Documentation and Rollout

- [ ] Document local startup, expected modes, and the recommended tmux or terminal-pane workflow.
- [ ] Document how the dashboard relates to `CURRENT_TASK.md`, MCP state, and worker logs.
- [ ] Add rollout notes describing the current local-only baseline and any deferred remote-view work.

## Phase 5: Tests

- [ ] Expand unit coverage for stale, paused, executing, and waiting state rendering paths.
- [ ] Add coverage for dashboard selection and event-pane behavior once richer panes exist.
- [ ] Add focused tests for action-wrapper preconditions and model or effort override flows.
- [ ] Add a smoke test for the dashboard against a local task with at least one active and one stale lane.

## Stretch Goals

- [ ] Add a push-based event stream only if polling against the existing status helpers proves insufficient.
- [ ] Add a read-only web view backed by the same shared dashboard data path.
- [ ] Add configurable alerting for `review_exhausted`, repeated blocker cycles, or abnormal token burn.

## Success Criteria

- [ ] An operator can open the dashboard and distinguish a truly running lane from a stale or paused lane without manually checking multiple commands.
- [ ] An operator can see model, reasoning effort, token context, recent events, and handoff or finding status from one surface.
- [ ] An operator can safely update next-turn settings or recover a lane using the existing MCP control plane.
- [ ] The dashboard continues to match daemon and MCP state without introducing a parallel orchestration state machine.
