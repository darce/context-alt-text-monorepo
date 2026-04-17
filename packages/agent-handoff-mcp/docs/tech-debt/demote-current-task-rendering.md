# Demote `CURRENT_TASK.json` Rendering to On-Demand

> **Metadata**
>
> - **Date**: 2026-04-17
> - **Project**: `agent-handoff-mcp`
> - **Status**: Tech-debt note (no implementation slice yet)
> - **Related rule**: [`CLAUDE.md` § MCP Handoff](../../../../CLAUDE.md) ("agents with live MCP access should use `get_handoff_state`/`load_session` instead")
> - **Related tool**: `mcp__agent-handoff-mcp__render_handoff` (`kind="current_task"`)
> - **Related hook**: [scripts/hooks/regenerate-task-views.sh](../../../../scripts/hooks/regenerate-task-views.sh) (already scoped to `--kind dashboard` only)

## Problem

`CURRENT_TASK.json` is rendered as an implicit side-effect of the majority of handoff write paths, even though:

1. **The PostToolUse hook already only writes `DASHBOARD.txt`.** The shell hook at [regenerate-task-views.sh:56](../../../../scripts/hooks/regenerate-task-views.sh) invokes `render-handoff --kind dashboard` and nothing else.
2. **CLAUDE.md already instructs agents with MCP access to prefer `get_handoff_state` / `load_session`** and treat `CURRENT_TASK.json` as a last-resort stale read for cold-start fallback.
3. **DASHBOARD.txt is the operator-facing cross-task view** — human inspection does not require `CURRENT_TASK.json`.

Despite this, the Python layer writes `CURRENT_TASK.json` on every major MCP mutation via at least the following call sites:

- `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py:776` — `close_slice` writes on every slice close.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py` — 6 sites in record / batch_record / update / merge paths (lines 298, 482, 721, 1344, 1792, plus `_write_current_task_md_for_active_context`).
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/import_export.py` — 3 sites across export payload shaping and import completion (lines 817, 890, 1055).
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py:703` — expected-state diff compare during close-check.

The result is disk churn, `git status` noise (the file is gitignored but changes timestamp constantly), and wasted work on every write for an artifact that nearly no agent reads in normal flow.

## Value Assessment

Narrow remaining value of `CURRENT_TASK.json`:

- **Cold-start fallback** when both MCP and the Python API are unavailable (rare, but documented).
- **Human inspection** of a machine-readable current-task snapshot.
- **Test fixture assertions** on the render shape.

None of these require per-write regeneration. All can be satisfied by on-demand rendering at `make context`, `make task-finish`, or explicit `render_handoff(kind="current_task")`.

## Proposed Change

1. **Remove implicit `_write_current_task_md_*` calls** from the following call sites:
   - `core.py` `close_slice` (retain the in-memory state mutation; drop the file write).
   - `review_findings.py` — all six call sites in record / batch_record / update / merge paths.
   - `import_export.py` — retain on import completion only if the import operation is meant to materialize a cold-start artifact; drop from export payload shaping.
   - `decisions.py` — retain for expected-state diff compare only; do not write to disk.
2. **Keep `_render_current_task_json`** as a pure function; only `render_handoff(kind="current_task")` writes to disk.
3. **Update `make context`** to call `render_handoff(kind="current_task")` alongside its existing dashboard render so cold-start agents always see a fresh file after a context check.
4. **Update `make task-finish`** to emit a final `CURRENT_TASK.json` snapshot atomically with archive so the archived-state snapshot has a durable companion.
5. **Update tests** that currently assert implicit side-effect writes. Shift those assertions to the explicit render path.
6. **Document the demotion** in `docs/agentic/contracts/agent-handoff-mcp.md` so the file's lifecycle is explicit (written by explicit render / context / task-finish only).

## Proof Criteria

- No handoff write path (`record_event`, `set_handoff_state`, `update_task_status`, `close_slice`, `review_findings` record/update/merge, `import_handoff_state`, `export_handoff_state`) touches `CURRENT_TASK.json` on disk.
- `make context` produces a current `CURRENT_TASK.json` with the latest state.
- `render_handoff(kind="current_task")` continues to write the same payload as today.
- `make test-handoff` + `make test-orchestrator` remain green after test fixtures are updated.
- `CURRENT_TASK.json` timestamp only changes on explicit render, `make context`, or `make task-finish`.

## Risks

- **Cold-start agents without MCP access relying on a fresh file after an implicit write.** Mitigation: document the contract change; CLAUDE.md already flags `CURRENT_TASK.json` as last-resort stale.
- **Test flakes from removed side effects.** Mitigation: audit every test currently asserting on `_write_current_task_md_*` and migrate them to explicit render calls.
- **Import/export round-trip semantics.** Import currently materializes `CURRENT_TASK.json` so the imported task becomes visible to a cold-start reader; keep this explicit if downstream callers rely on it.

## Trigger to Revive

This is pure hygiene; no external trigger required. Land when Slice 4 hygiene work resumes or when a broader render-path refactor is scheduled.
