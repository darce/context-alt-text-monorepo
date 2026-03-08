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
- `record_decision`
- `update_next_actions`
- `record_test_result`
- `report_blocker`

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
- `record_review_finding` accepts optional `details={ line_start?, line_end?, fix? }`.
- `update_review_finding` accepts exactly one of `finding_id` or `finding_db_id`.
- `update_review_finding` requires `resolution_notes` for `wontfix` and `deferred`.
- `update_review_finding` requires `reopen_reason` when changing a non-open finding back to `open`.
- `import_handoff_state(mode="replace_task")` rejects destructive clears unless `allow_destructive_clear=true`.

## CLI Fallback

Primary entrypoints:

- `agent-handoff-mcp --workspace-root <repo> serve-stdio`
- `agent-handoff-mcp --workspace-root <repo> doctor`

Fallback subcommands:

- `state`
- `dashboard`
- `set`
- `decision`
- `action`
- `blocker`
- `test`
- `review-record`
- `review-update`
- `review-list`
- `review-summary`
- `handoff-close-check`
- `task`
- `export`
- `import`
- `archive`

## Client Adapter Notes

- VS Code workspace adapter can keep a stable registration name even if the packaged binary name changes.
- Codex, Claude, Gemini, and other harnesses should register thin adapters that launch the same binary with harness-specific transport wiring.
- Registration-name changes can cascade into tool-prefix and instruction updates. Treat those as explicit adapter work, not implicit package renames.
