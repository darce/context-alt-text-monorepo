# Autonomous Lane Orchestration

## Problem Statement

The current worktree system already has the core ingredients for multi-lane orchestration: MCP-backed inboxes, deterministic dispatch, structured worker handoff, lane intake, and lane refresh. What it still lacks is unattended execution. The next step is to add daemon automation without breaking the current human-friendly workflow or duplicating responsibility across tools.

## Epic Principles

- **MCP remains the source of truth.** Dispatches, findings, worker reports, blockers, decisions, and tests continue to live in MCP.
- **Execution and handoff are separate concerns.** Worker daemons need a non-reporting implementation primitive for inner review loops; final handoff happens once, after review convergence and verification.
- **Review findings are recorded before they matter.** Daemon review output must be written to MCP before it drives retries, escalation, or completion decisions.
- **Routing is explicit.** Lane routes and merge order come from a checked-in task manifest shared by the dispatcher and orchestrator daemon.
- **Locks prevent duplicate loops.** Worker daemons lock per lane and the orchestrator daemon locks per root before polling.
- **Runtime configuration is explicit.** Daemon scripts configure MCP runtime from the orchestrator root before making MCP API calls.
- **Operator workflow stays intact.** `make lane-run`, `make lane-handoff`, `make handoff-dispatch`, and `make lane-intake` remain valid manual entry points.
- **Scheduling is optional.** launchd, cron, or other wrappers are an operational follow-up, not required for the core daemon implementation.

## Current State Analysis

- `make lane-run` already renders a lane prompt, runs Codex, and auto-submits a structured handoff through `scripts/mcp/lane_result.py`.
- `scripts/mcp/lane_prompt.py --check` already provides actionable-work detection for pull-based workers.
- `make handoff-dispatch` already routes review findings, blockers, and actions via `scripts/mcp/lane_manifest.py`, which loads a checked-in manifest from `config/lane-orchestration/<task-ref>.json`.
- `make lane-intake` already performs verified scratch-worktree intake.
- `make lane-refresh` already propagates committed orchestrator state into worker worktrees.
- `config/lane-orchestration/phase-5-retention-export-and-audit-controls.json` already defines routing, merge order, lane ownership, and downstream dependencies for the current task.
- No daemon scripts or execution primitive split exist yet.

## Target Architecture

The epic is delivered through three task plans:

1. **Daemon 1: Self-review runner**
   - Add `scripts/mcp/review_runner.py`
   - Keep review schema and result validation separate from worker handoff schema
   - Record findings in MCP before daemon callers act on them

2. **Daemon 2: Worker daemon**
   - Add a non-reporting execution primitive, `scripts/mcp/lane_exec.py`
   - Refactor `make lane-run` to stay as the human wrapper around `lane_exec.py` + `lane_result.py handoff`
   - Add `scripts/mcp/worker_daemon.py` to poll, execute, self-review, verify, and emit one final handoff

3. **Daemon 3: Orchestrator daemon**
   - Reuse the existing `config/lane-orchestration/<task-ref>.json` routing and merge-order manifest
   - Add `scripts/mcp/orchestrator_daemon.py` to dispatch, intake, refresh, and verify from root

## Delivery Shape

### Worker Flow

```text
lane_prompt.py --check
  -> lane_exec.py
  -> review_runner.py run --record-findings
  -> local fix cycle(s)
  -> make lane-check
  -> lane_result.py handoff
```

### Orchestrator Flow

```text
make handoff-dispatch
  -> list merge-ready reports
  -> make lane-intake
  -> make lane-refresh for downstream lanes
  -> record verification + decision results
```

### Shared Configuration

```text
config/lane-orchestration/<task-ref>.json
  - merge_order
  - routing
  - downstream lane dependencies
```

## Functions to Change

| File | Change |
| --- | --- |
| `scripts/mcp/review_runner.py` | New review execution and schema module |
| `scripts/mcp/lane_exec.py` | New non-reporting worker execution primitive |
| `scripts/mcp/worker_daemon.py` | New worker-side automation loop |
| `scripts/mcp/orchestrator_daemon.py` | New root-side automation loop |
| `config/lane-orchestration/<task-ref>.json` | Existing routing and merge-order manifest (already shipped) |
| `Makefile` | Add daemon targets and refactor `lane-run` around `lane_exec.py` |
| `docs/agentic/*` | Document daemon operation after the core scripts exist |

## Consolidated Checklist

## Phase 0: Review Primitive

- [ ] Implement `review_runner.py`
- [ ] Keep review schema out of `lane_result.py`
- [ ] Record daemon-driven findings in MCP before acting on them

## Phase 1: Execution Primitive Split

- [ ] Implement `lane_exec.py`
- [ ] Refactor `make lane-run` to preserve current behavior via `lane_exec.py` + `lane_result.py handoff`
- [ ] Preserve human ergonomics while unblocking daemon reuse

## Phase 2: Worker Automation

- [ ] Implement `worker_daemon.py`
- [ ] Add per-lane locking
- [ ] Keep fix cycles local rather than using `lane-dispatch`
- [ ] Emit one final merge-ready or blocked handoff per work cycle

## Phase 3: Orchestrator Automation

- [x] Routing manifest config shipped (`config/lane-orchestration/<task-ref>.json`)
- [x] `review_dispatch.py` loads routing from manifest via `lane_manifest.route_patterns()`
- [ ] Implement `orchestrator_daemon.py`
- [ ] Intake in manifest-defined order and refresh downstream dependents

## Phase 4: Operator Surface

- [ ] Add Makefile daemon targets
- [ ] Add pause/resume/status helpers
- [ ] Document long-running and single-pass usage
- [ ] Keep launchd or cron wrappers as optional follow-up docs, not core deliverables

## Success Criteria

- [ ] A worker daemon can pick up MCP lane work, iterate locally, and emit one final handoff without human intervention
- [ ] An orchestrator daemon can dispatch open work, intake merge-ready lanes, refresh downstream lanes, and record decisions/tests
- [ ] Routing works for tasks beyond the current Phase 5 slice because it is manifest-driven
- [ ] Existing manual commands continue to work unchanged alongside the daemons
