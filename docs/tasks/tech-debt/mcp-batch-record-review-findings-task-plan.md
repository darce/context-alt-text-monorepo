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
- Existing tests pass; new unit tests cover atomic write, partial-failure reporting, and
  FTS trigger correctness.

## Proposed Solution

Add `batch_record_review_findings` to `core.py` alongside `record_review_finding`. The
implementation re-uses the existing upsert SQL; only the outer loop and the
`_write_current_task_md_for_task` flush move to a batcher level.

### Input Shape

```python
BatchFindingItem = TypedDict("BatchFindingItem", {
    "finding_id": str,
    "severity": str,        # "HIGH" | "MEDIUM" | "LOW"
    "file_path": str,
    "description": str,
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
{ "ok": false, "error": "Item 3 (finding_id='H-OCI-31'): Invalid severity. Valid: HIGH, LOW, MEDIUM" }
```

### Implementation Notes

- `batch_record_review_findings` validates all items before opening the transaction
  (fail-fast on shape errors avoids partial writes).
- The single SQLite `with conn:` block wraps all upserts; FTS triggers fire inside the
  same transaction as the main upsert (existing trigger definitions require no change).
- `_write_current_task_md_for_task` is called once after all rows are committed.
- If `findings` is empty the call succeeds with `written: 0`.
- Maximum batch size is 100 items; larger batches return `ok: false` to prevent runaway
  context payloads.

## Files to Change

| File | Function / Target | What Changes |
|------|-------------------|--------------|
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | new `batch_record_review_findings()` | Add function alongside `record_review_finding` |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | module-level alias + `TOOL_DESCRIPTIONS` + `mcp.add_tool` list | Export and register the new tool |
| `packages/agent-handoff-mcp/tests/` | new `test_batch_record_review_findings.py` | Unit tests (see below) |

## Related Files

| File | Note |
| ---- | ---- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | `record_review_finding` at line 2402 is the single-item reference implementation |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | `TOOL_DESCRIPTIONS` dict at line 90; `mcp.add_tool` list at line 950 |
| `docs/agentic/contracts/agent-handoff-mcp.md` | Contract doc that will need a new section for the batch tool |

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [ ] Add `BatchFindingItem` TypedDict and `batch_record_review_findings` stub (raises
      `NotImplementedError`) to `core.py`.
- [ ] Add tool description entry in `TOOL_DESCRIPTIONS` dict in `api.py`.
- [ ] Add alias `batch_record_review_findings = core.batch_record_review_findings` and
      register it via `mcp.add_tool` in `api.py`.
- [ ] Add empty test file `tests/test_batch_record_review_findings.py` with `@pytest.mark.skip` scaffolds.
- [ ] Verify `make check` passes on the stub (no import errors, no lint failures).

## Phase 1: Implementation

- [ ] Implement pre-validation loop in `batch_record_review_findings`: check each item's
      severity before opening any transaction.
- [ ] Implement single-transaction upsert loop (re-use the existing INSERT ... ON CONFLICT
      SQL from `record_review_finding`).
- [ ] Call `_write_current_task_md_for_task` once after the transaction commits.
- [ ] Return per-item `action` field (`"inserted"` or `"updated"`) and `"reopened": true`
      where applicable.
- [ ] Enforce 100-item maximum; return `ok: false` with a clear error on overflow.

## Phase 2: Tests

- [ ] Empty `findings=[]` returns `ok: true, written: 0`.
- [ ] Single item round-trip matches `record_review_finding` output shape.
- [ ] All 12 items written atomically; FTS table row count matches after insert.
- [ ] Invalid severity on item 3 rejects entire batch before any write; DB row count
      unchanged.
- [ ] Duplicate `finding_id` in the same batch (second occurrence upserts/reopens first).
- [ ] Batch of 101 items returns `ok: false` without writing.
- [ ] `actor` and `task_ref` forwarding mirrors single-item behavior (agent, branch,
      commit_sha columns correct).
- [ ] `_write_current_task_md_for_task` called exactly once per batch call, regardless of
      batch size (mock/patch to verify call count).

## Phase 3: Contract Doc

- [ ] Add `batch_record_review_findings` entry to
      `docs/agentic/contracts/agent-handoff-mcp.md` with input/output shape and the
      100-item limit note.
- [ ] Add a usage note in `CLAUDE.md` under "MCP Handoff Contract (MANDATORY)": prefer
      `batch_record_review_findings` when logging >= 3 findings in one review pass to
      avoid redundant file rewrites.

## Success Criteria

- [ ] `make check` passes in `packages/agent-handoff-mcp/`.
- [ ] All new tests pass.
- [ ] `record_review_finding` (single) continues to work; no existing tests regress.
- [ ] A review agent can log 12 findings in one MCP call and receive 12 per-item results.
