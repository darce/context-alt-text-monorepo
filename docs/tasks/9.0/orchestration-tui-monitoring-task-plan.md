# Orchestration TUI Monitoring

## Problem Statement

Operators currently monitor lane execution through ad hoc CLI polling, JSONL tailing, and explicit Codex check-ins. That makes it too easy for a lane to look "alive" while its worker has already stalled, exhausted review cycles, or handed off a blocker. We need a real-time terminal UI for the orchestration pipeline so lane state is streamed to operators continuously and interventions can happen from a single surface.

## Workflow Principles

- **MCP and worker logs remain the source of truth.** The TUI must reflect orchestration state, not invent a parallel state machine.
- **Event-driven over manual polling.** Operators should see updates as lanes change state, not only when a harness explicitly asks.
- **Read-mostly, action-safe control plane.** Monitoring should be continuous, but actions must still route through existing MCP commands and validations.
- **Stale detection must be explicit.** A lane card should distinguish `executing`, `waiting_for_orchestrator`, `blocked`, and "record exists but no live worker" states.
- **Token and model telemetry are first-class.** Operators need to see model, reasoning effort, token burn, and recent cycle history without opening raw logs.

## Terminology

- **Lane**: A scoped worktree execution unit with owned paths, worker lifecycle state, and handoff records.
- **Worker event**: A structured JSONL record emitted by the worker daemon or orchestrator daemon describing lifecycle transitions such as `exec_spawned` or `review_exhausted`.
- **Derived lane state**: A UI-facing status computed from lock state, PID presence, last event, MCP worker state, and handoff metadata.
- **Action rail**: The TUI control surface for safe operator commands such as redispatch, stop, resume, close, or intake.
- **Event aggregator**: A small local service or module that tails daemon logs, normalizes events, and maintains an in-memory snapshot for the TUI.

## Current State Analysis

- `agent-handoff-mcp` exposes worker status, lane messages, findings, tests, and decisions, but operators must invoke it manually.
- Worker and orchestrator daemons already emit structured JSONL under [logs/worker-daemon](/Users/daniel/Development/context-alt-text-monorepo/logs/worker-daemon) and [logs/daemon/orchestrator.jsonl](/Users/daniel/Development/context-alt-text-monorepo/logs/daemon/orchestrator.jsonl).
- Lane records can become misleading if an operator reads only the lane status without also checking lock state, PID liveness, and the latest worker event.
- Token/model telemetry already exists in worker observability output, but it is buried in `worker-status` JSON and daemon logs.
- The current workflow encourages "tell me if it's still running" questions because there is no durable push-style operator view.
- The orchestration pipeline already has enough structured state to drive a TUI; the missing piece is an event aggregation and presentation layer.

## Proposed Solution

Build a local terminal UI for orchestration around an event aggregator that tails worker and orchestrator logs, enriches them with MCP state, and renders a live lane dashboard. The TUI should provide continuously updated lane cards, event feeds, findings/blockers, and token/model telemetry, while routing all operator actions through existing `agent-handoff-mcp` commands. The first implementation should be local-only, file-backed, and resilient to daemon restarts, with optional websocket streaming or remote views deferred until the core lane-state model is stable.

## Patterns to Follow

### Event Aggregation

```python
@dataclass
class LaneRuntimeSnapshot:
    lane_id: str
    task_ref: str
    lane_status: str
    worker_state: str
    lock_held: bool
    pid: int | None
    run_id: str | None
    cycle: int | None
    last_event: str | None
    last_event_ts: datetime | None
    model: str | None
    reasoning_effort: str | None
    findings_open: int
    blockers_open: int
    token_usage_last: TokenUsage | None


class EventAggregator:
    def on_worker_event(self, event: WorkerEvent) -> None:
        snapshot = self._lane_snapshots[event.lane]
        snapshot.last_event = event.event
        snapshot.last_event_ts = event.ts
        snapshot.run_id = event.run_id
        snapshot.cycle = event.cycle

    def reconcile_with_mcp(self, state: MpcStateSnapshot) -> None:
        # MCP remains the source of truth for findings, lane messages,
        # actions, blockers, and current worker lifecycle state.
        ...
```

### TUI Action Routing

```python
class LaneDetails(Screen):
    def action_redispatch_lane(self) -> None:
        self.run_command(
            [
                "agent-handoff-mcp",
                "--workspace-root",
                self.workspace_root,
                "worker-start",
                "--task-ref",
                self.task_ref,
                "--lane-id",
                self.lane_id,
                "--backend",
                self.snapshot.backend or "codex-subagent",
            ]
        )

    def action_refresh(self) -> None:
        self.app.refresh_snapshot()
```

### Stale Worker Detection

```python
def derive_live_state(snapshot: LaneRuntimeSnapshot) -> str:
    if snapshot.lock_held and snapshot.pid and snapshot.last_event in {"exec_spawned", "cycle_start"}:
        return "executing"
    if not snapshot.lock_held and snapshot.last_event == "review_exhausted":
        return "waiting_for_orchestrator"
    if not snapshot.lock_held and snapshot.worker_state in {"blocked", "review"}:
        return snapshot.worker_state
    return "stale"
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `scripts/mcp/orchestration_tui.py` | new | Add the Textual entrypoint, app shell, lane list, event feed, and action bindings. |
| `scripts/mcp/orchestration_tui/state.py` | new | Define lane runtime snapshot types, derived-state rules, and MCP projection helpers. |
| `scripts/mcp/orchestration_tui/events.py` | new | Tail worker/orchestrator JSONL logs and normalize them into typed events. |
| `scripts/mcp/orchestration_tui/actions.py` | new | Wrap safe operator actions that call `agent-handoff-mcp` subcommands. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` | TBD | Optionally expose a convenience `tui` command or structured state endpoint if direct import is too awkward. |
| `scripts/mcp/_env.py` | TBD | Share workspace-root, log-path, and state-dir discovery with the TUI launcher. |
| `mk/lane-worker.mk` | TBD | Add a `make orchestration-tui` target for consistent startup. |
| `docs/agentic/playbooks/worktree-codex-playbook.md` | TBD | Document how operators use the TUI alongside lane workflows. |

## Related Files

| File | Note |
| --- | --- |
| [logs/worker-daemon](/Users/daniel/Development/context-alt-text-monorepo/logs/worker-daemon) | Existing worker event stream that the aggregator should tail. |
| [logs/daemon/orchestrator.jsonl](/Users/daniel/Development/context-alt-text-monorepo/logs/daemon/orchestrator.jsonl) | Existing orchestrator event stream. |
| [lane_exec.py](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_exec.py) | Existing worker lifecycle semantics the TUI must represent faithfully. |
| [docs/agentic/playbooks/worktree-codex-playbook.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/playbooks/worktree-codex-playbook.md) | Operator workflow that should eventually reference the TUI. |
| [docs/agentic/contracts/agent-handoff-mcp.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/contracts/agent-handoff-mcp.md) | Source of truth for MCP orchestration behaviors and handoff expectations. |

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `mcp-runtime` | `packages/agent-handoff-mcp/**`, `scripts/mcp/_env.py` | None | `PYENV_VERSION=description-service pytest packages/agent-handoff-mcp/tests/` |
| `tui-core` | `scripts/mcp/orchestration_tui/**` | `mcp-runtime` | `PYENV_VERSION=description-service pytest scripts/mcp/orchestration_tui/tests/` |
| `operator-docs` | `docs/agentic/**`, `docs/tasks/8.0/**` | `tui-core` (behavior only) | docs review |

### Merge Order

`mcp-runtime` -> `tui-core` -> `operator-docs`

### Manifest

Initialize the lane manifest for this task:

```bash
make lane-manifest-init TASK=orchestration-tui-monitoring LANE_IDS='mcp-runtime tui-core operator-docs' TASK_PLAN=docs/tasks/8.0/orchestration-tui-monitoring-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with `backend="codex-subagent"` so the same telemetry the TUI will consume is exercised during implementation.
- **Shell fallback**: Use `make lane-open`, `make lane-run`, `make lane-handoff`, and `make lane-intake` from the orchestrator root if MCP worker lifecycle tools are unavailable.

---

# Consolidated Checklist

## Completed

- [ ] Existing worker/orchestrator JSONL streams and MCP worker status already expose the raw telemetry needed for a TUI.

## Phase 0: Scaffolding

- [ ] Add a new `scripts/mcp/orchestration_tui/` package with typed event and snapshot models.
- [ ] Add a launcher entrypoint (`scripts/mcp/orchestration_tui.py` or equivalent).
- [ ] Add initial tests for event parsing, stale-state derivation, and snapshot reconciliation.
- [ ] Document the TUI task contract in this plan and update operator docs if command names are introduced.
- [ ] Verify scaffolds compile and import cleanly.

## Phase 1: Event Aggregation

- [ ] Tail worker JSONL logs and normalize lifecycle events (`daemon_start`, `cycle_start`, `exec_spawned`, `subagent_turn_observed`, `review_complete`, `review_exhausted`).
- [ ] Tail orchestrator JSONL and merge orchestration-level events into the lane snapshot.
- [ ] Reconcile aggregated event state with `agent-handoff-mcp state` / `worker-status` so findings, blockers, and lane metadata stay current.
- [ ] Derive explicit UI states for `executing`, `waiting_for_orchestrator`, `blocked`, `review`, and `stale`.

## Phase 2: TUI Surface

- [ ] Implement a lane dashboard with columns for lane id, live state, last event, cycle, model, reasoning effort, findings, blockers, and token burn.
- [ ] Add a details pane showing the latest worker message, recent events, latest tests, and latest findings for the selected lane.
- [ ] Add an event feed pane so operators can watch transitions without tailing raw JSONL.
- [ ] Add clear stale-worker indicators when lane record, lock, PID, and worker state disagree.

## Phase 3: Operator Actions

- [ ] Add safe actions for refresh, redispatch, stop, resume, and open latest handoff using existing `agent-handoff-mcp` subcommands.
- [ ] Add confirmation guards for destructive or high-impact actions.
- [ ] Surface command results and failures in the TUI without hiding raw stderr/stdout context.
- [ ] Ensure actions cannot mutate orchestration state without going through MCP validation.

## Phase 4: Observability and Ergonomics

- [ ] Show latest token usage, cumulative token totals, model, and effective reasoning effort per active lane.
- [ ] Add filter/sort controls for active lanes, blocked lanes, stale lanes, and findings severity.
- [ ] Add operator-friendly timing metadata such as last event age, total run duration, and cycle count.
- [ ] Add a compact summary row for active task, pending actions, open blockers, and open findings by severity.

## Phase 5: Documentation and Rollout

- [ ] Document local startup, expected panes, and recommended operator workflow.
- [ ] Document how the TUI relates to `CURRENT_TASK.md`, MCP state, and worker logs.
- [ ] Add rollout notes describing the first local-only version and any deferred websocket/remote-view work.

## Phase 6: Tests

- [ ] Unit test event normalization from real daemon log fixtures.
- [ ] Unit test derived stale/executing/waiting state logic from lock/PID/event combinations.
- [ ] Integration test TUI action wrappers against a temporary handoff state fixture.
- [ ] Smoke test the TUI against a live local task with at least one active and one stale lane.

## Stretch Goals

- [ ] Add a websocket or local pub-sub bridge so the TUI can subscribe to a consolidated live stream rather than tailing files directly.
- [ ] Add a read-only web dashboard backed by the same event aggregator.
- [ ] Add configurable alerting for `review_exhausted`, repeated blocker cycles, or abnormal token burn.

## Success Criteria

- [ ] An operator can open the TUI and distinguish a truly running lane from a stale lane without manually checking multiple commands.
- [ ] The TUI updates lane state automatically as worker/orchestrator events arrive.
- [ ] An operator can view findings, blockers, token/model telemetry, and the latest handoff from one screen.
- [ ] An operator can safely redispatch or stop a lane from the TUI using the existing MCP control plane.
- [ ] The TUI never becomes the source of truth; lane state shown in the TUI matches MCP state and daemon logs.
