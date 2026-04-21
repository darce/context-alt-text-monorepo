# Event-Driven Daemon Design Note (E17-10 rework candidate)

> **Status**: Design note only. This document enumerates alternatives. It does
> not pick a solution. A follow-on epic owns selection and implementation.

## Problem

The orchestrator and worker daemons are pull-based: each cycle wakes on a
fixed `time.sleep(poll_interval)` and reissues a fan-out of MCP reads to
discover new work. Plan-stage measurements for E17-10:

- `orchestrator_loop()` polls every 60s. Each cycle runs ≈10–15 MCP queries
  across `_worker_management_phase()`, `_poll_merge_ready_lanes()`,
  `_dispatch_phase()`, and `_guidance_phase()`.
- `worker_loop()` polls every 30s. `_poll_phase()` calls
  `poll_lane_state()`, which spawns `lane_prompt.py --check` subprocesses
  per poll.

Because the daemons keep polling whether or not new state is available,
agent-token cost scales with wall-clock runtime rather than with the rate of
real handoff events. For long-running operator pipelines this becomes the
dominant cost.

A push-based signal would let daemons sleep on event arrival rather than on
the clock, collapsing per-cycle MCP-query cost when nothing has changed.

## Anchors in code

The poll sites this rework would replace, plus the locks that bound any
push-based redesign:

- `orchestrator_loop()` — main-loop sleep at the bottom of
  `_run_orchestrator_cycle()` plus the additional `time.sleep(poll_interval)`
  sites inside the same module (paused branch and runtime-failure branch).
- `_worker_management_phase()` — fans out `manage_worker(action="status")`
  per lane.
- `_poll_merge_ready_lanes()` — iterates lanes calling
  `worker_reports(operation="list", fields="merge_ready")`.
- `_dispatch_phase()` — reads lane inbox + decisions per cycle.
- `_guidance_phase()` — reads guidance summary per cycle.
- `worker_loop()` — every `time.sleep(cfg.poll_interval)` site.
- `_poll_phase()` — calls `poll_lane_state()` which subprocesses
  `lane_prompt.py --check`.
- `poll_lane_state()` — entry point for the worker's per-poll subprocess
  spawn.
- `OrchestratorLock` and `WorkerLock` — per-process flock locks any
  push transport must coexist with.

## Alternatives

### A. sqlite `update_hook` callbacks inside the MCP process

Register `sqlite3_update_hook` against `handoff.db`. The MCP process emits
in-process callbacks on insert/update/delete; daemons co-located in the same
process select on a `threading.Event` instead of sleeping.

- **Pros**: zero new transports; uses sqlite primitives already present;
  precise event signal; no missed-update window.
- **Cons**: only fires for connections in the same process, so the daemon
  must run in-proc with the writers (or a fanout proxy must republish);
  every new daemon process needs its own hook registration; hooks fire on
  every row change, including bookkeeping the daemon does not care about, so
  filtering still costs CPU.

### B. Filesystem watcher on `handoff.db` and lane-inbox markers

Use `watchdog` (cross-platform) or `inotify` (Linux) to watch
`<state-dir>/handoff.db` mtime plus the lane-inbox marker files the
orchestrator already writes. Daemons sleep on the watcher's event queue.

- **Pros**: works across processes and across machines that share a state
  dir over a synced filesystem; no new IPC; degrades cleanly to
  longer-interval polling if the watcher backend is missing.
- **Cons**: filesystem events are coarse (a single sqlite WAL flush can
  coalesce many logical writes into one fsync); macOS FSEvents and Linux
  inotify both have "many edits in a tight loop produce one event" failure
  modes that complicate test isolation; the watcher needs a debounce to
  avoid stampede on bursty writes.

### C. Unix-domain-socket pub/sub inside the orchestrator-lock boundary

Stand up a small pub/sub server inside `OrchestratorLock`'s lifetime
(socket lives at `<state-dir>/orchestrator.sock`). MCP write paths publish
event topics (`decision_recorded`, `lane_inbox_updated`,
`merge_ready_set`); daemons subscribe and select on socket reads.

- **Pros**: explicit event topology — only the writes that matter trigger
  wake-ups; survives across processes on the same host; easy to replay /
  buffer with a small ring; integrates with the existing
  `OrchestratorLock` / `WorkerLock` ownership model.
- **Cons**: real new transport surface to maintain; needs a fallback when
  the socket dies mid-run (orphaned subscriber, crash recovery); harder to
  reason about ordering relative to sqlite WAL durability; doesn't work
  across hosts without a network bridge.

### D. Hybrid push-with-fallback-poll

Push primary signal via either A, B, or C. Keep `time.sleep` as a watchdog
at a much longer interval (e.g. 600s) to recover from missed events without
re-introducing the per-minute poll cost.

- **Pros**: retains today's correctness guarantees on the slow path while
  capturing the cost win on the hot path; bounded blast radius on transport
  failure; easy to roll out behind a feature flag.
- **Cons**: two code paths to maintain; tests must exercise both the push
  and the watchdog paths; the watchdog interval is itself a tunable knob
  with the usual "set it once and forget it" failure mode.

## Non-goals

This note does not select an alternative. It does not commit to a
transport, a backwards-compat plan, or a migration sequence. Those belong
to the follow-on epic that picks one of A–D (most likely D as the
roll-out wrapper around whichever of A/B/C the maintainers prefer).
