# AHMCP-26. Pre-Composition Write Guidance

> **Metadata**:
>
> - **Date**: 2026-04-12
> - **Author**: Claude Sonnet 4.6 (retroactive)
> - **Project**: agent-handoff-mcp
> - **Task ID**: AHMCP-26
> - **Target Branch**: `feature/ahmcp-26`
> - **Merged**: `c880d7c2` on `main`

---

## Objective

Surface write constraints (char limits, required sections) to agents before a call is made — in tool schema Field descriptions and in the `get_handoff_state` response envelope — so structural rejections are caught client-side rather than after a server round-trip.

## Problem Statement

Agents calling `close_slice` or `record_event` with rationale that was too long or missing required sections received a rejection only after the call reached the server. The `guard-rationale-size.py` PreToolUse hook checked byte size but not section structure. Char limits and the required-section list were not visible in the tool descriptions that agents read at registration time. This produced avoidable reject-rewrite round-trips.

## Constraints

- All changes additive; no existing tool signatures or DB schema altered.
- `SLICE_COMPLETE_REQUIRED_SECTIONS` must become a single canonical constant — no duplication across modules.
- The hook must block before the call reaches the server for structural errors, not after.

## Proposed Solution

Three coordinated changes:

**A. Embed constraints in tool Field descriptions** — update `RecordDecisionEvent.rationale` and `close_slice.rationale` Field descriptions to include char limits and a pointer to the required-section template. Agents read these at schema registration; no additional call required.

**B. Upgrade `guard-rationale-size.py`** — extend the PreToolUse hook to detect missing required sections (parsed from `SLICE_COMPLETE_REQUIRED_SECTIONS`) before the call reaches the server. Exits non-zero on structural violation, not just size overflow.

**C. Surface `limits.write` in `get_handoff_state`** — extend the `limits` envelope key to include `write: {rationale_soft_chars, rationale_hard_chars, slice_complete_hard_chars, slice_complete_required_sections}` so any agent that reads state at startup already has the write constraints without needing to inspect tool descriptions.

## Files Changed

| File | Change |
|---|---|
| `src/agent_handoff_mcp/shared_primitives.py` | Add `SLICE_COMPLETE_REQUIRED_SECTIONS` constant as canonical source |
| `src/agent_handoff_mcp/_shared.py` | Re-export `SLICE_COMPLETE_REQUIRED_SECTIONS` |
| `src/agent_handoff_mcp/api.py` | Extend Field descriptions for `RecordDecisionEvent.rationale` and `close_slice.rationale` |
| `src/agent_handoff_mcp/handoff_state.py` | Add `limits.write` block to `get_handoff_state` response |
| `tests/test_handoff_state.py` | Assert `limits.write` present and correct |
| `scripts/hooks/guard-rationale-size.py` | Extend: block on missing required sections before size check |

## Verification

- `cd packages/agent-handoff-mcp && make test-handoff` — `test_handoff_state.py` asserts `limits.write` keys present
- `get_handoff_state(sections="identity")` response includes `limits.write.slice_complete_required_sections`
- PreToolUse hook called with `close_slice` rationale missing `## Verification` section → exits non-zero before the call reaches the server
