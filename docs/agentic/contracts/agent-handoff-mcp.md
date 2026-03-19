# Agent Handoff MCP Contract

## Purpose

`agent-handoff-mcp` is the portable MCP server for agent coordination state. It owns task state, review findings, exports/imports, dashboard summaries, and handoff close checks. It does not expose repo-intel tools.

## Runtime Configuration

CLI args take precedence over env vars.

Supported config inputs:

- `--workspace-root` or `AGENT_HANDOFF_WORKSPACE_ROOT`
- `--state-dir` or `AGENT_HANDOFF_STATE_DIR`
- `--current-task-path` or `AGENT_HANDOFF_CURRENT_TASK_PATH`
- `--exports-dir` or `AGENT_HANDOFF_EXPORTS_DIR`
- `AGENT_HANDOFF_DEFAULT_AGENT`
- `AGENT_HANDOFF_DEFAULT_BRANCH`
- `AGENT_HANDOFF_DEFAULT_COMMIT_SHA`

Default workspace-owned state:

- DB: `.task-state/handoff.db`
- exports: `.task-state/exports/`
- generated markdown: `CURRENT_TASK.md`

## MCP Tool Surface

Task state:

- `set_handoff_state`
- `get_handoff_state`
- `upsert_worktree_lane`
- `list_worktree_lanes`
- `get_lane_activity`
- `record_decision`
- `update_next_actions`
- `record_test_result`
- `report_blocker`
- `record_worker_report`
- `list_worker_reports`
- `record_lane_message`
- `record_lane_brief`
- `update_lane_message`
- `list_lane_messages`
- `list_lane_briefs`

Review findings:

- `record_review_finding`
- `update_review_finding`
- `reopen_review_finding`
- `list_review_findings`
- `get_review_finding`
- `get_review_findings_summary`
- `reconcile_review_findings`

Lifecycle:

- `orchestrator_start`
- `orchestrator_status`
- `orchestrator_stop`
- `orchestrator_pause`
- `orchestrator_resume`
- `worker_start`
- `worker_status`
- `worker_stop`
- `worker_resume`
- `worker_start_all`
- `run_structured_turn`
- `handoff_close_check`
- `generate_current_task_md`
- `export_handoff_state`
- `import_handoff_state`
- `archive_task_state`
- `get_handoff_dashboard`

## Request Shape Notes

- Write tools target the active task only.
- To write against a different task, switch active state first with `set_handoff_state(...)`.
- `set_handoff_state` requires `expected_revision` for updates.
- The shared actor shape may include `lane_id` in addition to `agent`, `branch`, and `commit_sha`. When present, lane-aware write tools persist it on decisions, tests, blockers, actions, and review findings.
- `record_review_finding` accepts optional `details={ line_start?, line_end?, fix? }`.
- `update_review_finding` accepts exactly one of `finding_id` or `finding_db_id`.
- `update_review_finding` requires `resolution_notes` for `wontfix` and `deferred`.
- `update_review_finding` requires `reopen_reason` when changing a non-open finding back to `open`.
- `import_handoff_state(mode="replace_task")` rejects destructive clears unless `allow_destructive_clear=true`.
- `upsert_worktree_lane` is the canonical way to register a delegated worker lane with `lane_id`, `worktree_path`, `branch`, ownership, and status.
- `record_worker_report` stores a structured worker handback for one lane: summary, changed files, test commands, blockers, and merge-readiness.
- `record_lane_message` / `update_lane_message` model orchestrator-to-worker and worker-to-orchestrator communication without relying on direct session chat.
- `record_lane_brief` / `list_lane_briefs` are the structured-brief helpers built on top of `lane_messages`; they persist an open `orchestrator_to_worker` message with a `brief:<reason>` subject plus a compact JSON payload (`source_lane`, `reason`, `summary`, optional `required_actions`, optional `artifacts`).
- `get_lane_activity` is the lane-scoped query surface for decisions, tests, blockers, actions, findings, worker reports, and lane messages.
- `worker_status` should be treated as an inspection tool, not a boolean health check. Use `running`, `worker_state`, `attention_required`, and `state_summary` together. Current durable worker states include `idle`, `waiting_for_orchestrator`, `handoff_failed`, `paused`, and `stopped`.
- `worker_start` and `worker_start_all` accept `session_mode`. Use `fresh_turn` for the default one-turn-per-session isolation, or `shared_lane` to reuse context only within the same lane worker session when repeated continuity is worth the extra retained context.
- `worker_start_all` is dependency-aware when a manifest merge order exists. Lanes whose upstream dependencies still have unresolved dispatched work are returned as clean `skipped` results with `reason="unresolved_upstream_dependencies"` and a `blocked_by` lane list instead of being started prematurely.
- `orchestrator_start` / `single-cycle` support `worker_start_mode`. Use `mcp` for the default MCP-first worker pool behavior, or `manual` when the host should keep worker startup in shell space.
- A recorded `handoff_failed` worker state means the implementation/review turn already completed and the saved result must be retried or inspected without silently rerunning the same lane assignment.

## CLI Fallback

Primary entrypoints:

- `agent-handoff-mcp --workspace-root <repo> serve-stdio`
- `agent-handoff-mcp --workspace-root <repo> serve-http`
- `agent-handoff-mcp --workspace-root <repo> doctor`

Fallback subcommands:

- `state`
- `dashboard`
- `set`
- `decision`
- `action`
- `lane-upsert`
- `lane-list`
- `lane-activity`
- `blocker`
- `test`
- `lane-report`
- `lane-report-list`
- `lane-message`
- `lane-message-update`
- `lane-message-list`
- `review-record`
- `review-update`
- `review-list`
- `review-summary`
- `handoff-close-check`
- `task`
- `export`
- `import`
- `archive`

## HTTP Transport

`serve-http` starts the same MCP server over FastMCP's `streamable-http` transport instead of stdio.

Current runtime behavior:

- host: `127.0.0.1`
- port: `8000`
- endpoint path: `/mcp`
- log level: FastMCP default unless overridden by its settings

Example:

```bash
agent-handoff-mcp --workspace-root /path/to/repo serve-http
```

Operational notes:

- This package's CLI does **not** currently expose explicit `--host`, `--port`, or `--path` flags.
- The current command relies on FastMCP's default HTTP settings (`host=127.0.0.1`, `port=8000`, `streamable_http_path=/mcp`).
- Prefer `serve-stdio` for editor adapters and local agent sessions unless you explicitly need HTTP transport.

## Client Adapter Notes

- VS Code workspace adapter can keep a stable registration name even if the packaged binary name changes.
- Codex, Claude, Gemini, and other harnesses should register thin adapters that launch the same binary with harness-specific transport wiring.
- Registration-name changes can cascade into tool-prefix and instruction updates. Treat those as explicit adapter work, not implicit package renames.

## Multi-Worktree Coordination Notes

Use the new lane tools when a task is intentionally split across Git worktrees or parallel agent sessions.

- Task-aware worktree automation should be driven by a checked-in manifest at `config/lane-orchestration/<task-ref>.json`. That manifest is the source of truth for lane ids, branch names, worktree paths, owned paths, test commands, merge order, and dispatch routing hints.
- Manifest creation must be generic, not task-specific. Use `make lane-manifest-init TASK=<task-ref> LANE_IDS='lane-a lane-b' [TASK_PLAN=docs/tasks/...md]` to scaffold a new manifest for any task, then fill in lane ownership and verification details.
- The orchestrator should register one `worktree_lane` per worker branch/worktree.
- Workers should write with `actor.lane_id` so decisions, tests, blockers, actions, and findings can be queried by lane.
- Workers should hand back one or more `worker_reports` as merge checkpoints instead of relying on free-form chat only.
- `lane_messages` provide an explicit mailbox for orchestrator briefs, worker questions, and acknowledgements when clients cannot directly message one another.
- Structured dependency briefs should ride on `lane_messages` rather than a parallel storage surface. The recommended convention is an open `orchestrator_to_worker` message whose subject starts with `brief:` and whose body stays compact enough to be injected into the next lane prompt without replaying full transcripts.
- Emit downstream briefs only for merge-ready source-lane reports with no unresolved blockers. If the source lane is blocked, non-merge-ready, or ambiguous, escalate through orchestrator guidance instead of replaying partial dependency state into downstream lanes.
- Lane prompt rendering is lane-scoped by default. `scripts/mcp/lane_prompt.py` should prioritize open assignment items plus compact `brief:` messages, cap those sections to a fixed budget, and omit deeper lane history unless an explicit inspection/escalation flag such as `--include-lane-history` is requested.
- Lane prompt renders should also expose a compact "Prompt Budget" summary so operators can see how much of the worker prompt came from assignment, dependency briefs, runtime guidance, lane history, and optional task-wide escalation before deciding to widen context further.
- Broader task-wide context is also opt-in. Use `--include-global-context` only when lane-local state and structured briefs are insufficient; default worker prompts should continue to rehydrate from the lane inbox, lane runtime guidance, unresolved briefs, and the latest lane report.
- Export/import and archive flows now include lane records, worker reports, and lane messages so delegated task history survives workspace migration.
- Lane verification should be recorded into MCP with `record_test_result`, not left as terminal-only output, so `get_lane_activity` remains the durable verification ledger for each lane.

Shared-state rule for sibling worktrees:

- Keep `workspace-root` pointed at the current worktree so branch/worktree provenance stays accurate.
- Point `state-dir`, `current-task-path`, and `exports-dir` at the orchestrator root so all lanes share one handoff database and generated `CURRENT_TASK.md`.
- The helper script [`scripts/worktree-lane`](../../scripts/worktree-lane) encodes this pattern and should be preferred over ad-hoc CLI invocation.
- Orchestrator entrypoints such as `make lane-open` should fail fast if an existing worktree has drifted onto the wrong branch; silently reusing the wrong checkout risks misdirected commits and violates the lane-safety contract.
- Worker daemons should be started from the worker worktree root against the shared orchestrator state, for example `make worker-daemon TASK=<task-ref> LANE=<lane>` from the lane checkout. If launched from an app subdirectory, callers should either use a forwarding app Makefile that supports `worker-daemon` or invoke the top-level Makefile explicitly with `make -C "$(git rev-parse --show-toplevel)" worker-daemon ...`.
- In MCP-capable hosts, the preferred worker lifecycle surface is now `worker_start`, `worker_status`, `worker_stop`, `worker_resume`, and `worker_start_all`. Shell `make worker-daemon*` commands remain the fallback/wrapper layer for non-MCP environments and manual operator workflows.
- Worker daemon execution should expose live progress. Operators should expect terminal lifecycle markers plus periodic `exec_heartbeat` output while `codex exec` is still running, with the full JSONL trail under `logs/worker-daemon/worker-<lane>.jsonl`.
- Worker state is also persisted outside the JSONL stream at `.task-state/worker-<lane>.status.json` so MCP status queries can explain why a lane is idle, waiting, paused, stopped, or blocked on final handoff without requiring log inspection.
- Continuous orchestrator polling is a separate concern from dispatch-only routing. `make orchestrator-daemon` is allowed to intake merge-ready lanes, while `make handoff-dispatch` is the safe root command when the operator wants to fan out open work without starting merge automation.
- Backend Python lane verification should not depend on interactive shell activation. Prefer `PYENV_VERSION=description-service ...` in lane test commands over `pyenv activate description-service`, because `pyenv activate` requires shell init hooks that may not exist in daemon subprocesses.
