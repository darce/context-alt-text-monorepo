# REFA-9. Extract `run_transactional(callable)` — sr-009 Transaction Wrapper Migration

> **Metadata**
>
> - **Date**: 2026-06-11
> - **Author**: fable (plan-analyze augmentation of 2026-06-11 draft)
> - **Project**: `apps/prototype-wp-alt-context`
> - **Task ID**: `REFA-9`
> - **Target Branch**: `feature/refa-9`
> - **Review Coverage Target**: 2

## Objective

Introduce one shared `run_transactional( callable )` wrapper and migrate the 10 raw inline `START TRANSACTION`/`COMMIT`/`ROLLBACK` blocks in the 6 cluster mutation services onto it, byte-for-byte behavior-preserving. Explicitly disposition the 8 remaining `START TRANSACTION` occurrences that already live behind local helper seams.

## Problem Statement

sr-009 mandates controller/service transactions route through a shared `run_transactional(callable)` wrapper. No such wrapper exists (`grep -rn "run_transactional" src/` = 0 hits). The REFA-1 service extraction copied the old controller's inline boilerplate verbatim into 6 services. Origin: REFA-1 finding 210 (high), deferred "to REFA-2" 2026-06-07, never owned; registered as `current-debt.md` #25.

## Current State Analysis

Verified at `feature/refa-9` HEAD (re-grep at implementation start; treat drift as a stop signal):
`grep -rn "START TRANSACTION" apps/prototype-wp-alt-context/src/` → **18 occurrences in 13 files**, in three distinct shapes:

**Shape A — raw inline, WP_Error returns (THE sr-009 violation; in scope, 10 sites / 6 files):**

| File | Lines | Sites |
|---|---|---|
| `src/api/services/class-cluster-label-service.php` | 76 | 1 |
| `src/api/services/class-cluster-lifecycle-service.php` | 54, 102 | 2 |
| `src/api/services/class-cluster-membership-service.php` | 92, 166, 281 | 3 |
| `src/api/services/class-cluster-merge-service.php` | 102, 228 | 2 |
| `src/api/services/class-cluster-representative-service.php` | 82 | 1 |
| `src/api/services/class-cluster-split-service.php` | 104 | 1 |

Pattern at every Shape-A site: `if ( false === $wpdb->query( 'START TRANSACTION' ) ) { return new WP_Error(...) }` → domain mutations with one or more early-`ROLLBACK`-and-return-`WP_Error` branches (e.g. merge-service lines 126, 233, 256) → in-transaction side effects (`SyncStateRepository::touch_local_curation_marker`) → `if ( false === $wpdb->query( 'COMMIT' ) ) { ROLLBACK; return WP_Error }` → post-commit side effects (`trigger_xmp_refresh_for_cluster_ids`) → `WP_REST_Response`.

**Shape B — already encapsulated in local throwing/callback helpers (NOT raw inline; out of migration scope, disposition in Slice 3):**

| File | Line(s) | Existing seam |
|---|---|---|
| `src/api/services/class-tenant-local-rekey-service.php` | 69 | `rekey_rows_transactionally()` private helper, throws `RuntimeException`, try/COMMIT/catch/ROLLBACK |
| `src/api/class-api.php` | 840 | private `begin/commit/rollback_database_transaction()` helper methods |
| `src/api/class-sync-status-controller.php` | 185 | throwing try/COMMIT/catch/ROLLBACK inside one method |
| `src/sovereign/repositories/class-batch-run-repository.php` | 598 | callback helper: `try { $callback(); COMMIT } catch { ROLLBACK; throw }` |
| `src/sovereign/sync/class-snapshot-projector.php` | 183, 218 | two callback helpers, throw `RuntimeException` |

**Shape C — divergent semantics (out of scope, disposition in Slice 3):**

| File | Line | Why divergent |
|---|---|---|
| `src/sovereign/sync/class-conflict-resolution-service.php` | 96 | returns result arrays (`['ok'=>false,'reason'=>...]`), not WP_Error |
| `src/sovereign/sync/class-split-topology-command-drain.php` | 727 | transaction is *optional* (`$transaction_started` guard), returns bool |

## Constraints

- **sr-009**: mutation paths route through shared wrapper; preserve `SyncStateRepository` metrics refresh on every mutation path.
- **rg-002**: never split an atomic write; the callable owns the entire current transaction body.
- **rg-005**: this task must not touch any SQL string. If a slice requires editing SQL, stop — scope is wrong.
- **rg-016**: any new `trait-*.php`/`class-*.php` under `src/` needs explicit `require_once` from the owning entrypoint + `php -r "require 'vendor/autoload.php'; var_export(trait_exists('AltContext\\\\Support\\\\RunsTransactional'));"` verification.
- **Two Hats**: behavior-preserving only. Any change to a `WP_Error` code, message, `status`, response shape, or side-effect ordering is feature work — out of scope. One deliberate, documented exception: see "Exception-path note" below.
- Greenfield: no compat shims; migrate each service fully in its slice.

## Workflow Principles

- Characterization first: the REFA-1 golden suite is the parity oracle; never proceed on a red bar.
- One service = one commit. Revert to last green if a diff is not byte-equivalent in behavior.
- Findings go to MCP via `review_findings`, never into this file.

## Terminology

- **Shape A/B/C**: the three transaction-site categories defined in Current State Analysis.
- **In-transaction side effect**: work that must run between START and COMMIT (e.g. `touch_local_curation_marker`).
- **Post-commit side effect**: work that must run only after a successful COMMIT (e.g. `trigger_xmp_refresh_for_cluster_ids`) — stays at the call site, *after* the wrapper returns.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/testing-php.md`
- Constitution anchors: sr-009, rg-002, rg-005, rg-016 (`docs/workbay/constitution.md`)
- Handoff/MCP: REFA-9 findings (`REFA-9-PA-01..05`), REFA-1 finding 210 (origin)
- Code anchors: `src/support/trait-batch-limits.php` (trait precedent: `namespace AltContext\Support`, consumed via `use AltContext\Support\BatchLimits;` + `use BatchLimits;` in `class-analysis-jobs-controller.php:31,43`); `src/api/class-cluster-mutations-controller.php:7-18` (require_once block precedent)
- No `ctx7` needed (WordPress `$wpdb` + PHPUnit only).

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `acx/v1` REST responses | PHP plugin | REFA-1 characterization fixtures | **none** | n/a — byte-identical | `ClusterMutationsCharacterizationTest` |

## Proposed Solution

New trait `src/support/trait-runs-transactional.php`:

```php
<?php
declare(strict_types=1);

namespace AltContext\Support;

use WP_Error;

trait RunsTransactional {
	/**
	 * Runs $operation inside a DB transaction.
	 * - START fails       → WP_Error( 'acx_db_error', $start_error, [ 'status' => 500 ] )
	 * - $operation returns WP_Error → ROLLBACK, return that WP_Error verbatim
	 * - $operation throws → ROLLBACK, rethrow
	 * - COMMIT fails      → ROLLBACK, WP_Error( 'acx_db_error', $commit_error, [ 'status' => 500 ] )
	 * - otherwise         → return $operation result unchanged
	 *
	 * @return mixed WP_Error or the callable's return value.
	 */
	private function run_transactional(
		callable $operation,
		string $start_error = 'Could not start local transaction.',
		string $commit_error = 'Could not commit local transaction.'
	) {
		global $wpdb;
		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', $start_error, array( 'status' => 500 ) );
		}
		try {
			$result = $operation();
		} catch ( \Throwable $throwable ) {
			$wpdb->query( 'ROLLBACK' );
			throw $throwable;
		}
		if ( is_wp_error( $result ) ) {
			$wpdb->query( 'ROLLBACK' );
			return $result;
		}
		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', $commit_error, array( 'status' => 500 ) );
		}
		return $result;
	}
}
```

Call-site mechanics at each Shape-A site (mechanical, same every time):

1. Add `use AltContext\Support\RunsTransactional;` import and `use RunsTransactional;` inside the class.
2. Move everything from after the START guard up to (and including) the in-transaction side effects into a closure: `$result = $this->run_transactional( function () use ( ... ) { ...; return $response_or_wp_error; } );`.
3. Every existing mid-transaction `ROLLBACK; return new WP_Error(...)` branch becomes plain `return new WP_Error(...)` inside the closure (wrapper performs the ROLLBACK).
4. The closure returns the `WP_REST_Response` (or final payload) that previously followed COMMIT-success.
5. Post-commit side effects stay *outside*, after the wrapper call, guarded exactly as today: `if ( ! is_wp_error( $result ) && $affected_rows > 0 ) { ...trigger_xmp_refresh... }`. Capture `$affected_rows` via `use ( &$affected_rows )` where the post-commit guard needs it.
6. **Before editing, diff the site's START/COMMIT error messages against the wrapper defaults**; if they differ, pass them as `$start_error`/`$commit_error` arguments. Messages must survive byte-identically.

**Exception-path note (deliberate, reviewed deviation):** current inline code has no try/catch — a mid-transaction exception today escapes with the transaction dangling. The wrapper adds ROLLBACK-and-rethrow. No test or caller depends on a dangling transaction; record this in the slice decision rationale. No other behavioral deltas are permitted.

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| support | `src/support/trait-runs-transactional.php` | NEW trait (code above) |
| entrypoint | `src/api/class-cluster-mutations-controller.php` | add `require_once __DIR__ . '/../support/trait-runs-transactional.php';` above the service requires (line ~7) |
| services | the 6 Shape-A files listed above | adopt wrapper at all 10 sites |
| tests | `tests/Unit/RunsTransactionalTest.php` | NEW unit tests for the trait itself |

## Related Files

| File | Note |
|---|---|
| `tests/Unit/ClusterMutationsCharacterizationTest.php` | parity oracle for all mutation routes |
| `tests/Unit/ClusterLabelServiceTest.php`, `ClusterMembershipServiceTest.php`, `ClusterMergeServiceTest.php` | per-service suites |
| `tests/Unit/ClusterMutationsControllerDualWriteTest.php` | dual-write path coverage |
| `composer.json` | classmap `[src/]` — run `composer dump-autoload` after adding the trait file |

## Verification Strategy

- Deterministic tests (every slice, from `apps/prototype-wp-alt-context/`):
  - `composer test` (full PHPUnit)
  - `composer phpstan`
  - `composer cs-check` (run `composer cs-fix` first per format-before-lint)
- Autoload parity (Slice 1 only): `composer dump-autoload && php -r "require 'vendor/autoload.php'; var_export(trait_exists('AltContext\\\\Support\\\\RunsTransactional'));"` → `true`; plus `php -l` on every touched file.
- Behavior parity: characterization + service suites green with **zero fixture changes** (`git status` must show no `tests/fixtures/` diffs).
- Completion grep: `grep -rn "START TRANSACTION" src/api/services/` → only Shape-B `class-tenant-local-rekey-service.php:69` remains (or zero if Slice 3 consolidates it).

## Slice Delivery

### Slice 1: Trait + first adopter (label service)

**Goal**: Land the wrapper with its simplest single-site adopter.

Changes:

- Add `src/support/trait-runs-transactional.php` exactly as specified; `require_once` in `class-cluster-mutations-controller.php`.
- Add `tests/Unit/RunsTransactionalTest.php`: commit path returns callable result; callable-WP_Error path rolls back + returns same instance; throw path rolls back + rethrows; COMMIT-false path rolls back + returns `acx_db_error`. Mock `$wpdb` per existing service-test conventions.
- Migrate `class-cluster-label-service.php:76` (one site; in-transaction `touch_local_curation_marker` stays in closure; post-commit `trigger_xmp_refresh_for_cluster_ids` stays outside).

Proof:

- `composer test && composer phpstan && composer cs-check`; autoload-parity check; `ClusterLabelServiceTest` + `ClusterMutationsCharacterizationTest` green, zero fixture diffs.

### Slice 2: Remaining 5 Shape-A services (9 sites)

**Goal**: Complete the sr-009 migration for all raw inline sites.

Changes (one commit per service, in this order — simplest first):

- `class-cluster-representative-service.php` (1 site: L82)
- `class-cluster-split-service.php` (1 site: L104)
- `class-cluster-lifecycle-service.php` (2 sites: L54, L102)
- `class-cluster-merge-service.php` (2 sites: L102, L228 — note 3 mid-transaction WP_Error/ROLLBACK branches at L126/L233/L256 become plain returns inside the closure)
- `class-cluster-membership-service.php` (3 sites: L92, L166, L281)

Proof:

- Full gate after each commit; completion grep shows 0 Shape-A sites; characterization suite green with zero fixture diffs.

### Slice 3: Shape-B/C disposition (decision, not migration)

**Goal**: Close debt #25 honestly — every remaining `START TRANSACTION` occurrence has a recorded disposition.

Changes:

- Record one MCP decision listing each Shape-B/C file with verdict `keep-local-helper` (default — they already satisfy sr-009's intent via encapsulation, and their throw/bool/array semantics don't fit the WP_Error wrapper) or `consolidate` (only if zero behavior delta is provable).
- Tick debt #25 in `docs/tasks/tech-debt/current-debt.md` with a pointer to that decision; note the Shape-B/C disposition inline in the entry.

Proof:

- Decision recorded; `current-debt.md` updated; final repo-wide grep documented in the decision rationale.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded backend-php + testing-php rules, constitution anchors (sr-009, rg-002, rg-005, rg-016), and REFA-9 findings before editing.
- [ ] Confirmed no `ctx7` dependency context needed.
- [ ] Confirmed no `acx/v1` contract change (characterization fixtures unchanged).

### Checklist for Slice 1: Trait + first adopter

- [ ] Trait file added with documented contract; require_once + autoload parity verified (rg-016).
- [ ] `RunsTransactionalTest` covers all four wrapper paths.
- [ ] Label service migrated; per-site error messages diffed against wrapper defaults before edit.
- [ ] Full gate green; zero fixture diffs; slice decision recorded with full 40-char SHA.

### Checklist for Slice 2: Remaining Shape-A services

- [ ] One commit per service in the stated order; gate green after each.
- [ ] All mid-transaction ROLLBACK branches converted to plain WP_Error returns inside closures.
- [ ] Post-commit side effects verified outside the wrapper at every site.
- [ ] Completion grep: 0 Shape-A sites; slice decision recorded.

### Checklist for Slice 3: Shape-B/C disposition

- [ ] Per-file disposition decision recorded in MCP.
- [ ] Debt #25 ticked in `current-debt.md` with decision pointer.

## Review Readiness

- [ ] No fixture or contract drift anywhere in the diff.
- [ ] Exception-path deviation documented in slice-1 decision rationale.
- [ ] Handoff decisions recorded per slice; review pass + `handoff_close_check(enforce=True)` before merge.

## Stretch Goals

- [ ] Consolidate `class-tenant-local-rekey-service.php` onto a throwing variant of the wrapper if a zero-delta migration is provable.

## Success Criteria

- [ ] `grep -rn "START TRANSACTION" src/api/services/` returns only documented Shape-B remainders (target: 1 or 0 occurrences).
- [ ] `run_transactional` exists once, in `AltContext\Support\RunsTransactional`, used by all 6 cluster mutation services.
- [ ] Full PHPUnit + phpstan + cs-check green at HEAD; characterization fixtures byte-identical.
- [ ] Debt #25 closed with disposition decision covering all 18 original occurrences.
