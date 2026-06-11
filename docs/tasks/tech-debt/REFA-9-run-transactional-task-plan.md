# REFA-9. Extract `run_transactional(callable)` — sr-009 Transaction Wrapper Migration

**Task ref:** `REFA-9`
**Status:** draft (plan authored 2026-06-11 at initial-refactoring-plan closure; implementation not started)
**Origin:** REFA-1 finding 210 (high) — sr-009 violation deferred "to REFA-2" on 2026-06-07, never picked up. Registered as `current-debt.md` #25.
**Parent docs:** `wp-alt-context-initial-refactoring-plan.md` (closed), `refactoring-evaluation.md` H4 (duplicated transaction boilerplate; Fowler Ch8 Replace Inline Code with Function Call).
**Scope:** Behavior-preserving. PHP plugin only (`apps/prototype-wp-alt-context/src/`). No acx/v1 contract changes, no response-shape changes.

---

## Problem

sr-009 mandates that controller/service transactions route through a shared `run_transactional(callable)` wrapper. Today the wrapper does not exist; `grep -rn "run_transactional" src/` = 0 hits. Inline `START TRANSACTION` / `COMMIT` / `ROLLBACK` blocks exist in 11 files (current `main`, c057949e):

| File | Inline sites |
|---|---|
| `src/api/services/class-cluster-membership-service.php` | 3 |
| `src/api/services/class-cluster-lifecycle-service.php` | 2 |
| `src/api/services/class-cluster-merge-service.php` | 2 |
| `src/api/services/class-cluster-label-service.php` | 1 |
| `src/api/services/class-cluster-representative-service.php` | 1 |
| `src/api/services/class-cluster-split-service.php` | 1 |
| `src/api/services/class-tenant-local-rekey-service.php` | 1 |
| `src/api/class-api.php` | (verify count at task start) |
| `src/api/class-sync-status-controller.php` | (verify) |
| `src/sovereign/repositories/class-batch-run-repository.php` | (verify) |
| `src/sovereign/sync/class-conflict-resolution-service.php`, `class-snapshot-projector.php`, `class-split-topology-command-drain.php` | (verify) |

Re-grep at task start; counts drift.

## Why it was deferred (and why it needs its own slice)

Not a mechanical find-replace: the inline blocks interleave **post-commit side effects** (sync-marker updates, metrics refresh via `SyncStateRepository`, operation enqueue checks that trigger rollback) and **per-route rollback error messages**. A naive wrapper changes error codes or side-effect ordering and breaks the byte-perfect parity the REFA-1 characterization suite certifies.

## Approach

1. **Slice 1 — wrapper + one adopter.** Add `run_transactional( callable $operation )` (shape per `refactoring-evaluation.md` H4: START → try/COMMIT → catch/ROLLBACK, returning `WP_REST_Response|WP_Error`) in a shared location reachable by both `src/api/services/` and sovereign callers. Support per-call rollback error code/message so existing route-specific `WP_Error` codes are preserved verbatim. Migrate the simplest single-site adopter (`class-cluster-label-service.php`) first. Characterization tests must pass unchanged.
2. **Slice 2 — cluster mutation services.** Migrate the remaining `class-cluster-*-service.php` sites. Preserve: enqueue-failure → rollback semantics; post-commit sync-marker/metrics ordering (rg-002: never split an atomic write).
3. **Slice 3 — API/controller + sovereign callers.** Migrate `class-api.php`, `class-sync-status-controller.php`, repositories, and sync drains. Sovereign callers may return non-REST types — generalize the wrapper signature or add a thin variant rather than forcing `WP_Error` returns into sync code.
4. **Verification per slice:** existing characterization suites (REFA-1/4/6/7 goldens) + `composer test` + `composer phpstan` + `composer cs-check`. New unit tests for the wrapper itself: commit path, exception-rollback path, query-failure path.

## Constraints

- sr-009, rg-002 (atomic paths), rg-005 (no SQL edits without schema parity — this task should not touch SQL strings at all), rg-016 (autoload parity if a new `class-*.php` file is added: explicit `require_once` + `class_exists` verification).
- Two Hats: no behavior change; any error-message/code change is feature work and out of scope.
- Standard gates: branch isolation via `make task-start TASK=REFA-9`, MCP decisions per slice, review pass + `handoff_close_check(enforce=True)` pre-merge.

## Done when

`grep -rn "START TRANSACTION" src/` returns 0 sites outside `run_transactional` itself; all gates green at HEAD; characterization parity proven; debt #25 checked off in `current-debt.md`.
