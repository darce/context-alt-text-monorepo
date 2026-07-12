# Upstream request: first-class cross-session continuation packets

- **Date**: 2026-07-12
- **Repos**: darce/mcp-workbay-handoff (primary), darce/mcp-workbay-orchestrator, codebase-graph-mcp (secondary)
- **Requested by**: operator (daniel) via claude-fable-5 session `planrev-uxui-20260712-01`
- **Severity**: workflow friction — concurrent agents corrupt each other's session-continuation state

## Problem

Cross-session continuation ("what the next cold-start agent must know") is currently carried in
ad-hoc `NEXT_SESSION_PROMPT.md` files. With 2+ concurrent agents these collide: parallel tracks
overwrite or fork the file (observed 2026-07-12: two divergent NEXT_SESSION_PROMPT files, one
committed mid-session by another agent while a second was being written). The content also rots —
it duplicates state the handoff DB already owns (task status, findings, decisions) alongside
genuinely novel content (orchestration recipes, verified anchors, direction ranking).

## What already works (validated 2026-07-12 on mcp-workbay-handoff 0.2.x)

- `artifacts(operation='record'|'search')` — task-scoped, labeled, term-indexed text packets.
  Collision-free by construction (`task_ref` + `source_label` upsert). We now store per-track
  continuation packets under a standing `ORCH-CONTINUITY` row (`source_kind='continuation'`)
  and shared offload/orchestration recipes (`source_kind='orchestration_guidelines'`).
- `load_session` — already has `last_injected_compaction_id` + `include_context_refresh`.
- `compaction(operation='record')` — transcript → StructuredSummary per task.
- `semantic_reinjection_packet` — embedding-anchored retrieval; local ONNX model configured via
  `.workbay/embedding.env` (`WORKBAY_REINJECT_SEMANTIC=1`).

## Gaps / asks

1. **Typed `continuation` surface** on the handoff MCP: `continuation(operation='save'|'load')`
   that (a) upserts a per-`task_ref` (or per-lane) packet with schema'd sections
   (done_do_not_redo / next_actions / verified_anchors / gotchas), (b) is returned by
   `load_session` automatically when present (like compactions), and (c) records
   supersedes-lineage so stale packets age out. Today we emulate this with `artifacts`, but
   nothing injects it at session start — the agent must know to search.
2. **Session-start injection hook**: a documented SessionStart hook recipe (or `make context`
   extension) that calls `load_session` + newest continuation packet + `compaction(get_latest)`
   and prints them — so cold starts need zero tribal knowledge.
3. **Embedding deps in the uv-tool venv**: `semantic_reinjection_packet` failed with
   `No module named 'numpy'` — the `mcp-workbay-handoff` uv tool install does not ship the
   embedding extra even when `embedding.env` is configured. Ask: make the embedding extra a
   default dependency, or fail with an actionable install hint. (Local fix applied:
   `uv pip install --python ~/.local/share/uv/tools/mcp-workbay-handoff/bin/python numpy onnxruntime tokenizers`.)
4. **Embedding backfill**: rows written while the provider was broken stay unembedded
   (`skip_reason: no_embeddings`); expose a backfill op so historical decisions/artifacts become
   retrievable without rewrites.
5. **codebase-graph persistence**: `index_repository(persistence=true)` returned
   `artifact_present: false` and wrote no `.codebase-memory/graph.db.zst` in this repo — either a
   bug or an undocumented precondition. A working persisted graph artifact would let cold starts
   bootstrap the codemap instead of re-indexing (~1 min each session, per worktree).
6. **resolve-op root-dirt false positive** (re-filed for visibility): `review_findings(resolve)`
   reports `pending_uncommitted` for all findings whenever the ROOT worktree has ANY untracked
   file — including other agents' lane configs — even when invoked from a clean worktree cwd.
   Multi-agent repos always have unrelated root dirt; dirt-check should scope to the finding's
   `file_path`s (or the fix commit), not the whole tree.

## Local state to migrate once upstream lands

Standing handoff row `ORCH-CONTINUITY` holds: `continuation-e21-uxui-track-20260712`,
`offload-orchestration-recipe-v1`. Retire `NEXT_SESSION_PROMPT.md` files after the injection
hook exists; until then they remain read-only historical inputs.
