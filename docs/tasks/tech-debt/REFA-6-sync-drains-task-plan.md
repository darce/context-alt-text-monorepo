# REFA-6. Simplify the sync drains (`split-topology-command-drain` + `outbox-drain`)

> **Metadata**
>
> - **Date**: 2026-06-09
> - **Author**: Claude (claude-opus-4-8)
> - **Owning Epic**: `docs/epics/v0.4.1/wp-alt-context-structural-refactor-epic.md`
> - **Epic Short ID**: REFA
> - **Target Branch**: `feature/refa-6`
> - **Review Coverage Target**: 2
>
> **Review coverage note:** Finding/coverage state is DB-generated. Query with
> `review_findings(operation=list, task_ref=REFA-6)` / `review_runs(operation=coverage, task_ref=REFA-6)`.
> Claims verified vs `main` HEAD `9d5d859` (2026-06-09).

## Objective

Simplify the two sync drains — `src/sovereign/sync/class-split-topology-command-drain.php` (799 LOC, 21 methods) and `src/sovereign/sync/class-outbox-drain.php` (680 LOC, 24 methods) — via **Split Loop** + **Extract Function** (split-topology) and **Extract Class** (outbox query/admin surface), **without changing observable behavior**. Phase 4 of epic REFA. The two drains are **independent files**; this stays one `feature/refa-6` branch (Slice 1 is a shared safety net), but split-topology (Slices 2-3) and outbox (Slice 4) are committed as two independent, separately-revertable commit groups and are **not interleaved** — see Branch & PR Structure.

## Problem Statement

Both drains mix loop orchestration, persistence, retry/status transitions, and (split-topology) a transaction-bearing god-method in one class. The dominant smell is the **long method** inside a loop, not a god-class of routes:

- **split-topology**: `drain()` interleaves a command-processing loop with a post-processing tenant loop; `apply_member_delta` (lines 569-690, ~120 LOC) carries an **inline transaction** (`START TRANSACTION` 601 → `COMMIT` 679, multiple `ROLLBACK`) wrapping nested `foreach` loops over created clusters/members plus a final `upsert_snapshot_version`. `build_result_from_targeted_snapshot`, `process_command`, `dispatch_command`, and `reconcile_*` add further long methods.
- **outbox-drain**: already partly decomposed (injects `OutboxDispatcher`, `CrossPlaneSequencer`, `TopologyCommandRepository`), but still bundles a large **read/query surface** (`find_operations_by_status`, `count_operations_by_status`, `find_operations_by_ids`, `find_operation_by_id`, `load_pending_operations`) and **admin ops** (`retry_failed_operation`, `discard_operation`, `re_enqueue_with_current_base`) alongside the `drain()` + `apply_result` orchestration.

Every edit risks a sync regression: wrong status transition, broken retry, changed transaction timing, or altered enqueued meaning.

## Constraints

- **Behavior-preserving.** No change to processed status transitions, retry counts, emitted side effects, or scheduling. No `acx/v1`/contract change (rg-002).
- **Append-only payload semantics (rg-002, DDIA Ch4).** Do not change the meaning of enqueued commands/operations: `payload_json`/`result_json` decode, `member_delta` interpretation, and the `pending`/`failed` status machine stay byte-identical. Refactor reads the queue; it must not rewrite enqueued meaning.
- **Preserve inline transaction boundaries (sr-009/rg-002).** `apply_member_delta`'s `START TRANSACTION`/`COMMIT`/`ROLLBACK` (601-680) wraps the whole method body. **Extract Function must keep the transaction begin/commit/rollback in the orchestrating method**; extracted phase-functions run *inside* the open transaction. No commit/rollback timing change. `run_transactional` adoption is deferred (epic Deferred); do not introduce it here.
- **Preserve per-unit failure isolation + bounded progress (rg-007).** Each drain loop processes independent units (commands/operations) where one unit's failure sets its own `failed`/`pending` status and **continues** the batch; the batch re-schedules itself when full + more pending (`maybe_schedule_drain`), and `resolve_max_attempts()` bounds retries. The Split Loop must not regress this isolation, the re-schedule trigger, the per-tenant `refresh_curation_metrics` post-pass, or the attempt ceiling.
- **Preserve the scheduling seam.** `register()` enqueues via Action Scheduler (`as_enqueue_async_action`) with WP-Cron fallback; keep the hook names (`acx_sync_drain_*`) and fallback path.
- **rg-016 autoload.** New `class-*.php` collaborators must be `require_once`'d from the owning drain (the drains already `require_once` their collaborators) and verified.
- **sr-008.** Extracted collaborator/class constructors group >8 dependencies into typed objects; reuse the existing nullable-default injection idiom.
- **sr-007 status strings.** The drains compare/assign `pending`/`failed`-style status literals (~22 occurrences across the two files). Extraction must **not** scatter new status-string literals into the extracted phases/classes: reuse an existing constant where one exists (`Sync_Pull_Result::FAILED = 'failed'`) or preserve the current literals verbatim (behavior-preserving). Do not introduce a new status enum in this refactor.
- **Preserve public method surface (rg-002).** `retry_failed_operation`, `discard_operation`, `re_enqueue_with_current_base`, `find_operation_by_id`, `find_operations_by_ids` on `OutboxDrain` are **external API** — consumed by `src/api/class-conflict-controller.php` and `src/sovereign/sync/class-conflict-resolution-service.php`, and overridden by `InMemoryOutboxDrain` + anonymous test doubles. Extract Class moves only the **bodies** into the new collaborators; `OutboxDrain` keeps thin public delegating methods so callers and subclassing doubles stay green.

## Workflow Principles

- Safety net first: extend characterization to the loop + transaction + retry paths before touching structure (Fowler Ch4). Epic marks both safety nets "yes" — treat as **partial**; the long methods (`apply_member_delta`, `apply_result`, the query surface) are the likely gaps.
- Split Loop / Extract Function are mechanical (Fowler Ch6/Ch7): one phase per step, `composer test` + `phpstan` + `cs` green after each; the extracted function's call-site is identical.
- Per-slice stop rule: any status-transition / side-effect / SQL diff in characterization, or a transaction-timing change → revert.
- YAGNI: extract a class only where it groups a cohesive field+method subset (the outbox query surface); do not speculatively split the small drains further.
- Format before lint (`composer cs-fix`); never relax a gate (sr-001). Cite `docs/tasks/tech-debt/refactoring-evaluation.md` (Fowler Ch6 Split Loop / Split Phase, Ch7 Extract Function/Class).

## Terminology

- **Split Loop (Fowler Ch6)**: a loop doing two things (e.g. processing + metrics accumulation) is split into two single-purpose loops; here also separating the command/operation loop from the per-tenant post-pass.
- **Extract Function (Fowler Ch7)**: pull a named phase out of a long method, called at the same point with the same data; for `apply_member_delta` the extracted phases run *within the existing transaction*.
- **Characterization**: drive the drain over a fixed set of seeded commands/operations and assert identical resulting row statuses, retry counts, snapshot-version upserts, metrics refreshes, and re-schedule decisions pre/post.

## Current State Analysis

- Works: both drains process their queues; split-topology applies member deltas transactionally; outbox applies results with retry; both schedule via Action Scheduler/WP-Cron.
- Insufficient: `apply_member_delta` (~120 LOC, transaction + nested loops) and the outbox query surface concentrate logic; `drain()` loops mix processing with post-processing.
- Misleading: "safety net: yes" likely covers the happy drain path, not the rollback branch, retry ceiling, or re-schedule trigger. Treat as partial; extend in Slice 1.
- Already-good: outbox-drain's `OutboxDispatcher`/`CrossPlaneSequencer`/`TopologyCommandRepository` are already injected collaborators — reuse, do not duplicate.

## Target Outcome

`split-topology-command-drain` reads as a thin `drain()` (single-purpose loops) delegating to named phase-functions, with `apply_member_delta` decomposed into `apply created clusters → apply member rows → finalize snapshot` work-phases that run inside the unchanged transaction (the `START TRANSACTION`/`COMMIT`/`ROLLBACK` stay literally in `apply_member_delta`). `outbox-drain` keeps `drain()`/`apply_result` orchestration and delegates its read/query and admin surfaces to an `OutboxQueryRepository` and `OutboxMaintenanceService` **behind thin public delegating methods on `OutboxDrain`** (both surfaces are external API — see Contract and Boundary Impact). All status transitions, retries, transaction timing, payload meaning, scheduling, and metrics are identical; each new unit is tested.

## Context Loading

- Rules: `docs/workstate/rules/backend-php-guidelines.md`, constitution (sr-008/sr-009, rg-002/rg-007/rg-016).
- Drains: the two target files + their injected collaborators in `src/sovereign/sync/` (`class-outbox-dispatcher.php`, `class-cross-plane-sequencer.php`, `class-topology-command-repository.php`) and the split-topology drain's `SyncStateRepositoryInterface` dependency in `src/sovereign/repositories/` (`class-sync-state-repository.php` / `interface-sync-state-repository.php`, defaulted to `new SyncStateRepository()`).
- Technique: `docs/tasks/tech-debt/refactoring-evaluation.md` (Fowler Ch6/Ch7); DDIA Ch4 (append-only) for payload semantics.
- Handoff: epic `REFA`; this task `REFA-6`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `wp_acx_sync_outbox` / topology-command rows + status machine | backend | append-only payloads + `pending`/`failed` transitions | **none** (meaning preserved) | no | characterization asserts identical row statuses/retries/side effects |
| Action Scheduler / WP-Cron drain hooks (`acx_sync_drain_*`) | backend | hook names + fallback path | **none** | no | `register()`/`maybe_schedule_drain` behavior unchanged |
| Inline transaction in `apply_member_delta` | backend | `START TRANSACTION`…`COMMIT`/`ROLLBACK` boundary | **none** (boundary stays in orchestrator) | no | tx command-sequence assertion (START/COMMIT/ROLLBACK emission order via `$wpdb->queries`); no timing change |
| `OutboxDrain` public methods (`retry_failed_operation`, `discard_operation`, `re_enqueue_with_current_base`, `find_operation_by_id`, `find_operations_by_ids`) | backend | public methods called by conflict controller/service + overridden by `InMemoryOutboxDrain`/test doubles | **none** (signatures preserved; thin delegating methods retained) | no | extracted bodies behind unchanged public delegators; existing consumer + stub suites green |

## Proposed Solution

Characterize the loop, transaction (incl. rollback branch), retry ceiling, and re-schedule trigger first (Slice 1). Then, per drain independently:

- **split-topology** — Split Loop on `drain()` (separate command processing from the per-tenant metrics post-pass); Extract Function on `apply_member_delta` into transaction-internal phases (the `START`/`COMMIT`/`ROLLBACK` stays in the parent); Extract Function on `build_result_from_targeted_snapshot` / `process_command` / `dispatch_command` / `reconcile_*` (Slices 2-3).
- **outbox-drain** — Extract Class: `OutboxQueryRepository` (the `find_*`/`count_*`/`load_pending_operations` read surface) and `OutboxMaintenanceService` (`retry_failed_operation`, `discard_operation`, `re_enqueue_with_current_base`); leave `drain()`/`apply_result` as orchestration, Split Loop where it mixes concerns (Slice 4).

Each new class is `require_once`'d from its owning drain (rg-016). Collapse any trivial extraction back (YAGNI).

## Branch & PR Structure

One `feature/refa-6` branch. The two drains share **only** Slice 1 (characterization safety net); their structural work is on disjoint files with no shared state and must stay independent:

- **Slice 1** (shared) lands first: characterization for both drains.
- **split-topology group** = Slices 2-3 — committed as an independent, separately-revertable group.
- **outbox group** = Slice 4 — committed as an independent, separately-revertable group.

The two groups are not interleaved in history; either group may ship as its own PR off this branch. If review surfaces cross-drain coupling (none expected), stop and re-evaluate a `REFA-6a`/`REFA-6b` split. The epic checklist tracks REFA-6 as one task.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `src/sovereign/sync/class-split-topology-command-drain.php` | Split Loop on `drain()`; Extract Function on `apply_member_delta` (tx-internal phases) + result/dispatch/reconcile methods |
| backend (new, optional) | `src/sovereign/sync/class-split-topology-member-delta-applier.php` | only if the delta phases form a cohesive unit beyond function extraction (YAGNI-gated) |
| backend | `src/sovereign/sync/class-outbox-drain.php` | delegate query + admin surfaces; keep `drain()`/`apply_result` orchestration |
| backend (new) | `src/sovereign/sync/class-outbox-query-repository.php`, `class-outbox-maintenance-service.php` | extracted read/query + admin collaborators (`AltContext\Sovereign\Sync\`) |
| tests | `tests/Unit/SplitTopologyCommandDrainTest.php`, `tests/Unit/OutboxDrainTest.php` (+ new per-collaborator tests) | extend characterization (rollback/retry/re-schedule) + per-unit coverage |

## Related Files

| File | Note |
| --- | --- |
| `src/sovereign/sync/`: `class-outbox-dispatcher.php`, `class-cross-plane-sequencer.php`, `class-topology-command-repository.php`; `src/sovereign/repositories/class-sync-state-repository.php` (`SyncStateRepositoryInterface`) | already-injected collaborators — reuse, untouched |
| `src/sovereign/sync/class-conflict-resolution-service.php`, `src/api/class-conflict-controller.php` | external consumers of `OutboxDrain` public admin/query methods — do not refactor; verify still green after Slice 4 |
| `docs/tasks/tech-debt/current-debt.md` | append-only/outbox debt references |

## Verification Strategy

- Deterministic: `cd apps/prototype-wp-alt-context && composer test && composer phpstan && composer cs-check`.
- Autoload (rg-016) per new class: `composer dump-autoload && php -l <file> && php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\\\Sovereign\\\\Sync\\\\OutboxQueryRepository'));"`.
- Characterization: seed a fixed set of commands/operations (incl. a failing unit and a rollback-triggering case via the `wpdb` stub's `queryResults`); assert identical resulting statuses, retry counts, snapshot-version upserts, `refresh_curation_metrics` calls, and `maybe_schedule_drain` decisions pre/post each extraction.
- Transaction: assert the transaction **command sequence** emitted to `$wpdb->queries` — `START TRANSACTION` present, then `COMMIT` on success / `ROLLBACK` on a forced failure, in order. The `wpdb` stub records SQL and does not execute transactions, so data-level rollback is not observable; emission/order is. Use the ordering-assert pattern already in `SnapshotProjectorTest` (`array_search('ROLLBACK', $wpdb->queries)`).
- Full gate before review-ready: root `make check-all`.

## Slice Delivery

### Slice 1: Characterization safety net + loop/transaction/retry map

**Goal**: Pin drain behavior (happy + failure + rollback + re-schedule) and map the phases before touching structure.

Changes:
- Extend `SplitTopologyCommandDrainTest` + `OutboxDrainTest` to cover: a failing unit (per-unit isolation), the `apply_member_delta` rollback branch (force a failing `wpdb` query; assert `ROLLBACK` emitted in order — the stub records SQL, no real tx), the retry ceiling (`resolve_max_attempts`), and the `maybe_schedule_drain` re-schedule trigger.
- Phase/transaction map: document `apply_member_delta`'s transaction scope + the extractable phases, and the outbox query/admin method clusters.

Proof: characterization green against current drains; map recorded; `composer test` green.

### Slice 2: split-topology — Split Loop + tx-preserving Extract Function on `apply_member_delta`

**Goal**: Make `drain()` single-purpose loops; decompose `apply_member_delta` into transaction-internal phases.

Changes:
- Split `drain()` into the command-processing loop and the per-tenant metrics post-pass.
- Extract Function: `apply_member_delta` → `apply_created_clusters` + `apply_member_rows` + `finalize_snapshot` work-phases, all called *within* the existing open transaction; the `START TRANSACTION`/`COMMIT`/`ROLLBACK` statements stay **literally in** `apply_member_delta` (not extracted into a `begin_*` helper).

Proof: happy + forced-rollback characterization shows identical `$wpdb->queries` transaction sequence (START→…→COMMIT vs START→…→ROLLBACK); emission order unchanged; phpstan/cs green.

### Slice 3: split-topology — extract result/dispatch/reconcile phases; thin `drain()`

**Goal**: Extract the remaining long methods; `drain()`/`process_command` read as orchestration.

Changes:
- Extract Function on `build_result_from_targeted_snapshot`, `process_command`, `dispatch_command`, `reconcile_*` into named phases (or a `MemberDeltaApplier` class only if cohesive — YAGNI-gated).

Proof: command-processing characterization identical (statuses/retries/side effects); phpstan/cs green.

### Slice 4: outbox-drain — Extract Class (query repo + maintenance); Split Loop; thin drain

**Goal**: Delegate the read/query + admin surfaces; keep orchestration.

Changes:
- `OutboxQueryRepository` (`find_operations_by_status`, `count_operations_by_status`, `find_operations_by_ids`, `find_operation_by_id`, `load_pending_operations`) and `OutboxMaintenanceService` (`retry_failed_operation`, `discard_operation`, `re_enqueue_with_current_base`). **`OutboxDrain` keeps thin public delegating methods** for the externally-consumed members (`retry_failed_operation`, `discard_operation`, `re_enqueue_with_current_base`, `find_operation_by_id`, `find_operations_by_ids`) — move bodies only — so `class-conflict-controller.php`, `class-conflict-resolution-service.php`, and `InMemoryOutboxDrain`/test doubles stay green. Split Loop where `drain()` mixes processing + post-pass; `require_once` + verify (rg-016).

Proof: query results + admin-op side effects + drain statuses/re-schedule identical; per-collaborator tests; existing `ConflictControllerTest`/`ConflictResolutionServiceTest`/`Phase4WorkflowIntegrationTest` consumer suites green; `make check-all` green.

---

## Consolidated Checklist

> Describe work delivered, not finding status (query `review_findings(operation=list, status=open, task_ref=REFA-6)`).

## Context and Ownership

- [ ] Loaded backend-php guidelines + constitution (sr-008/sr-009, rg-002/rg-007/rg-016) and the Fowler evaluation.
- [ ] Confirmed `ctx7` not required.
- [ ] Recorded boundary ownership = backend; payload semantics + transaction boundary + scheduling = unchanged.

### Checklist for Slice 1: Characterization + map

- [ ] Characterization extended: failing-unit isolation, `apply_member_delta` rollback branch, retry ceiling, re-schedule trigger.
- [ ] Phase/transaction map + outbox query/admin clusters recorded.
- [ ] `composer test` green against current drains.

### Checklist for Slice 2: split-topology Split Loop + tx-preserving Extract Function

- [ ] `drain()` split into single-purpose loops.
- [ ] `apply_member_delta` decomposed into transaction-internal work-phases (no `begin_*` extraction); `START`/`COMMIT`/`ROLLBACK` remain literally in the parent; happy + forced-rollback `$wpdb->queries` tx-sequence identical.

### Checklist for Slice 3: split-topology extract remaining phases

- [ ] `build_result_from_targeted_snapshot`/`process_command`/`dispatch_command`/`reconcile_*` extracted; `drain()` reads as orchestration.
- [ ] Command-processing characterization identical (statuses/retries/side effects).

### Checklist for Slice 4: outbox Extract Class + Split Loop

- [ ] `OutboxQueryRepository` + `OutboxMaintenanceService` extracted; `OutboxDrain` retains thin public delegators for externally-consumed methods; `require_once` verified (rg-016).
- [ ] Query results + admin side effects + drain statuses/re-schedule identical; conflict controller/service consumer suites green; `make check-all` green.

## Review Readiness

- [ ] Every extraction has characterization evidence (incl. rollback/retry/re-schedule); no behavior-touching change without proof.
- [ ] Transaction boundary confirmed unchanged; per-unit isolation (rg-007) preserved; payload meaning unchanged.
- [ ] rg-016 autoload checks run for each new class.
- [ ] Handoff decision records moves, verification, citation, and confirms no behavior/contract change.

## Stretch Goals

- [ ] Note (do not implement) a `run_transactional` adoption opportunity for `apply_member_delta` for the epic's deferred wrapper slice (sr-009).

## Success Criteria

- [ ] `apply_member_delta` and `drain()` decomposed into named phases/loops; outbox query + admin surfaces extracted; each unit < the long-method threshold.
- [ ] All status transitions, retries, transaction timing, payload meaning, scheduling, and metrics identical (characterization proves it).
- [ ] `make check-all` green at HEAD.
