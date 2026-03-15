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
- `update_lane_message`
- `list_lane_messages`

Review findings:

- `record_review_finding`
- `update_review_finding`
- `reopen_review_finding`
- `list_review_findings`
- `get_review_finding`
- `get_review_findings_summary`
- `reconcile_review_findings`

Lifecycle:

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
- `get_lane_activity` is the lane-scoped query surface for decisions, tests, blockers, actions, findings, worker reports, and lane messages.

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
- The orchestrator should register one `worktree_lane` per worker branch/worktree.
- Workers should write with `actor.lane_id` so decisions, tests, blockers, actions, and findings can be queried by lane.
- Workers should hand back one or more `worker_reports` as merge checkpoints instead of relying on free-form chat only.
- `lane_messages` provide an explicit mailbox for orchestrator briefs, worker questions, and acknowledgements when clients cannot directly message one another.
- Export/import and archive flows now include lane records, worker reports, and lane messages so delegated task history survives workspace migration.
- Lane verification should be recorded into MCP with `record_test_result`, not left as terminal-only output, so `get_lane_activity` remains the durable verification ledger for each lane.

Shared-state rule for sibling worktrees:

- Keep `workspace-root` pointed at the current worktree so branch/worktree provenance stays accurate.
- Point `state-dir`, `current-task-path`, and `exports-dir` at the orchestrator root so all lanes share one handoff database and generated `CURRENT_TASK.md`.
- The helper script [`scripts/worktree-lane`](../../scripts/worktree-lane) encodes this pattern and should be preferred over ad-hoc CLI invocation.
- Orchestrator entrypoints such as `make lane-open` should fail fast if an existing worktree has drifted onto the wrong branch; silently reusing the wrong checkout risks misdirected commits and violates the lane-safety contract.
