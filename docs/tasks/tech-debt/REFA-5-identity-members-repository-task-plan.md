# REFA-5. Decompose `class-identity-members-repository.php`

> **Metadata**
>
> - **Date**: 2026-06-09
> - **Author**: Claude (claude-opus-4-8)
> - **Owning Epic**: `docs/epics/v0.4.1/wp-alt-context-structural-refactor-epic.md`
> - **Epic Short ID**: REFA
> - **Target Branch**: `feature/refa-5`
> - **Review Coverage Target**: 2
>
> **Review coverage note:** Finding/coverage state is DB-generated. Query with
> `review_findings(operation=list, task_ref=REFA-5)` / `review_runs(operation=coverage, task_ref=REFA-5)`.
> Claims verified vs `main` HEAD `9574e7d` (2026-06-09).

## Objective

Reduce `src/sovereign/repositories/class-identity-members-repository.php` (1045 LOC, 28 declared methods incl. constructor — 15 public implementing `IdentityMembersRepositoryInterface` + 1 constructor + 12 private; matches epic targets table) to a thin **facade that keeps implementing the interface unchanged** and delegates each operation to a cohesive collaborator, **without changing observable behavior**. Add an rg-005 schema-parity test and an N+1 audit. Structure-only — perf deferred. Phase 3 of epic REFA.

## Problem Statement

The repository is a God Class: 28 methods (incl. ctor) spanning tenant read/query (with `clusters`/`persons` JOINs), curation mutations, the `merge_snapshot_for_tenant` projection-merge path (incl. stale/orphan deletes), member-conflict recording, and 7 private value-normalizers. Ten+ consumers (`split-topology-command-drain`, `conflict-resolution-service`, `media-identities-controller`, `clusters-controller`, `cluster-mutations-controller`, `sync-status-controller`, `recognition-controller`, and the cluster `merge`/`membership`/`projection-sync` services) reach it through `IdentityMembersRepositoryInterface`, so any edit risks a `wp_acx_identity_members` regression across read, sync, curation, and conflict paths at once.

## Constraints

- **Behavior-preserving; `IdentityMembersRepositoryInterface` (15 methods) unchanged** (no signature change). The interface file diff must be empty; consumers stay untouched. No `acx/v1`/contract change (rg-002).
- **Structure-only — perf is explicitly deferred.** The `foreach ($normalized_members …)` per-member query loop inside `merge_snapshot_for_tenant` (lines 97-160) and the `delete_orphan_rows()` LEFT-JOIN cost (line 827; `current-debt.md` #11, also in epic Deferred) are **classified + documented in the N+1/perf audit, not changed**. Collapsing the merge loop or rewriting the orphan delete changes write/scan granularity and is a profiled perf task under a feature hat (rg-002), not this refactor.
- **rg-005 schema parity.** This repo emits hand-built SQL with `clusters`/`persons` JOINs and `wp_acx_identity_members` column writes. Add a schema-parity test validating every referenced column against the real schema (`class-life-cycle-manager.php`) **before** moving any SQL.
- **No inline transactions** (verified: zero `START TRANSACTION`/`COMMIT`/`ROLLBACK`) — unlike a transactional repo, the risk here is SQL/column drift and side-effect ordering (stale+orphan deletes during merge), not commit timing.
- **rg-016 autoload.** `composer.json` uses `psr-4` (`AltContext\` → `src/`) **plus** `classmap: ["src/"]`; WP-style `class-*.php` resolves via classmap only after `composer dump-autoload`, and the codebase additionally `require_once`s repo/interface files defensively. New collaborator files must be `require_once`'d from `class-identity-members-repository.php` and verified.
- **sr-008.** Collaborator constructors group >8 dependencies into typed objects. The current ctor is `__construct( ?string $members_table_name = null, ?string $clusters_table_name = null, ?ConflictRepository $conflict_repository = null )` — **two** resolved table names (`members` + the JOINed `clusters` table) plus an **already-injected** `AltContext\Sovereign\Sync\ConflictRepository`. Collaborators share the relevant subset: read/merge/delete paths need `members_table_name` (+ `clusters_table_name` where they JOIN `clusters`/`persons`) and the SQL-prepare/persons-table traits; the conflict-recording collaborator is threaded the existing `ConflictRepository` (it is not a new persistence layer — see Proposed Solution).

## Workflow Principles

- Safety net first: extend characterization to every uncovered public method + add the schema-parity guard before touching structure (Fowler Ch4). Treat the epic's "safety net: yes" as **partial** — the mutation/merge/delete paths are the likely gaps (same lesson as REFA-1/REFA-2).
- Two Hats; one cohesive collaborator per extraction step; `composer test` + `phpstan` + `cs` green after each.
- Per-slice stop rule: any return/SQL diff in a characterization assertion, or 2 consecutive red steps with unclear cause → revert and re-plan smaller.
- YAGNI (Fowler Ch3): a collaborator that would be trivial collapses back into the facade rather than being created speculatively.
- Format before lint (`composer cs-fix`); never relax a gate (sr-001). Each slice decision cites `docs/tasks/tech-debt/refactoring-evaluation.md` + Fowler Ch7 (Extract Class).

## Terminology

- **Repository facade / composition root**: `IdentityMembersRepository` keeps implementing `IdentityMembersRepositoryInterface` and delegates each method to an internal collaborator, constructed via the nullable-default injection idiom (`?Dep $x = null` → `$x ?? new Dep()`) used throughout this codebase. Interface + method signatures are frozen.
- **Characterization**: existing + new repository unit tests assert identical return value **and emitted SQL** pre/post extraction for each method.
- **N+1 audit**: classify each query-in-loop / JOIN-cost site as *intentional* (document) vs *accidental* (record a deferred perf finding); change nothing here.

## Current State Analysis

- Works: every interface method functions; reads, `merge_snapshot_for_tenant`, and curation paths operate in production.
- Insufficient: 1045 LOC / 28 methods (incl. ctor) in one class mix read/query, curation mutation, snapshot-merge + stale/orphan deletes, conflict recording, and 7 value-normalizers; the interface bundles read + mutation + merge responsibilities.
- Misleading: the epic Current State marks REFA-5's safety net "yes", but the **merge/curation/delete paths slated for extraction are likely only partially covered** by `IdentityMembersRepositoryTest`. Treat the net as partial and extend it in Slice 1.
- Known deferred perf: merge per-member loop (97-160) and `delete_orphan_rows` LEFT JOIN (827) — debt #11.

## Target Outcome

`IdentityMembersRepository` becomes a thin facade implementing the unchanged 15-method interface, delegating to 5–6 collaborators under `src/sovereign/repositories/`: a read/query repository, a curation-mutation writer, a projection snapshot-merger (owning stale/orphan deletes + the deferred N+1), a member-conflict recorder (wrapping the existing injected `ConflictRepository`), a shared value-normalizer (trait or collaborator), and — **conditionally** — a deletion service (only if the Slice-1 matrix shows `delete_member` + the delete privates cohere apart from the merger; otherwise it collapses into the merger/facade per YAGNI) — each unit-tested. The interface file and every return value / emitted SQL are identical; an rg-005 schema-parity test guards column drift; the N+1/orphan-delete perf is documented and deferred.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`, constitution (sr-008, rg-002/rg-005/rg-016).
- Contract (frozen): `src/sovereign/repositories/interface-identity-members-repository.php`.
- Schema cross-check (rg-005): `src/support/class-life-cycle-manager.php`.
- Sibling precedent: `docs/tasks/tech-debt/REFA-2-clusters-repository-task-plan.md` + the extracted `class-clusters-read-repository.php` / `-snapshot-merger.php` / `-deletion-service.php` collaborators.
- Technique: `docs/tasks/tech-debt/refactoring-evaluation.md` (Fowler Ch7).
- Handoff: epic `REFA`; this task `REFA-5`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `IdentityMembersRepositoryInterface` (15 methods) | backend | `interface-identity-members-repository.php` | **none** (facade keeps implementing it) | no | interface file diff = none; existing + new unit tests assert identical return/SQL; all 10+ consumers untouched |
| `wp_acx_identity_members` + JOINed `clusters`/`persons` columns | backend | hand-built SQL in this repo | **none** (same columns) | no | rg-005 schema-parity test (Slice 1) validates every referenced column against `class-life-cycle-manager.php` |

## Proposed Solution

Extend the characterization safety net to every uncovered public method and add the schema-parity test + N+1 audit first (Slice 1). Then Extract Class per cohesive group into collaborators that share the relevant table names (`members_table_name` + `clusters_table_name` where they JOIN) + traits, injected into `IdentityMembersRepository` via the nullable-default idiom; the facade delegates each interface method (Slices 2-4). Keep the interface and all signatures frozen. `require_once` each new file from the facade (rg-016).

The split is cohesion-driven and a **superset** of the epic's "Extract Class" framing. Collaborator membership is locked from a Slice-1 method→fields-written + private-helper call-site matrix (esp. ownership of the 7 normalizers and whether stale/orphan deletes belong to the merger or a deletion service). The existing injected `ConflictRepository` is threaded into `MemberConflictRecorder` unchanged — conflict persistence (`record_projection_conflict`) already lives in that collaborator, so the recorder wraps it rather than reimplementing it. Any collaborator that would be trivial collapses into the facade (YAGNI).

Proposed collaborator grouping (redistributes the 27 non-ctor methods — all 15 interface methods + 12 privates; the constructor stays on the facade as composition-root wiring):

| Collaborator | Methods |
| --- | --- |
| `IdentityMembersReadRepository` | `list_for_cluster`, `list_for_cluster_uuids`, `list_for_media_ids`, `has_projection_rows_for_tenant`, `count_for_cluster`, `find_by_identity_uuid`, `get_curated_members_for_tenant` |
| `IdentityMemberCurationWriter` | `mark_as_curated`, `reassign_to_cluster`, `reassign_cluster_members`, `reset_curation`, `accept_machine_cluster_assignment` |
| `IdentityMemberSnapshotMerger` | `merge_snapshot_for_tenant`, `assign_to_cluster_for_projection`, + privates `delete_stale_non_curated_rows`, `delete_orphan_rows` (owns the deferred N+1 + orphan-delete perf debt). **Exclusive-or with the deletion service** — the Slice-1 matrix assigns the two delete privates to the merger *or* the deletion service, never both. |
| `IdentityMemberDeletionService` | `delete_member` (+ the two stale/orphan delete privates *only if* the Slice-1 matrix shows them cohesive with member deletion rather than merge — see exclusive-or note above) |
| `MemberConflictRecorder` | `is_member_cluster_conflict` (pure predicate), `record_member_cluster_reassignment_conflict`, `record_missing_curated_member_conflicts`. **Wraps the existing injected `ConflictRepository`** (the record_* privates already delegate to `conflict_repository->record_projection_conflict(...)`); constructed with that `ConflictRepository` threaded from the facade ctor — not a new persistence layer. |
| `MemberRowNormalizer` (trait or collaborator) | `normalize_similarity_value`, `normalize_optional_float_value`, `normalize_thumb_path`, `encode_bbox_json`, `extract_pixels`, `extract_normalized_bbox`, `sanitize_uuid_list` — extracted as shared when consumed by >1 owner |

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `src/sovereign/repositories/class-identity-members-repository.php` | reduce to a facade delegating all 15 interface methods; `require_once` each collaborator |
| backend (new) | `src/sovereign/repositories/class-identity-members-read-repository.php`, `class-identity-member-curation-writer.php`, `class-identity-member-snapshot-merger.php`, `class-member-conflict-recorder.php` (+ normalizer trait/class); `class-identity-member-deletion-service.php` **only if** the Slice-1 matrix justifies it (else `delete_member` folds into the merger/facade, YAGNI) | extracted collaborators (`AltContext\Sovereign\Repositories\`) |
| tests | `tests/Unit/IdentityMembersRepositoryTest.php` (+ new per-collaborator tests + `IdentityMembersSchemaParityTest`) | characterization for uncovered methods + per-collaborator coverage + schema parity |

## Related Files

| File | Note |
| --- | --- |
| `src/sovereign/repositories/interface-identity-members-repository.php` | frozen contract — must not change |
| 10+ consumers (`class-split-topology-command-drain.php`, `class-conflict-resolution-service.php`, `class-media-identities-controller.php`, `class-clusters-controller.php`, `class-cluster-mutations-controller.php`, `class-sync-status-controller.php`, `class-recognition-controller.php`, `services/class-cluster-merge-service.php`, `class-projection-sync-service.php`, `class-cluster-membership-service.php`) | interface consumers — untouched |
| `src/support/class-life-cycle-manager.php` | rg-005 schema source of truth |
| REFA-2 collaborators under `src/sovereign/repositories/` | precedent shapes/traits to reuse |

## Verification Strategy

- Deterministic: `cd apps/prototype-wp-alt-context && composer test && composer phpstan && composer cs-check`.
- Autoload (rg-016) per new collaborator: `composer dump-autoload && php -l <file> && php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\\\Sovereign\\\\Repositories\\\\IdentityMembersReadRepository'));"`.
- Contract: existing + new unit tests assert identical return + emitted SQL pre/post extraction for each interface method; `interface-identity-members-repository.php` diff = none.
- Schema parity (rg-005): `IdentityMembersSchemaParityTest` validates every referenced `identity_members`/`clusters`/`persons` column against `class-life-cycle-manager.php`.
- Full gate before review-ready: root `make check-all`.

## Slice Delivery

### Slice 1: Safety net + schema-parity guard + N+1/perf audit + boundary matrix

**Goal**: Pin current behavior of every uncovered public method, lock collaborator boundaries from a verified matrix, add the rg-005 guard, and document deferred perf — before touching structure.

Changes:
- Extend `IdentityMembersRepositoryTest` to cover every uncovered public method (return + emitted SQL), esp. `merge_snapshot_for_tenant`, curation writes, and `delete_member`.
- Add `IdentityMembersSchemaParityTest` (rg-005).
- **Collaborator-boundary matrix**: method → columns-written + private-helper call-sites, locking normalizer ownership and whether `delete_stale_non_curated_rows`/`delete_orphan_rows` belong to the merger or the deletion service.
- **N+1/perf audit**: document the merge per-member loop + `delete_orphan_rows` LEFT JOIN as deferred (debt #11) — record a deferred perf finding; change nothing.

Proof: characterization green against the current repo; schema-parity test green; matrix + audit recorded; `composer test` green.

### Slice 2: Extract `IdentityMembersReadRepository` + `MemberRowNormalizer`

**Goal**: Move the read/query surface and the shared value-normalizers first (lowest risk; reads have no write side effects).

Changes:
- `IdentityMembersReadRepository` (7 read methods) + `MemberRowNormalizer` (the 7 normalizers, as a trait/collaborator shared by reader + writers); facade delegates; `require_once` + verify (rg-016).

Proof: read-method return + SQL identical; normalizer outputs identical; per-collaborator tests; phpstan/cs green.

### Slice 3: Extract `IdentityMemberCurationWriter` + `MemberConflictRecorder`

**Goal**: Move curation mutations and conflict recording.

Changes:
- `IdentityMemberCurationWriter` (5 curation methods) + `MemberConflictRecorder` (3 conflict privates, wrapping the existing injected `ConflictRepository` threaded from the facade ctor); facade delegates; preserve side-effect ordering (incl. the existing `conflict_repository->record_projection_conflict(...)` calls).

Proof: curation-method return + SQL identical; conflict-recording side effects identical; per-collaborator tests; phpstan/cs green.

### Slice 4: Extract `IdentityMemberSnapshotMerger` + `IdentityMemberDeletionService`; thin facade

**Goal**: Move the projection-merge path (with deferred-perf deletes) and member deletion; facade becomes thin delegation.

Changes:
- `IdentityMemberSnapshotMerger` (`merge_snapshot_for_tenant`, `assign_to_cluster_for_projection` + stale/orphan deletes per the matrix) preserving the documented N+1 + orphan-delete behavior unchanged; `IdentityMemberDeletionService` (`delete_member`); facade reduced to delegation.

Proof: merge + delete return/SQL + side-effect ordering identical; all 15 interface methods characterized green; `interface-…` diff = none; `make check-all` green.

---

## Consolidated Checklist

> Describe work delivered, not finding status (query `review_findings(operation=list, status=open, task_ref=REFA-5)`).

## Context and Ownership

- [ ] Loaded backend-php guidelines + constitution (sr-008, rg-002/rg-005/rg-016) and the Fowler evaluation.
- [ ] Confirmed `ctx7` not required.
- [ ] Recorded boundary ownership = backend; `IdentityMembersRepositoryInterface` frozen; expected change = none.

### Checklist for Slice 1: Safety net + schema parity + matrix + audit

- [ ] Characterization extended to every uncovered public method (return + emitted SQL).
- [ ] `IdentityMembersSchemaParityTest` added + green (rg-005).
- [ ] Collaborator-boundary matrix recorded (normalizer ownership + stale/orphan-delete placement locked).
- [ ] N+1/orphan-delete perf documented as deferred (debt #11); nothing changed.

### Checklist for Slice 2: Read repository + normalizer

- [ ] `IdentityMembersReadRepository` + `MemberRowNormalizer` extracted; facade delegates; `require_once` verified (rg-016).
- [ ] Read return + SQL identical; normalizer outputs identical; per-collaborator tests green.

### Checklist for Slice 3: Curation writer + conflict recorder

- [ ] `IdentityMemberCurationWriter` + `MemberConflictRecorder` extracted; side-effect ordering preserved.
- [ ] Curation return + SQL identical; conflict side effects identical; per-collaborator tests green.

### Checklist for Slice 4: Snapshot-merger + deletion; thin facade

- [ ] `IdentityMemberSnapshotMerger` (+ deferred-perf deletes) + `IdentityMemberDeletionService` extracted; facade reduced to delegation.
- [ ] Merge/delete return + SQL + ordering identical; all 15 interface methods green; interface diff = none; `make check-all` green.

## Review Readiness

- [ ] Every extracted method has return + emitted-SQL characterization evidence; no behavior-touching change without proof.
- [ ] rg-005 schema-parity + rg-016 autoload checks run.
- [ ] Interface file diff confirmed empty; consumers untouched.
- [ ] Handoff decision records moves, verification, citation, deferred-perf findings, and confirms no contract change.

## Stretch Goals

- [ ] File the separate **profiled perf follow-up task** (the actual optimization, under a feature hat) for the merge N+1 + `delete_orphan_rows` LEFT-JOIN, linking the deferred finding recorded in Slice 1 and `current-debt.md` #11. (Distinct from Slice 1, which only *records* the deferred finding — this stretch item opens the downstream perf task.)

## Success Criteria

- [ ] Repository reduced to a thin facade implementing the unchanged 15-method interface; all methods delegated to 5–6 unit-tested collaborators (deletion service conditional per the Slice-1 matrix).
- [ ] Every interface method returns identical values + emits identical SQL (characterization proves it); `interface-identity-members-repository.php` diff = none.
- [ ] rg-005 schema-parity test green; perf items documented + deferred (not changed).
- [ ] `make check-all` green at HEAD.
