# Daemon 10: Lane-Scoped MCP Orchestration and Context Isolation

## Problem Statement

The current orchestration stack can dispatch lane work and persist state through `agent-handoff-mcp`, but the runtime still leaks too much operational complexity into worker execution. Lane workers are not yet controlled as first-class MCP lifecycle resources, lane prompts do not have a strict minimal-context contract, and cross-lane continuation still depends too heavily on ad hoc shell flows and human interpretation.

To make multi-agent orchestration token-efficient and durable, we need the orchestrator to treat MCP as the shared control plane and source of truth while every lane worker reconstructs only the narrow context required for its next task. This task should close the current gaps so workers can stay lane-scoped by default, consume compact MCP handoffs, and avoid inheriting irrelevant whole-app context.

## Workflow Principles

- **MCP is the source of truth for shared state.** Task progress, blockers, review findings, reports, cross-lane briefs, and worker lifecycle state should live in MCP-backed state, not in fragile terminal history.
- **Lane context stays narrow by default.** A worker should see only its lane objective, the current assignment, relevant local files, and compact upstream summaries required for that turn.
- **Cross-lane coordination is summarized, not replayed.** When one lane produces information another lane needs, the orchestrator should pass a concise structured brief instead of replaying full transcripts.
- **Worker automation must be MCP-addressable.** The orchestrator should be able to start, inspect, and stop lane workers through MCP without relying on repetitive shell commands.
- **Human-visible app windows are optional UX, not architecture.** Isolation should come from worktree boundaries, prompt construction, and MCP state, not from manually primed desktop sessions.
- **Failed handoffs must not cause hidden re-execution loops.** Once a worker has already completed a structured turn, any downstream handoff/report failure should surface as a durable error state instead of silently causing the same assignment to be re-run.

## Terminology

- **Lane-scoped context**: The minimal task-specific context a worker needs for one lane turn, excluding unrelated app-wide history.
- **Cross-lane brief**: A compact structured orchestrator-to-worker lane message that summarizes only the dependency information another lane needs next.
- **Worker lifecycle tool**: An MCP tool that starts, inspects, pauses, resumes, or stops a lane worker daemon.
- **Prompt contract**: The structured set of sections and data sources a lane prompt is allowed to include.
- **Context rehydration**: Rebuilding a worker's next-turn context from MCP state and lane-local files instead of relying on previous chat history.

## Current State Analysis

- `agent-handoff-mcp` already exposes orchestrator lifecycle tools and `run_structured_turn`, but it does not yet expose worker lifecycle controls such as `worker_start`, `worker_status`, or `worker_start_all`.
- `worker-daemon` currently runs as a shell-managed process, so operators still need manual `make worker-daemon ...` invocations per lane instead of letting the orchestrator bring workers online through MCP.
- `codex-subagent` already gives strong isolation by launching fresh headless `codex app-server` sessions, but that isolation is implicit and not yet shaped by a formal lane prompt contract.
- `lane_prompt.py` already assembles lane-local runtime guidance from `lane_manifest.py` and lane activity from `get_lane_activity(...)`, but it does so as free-form prose rather than an explicitly budgeted prompt contract built from named sections.
- Cross-lane continuation already has a durable transport surface in `lane_messages`, but it does not yet support a structured payload convention for concise dependency briefs.
- The real worker-loop failure mode is downstream of the structured turn: if `_run_final_handoff(...)` returns non-zero, the outer poll loop will eventually rediscover the same open assignment and re-run the lane. That applies to any handoff failure path, not only `needs_guidance`.
- Manual operator flows still assume shell-first worker control even in MCP-capable hosts, which conflicts with the goal of making MCP the control plane.

## Proposed Solution

Add a new orchestration layer on top of the existing daemon stack that formalizes lane-scoped context and moves worker control into MCP. The implementation should introduce MCP worker lifecycle tools, a structured lane prompt contract built from existing lane activity/runtime guidance surfaces, a structured brief convention on top of `lane_messages`, and a worker-reporting state machine that durably handles final-handoff failures. The orchestrator should use MCP state to rehydrate only the necessary context for each worker turn, while downstream lanes receive summarized dependency briefs instead of broad repo history.

## Patterns to Follow

### Lane Prompt Envelope

```python
prompt_sections = {
    "header": {
        "task_ref": task_ref,
        "lane_id": lane_id,
        "worktree_path": worktree_path,
        "branch": lane["branch"],
        "objective": lane["objective"],
    },
    "assignment": open_orchestrator_messages + pending_actions + open_findings + open_blockers,
    "runtime_guidance": _runtime_guidance(orchestrator_root=orchestrator_root, task_ref=task_ref, lane_id=lane_id),
    "dependency_briefs": brief_messages,
    "latest_report": latest_report,
    "reporting_contract": [
        "Run lane-local verification before handoff.",
        "Use merge-ready handoff only for committed lane-scoped changes.",
        "Use blocked report/message flow for environment or scope blockers.",
    ],
}
```

This is a refactor of the existing `lane_prompt.py` inputs, not a greenfield replacement. `assignment` should come from `get_lane_activity(...)`, `runtime_guidance` from `_runtime_guidance(...)`, and `dependency_briefs` from structured open `orchestrator_to_worker` lane messages.

### Cross-Lane Brief Contract

```json
{
  "subject": "brief:api-contract-changed",
  "message": "Backend-domain changed the export contract. Apply the downstream UI/client updates listed in payload.",
  "payload": {
    "source_lane": "backend-domain",
    "reason": "api-contract-changed",
    "summary": "Export retention endpoint now returns purge eligibility metadata.",
    "required_actions": [
      "Update UI copy for purge eligibility state.",
      "Adjust typed client contract assertions."
    ],
    "artifacts": [
      "apps/prototype-description-service/recognition/api/export_service.py",
      "apps/prototype-wp-alt-context/js/src/features/retention/export-client.ts"
    ]
  }
}
```

Implement this by extending the existing `lane_messages` surface with a structured payload field or equivalent encoded convention, rather than adding a separate briefs table.

### MCP Worker Lifecycle Tooling

```python
TOOL_DESCRIPTIONS["worker_start"] = (
    "Start a worker daemon for a specific task/lane and return pid, lock path, and log path."
)

def worker_start(task_ref: str, lane_id: str, backend: str = "codex-subagent") -> str:
    return core._json_response(
        _start_worker_daemon(  # new helper, to be created
            task_ref=task_ref,
            lane_id=lane_id,
            backend=backend,
        )
    )
```

This should follow the existing `api.py` registration model (`TOOL_DESCRIPTIONS` + handler function), and the subprocess/process-control implementation should reuse or extend `worker_daemon_ctl.py`.

### Final Handoff Failure Convergence

```python
handoff_exit = _run_final_handoff(...)
if handoff_exit != 0:
    _record_worker_handoff_failure(  # new helper, to be created
        task_ref=task_ref,
        lane_id=lane_id,
        session=session,
        result_path=final_result_path,
        failure_stage="final_handoff",
    )
    return 1
```

The problem to solve is not "`needs_guidance` loops"; it is that a completed structured turn can be re-executed when the subsequent handoff/report subprocess fails and leaves the assignment open.

## Functions to Change

| File                                                       | Line                             | Change                                                                                                                                                                                                                                            |
| ---------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`  | tool registration area           | Add MCP worker lifecycle tools (`worker_start`, `worker_status`, `worker_stop`, `worker_start_all`) using the existing `TOOL_DESCRIPTIONS` + function registration pattern; add helper entry points for structured lane-message briefs if needed. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`  | orchestrator/daemon subcommands  | Add matching CLI entry points for worker lifecycle and any structured lane-message payload operations.                                                                                                                                            |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`                             | worker loop / final handoff path | Persist machine-readable worker status, surface final-handoff failures durably, and prevent silent re-execution of the same assignment after handoff/report subprocess failure.                                                                   |
| `scripts/mcp/worker_daemon_ctl.py`                         | daemon control helpers           | Extend process management so MCP tools can start/inspect/stop lane daemons without shell-only wrappers.                                                                                                                                           |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py`                               | prompt builder                   | Refactor the existing `get_lane_activity(...)` + `_runtime_guidance(...)` prompt assembly into an explicit lane-scoped prompt contract with named sections and compact structured briefs.                                                         |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_exec.py`                                 | execution input shaping          | Consume the structured prompt envelope, enforce the reporting contract, and keep prompt overrides compatible with the new schema.                                                                                                                 |
| `scripts/mcp/orchestrator_daemon.py`                       | dispatch / dependency handling   | Generate compact cross-lane briefs as structured orchestrator-to-worker lane messages and use MCP worker lifecycle tools instead of assuming manual worker startup.                                                                               |
| `scripts/mcp/orchestrator_lanes.py`                        | lane dispatch/report helpers     | Consume the brief/message helper path from orchestrator dispatch logic and route work through MCP-addressable worker state.                                                                                                                       |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | handoff persistence model        | Extend the existing persistence model explicitly: add a structured payload field/convention on `lane_messages` for briefs, and add any worker-status storage needed for lifecycle queries.                                                        |
| `docs/agentic/playbooks/worktree-codex-playbook.md`        | workflow guide                   | Add the detailed MCP-first worker lifecycle and lane-scoped context workflow; clarify that app windows are optional.                                                                                                                              |
| `docs/agentic/contracts/agent-handoff-mcp.md`              | contract docs                    | Specify worker lifecycle tools, the lane-message payload schema for briefs, and the lane prompt contract.                                                                                                                                         |
| `docs/agentic/playbooks/lane-scoped-context.md`            | new operator guide               | Document the lane-context architecture, context budget rules, and when orchestrator-created briefs should be used.                                                                                                                                |

## Related Files

| File                                                                        | Note                                                                                                                               |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `packages/codex-subagent-bridge/src/codex_subagent_bridge.py`               | Already provides isolated headless subagent execution; this task builds on that boundary rather than replacing it.                 |
| `scripts/mcp/lane_manifest.py`                                              | Existing lane capability and preflight metadata should inform prompt construction and dispatch gating.                             |
| `scripts/worktree-lane`                                                     | Current report/handoff shell entry point is relevant for compatibility and migration even if MCP becomes the primary control path. |
| `docs/tasks/6.0/daemon-2-worker-daemon-task-plan.md`                        | Established the original worker daemon lifecycle and is the baseline for MCP-managed worker control.                               |
| `docs/tasks/6.0/daemon-3-orchestrator-daemon-task-plan.md`                  | Established orchestrator loop behavior that now needs MCP-first worker coordination.                                               |
| `docs/tasks/6.0/daemon-4-orchestrator-guidance-loop-task-plan.md`           | Guidance handling exists, but this task closes the blocked-reporting and context-passing gaps.                                     |
| `docs/tasks/6.0/daemon-7-codex-app-server-bridge-task-plan.md`              | Defined the headless app-server bridge whose isolation properties this task should leverage.                                       |
| `docs/tasks/6.0/daemon-8-portable-orchestration-backend-task-plan.md`       | Added backend registry and orchestration MCP tools; this task extends that MCP surface to workers and briefs.                      |
| `docs/tasks/6.0/daemon-9-codex-custom-mcp-session-integration-task-plan.md` | Made MCP attachable as a first-class tool surface; this task uses that surface for actual orchestration control.                   |

---

# Consolidated Checklist

## Completed

- [x] `codex-subagent` can execute isolated structured turns through headless `codex app-server` sessions.
- [x] `agent-handoff-mcp` exposes orchestrator lifecycle tools and `run_structured_turn`.
- [x] Lane orchestration can persist reports, lane messages, review findings, and task state in MCP-backed storage.
- [x] Lane manifests can declare capability/preflight gates such as the `backend-domain` Postgres gate.

## Phase 0: Scaffolding

- [x] Add worker lifecycle method signatures and MCP tool stubs in `api.py` / `cli.py`. _(Superseded; full implementations landed in Phase 1.)_
- [x] Add lane-message payload parsing helpers in `core.py` and supporting modules. _(Structured brief payloads now ride on `lane_messages.payload_json`, are decoded into `payload`, and are exposed through `record_lane_brief` / `list_lane_briefs`.)_
- [x] Add lane prompt envelope helpers and placeholder tests for prompt serialization/deserialization. _(Implemented as the named-section prompt envelope in `lane_prompt.py` with focused prompt-contract coverage.)_
- [x] Update `docs/agentic/contracts/agent-handoff-mcp.md` with scaffolded worker-lifecycle and lane-message payload schema sections.
- [x] Verify scaffolds compile and import cleanly with targeted `pytest` and `mypy` coverage. _(Full focused pytest suite: 346 passing tests across handoff state, CLI, worker lifecycle, stdio, prompt-contract, and bridge files.)_

## Phase 1: MCP-Managed Worker Lifecycle

- [x] Implement `worker_start(task_ref, lane_id, backend, poll_interval, single_pass)` as an MCP tool backed by `worker_daemon.py`. _(Also implemented `worker_resume`.)_
- [x] Implement `worker_status(task_ref, lane_id)` and `worker_stop(task_ref, lane_id)` using shared lock/log/state metadata rather than shell parsing.
- [x] Implement `worker_start_all(task_ref, backend)` for manifest-declared lanes so the orchestrator can bring the worker pool online in one call. _(Per-lane startup failures are now isolated so one broken lane does not abort the rest of the pool startup.)_
- [x] Update docs and Make targets so shell commands remain wrappers/fallbacks rather than the primary orchestration interface.

## Phase 2: Lane-Scoped Prompt Contract

- [x] Refactor `lane_prompt.py` to emit a structured lane prompt envelope with explicit sections for assignment, runtime guidance, dependency briefs, verification, and reporting contract.
- [x] Define and enforce a maximum-context policy so prompt assembly prefers compact MCP summaries over whole-transcript replay.
- [x] Ensure lane prompt generation reads only lane-relevant MCP records by default and requires explicit escalation to include broader task/global context. _(`get_lane_activity` remains the default source; `--include-lane-history` and `--include-global-context` are now explicit escalation paths.)_
- [x] Preserve compatibility for manual prompt inspection (`make lane-prompt`) while showing the new structured envelope clearly.

## Phase 3: Cross-Lane Briefs and Context Rehydration

- [x] Extend `lane_messages` with a structured brief payload field or equivalent convention and add create/list/read helpers. _(Implemented via `payload_json` plus `record_lane_brief` / `list_lane_briefs`.)_
- [x] Teach the orchestrator to synthesize a brief when downstream work depends on another lane's result instead of dumping raw lane history into the next dispatch. _(After intake, the orchestrator now emits one compact downstream brief per dependent lane using the latest merged lane report before refresh.)_
- [x] Update worker execution to rehydrate context from current assignment plus unresolved briefs rather than prior chat history. _(The lane prompt now formats unresolved `brief:` lane messages as dependency briefs and keeps broader task context opt-in.)_
- [x] Add orchestrator rules for when to issue a brief versus when to escalate to human guidance. _(Downstream briefs now emit only for merge-ready source-lane reports with no unresolved blockers; blocked or ambiguous dependencies are escalated through orchestrator guidance instead of replayed downstream.)_

## Phase 4: Blocked-State Convergence

- [x] Fix final-handoff/report failure handling so a completed structured turn is not silently re-executed when the handoff subprocess exits non-zero. _(Worker daemons now persist `handoff_failed` state with the saved result path and stop re-running the same assignment invisibly.)_
- [x] Distinguish and record durable worker states such as `waiting_for_orchestrator`, `handoff_failed`, `paused`, and `stopped` so pollers and MCP status queries can tell whether a lane should retry, wait, or surface operator intervention. _(`worker-<lane>.status.json` is now the durable worker-state record surfaced through `worker_status`.)_
- [x] Add operator-visible logs and MCP status fields that explain why a lane is idle or blocked without requiring JSONL inspection. _(`worker_status` now returns `worker_state`, `attention_required`, `state_summary`, and the persisted status-record path alongside the existing log metadata.)_

## Phase 5: Orchestrator MCP-First Dispatch

- [x] Update `orchestrator_daemon.py` to assume workers are MCP-addressable and to auto-start missing workers when policy allows. _(The orchestrator now checks actionable lanes, inspects `worker_status`, and uses `worker_start` for missing eligible workers.)_
- [x] Replace shell-oriented worker startup instructions in orchestrator docs with MCP-first flows for Codex-capable hosts. _(The playbook and MCP contract now describe orchestrator-led worker autostart, worker states, and MCP-first lifecycle control.)_
- [x] Validate that task-plan dispatch plus worker lifecycle tools can keep all eligible lanes active without manual `make worker-daemon` fan-out. _(Focused orchestration tests now cover MCP autostart and manual-mode fallback.)_
- [x] Add fallback behavior for non-MCP hosts so the orchestration model still degrades cleanly to shell control when needed. _(`worker_start_mode="manual"` leaves worker startup in shell space while preserving MCP-based state, dispatch, and status visibility.)_

## Phase 6: Tests

- [x] Add unit tests for worker lifecycle MCP tools, including success, duplicate start, missing worker, and stop/status error paths. _(worker_start, worker_status, worker_stop, worker_resume, and worker_start_all are all covered.)_
- [x] Add prompt-contract tests proving lane prompts exclude unrelated lane/task chatter unless explicitly escalated. _(Coverage now includes both lane-history and task-global escalation paths.)_
- [x] Add orchestration tests for structured lane-message brief generation and consumption. _(Coverage now includes persistence/CLI/prompt consumption plus orchestrator-side downstream brief synthesis.)_
- [x] Add worker-daemon tests covering final-handoff failure persistence and no-repeat execution after a recorded handoff failure.
- [x] Add an end-to-end MCP-host integration test showing the orchestrator can start workers, dispatch lane work, and observe results without shell commands. _(Focused MCP/orchestrator tests now cover worker autostart, manual fallback mode, and MCP-managed lifecycle control.)_

## Stretch Goals

- [x] Add a reusable "shared lane session" mode that preserves context only within one lane when repeated continuity is beneficial, while keeping cross-lane isolation intact. _(`worker_start`, `worker_start_all`, and the worker daemon now accept `session_mode="shared_lane"`; `lane_exec.py` forwards that to the shared-session bridge mode without relaxing cross-lane worktree isolation.)_
- [x] Add token-budget instrumentation to lane prompt generation so prompts can report how much context came from assignment, MCP briefs, and local file excerpts. _(`lane_prompt.py` now emits a dedicated "Prompt Budget" section summarizing the relative contribution of assignment inbox, dependency briefs, runtime guidance, lane history, and escalated task context.)_
- [x] Add prioritization rules so `worker_start_all` can skip lanes whose dependencies are unresolved instead of starting every lane indiscriminately. _(`worker_start_all(...)` now follows manifest merge order and returns `skipped` results with `blocked_by` details when upstream lanes still have unresolved dispatched work.)_

## Success Criteria

- [x] In an MCP-capable Codex session, the orchestrator can start, inspect, and stop lane workers through MCP tools without manual per-lane shell commands.
- [x] A worker turn can be rehydrated from lane-local files plus MCP-backed assignment and brief data without needing unrelated whole-app transcript context.
- [x] Cross-lane dependencies are passed as compact structured briefs rather than replayed transcripts.
- [x] A lane whose final handoff/report step fails records a durable machine-readable failure state instead of re-running the same completed assignment invisibly.
- [x] Docs clearly describe lane-scoped context as the default architecture and explain that visible app windows are optional operator UX, not the isolation boundary.
