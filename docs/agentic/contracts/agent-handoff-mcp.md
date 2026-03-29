---
boundary_owner: agentic-tooling
---

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
- artifact DB: `.task-state/mcp-artifacts.db`
- exports: `.task-state/exports/`
- generated markdown: `CURRENT_TASK.md`

Runtime bootstrap:

```bash
cd /Users/daniel/Development/context-alt-text-monorepo

# Packaged MCP server
uv tool install ./packages/agent-handoff-mcp

# Codex subagent bridge for BACKEND=codex-subagent
python3 -m pip install -e packages/codex-subagent-bridge

# Optional monitoring UI packages for dashboard-tui / rich.live fallback
PYENV_VERSION=description-service python3 -m pip install -e "apps/prototype-description-service[dashboard,dev]"

# Validate runtime wiring, writable state dirs, and FTS5 support
agent-handoff-mcp --workspace-root "$(pwd)" doctor
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

| Tool                             | Surface class | Idempotent | Notes                                                                                                                                                                              |
| -------------------------------- | ------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `set_handoff_state`              | action        | no         | Updates active task state with optimistic revision guard.                                                                                                                          |
| `get_handoff_state`              | query         | yes        | Canonical task-state read.                                                                                                                                                         |
| `upsert_worktree_lane`           | action        | no         | Updates lane metadata and regenerates `CURRENT_TASK.md`.                                                                                                                           |
| `close_worktree_lane`            | action        | no         | Transitions lane status to merged or closed.                                                                                                                                       |
| `list_worktree_lanes`            | query         | yes        | Lists registered lane rows.                                                                                                                                                        |
| `get_lane_activity`              | generator     | yes        | Aggregated lane summary across decisions, tests, blockers, and messages; supports `format="archival"` for compact retention-friendly summaries.                                    |
| `list_next_actions`              | query         | yes        | Lists canonical action rows.                                                                                                                                                       |
| `record_decision`                | action        | no         | Appends decision ledger state.                                                                                                                                                     |
| `update_next_actions`            | action        | no         | Creates or mutates action rows.                                                                                                                                                    |
| `record_test_result`             | action        | no         | Appends verification evidence.                                                                                                                                                     |
| `report_blocker`                 | action        | no         | Adds, resolves, or reopens blockers.                                                                                                                                               |
| `record_worker_report`           | action        | no         | Appends structured worker handback state.                                                                                                                                          |
| `list_worker_reports`            | query         | yes        | Lists worker reports.                                                                                                                                                              |
| `record_lane_message`            | action        | no         | Appends lane message state.                                                                                                                                                        |
| `record_lane_brief`              | action        | no         | Creates a structured brief on top of lane messages.                                                                                                                                |
| `update_lane_message`            | action        | no         | Mutates lane-message status.                                                                                                                                                       |
| `list_lane_messages`             | query         | yes        | Lists lane messages.                                                                                                                                                               |
| `list_lane_briefs`               | query         | yes        | Lists structured lane briefs.                                                                                                                                                      |
| `record_turn_metric`             | action        | no         | Records one durable turn-metrics row, including exact-vs-estimated usage metadata, prompt-budget fields, and structured attribution payloads.                                     |
| `list_turn_metrics`              | query         | yes        | Lists durable turn-metrics rows for the active or requested task, optionally filtered by lane, backend, model, or phase.                                                        |
| `get_turn_metrics_summary`       | generator     | yes        | Aggregates turn-metrics rows into exact-vs-estimate coverage, pressure counts, and token totals by lane/backend/model.                                                           |
| `get_plan_cursor`                | query         | yes        | Reads one durable plan cursor.                                                                                                                                                     |
| `list_plan_cursors`              | query         | yes        | Lists plan cursor rows.                                                                                                                                                            |
| `upsert_plan_cursor`             | action        | no         | Mutates plan cursor state; can enforce clean-slice gate.                                                                                                                           |
| `record_review_finding`          | action        | no         | Creates or reopens review findings.                                                                                                                                                |
| `update_review_finding`          | action        | no         | Changes finding status or resolution metadata.                                                                                                                                     |
| `reopen_review_finding`          | action        | no         | Reopens closed finding with reason.                                                                                                                                                |
| `list_review_findings`           | query         | yes        | Lists findings with filters.                                                                                                                                                       |
| `get_review_finding`             | query         | yes        | Reads one finding by stable or DB id.                                                                                                                                              |
| `get_review_findings_summary`    | generator     | yes        | Returns aggregated counts and top open findings.                                                                                                                                   |
| `reconcile_review_findings`      | generator     | yes        | Compares open findings with current files; `apply=true` turns it into a mutating action and should be treated as a controlled repair step.                                         |
| `handoff_close_check`            | generator     | yes        | Derived readiness verdict from current state.                                                                                                                                      |
| `generate_current_task_md`       | generator     | no         | Renders deterministic markdown and writes `CURRENT_TASK.md` by default.                                                                                                            |
| `export_handoff_state`           | generator     | yes        | Produces portable snapshot output.                                                                                                                                                 |
| `import_handoff_state`           | action        | no         | Imports snapshot into local DB; destructive in replace modes.                                                                                                                      |
| `archive_task_state`             | action        | no         | Moves active state into archive storage.                                                                                                                                           |
| `switch_task`                    | action        | no         | Archives outgoing task and activates target task.                                                                                                                                  |
| `get_handoff_dashboard`          | generator     | yes        | Derived dashboard view across lanes, findings, and blockers.                                                                                                                       |
| `orchestrator_start`             | action        | no         | Starts shared orchestrator daemon.                                                                                                                                                 |
| `orchestrator_status`            | query         | yes        | Inspects orchestrator runtime state.                                                                                                                                               |
| `orchestrator_stop`              | action        | no         | Stops orchestrator daemon.                                                                                                                                                         |
| `orchestrator_pause`             | action        | no         | Creates pause sentinel.                                                                                                                                                            |
| `orchestrator_resume`            | action        | no         | Clears pause sentinel.                                                                                                                                                             |
| `worker_start`                   | action        | no         | Starts one lane worker daemon.                                                                                                                                                     |
| `worker_status`                  | query         | yes        | Inspects worker runtime state and health metadata.                                                                                                                                 |
| `worker_event_history`           | query         | yes        | Reads worker JSONL event history. Event-name filters should use the canonical enum-backed worker event vocabulary (for example `cycle_start`, `exec_complete`, `review_complete`). |
| `worker_stop`                    | action        | no         | Stops worker daemon.                                                                                                                                                               |
| `worker_resume`                  | action        | no         | Resumes stopped worker daemon.                                                                                                                                                     |
| `worker_start_all`               | action        | no         | Starts multiple worker daemons.                                                                                                                                                    |
| `run_structured_turn`            | action        | no         | Executes a synchronous backend turn; may spend tokens or mutate external runtime state.                                                                                            |
| `orchestrator_single_cycle`      | action        | no         | Runs one full dispatch/poll/intake/verify cycle.                                                                                                                                   |
| `dispatch_lane_work`             | action        | no         | Mutates lane dispatch parameters for future cycles.                                                                                                                                |
| `list_available_backends`        | query         | yes        | Reads registered backend catalog.                                                                                                                                                  |
| `record_artifact`                | action        | no         | Indexes artifact content into sidecar FTS store.                                                                                                                                   |
| `search_artifacts`               | generator     | yes        | Returns ranked snippets from indexed artifacts.                                                                                                                                    |
| `get_artifact_source`            | query         | yes        | Reads stored artifact record.                                                                                                                                                      |
| `get_artifact_terms`             | generator     | yes        | Derives suggested query terms from indexed artifact chunks.                                                                                                                        |
| `list_artifact_sources`          | query         | yes        | Lists indexed artifact metadata.                                                                                                                                                   |
| `purge_artifacts`                | action        | no         | Deletes stored artifact rows and FTS chunks.                                                                                                                                       |
| `search_handoff`                 | generator     | yes        | Returns ranked snippets over handoff FTS tables.                                                                                                                                   |
| `get_latest_slice_review_packet` | query         | yes        | Resolves the latest `slice_complete_*` decision into a deterministic review packet.                                                                                                |
| `get_metrics_summary`            | generator     | yes        | Derived metrics snapshot across lanes, retrieval, context pressure, process-health signals, and handoff-memory health.                                                             |

### `get_metrics_summary` Snapshot Shape

`get_metrics_summary` is additive: existing top-level sections remain stable and new sections are appended rather than replacing prior keys.

Top-level snapshot fields:

- `timestamp`: ISO-8601 generation time.
- `task_ref`: task the snapshot was generated for.
- `token_burn`: aggregate token spend and converged-cycle efficiency.
- `context_pressure`: pressure-level ratios from worker events.
- `fts5_retrieval`: handoff/artifact index counts.
- `lane_health`: scope-violation, exhaustion, and convergence signals.
- `process_health`: repo-process quality signals derived from handoff state and git history.
- `handoff_memory`: hot-state and artifact-footprint signals derived from current MCP state.
- `planning_drift`: plan-cursor completion vs dispatch drift within the evaluation window.
- `stale_artifact_rate`: artifact-source staleness counts and ratio from `mcp-artifacts.db`.
- `archive_rate`: repo-wide task archive cadence derived from `task_archives`.
- `ctx7_adoption`: decision-level `ctx7 library id:` reuse and adoption counts.
- `phase_timing`: exec/review timing aggregates.
- `ace_documentation`: strategy-bullet and pruning-candidate counts from instruction files.

`process_health` currently includes:

- `reopened_finding_rate`: `{ value, reopened_findings, total_findings }`
- `finding_resolution_velocity_hours`: `{ median_hours, resolved_findings }`
- `handoff_decision_completeness`: `{ value, structured_decisions, total_decisions }`
- `contract_co_change_signal`: `{ data_available, recent_commits_scanned, boundary_touching_commits, boundary_commits_with_contract_co_change, value }`

`handoff_memory` currently includes:

- `hot_state_size_bytes`: serialized byte size of the `get_handoff_state`-shaped hot-state payload for the active task
- `total_decisions`: total decisions stored for the task
- `total_findings`: total review findings stored for the task
- `artifact_source_count`: indexed artifact-source count from `mcp-artifacts.db`

Example `get_lane_activity(format="archival")` response:

```json
{
  "ok": true,
  "task_ref": "agentic-development-process-hardening-epic",
  "format": "archival",
  "lane": {
    "lane_id": "backend",
    "status": "active"
  },
  "summary": {
    "decisions": {
      "count": 3,
      "latest_rationale_excerpt": "Aligned the retention contract with the new archive cadence metrics..."
    },
    "findings": {
      "counts_by_status": {
        "open": 1,
        "fixed": 4,
        "wontfix": 0,
        "deferred": 0
      }
    },
    "reports": {
      "count": 2,
      "latest_merge_ready": true
    },
    "messages": {
      "counts_by_direction": {
        "orchestrator_to_worker": 2,
        "worker_to_orchestrator": 3
      },
      "counts_by_status": {
        "open": 0,
        "acknowledged": 1,
        "closed": 4
      }
    },
    "tests": {
      "total": 5,
      "passed": 5,
      "pass_rate": 1.0
    }
  }
}
```

`planning_drift` currently includes:

- `window_days`: lookback window used for evaluation
- `total`: total `plan_cursors` rows updated inside the window
- `terminal`: rows in terminal states (`completed`, `skipped`) inside the window
- `drift`: `1 - terminal / total`, or `null` when no rows exist in the window

`stale_artifact_rate` currently includes:

- `window_days`: staleness threshold for artifact freshness
- `total`: total indexed artifact sources
- `stale_count`: artifact sources with `updated_at` older than the threshold
- `stale_rate`: `stale_count / total`, with `0.0` for an empty artifact index

`archive_rate` currently includes:

- `window_days`: lookback window used for the in-window archive count
- `total_archives`: total archived tasks recorded in `task_archives`
- `in_window`: archived tasks whose `archived_at` falls inside the window
- `mean_interval_hours`: average hours between archive events across the repo, or `null` when fewer than two archives exist

`ctx7_adoption` currently includes:

- `decisions_with_ctx7`: number of task decisions containing at least one `ctx7 library id:`
- `unique_library_ids`: distinct library ids referenced by those decisions
- `reuse_ratio`: total library-id mentions divided by distinct library ids, or `null` when none exist
- `library_ids`: sorted distinct library ids referenced in task decisions

### Deferred Instrumentation

The current handoff schema does not support the following metrics without new structured telemetry. These remain explicit instrumentation gaps, not inferred heuristics:

- `runtime_parity` coverage: requires structured classification of verification rows beyond raw command text
- `performance_evidence` coverage: requires typed linkage between verification records and latency / queue-health benchmark evidence
- `resolved_from_hot_state` ratio: requires agent-side retrieval telemetry indicating whether work was resolved from hot state, archival summary, or targeted search
- `ctx7` token-cost reduction: requires prompt/tooling telemetry outside the current handoff DB schema

Consumers should treat unknown keys as forward-compatible additions and should not require every section to have `data_available=true`; unavailable sections return explicit sentinel values rather than disappearing.

### Turn Metrics Surfaces

`turn_metrics` is the canonical per-turn ledger for token and prompt-budget telemetry. It exists so consumers can distinguish exact provider usage from preflight estimates without parsing decision prose or worker JSONL logs.

Common stored fields:

- Identity: `task_ref`, `lane_id`, `session`, `cycle`, `phase`, `backend`, `model`, `thread_id`, `turn_id`
- Observed usage: `input_tokens`, `output_tokens`, `cached_input_tokens`, `reasoning_output_tokens`, `total_tokens`
- Prompt-budget context: `model_context_window`, `prompt_tokens`, `prompt_chars`, `prompt_token_source`, `utilization_ratio`, `domain_signal_ratio`, `pressure_level`
- Attribution payloads: `attribution`, `section_sizes`, `raw_usage`
- Current attribution fields include additive booleans such as `used_ace_guidance`, `used_artifact_context`, `used_slice_packet`, `used_recent_lane_history`, `used_global_context`, and `used_ctx7`, plus `ctx7_query_count` when the caller/runtime explicitly reports it.
- Usage exactness: `usage_source` with additive values `observed`, `tokenizer_estimate`, or `char_estimate`

Exactness rules:

- `usage_source="observed"` means the token totals came from a provider/backend response, not a local heuristic.
- `prompt_token_source="observed"` means preflight tokenization used an explicitly supported exact tokenizer path for that backend/model combination.
- `prompt_token_source="tokenizer_estimate"` means prompt tokens came from a tokenizer-backed estimate on a non-exact model path.
- `prompt_token_source="char_estimate"` means prompt tokens came from the fallback character heuristic and must not be treated as exact.

`get_turn_metrics_summary` returns:

- `total_turns`
- `usage_source_counts`
- `prompt_token_source_counts`
- `pressure_level_counts`
- `total_tokens`
- `prompt_tokens`
- `by_lane_total_tokens`
- `by_backend_model_total_tokens`

Retry guidance:

- Retry `query` and pure `generator` surfaces when the failure is transport-level, timeout-based, or due to a transient read lock.
- Do not auto-retry `action` surfaces unless the caller can prove the operation is safe to repeat.
- Treat `generate_current_task_md` and `reconcile_review_findings(apply=true)` as write-affecting surfaces even though they derive output from current state.

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
- point the client at the real orchestrator root
- create or repair the workspace-owned state directories

### 2. Capability Discovery Failure

Symptoms:

- tool appears in docs but not in the client
- wrapper or skill references stale tool names
- adapter launches the wrong server entrypoint

Checks:

```bash
python3 - <<'PY'
from agent_handoff_mcp.api import TOOL_DESCRIPTIONS
print(len(TOOL_DESCRIPTIONS))
print(sorted(TOOL_DESCRIPTIONS))
PY
```

Recovery:

- treat `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` as the live source of truth
- update stale docs, skills, or wrappers in the same slice
- prefer minimal valid payloads when a write bounces on signature drift

### 3. Runtime Execution Failure

Symptoms:

- optimistic revision mismatch
- SQLite lock or FTS5 errors
- daemon start/stop/resume fails
- lane-intake or lane worker actions leave stale runtime state

Checks:

```bash
agent-handoff-mcp --workspace-root /path/to/repo doctor
agent-handoff-mcp --workspace-root /path/to/repo orchestrator-status
agent-handoff-mcp --workspace-root /path/to/repo worker-status --lane-id <lane>
```

Recovery:

- refresh the expected revision before retrying write operations
- treat FTS5 errors as environment/runtime issues first, not search-contract bugs
- use the daemon lifecycle skill or Make targets before manual lock cleanup

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

| FTS table       | Source table      | Indexed body  | Status column |
| --------------- | ----------------- | ------------- | ------------- | --- | --- | ------------------------ | --- |
| `decisions_fts` | `decisions`       | `decision     |               | ' ' |     | COALESCE(rationale, '')` | no  |
| `findings_fts`  | `review_findings` | `description  |               | ' ' |     | COALESCE(fix, '')`       | yes |
| `blockers_fts`  | `blockers`        | `description` | yes           |
| `actions_fts`   | `next_actions`    | `action`      | yes           |

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

## Request Shape Notes

- Most write tools accept optional `task_ref`. When omitted, they target the active task as a fallback.
- In concurrent or multi-task workflows, pass `task_ref` explicitly on writes instead of relying on `switch_task(...)` plus ambient active-state routing.
- Live MCP tool signatures are authoritative over examples, templates, or prior-session memory. Prefer the minimal valid payload for write operations unless a richer payload is required by the current signature.
- If a write call fails validation, treat it as signature drift. Retry once with the minimal payload accepted by the live signature, then update the stale contract/rule/template in the same slice so the bounce does not recur.
- Slice-completion decisions must use `decision="slice_complete_<short_label>"` and a structured rationale with the four headings `## Changes`, `## Verification`, `## Schema / Contract Changes`, and `## Open Threads`.
- `record_decision(...)` rejects `slice_complete_*` writes at write time when the rationale is missing those headings or any section is empty. This is enforced before the row is inserted.
- The structured rationale is mandatory even for docs-only slices. Use `- none.` for empty sections rather than omitting headings.
- Handoff consumers should treat prose-only completion decisions as malformed process output that must be corrected before the slice is considered fully handed off.
- To switch between tasks, use `switch_task(task_ref)`. It auto-archives the outgoing task (full snapshot) and activates the target, restoring the objective from its archive when not provided. Idempotent if the target is already active.
- For in-place updates to the _current_ task (status, objective change), use `set_handoff_state(...)` directly.
- `set_handoff_state` requires `expected_revision` for updates.
- The shared actor shape may include `model`, `model_label`, `reasoning_level`, and `lane_id` in addition to `agent`, `branch`, and `commit_sha`. Only decisions persist the granular model fields today; other write surfaces continue to persist `agent` plus git provenance.
- `build_write_actor(agent=None, model=None, model_label=None, reasoning_level=None, branch=None, commit_sha=None, lane_id=None) -> WriteActor` is the public helper for constructing that normalized actor payload before passing it into write tools.
- `build_write_actor` derives the canonical `agent` display identity from model provenance when available: `"{model_label} {reasoning_level}"` when both are present, `model_label` when only the label is known, and the caller-provided `agent` only as a legacy fallback.
- Known model labels are normalized for common backends (`claude-opus-4-0520` -> `Opus 4.6`, `claude-sonnet-4-20250514` -> `Sonnet 4`); unknown models pass through unchanged.
- Decision rows now persist nullable `model`, `model_label`, and `reasoning_level` columns alongside `agent`. Treat the turn-metrics ledger as the canonical source for token consumption; decision rows carry model provenance only and do not duplicate per-turn token columns.
- `record_decision`, `record_test_result`, `report_blocker`, and `update_next_actions` now accept optional `task_ref`, matching the existing cross-task targeting pattern already used by the review-finding and lane-message/report surfaces.
- Write responses for `record_decision`, `record_test_result`, `report_blocker`, and `update_next_actions` echo the resolved `task_ref`. Treat that field as the authoritative write target in multi-agent flows.
- `record_review_finding` accepts optional `details={ line_start?, line_end?, fix? }`.
- `record_review_finding` also accepts optional `review_mode` with values `branch` or `release_audit`.
- `update_review_finding` accepts exactly one of `finding_id` or `finding_db_id`.
- `update_review_finding` requires `resolution_notes` for `wontfix` and `deferred`.
- `update_review_finding` requires `reopen_reason` when changing a non-open finding back to `open`.
- `list_review_findings` accepts optional `review_mode`; `branch` includes rows where `review_mode IS NULL` for backward compatibility.
- `get_review_findings_summary` accepts the same optional `review_mode` filter and scopes counts/top lists to that mode.
- `handoff_close_check` accepts optional `require_fresh_tests` and `current_commit_sha`. When the flag is enabled, at least one `verified_tests` row must exist for the current commit or the close check fails with a structured stale-test error.
- When `current_commit_sha` is provided, `handoff_close_check` also verifies that at least one structured `slice_complete_*` decision exists for that commit. Treat missing current-commit slice summaries as a close/review gate failure, including for docs-only slices.
- `record_test_result.result` is a concise verification-summary field, not a full log sink. Keep short proof lines such as `55 passed in 7.02s`, `diff-check clean`, or `REVIEW READY: READY`; store longer output in artifacts/files instead of the `verified_tests` table.
- `upsert_plan_cursor` accepts optional `require_clean_slice`. When enabled, the update fails unless there are no open HIGH findings in the relevant lane/task scope and at least one recent `verified_tests` row exists since the cursor's prior update time.
- `import_handoff_state(mode="replace_task")` rejects destructive clears unless `allow_destructive_clear=true`.
- `upsert_worktree_lane` is the canonical way to register a delegated worker lane with `lane_id`, `worktree_path`, `branch`, ownership, and status.
- `record_worker_report` stores a structured worker handback for one lane: summary, changed files, test commands, blockers, and merge-readiness.
- `record_lane_message` / `update_lane_message` model orchestrator-to-worker and worker-to-orchestrator communication without relying on direct session chat.
- `record_lane_message` accepts artifact refs in its payload; the CLI fallback exposes this as repeated `--artifact <source-id>` flags.
- `record_lane_brief` / `list_lane_briefs` are the structured-brief helpers built on top of `lane_messages`; they persist an open `orchestrator_to_worker` message with a `brief:<reason>` subject plus a compact JSON payload (`source_lane`, `reason`, `summary`, optional `required_actions`, optional `artifacts`).
- `get_lane_activity` is the lane-scoped query surface for decisions, tests, blockers, actions, findings, worker reports, and lane messages.
- `get_lane_activity(format="full")` preserves the existing detailed payload.
- `get_lane_activity(format="archival")` returns a compact `summary` object with decision count plus latest rationale excerpt, finding counts by status, latest worker merge-ready state, message counts by direction/status, and verified-test totals with pass rate.
- `get_latest_slice_review_packet` resolves the latest `slice_complete_*` decision into a deterministic review packet using MCP state instead of current branch diff. The packet currently includes `slice_label`, `decision_id`, `decision`, `session`, `lane_id`, `plan_item_id`, `changed_files`, `test_commands`, `contract_files`, `review_kind`, `review_guide_path`, `scope_source="slice_packet"`, and a rationale excerpt.
- `get_latest_slice_review_packet(review_kind="planning")` only matches docs-only slices (`changed_files` all under `docs/`). Mixed doc-plus-code slices resolve to `branch`.
- `worker_status` should be treated as an inspection tool, not a boolean health check. Use `running`, `worker_state`, `attention_required`, and `state_summary` together. Current durable worker states include `idle`, `waiting_for_orchestrator`, `handoff_failed`, `paused`, and `stopped`.
- `worker_status` also exposes hardening signals: `exhaustion_streak` (consecutive non-converged cycles), `cumulative_tokens` (session token spend), `health` (`healthy` / `degraded` / `unhealthy`), and a `context_utilization` sub-dict with `utilization_ratio`, `domain_signal_ratio`, and `pressure` (`normal` / `elevated` / `high`). Use these alongside `attention_required` to assess lane health.
- `worker_status` and dashboard surfaces should be treated as the authoritative runtime view for model size, requested/effective reasoning effort, token burn, and context pressure. Use them before redispatching or promoting a lane.
- `worker_stop` now performs authoritative lock cleanup. After stop, the lock file is deleted and a `worker_stopped` JSONL event is emitted. `daemon_status()` reports `lock.held: false` consistently; no contradictory state artifacts remain.
- `worker_start` and `worker_start_all` accept `session_mode`. Use `fresh_turn` for the default one-turn-per-session isolation, or `shared_lane` to reuse context only within the same lane worker session when repeated continuity is worth the extra retained context.
- `worker_start_all` is dependency-aware when a manifest merge order exists. Lanes whose upstream dependencies still have unresolved dispatched work are returned as clean `skipped` results with `reason="unresolved_upstream_dependencies"` and a `blocked_by` lane list instead of being started prematurely.
- `orchestrator_start` / `single-cycle` support `worker_start_mode`. Use `mcp` for the default MCP-first worker pool behavior, or `manual` when the host should keep worker startup in shell space.
- A recorded `handoff_failed` worker state means the implementation/review turn already completed and the saved result must be retried or inspected without silently rerunning the same lane assignment.
- For task-plan-driven orchestration, treat the checked-in lane manifest as the executable version of the task plan. `dispatch_lane_work` controls backend/model/reasoning effort; `record_lane_message` and `record_lane_brief` carry the human-readable slice assignment and dependency context.

### Scope Enforcement and Effective Owned Paths

Scope enforcement is a runtime gate in `lane_exec.py`. After worker execution completes, the worktree diff is validated against `effective_owned_paths`. If violations are found, review is skipped and a `scope_violation` event is emitted.

- The orchestrator can narrow scope for a specific dispatch by embedding `effective_owned_paths` as a JSON-encoded string in the `artifacts` list of the dispatch lane message: `artifacts=[json.dumps({"type": "owned_paths_override", "paths": [...]})]`.
- The `artifacts` field accepts `list[str]`; the normalizer's `_coerce_string_list()` preserves strings but silently drops non-string items, so the override dict must be serialized before dispatch.
- `lane_exec.py` reads the override from the most recent `orchestrator_to_worker` message via `list_lane_messages`, iterating `artifacts` and attempting `json.loads()` on each string to find the entry with `type == "owned_paths_override"`. Non-parseable strings are skipped.

### Lane Health Scoring

The orchestrator daemon computes per-lane health via `_check_lane_health()` based on exhaustion streak, scope violation history, token burn, and context pressure.

- Health enum: `healthy` / `degraded` / `unhealthy`.
- The daemon skips auto-start for lanes with `exhaustion_streak >= 2` and emits `lane_unhealthy`. Unhealthy lanes require an explicit orchestrator decision (e.g., `promote_model`, `split_lane`, `close_lane`, `fresh_worktree`).
- Health transitions emit `lane_health_changed` events.

### Worker Daemon JSONL Events

The worker daemon emits structured JSONL events to `logs/worker-daemon/worker-<lane>.jsonl`:

- `scope_violation`: files modified outside owned_paths; turn rejected before review.
- `exhaustion_streak`: consecutive non-converged review cycles; includes streak count, run_id, lane_id.
- `token_burn_warning`: cumulative session token spend exceeds `token_burn_threshold` (default 2M).
- `worker_stopped`: clean daemon shutdown with lock cleanup.
- `context_pressure`: prompt consuming an unsafe fraction of the model's context window.
- `artifact_indexed`: large execution details were indexed into the artifact sidecar and referenced by `details_artifact_ref`.
- `lane_health_changed`: health state transition (e.g., `healthy` -> `degraded`).

### Lane Manifest Configuration

Lane manifests at `config/lane-orchestration/<task-ref>.json` support these hardening-related fields:

- `token_burn_threshold`: cumulative token spend threshold per session before emitting a warning (default: `2000000`).
- `model_context_window`: model context window size for context utilization measurement (default: `128000`).

### BackendAdapter Protocol

All execution backends MUST implement the `BackendAdapter` protocol defined in `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/backend_registry.py`. This ensures consistent handling of `execute()` and `resolve_reasoning_effort()` across Codex, Claude, and local models.

### Tool Signatures (Implementation Details)

- `switch_task(task_ref: string, objective: string = None, status: string = "in_progress", actor: object = None)` -> auto-archives outgoing task, activates target, restores objective from archive
- `orchestrator_start(task_ref: string, backend: string, poll_interval: float, single_pass: bool, model: string = None)`
- `orchestrator_single_cycle(task_ref: string, backend: string, model: string = None, worker_start_mode: string = "mcp")` -> runs one dispatch+poll+intake+verify cycle
- `worker_start(task_ref: string, lane_id: string, backend: string, poll_interval: float, single_pass: bool, session_mode: string, model: string = None, reasoning_effort: string = None)`
- `worker_event_history(task_ref: string, lane_id: string, limit: int = 20)` -> recent worker lifecycle events
- `worker_start_all(task_ref: string, backend: string, poll_interval: float, single_pass: bool, session_mode: string, model: string = None)`
- `run_structured_turn(prompt: string, schema: object, cwd: string, backend: string, env: dict = None, model: string = None, reasoning_effort: string = None, timeout_seconds: float = 120.0)`
- `dispatch_lane_work(task_ref: string, lane_id: string, model: string = None, backend: string = None, reasoning_effort: string = None)`
- `list_available_backends()` -> `list<string>`

## CLI Fallback

Primary entrypoints:

- `agent-handoff-mcp --workspace-root <repo> serve-stdio`
- `agent-handoff-mcp --workspace-root <repo> serve-http`
- `agent-handoff-mcp --workspace-root <repo> doctor`

Fallback subcommands:

- `state`
- `dashboard`
- `set`
- `switch`
- `decision`
- `action`
- `lane-upsert`
- `lane-list`
- `lane-activity`
- `lane-brief`
- `lane-brief-list`
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
- `dispatch-lane-work`
- `single-cycle`
- `orchestrator-start`, `orchestrator-status`, `orchestrator-stop`, `orchestrator-pause`, `orchestrator-resume`
- `worker-start`, `worker-status`, `worker-stop`, `worker-resume`, `worker-start-all`
- `worker-event-history`
- `run-structured-turn`
- `artifact-record`
- `artifact-search`
- `artifact-list`
- `artifact-get`
- `artifact-purge`

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
- Manifests should also identify runtime roots through `app_root` and/or `tooling_paths` when a lane depends on `composer.json` or `package.json`. The lane runtime uses those paths to bootstrap dependencies and derive default preflight checks when a manifest does not define explicit `preflight_commands`.
- Manifest creation must be generic, not task-specific. Use `make lane-manifest-init TASK=<task-ref> LANE_IDS='lane-a lane-b' [TASK_PLAN=docs/tasks/...md]` to scaffold a new manifest for any task, then fill in lane ownership and verification details.
- The orchestrator should register one `worktree_lane` per worker branch/worktree.
- Workers should write with `actor.lane_id` so decisions, tests, blockers, actions, and findings can be queried by lane.
- Workers should hand back one or more `worker_reports` as merge checkpoints instead of relying on free-form chat only.
- `lane_messages` provide an explicit mailbox for orchestrator briefs, worker questions, and acknowledgements when clients cannot directly message one another.
- Structured dependency briefs should ride on `lane_messages` rather than a parallel storage surface. The recommended convention is an open `orchestrator_to_worker` message whose subject starts with `brief:` and whose body stays compact enough to be injected into the next lane prompt without replaying full transcripts.
- Emit downstream briefs only for merge-ready source-lane reports with no unresolved blockers. If the source lane is blocked, non-merge-ready, or ambiguous, escalate through orchestrator guidance instead of replaying partial dependency state into downstream lanes.
- Lane prompt rendering is lane-scoped by default. `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py` should prioritize open assignment items plus compact `brief:` messages, cap those sections to a fixed budget, and omit deeper lane history unless an explicit inspection/escalation flag such as `--include-lane-history` is requested.
- Lane prompt renders should also expose a compact "Prompt Budget" summary so operators can see how much of the worker prompt came from assignment, dependency briefs, runtime guidance, lane history, and optional task-wide escalation before deciding to widen context further.
- Broader task-wide context is also opt-in. Use `--include-global-context` only when lane-local state and structured briefs are insufficient; default worker prompts should continue to rehydrate from the lane inbox, lane runtime guidance, unresolved briefs, and the latest lane report.
- Export/import and archive flows now include lane records, worker reports, and lane messages so delegated task history survives workspace migration.
- Lane verification should be recorded into MCP with `record_test_result`, not left as terminal-only output, so `get_lane_activity` remains the durable verification ledger for each lane.

Shared-state rule for sibling worktrees:

- Keep `workspace-root` pointed at the current worktree so branch/worktree provenance stays accurate.
- Point `state-dir`, `current-task-path`, and `exports-dir` at the orchestrator root so all lanes share one handoff database and generated `CURRENT_TASK.md`.
- The helper script [`scripts/worktree-lane`](../../../scripts/worktree-lane) encodes this pattern and should be preferred over ad-hoc CLI invocation.
- Orchestrator entrypoints such as `make lane-open` should fail fast if an existing worktree has drifted onto the wrong branch; silently reusing the wrong checkout risks misdirected commits and violates the lane-safety contract.
- Worker daemons should be started from the worker worktree root against the shared orchestrator state, for example `make worker-daemon TASK=<task-ref> LANE=<lane>` from the lane checkout. If launched from an app subdirectory, callers should either use a forwarding app Makefile that supports `worker-daemon` or invoke the top-level Makefile explicitly with `make -C "$(git rev-parse --show-toplevel)" worker-daemon ...`.
- In MCP-capable hosts, the preferred worker lifecycle surface is now `worker_start`, `worker_status`, `worker_stop`, `worker_resume`, and `worker_start_all`. Shell `make worker-daemon*` commands remain the fallback/wrapper layer for non-MCP environments and manual operator workflows.
- Worker daemon execution should expose live progress. Operators should expect terminal lifecycle markers plus periodic `exec_heartbeat` output while `codex exec` is still running, with the full JSONL trail under `logs/worker-daemon/worker-<lane>.jsonl`.
- Worker state is also persisted outside the JSONL stream at `.task-state/worker-<lane>.status.json` so MCP status queries can explain why a lane is idle, waiting, paused, stopped, or blocked on final handoff without requiring log inspection.
- Continuous orchestrator polling is a separate concern from dispatch-only routing. `make orchestrator-daemon` is allowed to intake merge-ready lanes, while `make handoff-dispatch` is the safe root command when the operator wants to fan out open work without starting merge automation.
- Backend Python lane verification should not depend on interactive shell activation. Prefer `PYENV_VERSION=description-service ...` in lane test commands over `pyenv activate description-service`, because `pyenv activate` requires shell init hooks that may not exist in daemon subprocesses.

## Artifact Retrieval Sidecar

The artifact retrieval sidecar extends `agent-handoff-mcp` with a content-indexed store for large agent outputs, execution logs, guidance briefs, and other bulky payloads that would otherwise inflate prompt context or be silently truncated.

### Sidecar Database

Artifacts are stored in a **separate** SQLite database at `.task-state/mcp-artifacts.db`. This file is:

- Not included in `export_handoff_state` / `import_handoff_state` payloads.
- Not rendered into `CURRENT_TASK.md`.
- Not queried by the primary handoff tools (`get_handoff_state`, `get_lane_activity`, etc.).

The sidecar tables use SQLite's FTS5 (Full-Text Search) extension. `run-doctor` checks FTS5 availability at startup and exits with an actionable error if it is unavailable.

### Thresholds

Controlled via `RuntimeConfig`. Contract-frozen defaults:

- `artifact_index_min_bytes = 4096` (approximately 4 KB)
- `artifact_index_min_lines = 80`

`maybe_record_artifact()` skips indexing when content falls below **both** thresholds and returns `None`. Callers must not add artifact refs to messages or prompts when `None` is returned.

### MCP Tool Signatures

- `record_artifact(task_ref=None, lane_id=None, app_root=None, source_kind, source_label, content_type="text/plain", summary=None, content)` -> `{ ok, source_id, source_label, was_updated, chunk_count }`
- `search_artifacts(queries: list<string>, task_ref=None, lane_id=None, app_root=None, source_kind=None, content_type=None, limit=10)` -> `{ ok, total, hits: list<{ source_id, source_label, source_summary, task_ref, lane_id, app_root, source_kind, content_type, title, snippet, rank }> }`
- `get_artifact_source(source_id=None, task_ref=None, source_label=None)` -> `{ ok, source }` where `source` includes source metadata plus `chunks: list<{ chunk_order, title, body }>`
- `list_artifact_sources(task_ref=None, lane_id=None, app_root=None, source_kind=None, limit=50, offset=0)` -> `{ ok, total, sources: list<SourceSummary> }`
- `purge_artifacts(task_ref=None, older_than_days=None)` -> `{ ok, purged_sources }` — at least one of `task_ref` or `older_than_days` is required

### Chunking Strategy

Content is chunked by `content_type` before FTS5 indexing:

| `content_type`     | Strategy                                                     |
| ------------------ | ------------------------------------------------------------ |
| `text/markdown`    | Split at H1/H2/H3 headings; heading text becomes chunk title |
| `text/plain`       | Fixed groups of 50 lines; no title                           |
| `application/json` | Top-level keys (object) or top-level list elements (array)   |

### Deduplication

`maybe_record_artifact()` computes a SHA-256 hash of the content before indexing. If a source with the same `(source_label, task_ref, lane_id, source_kind)` identity already exists with an identical hash, indexing is skipped and the call returns `None` to the caller or `was_updated: false` through the MCP write surface. Callers must not add new artifact refs to messages or prompts on a duplicate/no-op path.

### Prompt-Budget Integration

`packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py` appends retrieved artifact snippets to worker prompts when context budget allows:

1. After the base sections are rendered, `_measure_context_utilization()` produces a `pressure` value.
   Pressure is classified from `prompt_tokens`, which may come from an exact supported tokenizer path (`prompt_token_source="observed"`), a tokenizer-backed estimate (`"tokenizer_estimate"`), or the char-per-token fallback (`"char_estimate"`):
   - `"high"`: `utilization_ratio > 0.40` AND `domain_signal_ratio < 0.50` — prompt is large relative to context window and less than half consists of domain-task content (assignment, runtime guidance, dependency briefs).
   - `"elevated"`: `utilization_ratio > 0.30` — prompt uses more than 30% of the configured context window.
   - `"normal"`: otherwise.
2. If `pressure` is `"elevated"` or `"high"`, artifact retrieval is skipped entirely to protect required assignment content.
3. Otherwise, `_artifact_context_section()` receives a `budget_chars` equal to the remaining estimated char budget.
4. Pinned artifact refs from lane-message payloads (`payload.artifacts`) are loaded first with `get_artifact_source()`.
5. Remaining budget is filled by `search_artifacts()` queries derived from open lane-message bodies, blocker descriptions, and open finding descriptions.
6. Retrieved snippets are appended as a "Relevant Artifacts" section and context metrics are recomputed after appending the section.

Base prompt sections are subject to per-section item caps (hardcoded in `lane_prompt.py`):

| Section                                 | Default cap | Requires flag              |
| --------------------------------------- | ----------- | -------------------------- |
| Assignment items (open actions, briefs) | 12          | —                          |
| Dependency brief items                  | 6           | —                          |
| Lane decision items                     | 4           | `--include-lane-history`   |
| Lane test result items                  | 4           | `--include-lane-history`   |
| Global / task-wide context items        | 6           | `--include-global-context` |

`--include-lane-history` and `--include-global-context` are both off by default. When omitted, the rendered prompt includes a "Context Budget" section that tells the model explicitly why those sections are absent (to preserve tokens), and how to request them if manual inspection is needed.

This integration is purely additive. When `agent_handoff_mcp` is not importable, a module-level import guard (`_ARTIFACT_SEARCH_AVAILABLE = False`) silently disables retrieval.

### Ingestion Gates

`packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_exec.py` applies `_compress_large_result_details()` after worker execution:

- If the `details` field of the structured result JSON exceeds the configured `RuntimeConfig.artifact_index_min_bytes` / `artifact_index_min_lines` threshold, the full body is indexed as an `"execution-output"` artifact.
- The inline `details` is replaced with the first 500 chars plus a truncation marker: `... [truncated — full output indexed as artifact:<source_id>]`.
- The result JSON gains a `details_artifact_ref` integer field.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py` reads `details_artifact_ref` after `exec_complete` and emits an `artifact_indexed` JSONL event when present.
- `scripts/mcp/lane_result.py` can attach that artifact ref to the follow-up `worker_to_orchestrator` lane message payload so operators have an inspectable evidence handle without replaying the full log.

`scripts/mcp/orchestrator_guidance.py` indexes redispatch message bodies:

- When `_apply_guidance_resolution()` emits a `redispatch` lane message and the body exceeds the configured threshold, it is indexed as a `"guidance-redispatch"` artifact.
- The `payload["artifacts"]` list on the lane message receives the corresponding `source_id` string.
- Workers polling `make lane-inbox` see the artifact ref in the message payload and can retrieve the full brief via `get_artifact_source` or `make artifact-list`.

### Make Targets

```bash
make artifact-search QUERY="<text>" [TASK=<task-ref>] [LANE=<lane-id>] [LIMIT=10]
make artifact-list [TASK=<task-ref>] [LANE=<lane-id>] [LIMIT=20]
```

Both targets are defined in `mk/lane-worker.mk`. `QUERY` is required for `artifact-search`. They operate against the shared sidecar database at `.task-state/mcp-artifacts.db`.

### CLI Subcommands

```bash
agent-handoff-mcp --workspace-root <repo> artifact-record --source-kind log --source-label pytest-output --content-file /tmp/output.txt [--task-ref ...] [--lane-id ...]
agent-handoff-mcp --workspace-root <repo> artifact-search --query "..." [--task-ref ...] [--lane-id ...] [--limit 10]
agent-handoff-mcp --workspace-root <repo> artifact-list [--task-ref ...] [--lane-id ...] [--limit 20]
agent-handoff-mcp --workspace-root <repo> artifact-get --source-id <source-id>
agent-handoff-mcp --workspace-root <repo> artifact-purge [--task-ref ...] [--older-than-days ...]
```

### Retention Rules

Call `purge_artifacts` periodically to reclaim disk space:

- Per-task purge on final archive: `purge_artifacts(task_ref=<completed_task>)`.
- Global age-based purge: `purge_artifacts(older_than_days=30)`.
- The default stale-artifact threshold is 30 days since `artifact_sources.updated_at`.
- `archive_task_state(...)` archives handoff rows only. Artifact retention stays explicit: archive the task first, then purge artifact rows with `purge_artifacts(...)` if the artifacts are no longer needed.
- `purge_artifacts(...)` can scope by `task_ref`, `lane_id`, `app_root`, `older_than_days`, or a compatible combination of those filters.

The sidecar database is not included in `archive_task_state` and must be backed up separately if artifact content needs to survive workspace migration.
