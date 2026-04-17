# E17-11 Catalogue — Singleton Sentinel Sites

> Artifact for [E17-11 task plan](./E17-11-multi-active-task-singleton-writes-hotfix-task-plan.md) Slice 1.
> Generated: 2026-04-17 against `feature/e17-11` @ 5078b368.
> Paths are `packages/agent-handoff-mcp/src/agent_handoff_mcp/*` unless noted.

## Table A — Sentinel reads and upserts

Classification legend: **read_active_as_pointer** (treats `id = 1` as "the active task" — must be removed). **write_upsert** (inserts new row with `id = 1` — sentinel eviction pattern, remove). **write_demote_promote** (temporarily demotes prior sentinel then re-promotes just-written task_ref — remove). **read_specific_row_by_id** (legitimate `id = 1 AND task_ref = ?` guard — keep or simplify).

| File:line | Snippet | Classification | Owning slice |
|---|---|---|---|
| `handoff_state.py:63` | `UPDATE handoff_state SET id = NULL WHERE id = 1` (demote before INSERT) | write_demote_promote | 2f |
| `handoff_state.py:69` | `VALUES (1, ?, ?, ?, ...)` (set_handoff_state INSERT) | write_upsert | 2f |
| `handoff_state.py:164` | `UPDATE handoff_state SET id = NULL WHERE id = 1 AND task_ref <> ?` (post-update demote) | write_demote_promote | 2f |
| `handoff_state.py:168` | `UPDATE handoff_state SET id = 1 WHERE task_ref = ?` (post-update promote) | write_demote_promote | 2f |
| `import_export.py:156` | `SELECT revision FROM handoff_state WHERE id = 1` (`_set_import_active_state` revision probe) | read_active_as_pointer | 2f |
| `import_export.py:162` | `VALUES (1, ?, ?, ...)` (`_set_import_active_state` INSERT) | write_upsert | 2f |
| `import_export.py:176` | `UPDATE handoff_state SET ... WHERE id = 1` (`_set_import_active_state` UPDATE) | write_upsert | 2f |
| `import_export.py:665` | `SELECT task_ref FROM handoff_state WHERE id = 1` (archive `clear_active_if_matches`) | read_active_as_pointer | 2g |
| `import_export.py:667` | `DELETE FROM handoff_state WHERE id = 1` (archive clear branch) | write_upsert (delete of sentinel) | 2g |
| `import_export.py:799` | `SELECT * FROM handoff_state WHERE id = 1 AND task_ref = ?` (`update_task_status` probe) | read_specific_row_by_id (drop `id = 1` conjunct) | 2g |
| `import_export.py:890` | `SELECT task_ref FROM handoff_state WHERE id = 1` (post-archive CURRENT_TASK regen) | read_active_as_pointer | 2g |
| `import_export.py:949` | `SELECT task_ref, objective, revision FROM handoff_state WHERE id = 1` (switch_task prior-active read) | read_active_as_pointer | 2a |
| `import_export.py:953` | `SELECT * FROM handoff_state WHERE id = 1` (switch_task already-active return path) | read_active_as_pointer | 2a |
| `import_export.py:1022` | `INSERT ... VALUES (1, ?, ?, ?, ?, ?, ...)` (switch_task INSERT branch) | write_upsert | 2a |
| `import_export.py:1036` | `UPDATE ... WHERE id = 1` (switch_task UPDATE branch) | write_upsert | 2a |
| `import_export.py:1049` | `SELECT * FROM handoff_state WHERE id = 1` (switch_task post-write return) | read_active_as_pointer | 2a |
| `shared_write_context.py:451` | `SELECT task_ref, target_branch, target_worktree_path FROM handoff_state WHERE id = 1` (guard fallback) | read_active_as_pointer | 3a |
| `shared_write_context.py:527` | `SELECT updated_by, updated_branch, updated_commit_sha FROM handoff_state WHERE id = 1` (actor drift probe) | read_active_as_pointer | 3a |
| `shared_primitives.py:343` | `_get_current_handoff_row` → `SELECT * FROM handoff_state WHERE id = 1` | read_active_as_pointer | 2e (dead-code removal) |
| `shared_primitives.py:352` | `ORDER BY CASE WHEN id = 1 THEN 0 ELSE 1 END, updated_at DESC, task_ref ASC` (`_resolve_workspace_handoff_row` tie-break) | read_active_as_pointer | 3a (drop sentinel tie-break) |
| `shared_primitives.py:399–402` | bootstrap branch: "no `target_worktree_path` rows → fall back to `id = 1`" | read_active_as_pointer | 3a |
| `current_task_rendering.py:148` | activity-anchor CTE: `FROM handoff_state WHERE id = 1` | read_active_as_pointer | 2b |
| `current_task_rendering.py:201` | cross-task `active_state` CTE: `WHERE id = 1` | read_active_as_pointer | 2g |
| `current_task_rendering.py:319` | `_collect_task_snapshot` sentinel probe: `SELECT * FROM handoff_state WHERE id = 1` | read_active_as_pointer | 2g |
| `dashboard_rendering.py:122` | `SELECT task_ref FROM handoff_state WHERE id = 1` (alt active_row read) | read_active_as_pointer | 2c |
| `dashboard_rendering.py:542` | `SELECT task_ref, target_branch, target_worktree_path FROM handoff_state WHERE id = 1` (dashboard header) | read_active_as_pointer | 2c |
| `review_findings.py:54` | `_write_current_task_md_for_active_context`: `SELECT task_ref FROM handoff_state WHERE id = 1` | read_active_as_pointer | 2g |
| `review_findings.py:1699` | `done_with_open_findings` probe: `SELECT task_ref, status FROM handoff_state WHERE id = 1` | read_active_as_pointer | 2g |
| `review_findings.py:1876` | `record_review_run` implicit fallback: `SELECT task_ref FROM handoff_state WHERE id = 1` | read_active_as_pointer | 2d |
| `decisions.py:663` | `SELECT task_ref FROM handoff_state WHERE id = 1` (audit_decision_ids active-task fallback) | read_active_as_pointer | 2g (same pattern as review_findings 2g readers) |
| `api.py:1727` | `SELECT task_ref FROM handoff_state WHERE id = 1` (API-surface implicit fallback) | read_active_as_pointer | 2d or 2g (triage during implementation) |

Schema definitions at `shared_schema.py:106/925` (`id INTEGER UNIQUE CHECK (id IS NULL OR id = 1)`) and the migration-only hit at `shared_schema.py:949` (`CASE WHEN id = 1 THEN 1 ELSE NULL END`) are **kept**. Per the Greenfield Decision in the plan, `id` stays as an ignored nullable legacy column; no schema change.

**Two hits not previously enumerated by the plan's Catalogue-A preview:** `decisions.py:663` and `api.py:1727`. Both follow the same "active-task-when-no-task_ref-passed" pattern as `review_findings.py:1876`. Covered by the existing 2d/2g ownership; no new slice required.

## Table B — Implicit-task write handlers

Handlers that derive `task_ref` implicitly (from the sentinel or from the guard's side effects) rather than requiring it as a parameter. Each must be redesigned to require explicit `task_ref` or workspace-derived resolution.

| Handler | Location | Current implicit source | Remediation | Owning slice |
|---|---|---|---|---|
| `record_review_run` | `review_findings.py:1873–1878` | `collect_target_context_warnings` runs first, then falls back to `SELECT task_ref WHERE id = 1`. No `_resolve_task_ref` anywhere. | Require explicit `task_ref`; return error naming caller when absent. No sentinel fallback. | 2d |
| `switch_task` | `import_export.py:948–949` | Guard runs before any task resolution; subsequent read is the sentinel. | Rewrite to `WHERE task_ref = ?` insert-or-update; drop archiving and drop sentinel read. | 2a |
| `_set_import_active_state` | `import_export.py:156–176` | Revision probe + INSERT/UPDATE all target `id = 1`. | INSERT `VALUES (NULL, ?, ...)`; UPDATE `WHERE task_ref = ?`; revision probe by `task_ref`. | 2f |
| `set_handoff_state` (eviction pattern) | `handoff_state.py:62–69, 162–170` | Demote prior sentinel → INSERT `VALUES (1, ...)` → re-promote. | INSERT `VALUES (NULL, ?, ...)`; delete demote/promote; keep the task_ref-aware guard path at `:121–127` which already passes `task_ref=`. | 2f |
| `update_task_status` | `import_export.py:797–801` | Guard runs without `task_ref`; then probe uses `id = 1 AND task_ref = ?`. Passing `task_ref` is present but redundant because of the `id = 1` conjunct. | Drop `id = 1` conjunct; thread `task_ref` into guard. | 2g (sentinel read) + 3b (caller ordering) |
| `archive_task_state` (`clear_active_if_matches` branch) | `import_export.py:665–667` | Sentinel read-then-delete. | `DELETE FROM handoff_state WHERE task_ref = ?` for the just-archived task_ref. | 2g |
| Post-archive CURRENT_TASK regen | `import_export.py:890–895` | Picks "the sentinel's task_ref". | Iterate all remaining active rows (or require caller-supplied `task_ref`, or delete block if no-op is acceptable). | 2g |
| `_write_current_task_md_for_active_context` | `review_findings.py:45–58` | Sentinel read to anchor CURRENT_TASK.json regeneration. | Regenerate against the `fallback_task_ref` / just-written finding's `task_ref` directly. | 2g |
| `done_with_open_findings` check | `review_findings.py:1699–1703` | Reads sentinel to evaluate "is task done?" | Read row for the specific `task_ref` under review via `_get_handoff_row_for_task`. | 2g |
| `audit_decision_ids` active-task fallback | `decisions.py:663` | Same pattern: pick sentinel task_ref when none passed. | Require explicit `task_ref` or workspace-resolve. | 2g |
| `api.py:1727` active-task implicit fallback | `api.py:1727` | Same pattern. | Same. | 2d/2g (triage during implementation; per RG-015 no silent fallbacks). |

## Table C — Caller ordering

Every handler that calls both `collect_target_context_warnings(` and `_resolve_task_ref(`. "before" = bug (guard runs against sentinel). "after" = correct (guard sees resolved task_ref).

| Handler | Guard call | Resolve call | Order | Owning slice |
|---|---|---|---|---|
| `record_event` (decisions) | `decisions.py:110` | `decisions.py:100` | after ✓ | — |
| `audit_decision_ids` write path | `decisions.py:176` | `decisions.py:174` | after ✓ | — |
| `update_decision_ref` | `decisions.py:361` | `decisions.py:359` | after ✓ | — |
| `close_slice` | `decisions.py:424` | `decisions.py:422` | after ✓ | — |
| `review_findings.record_review_finding` | `review_findings.py:248` | `review_findings.py:246` | after ✓ | — |
| `review_findings.batch_record` | `review_findings.py:402` | `review_findings.py:400` | after ✓ | — |
| `review_findings.update_review_finding` | `review_findings.py:852` | `review_findings.py:881` | **before ✗** | 3b |
| `review_findings.repair_provenance` | `review_findings.py:1191` | `review_findings.py:1216` | **before ✗** | 3b |
| `review_findings.record_review_run` | `review_findings.py:1873` | — (sentinel fallback at `:1876`, no `_resolve_task_ref`) | n/a — implicit-task handler | 2d |
| `import_export.export_handoff_state` | `import_export.py:642` | `import_export.py:632` | after ✓ | — |
| `import_export.update_task_status` | `import_export.py:797` | — (no `_resolve_task_ref`; relies on caller-passed `task_ref`) | guard called without `task_ref=` → treat as inverted | 3b |
| `import_export.switch_task` | `import_export.py:948` | — (no `_resolve_task_ref`; derives from sentinel) | n/a — implicit-task handler | 2a (rewrite) |
| `handoff_state.set_handoff_state` | `handoff_state.py:121` (passes `task_ref=`) | resolved inline from arg (`task_ref` arg of function) | after ✓ (guard accepts task_ref kwarg) | — |

**Bug sites confirmed:** `review_findings.py:852/881`, `review_findings.py:1191/1216`. `import_export.py:797` is guard-without-task_ref and relies on the sentinel via the `:798–801` probe — it counts as inverted for the purposes of Slice 3b's regression test even though no `_resolve_task_ref` call exists.

**Not visited by Table C (no guard at all):** every other `_resolve_task_ref` call site (`touched_files.py`, `verified_tests.py`, `core.py`, read paths in `decisions.py`, etc.) — resolve-only, no guard, no ordering concern.

## Summary — ownership rollup

| Slice | Sites owned |
|---|---|
| 2a (switch_task rewrite) | `import_export.py:948–1049` |
| 2b (activity-anchor CTE) | `current_task_rendering.py:148` |
| 2c (dashboard header) | `dashboard_rendering.py:122, 542` |
| 2d (record_review_run explicit) | `review_findings.py:1873–1876`, `api.py:1727` (triage) |
| 2e (dead helpers) | `shared_primitives.py:342–343` (`_get_current_handoff_row`) |
| 2f (set_handoff_state + _set_import_active_state) | `handoff_state.py:62–170`, `import_export.py:147–176` |
| 2g (remaining sentinel readers) | `current_task_rendering.py:201, 319`; `review_findings.py:45–58, 1699–1703`; `import_export.py:665–667, 798–801, 890–895`; `decisions.py:663` |
| 3a (guard + workspace helper) | `shared_write_context.py:451, 527`; `shared_primitives.py:352, 399–402`; `__init__.py:58/64` (new `UnresolvedTaskContextError` re-export) |
| 3b (caller ordering) | `review_findings.py:852/881, 1191/1216`; `import_export.py:797` |
| 3c (drift hook) | hook-side (covered in Slice 3c proper) |

No slice is under- or over-owned. Plan's Catalogue-A preview was complete; this audit adds two same-pattern sites (`decisions.py:663`, `api.py:1727`) already covered by 2d/2g ownership.
