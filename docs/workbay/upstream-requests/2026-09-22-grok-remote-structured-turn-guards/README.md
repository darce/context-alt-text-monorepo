# Upstream request: grok-remote structured-turn guards

**Requested by:** context-alt-text-monorepo · **Date:** 2026-09-22
**Status:** proposed
**Blocks:** nothing today; reduces wasted grok-remote passes on diagnosis-heavy lanes (FIR512-2 preprocess burned 6 passes to land 1).

## Summary

`grok-remote` passes fail in two shapes that the orchestrator currently treats
as terminal instead of recoverable. Both are visible from `debug.log` and the
launcher receipt without any model-side change. Handoff decision `13465`
(`claude_grok_preprocess_stall_root_cause_20260922`) holds the per-pass
evidence.

| ID | Shape | Evidence |
| --- | --- | --- |
| G1 | **No-tool first turn.** Under `--json-schema`, grok-4.6 emits a schema-valid placeholder (`"Starting ..."`, `tests_run: []`) on model call 1 with `has_tool_call=false`, the CLI ends the turn, and the pass is quarantined as `guidance_without_attempt`. | `remote-exec-preprocess-b0u2k_53` (1 call), `lane-exec-preprocess-92tf37nb` (quarantined), review twin `pt56xfzx` (1 call, `findings: []`). Brief wording does not prevent it; see the 15+ instances logged in the consumer's memory notes since 2026-09-08. |
| G2 | **Fixed max-turns exhaustion.** When the model does work, `api.py` pins `--max-turns` to a fixed bound per effort (`bounds["max_turns"]` = 20/25/40). Diagnosis-heavy briefs hit `cancellationCategory: max_turns_reached` at 118k–192k context with **no commit**; the stdout remainder (267 KB) then fails salvage and the pass yields a 0-byte `turn.patch`. | `remote-exec-preprocess-codvijhj` (40 turns, 0 B), `lxaxh406` (25 turns, 78 B), `f6jpji7t` (20 turns, 0 B). The only landed pass (`7zdu4k0z`, 28.7 KB) carried a finished diagnosis in the brief, so it needed few turns. |

## Requested mechanism

1. **Auto-continue on a no-tool first turn (G1).** When the first model call
   returns structured output with `has_tool_call=false` and `changed_files=[]`,
   re-enter the turn once with the fixed nudge "your previous message was a
   placeholder; the first action must be a tool call" instead of terminating.
   Cap at one continuation; record `first_turn_nudged=true` in the receipt so
   the consumer can tell a nudged pass from a clean one.
2. **Derive `max_turns` from `token_budget` (G2).** Replace the fixed
   per-effort bound with `max(bound, token_budget // per_turn_estimate)`, using
   the same table that already derives the wall clock from `token_budget`
   (100k → 750 s, 300k → 1800 s). A 300k budget should not stop at 25 turns.
3. **Commit-before-cancel (G2).** On `max_turns_reached` with a dirty sandbox,
   run the lane's `test_cmd`; if green, land a `wip(offload): <lane> checkpoint`
   commit and report `self_verify_inconclusive` (resumable) rather than
   discarding the tree. Today the dirty tree is thrown away with the pass.
4. **Salvage size guard.** Truncate the stdout remainder to the last
   schema-valid JSON object before salvage; a 267 KB remainder is a parse
   failure, not a diagnosis.

## Consumer-side workaround in force

- Coordinator does the diagnosis locally and ships a 1–3 file brief that
  states the concrete approach and an explicit commit step.
- Re-pin lane row and manifest together before dispatch (row/manifest pin
  mismatch refused runtime p6).
- `test_cmd` uses relative paths only (host-absolute `--basetemp` refused
  preprocess p4).
- `token_budget` ≥ 120000 (the router floor refuses smaller budgets in ~1.4 s).

## Out of scope

Model choice. The consumer's policy keeps grok-4.6 for implementation lanes;
this request makes the harness tolerate the model's first-turn and long-turn
behaviour rather than replace the model.
