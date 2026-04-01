---
boundary_owner: agentic-tooling
---

# Agent Handoff MCP Contract

## Purpose

`agent-handoff-mcp` is the portable MCP server for agent coordination state. After the E12-5/E12-6 split it exposes **27 tools** in its full profile (**16 core**, **11 extended**) for task state, review findings, artifacts, export/import, and handoff close checks. Orchestration, daemon lifecycle, lane management, and turn metrics are served by [`agent-orchestrator-mcp`](agent-orchestrator-mcp.md).

## Runtime Configuration

CLI args take precedence over env vars.

Supported config inputs:

- `--workspace-root` or `AGENT_HANDOFF_WORKSPACE_ROOT`
- `--state-dir` or `AGENT_HANDOFF_STATE_DIR`
- `--current-task-path` or `AGENT_HANDOFF_CURRENT_TASK_PATH`
- `--exports-dir` or `AGENT_HANDOFF_EXPORTS_DIR`
- `--tool-profile` or `AGENT_HANDOFF_TOOL_PROFILE` — `core` (default) or `full`; core exposes 16 daily-use ledger tools, full exposes all 27
- `AGENT_HANDOFF_DEFAULT_AGENT`
- `AGENT_HANDOFF_DEFAULT_BRANCH`
- `AGENT_HANDOFF_DEFAULT_COMMIT_SHA`

Default workspace-owned state:

- DB: `.task-state/handoff.db`
- artifact DB: `.task-state/mcp-artifacts.db`
- exports: `.task-state/exports/`
- generated markdown: `CURRENT_TASK.md`

`CURRENT_TASK.md` now renders a compact cross-task dashboard header above the active task detail section. The dashboard is derived from the same aggregated task-state query used by `get_handoff_state(view="dashboard")`, so switching tasks preserves visibility into other active or recently active tasks without creating extra files.

For extracted-consumer setups, replace the local `uv tool install ./packages/agent-handoff-mcp` step with the private git+ssh source for `darce/mcp-agent-handoff`; the installed binary shape stays the same.

Runtime bootstrap:

```bash
cd /Users/daniel/Development/context-alt-text-monorepo

# Core ledger server
uv tool install ./packages/agent-handoff-mcp

# Orchestration server (daemons, workers, lanes, metrics)
uv tool install ./packages/agent-orchestrator-mcp

# Codex subagent bridge for BACKEND=codex-subagent
python3 -m pip install -e packages/codex-subagent-bridge

# Validate runtime wiring, writable state dirs, and FTS5 support
agent-handoff-mcp --workspace-root "$(pwd)" doctor
agent-orchestrator-mcp --workspace-root "$(pwd)" doctor
```

Notes:

- `doctor` hard-fails when the local SQLite build lacks FTS5; artifact indexing depends on it.
- When running from repo source instead of an installed binary, use `PYTHONPATH="packages/agent-handoff-mcp/src:packages/codex-subagent-bridge/src" python3 -m agent_handoff_mcp ...`.
- `dashboard-live` does not require optional UI packages. `dashboard-tui` uses Textual when installed, then `rich.live`, then plain text.

## MCP Tool Surface

Surface classes:

- `action`: mutates state, filesystem state, lane runtime, or daemon runtime. Do not retry blindly.
- `query`: read-only inspection of canonical state. Safe to retry when transport/runtime is healthy.
- `generator`: derives a report, search result, reconciliation result, or rendered artifact from current state. Usually safe to retry unless the tool also writes a file by default.

| Tool                           | Surface class | Idempotent | Notes                                                                                                                                                                                                                                         |
| ------------------------------ | ------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `set_handoff_state`            | action        | no         | Updates active task state with optimistic revision guard.                                                                                                                                                                                     |
| `get_handoff_state`            | query         | yes        | Canonical task-state read. Pass `view="dashboard"` for a cross-task aggregation (replaces the former `get_handoff_dashboard`). For task views, `sections` accepts a comma-separated subset of task-state sections; `active` and `limits` remain always included. `detail` accepts `full` (default) or `summary` to truncate long rationale and verification fields without changing the default payload shape. |
| `record_decision`              | action        | no         | Appends decision ledger state.                                                                                                                                                                                                                |
| `update_next_actions`          | action        | no         | Creates or mutates action rows.                                                                                                                                                                                                               |
| `list_next_actions`            | query         | yes        | Lists canonical action rows.                                                                                                                                                                                                                  |
| `record_test_result`           | action        | no         | Appends verification evidence.                                                                                                                                                                                                                |
| `report_blocker`               | action        | no         | Adds, resolves, or reopens blockers.                                                                                                                                                                                                          |
| `record_review_finding`        | action        | no         | Creates or reopens review findings.                                                                                                                                                                                                           |
| `batch_record_review_findings` | action        | no         | Records or reopens multiple findings atomically (single transaction, single `CURRENT_TASK.md` flush). Max 100 items. Returns per-item `action`/`reopened` results. Prefer over `record_review_finding` when logging ≥ 3 findings in one pass. |
| `update_review_finding`        | action        | no         | Changes finding status or resolution metadata. Pass `reopen_reason` for non-open → open transitions (replaces the former `reopen_review_finding`).                                                                                            |
| `list_review_findings`         | query         | yes        | Lists findings with filters. Pass `finding_id` or `finding_db_id` for global single-finding lookup (returns the row regardless of owning task; pass `task_ref` to scope). `detail` accepts `full` (default) or `summary`; summary mode truncates long finding body fields while preserving the existing filters and default full-detail behavior. |
| `record_review_run`            | action        | no         | Records a completed review pass in the `review_runs` ledger. Requires unique `review_run_id`, `session`, `subject_path`. `verdict` and `verdict_decision` are optional at record time.                                                        |
| `list_review_runs`             | query         | yes        | Lists `review_runs` ledger entries. Filter by `task_ref`, `subject_path`, `review_mode`, or `verdict`. Paginated, ordered by recency.                                                                                                         |
| `get_review_coverage`          | query         | yes        | Coverage summary for a task or artifact: run count, latest verdict, recent run ids, open findings by severity, reopened count. Provide `task_ref`, `subject_path`, or both.                                                                   |
| `handoff_close_check`          | generator     | yes        | Derived readiness verdict from current state.                                                                                                                                                                                                 |
| `generate_current_task_md`     | generator     | no         | Renders deterministic markdown and writes `CURRENT_TASK.md` by default. Output includes a cross-task dashboard header plus the existing active-task detail section.                                                                            |
| `export_handoff_state`         | generator     | yes        | Produces portable snapshot output.                                                                                                                                                                                                            |
| `import_handoff_state`         | action        | no         | Imports snapshot into local DB; destructive in replace modes.                                                                                                                                                                                 |
| `archive_task_state`           | action        | no         | Moves active state into archive storage.                                                                                                                                                                                                      |
| `load_session`                 | query         | yes        | **Compound**: calls `get_handoff_state` + `list_review_findings(status="open")` in one invocation. Use at session start to minimise round trips. `sections` is passed through only to the nested `state` payload from `get_handoff_state`; `detail` is passed through to both nested state and findings. Defaults preserve the pre-parameterization full payload behavior. |
| `close_slice`                  | action        | no         | **Compound**: calls `record_decision` + `set_handoff_state` + `generate_current_task_md` in one invocation. Use at slice completion to write evidence atomically.                                                                             |
| `audit_decision_ids`           | query         | yes        | Audits recent decision IDs for grammar conformance. Returns canonical/malformed/freeform classifications per ID.                                                                                                                              |
| `record_artifact`              | action        | no         | Indexes artifact content into sidecar FTS store.                                                                                                                                                                                              |
| `search_artifacts`             | generator     | yes        | Returns ranked snippets from indexed artifacts. Empty `queries` returns a source listing (replaces the former `list_artifact_sources`).                                                                                                       |
| `get_artifact`                 | query         | yes        | Reads stored artifact record; pass `include_terms=true` for term derivation (replaces `get_artifact_source` and `get_artifact_terms`).                                                                                                        |
| `purge_artifacts`              | action        | no         | Deletes stored artifact rows and FTS chunks.                                                                                                                                                                                                  |
| `search_handoff`               | generator     | yes        | Returns ranked snippets over handoff FTS tables.                                                                                                                                                                                              |

Cross-task and review-summary tools (`switch_task`, `get_latest_slice_review_packet`, `get_review_findings_summary`, `reconcile_review_findings`) are registered on `agent-orchestrator-mcp`. See [`agent-orchestrator-mcp.md`](agent-orchestrator-mcp.md).

Retry guidance:

- Retry `query` and pure `generator` surfaces when the failure is transport-level, timeout-based, or due to a transient read lock.
- Do not auto-retry `action` surfaces unless the caller can prove the operation is safe to repeat.
- Treat `generate_current_task_md` and `close_slice` as write-affecting surfaces even though they derive output from current state.

## MCP Troubleshooting Ladder

### 1. Startup Failure

Symptoms:

- `agent-handoff-mcp` binary not found
- import or launcher failure
- wrong `--workspace-root` / `--state-dir`
- missing `.task-state` or unwritable `CURRENT_TASK.md`

Checks:

```bash
agent-handoff-mcp --workspace-root /path/to/repo doctor
python3 -m agent_handoff_mcp --workspace-root /path/to/repo doctor
ls -ld /path/to/repo/.task-state /path/to/repo/.task-state/exports
```

Recovery:

- fix the executable or `PYTHONPATH`
- point the client at the real workspace root
- create or repair the workspace-owned state directories

### 2. Capability Discovery Failure

Symptoms:

- tool appears in docs but not in the client
- wrapper or skill references stale tool names
- adapter launches the wrong server entrypoint

Checks:

```python
from agent_handoff_mcp.api import TOOL_DESCRIPTIONS
print(len(TOOL_DESCRIPTIONS))
print(sorted(TOOL_DESCRIPTIONS))
```

Recovery:

- treat `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` as the live source of truth
- update stale docs, skills, or wrappers in the same slice
- prefer minimal valid payloads when a write bounces on signature drift

### 3. Runtime Execution Failure

Symptoms:

- optimistic revision mismatch
- SQLite lock or FTS5 errors

Checks:

```bash
agent-handoff-mcp --workspace-root /path/to/repo doctor
agent-handoff-mcp --workspace-root /path/to/repo state
```

Recovery:

- refresh the expected revision before retrying write operations
- treat FTS5 errors as environment/runtime issues first, not search-contract bugs

### 4. Evidence-Write Failure

Symptoms:

- a decision, finding, or test write is described in prose but not persisted
- `CURRENT_TASK.md` is out of sync with handoff state
- review close checks fail because fresh verification evidence is missing

Checks:

```bash
agent-handoff-mcp --workspace-root /path/to/repo doctor
agent-handoff-mcp --workspace-root /path/to/repo state
agent-handoff-mcp --workspace-root /path/to/repo review-list
```

Recovery:

- reissue the write with the live signature and minimal valid payload
- record verification with `record_test_result` instead of prose-only rationale
- regenerate `CURRENT_TASK.md` after decision writes when the workflow requires it

## Structured Handoff Search (`search_handoff`)

`search_handoff` provides BM25/FTS5 full-text search over the four canonical handoff record
tables (decisions, review findings, blockers, and next actions) stored in `handoff.db`.

### FTS5 Shadow Tables

Four FTS5 virtual tables are maintained in `handoff.db` alongside the canonical tables:

| FTS table       | Source table      | Indexed body                                     | Status column |
| --------------- | ----------------- | ------------------------------------------------ | ------------- |
| `decisions_fts` | `decisions`       | `decision \|\| ' ' \|\| COALESCE(rationale, '')` | no            |
| `findings_fts`  | `review_findings` | `description \|\| ' ' \|\| COALESCE(fix, '')`    | yes           |
| `blockers_fts`  | `blockers`        | `description`                                    | yes           |
| `actions_fts`   | `next_actions`    | `action`                                         | yes           |

All tables use `tokenize='porter unicode61'`, `record_id UNINDEXED`, `task_ref UNINDEXED`, and
`lane_id UNINDEXED` so that scope filters (`task_ref`, `lane_id`) are fast equality lookups
without touching FTS ranking.

### Trigger Maintenance

Twelve SQL triggers (INSERT / UPDATE / DELETE for each source table) keep FTS tables in sync
automatically. UPDATE triggers follow the DELETE-then-INSERT pattern to prevent stale rows. All
triggers use `CREATE TRIGGER IF NOT EXISTS` so they are schema-idempotent.

`_ensure_handoff_fts(conn)` is called on every `_get_db_connection()` call. It:

1. Probes FTS5 availability (CREATE/DROP `_fts5_handoff_probe`); silently returns on failure.
2. Creates the four FTS5 virtual tables if not already present.
3. Creates the twelve triggers if not already present.
4. Runs `_backfill_handoff_fts(conn)`: for each source/FTS pair, if source has rows but FTS is
   empty, bulk-inserts all source rows into the FTS table (handles cold-start upgrades).

FTS5 unavailability degrades silently so existing handoff operations are never blocked. Call
`agent-handoff-mcp doctor` to verify FTS5 is available.

### Tool Signature

```python
search_handoff(
    queries: list[str],
    task_ref: str | None = None,
    lane_id: str | None = None,
    record_types: list[str] | None = None,  # subset of ["decision", "finding", "blocker", "action"]
    limit: int = 20,                         # max 200
) -> str:
```

- **queries**: One or more search terms. Multiple terms are OR-joined. Multi-word terms are
  automatically phrase-quoted (`"term with spaces"`) for precise adjacency matching.
- **record_types**: Defaults to all four types when omitted.
- **limit**: Clamped to [1, 200]. Results across all searched types are merged and re-ranked.

### Response Shape

```json
{
  "ok": true,
  "results": [
    {
      "record_type": "decision",
      "record_id": 42,
      "task_ref": "my-task",
      "lane_id": "backend-domain",
      "status": null,
      "snippet": "...exponential backoff retry policy..."
    }
  ],
  "total": 1,
  "query": "\"exponential backoff\"",
  "record_types_searched": ["action", "blocker", "decision", "finding"]
}
```

- `status` is `null` for decisions (no status column); `open` / `fixed` / etc. for others.
- `snippet` uses FTS5 `snippet()` with a 12-token window; result is compact, not full body.
- Results are sorted by BM25 rank (best match first); ties break by insertion order.

### CLI Subcommand

```bash
agent-handoff-mcp --workspace-root <repo> handoff-search \
    --query "retry policy" \
    --query "circuit breaker" \
    --task-ref my-task \
    --lane-id backend-domain \
    --record-types decision finding \
    --limit 10
```

`--query` is repeatable; multiple `--query` flags are OR-joined.

### Error Cases

- `queries` is `None` or all strings are blank: returns `{"ok": false, "error": "..."}`.
- Any `record_types` entry is not in `["decision", "finding", "blocker", "action"]`: returns error.
- FTS5 tables not initialized (FTS5 unavailable): returns `{"ok": false, "error": "..."}`. Run
  `doctor` to diagnose.

## `get_handoff_state` Dashboard View Response Shape

When called with `view="dashboard"`, `get_handoff_state` returns:

```json
{
  "ok": true,
  "view": "dashboard",
  "active": { "task_ref": "E12-11", "status": "in_progress", "..." : "..." },
  "tasks": [
    {
      "task_ref": "E12-11",
      "status": "in_progress",
      "last_activity": "2026-03-30 23:50:30",
      "open_blockers": 0,
      "pending_actions": 0,
      "open_findings": 6,
      "archived_at": null
    }
  ]
}
```

`tasks[]` field reference:

| Field | Type | Notes |
| --- | --- | --- |
| `task_ref` | `string` | Task reference identifier |
| `status` | `string` | For the active task: live `handoff_state.status`. For archived tasks: recovered from the archived snapshot's `active.status` when available, else `"archived"`. For non-active, non-archived tasks: `"active"` as fallback. |
| `last_activity` | `string \| null` | ISO datetime of the most recent ledger entry across decisions, blockers, next_actions, verified_tests, review_findings, worktree_lanes, worker_reports, and lane_messages. Also includes `handoff_state.updated_at` for the currently active task as a baseline anchor (see behavioral note below). |
| `open_blockers` | `integer` | Count of blockers with `status = 'open'` |
| `pending_actions` | `integer` | Count of next_actions with `status = 'pending'` |
| `open_findings` | `integer` | Count of review_findings with `status = 'open'` |
| `archived_at` | `string \| null` | ISO datetime of archival; `null` for non-archived tasks |

**Behavioral note on `last_activity`:** `_collect_dashboard_rows` includes `handoff_state.updated_at` (the `id = 1` row, i.e. the active task) as an activity source. This gives the currently active task a recent-activity anchor even when it has no separate ledger entries. The prior `_get_handoff_dashboard_view` implementation did not include this source; the difference is intentional.

## Request Shape Notes

- Most write tools accept optional `task_ref`. When omitted, they target the active task as a fallback.
- In concurrent or multi-task workflows, pass `task_ref` explicitly on writes instead of relying on ambient active-state routing.
- Live MCP tool signatures are authoritative over examples, templates, or prior-session memory. Prefer the minimal valid payload for write operations unless a richer payload is required by the current signature.
- If a write call fails validation, treat it as signature drift. Retry once with the minimal payload accepted by the live signature, then update the stale contract/rule/template in the same slice so the bounce does not recur.
- Slice-completion decisions must use the prefixed decision grammar `<author_tag>_slice_complete_<work_ref>_<slug>` for new writes. The legacy `slice_complete_<short_label>` format is grandfathered for historical rows and recognized by all read paths (close-check, slice-review packet derivation). New writes should use the prefixed form. Both formats require a structured rationale with the four headings `## Changes`, `## Verification`, `## Schema / Contract Changes`, and `## Open Threads`.
- `record_decision` requires a `session` string as its first positional argument (MCP path) or `--session` flag (CLI path). Use a stable, human-readable identifier such as `"<agent>-<task-slug>"` or `"<agent>-<short-description>"`. The field is NOT auto-populated from context; omitting it causes a `Missing required argument` validation error.
- `record_decision(...)` rejects slice-complete writes at write time when the rationale is missing those headings or any section is empty. This is enforced before the row is inserted.
- Historical decision rows that predate the prefixed naming scheme are grandfathered. MCP read paths (close-check, slice-review packet, handoff search) recognize both formats. Do not plan retroactive renames of historical rows.
- The structured rationale is mandatory even for docs-only slices. Use `- none.` for empty sections rather than omitting headings.
- Handoff consumers should treat prose-only completion decisions as malformed process output that must be corrected before the slice is considered fully handed off.
- To switch between tasks, use `switch_task(task_ref)` on `agent-orchestrator-mcp`. It auto-archives the outgoing task (full snapshot) and activates the target, restoring the objective from its archive when not provided. Idempotent if the target is already active.
- For in-place updates to the _current_ task (status, objective change, focus update), use `set_handoff_state(...)` directly.
- `set_handoff_state` requires `expected_revision` for updates. Accepts optional `focus` for mutable per-slice working context. `objective` is optional on updates (preserved when omitted). `focus` is preserved when omitted on updates; pass an empty string to clear it explicitly.
- The shared actor shape may include `model`, `model_label`, `reasoning_level`, and `lane_id` in addition to `agent`, `branch`, and `commit_sha`. Only decisions persist the granular model fields today; other write surfaces continue to persist `agent` plus git provenance.
- `build_write_actor(agent=None, model=None, model_label=None, reasoning_level=None, branch=None, commit_sha=None, lane_id=None) -> WriteActor` is the public helper for constructing that normalized actor payload before passing it into write tools.
- `build_write_actor` derives the canonical `agent` display identity from model provenance when available: `"{model_label} {reasoning_level}"` when both are present, `model_label` when only the label is known, and the caller-provided `agent` only as a legacy fallback.
- Known model labels are normalized for common backends (`claude-opus-4-0520` -> `Opus 4.6`, `claude-sonnet-4-20250514` -> `Sonnet 4`); unknown models pass through unchanged.
- Decision rows now persist nullable `model`, `model_label`, and `reasoning_level` columns alongside `agent`. Treat the turn-metrics ledger on `agent-orchestrator-mcp` as the canonical source for token consumption; decision rows carry model provenance only and do not duplicate per-turn token columns.
- `record_decision`, `record_test_result`, `report_blocker`, and `update_next_actions` now accept optional `task_ref`, matching the existing cross-task targeting pattern.
- Write responses for `record_decision`, `record_test_result`, `report_blocker`, and `update_next_actions` echo the resolved `task_ref`. Treat that field as the authoritative write target in multi-agent flows.
- `record_review_finding` accepts optional `details={ line_start?, line_end?, fix? }`.
- `record_review_finding` also accepts optional `review_mode` with values `branch`, `release_audit`, or `planning`.
- `record_review_finding` accepts `task_ref="__repo__"` to record a repo-scoped finding that is not owned by any one implementation task. Task-scoped listing queries exclude `__repo__` rows unless repo scope is explicitly included.
- `batch_record_review_findings` accepts `session`, `findings` (list of `BatchFindingItem`), optional `actor`, and optional `task_ref`. Each `BatchFindingItem` requires `finding_id`, `severity`, `file_path`, and `description`; `review_mode` and `details` are optional. Maximum 100 items per call; larger batches return `ok: false` without writing. All items are pre-validated (severity, review_mode, required fields) before the transaction opens — a single invalid item rejects the entire batch. Returns `{ ok, task_ref, written, results: [{ finding_id, action, reopened? }] }`. Use this tool instead of repeated `record_review_finding` calls when logging 3 or more findings in a single review pass.
- `get_handoff_state` accepts optional `sections` and `detail` on task views. `sections` is a comma-separated subset of task-state sections; invalid names are silently dropped, and if no valid names remain the response contains only identity data (`active` + `limits`, no data sections). The reserved token `sections="identity"` explicitly requests the same identity-only shape; when present it takes precedence over any other section names. `active` and `limits` are always included and are not selectable or suppressible. Pass `sections=None` (the default) to receive the full task payload. `detail="summary"` truncates long rationale, command, result, and finding text fields while keeping the default `detail="full"` response backward-compatible.
- `update_review_finding` accepts exactly one of `finding_id` or `finding_db_id`.
- `update_review_finding` requires `resolution_notes` for `wontfix` and `deferred`.
- `update_review_finding` requires `reopen_reason` when changing a non-open finding back to `open`.
- `update_review_finding`: when `task_ref` is omitted and `finding_id` or `finding_db_id` is provided, the lookup is global. If exactly one row matches, the update is applied to that row regardless of active task. If multiple rows share the same `finding_id`, an explicit ambiguity error listing the candidate scopes is returned.
- `list_review_findings`: when `finding_id` or `finding_db_id` is provided and `task_ref` is omitted, the lookup is global — the active-task fallback is skipped. If more than one row shares the same `finding_id` across different task scopes, an explicit ambiguity error is returned. To scope the lookup to a specific task, pass `task_ref` explicitly.
- `finding_id` naming convention: prefix with the owning task-ref or review scope to minimize cross-scope collisions (e.g., `E12-3-001`, `REVIEW-COVERAGE-E12-3-001`). Global uniqueness is not schema-enforced; ambiguity errors serve as the collision safety net. Repo-scoped findings should use the `__repo__` task-ref prefix or the review subject path as the prefix.
- `list_review_findings` accepts optional `review_mode`; `branch` includes rows where `review_mode IS NULL` for backward compatibility.
- `list_review_findings` accepts optional `detail="full"|"summary"`. Summary mode truncates long `description`, `fix`, `resolution_notes`, and `verification_evidence` fields while preserving the same filters, counts, and lookup rules.
- `load_session` accepts optional `sections` and `detail`. `sections` is passed only to the nested `state` payload returned by `get_handoff_state`; `detail` is passed to both `get_handoff_state` and `list_review_findings(status="open")` so the combined response can be trimmed without changing default compatibility behavior.
- `record_review_run` requires `review_run_id` (must be globally unique in the ledger), `session`, and `subject_path`. `subject_kind` defaults to `task_plan`; valid values are `task_plan`, `epic`, `branch`, `adr`, `roadmap`, `other`. `review_mode` defaults to `planning`; valid values are `branch`, `release_audit`, `planning`. `verdict` is optional; valid values are `pass`, `pass_with_findings`, `fail`, `conditional_pass`. `verdict_decision` is optional and should hold the stable decision string from `record_decision` (not the integer id). `task_ref` is optional and links the run to a task scope.
- `list_review_runs` is unscoped by default (returns all runs). Pass `task_ref` to scope to a task, `subject_path` to scope to an artifact, `review_mode` to filter by review type, or `verdict` to filter by outcome. Max 100 per page.
- `get_review_coverage` requires at least one of `task_ref` or `subject_path`. When `task_ref` is given, finding counts come from the `task_ref` column on `review_findings`. When only `subject_path` is given, finding counts are derived via the `review_run_id` link from matching runs. Returns: `run_count`, `latest_review_run_id`, `latest_verdict`, `recent_run_ids` (last 5), `open_findings_by_severity` (dict of high/medium/low counts), `reopened_findings_count`.
- `get_review_coverage` with `task_ref="REVIEW-COVERAGE"` is a supported backward-compatible query pattern; the returned counts will be zero until repo-scoped findings are migrated from the pseudo-task bucket.
- Use `record_review_run` at the end of each planning or branch review to record the verdict and link it to the reviewed artifact. Then pass `review_run_id` on each `record_review_finding` call to link findings to their run.
- When `current_commit_sha` is provided, `handoff_close_check` also verifies that at least one structured `slice_complete_*` decision exists for that commit. Treat missing current-commit slice summaries as a close/review gate failure, including for docs-only slices.
- `record_test_result.result` is a concise verification-summary field, not a full log sink. Keep short proof lines such as `55 passed in 7.02s`, `diff-check clean`, or `REVIEW READY: READY`; store longer output in artifacts/files instead of the `verified_tests` table.
- `import_handoff_state(mode="replace_task")` rejects destructive clears unless `allow_destructive_clear=true`.
- `close_slice` requires a `session` string (same as `record_decision`). Pass `task_ref` explicitly in multi-task flows. `focus` updates the active-task working context after the decision is recorded.

## CLI Fallback

Primary entrypoints:

- `agent-handoff-mcp --workspace-root <repo> serve-stdio`
- `agent-handoff-mcp --workspace-root <repo> serve-http`
- `agent-handoff-mcp --workspace-root <repo> doctor`

Fallback subcommands:

- `state`
- `dashboard`
- `set`
- `decision` — requires `--session` and `--decision`; `--rationale` is optional but mandatory for `slice_complete_*` decisions:

  ```bash
  agent-handoff-mcp --workspace-root <repo> decision \
    --session "<agent>-<task-slug>" \
    --decision "cdx_slice_complete_<work_ref>_<slug>" \
    --rationale "## Changes\n..."
  ```

- `action`
- `blocker`
- `test`
- `review-record`
- `review-update`
- `review-list`
- `review-run-record`
- `review-run-list`
- `review-coverage`
- `handoff-close-check`
- `task`
- `export`
- `import`
- `archive`
- `audit-decisions`
- `artifact-record`
- `artifact-search`
- `artifact-get`
- `artifact-purge`
- `handoff-search`

Orchestration subcommands (`orchestrator-start`, `worker-start`, `dispatch`, `orchestrator-cycle`, `worker-events`, `list-backends`, `metrics`, etc.) are served exclusively by `agent-orchestrator-mcp`. See [`agent-orchestrator-mcp.md`](agent-orchestrator-mcp.md).

**CLI surface note:** `agent-handoff-mcp` CLI is ledger-only. It exposes `serve-stdio`, `serve-http`, `doctor`, `dashboard`, and the 27 ledger MCP tools as CLI wrappers, plus two CLI-only artifact variants (`artifact-list`, `artifact-terms`). All orchestration and lane-management commands are exclusively on `agent-orchestrator-mcp`.

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

## Portable Hook Semantics

The orchestration tooling implements a set of named automation events with stable expected behavior regardless of the host agent. Each semantic has a trigger condition, allowed side effects, a required durable output, and an operator visibility path.

Host-specific integrations (e.g. Codex skill wrappers, VS Code callbacks) trigger these semantics, but the semantics themselves and their durable outputs live in this contract and the repo tooling layer. A hook semantic must never depend on a single host product's lifecycle model.

---

### `after_review_findings_recorded`

**Trigger:** The worker-daemon review pipeline (`worker_daemon.py`) completes a review turn that produces one or more new findings. This hook fires in the daemon review path only; it does not fire on every individual `record_review_finding` MCP tool call.

**Side effects allowed:** ACE reflection detection. The worker daemon scans the batch of new findings for `[sr-NNN]` or `[rg-NNN]` rule references and appends pending evidence entries to `.task-state/ace_reflect_log.jsonl`.

**Required durable output:** An entry in `.task-state/ace_reflect_log.jsonl` naming the finding ID, the matched rule reference, and the support/contradiction classification. The entry is written only when findings in the batch contain rule references. Direct MCP finding writes do not trigger this hook.

**Operator visibility:** Inspect `.task-state/ace_reflect_log.jsonl` directly, or run `make ace-reflect TASK=<task-ref> --dry-run` to preview pending counter updates. Run `make ace-reflect TASK=<task-ref>` to apply pending updates to `instructions.md` evidence counters.

---

### `before_close_check`

**Trigger:** `handoff_close_check(task_ref=...)` is invoked.

**Side effects allowed:** None. `handoff_close_check` is a pure `generator` surface and must not mutate state.

**Required durable output:** A structured readiness verdict (JSON envelope) including open blockers, open high-severity findings, unresolved test failures, and missing slice decisions. The verdict must be inspectable without re-running the tool. Individual failure reasons must reference MCP record IDs (finding IDs, blocker IDs) so the operator can navigate to the source.

**Operator visibility:** The verdict is returned synchronously in the tool response. No additional state query is required to understand what blocked the close check.

---

### `after_worker_turn`

**Trigger:** A worker execution turn completes, regardless of whether review passed or was skipped due to a scope violation.

**Side effects allowed:** Observability logging. The worker daemon appends a structured JSONL event to `logs/worker-daemon/worker-<lane>.jsonl` recording token usage, scope result, context pressure, and turn outcome.

**Required durable output:** A JSONL event with at minimum: `event_type`, `task_ref`, `lane_id`, `turn_timestamp`, `scope_result` (`pass` or `violation`), and `turn_outcome` (`review_submitted` or `skipped`). Token fields (`input_tokens`, `output_tokens`, `total_tokens`) are included when the backend provides exact usage.

**Operator visibility:** `worker_event_history(task_ref, lane_id, limit=20)` via MCP, or `make worker-daemon-tail` from the worker worktree.

---

### `after_task_switch`

**Trigger:** `switch_task(task_ref=...)` completes (archives the prior task, activates the new task).

**Side effects allowed:** `CURRENT_TASK.md` regeneration. `generate_current_task_md` runs for the new active task so the human-readable mirror reflects the switch immediately.

**Required durable output:** Updated `CURRENT_TASK.md` with the dashboard header plus the new task's latest decision, objective, and open findings in the detail section. If regeneration fails, the failure must be surfaced in the `switch_task` response, not silently swallowed.

**Operator visibility:** `CURRENT_TASK.md` must be current after `switch_task` returns. If the file appears stale, run `generate_current_task_md(task_ref=<new-task>)` explicitly.

---

### `before_review_prompt_build`

**Trigger:** The orchestrator daemon or `review_runner.py` prepares a review prompt for a completed worker turn.

**Side effects allowed:** Slice-packet composition. ACE guidance, slice decisions, the review checklist, and a scope diff are assembled into the prompt envelope. Composition metadata (section sizes, attribution flags) should be captured for the turn-metrics ledger when available.

**Required durable output:** A scope-violation precondition check runs before prompt assembly. If scope validation failed, prompt build is skipped entirely and a `scope_violation` JSONL event is emitted instead of a review prompt. No review prompt is produced for a scope-violating turn.

**Operator visibility:** Prompt composition metadata (section label, character count, attribution flags) is included in `worker_event_history` output when the worker daemon captures it. The `scope_violation` event is inspectable via `worker_event_history` without re-running the review cycle.

---

### Hook Adapter Guidance

A host-specific integration that triggers a hook semantic must:

1. Invoke the tooling mechanism that produces the required durable output (write to DB, append to JSONL, regenerate a file).
2. Not substitute informal prose or chat messages for the required durable output.
3. Surface failures explicitly rather than silently continuing as if the hook ran.
4. Not assume a specific agent product manages the hook lifecycle; the trigger condition and durable output must be achievable from any MCP-capable runtime or shell.
