---
boundary_owner: agentic-tooling
---

# Agent Handoff MCP Contract

## Purpose

`agent-handoff-mcp` is the portable MCP server for agent coordination state. After the AHMCP-6 event, review, next-action, and artifact-domain consolidation plus profile-removal stretch work, AHMCP-8 verified-test search/read support, and AHMCP-23 observatory dashboard split, it exposes a unified MCP surface for task state, review findings, verification evidence, artifacts, export/import, handoff close checks, and DASHBOARD.txt generation. Orchestration, daemon lifecycle, lane management, and turn metrics are served by [`agent-orchestrator-mcp`](agent-orchestrator-mcp.md). Use `agent-handoff-mcp --workspace-root "$(pwd)" doctor` to inspect the live registered tool surface from the installed package.

## Runtime Configuration

CLI args take precedence over env vars.

Supported config inputs:

- `--workspace-root` or `AGENT_HANDOFF_WORKSPACE_ROOT`
- `--state-dir` or `AGENT_HANDOFF_STATE_DIR`
- `--current-task-path` or `AGENT_HANDOFF_CURRENT_TASK_PATH`
- `--exports-dir` or `AGENT_HANDOFF_EXPORTS_DIR`
- `--tool-profile` or `AGENT_HANDOFF_TOOL_PROFILE` — legacy compatibility input. The installed server exposes the unified `all` surface.
- `AGENT_HANDOFF_DEFAULT_AGENT`
- `AGENT_HANDOFF_DEFAULT_BRANCH`
- `AGENT_HANDOFF_DEFAULT_COMMIT_SHA`

Default workspace-owned state:

- DB: `.task-state/handoff.db`
- artifact DB: `.task-state/mcp-artifacts.db`
- exports: `.task-state/exports/`
- generated machine-readable snapshot: `CURRENT_TASK.json` (JSON, active-task-only)
- generated human-readable dashboard: `DASHBOARD.txt` (pure ASCII, human-scoped observatory view)

`CURRENT_TASK.json` is a deterministic JSON snapshot of the active task state (objective, status, findings, decisions, tests, blockers, actions, lanes). `DASHBOARD.txt` is the human-readable ASCII observatory: Needs Attention summary, All Tasks table, cross-task open findings, deferred/wontfix findings, and registered extension sections (e.g. Lane Health from agent-orchestrator-mcp). Use `render_handoff(kind='current_task')` to refresh the JSON snapshot and `render_handoff(kind='dashboard')` to refresh the ASCII dashboard.

The monorepo now consumes `agent-handoff-mcp` from the private git+ssh source for `darce/mcp-agent-handoff`; the installed binary shape stays the same.

Runtime bootstrap:

```bash
cd "${REPO_ROOT:-$PWD}"

# Core ledger server
uv tool install "agent-handoff-mcp @ git+ssh://git@github.com/darce/mcp-agent-handoff.git"

# Orchestration server (daemons, workers, lanes, metrics)
uv tool install "agent-orchestrator-mcp @ git+ssh://git@github.com/darce/mcp-agent-orchestrator.git"

# Codex subagent bridge for BACKEND=codex-subagent
python3 -m pip install -e packages/codex-subagent-bridge

# Validate runtime wiring, writable state dirs, and FTS5 support
agent-handoff-mcp --workspace-root "$(pwd)" doctor
agent-orchestrator-mcp --workspace-root "$(pwd)" doctor
```

Notes:

- `doctor` hard-fails when the local SQLite build lacks FTS5; artifact indexing depends on it.
- `dashboard-live` does not require optional UI packages. `dashboard-tui` uses Textual when installed, then `rich.live`, then plain text.

## MCP Tool Surface

Surface classes:

- `action`: mutates state, filesystem state, lane runtime, or daemon runtime. Do not retry blindly.
- `query`: read-only inspection of canonical state. Safe to retry when transport/runtime is healthy.
- `generator`: derives a report, search result, reconciliation result, or rendered artifact from current state. Usually safe to retry unless the tool also writes a file by default.

| Tool | Surface class | Idempotent | Notes |
| --- | --- | --- | --- |
| `set_handoff_state` | action | no | Updates active task state with optimistic revision guard. |
| `get_handoff_state` | query | yes | Canonical task-state read. `sections` accepts a comma-separated subset of task-state sections; `active` and `limits` remain always included. `detail` accepts `full` (default) or `summary` to truncate long rationale and verification fields without changing the default payload shape. |
| `record_event` | action | no | Appends decision/test-result/blocker state through a typed `event` payload. `event.event_kind` selects the variant and required fields. |
| `next_actions` | action | no | Typed next-actions domain surface. `action.operation` selects `list`, `add`, `update`, `complete`, or `skip`. |
| `review_findings` | action | no | Typed review-findings domain surface. `review.operation` selects `record`, `batch_record`, `update`, or `list`. Preserves atomic batch semantics and list filters on one tool. |
| `review_runs` | action | no | Typed review-runs domain surface. `review.operation` selects `record`, `list`, or `coverage`. |
| `handoff_close_check` | generator | yes | Derived readiness verdict from current state. |
| `render_handoff` | generator | no | Compound renderer. `kind="current_task"` writes machine-readable JSON to `CURRENT_TASK.json` by default (objective, status, recent decisions, tests, findings, and actions for the active task ref). `kind="dashboard"` renders the human observatory view and writes pure-ASCII `DASHBOARD.txt` by default (All Tasks table, Needs Attention, Open Findings, Deferred/Won't Fix, and registered extension sections such as Lane Health / Worker Status from `agent-orchestrator-mcp`). Pass `write_file=False` to return content without writing. |
| `export_handoff_state` | generator | yes | Produces portable snapshot output. |
| `import_handoff_state` | action | no | Imports snapshot into local DB; destructive in replace modes. |
| `archive_task_state` | action | no | Moves active state into archive storage. |
| `record_file_touch` | action | no | Records a file-touch entry in the touched-files ledger. Requires `file_path` (monorepo-relative, rejects absolute paths and `..` traversal) and `change_kind` (`edit`, `add`, or `delete`). Optional: `session`, `commit_sha` (validated through shared SHA expansion), `actor`, `task_ref`. Returns the inserted touch row. |
| `get_touched_files` | query | yes | Lists touched-file rows for the resolved task. Optional: `task_ref`, `limit` (default 20, max 200), `offset`. Returns `touches` array with `total_matching` and `has_more` pagination metadata. |
| `get_verified_tests` | query | yes | Lists verified test rows with optional task, lane, branch, commit, and pass/fail filters. |
| `load_session` | query | yes | **Compound**: calls `get_handoff_state` + `review_findings(review={"operation":"list","status":"open"})` + `get_touched_files` in one invocation. Use at session start to minimise round trips. `sections` is passed through only to the nested `state` payload from `get_handoff_state`; `detail` is passed through to both nested state and findings; `top_n_touched_files` (default 20, max 200) bounds the additive `touched_files` list. Defaults preserve the pre-parameterization full payload behavior. |
| `close_slice` | action | no | **Compound**: records a slice-complete decision, re-applies the active task as `in_progress`, and regenerates `CURRENT_TASK.json` plus `DASHBOARD.txt`. Requires `expected_revision` when the target task is currently active. Accepts the same optional `changed_files` list as the decision variant of `record_event` and passes it through to the nested decision write. |
| `update_task_status` | action | no | Updates task status without recording a slice decision. For the active task this requires `expected_revision`; for archived tasks it updates the archived snapshot status used by dashboard rendering. |
| `audit_decision_ids` | query | yes | Audits recent decision IDs for grammar conformance. Returns canonical/malformed/freeform classifications per ID. |
| `artifacts` | action | no | Typed artifacts domain surface. `artifact.operation` selects `record`, `search`, `get`, or `purge`. Search mode supports both ranked hits and source-list mode when `queries` is omitted or empty; get mode supports `include_terms=true`. |
| `search_handoff` | generator | yes | Returns ranked snippets over handoff FTS tables, including verified test evidence. `detail` accepts `full` (default) or `summary`, and `fields` accepts a comma-separated per-result projection. |

Cross-task and review-summary tools (`switch_task`, `get_latest_slice_review_packet`, `get_review_findings_summary`, `reconcile_review_findings`) are registered on `agent-orchestrator-mcp`. See [`agent-orchestrator-mcp.md`](agent-orchestrator-mcp.md).

Preferred review-intake path when orchestrator is loaded:

1. `get_latest_slice_review_packet`
2. `get_review_findings_summary` or `review_findings(review={"operation":"list","status":"open"})` as needed

Handoff-only fallback:

1. `load_session`
2. `search_handoff(queries=["slice_complete"], record_types=["decision"], limit=1)`
3. `get_verified_tests(task_ref=..., commit_sha=...)`
4. `review_findings(review={"operation":"list","status":"open"})`

This is a degraded multi-call fallback for sessions where orchestrator is unavailable. `agent-handoff-mcp` does not expose a parallel compound `get_review_packet` surface.

Retry guidance:

- Retry `query` and pure `generator` surfaces when the failure is transport-level, timeout-based, or due to a transient read lock.
- Do not auto-retry `action` surfaces unless the caller can prove the operation is safe to repeat.
- Treat `render_handoff` and `close_slice` as write-affecting surfaces even though they derive output from current state.

## MCP Troubleshooting Ladder

### 1. Startup Failure

Symptoms:

- `agent-handoff-mcp` binary not found
- import or launcher failure
- wrong `--workspace-root` / `--state-dir`
- missing `.task-state` or unwritable `CURRENT_TASK.json` / `DASHBOARD.txt`

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

- treat the installed `agent-handoff-mcp` package and this contract as the live source of truth for the ledger surface in this monorepo
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
- `CURRENT_TASK.json` is out of sync with handoff state
- review close checks fail because fresh verification evidence is missing

Checks:

```bash
agent-handoff-mcp --workspace-root /path/to/repo doctor
agent-handoff-mcp --workspace-root /path/to/repo state
agent-handoff-mcp --workspace-root /path/to/repo review-findings --operation list
```

Recovery:

- reissue the write with the live signature and minimal valid payload
- record verification with `record_event(event={event_kind=\"test_result\", ...})` instead of prose-only rationale
- regenerate `CURRENT_TASK.json` after decision writes when the workflow requires it

## Artifact Read Shaping

The artifact read surfaces now support the same additive compact-read pattern used by the handoff state and review-finding reads:

```python
artifacts(
    artifact={
        "operation": "search" | "get",
        ...
    }
) -> str
```

- `detail="summary"` truncates long artifact text fields (`summary`, `source_summary`, `snippet`, and `metadata_json`) without changing the default full-detail behavior.
- `artifacts(operation="get", detail="summary")` also returns only the first three chunk previews while preserving `chunk_count` for the full source.
- `fields` is a comma-separated projection over the per-row payload. `artifacts(operation="search")` interprets it against the active mode:
  - search mode: hit fields such as `source_id`, `source_label`, `title`, `snippet`
  - source-list mode: source fields such as `id`, `task_ref`, `source_label`, `summary`
  - artifact fetch: source fields such as `source_label`, `chunk_count`, `chunks`
- Invalid field names are stripped. If none remain, the tool falls back to a compact identity shape instead of failing.

## Structured Handoff Search (`search_handoff`)

`search_handoff` provides BM25/FTS5 full-text search over the five canonical handoff record
tables (decisions, review findings, blockers, next actions, and verified tests) stored in `handoff.db`.

### FTS5 Shadow Tables

Five FTS5 virtual tables are maintained in `handoff.db` alongside the canonical tables:

| FTS table       | Source table      | Indexed body                                     | Status column |
| --------------- | ----------------- | ------------------------------------------------ | ------------- |
| `decisions_fts` | `decisions`       | `decision \|\| ' ' \|\| COALESCE(rationale, '')` | no            |
| `findings_fts`  | `review_findings` | `description \|\| ' ' \|\| COALESCE(fix, '')`    | yes           |
| `blockers_fts`  | `blockers`        | `description`                                    | yes           |
| `actions_fts`   | `next_actions`    | `action`                                         | yes           |
| `verified_tests_fts` | `verified_tests` | `command \|\| ' ' \|\| COALESCE(result, '')` | no            |

All tables use `tokenize='porter unicode61'`, `record_id UNINDEXED`, `task_ref UNINDEXED`, and
`lane_id UNINDEXED` so that scope filters (`task_ref`, `lane_id`) are fast equality lookups
without touching FTS ranking.

### Trigger Maintenance

Fifteen SQL triggers (INSERT / UPDATE / DELETE for each source table) keep FTS tables in sync
automatically. UPDATE triggers follow the DELETE-then-INSERT pattern to prevent stale rows. All
triggers use `CREATE TRIGGER IF NOT EXISTS` so they are schema-idempotent.

`_ensure_handoff_fts(conn)` is called on every `_get_db_connection()` call. It:

1. Probes FTS5 availability (CREATE/DROP `_fts5_handoff_probe`); silently returns on failure.
2. Creates the five FTS5 virtual tables if not already present.
3. Creates the fifteen triggers if not already present.
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
    record_types: list[str] | None = None,  # subset of ["decision", "finding", "blocker", "action", "verified_test"]
    limit: int = 20,                         # max 200
    detail: str = "full",
    fields: str | None = None,
) -> str:
```

- **queries**: One or more search terms. Multiple terms are OR-joined. Multi-word terms are
  automatically phrase-quoted (`"term with spaces"`) for precise adjacency matching.
- **record_types**: Defaults to all five types when omitted.
- **limit**: Clamped to [1, 200]. Results across all searched types are merged and re-ranked.
- **detail**: `full` preserves the compact FTS snippet returned by SQLite. `summary` truncates that snippet further for startup-friendly reads.
- **fields**: Optional comma-separated projection over result rows, for example `record_type,snippet`.

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
  "record_types_searched": ["action", "blocker", "decision", "finding", "verified_test"]
}
```

- `status` is `null` for decisions (no status column); `open` / `fixed` / etc. for others.
- `snippet` uses FTS5 `snippet()` with a 12-token window; result is compact, not full body.
- Results are sorted by BM25 rank (best match first); ties break by insertion order.
- Invalid `fields` values are stripped. If none remain, the result rows fall back to `record_type`, `record_id`, `task_ref`, and `snippet`.

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
- Any `record_types` entry is not in `["decision", "finding", "blocker", "action", "verified_test"]`: returns error.
- FTS5 tables not initialized (FTS5 unavailable): returns `{"ok": false, "error": "..."}`. Run
  `doctor` to diagnose.

## Verified Test Read Surface (`get_verified_tests`)

`get_verified_tests` returns verified test rows from the handoff ledger without requiring a broader dashboard read.

```python
get_verified_tests(
  task_ref: str | None = None,
  lane_id: str | None = None,
  branch: str | None = None,
  commit_sha: str | None = None,
  passed: bool | None = None,
  limit: int = 100,
  offset: int = 0,
) -> str
```

- Results are ordered by `verified_at DESC, id DESC` for deterministic newest-first reads.
- Filters are additive; combine `branch`, `commit_sha`, and `passed` to inspect the exact verification rows tied to a merge candidate.
- The envelope includes `total_matching`, `returned`, `has_more`, and `tests`.

### Response Shape

```json
{
  "ok": true,
  "total_matching": 1,
  "returned": 1,
  "has_more": false,
  "tests": [
    {
      "id": 42,
      "task_ref": "my-task",
      "lane_id": "backend-domain",
      "branch": "feature/my-task",
      "commit_sha": "0123456789abcdef0123456789abcdef01234567",
      "command": "PYENV_VERSION=description-service pytest tests/test_schema_migrations.py -q",
      "passed": true,
      "verified_at": "2026-04-10 03:20:23"
    }
  ]
}
```

- `tests` entries return the stored verification row data rather than FTS snippets.
- Filter combinations narrow the result set without changing the envelope shape.


## Request Shape Notes

- Most write tools accept optional `task_ref`. When omitted, they target the active task as a fallback.
- In concurrent or multi-task workflows, pass `task_ref` explicitly on writes instead of relying on ambient active-state routing.
- Live MCP tool signatures are authoritative over examples, templates, or prior-session memory. Prefer the minimal valid payload for write operations unless a richer payload is required by the current signature.
- If a write call fails validation, treat it as signature drift. Retry once with the minimal payload accepted by the live signature, then update the stale contract/rule/template in the same slice so the bounce does not recur.
- Slice-completion decisions must use the prefixed decision grammar `<author_tag>_slice_complete_<work_ref>_<slug>` for new writes. The legacy `slice_complete_<short_label>` format is grandfathered for historical rows and recognized by all read paths (close-check, slice-review packet derivation). New writes should use the prefixed form. Both formats require a structured rationale with the four headings `## Changes`, `## Verification`, `## Schema / Contract Changes`, and `## Open Threads`.
- `record_event(event={event_kind="decision", ...})` requires a `session` string in the nested decision variant (MCP path) or `--session` flag on the `event --event-kind decision` CLI path. Use a stable, human-readable identifier such as `"<agent>-<task-slug>"` or `"<agent>-<short-description>"`. The field is NOT auto-populated from context; omitting it causes validation failure.
- The `decision` variant of `record_event(...)` rejects slice-complete writes at write time when the rationale is missing those headings or any section is empty. This is enforced before the row is inserted.
- The `decision` variant of `record_event` accepts optional `changed_files` (list of monorepo-relative paths touched by this slice). Stored as `changed_files_json` on the decision row. When present, the slice-review packet uses this list directly instead of parsing file paths from the rationale text. Pass this parameter on every slice-completion decision to give reviewers an explicit, structured scope.
- Historical decision rows that predate the prefixed naming scheme are grandfathered. MCP read paths (close-check, slice-review packet, handoff search) recognize both formats. Do not plan retroactive renames of historical rows.
- The structured rationale is mandatory even for docs-only slices. Use `- none.` for empty sections rather than omitting headings.
- Handoff consumers should treat prose-only completion decisions as malformed process output that must be corrected before the slice is considered fully handed off.
- To switch between tasks, use `switch_task(task_ref)` on `agent-orchestrator-mcp`. It auto-archives the outgoing task (full snapshot) and activates the target, restoring the objective from its archive when not provided. Idempotent if the target is already active.
- For in-place updates to the _current_ task (status, objective change, focus update), use `set_handoff_state(...)` directly.
- `set_handoff_state` requires `expected_revision` for updates. Accepts optional `focus` for mutable per-slice working context. `objective` is optional on updates (preserved when omitted). `focus` is preserved when omitted on updates; pass an empty string to clear it explicitly.
- `close_slice` is a slice-completion helper, not a task-closure helper. It keeps the target task `in_progress` and now preflights the active-task revision guard before recording a decision.
- Use `update_task_status(task_ref, status, expected_revision=...)` when you need to mark a task `done` or otherwise correct status without writing a slice-completion decision. Archived-task updates do not require `expected_revision` because they update the archived snapshot rather than the live singleton row.
- The shared actor shape may include `model`, `model_label`, `reasoning_level`, and `lane_id` in addition to `agent`, `branch`, and `commit_sha`. Only decisions persist the granular model fields today; other write surfaces continue to persist `agent` plus git provenance.
- `build_write_actor(agent=None, model=None, model_label=None, reasoning_level=None, branch=None, commit_sha=None, lane_id=None) -> WriteActor` is the public helper for constructing that normalized actor payload before passing it into write tools.
- `build_write_actor` derives the canonical `agent` display identity from model provenance when available: `"{model_label} {reasoning_level}"` when both are present, `model_label` when only the label is known, and the caller-provided `agent` only as a legacy fallback.
- Known model labels are normalized for common backends (`claude-opus-4-0520` -> `Opus 4.6`, `claude-sonnet-4-20250514` -> `Sonnet 4`); unknown models pass through unchanged.
- Decision rows now persist nullable `model`, `model_label`, and `reasoning_level` columns alongside `agent`. Treat the turn-metrics ledger on `agent-orchestrator-mcp` as the canonical source for token consumption; decision rows carry model provenance only and do not duplicate per-turn token columns.
- `record_event` and `next_actions` accept optional `task_ref`, matching the existing cross-task targeting pattern. For `record_event`, `task_ref` lives inside the typed `event` payload.
- Write responses for `record_event` and `next_actions` echo the resolved `task_ref`. Treat that field as the authoritative write target in multi-agent flows.
- `review_findings(review={"operation":"record", ...})` accepts optional `details={ line_start?, line_end?, fix? }`.
- `review_findings(review={"operation":"record", ...})` also accepts optional `review_mode` with values `branch`, `release_audit`, or `planning`.
- `review_findings(review={"operation":"record", ...})` accepts `task_ref="__repo__"` to record a repo-scoped finding that is not owned by any one implementation task. Task-scoped listing queries exclude `__repo__` rows unless repo scope is explicitly included.
- `review_findings(review={"operation":"batch_record", ...})` accepts `session`, `findings` (list of `BatchFindingItem`), optional `actor`, and optional `task_ref`. Each `BatchFindingItem` requires `finding_id`, `severity`, `file_path`, and `description`; `review_mode` and `details` are optional. Maximum 100 items per call; larger batches return `ok: false` without writing. All items are pre-validated (severity, review_mode, required fields) before the transaction opens — a single invalid item rejects the entire batch. Returns `{ ok, task_ref, written, results: [{ finding_id, action, reopened? }] }`. Use this operation instead of repeated single-record writes when logging 3 or more findings in a single review pass.
- `get_handoff_state` accepts optional `sections` and `detail` on task views. `sections` is a comma-separated subset of task-state sections; invalid names are silently dropped, and if no valid names remain the response contains only identity data (`active` + `limits`, no data sections). The reserved token `sections="identity"` explicitly requests the same identity-only shape; when present it takes precedence over any other section names. `active` and `limits` are always included and are not selectable or suppressible. Pass `sections=None` (the default) to receive the full task payload. `detail="summary"` truncates long rationale, command, result, and finding text fields while keeping the default `detail="full"` response backward-compatible.
- `review_findings(review={"operation":"update", ...})` accepts exactly one of `finding_id` or `finding_db_id`.
- `review_findings(review={"operation":"update", ...})` requires `resolution_notes` for `wontfix` and `deferred`.
- `review_findings(review={"operation":"update", ...})` requires `reopen_reason` when changing a non-open finding back to `open`.
- `review_findings(review={"operation":"update", ...})`: when `task_ref` is omitted and `finding_id` or `finding_db_id` is provided, the lookup is global. If exactly one row matches, the update is applied to that row regardless of active task. If multiple rows share the same `finding_id`, an explicit ambiguity error listing the candidate scopes is returned.
- `review_findings(review={"operation":"list", ...})`: when `finding_id` or `finding_db_id` is provided and `task_ref` is omitted, the lookup is global — the active-task fallback is skipped. If more than one row shares the same `finding_id` across different task scopes, an explicit ambiguity error is returned. To scope the lookup to a specific task, pass `task_ref` explicitly.
- `finding_id` naming convention: prefix with the owning task-ref or review scope to minimize cross-scope collisions (e.g., `E12-3-001`, `REVIEW-COVERAGE-E12-3-001`). Global uniqueness is not schema-enforced; ambiguity errors serve as the collision safety net. Repo-scoped findings should use the `__repo__` task-ref prefix or the review subject path as the prefix.
- `review_findings(review={"operation":"list", ...})` accepts optional `review_mode`; `branch` includes rows where `review_mode IS NULL` for backward compatibility.
- `review_findings(review={"operation":"list", ...})` accepts optional `detail="full"|"summary"`. Summary mode truncates long `description`, `fix`, `resolution_notes`, and `verification_evidence` fields while preserving the same filters, counts, and lookup rules.
- `load_session` accepts optional `sections`, `detail`, and `top_n_touched_files`. `sections` is passed only to the nested `state` payload returned by `get_handoff_state`; `detail` is passed to both `get_handoff_state` and `review_findings(review={"operation":"list","status":"open"})` so the combined response can be trimmed without changing default compatibility behavior. `top_n_touched_files` (default 20, max 200) bounds the additive `touched_files` list returned alongside `state`, `open_findings`, and `open_findings_count`.
- `review_runs(review={"operation":"record", ...})` requires `review_run_id` (must be globally unique in the ledger), `session`, and `subject_path`. `subject_kind` defaults to `task_plan`; valid values are `task_plan`, `epic`, `branch`, `adr`, `roadmap`, `other`. `review_mode` defaults to `planning`; valid values are `branch`, `release_audit`, `planning`. `verdict` is optional; valid values are `pass`, `pass_with_findings`, `fail`, `conditional_pass`. `verdict_decision` is optional and should hold the stable decision string from the decision variant of `record_event` (not the integer id). `task_ref` is optional and links the run to a task scope.
- `review_runs(review={"operation":"list", ...})` is unscoped by default (returns all runs). Pass `task_ref` to scope to a task, `subject_path` to scope to an artifact, `review_mode` to filter by review type, or `verdict` to filter by outcome. Max 100 per page.
- `review_runs(review={"operation":"coverage", ...})` requires at least one of `task_ref` or `subject_path`. When `task_ref` is given, finding counts come from the `task_ref` column on `review_findings`. When only `subject_path` is given, finding counts are derived via the `review_run_id` link from matching runs. Returns: `run_count`, `latest_review_run_id`, `latest_verdict`, `recent_run_ids` (last 5), `open_findings_by_severity` (dict of high/medium/low counts), `reopened_findings_count`.
- `review_runs(review={"operation":"coverage","task_ref":"REVIEW-COVERAGE"})` is a supported backward-compatible query pattern; the returned counts will be zero until repo-scoped findings are migrated from the pseudo-task bucket.
- Use `review_runs(review={"operation":"record", ...})` at the end of each planning or branch review to record the verdict and link it to the reviewed artifact. Then pass `review_run_id` on each `review_findings(review={"operation":"record", ...})` call to link findings to their run.
- When `current_commit_sha` is provided, `handoff_close_check` also verifies that at least one structured `slice_complete_*` decision exists for that commit. Treat missing current-commit slice summaries as a close/review gate failure, including for docs-only slices.
- The `test_result` variant's `result` field on `record_event` is a concise verification-summary field, not a full log sink. Keep short proof lines such as `55 passed in 7.02s`, `diff-check clean`, or `REVIEW READY: READY`; store longer output in artifacts/files instead of the `verified_tests` table.
- `import_handoff_state(mode="replace_task")` rejects destructive clears unless `allow_destructive_clear=true`.
- `close_slice` requires a `session` string (same as the decision variant of `record_event`). Pass `task_ref` explicitly in multi-task flows. `focus` updates the active-task working context after the decision is recorded. `changed_files` passes through to the decision variant of `record_event` for structured review scope. The success response includes `decision` (full row) and `task_revision` (int) so callers can confirm state without a follow-up read.
- `export_handoff_state` defaults to `include_markdown=False`. Pass `include_markdown=True` explicitly to embed CURRENT_TASK.json markdown in the export.
- `render_handoff(kind="current_task")` renders active-task-only output; cross-task sections are produced by `render_handoff(kind="dashboard")`. The "All Review Findings History" section has been removed from the default render; historical findings are available via `review_findings(review={"operation":"list","status":"all"})`.
- `render_handoff(kind="dashboard")` accepts `write_file` (default `True`) to control whether `DASHBOARD.txt` is written to disk. Pass `write_file=False` to get the text without writing a file (useful in tests and CI diff checks). Extension sections (Lane Health, Worker Status) are contributed by `agent-orchestrator-mcp` via `register_dashboard_extension`.
- `set_handoff_state` accepts an optional `target_branch` parameter. When provided, it sets the task's intended work branch. When omitted on subsequent calls, the existing value is preserved. The field appears in `get_handoff_state` responses and in the CURRENT_TASK.json Active Status section.
- `set_handoff_state` accepts an optional `target_worktree_path` parameter (introduced in the lane-orchestration improvements slice). It records the absolute filesystem path of the linked worktree where the task should be implemented. Used by `make context` and write-side context-drift warnings to fail-fast when an agent runs from the wrong directory in a multi-agent / multi-worktree workflow. When omitted on subsequent calls, the existing value is preserved.
- Write surfaces that resolve actor context (`set_handoff_state`, `record_event`, `next_actions`, `review_findings`, and `review_runs`) emit `context_drift` warnings when the resolved actor branch differs from the active task's `target_branch`, or when the current process working directory differs from the active task's `target_worktree_path`.
- Branch drift is warning-only by default. When `AGENT_HANDOFF_ENFORCE_BRANCH` is truthy and `AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT` is not, writes targeting enforceable branches fail before mutation with `BranchMismatchError` for direct Python callers.
- MCP clients do not receive a transport exception for this case. The MCP wrapper converts `BranchMismatchError` into the normal v2 envelope with `ok=false` and `data.error`, `data.task_ref`, `data.expected_branch`, and `data.actual_branch` populated so agents can handle the failure as structured tool output.
- `switch_task` (registered on `agent-orchestrator-mcp`) also accepts `target_branch`, set at task init time.

### v2 Response Envelope (OC-004)

All public MCP tool responses use the v2 envelope as of package version `0.2.0`. Previous tool-specific top-level fields are nested under `data`.

As of AHMCP-7, responses use compact serialization: no indentation, null/empty fields stripped, and no legacy field mirroring. MCP tool handlers return `dict` to FastMCP (which serializes once), eliminating double-serialization escapes in MCP responses. Core functions continue returning `str` for orchestrator in-process callers. The `data` block is the canonical payload; callers should read fields from `data`, not from top-level mirrors. In-process Python callers that need flat access should use `_flatten_v2()`.

```json
{"ok":true,"schema_version":2,"tool":"get_handoff_state","scope":{"task_ref":"AHMCP-3"},"data":{"active":{...},"limits":{...},...},"task_ref":"AHMCP-3"}
```

| Key | Type | Notes |
|-----|------|-------|
| `ok` | bool | Always present |
| `schema_version` | int | Always `2` for v2 responses |
| `tool` | string | Tool name that produced this response |
| `scope.task_ref` | string/null | Resolved task reference |
| `data` | object | Tool-specific payload (canonical v2 shape) |
| `task_ref` | string | Present when task_ref is non-null |
| `mutation` | object | Present on write responses only: `{ entity, operation, affected_ids, task_revision }`. Omitted when null. |
| `artifacts` | array | Present only when non-empty |
| `warnings` | array | Present only when non-empty |

Internal utility functions (`get_review_findings_summary`, `reconcile_review_findings`) may still use the v1 shape. All public MCP-registered tools return the v2 envelope. Check `schema_version == 2` to confirm.

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
  agent-handoff-mcp --workspace-root <repo> event \
    --event-kind decision \
    --session "<agent>-<task-slug>" \
    --decision "cdx_slice_complete_<work_ref>_<slug>" \
    --rationale "## Changes\n..."
  ```

- `next-actions`
- `blocker`
- `test`
- `review-findings`
- `review-runs`
- `handoff-close-check`
- `task`
- `export`
- `import`
- `archive`
- `audit-decisions`
- `artifacts`
- `handoff-search`

Orchestration subcommands (`orchestrator-start`, `worker-start`, `dispatch`, `orchestrator-cycle`, `worker-events`, `list-backends`, `metrics`, etc.) are served exclusively by `agent-orchestrator-mcp`. See [`agent-orchestrator-mcp.md`](agent-orchestrator-mcp.md).

**CLI surface note:** `agent-handoff-mcp` CLI is ledger-only. It exposes `serve-stdio`, `serve-http`, `doctor`, `render-handoff`, the ledger MCP tools as CLI wrappers, and two CLI-only artifact variants (`artifact-list`, `artifact-terms`). All orchestration and lane-management commands are exclusively on `agent-orchestrator-mcp`.

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

**Trigger:** The worker-daemon review pipeline (`worker_daemon.py`) completes a review turn that produces one or more new findings. This hook fires in the daemon review path only; it does not fire on every individual `review_findings(operation="record")` MCP tool call.

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

**Side effects allowed:** `CURRENT_TASK.json` and `DASHBOARD.txt` regeneration. `render_handoff(kind="current_task")` runs for the new active task so the machine-readable snapshot and human-readable mirror reflect the switch immediately.

**Required durable output:** Updated machine-readable `CURRENT_TASK.json` plus human-readable `DASHBOARD.txt` for the new task. If regeneration fails, the failure must be surfaced in the `switch_task` response, not silently swallowed.

**Operator visibility:** `DASHBOARD.txt` must be current after `switch_task` returns, and `CURRENT_TASK.json` must remain parseable machine state. If either file appears stale, run `render_handoff(kind="current_task", task_ref=<new-task>)` explicitly.

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
