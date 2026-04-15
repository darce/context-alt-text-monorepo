# AHMCP-29. switch_task: archived_previous Flag in Response

> **Metadata**:
>
> - **Date**: 2026-04-14
> - **Author**: Daniel Arcé (retroactive)
> - **Project**: agent-handoff-mcp
> - **Task ID**: AHMCP-29
> - **Target Branch**: `feature/ahmcp-29`

---

## Objective

Fix `archived_previous` always returning `False` in the `switch_task` response, and assert both `archived_previous` and `previous_task_ref` in the existing regression test.

## Problem Statement

`switch_task` had `archived_previous = False` and `previous_task_ref = None` initialized before the archive block, and both fields were already present in the response envelope. However, the assignment `archived_previous = True` was missing from inside the archive code path, so the flag was always `False` in the response even when an archive actually occurred. Callers (e.g., `agent-orchestrator-mcp`'s `switch_task` tool) could not reliably distinguish "previous task was archived" from "no previous task existed." The existing regression test `test_switch_task_returns_full_mutation_shape` exercised the response shape but had no assertions for these two fields.

## Constraints

- One-line fix inside the archive block; no logic restructuring.
- Response envelope shape unchanged — both keys were already present.

## Current State Analysis

- `import_export.py` line ~932: `archived_previous = False` initialized before the `if current is not None:` block.
- Inside that block (line ~958): the INSERT to `task_archives` completed but `archived_previous = True` was never set.
- Response envelope (lines ~1006–1007) already referenced both `archived_previous` and `previous_task_ref`.
- `test_switch_task_returns_full_mutation_shape` asserted mutation shape but skipped the two provenance fields.

## Proposed Solution

1. Add `archived_previous = True` after the `task_archives` INSERT inside the `if current is not None:` block.
2. Add assertions for `archived_previous is True` and `previous_task_ref == "task-a"` to the existing regression test.

## Verification Strategy

- `cd packages/agent-handoff-mcp && make test-handoff` — 497 tests pass.
- Regression test `test_switch_task_returns_full_mutation_shape` directly asserts the fixed fields.

## Slice Delivery

### Slice 1: Fix archived_previous Assignment and Test Assertions

**Goal**: `archived_previous` is `True` in the response when an archive occurred; regression test covers both fields.

Changes:

- `src/agent_handoff_mcp/import_export.py`: Add `archived_previous = True` inside the archive block after the `task_archives` INSERT.
- `tests/test_import_export_regressions.py`: Add `assert switched["archived_previous"] is True` and `assert switched["previous_task_ref"] == "task-a"` to `test_switch_task_returns_full_mutation_shape`.

Proof:

- `make test-handoff` — 497 passed
- `test_switch_task_returns_full_mutation_shape` passes with the new assertions

## Handoff Reference

- MCP task ref: `AHMCP-29`
- Feature commit: `41f288d9` (`feat(ahmcp-29): add archived_previous flag to switch_task response`)
- Merge commit: `befbdce8` (`merge(ahmcp-29): add archived_previous flag to switch_task response`)
- No MCP handoff task was created; this plan is retroactive.

---

## Consolidated Checklist

### Checklist for Slice 1: archived_previous Fix

- [x] `archived_previous = True` added inside the archive block in `import_export.py`
- [x] `test_switch_task_returns_full_mutation_shape` asserts `archived_previous is True`
- [x] `test_switch_task_returns_full_mutation_shape` asserts `previous_task_ref == "task-a"`
- [x] `make test-handoff` — 497 passed

## Success Criteria

- [x] `switch_task` response has `archived_previous: true` when a previous task was archived
- [x] `switch_task` response has `previous_task_ref` set to the outgoing task ref
- [x] All 497 existing tests pass
