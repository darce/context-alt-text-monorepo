# MCP Batch Record Review Findings

## Problem Statement

When an agent performs a branch review that produces multiple findings, it must call
`record_review_finding` once per finding. There is no batch equivalent. This causes two
observable failure modes:

1. Agents that attempt to pass a list of findings inside a single `record_review_finding`
   call receive a rejection (`ok: false`) because the payload shape does not match the
   expected single-finding signature. They then re-log each finding sequentially, wasting
   token budget and producing verbose intermediate output such as:
   > "The MCP recorder rejected the batched write format, so I'm re-logging the findings
   > one at a time with the exact payload shape it expects."

2. A review session with 10-15 findings incurs 10-15 full MCP round-trips, each of which
   triggers a `_write_current_task_md_for_task` rewrite. At 15 findings this is 15
   redundant file rewrites that could be deferred to a single flush at the end.

## Success Criteria

- A new `batch_record_review_findings` MCP tool exists that accepts a list of findings in
  one call and writes them atomically (single SQLite transaction, single
  `_write_current_task_md_for_task` flush at end).
- All existing `record_review_finding` semantics are preserved for each item: stable
  `finding_id`, ON CONFLICT upsert, reopen counters, FTS sync via existing triggers.
- The tool returns a per-item result array so callers can see which findings were inserted
  vs reopened without making a follow-up list query.
- `record_review_finding` (single) continues to work unchanged; nothing is removed.
- Existing tests pass; new unit tests cover atomic write, batch-level failure reporting, and
  FTS trigger correctness.

## Proposed Solution

Add `batch_record_review_findings` to `review_findings.py` alongside `record_review_finding`, then re-export it through `core.py` and register it via the existing `ToolEntry` path in `api.py`. The implementation re-uses the existing upsert SQL; only the outer loop and the `_write_current_task_md_for_task` flush move to a batcher level.

### Input Shape

```python
BatchFindingItem = TypedDict("BatchFindingItem", {
    "finding_id": str,
    "severity": str,        # "high" | "medium" | "low" — matches the existing single-item contract
    "file_path": str,
    "description": str,
    "review_mode": str | None,  # optional: "branch" | "release_audit"; preserved on upsert
    "details": ReviewFindingDetails | None,  # optional: line_start, line_end, fix
})

def batch_record_review_findings(
    session: str,
    findings: list[BatchFindingItem],
    actor: WriteActor | None = None,
    task_ref: str | None = None,
) -> str: ...
```

### Return Shape

```json
{
  "ok": true,
  "task_ref": "...",
  "written": 12,
  "results": [
    { "finding_id": "H-OCI-28", "action": "inserted" },
    { "finding_id": "H-OCI-29", "action": "updated", "reopened": true }
  ]
}
```

If any item has an invalid severity the entire batch is rejected before any writes with:

```json
{ "ok": false, "error": "Item 3 (finding_id='H-OCI-31'): Invalid severity. Valid: high, low, medium" }
```

### Implementation Notes

- `batch_record_review_findings` validates all items before opening the transaction
  (fail-fast on shape errors avoids partial writes). If validation fails the entire batch
  is rejected; no rows are written.
- The single SQLite `with conn:` block wraps all upserts atomically; FTS triggers fire
  inside the same transaction as the main upsert (existing trigger definitions require no
  change).
- Each item's `review_mode` is forwarded to `_normalize_review_mode` exactly like
  `record_review_finding`; ON CONFLICT upsert preserves existing `review_mode` when
  `None` is passed, matching the single-item behavior.
- `_write_current_task_md_for_task` is called once after all rows are committed.
- If `findings` is empty the call succeeds with `written: 0`.
- Maximum batch size is 100 items; larger batches return `ok: false` to prevent runaway
  context payloads.

## Files to Change

| File | Function / Target | What Changes |
|------|-------------------|--------------|
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py` | new `batch_record_review_findings()` alongside `record_review_finding` | Domain implementation lives here |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | re-export `batch_record_review_findings` in the `from .review_findings import (...)` block | Re-export only; no domain logic |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | module-level alias + `TOOL_DESCRIPTIONS` entry + `ToolEntry` registration | Export and register via existing `ToolEntry` path |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` | add `batch_record_review_findings` to imports and `__all__` | Required for public package API and review_runner caller |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_runner.py` | `_record_findings()` | Switch from per-item `record_review_finding` loop to single `batch_record_review_findings` call |
| `packages/agent-handoff-mcp/tests/` | new `test_batch_record_review_findings.py` | Unit tests (see below) |

## Related Files

| File | Note |
| ---- | ---- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py` | `record_review_finding` is the single-item reference implementation |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | thin re-export layer; `batch_record_review_findings` re-exported here alongside other review_findings symbols |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | `TOOL_DESCRIPTIONS` dict and `ToolEntry` registration list |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_runner.py` | `_record_findings()` is the real caller that loops over findings today; adoption target for batch tool |
| `docs/agentic/contracts/agent-handoff-mcp.md` | Contract doc that will need a new section for the batch tool |

---

# Consolidated Checklist

## Phase 1: Implementation

- [x] Add `BatchFindingItem` TypedDict to `review_findings.py`.
- [x] Implement `batch_record_review_findings` in `review_findings.py`: pre-validation
      loop (severity + review_mode per item), single-transaction upsert loop re-using the
      existing INSERT ... ON CONFLICT SQL, single `_write_current_task_md_for_task` flush
      after commit.
- [x] Return per-item `action` field (`"inserted"` or `"updated"`) and `"reopened": true`
      where applicable.
- [x] Enforce 100-item maximum; return `ok: false` with a clear error on overflow.
- [x] Re-export `batch_record_review_findings` through `core.py` in the
      `from .review_findings import (...)` block.
- [x] Add module-level alias, `TOOL_DESCRIPTIONS` entry, and `ToolEntry` registration in
      `api.py` (same pattern as `record_review_finding`).
- [x] Add `batch_record_review_findings` to `__init__.py` imports and `__all__`.
- [x] Switch `_record_findings()` in `orchestration/review_runner.py` from per-item loop
      to a single `batch_record_review_findings` call.
- [x] Create `packages/agent-handoff-mcp/tests/test_batch_record_review_findings.py` with
      working tests (no `@pytest.mark.skip`). Verify `make check` passes.

## Phase 2: Tests

- [x] Empty `findings=[]` returns `ok: true, written: 0`.
- [x] Single item round-trip matches `record_review_finding` output shape.
- [x] All 12 items written atomically; FTS table row count matches after insert.
- [x] Invalid severity on item 3 rejects entire batch before any write; DB row count
      unchanged.
- [x] Duplicate `finding_id` in the same batch (second occurrence upserts/reopens first).
- [x] Batch of 101 items returns `ok: false` without writing.
- [x] `actor` and `task_ref` forwarding mirrors single-item behavior (agent, branch,
      commit_sha columns correct).
- [x] `review_mode` per-item is preserved exactly like `record_review_finding`; upsert
      preserves existing `review_mode` when `None` is passed.
- [x] `_write_current_task_md_for_task` called exactly once per batch call, regardless of
      batch size (mock/patch to verify call count).
- [x] `review_runner._record_findings` smoke test confirms N findings are written with one
      batch call.

## Phase 3: Contract Doc

- [x] Add `batch_record_review_findings` entry to
      `docs/agentic/contracts/agent-handoff-mcp.md` with input/output shape and the
      100-item limit note.
- [x] Add a usage note in `CLAUDE.md` under "MCP Handoff Contract (MANDATORY)": prefer
      `batch_record_review_findings` when logging >= 3 findings in one review pass to
      avoid redundant file rewrites.

## Success Criteria

- [x] `make check` passes in `packages/agent-handoff-mcp/`.
- [x] All new tests pass.
- [x] `record_review_finding` (single) continues to work; no existing tests regress.
- [x] A review agent can log 12 findings in one MCP call and receive 12 per-item results.
- [x] `_record_findings()` in `review_runner.py` uses `batch_record_review_findings`;
      the per-item loop is gone.
- [x] `review_mode` values written through the batch path are queryable via
      `list_review_findings(review_mode=...)` exactly like the single-item path.
