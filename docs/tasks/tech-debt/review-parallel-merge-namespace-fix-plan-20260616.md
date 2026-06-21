# Task Plan — review-parallel scratch-namespace collision & drift fix

> - **Date**: 2026-06-16 EST
> - **Author**: Claude Opus 4.8
> - **Project**: workstate tooling (upstream: `darce/mcp-workstate-handoff` package + `workstate-system` plugin `review-parallel` skill)
> - **Task ID**: `MAINT-REVPARALLEL-FIX-20260616`
> - **Target Branch**: `feature/maint-revparallel-fix-20260616`
> - **Review Coverage Target**: 2

> **Boundary note:** the implementation targets live in the **workstate repos, which are out of bounds in this monorepo checkout** (Plugin Boundary Rule). This plan is the durable spec + upstream ask. The generated effective skill copy under `.workstate/generated/**` is NOT a durable edit target — it reverts on re-sync; the durable home for the skill change is the `workstate-system` plugin source.

---

## MAINT-REVPARALLEL-FIX-20260616. review-parallel scratch-namespace collision & drift fix

## Implementation Status — SHIPPED / overtaken by events (2026-06-21)

> This plan was authored 2026-06-16. The package + skill layers it specifies **shipped upstream afterward** (workstate v0.4.2, 2026-06-18). Verified against installed `mcp-workstate-handoff 0.13.2` and the effective `workstate-system` `review-parallel` skill. The plan is retained as the historical design spec; slice bodies below are **not** re-edited.

| Slice | Status | Evidence (installed) |
| --- | --- | --- |
| S1 skill round-scoping + preflight + teardown | SHIPPED | `review-parallel/SKILL.md`: round-unique `<coordinator>-REV-<round>-<letter>`, round token recorded in the opening decision, commit-prefix token preferred (steps 2/5); preflight `total_matching==0` + re-token on collision; excluded-reviewer `wontfix` teardown (Recovery) |
| S2 `superseded` CHECK migration | SHIPPED | `enums.py:92` `FindingStatus.SUPERSEDED`; `shared_schema.py:288,1349` CHECK; idempotent `_migrate_review_findings_superseded_status` v15→v16 (probes before rebuild) |
| S3 terminal semantics | SHIPPED | `review_findings_queries.py:238` sort rank `'superseded' THEN 3` |
| S4 merge no-reopen + disposition preserve | SHIPPED | disposition-preservation `ON CONFLICT` branch in `_batch_record_review_findings_in_conn` (`review_findings_recording.py:805`) |
| S5 `merge(retire_sources=True)` atomic | SHIPPED | `merge_review_findings(retire_sources=True)` (`recording.py:718`); `_retire_merged_source_rows` sets `superseded` idempotently in the **same `_get_db_connection()` block** as the source SELECT + in-connection upsert (`recording.py:747–821`) |
| S6 reconcile live drift | **DONE 2026-06-21** | `reconcile_review_findings(apply=true)` retired 8 eligible `MAINT-WPAC-HARDEN-20260614-*REV-*` rows (incl. id-1515 / `REV-B-1`) to `superseded`; both scratch refs now report 0 open |

**Disposition of plan-analyze findings (PA-1..PA-17, verdict REVISE_FIRST 2026-06-17).** The triage critiqued an *unwritten* spec; the implementation has since landed, so the blocking items are resolved by shipped code rather than by re-specifying:

- **PA-1** (retire UPDATE "same transaction" mechanically impossible): resolved — shipped `merge_review_findings` performs the source SELECT, the in-connection upsert (`_batch_record_review_findings_in_conn`), and `_retire_merged_source_rows` under **one** connection/transaction.
- **PA-3 / PA-8** ("materially differs" ambiguity; preserve-vs-skip either/or): resolved — shipped disposition-preservation `ON CONFLICT` branch is the single concrete behavior.
- **PA-4** (round-token format/generation underspecified + self-contradictory): resolved — skill specifies a concrete generator (commit-prefix token), preflight emptiness, and re-token on collision, explicitly best-effort (not a concurrency lock).
- **PA-5** (excluded/crashed reviewer not delivered): resolved — skill Recovery flips every open row under an excluded ref to `wontfix` with "excluded and not merged" notes.
- **PA-6 / PA-9** (Slice 6 reconcile mechanism unspecified; interim→canonical transition): resolved — `reconcile_review_findings` exposes `checks.reviewer_scratch_drift` with `eligible_for_retirement` + `apply=true` retiring via the merge-managed `superseded` path (used for S6 above).
- **PA-10** (migration idempotency/needed-detection): resolved — `_migrate_review_findings_superseded_status` probes before rebuilding.
- **PA-2** (CURRENT_TASK `superseded` bucket = data loss): the shipped package does **not** bucket `superseded` into the active `current_task` render (terminal/audit-only, excluded from open/deferred/resolved surfaces). Accepted as the shipped decision.
- **PA-7 / PA-11..PA-17** (parity-test invariant, teardown-timing wording, duplication, stale line anchors, sr-007/rg-009 citations): doc-quality items on a now-historical spec; superseded by this status section.

## Objective

Eliminate the cross-round finding-id collision and source/coordinator status drift produced when `/review-parallel` runs more than once against the same coordinator task. After the fix, a second parallel-review round cannot accumulate or overwrite a prior round's rows, and no scratch reviewer task retains `open` rows that diverge from the coordinator's triaged status.

## Problem Statement

`/review-parallel` fans out reviewers under deterministic scratch task_refs `<coordinator>-REV-<letter>`, then merges their findings under the coordinator. Three layers combine into silent corruption and drift (all confirmed against installed `workstate_handoff_mcp` + skill source, and observed live on `MAINT-WPAC-HARDEN-20260614`):

1. **Deterministic refs reused across rounds.** The `-REV-<letter>` suffix is a pure function of coordinator + reviewer index, so re-running on the same coordinator reuses the same scratch ref; rows from multiple rounds accumulate under one ref (`…-REV-A` held 3 sessions).
2. **Merge never cleans the source.** `merge_review_findings` (`review_findings_recording.py:351-360`) is a read-only `SELECT` over sources that re-records into the target and touches no source row, so sources stay `open` while coordinator copies resolve — drift is **per-round**, not just cross-round.
3. **`batch_record` upsert corrupts on id reuse.** `ON CONFLICT(task_ref,finding_id) DO UPDATE` (`:239-265`) overwrites `description`/`status`→`open` and nulls `resolved_at`/`resolution_notes`, but does **not** reset `resolved_on_branch_at_commit/_ref/_at_ts`, `verification_evidence`, `integrated_at_*`. Reusing an id for a different finding yields new content with stale resolution provenance (observed: `…-REV-B/REV-B-1` id 1515 — CON-5 description, `40685c1d` dead-SCSS evidence).

The current state passes the pre-merge gate (the gate audits only the coordinator task_ref), so the corruption is invisible to `handoff_close_check` and rots the audit trail.

## Constraints

- **Boundary:** implementation lands in `darce/mcp-workstate-handoff` (package) and the `workstate-system` plugin (skill source); neither is editable from this checkout. This plan is the spec/ask, not the implementation.
- **Greenfield does not apply to this package's schema.** Unlike the monorepo's `001_identity_schema.py`, `review_findings` has a hard `CHECK` constraint and a real migration lane (`_migrate_finding_lifecycle_states`); a new status value requires a table rebuild, not an in-place edit.
- **Preserve invariants:** `merged_from` provenance; reviewer rows retained as an audit trail (retired, not deleted); cross-harness MCP-state parity (Claude / Codex+Copilot `run_structured_turn` / Grok `task` / degradation fallback); merge resumability/idempotency.
- **Pre-merge gate:** `handoff_close_check` filters strictly on `status == open`, so any terminal status (incl. a new `superseded`) is excluded for free — **no close-check change is permitted or needed.**

## Workflow Principles

- **Status-flip, never delete, for teardown.** Retire scratch rows by moving them to a terminal status; never `prune_working_rows`/delete (destroys the audit trail).
- **`superseded` is merge-managed.** It is set only inside the merge-retire transaction, never via a direct `update`.
- **Skill layer cannot satisfy the post-merge invariant alone.** Round-scoping + preflight fix ref reuse (layer 1) but not merge's failure to clean sources (layer 2); a status-flip teardown (or package `retire_sources`) is therefore required, not optional.
- **Record the combined `review_run` before teardown**, so coverage aggregation and reviewer sub-run audit rows are stable.

## Terminology

- **Coordinator task_ref**: the task under which the merged finding set + verdict + combined review_run live.
- **Scratch / reviewer ref**: the per-reviewer task_ref a reviewer writes under before merge.
- **Round token**: a per-run identifier making scratch refs unique across repeated reviews of one coordinator.
- **Retire / teardown**: moving a scratch row to a terminal status (`superseded`, or `wontfix` as the interim) after merge so it no longer counts as `open`.

## Current State Analysis

- **Works:** single-round `/review-parallel`; merge `merged_from` provenance; `target ∉ sources` guard; close-check/dashboard open-counts (strict `status='open'`).
- **Broken / drifting:** repeated rounds on one coordinator collide on finding ids and overwrite content; scratch sources keep `open` rows after merge; reused ids carry stale resolution anchors.
- **Misleading:** the skill text "reviewer source rows remain intact / additive, not destructive" (`SKILL.md:84,115`) reads as a feature but is the drift mechanism; a corrupted row's `verification_evidence` describes a different finding than its `description`.

## Target Outcome

`/review-parallel` uses **round-unique** scratch refs, **preflight-asserts** them empty, and after recording the combined review_run **retires every scratch ref this round** (merged and excluded) to a terminal status. The package gains a `superseded` finding status, a `merge(retire_sources=True)` that retires merged sources atomically and idempotently, a merge upsert that does not reopen terminal target rows, and a corruption-safe `batch_record` that clears stale resolution anchors only when a finding is re-identified. Existing drift is reconciled and the id-1515 corruption repaired.

## Context Loading

- Skill source: `workstate-system` plugin `skills/review-parallel/SKILL.md` (effective copy for reference: `.workstate/generated/plugins/workstate-system/effective/claude/skills/review-parallel/SKILL.md`).
- Package: `workstate_handoff_mcp/review_findings_recording.py` (`merge_review_findings`, `batch_record_review_findings`), `enums.py` (`FindingStatus`), `shared_schema.py` (`review_findings` CHECK at `:270` + migration recreate `:1296`; anchor columns `:283-290`), `review_findings_queries.py` (list ordering `:236`; open-count `:405-410`), `review_findings_updates.py` (`_validate` `:752`, `_apply_finding_update` `:626-646`), `current_task_rendering.py` (buckets `:423-433`; collectors `:206,:281`), `decisions.py` (close-check open filter `:729`), `import_export.py` (`archive_task_state` prune `:1082,:1098-1113`).
- Handoff/MCP state: `MAINT-WPAC-HARDEN-20260614` (live drift sample) + its `*-REV-A`/`*-REV-B` scratch refs; corrupted row `…-REV-B/REV-B-1` id 1515.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `review_findings.status` domain | handoff package | CHECK `IN (open,fixed,wontfix,deferred,resolved_on_branch,integrated)` | add `superseded` (CHECK + enum + migration) | yes — table rebuild for existing DBs | migration test; `superseded` write succeeds |
| `merge_review_findings` signature | handoff package | `(session, source_task_refs, target, actor)` | add `retire_sources: bool = True` | yes — default True changes merge behavior; `False` = legacy | merge marks sources superseded; `False` reproduces additive |
| `review-parallel` skill contract | workstate-system plugin | `<coord>-REV-<letter>` + additive merge | round-scoped refs + required teardown | n/a (instruction) | 2-round dry-run: disjoint refs, 0 open sources post-merge |
| cross-vendor parity | orchestrator package | `test_cross_vendor_subagent_equivalence` | extend for round refs + teardown | no | parity test green across backends |

## Proposed Solution

Two coordinated layers. **Skill layer (ships first, works today):** round-unique refs + preflight + a required status-flip teardown (interim `wontfix`). **Package layer (upstream, sequenced behind a CHECK migration):** add `superseded`, make merge retire sources + not reopen terminal targets, and clear stale anchors only on re-identification. Then a one-shot data reconcile. Detailed mechanics and the corrected (adversarially hardened) decisions live in the slices below.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| skill | plugin `skills/review-parallel/SKILL.md` | round-unique refs (steps 2-5, `:68,:100,:109,:113-114`); preflight; required teardown step (after step 6); reconcile Goal `:41`/Convergence `:115`; new red flags; known-limitation note |
| tooling/schema | `shared_schema.py:270,:1296` | add `superseded` to `status` CHECK (base + migration recreate); table-rebuild forward migration mirroring `_migrate_finding_lifecycle_states` |
| tooling/enum | `enums.py:82` | add `FindingStatus.SUPERSEDED` |
| tooling | `review_findings_queries.py:236` | add `superseded` (and `resolved_on_branch`/`integrated`) terminal sort rank |
| tooling | `current_task_rendering.py:423-433` | decide + wire the `superseded` CURRENT_TASK bucket (own bucket vs intentionally hidden) |
| tooling | `review_findings_recording.py` merge + `:239-265` | `retire_sources` param; preserve terminal target status on conflict; gate anchor-null on material change; resume no-op |
| tooling | `review_findings_updates.py:752` | reject direct `status='superseded'` ("merge-managed") |
| tooling/test | orchestrator `test_cross_vendor_subagent_equivalence` | extend for round-scoped refs + teardown parity |
| data | handoff DB | one-shot reconcile of `*-REV-*` drift + targeted id-1515 anchor repair |

## Related Files

| File | Note |
| --- | --- |
| `decisions.py:729` | close-check open filter — confirm NO change (strict `==open`) |
| `review_findings_queries.py:405-410` | integrity open-count — confirm NO change (`='open'`) |
| `import_export.py:1082,:1098-1113` | `archive_task_state` — must NOT be used for teardown (no retire without destructive prune) |
| `shared_primitives.py:103` | `REVIEW_FINDING_STATUSES` derives from enum — auto-admits `superseded` to validators (drives R6 guard) |

## Verification Strategy

- Deterministic tests:
  - `pytest` (handoff package) — migration adds `superseded`; superseded write succeeds; merge `retire_sources` supersedes merged sources; resume re-run is a no-op; merge does not reopen terminal target rows; anchors cleared only on material change; direct `status='superseded'` update rejected; `superseded` excluded from open-count + sorts terminal.
  - cross-vendor: `test_cross_vendor_subagent_equivalence` extended.
- Contract/fixture verification:
  - skill dry-run: two consecutive `/review-parallel` rounds on one coordinator → disjoint scratch refs; round-2 preflight passes; after each merge+teardown every scratch ref (incl. an excluded reviewer's) has 0 `open`.
- Manual verification:
  - reconcile sweep leaves `MAINT-WPAC-HARDEN-20260614` `*-REV-*` refs with 0 open diverging rows; id 1515 anchors nulled.

## Slice Delivery

### Slice 1: Skill round-scoping + preflight + required teardown (ships today)

**Goal**: Make `/review-parallel` round-safe and self-cleaning with no package change.

Changes:
- `<coord>-REV-<letter>` → `<coord>-REV-<round>-<letter>`; round token chosen once at step 2, recorded in the open decision (auditable/resume-stable); update all ref mentions.
- Step-2 preflight: assert each scratch ref `total_matching==0`; on non-empty pick a fresh token.
- New teardown step **after** the combined review_run/verdict: status-flip every scratch ref this round — merged **and** excluded/crashed — to `wontfix` (interim) with `resolution_notes="merged into <coord> @ <session>"`. Forbid `archive_task_state` (does not retire) and `prune_working_rows` (deletes).
- Reconcile Goal/Convergence wording to "retired terminal, provenance intact"; add red flags (ref-already-populated; post-merge open source); add the two-concurrent-coordinators known-limitation note.

Proof:
- Two-round dry-run on a throwaway coordinator: disjoint refs; preflight passes round 2; 0 open sources post-merge including an excluded reviewer.

### Slice 2: `superseded` status — CHECK migration (gating dependency)

**Goal**: Make a terminal `superseded` status writable on real DBs.

Changes:
- Extend `review_findings.status` CHECK at `shared_schema.py:270` and `:1296`; forward migration rebuilds the table (RENAME→CREATE-with-extended-CHECK→copy→drop) mirroring `_migrate_finding_lifecycle_states`.
- Add `FindingStatus.SUPERSEDED` (`enums.py:82`).

Proof:
- migration test on a pre-existing DB; `UPDATE … SET status='superseded'` succeeds (no `IntegrityError`).

### Slice 3: `superseded` terminal semantics in queries/renderers

**Goal**: `superseded` behaves as terminal everywhere it surfaces.

Changes:
- list ordering CASE (`review_findings_queries.py:236`): terminal sort rank for `superseded` (+ unhandled `resolved_on_branch`/`integrated`).
- CURRENT_TASK bucket (`current_task_rendering.py:423-433`): decide own-bucket vs hidden; wire + document.
- Confirm (test) close-check open-count + `_collect_all_open_findings` exclude `superseded` (no code change expected).

Proof:
- `superseded` rows sort after open/active; excluded from open surfaces; CURRENT_TASK render is deterministic.

### Slice 4: Merge/upsert correctness (no-reopen + gated anchor reset + guard)

**Goal**: Stop terminal-row reopen on re-merge and stop stale-anchor corruption.

Changes:
- On conflict, preserve terminal target status (or skip terminal target rows) so a merge re-run/resume does not reopen resolved coordinator rows.
- Add the 7 anchor columns to the `DO UPDATE` NULL set **only when the incoming finding materially differs** (`file_path`/`description` changed); same-finding reopen keeps anchors.
- Re-identify guard: if existing row terminal and incoming differs, reject ("use a new finding_id / `allow_reidentify=true`").
- Reject direct `status='superseded'` update in `_validate` (`:752`).

Proof:
- re-merge does not reopen terminal targets; anchors cleared only on material change; reject-direct-superseded; reidentify-guard tests.

### Slice 5: `merge(retire_sources=True)`

**Goal**: Merge retires its merged sources atomically and idempotently.

Changes:
- `merge_review_findings(retire_sources: bool = True)`: after inner `batch_record` succeeds, same transaction `UPDATE … SET status='superseded', resolution_notes=…, updated_at=now WHERE task_ref IN (sources) AND id IN (<merged ids>)`. `False` = legacy. Re-superseding an already-superseded source = no-op. `merged_from_json` untouched.
- Skill (follow-up to Slice 1): prefer `retire_sources=true`; skill then only status-flips excluded refs.

Proof:
- merge marks merged sources `superseded`; resume idempotent; `False` reproduces additive.

### Slice 6: Reconcile existing drift + id-1515 repair

> **DONE 2026-06-21** — executed via the shipped path: `reconcile_review_findings(task_ref="MAINT-WPAC-HARDEN-20260614", apply=true)` retired all 8 eligible `*-REV-*` drift rows (`REV-A`: 1404/1405/1484; `REV-B`: 1406/1485/1515/1526/1527) to `superseded` (each had a terminal coordinator copy). Both scratch refs now report 0 open. Note: the shipped reconcile **retires** the rows; it does not NULL the stale resolution anchors on id-1515 — those persist on the now-terminal (`superseded`) audit row and are excluded from every open surface, which satisfies "0 open diverging rows". Anchor-nulling was never shipped and is not pursued (would re-introduce spec-beyond-code; raw-SQL anchor edits are forbidden by rg-018).

**Goal**: Clean the live drift this bug already produced.

Changes:
- One-shot reconcile (`reconcile_review_findings` mode or `make` helper): for every `*-REV-*` ref, retire `open` rows whose coordinator copy is terminal (`wontfix` now / `superseded` post-Slice 2).
- Targeted repair of `…-REV-B/REV-B-1` id 1515 and the 3 open `…-REV-A` rows: `NULL` `verification_evidence, resolved_on_branch_at_commit, resolved_on_branch_ref, resolved_on_branch_at_ts, integrated_at_commit, integrated_at_ref, integrated_at_ts`.

Proof:
- `MAINT-WPAC-HARDEN-20260614` `*-REV-*` refs have 0 open diverging rows; id 1515 anchors nulled.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed whether external dependency context requires `ctx7`.
- [ ] Recorded boundary ownership (handoff package + workstate-system plugin are upstream/out-of-bounds here).

### Checklist for Slice 1: Skill round-scoping + preflight + required teardown

- [ ] Round-unique `<coord>-REV-<round>-<letter>` across all ref mentions; round token in step-2 open decision.
- [ ] Step-2 preflight emptiness assertion.
- [ ] Teardown step after the combined review_run; status-flip merged + excluded refs; archive/prune forbidden.
- [ ] Goal/Convergence wording reconciled; red flags + known-limitation note added.
- [ ] Two-round dry-run proof captured.

### Checklist for Slice 2: `superseded` CHECK migration

- [ ] CHECK extended at `shared_schema.py:270` and `:1296`; table-rebuild forward migration.
- [ ] `FindingStatus.SUPERSEDED` added.
- [ ] Migration test on pre-existing DB; superseded write succeeds.

### Checklist for Slice 3: `superseded` terminal semantics

- [ ] List ordering terminal rank for superseded (+ resolved_on_branch/integrated).
- [ ] CURRENT_TASK bucket decision wired + documented.
- [ ] Test: superseded excluded from open surfaces; no close-check change.

### Checklist for Slice 4: Merge/upsert correctness

- [ ] Conflict preserves terminal target status (no reopen on re-merge).
- [ ] Anchor-null gated on material change; same-finding reopen keeps anchors.
- [ ] Re-identify guard; reject direct `status='superseded'` update.
- [ ] Tests for each.

### Checklist for Slice 5: `merge(retire_sources=True)`

- [ ] `retire_sources` param supersedes merged sources in-transaction; `False`=legacy; resume no-op.
- [ ] Skill follow-up prefers `retire_sources=true`.
- [ ] Tests for retire + resume idempotency.

### Checklist for Slice 6: Reconcile + id-1515 repair

- [ ] One-shot reconcile of `*-REV-*` drift.
- [ ] id-1515 + REV-A anchors nulled.
- [ ] Verified 0 open diverging rows on the sample coordinator.

## Review Readiness

- [ ] No boundary-touching change (status domain, merge signature) left without migration + test evidence.
- [ ] Runtime-parity: cross-vendor equivalence test extended; skill dry-run proof recorded.
- [ ] Handoff decision records the change, verification, and the status-domain/merge-signature contract implications.

## Stretch Goals

- [ ] `B-conflict-key` composite `(task_ref, session, finding_id)` dedup — only if the two-concurrent-coordinators case must be structurally closed (schema/migration cost; de-recommended).

## Success Criteria

- [ ] A second `/review-parallel` round on the same coordinator produces disjoint scratch refs, collides with nothing, and overwrites no prior finding.
- [ ] After every merge, no scratch ref (merged or excluded) retains `open` rows; retired rows keep content + `merged_from` provenance.
- [ ] No finding row carries another finding's resolution anchors; a merge re-run/resume does not reopen terminal rows.
- [ ] `handoff_close_check` behavior unchanged (no edit); `superseded` excluded from all open-count surfaces and sorted terminal.
- [ ] Existing `MAINT-WPAC-HARDEN-20260614` `*-REV-*` drift reconciled; id-1515 corruption repaired.
