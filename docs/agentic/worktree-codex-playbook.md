# Worktree Codex Playbook

Use this playbook when operating multi-agent worktree lanes in this repo. Covers both orchestrator (human or lead agent) and worker (Codex or interactive agent) perspectives.

## Goal

Start workers in the correct worktree, on the correct branch, with the correct lane inbox and handoff commands available. Complete the full lifecycle from task decomposition through lane merge and close.

## Task Manifests

Each task that uses lane automation should define its orchestration config in `config/lane-orchestration/<task-ref>.json`.

Start from the generic scaffold command:

```bash
make lane-manifest-init TASK=<task-ref> LANE_IDS='backend frontend' TASK_PLAN=docs/tasks/...md
```

That manifest is the source of truth for:

- lane ids and branch names
- worktree path templates
- owned paths and commit scope
- required docs and verification commands
- merge order and dispatch routing hints
- `token_burn_threshold` (default 2000000): cumulative token ceiling before `token_burn_warning` events fire
- `model_context_window` (default 128000): model context window size used for context utilization scoring

When a lane declares `app_root`, `owned_paths`, or `tooling_paths` that resolve to
an app with `composer.json` or `package.json`, the lane runtime now treats that as
bootstrap/preflight metadata too. New lanes inherit default dependency checks from
those paths even when a manifest does not manually spell out `preflight_commands`.

To add lane automation for a new task, add a new manifest first. The root `Makefile`, `review_dispatch.py`, and the worker helpers read from that manifest instead of from task-specific hardcoded tables.

## Terminology

- orchestrator root: the main repo checkout, usually `/Users/daniel/Development/context-alt-text-monorepo`
- worker worktree: a sibling checkout created for one lane
- task ref: the active MCP task, for example `phase-5-retention-export-and-audit-controls`
- lane id: the worker slice name, for example `backend-domain`, `backend-http`, `wp-proxy`, or `frontend`

## Current repo examples

Current worker worktree examples:

- `/Users/daniel/Development/context-alt-text-monorepo-p5-backend-domain`
- `/Users/daniel/Development/context-alt-text-monorepo-p5-backend-http`
- `/Users/daniel/Development/context-alt-text-monorepo-p5-wp-proxy`
- `/Users/daniel/Development/context-alt-text-monorepo-p5-frontend`

Current lane examples:

- `backend-domain` -> branch `codex/p5-backend-domain`
- `backend-http` -> branch `codex/p5-backend-http`
- `wp-proxy` -> branch `codex/p5-wp-proxy`
- `frontend` -> branch `codex/p5-frontend`

---

## Quick Reference

### Orchestrator one-liners (run from orchestrator root)

```bash
make lane-open TASK=<task> LANE=<lane>                         # Create/open a lane
make lane-manifest-init TASK=<task> LANE_IDS='lane-a lane-b'   # Scaffold a task manifest
make lane-dispatch TASK=<task> LANE=<lane> MESSAGE="..."       # Assign work
make handoff-dispatch TASK=<task>                              # Route findings / blockers / next actions to lanes
make handoff-inbox TASK=<task>                                 # Poll worker handoffs
make lane-commits TASK=<task> LANE=<lane>                      # Preview intake
make lane-intake TASK=<task> LANE=<lane>                       # Merge a lane
make lane-refresh TASK=<task> LANE=<lane>                      # Sync lane to root
make lane-list                                                 # List all lanes
make state                                                     # Full MCP state
make dashboard                                                 # MCP dashboard
make orchestrator-daemon [TASK=<task>] [BACKEND=codex-cli|codex-subagent] [MODEL=gpt-5.4-mini]
make artifact-list TASK=<task> [LANE=<lane>]                  # List indexed evidence
make artifact-search TASK=<task> QUERY="schema missing"       # Search indexed evidence
```

### Worker one-liners (run from worker worktree)

```bash
make lane-inbox                                                # Poll assignments
make lane-prompt                                               # Render actionable prompt
make lane-prompt EXTRA_ARGS=--include-lane-history             # Escalate prompt rendering to include recent lane decisions/tests
make lane-prompt EXTRA_ARGS=--include-global-context           # Escalate prompt rendering to include compact task-wide context
make lane-check                                                # Run lane tests
make worker-daemon TASK=<task> LANE=<lane> [BACKEND=codex-cli|codex-subagent] [MODEL=gpt-5.4-mini]  # Continuous worker polling loop
make worker-daemon-status                                      # Inspect lock/PID/log state
make worker-daemon-stop                                        # Stop the lane daemon
make worker-daemon-resume                                      # Resume a stopped lane daemon
make worker-daemon-tail                                        # Tail the lane daemon log
make lane-handoff                                              # Commit + report + hand off
make lane-report STATUS=blocked MERGE_READY=0 SUMMARY="..." MESSAGE="..."  # Blocked report
```

All `lane-*` commands work from the repo root and from the app directories that ship forwarding Makefiles. The app-level Makefiles use a `lane-%:` pattern rule that auto-forwards any `lane-*` target to the root Makefile, so new lane targets never need to be registered in the app Makefiles. `worker-daemon` should be launched from the worker worktree root. If you are already in an app subdirectory and that checkout does not yet forward `worker-daemon`, use `make -C "$$(git rev-parse --show-toplevel)" worker-daemon ...`.

## Bootstrap and Install

Bootstrap these pieces before relying on daemon-based orchestration or artifact retrieval:

```bash
cd /Users/daniel/Development/context-alt-text-monorepo

# MCP server package
uv tool install ./packages/agent-handoff-mcp

# Codex app-server bridge used by BACKEND=codex-subagent
python3 -m pip install -e packages/codex-subagent-bridge

# Optional dashboard dependencies for richer monitoring UI
PYENV_VERSION=description-service python3 -m pip install -e "apps/prototype-description-service[dashboard,dev]"

# Verify writable state dirs, bridge import paths, and SQLite FTS5 support
agent-handoff-mcp --workspace-root "$(pwd)" doctor
```

Notes:

- `dashboard-live` works without optional UI packages. `dashboard-tui` uses Textual when installed, falls back to `rich.live` when only `rich` is available, and finally to plain text.
- If you are running from repo source instead of an installed `agent-handoff-mcp` binary, use `PYTHONPATH="packages/agent-handoff-mcp/src:packages/codex-subagent-bridge/src" python3 -m agent_handoff_mcp ...`.
- Artifact retrieval requires SQLite FTS5. Treat a failing `doctor` as a blocker before starting continuous orchestration.

### Execution backends

Both daemons default to `BACKEND=codex-cli`.

- `BACKEND=codex-cli`: runs the normal `codex exec` subprocess flow.
- `BACKEND=codex-subagent`: uses the host-provided `codex_subagent_bridge` module instead of spawning `codex exec`.
- `BACKEND=claude-code`: uses the `claude` CLI (Anthropic) for execution.
- `BACKEND=local-model-openai`: uses a generic OpenAI-compatible local model API (Ollama, vLLM).

Backend dispatch is now registry-based, not duplicated per caller. The shared
registry lives at
[`scripts/mcp/backend_registry.py`](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/backend_registry.py).
`lane_exec.py`, `review_runner.py`, and the daemon CLI surfaces all read backend
choices from that registry. New bridge backends should be added there instead of
editing `if backend == ...` branches in multiple files.

### Model & Reasoning Effort

The orchestrator can control the execution model and reasoning effort for each lane:

- `model`: Explicitly set the LLM to use (e.g. `o3-mini`, `gpt-4o`, `claude-3-5-sonnet`).
- `reasoning_effort`: Controls the "thinking" budget for supported models. Choices: `low`, `medium`, `high`, or `auto` (default). `auto` uses internal heuristics (e.g., follow-up cycles or backend-heavy tasks escalate to `high`).
- **Effort escalation after exhaustion:** The `_escalate_effort()` ladder in `_env.py` enforces `low -> medium -> high -> xhigh` after each exhaustion. Effort MUST go up on failure, never down. A real failure in this project (backend-domain auto-lowered from medium to low after exhaustion) caused 7M+ tokens burned in non-converging loops.

These are typically set in the lane manifest but can be overridden via MCP:

```bash
agent-handoff-mcp dispatch_lane_work --task-ref <task> --lane-id <lane> --model o3-mini --reasoning-effort high
```

### Cost-Sensitive Lane Guidance

When dispatching to model-backed lanes (especially high-reasoning ones), provide narrow, actionable briefs to minimize token waste. If a lane is stalled, escalate to an operator instead of re-running expensive high-reasoning turns with the same prompt.

- If a lane has `exhaustion_streak >= 2`, the orchestrator daemon auto-gates it (`lane_unhealthy`) and skips auto-start. Do not redispatch until an explicit operator decision (e.g., `promote_model`, `split_lane`, `close_lane`, `fresh_worktree`).
- Cumulative tokens exceeding the lane's `token_burn_threshold` (default 2M) trigger a `token_burn_warning` event and set `attention_required` on the lane.
- Use `preferred_model` and `preferred_reasoning_effort` in the manifest for the default lane posture, then override per-lane with `dispatch_lane_work(...)` only when the current slice truly needs a different model size or effort level.

Workers synchronize their internal state with these authoritative MCP values at the start of each execution cycle.

### Agent Configuration Utility

Use `scripts/mcp/generate_agent_config.py` to initialize a worktree with settings derived from the lane manifest:

```bash
python3 scripts/mcp/generate_agent_config.py --task-ref <task> --lane-id <lane> --output .agent/config.json
```

Important:

- `codex-subagent` is only available when the current runtime has provisioned that bridge module.
- The bridge should accept the lane/review prompt, output schema, worktree `cwd`, and may also receive an optional `env` map with lane-scoped runtime hints such as `TMPDIR` and `PYENV_VERSION`.
- If the bridge is unavailable, the daemon raises an error; it does not silently fall back to `codex-cli`.
- The backend changes only the execution seam. MCP handoff, lane manifests, worktree isolation, and intake/merge flow stay the same.
- The in-repo reference bridge now lives at `packages/codex-subagent-bridge/`. Install it editable (`pip install -e packages/codex-subagent-bridge`) or expose its `src/` directory on `PYTHONPATH` so `import codex_subagent_bridge` succeeds in the daemon runtime.
- The bridge forwards runtime hints only as local process/session context. Today that means lane-scoped environment values such as `TMPDIR`, `PATH`, and `PYENV_VERSION` become subprocess environment for `codex app-server`, while reasoning effort may be forwarded from `CODEX_REASONING_EFFORT` or `REASONING_EFFORT` into `turn/start.effort`.
- MCP endpoints, credentials, and handoff writes are intentionally not forwarded through the bridge. Any MCP interaction stays in the parent daemon process.
- Spawned app-server sessions discover repo instructions from the worktree root (`CLAUDE.md` / `GEMINI.md` symlinked to `docs/agentic/instructions.md` in this repo). There is no `AGENTS.md` here.
- Build and test commands still need to be discoverable by the spawned agent. In practice that means keeping them in the repo instruction surface or rendering them directly into the lane/review prompt.
- The reference bridge is safe for parallel daemon calls because each `run_subagent()` invocation starts its own short-lived `codex app-server` process; there is no shared in-process session state.

146:
147: ### Model Selection Guidance
148:
149: | Backend | Supported Models | Reasoning Effort Support |
150: | --- | --- | --- |
151: | `codex-cli` | `gpt-4o`, `gpt-4o-mini`, `o1-preview` | `low`, `medium`, `high` |
152: | `codex-subagent` | `gpt-4o`, `o1-mini`, `o3-mini` | `low`, `medium`, `high`, `xhigh` |
153: | `claude-code` | `claude-3-5-sonnet` (default) | Not applicable (model-driven) |
154:
155: **Note:** `xhigh` effort is only supported by the `codex-subagent` bridge today. Using `xhigh` with `codex-cli` will fall back to `high`.
156:
157: ### MCP orchestration commands

For in-app agents that can call MCP tools directly, `agent-handoff-mcp` now exposes
an orchestration control surface in addition to the existing handoff state tools.

- `orchestrator_start(task_ref, backend, poll_interval, single_pass, model=None)`
- `orchestrator_status()`
- `orchestrator_stop(force=False)`
- `orchestrator_pause()`
- `orchestrator_resume()`
- `orchestrator_single_cycle(task_ref, backend, model=None, worker_start_mode="mcp")`
- `worker_start(task_ref, lane_id, backend, poll_interval, single_pass, session_mode, model=None, reasoning_effort=None)`
- `worker_status(task_ref, lane_id)`
- `worker_stop(task_ref, lane_id, force=False)`
- `worker_resume(task_ref, lane_id)`
- `worker_event_history(task_ref, lane_id, limit=20)`
- `worker_start_all(task_ref, backend, poll_interval, single_pass, session_mode, model=None)`
- `run_structured_turn(prompt, schema, cwd, backend, env=None, model=None, reasoning_effort=None, timeout_seconds=120.0)`
- `dispatch_lane_work(task_ref, lane_id, model=None, backend=None, reasoning_effort=None)`
- `list_available_backends()`
- `switch_task(task_ref, objective=None, status="in_progress", actor=None)` -- atomically archive+switch active task

Use these when the host agent already has MCP access and you want to avoid driving
daemon lifecycle through a shell or `run_in_terminal`.

Important:

- `run_structured_turn` is bridge-only. It rejects `codex-cli` because synchronous
  `codex exec` management belongs in the daemon/worker path.
- The MCP daemon controls operate on the authoritative orchestrator checkout, using
  the same lock, pause sentinel, logs, and `.task-state` conventions as the Make
  wrappers.
- `worker_status(...)` exposes durable lane-state hints in addition to PID/log metadata. Use `running`, `worker_state`, `attention_required`, and `state_summary` together. Important states include `idle`, `waiting_for_orchestrator`, `handoff_failed`, `paused`, and `stopped`.
- Use `session_mode="fresh_turn"` for the default fully isolated turn model, or `session_mode="shared_lane"` when you want repeated worker turns in one lane to reuse the same bridge session without leaking context across lanes.
- `orchestrator_start(...)` and `single-cycle` default to `worker_start_mode="mcp"`, which lets the orchestrator auto-start missing actionable workers through MCP. Use `worker_start_mode="manual"` when the host should keep worker startup in shell space.
- Treat lane worktrees as branch-local truth. If the orchestrator/root branch has uncommitted or manually salvaged scaffolding that has not been propagated into the lane branch, the worker cannot see it. Before dispatching a dependent slice, verify required contract/stub files exist in the worker worktree or explicitly hold that lane.
- `handoff_failed` is sticky. If a worker completed execution but remains in `handoff_failed`, salvage/intake the saved result first, then recycle the daemon with `worker_stop(..., force=True)` plus `worker_start(...)` for the next assignment. A fresh lane message by itself does not reliably clear the old saved-result state.
- `worker_stop(...)` now cleans up the lock file and emits a `worker_stopped` event. After stop, `worker_status(...)` reports `lock.held: false` consistently with no stale artifacts.
- `worker_status(...)` now includes hardening signals: `exhaustion_streak` (int), `cumulative_tokens` (int), `health` (`healthy` / `degraded` / `unhealthy`), and a `context_utilization` sub-dict with `utilization_ratio`, `domain_signal_ratio`, and `pressure` (`normal` / `elevated` / `high`).

### Scope Enforcement

Scope enforcement is a **runtime gate**, not advisory. After each worker execution turn, `lane_exec.py` validates the worktree diff against the lane's `effective_owned_paths` (or manifest `owned_paths`) before submitting the turn for review. A scope violation skips review entirely and emits a `scope_violation` JSONL event.

- The orchestrator can narrow scope for a specific dispatch by embedding `effective_owned_paths` as a JSON-encoded string in the `artifacts` list of a dispatch lane message (e.g., `artifacts=[json.dumps({"type": "owned_paths_override", "paths": [...]})]`). `lane_exec.py` reads from the most recent `orchestrator_to_worker` message and prefers the override over manifest `owned_paths`.
- Workers that detect out-of-scope needs should record a blocker or lane message for the orchestrator instead of editing files outside their lane.

### Lane Health Scoring

`_check_lane_health()` in `orchestrator_daemon.py` scores each lane as `healthy`, `degraded`, or `unhealthy` based on:

- Exhaustion streak (consecutive non-converged review cycles)
- Scope violation history
- Cumulative token burn relative to `token_burn_threshold`
- Context pressure from `_measure_context_utilization()`

Health transitions emit `lane_health_changed` JSONL events. Lanes scored `unhealthy` (`exhaustion_streak >= 2`) are auto-gated by the orchestrator daemon; they require an explicit operator decision before work resumes.

Recommended actions for unhealthy lanes: `promote_model`, `split_lane`, `close_lane`, or `fresh_worktree`.

### Context Freshness

`_measure_context_utilization()` in `lane_prompt.py` computes:

- `utilization_ratio`: prompt tokens / `model_context_window` (from manifest, default 128K)
- `domain_signal_ratio`: domain-relevant content / total prompt content
- `pressure`: `normal` (< 0.6), `elevated` (0.6-0.8), or `high` (> 0.8)

Context pressure is reported in `worker_status(...)` and emitted as a `context_pressure` JSONL event when elevated or high. Elevated pressure suggests trimming non-essential prompt sections; high pressure risks truncation.

### Worker Daemon JSONL Events

The worker daemon emits structured JSONL events to `logs/worker-daemon/worker-<lane>.jsonl` for health-relevant conditions:

| Event                 | Trigger                                              |
| --------------------- | ---------------------------------------------------- |
| `scope_violation`     | Files outside `owned_paths` detected post-execution  |
| `exhaustion_streak`   | Consecutive non-converged review cycles              |
| `token_burn_warning`  | Cumulative tokens exceed `token_burn_threshold`      |
| `worker_stopped`      | Clean shutdown with lock cleanup                     |
| `context_pressure`    | Prompt consuming unsafe fraction of context window   |
| `lane_health_changed` | Health state transition (healthy/degraded/unhealthy) |

Use `worker_event_history(task_ref, lane_id, limit=20)` via MCP to query recent events without tailing log files.

- For remote HTTP custom-MCP attachment (e.g. Codex custom MCP), see
  [codex-custom-mcp-playbook.md](codex-custom-mcp-playbook.md). Start the server
  with `make mcp-serve-http`, verify the endpoint, then attach in Codex settings.

---

## Recipes

### Recipe: Open a new lane

**Who:** Orchestrator. **When:** Starting a new worker slice.

```bash
cd /Users/daniel/Development/context-alt-text-monorepo
MODEL=o3-mini make lane-open TASK=<task-ref> LANE=<lane>
```

What this does:

- verifies or creates the lane registration in MCP
- hard-fails if an existing worktree is on the wrong branch for that lane
- prints the lane brief (owned paths, test commands, non-goals)
- proves the target worktree branch with `git status -sb`
- polls the lane inbox immediately so the worker sees open orchestrator messages before coding
- opens an interactive shell in the worker worktree by default

After the subshell opens, verify:

```bash
pwd                       # should be the lane worktree path
git branch --show-current # should be the lane branch
make lane-inbox           # should show any open dispatches
```

To stay in the orchestrator root instead of opening a subshell:

```bash
MODEL=o3-mini make lane-open TASK=<task-ref> LANE=<lane> ENTER_SHELL=0
cd "$(make lane-path TASK=<task-ref> LANE=<lane>)"
```

### Recipe: Dispatch work to a lane

**Who:** Orchestrator. **When:** Assigning or reassigning work to a worker.

```bash
make lane-dispatch TASK=<task-ref> LANE=<lane> MESSAGE="Wire the retention router to the real services and verify pytest + mypy."
```

What this does:

1. Upserts the lane registration to `active` status.
2. Sends an open `orchestrator_to_worker` lane message.
3. Regenerates `CURRENT_TASK.md` so the dispatch is human-readable.

The worker sees it the next time they run `make lane-inbox`.

Prompt-shaping note:

- `make lane-prompt` is intentionally narrow by default: it shows the assignment inbox, runtime guidance, compact dependency briefs, and the latest report.
- The rendered prompt now also includes a compact "Prompt Budget" section so you can see how much context each prompt section contributes before escalating.
- Recent lane decisions/tests are omitted unless you explicitly escalate with `EXTRA_ARGS=--include-lane-history`.
- Broader task-wide context is also omitted unless you explicitly escalate with `EXTRA_ARGS=--include-global-context`.
- If a lane needs cross-lane or global task context, send a compact orchestrator brief instead of replaying whole transcripts into the worker prompt.
- Before dispatching a dependent lane, check the actual worker worktree for required files or branch-local scaffolding. Root-branch changes do not magically appear in sibling lane branches. If the worker reports missing contracts or repository surfaces, prefer a hold/re-refresh over speculative implementation.

Structured-brief note:

- Orchestrators can now send compact dependency handoffs with `agent-handoff-mcp lane-brief ...` or the MCP tool `record_lane_brief(...)`.
- Workers can inspect only those dependency briefs with `agent-handoff-mcp lane-brief-list ...` or `list_lane_briefs(...)` instead of scanning the full lane message history.
- Only emit downstream briefs when the upstream lane already produced a merge-ready result with no unresolved blockers. If the upstream lane is blocked or the dependency is still ambiguous, escalate with orchestrator guidance instead of replaying partial transcripts downstream.

To preview without writing:

```bash
make lane-dispatch TASK=<task-ref> LANE=<lane> MESSAGE="..." DRY_RUN=1
```

### Recipe: Dispatch lanes from a task plan

**Who:** Orchestrator. **When:** Turning a reviewed task plan into concrete worker lanes.

```bash
make lane-manifest-init TASK=<task-ref> \
  LANE_IDS='lane-a lane-b lane-c' \
  TASK_PLAN=docs/tasks/8.0/<task-plan>.md
```

Then fill the manifest from the task plan's lane table:

1. Copy lane ids, owned paths, and required tests from the plan into `config/lane-orchestration/<task-ref>.json`.
2. Set runtime defaults per lane: `preferred_model`, `preferred_reasoning_effort`, `token_burn_threshold`, and `model_context_window`.
3. Open or refresh each lane with `make lane-open TASK=<task-ref> LANE=<lane>`.
4. Use `agent-handoff-mcp dispatch-lane-work --task-ref <task-ref> --lane-id <lane> --backend codex-subagent --model gpt-5.4-mini --reasoning-effort auto` to set execution posture for that lane.
5. Send the human-readable assignment with `make lane-dispatch ...` or a structured dependency summary with `agent-handoff-mcp lane-brief ...`.

Dispatch content should come from the task plan, not from ad-hoc chat memory:

- objective for that lane
- owned paths / scope boundaries
- required verification commands
- explicit non-goals
- upstream dependency notes
- artifact refs for bulky evidence instead of pasted logs

If the plan defines merge order, respect it in `worker_start_all(...)` or `make orchestrator-daemon`; upstream incomplete lanes should block downstream auto-starts.

### Recipe: Worker implements a slice

**Who:** Worker (agent or human). **When:** After receiving a dispatch.

```bash
# 1. Check what work is assigned
make lane-inbox

# 2. Read the detailed prompt (includes findings, actions, blockers)
make lane-prompt

# 3. Optionally sync with latest orchestrator changes
make lane-refresh

# 4. Implement changes within lane-owned paths only

# 5. Verify before handoff
make lane-check

# 6. Hand off (commits lane-owned files, submits merge-ready report)
make lane-handoff
```

Notes:

- `make lane-check` runs the lane's configured test commands (`LANE_TEST_CMD_1`, `LANE_TEST_CMD_2`) in the current worktree and records each result into MCP, so lane activity keeps a durable verification trail. Run it before `make lane-handoff` to catch failures early.
- `make lane-check` is not a full lint/format gate. Before submitting `merge_ready=1`, run lint + format checks for touched stacks (or `make check-all` if your slice spans multiple stacks). This prevents "tests green, check-all red" handoffs caused by formatter/import-order regressions.
- `make lane-handoff` will refuse to proceed if there are no unique lane commits or if out-of-scope files are present.
- If you need a custom commit message: `make lane-handoff COMMIT_MSG="implement retention policy service"`.
- For backend Python lanes, prefer commands that embed `PYENV_VERSION=description-service` instead of relying on `pyenv activate description-service` in subprocesses. If you need an interactive shell activation, load pyenv first with `eval "$$(pyenv init -)"` and `eval "$$(pyenv virtualenv-init -)"`.

### Recipe: Run a continuous worker daemon

**Who:** Worker (agent or human). **When:** You want the lane to keep polling MCP and execute work automatically.

```bash
cd /Users/daniel/Development/context-alt-text-monorepo-p5-backend-domain
make worker-daemon TASK=<task-ref> LANE=<lane>
make worker-daemon TASK=<task-ref> LANE=<lane> BACKEND=codex-subagent
```

What this does:

1. Polls the lane inbox for actionable work.
2. Runs `codex exec` with the rendered lane prompt.
3. Submits the final handoff automatically.
4. Repeats until stopped.

Hardening behavior:

- **Scope enforcement:** After each execution turn, the daemon validates the worktree diff against `effective_owned_paths`. A scope violation skips review, emits a `scope_violation` event, and marks the turn as failed.
- **Exhaustion tracking:** Consecutive non-converged review cycles increment `exhaustion_streak`. After each exhaustion, reasoning effort auto-escalates one level (never decreases). At streak >= 2, the lane is marked `unhealthy` and the orchestrator daemon gates further auto-starts.
- **Token burn:** Cumulative tokens are tracked per lane. Exceeding `token_burn_threshold` (default 2M, configurable in manifest) fires a `token_burn_warning` event.
- **Context pressure:** Each cycle measures prompt utilization against `model_context_window`. Elevated or high pressure emits a `context_pressure` event.
- **Artifact indexing:** Large execution `details` payloads are indexed into `.task-state/mcp-artifacts.db` and replaced inline with a compact excerpt plus `details_artifact_ref`.

### Phase 5: Verification & Handoff

Phase 5 represents the final delivery and audit stage:

1. **Sub-Phase 5.1: Cross-Lane Verification.** Once all lanes are merged, run full integration tests (`make check-all`) in the orchestrator root.
2. **Sub-Phase 5.2: Documentation Audit.** Verify all `docs/`, `CURRENT_TASK.md`, and `CHANGELOG` are consistent with the implemented reality.
3. **Sub-Phase 5.3: Handoff Closure.** Perform a final `agent-handoff-mcp handoff-close-check --task-ref <task>` to ensure all findings are resolved and provenance is complete.

### Recipe: In-app orchestration via MCP

**Who:** Orchestrator or lead in-app agent. **When:** The host already exposes
`agent-handoff-mcp` as MCP tools and you want to control orchestration without shell
commands.

Typical flow:

1. Call `orchestrator_start(task_ref="<task-ref>", backend="codex-cli" | "codex-subagent")`.
2. Let the default `worker_start_mode="mcp"` bring missing actionable workers online automatically, or use `worker_start(...)` / `worker_start_all(...)` when you want explicit worker control.
3. Poll `orchestrator_status()` / `worker_status(task_ref="<task-ref>", lane_id="<lane>")` until work begins flowing.
4. Use `run_structured_turn(...)` when you need one synchronous bridge-backed
   execution turn without starting a worker daemon.
5. Call `orchestrator_pause()` / `orchestrator_resume()` when the singleton loop
   needs to be temporarily gated.
6. If the host should keep worker startup outside MCP, start the orchestrator with `worker_start_mode="manual"` and use the existing `make worker-daemon ...` shell wrappers as the fallback path.
7. Call `worker_stop(...)` / `worker_resume(...)` for lane-local control, and `orchestrator_stop()` when orchestration should exit cleanly.

Use Make targets when you are operating from a shell-first workflow. Use MCP tools
when you are already inside an MCP-capable agent host and want the same control plane
without shell mediation.

Notes:

- The foreground terminal now shows `exec_start`, `exec_spawned`, and periodic `exec_heartbeat` markers while `codex exec` is still running.
- Detailed JSONL progress is still written to `logs/worker-daemon/worker-<lane>.jsonl`.
- `worker_start_all(...)` uses the checked-in lane manifest order and returns per-lane results. It now skips lanes whose upstream dependencies still have unresolved work, reporting `skipped` results with `blocked_by` details instead of starting every lane indiscriminately.
- If a second worker daemon is started for the same lane, the per-lane lock will reject it with `Another worker daemon is already running for lane '<lane>'`.
- Use `make worker-daemon-status` to see the shared-root lock path, current PID/state, and the latest JSONL event. Use `make worker-daemon-stop` or `make worker-daemon-resume` instead of sending manual signals when possible.
- A `handoff_failed` worker state means the implementation/review turn already completed but the final report handoff did not persist. Fix the MCP/handoff issue first, then retry or restart the worker so it can replay the saved result instead of rerunning the lane assignment.
- Visible Codex app windows are optional operator UX only. Lane isolation comes from worktree boundaries, lane-scoped prompt construction, and MCP state rehydration rather than from keeping a desktop session open.
- `worker_status(...)` is the primary telemetry surface for both humans and agents. Inspect model, requested/effective reasoning effort, cumulative token totals, health, and `context_utilization.pressure` before redispatching or promoting a lane.

### Recipe: Monitor lane health with the dashboard

**Who:** Orchestrator. **When:** Monitoring active lanes for health, token burn, exhaustion, and context pressure.

```bash
# Polling dashboard (refreshes every 10s by default)
make dashboard-live

# Interactive Textual TUI (requires dashboard optional deps)
make dashboard-tui
```

The dashboard shows per-lane: composite state, health (`healthy` / `degraded` / `unhealthy`), cycle count, model, effort, cumulative tokens, context pressure, and exhaustion streak.

Use `worker_status(task_ref, lane_id)` via MCP for programmatic access to the same signals.

When a lane is flagged `unhealthy`, the orchestrator daemon skips auto-start and emits `lane_unhealthy`. The operator must decide on an explicit recovery action (`promote_model`, `split_lane`, `close_lane`, or `fresh_worktree`) before work resumes.

### Recipe: Retrieve large evidence without prompt bloat

**Who:** Orchestrator or worker. **When:** Logs, test output, or copied docs are too large to paste into a lane message or prompt.

```bash
# Search the artifact sidecar
make artifact-search TASK=<task-ref> QUERY="column missing" [LANE=<lane-id>]

# List available indexed sources
make artifact-list TASK=<task-ref> [LANE=<lane-id>]

# Full-fidelity readback by source id
agent-handoff-mcp --workspace-root "$(pwd)" artifact-get --source-id <id>
```

Operational guidance:

- Attach artifact refs to lane messages with `agent-handoff-mcp lane-message --artifact <id> ...` when you want the next worker prompt to prioritize exact evidence.
- `lane_prompt.py` currently consumes pinned artifact refs from lane-message payloads first, then falls back to scoped FTS search by lane message text, blockers, and findings.
- Use `artifact-purge` or `purge_artifacts(...)` for retention cleanup after archival or when the cache grows too large.

### Recipe: Worker is blocked

**Who:** Worker (agent or human). **When:** Cannot proceed due to sandbox, permissions, missing dependencies, or unclear requirements.

```bash
make lane-report STATUS=blocked MERGE_READY=0 \
  SUMMARY="Cannot install Python deps in scratch worktree" \
  MESSAGE="Verified schema migration is correct. pytest cannot run because venv is missing. Recommend SKIP_TESTS=1 on intake or orchestrator runs tests manually."
```

What this does:

1. Submits a blocked worker report (no lane commit required).
2. Sends a `worker_to_orchestrator` lane message so the orchestrator sees it in `make handoff-inbox`.
3. Sets the lane status to `blocked`.

The orchestrator picks it up with `make handoff-inbox TASK=<task-ref>` and decides next steps.

### Recipe: Poll for worker handoffs

**Who:** Orchestrator. **When:** Waiting for workers to finish, or checking progress.

```bash
make handoff-inbox TASK=<task-ref>
```

Shows:

- Open `worker_to_orchestrator` lane messages (merge-ready handoffs, guidance requests).
- Latest worker reports with merge-ready or blocked status.

To filter to a specific lane:

```bash
make handoff-inbox TASK=<task-ref> LANE=backend-domain
```

### Recipe: Route review findings to lanes

**Who:** Orchestrator. **When:** After recording review findings in MCP from the orchestrator root.

```bash
# Step 1: Record findings using MCP tools (record_review_finding)
# Step 2: Route them to the correct worker lanes
make handoff-dispatch TASK=<task-ref>
```

What `handoff-dispatch` does:

1. Loads all open, unassigned review findings, blockers, and next actions from MCP.
2. Routes each to a lane based on file path patterns or text hints.
3. Stamps the lane assignment on each item.
4. Sends lane messages so workers see the queue in `make lane-inbox`.
5. Records a dispatch decision in MCP.

To preview without sending:

```bash
make handoff-dispatch TASK=<task-ref> DRY_RUN=1
```

### Recipe: Inspect plan cursor state

**Who:** Orchestrator. **When:** A task-plan-driven daemon is dispatching work and you need to inspect or override cursor state.

Check the active task and current runtime view first:

```bash
make state
```

List plan cursors directly:

```bash
PYTHONPATH="packages/agent-handoff-mcp/src" python3 -m agent_handoff_mcp \
  --workspace-root /Users/daniel/Development/context-alt-text-monorepo \
  --state-dir /Users/daniel/Development/context-alt-text-monorepo/.task-state \
  --current-task-path /Users/daniel/Development/context-alt-text-monorepo/CURRENT_TASK.md \
  --exports-dir /Users/daniel/Development/context-alt-text-monorepo/.task-state/exports \
  review-summary --task-ref <task-ref>

PYTHONPATH="packages/agent-handoff-mcp/src" python3 -m agent_handoff_mcp \
  --workspace-root /Users/daniel/Development/context-alt-text-monorepo \
  --state-dir /Users/daniel/Development/context-alt-text-monorepo/.task-state \
  --current-task-path /Users/daniel/Development/context-alt-text-monorepo/CURRENT_TASK.md \
  --exports-dir /Users/daniel/Development/context-alt-text-monorepo/.task-state/exports \
  dashboard
```

For direct cursor inspection or override, use the Python API helpers from the orchestrator root:

```bash
PYTHONPATH="packages/agent-handoff-mcp/src" python3 - <<'PY'
from agent_handoff_mcp import list_plan_cursors, upsert_plan_cursor
print(list_plan_cursors(task_ref="<task-ref>", state="all"))
print(upsert_plan_cursor(task_ref="<task-ref>", plan_item_id="<plan-item-id>", state="skipped", summary="Operator skipped stuck item."))
PY
```

Expected daemon log lines during plan-driven dispatch include:

- `task_plan_dispatch`
- `plan_cursor_completed`
- `task_plan_remaining`
- `task_plan_stalled`

### Recipe: Start the root-side orchestrator daemon

**Who:** Orchestrator. **When:** You want the singleton root daemon to keep dispatching, intaking, refreshing, and verifying automatically.

```bash
cd /Users/daniel/Development/context-alt-text-monorepo
make orchestrator-daemon
make orchestrator-daemon BACKEND=codex-subagent
```

Notes:

- The orchestrator daemon is singleton-root scoped, not lane scoped.
- `BACKEND` is threaded for orchestrator-invoked execution surfaces so the operator-facing command line stays aligned with worker-daemon usage.
- In current daemon-6 scope, most orchestrator work still happens through MCP + Make orchestration, so `BACKEND` mainly keeps the CLI surface consistent while future orchestrator-invoked execution hooks are added.

Items that cannot be auto-routed (ambiguous or no file path) are listed as `unmatched` in the output. Route those manually with `make lane-dispatch`.

### Recipe: Start the root-side daemon

**Who:** Orchestrator. **When:** You want root to keep polling, dispatching, intaking, refreshing, and verifying automatically.

```bash
cd /Users/daniel/Development/context-alt-text-monorepo
make orchestrator-daemon TASK=<task-ref>
```

Use `make handoff-dispatch TASK=<task-ref>` instead when you only want to route open work to lanes without starting automated intake.

### Recipe: Preview lane commits before intake

**Who:** Orchestrator. **When:** A worker reports merge-ready.

```bash
# See what commits the lane has
make lane-commits TASK=<task-ref> LANE=backend-domain

# Dry-run intake to see the full plan
make lane-intake TASK=<task-ref> LANE=backend-domain DRY_RUN=1
```

The dry run shows:

- Latest worker report summary.
- Lane commits to cherry-pick.
- What would happen in the scratch worktree.

### Recipe: Intake (merge) a lane

**Who:** Orchestrator. **When:** Lane is verified and ready to merge.

```bash
make lane-intake TASK=<task-ref> LANE=backend-domain
```

What this does:

1. Verifies the orchestrator root is clean (no uncommitted changes).
2. Checks the latest lane report is merge-ready.
3. Lists the lane commits.
4. Creates a temporary scratch worktree from the current orchestrator HEAD.
5. Cherry-picks the lane commits into the scratch worktree.
6. Checks that all modified files are within the lane's allowed paths.
7. Runs the lane's test commands in the scratch worktree.
8. Fast-forward merges the scratch branch into the orchestrator branch.
9. Updates the lane status to `merged` in MCP.
10. Cleans up the scratch worktree.

If cherry-pick conflicts, intake aborts without touching the orchestrator root. Fix in the worker lane and resubmit.

If tests fail, intake aborts with an explicit message. Fix in the worker lane and resubmit.

To skip scratch-worktree tests (when deps cannot be installed in the scratch checkout):

```bash
make lane-intake TASK=<task-ref> LANE=backend-domain SKIP_TESTS=1
```

### Recipe: Refresh a lane after root changes

**Who:** Orchestrator or worker. **When:** The orchestrator branch has new commits the worker should pick up.

```bash
# From orchestrator root:
make lane-refresh TASK=<task-ref> LANE=backend-domain

# Or from the worker worktree (TASK and LANE auto-inferred):
make lane-refresh
```

What this does:

1. Verifies orchestrator workflow tooling is committed (refuses if dirty).
2. Auto-stashes any dirty lane state.
3. Fetches orchestrator branch into the lane.
4. If the lane has no unique commits: hard-reset to orchestrator HEAD.
5. If the lane has unique commits: rebase onto orchestrator HEAD.
6. If all lane commits are superseded (already integrated upstream): reset instead of rebase.
7. Auto-pops the stash to restore uncommitted work. If the pop conflicts, the stash is preserved and a warning is printed.

If rebase conflicts, the rebase is auto-aborted and the lane is left untouched. Resolve in the lane manually.

### Recipe: Reset a lane to a specific ref

**Who:** Orchestrator. **When:** The lane needs a hard reset (discards all lane work).

```bash
make lane-reset TASK=<task-ref> LANE=backend-domain REF=feature/6.0.2-retention-export
```

This is destructive. It runs `git reset --hard` and `git clean -fd` in the lane worktree.

### Recipe: Clean tooling drift from a lane

**Who:** Orchestrator. **When:** A lane has stale copied Makefiles or helper scripts.

```bash
make lane-clean TASK=<task-ref> LANE=backend-domain
```

Restores tooling files (`Makefile`, `scripts/worktree-lane`, templates) to their committed state without touching lane-owned product files.

### Recipe: Codex CLI setup

**Who:** Developer. **When:** First-time setup or on a new machine.

1. **Install globally**: `npm i -g @openai/codex@latest`
2. **Authenticate**: `codex login`
3. **Verify status**: `codex login status` (should exit 0)
4. **Configure profiles**: Edit `~/.codex/config.toml`:

   ```toml
   model = "gpt-5.4"

   [profile.mini]
   model = "gpt-5.4-mini"

   [profile.full]
   model = "gpt-5.4"
   ```

5. **Verify model access**: `codex exec -m gpt-5.4-mini "echo hello"`

### Recipe: Automated worker run (Codex CLI)

**Who:** Orchestrator. **When:** Running a worker non-interactively via `codex exec`.

```bash
make lane-run TASK=<task-ref> LANE=frontend
```

What this does:

1. Checks if the lane has actionable work (exits gracefully if not).
2. Generates a worker prompt from MCP lane activity.
3. Appends structured output instructions.
4. Runs `codex exec` in the lane worktree with an output schema.
5. On success: auto-records `make lane-commit` + `make lane-report` (merge-ready) or blocked report.
6. On failure: preserves the partial result file in `.task-state/exports/lane-run-failures/`.

To pass extra arguments to `codex exec`:

```bash
make lane-run TASK=<task-ref> LANE=frontend MODEL=o3
```

---

## Multi-Lane Merge Order

Merge lanes in dependency order to avoid cascading conflicts:

1. **backend-domain** (schema, domain services, infrastructure) -- no upstream dependencies
2. **backend-http** (API routers) -- depends on domain contracts from backend-domain
3. **wp-proxy** (PHP REST proxy) -- depends on backend HTTP contract
4. **frontend** (React UI) -- depends on wp-proxy contract

After merging each lane:

```bash
# Verify the merge
make check-all

# Refresh downstream lanes so they pick up upstream changes
make lane-refresh TASK=<task-ref> LANE=backend-http
```

---

## Fresh Codex Startup

In Terminal:

```bash
open -n -a Codex
```

In the new Codex window, point the workspace at the worker worktree path, then run:

```bash
pwd
git branch --show-current
make lane-inbox
```

The worker should not start coding before `make lane-inbox` shows the open orchestrator dispatch.
If root workflow tooling changed since the lane was opened, commit those root changes and then run `make lane-refresh` once before trusting the local lane commands.
Use `make lane-run` for non-interactive worker runs instead of trying to push a prompt into an already-running session.

---

## Troubleshooting

### Worker is on the wrong branch

```bash
cd /Users/daniel/Development/context-alt-text-monorepo
make lane-refresh TASK=<task-ref> LANE=<lane>
make lane-open TASK=<task-ref> LANE=<lane>
```

`make lane-open` now refuses to reuse an existing worktree if it is checked out on the wrong branch. Fix the branch drift first instead of letting work continue in the wrong lane.

### Lane-handoff refuses: "no unique lane commits"

The worker has not committed any lane-owned changes. Either:

- Run `make lane-commit` first (it stages only lane-owned paths).
- If the lane is genuinely blocked with no code changes, use `make lane-report STATUS=blocked MERGE_READY=0 SUMMARY="..." MESSAGE="..."` instead.

### Lane-commit refuses: "out-of-scope changes"

The worker edited files outside the lane's owned paths. Options:

- `git checkout -- <out-of-scope-file>` to discard unwanted changes.
- `git stash push -- <out-of-scope-file>` to save for later.
- Then retry `make lane-commit`.

### Lane-intake conflicts in scratch worktree

The orchestrator branch diverged from the lane. Fix:

```bash
make lane-refresh TASK=<task-ref> LANE=<lane>   # rebase lane onto current root
make lane-handoff                                # re-submit from worker worktree
make lane-intake TASK=<task-ref> LANE=<lane>     # retry from orchestrator root
```

### Lane-intake test failure

Tests failed in the scratch worktree. The orchestrator root was not modified. Fix the failing tests in the worker lane, then:

```bash
make lane-handoff                                # from worker worktree
make lane-intake TASK=<task-ref> LANE=<lane>     # from orchestrator root
```

If the test failure is environmental (missing deps in scratch checkout):

```bash
make lane-intake TASK=<task-ref> LANE=<lane> SKIP_TESTS=1
```

### Lane-refresh rebase conflicts

```bash
# The lane-refresh auto-aborted the rebase. Resolve manually:
cd "$(make lane-path TASK=<task-ref> LANE=<lane>)"
git rebase FETCH_HEAD
# ... resolve conflicts ...
git rebase --continue
```

### Orchestrator root is dirty before intake

```bash
git stash push -u -m "pre-intake stash"
make lane-intake TASK=<task-ref> LANE=<lane>
git stash pop
```

### MCP state seems stale

```bash
make state                    # full MCP state dump
make dashboard                # quick overview
make task                     # regenerate CURRENT_TASK.md
```

### Lane-refresh refuses: "orchestrator workflow tooling has uncommitted changes"

Commit the tooling changes on the orchestrator branch first, then retry:

```bash
git add Makefile scripts/worktree-lane docs/agentic/templates/
git commit -m "update pipeline tooling"
make lane-refresh TASK=<task-ref> LANE=<lane>
```
