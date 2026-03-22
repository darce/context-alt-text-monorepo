# Structured-Memory Search Over Canonical Handoff Tables

## Problem Statement

The artifact sidecar introduced in the orchestration-context-retrieval task covers large,
unstructured evidence blobs (logs, HTTP payloads, grep output, docs). What it does *not* cover
is structured retrieval over the canonical handoff tables themselves: decisions, review findings,
blocker history, next-action descriptions, lane messages, and worker report summaries.

Today an agent that wants to know "what decisions were made about the retry policy?" must either
read the full `get_handoff_state` snapshot (which truncates history) or call `list_review_findings`
/ `list_worker_reports` and do keyword matching client-side. Neither path scales as task history
grows. This task adds BM25 full-text search over the *structured* handoff tables so agents can
retrieve the most relevant decisions, findings, blockers, and actions by keyword without reading
the full table.

## Workflow Principles

- Extend the existing handoff database; do not add a third database.
- Search must be scope-first: narrow by `task_ref`, `lane_id`, and record type before text ranking.
- Search results must include enough metadata (record type, id, status) for callers to act on them.
- Keep the schema additive: the new FTS5 shadow tables must coexist with the existing handoff.db
  schema without affecting existing queries.
- FTS5 availability is already validated by `run_doctor()`; rely on that gate.

## Terminology

- **Handoff record**: A row in one of the canonical handoff tables (decisions, review_findings,
  actions, blockers, lane_messages, worker_reports).
- **Structured search**: Full-text search scoped to a specific record type and task, returning
  record IDs plus ranked snippets.
- **Search index**: FTS5 virtual tables in `handoff.db` that mirror the text bodies from
  canonical tables and are kept current via shadow-insert triggers.

## Current State Analysis

- `handoff.db` contains tables: `handoff_state`, `actions`, `blockers`, `decisions`,
  `review_findings`, `lane_messages`, `lane_briefs`, `worker_reports`, `test_results`,
  `plan_cursors`, `worktree_lanes`, `exports`.
- Each table has one or more text columns (e.g. `decisions.decision`, `review_findings.description`,
  `blockers.description`, `actions.action`, `lane_messages.message`).
- There is no FTS5 index over these columns today.
- `search_artifacts` in the sidecar covers unstructured blobs; there is no equivalent for handoff
  records.
- The closest existing primitive is `get_handoff_state(verbose=True)`, which returns everything
  but is not searchable.

## Proposed Solution

Add FTS5 virtual tables to `handoff.db` for each searchable record type, maintain them via
insert/update triggers, and expose a `search_handoff` MCP tool plus a CLI subcommand. The initial
implementation should cover decisions, review_findings, blockers, and actions — the four record
types most commonly queried for context during worker sessions. Lane messages and worker reports
can follow in a second pass once trigger maintenance is validated.

The search tool returns ranked hits with `record_type`, `record_id`, `task_ref`, `lane_id`, and a
compact snippet; callers can fetch the full record with the existing `get_review_finding`,
`record_decision`, etc. tools if they need it.

## Schema Extension

```sql
-- Decisions FTS
CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
    body,
    record_id UNINDEXED,
    task_ref  UNINDEXED,
    lane_id   UNINDEXED,
    tokenize='porter unicode61'
);

-- Findings FTS
CREATE VIRTUAL TABLE IF NOT EXISTS findings_fts USING fts5(
    body,
    record_id UNINDEXED,
    task_ref  UNINDEXED,
    lane_id   UNINDEXED,
    tokenize='porter unicode61'
);

-- Blockers FTS
CREATE VIRTUAL TABLE IF NOT EXISTS blockers_fts USING fts5(
    body,
    record_id UNINDEXED,
    task_ref  UNINDEXED,
    lane_id   UNINDEXED,
    tokenize='porter unicode61'
);

-- Actions FTS
CREATE VIRTUAL TABLE IF NOT EXISTS actions_fts USING fts5(
    body,
    record_id UNINDEXED,
    task_ref  UNINDEXED,
    lane_id   UNINDEXED,
    tokenize='porter unicode61'
);
```

Triggers keep each FTS table in sync on insert and update against the canonical table. A
backfill migration runs at startup when the FTS tables are first created, so existing records are
searchable immediately.

## Proposed Tool Surface

```python
def search_handoff(
    queries: list[str],
    task_ref: str | None = None,
    lane_id: str | None = None,
    record_types: list[str] | None = None,   # ["decision", "finding", "blocker", "action"], default: all
    limit: int = 20,
) -> str:
    """Search canonical handoff records by keyword with optional scope filters.

    Returns ranked results with record_type, record_id, task_ref, lane_id, status,
    and a compact highlighted snippet for each match.
    """
```

## Functions to Change

| File | Target | Change |
|------|--------|--------|
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/schema.py` | new or extended module | Add FTS5 table definitions and backfill migration for decisions, findings, blockers, actions. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/adapters.py` | schema migration | Ensure handoff.db migration applies new FTS tables on `configure_runtime` if missing. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | after `purge_artifacts` | Add `search_handoff` tool implementation. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | tool export map | Export `search_handoff` in MCP API surface and TOOL_DESCRIPTIONS. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` | search subcommand | Add `search` or `handoff-search` CLI subcommand. |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` | exports | Export `search_handoff`. |
| `packages/agent-handoff-mcp/tests/test_search_handoff.py` | new test module | Unit + integration tests for FTS5 indexing, backfill, scoped search, and snippet rendering. |
| `docs/agentic/contracts/agent-handoff-mcp.md` | structured search section | Document `search_handoff` surface, FTS5 shadow table semantics, and trigger maintenance rules. |

## Related Files

| File | Note |
|------|------|
| [packages/agent-handoff-mcp/src/agent_handoff_mcp/artifact_index.py](../../../packages/agent-handoff-mcp/src/agent_handoff_mcp/artifact_index.py) | Reference implementation pattern for FTS5 chunking and scoped search; adapt trigger approach from here. |
| [docs/tasks/8.0/orchestration-context-retrieval-task-plan.md](orchestration-context-retrieval-task-plan.md) | Parent task that introduced the artifact sidecar; this task is its structured-table complement. |
| [packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py](../../../packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py) | Existing tool implementations to follow as patterns. |

## Lane Decomposition

This task does not require multi-agent decomposition. A single `mcp-search` lane covers all
schema, tool, test, and doc changes. The work is sequentially dependent (schema before tools
before tests) and the owned file set is entirely within `packages/agent-handoff-mcp/`.

## Consolidated Checklist

### Phase 0: Scaffolding

- [ ] Add FTS5 virtual table definitions for decisions, findings, blockers, actions to the
      existing handoff.db schema migration path.
- [ ] Add backfill logic that populates FTS tables from canonical rows when first created.
- [ ] Add stub `search_handoff` tool (returns empty results) so MCP API surface is visible.
- [ ] Add test scaffolds covering schema idempotency and empty-result roundtrip.

### Phase 1: Index Maintenance

- [ ] Implement insert triggers for each FTS table (decisions, findings, blockers, actions).
- [ ] Implement update triggers to keep FTS bodies in sync on record edits.
- [ ] Verify existing `record_decision`, `record_review_finding`, `report_blocker`, and
      `update_next_actions` write paths populate FTS tables correctly via trigger.
- [ ] Ensure backfill runs at startup via `configure_runtime` migration guard.

### Phase 2: Search Implementation

- [ ] Implement `search_handoff` with multi-query OR join, scope filters (task_ref, lane_id,
      record_types), BM25 ranking, and compact snippets.
- [ ] Return `record_type`, `record_id`, `task_ref`, `lane_id`, `status`, and `snippet` per hit.
- [ ] Add CLI `handoff-search` subcommand with `--query`, `--task-ref`, `--lane-id`,
      `--record-types`, `--limit`.

### Phase 3: Tests

- [ ] Unit test FTS5 trigger correctness: insert a decision, verify it appears in FTS; update
      it, verify FTS body updates.
- [ ] Unit test scoped search: results respect task_ref and lane_id filters.
- [ ] Integration test `search_handoff` tool against a real handoff.db with seeded decisions and
      findings.
- [ ] Test backfill: pre-seed rows before FTS tables exist, apply migration, verify rows are
      searchable.

### Phase 4: Docs and Contract Update

- [ ] Update `docs/agentic/contracts/agent-handoff-mcp.md` with `search_handoff` surface,
      FTS5 shadow table semantics, trigger maintenance rules, and scope filter behaviour.
- [ ] Update `CLAUDE.md` or `BOOTSTRAP.md` if search tooling changes any operator command
      surfaces.

## Success Criteria

- [ ] An agent can search decisions, findings, blockers, and actions with `search_handoff` and
      receive ranked, scoped results without reading the full task snapshot.
- [ ] FTS5 index stays consistent with canonical table state across insert, update, and
      `switch_task` / `archive_task_state` lifecycle operations.
- [ ] All existing handoff tests continue to pass after schema extension.
- [ ] `run_doctor()` reports FTS5 availability and structured-index status.
