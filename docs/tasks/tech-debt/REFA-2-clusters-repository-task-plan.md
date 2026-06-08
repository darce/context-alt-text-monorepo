# REFA-2. Decompose `class-clusters-repository.php`

> **Metadata**
>
> - **Date**: 2026-06-07
> - **Author**: Claude (claude-opus-4-8)
> - **Owning Epic**: `docs/epics/v0.4.1/wp-alt-context-structural-refactor-epic.md`
> - **Epic Short ID**: REFA
> - **Target Branch**: `feature/refa-2`
> - **Review Coverage Target**: 2
>
> **Review coverage note:** Finding/coverage state is DB-generated. Query with
> `review_findings(operation=list, task_ref=REFA-2)` / `review_runs(operation=coverage, task_ref=REFA-2)`.
> Claims verified vs `main` HEAD `b0413891` (2026-06-07).

## Objective

Reduce `src/sovereign/repositories/class-clusters-repository.php` (1164 LOC, 34 declared methods — 21 public / 13 private, implementing the 20-method `ClustersRepositoryInterface`) to a thin **facade that keeps implementing the interface unchanged** and delegates each operation to a cohesive collaborator, **without changing observable behavior**. Add an rg-005 schema-parity test and an N+1 audit. Phase 1 of epic REFA.

## Problem Statement

The repository is a God Class: 34 methods spanning tenant read/query, curation mutations, snapshot-merge orchestration plus 13 private normalizers, projection upsert/update, local-cluster creation, and cascade delete-with-members. The `ClustersRepositoryInterface` bundles all of these responsibilities, so any edit risks a `wp_acx_clusters` regression across read, sync, and mutation paths at once.

Coverage is uneven: `ClustersRepositoryTest` covers reads + snapshot-merge; `ClustersRepositoryMutationTest` covers `update_label`/`dismiss`/`undismiss`. The following public methods have **no direct test** and would be moved blind: `update_identity_count`, `update_representative_state`, `create_local_cluster`, `upsert_projection_cluster`, `update_projection_cluster`, `reset_curation`, `delete_cluster_with_members`, `get_curated_clusters_for_tenant`, `has_projection_rows_for_tenant`.

## Constraints

- **Behavior-preserving; `ClustersRepositoryInterface` unchanged** (no signature change). Consumers `ClusterFacade` and `SyncPullJobFactory` type-hint the interface; controllers/services instantiate `ClustersRepository` directly. No `acx/v1` or contract change (rg-002).
- **No transactions in this file.** `START TRANSACTION`/`COMMIT`/`ROLLBACK` count = **0**; transaction control is owned by callers (`SnapshotProjector`, `ConflictResolutionService`, `SplitTopologyCommandDrain`). Do **not** introduce or move transaction boundaries here. `run_transactional` does **not** exist anywhere in `src/` (epic-confirmed) — out of scope.
- **Preserve the intentional chunked-upsert design.** The per-cluster `INSERT … ON DUPLICATE KEY` loop in `merge_snapshot_batch_for_tenant` is deliberate (interface docblock; `MAX_SNAPSHOT_MERGE_BATCH = 500`). The "N+1 audit" is **classify + document**; collapsing it into one multi-row `INSERT` changes write granularity and is a profiled perf task under a feature hat (rg-002), not this refactor.
- **rg-005 schema parity.** Clusters DDL lives at `src/support/class-life-cycle-manager.php:473-498` (PK `cluster_uuid`; 4 secondary keys). Every column the repository SQL references must exist in that DDL; a parity test must fail on a non-existent key.
- **rg-016 autoload.** `composer.json` uses `psr-4` (`AltContext\` → `src/`) **plus** `classmap: ["src/"]`; WP-style `class-*.php` resolves via the classmap only after `composer dump-autoload`, and the codebase additionally `require_once`s the repo/interface defensively from each entrypoint. New collaborator files must be `require_once`'d from `class-clusters-repository.php` and verified.
- **sr-008.** Collaborator constructors group >8 dependencies into typed objects. (Current ctor takes only `?string $table_name`; collaborators share the resolved `table_name` + the `PreparesSqlQueries` / `ResolvesPersonsTableName` traits.)
- **Two Hats; greenfield-but-incremental.** A God-Class split is cross-cutting — one verified step at a time, not a single rewrite.

## Workflow Principles

- Safety net first: extend characterization to every uncovered public method **before** extraction (Fowler Ch4).
- One cohesive collaborator per extraction step; compile/test after each.
- Per-slice stop rule: any return/SQL diff in a characterization assertion, or 2 consecutive red steps with unclear cause → revert and re-plan smaller.
- Format before lint (`composer cs-fix`); never relax a gate (sr-001).
- Each slice decision cites `docs/tasks/tech-debt/refactoring-evaluation.md` + Fowler Ch7 (Extract Class).

## Terminology

- **Repository facade / composition root**: `ClustersRepository` keeps implementing `ClustersRepositoryInterface` and delegates each method to an internal collaborator, constructed via the nullable-default injection idiom (`?Dep $x = null` → `$x ?? new Dep()`) used throughout this codebase. The interface and method signatures are frozen.
- **Collaborator**: an extracted class under `AltContext\Sovereign\Repositories\` that shares the resolved `table_name` and the `PreparesSqlQueries` / `ResolvesPersonsTableName` traits.
- **Characterization**: a direct repository method call against a seeded `$wpdb` (the existing `ClustersRepositoryTest` pattern), asserting identical return value + emitted SQL pre/post extraction.

## Current State Analysis

- Works: every interface method functions; reads, snapshot-merge, and `update_label`/`dismiss`/`undismiss` are covered.
- Insufficient: 1164 LOC / 34 methods in one class mix read/query, curation mutation, snapshot-merge + normalization, projection writes, creation, and cascade delete; the interface mirrors that sprawl.
- Misleading: the epic's Current State marks REFA-2's safety net "yes", but the **mutation and delete paths slated for extraction are largely uncovered** — the same characterization gap REFA-1 faced. Treat the safety net as partial.

## Target Outcome

`ClustersRepository` becomes a thin facade implementing the unchanged 20-method interface and delegating to ~5 collaborators under `src/sovereign/repositories/`: a read/query repository, a curation-mutation writer, a projection writer, a snapshot-merge service (owning the 13 private normalizers), and a deletion service — each unit-tested. The interface file and every return value / emitted SQL are identical; an rg-005 schema-parity test guards column drift; the N+1 audit is documented with the chunked-upsert design preserved.

## Context Loading

- Rules: `docs/workstate/rules/backend-php-guidelines.md`, constitution (sr-008, rg-002/rg-005/rg-016).
- Contract: `src/sovereign/repositories/interface-clusters-repository.php` (frozen).
- Schema SoT: `src/support/class-life-cycle-manager.php:473-498` (clusters DDL).
- Injection-idiom precedent: `src/api/class-recognition-controller.php`.
- Technique: `docs/tasks/tech-debt/refactoring-evaluation.md` (Fowler Ch7).
- Handoff: epic `REFA`; this task `REFA-2`.
- `ctx7`: not required (no upstream-library behavior in scope).

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `ClustersRepositoryInterface` (20 methods) | backend | `interface-clusters-repository.php` | **none** (facade keeps implementing it) | no | interface file diff = none; existing + new repository unit tests assert identical return/SQL; consumers `ClusterFacade`/`SyncPullJobFactory` untouched |
| `wp_acx_clusters` columns | backend | DDL `class-life-cycle-manager.php:473-498` | **none** | no | new schema-parity test (rg-005) |

## Proposed Solution

Extend the characterization safety net to every uncovered public method and add the schema-parity test first (Slice 1). Then Extract Class per cohesive group into collaborators that share `table_name` + traits, injected into `ClustersRepository` via the nullable-default idiom; the facade delegates each interface method (Slices 2-4). Keep the interface and all signatures frozen. `require_once` each new file from the facade (rg-016).

The 5-way split is cohesion-driven (each collaborator groups methods sharing fields + intent, keeping every unit well under the God-Class threshold) and is a **superset** of the epic's "read/query vs curation-reset/delete" framing, not a contradiction. Any collaborator that would end up trivial collapses back into the facade rather than being created speculatively (YAGNI, Fowler Ch3).

Proposed collaborator grouping (covers all 20 interface methods; the curation-vs-projection boundary is re-verified at extraction by which methods touch `is_user_confirmed` / `local_revision`, and the 13 private normalizers are allocated to owners by call-site — a shared normalizer trait/collaborator is extracted when a helper is consumed by more than one writer, e.g. the `resolve_representative_*` / `normalize_curation_state` / `resolve_user_confirmed_flag` helpers used by both projection and curation writes):

| Collaborator | Public methods |
| --- | --- |
| `ClustersReadRepository` | `list_for_tenant`, `list_labels`, `has_projection_rows_for_tenant`, `list_top_unlabeled`, `count_top_unlabeled_singletons`, `find_by_uuid`, `get_curated_clusters_for_tenant` |
| `ClusterCurationWriter` | `update_label`, `dismiss`, `undismiss`, `reset_curation`, `update_identity_count`, `update_representative_state` |
| `ClusterProjectionWriter` | `create_local_cluster`, `upsert_projection_cluster`, `update_projection_cluster` |
| `ClusterSnapshotMerger` | `merge_snapshot_for_tenant`, `prepare_snapshot_merge_for_tenant`, `merge_snapshot_batch_for_tenant` (+ the 13 private `normalize_*`/`resolve_*`/`sanitize_*` helpers + `delete_stale_non_curated_rows`) |
| `ClusterDeletionService` | `delete_cluster_with_members` |

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `src/sovereign/repositories/class-clusters-repository.php` | reduce to a facade delegating all 20 interface methods |
| backend (new) | `src/sovereign/repositories/class-clusters-read-repository.php`, `class-cluster-curation-writer.php`, `class-cluster-projection-writer.php`, `class-cluster-snapshot-merger.php`, `class-cluster-deletion-service.php` | extracted collaborators (`AltContext\Sovereign\Repositories\`) |
| backend (autoload) | `src/sovereign/repositories/class-clusters-repository.php` | `require_once` each new collaborator (rg-016) |
| tests | `tests/Unit/ClustersRepositoryTest.php`, `ClustersRepositoryMutationTest.php` (+ new per-collaborator tests + `ClustersSchemaParityTest`) | characterization for uncovered methods + per-collaborator coverage + schema parity |

## Related Files

| File | Note |
| --- | --- |
| `src/sovereign/repositories/interface-clusters-repository.php` | frozen contract — must not change |
| `src/support/class-life-cycle-manager.php` | clusters DDL (rg-005 schema-parity source, lines 473-498) |
| `src/sovereign/class-cluster-facade.php`, `src/sovereign/sync/class-sync-pull-job-factory.php` | interface consumers — untouched |
| `src/sovereign/sync/class-snapshot-projector.php`, `class-conflict-resolution-service.php` | transaction owners + mutation callers — untouched |
| `src/sovereign/repositories/trait-prepares-sql-queries.php`, `trait-resolves-persons-table-name.php` | shared by collaborators |

## Verification Strategy

- Deterministic: `cd apps/prototype-wp-alt-context && composer test && composer phpstan && composer cs-check`.
- Autoload (rg-016) per new file: `composer dump-autoload && php -l <file> && php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\\\Sovereign\\\\Repositories\\\\ClustersReadRepository'));"`.
- Contract: existing + new repository unit tests assert identical return + emitted SQL pre/post extraction for each method; `interface-clusters-repository.php` diff = none.
- Schema parity: new test asserts every column referenced in repository SQL exists in the DDL.
- Full gate before review-ready: root `make check-all`.

## Slice Delivery

### Slice 1: Safety net + schema-parity guard + N+1 audit

**Goal**: Pin current behavior of every uncovered public method, lock the collaborator boundaries from a verified matrix, and add the rg-005 guard before touching structure.

Changes:
- **Collaborator-boundary matrix**: build a method→fields-written + private-helper call-site matrix from the repo SQL to lock each collaborator's membership before extraction — in particular `create_local_cluster`'s curation-vs-projection placement (it sets `is_user_confirmed=1`) and ownership of the 13 private normalizers (extract a shared normalizer trait/collaborator for any helper consumed by more than one writer rather than duplicating it).
- Characterization tests for the 9 uncovered public methods (`update_identity_count`, `update_representative_state`, `create_local_cluster`, `upsert_projection_cluster`, `update_projection_cluster`, `reset_curation`, `delete_cluster_with_members`, `get_curated_clusters_for_tenant`, `has_projection_rows_for_tenant`), capturing emitted SQL + return + curation-marker side effects (`is_user_confirmed`/`local_revision`).
- `ClustersSchemaParityTest`: assert every column in repository SQL exists in the DDL; fail on a fabricated column.
- N+1 audit: classify every `foreach`/`while`; record a decision that `merge_snapshot_batch_for_tenant`'s chunked per-cluster upsert is intentional and any single-`INSERT` change is deferred to a profiled perf task.

Proof: `composer test` green; all 21 public methods have direct coverage; parity test green and fails on an injected bad column.

### Slice 2: Extract `ClustersReadRepository`

**Goal**: Move the 7 read/query methods to a collaborator; facade delegates.

Changes:
- `ClustersReadRepository` (read methods); `require_once` from the facade; facade delegates.

Proof: read characterization return-identical; per-collaborator tests; phpstan/cs green.

### Slice 3: Extract `ClusterCurationWriter` + `ClusterProjectionWriter`

**Goal**: Move mutation methods; preserve curation-marker semantics per method.

Changes:
- `ClusterCurationWriter` (curation mutations) + `ClusterProjectionWriter` (projection writes); verify which methods set `is_user_confirmed`/bump `local_revision` and preserve exactly; facade delegates.

Proof: mutation characterization identical; per-collaborator tests; phpstan/cs green.

### Slice 4: Extract `ClusterSnapshotMerger` + `ClusterDeletionService`; thin facade

**Goal**: Finish extraction; facade becomes thin delegation.

Changes:
- `ClusterSnapshotMerger` (3 merge methods + 13 private normalizers + `delete_stale_non_curated_rows`) and `ClusterDeletionService` (`delete_cluster_with_members`); remove residual logic from the facade.

Proof: merge + delete characterization identical; full per-collaborator coverage; `make check-all` green; interface file unchanged.

---

## Consolidated Checklist

> Describe work delivered, not finding status (query `review_findings(operation=list, status=open, task_ref=REFA-2)`).

## Context and Ownership

- [ ] Loaded backend-php guidelines + constitution (sr-008, rg-002/rg-005/rg-016), interface, DDL, and the Fowler evaluation.
- [ ] Confirmed `ctx7` not required.
- [ ] Recorded boundary ownership: `ClustersRepositoryInterface` = backend, expected change = none.

### Checklist for Slice 1: Safety net + schema-parity guard + N+1 audit

- [ ] Collaborator-boundary matrix built (method→fields-written + private-helper call-sites); `create_local_cluster` placement + shared-normalizer ownership locked.
- [ ] Characterization tests for all 9 uncovered public methods committed (SQL + return + curation-marker side effects).
- [ ] `ClustersSchemaParityTest` green and fails on an injected bad column.
- [ ] N+1 audit recorded; chunked-upsert intentional, single-`INSERT` change deferred.

### Checklist for Slice 2: Extract read repository

- [ ] `ClustersReadRepository` created; `require_once` added + verified; facade delegates the 7 read methods.
- [ ] Read characterization return-identical; per-collaborator tests green.

### Checklist for Slice 3: Extract curation + projection writers

- [ ] `ClusterCurationWriter` + `ClusterProjectionWriter` extracted; `is_user_confirmed`/`local_revision` semantics preserved per method.
- [ ] Mutation characterization identical; per-collaborator tests green.

### Checklist for Slice 4: Extract snapshot merger + deletion; thin facade

- [ ] `ClusterSnapshotMerger` (+ 13 private helpers) + `ClusterDeletionService` extracted; facade reduced to delegation.
- [ ] Merge + delete characterization identical; `make check-all` green; interface file unchanged.

## Review Readiness

- [ ] Every extracted method has characterization + unit evidence; no behavior-touching change without proof.
- [ ] rg-016 autoload checks run for each new collaborator.
- [ ] rg-005 schema-parity test present and enforced.
- [ ] Handoff decision records moves, verification, citation, and confirms the interface + return/SQL are unchanged.

## Stretch Goals

- [ ] Note any `run_transactional` adoption opportunity for the epic's deferred wrapper slice (do **not** implement here; the helper does not yet exist).

## Success Criteria

- [ ] `ClustersRepository` reduced to a thin facade; all 20 interface methods delegated to ~5 unit-tested collaborators.
- [ ] `ClustersRepositoryInterface` and every return value / emitted SQL unchanged (characterization proves it).
- [ ] rg-005 schema-parity test green; N+1 audit documented.
- [ ] `make check-all` green at HEAD.
