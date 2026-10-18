# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-15
> - **Author**: Claude (Opus 4.8)
> - **Owning Epic**: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md`
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-35`
> - **Review Coverage Target**: 2

---

## E15-35. Outbox Sync Resilience — backoff, bounded recovery, and conflict-storm dampening

## Objective

Make the sovereign curation-sync loop survive a transient recognition-backend incident without permanently dead-lettering a whole curation session. After this task, a short backend outage retries with exponential backoff over a bounded time window, an operator can bulk-recover dead-lettered pushes in one action, and a single regressed snapshot raises one actionable signal instead of one conflict row per curated entity.

## Problem Statement

A live curation session on tenant `4ddf8f36` (vlm site, :10018) produced **99 dead-lettered outbox pushes + 60 open projection conflicts** during a ~2-hour window (2026-07-15 23:53 → 2026-07-16 01:47) against prod `https://api.altcontext.com`. Triage confirmed a **transient backend incident** — a mix of 5xx (`remote_error` ×44) and malformed/short 200 responses whose `results` length ≠ ops sent (`unexpected_response` ×55) — **not** a contract drift (backend contract matches, `curation_router.py:69-75` `zip(..., strict=True)` guarantees length) and **not** auth (401/403 dead-letter at attempt 1; every failure here is retryable at attempt 5/5).

The incident became permanent damage because of four resilience gaps, all still present:

1. **No retry backoff.** Retryable failures return straight to `pending` and re-drain immediately (only the 300 s claim lease delays; `class-outbox-drain.php` has zero backoff). All 99 ops burned through the 5-attempt budget in minutes, so a brief blip = permanent dead-letter.
2. **Count-only terminal.** Terminal is `attempts >= DEFAULT_MAX_ATTEMPTS (5)` regardless of elapsed time (`class-outbox-drain.php:374-376`). A retryable class has no "keep trying for N hours" ceiling.
3. **Per-op recovery only.** `retry_failed_operation()` takes one `outbox_id` (`class-outbox-maintenance-service.php:232`); the Dead-Letter panel retries one row at a time (`DeadLetterPanel.tsx:137-146`). 99 rows is unrecoverable by hand.
4. **Conflict-storm amplification.** One regressed snapshot records one `curated_*` conflict per affected entity across **two** recorders → 40 `curated_cluster_deleted` (`class-snapshot-projector.php:516`) + 10 `curated_member_deleted` + 10 `member_cluster_reassignment` (`class-member-conflict-recorder.php:78`/`:48`, via `class-identity-member-snapshot-merger.php:100`) open rows for a single upstream event, with no auto-purge of open conflicts. (`class-snapshot-projector.php:557` is `record_person_name_conflicts`, a different code — not a storm site.)

Prod is healthy now, so the 99 retryable ops would very likely acknowledge on requeue — but nothing self-heals: failed rows never auto-retry past max and are never auto-purged.

## Constraints

- **Greenfield, no migration shims.** New outbox columns go directly into the outbox `CREATE TABLE` (`$outbox_sql`, `class-life-cycle-manager.php:660`). Existing installs heal through the plugin's real schema path — `LifeCycleManager::maybe_upgrade()` (`:91`) runs `dbDelta( $outbox_sql )` (`:738`) whenever the code version exceeds the stored `acx_version` option (`:22`), so **bump the plugin version constant** to fire the upgrade. There is **no `_ensure_columns` heal in the WP plugin** (that path lives in the recognition backend's identity Postgres, not here); do not hunt for it and do not hand-roll `ALTER TABLE`. Honor dbDelta's column-add caveats: one column per line, exactly two spaces after `PRIMARY KEY`, and types/casing that match dbDelta's normalization (nullable `datetime` cols) or dbDelta re-issues ALTERs on every load.
- **Concrete resilience tunables with fail-safe validation** (rg-008). Defaults: backoff `base=60s`, per-attempt `cap=3600s` (1h), `retry_window=24h` (primary terminal), `hard_cap=40` attempts (backstop); conflict-storm threshold fires when curated divergence is `>= 20` entities (absolute) **OR** `> 50%` of the tenant's curated clusters. **Window-first by construction:** the exponential ramp is `60,120,240,480,960,1920` (sum `3780s` ≈ 1.05h over attempts 1–6) then `3600s` per attempt, so cumulative wall-clock reaches the 24h window at **~attempt 29** — well before `hard_cap=40` (~35h, ~attempt 40) — giving an ~11-attempt / ~11h margin so the window is unambiguously the terminal that fires *without relying on jitter*, and the count is a true backstop for a wedged clock. (`hard_cap=12`, cumulative ~7h, would make count primary and the 24h window dead config — do not use it.) All are `apply_filters`-overridable, but each filtered value is validated at read time (finite, numeric, `> 0`; `hard_cap >= 1`) and falls back to the default when a filter returns an invalid value — a bad filter can never disable the terminal ceiling or the storm cap.
- **Plugin boundary only.** Changes confined to `apps/prototype-wp-alt-context/` and `apps/prototype-description-service/`. Never touch WP core, LocalWP config, or `~/Local Sites/`.
- **Idempotency is load-bearing.** Curation replays are idempotency-keyed; bulk requeue and backoff-retry must not double-apply. Preserve the CAS/compare-and-swap status guards on every status transition.
- **No behavior change for non-retryable failures.** Auth (401/403), validation (4xx), and invalid-payload results must still dead-letter immediately — backoff applies to the retryable class only.
- **Backoff must be bounded and stall-aware** (rg-007): a permanently-down backend must still reach a terminal state and stop consuming drain cycles.
- **Status enums centralized** (sr-007): reuse `OutboxStatus` / `ConflictResolutionStatus`; no new magic strings.
- **Build on REFA-6's landed shape.** REFA-6 (sync-drains Extract Class) is **already merged to `main`** — `OutboxQueryRepository` owns the read/claim surface (`load_pending_operations`), `OutboxMaintenanceService` owns admin ops (`retry_failed_operation`, `discard_operation`, `re_enqueue_with_current_base`), and `OutboxDrain` keeps thin public delegators for externally-consumed members. There is no merge-ordering race; new work lands in the post-extraction files and follows the thin-delegator convention (see Coordination note).

## Workflow Principles

- One contract owner: the batch curation-sync response shape stays owned by `curation_router.py`; this task does not change it.
- Delete-over-flag: prefer replacing the count-only terminal decision with a combined time+count ceiling rather than gating the old path behind a flag.
- Behavior + proof per slice: every slice lands a deterministic test that reproduces the incident condition and shows the new outcome.

## Terminology

- **Dead-letter**: an outbox row in terminal `OutboxStatus::FAILED`. Not a distinct enum — it is `failed` reached via non-retryable result or exhausted retry budget.
- **Retryable class**: dispatch results with `retryable = true` (5xx / 408 / 429 / transport/network / unexpected-shape 200).
- **Retry window**: wall-clock span from an op's first failure during which retryable attempts continue before the op is dead-lettered.
- **Conflict storm**: many `curated_*` projection conflicts recorded from a single snapshot projection because the incoming snapshot diverged from local curation across many entities.

## Current State Analysis

- **Works**: single-op dispatch, 409→conflict recording, idempotency replay cache on the backend, per-op retry/discard, daily purge of *acknowledged* outbox rows and *resolved* conflicts.
- **Broken/brittle**: retry cadence (no backoff), terminal policy (count-only), recovery ergonomics (per-op), conflict volume (per-entity storm). Open `failed` and open conflict rows have no TTL and no auto-recovery.
- **Misleading**: the workbench "Conflicts: N / Failed: N" counters read the cached `wp_acx_sync_state` row, which lagged the live tables during the incident (UI 59 vs live 60 open conflicts; UI 99 vs live 99 failed). Not a second bug, but the counter should reconcile on read (stretch).

## Target Outcome

A retryable failure schedules the next attempt at `now + backoff(attempts)` with jitter; the drain only claims `pending` rows whose `next_attempt_at` has elapsed, and reschedules itself for the earliest pending attempt. An op is dead-lettered only when it is non-retryable, OR its attempts exceed a hard cap, OR its first-failure age exceeds the retry window — so a sub-window outage recovers automatically and a sustained outage still terminates cleanly. The Dead-Letter panel offers "Retry all failed (N)" that requeues every failed row for the tenant in one guarded call. When a projection finds curated divergence above a configured threshold, the projector records a single aggregate "backend roster appears rolled back" conflict + degraded-mode banner instead of per-entity rows.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-php.md`, `docs/workbay/rules/testing-typescript.md`
- Contracts: `apps/prototype-description-service/roster/interface_adapters/http/curation_router.py` (batch response shape — unchanged, reference only)
- Handoff/MCP state: task ref `E15-35`; incident evidence recorded on the E15-35 handoff decision
- Epic phase: E15 Phase 6 (Local Sync Correctness / operator hardening), alongside E15-7/E15-13..17

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `POST /roster/curation/sync` (batch) | backend (recognition) | `curation_router.py:69-75` `{results:[...]}` len==ops | **none** — contract is correct; not the defect | no | existing router unit tests |
| Outbox drain ↔ `wp_acx_sync_outbox` schema | plugin (PHP) | cols per `class-life-cycle-manager.php:660-683` | add `next_attempt_at`, `first_failed_at` (nullable `datetime`) to `$outbox_sql` + bump plugin version so `maybe_upgrade()`→`dbDelta` heals installs | yes — existing installs healed via dbDelta, not migrated | dbDelta runtime column-heal check + drain unit tests |
| Dead-letter recovery REST (plugin-internal) | plugin (PHP + React) | per-op retry hook (`DeadLetterPanel.tsx:137`) | add bulk-retry route + hook | no (additive, plugin-internal) | PHP route test + TS mutation test |
| `curation_router.py` `zip(strict=True)` | backend (recognition) | raises → 500 on service-side length mismatch | **stretch**: return structured error, not 500 | no | router test (stretch) |

## Coordination and Dependencies

- **REFA-6 (sync-drains Extract Class) — already merged to `main`** (all 4 slices; `git log feature/refa-6 ^main` is empty; extracted classes present at this branch's base SHA). E15-35 builds directly on its post-extraction shape, so there is **no merge-ordering race**:
  - The claim/read surface (`load_pending_operations`, `find_operations_by_*`, `count_operations_by_status`) lives in `OutboxQueryRepository` (`class-outbox-query-repository.php`).
  - Admin ops (`retry_failed_operation`, `discard_operation`, `re_enqueue_with_current_base`) live in `OutboxMaintenanceService` (`class-outbox-maintenance-service.php`); `OutboxDrain` retains **thin public delegators** for those externally-consumed members (called by `class-conflict-controller.php` / `class-conflict-resolution-service.php` and overridden by `InMemoryOutboxDrain`/test doubles).
  - **E15-35 follows the same convention:** the three *in-place* edits — claim-gate in `OutboxQueryRepository::load_pending_operations()`, terminal decision in `OutboxDrain::apply_result()`, and the member-merge suppression flag — keep their current method signatures (behavior changes *inside* them). E15-35 also adds *new* additive surfaces: `OutboxMaintenanceService::retry_failed_operations_bulk()`, the two new outbox columns (Slice 1), and the `backend_roster_regressed` conflict-code branch (Slice 3). New public methods follow REFA-6's thin-delegator convention if a controller entry point is needed.

## Proposed Solution

Three independent, additively-verifiable slices, backend-first:

1. **Backoff + bounded terminal** in the outbox drain/claim path (the root amplifier).
2. **Bulk dead-letter recovery** surface (maintenance service → REST → panel) for fast operator recovery.
3. **Conflict-storm dampening** in the snapshot projector to collapse a mass-divergence event into one signal.

Slices are independent: each ships behavior + proof and can merge alone. Recommended merge order 1 → 2 → 3 (1 prevents recurrence; 2 recovers the current jam class; 3 tames the pull-side symptom).

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `src/support/class-life-cycle-manager.php` | Add `next_attempt_at datetime NULL`, `first_failed_at datetime NULL` to `$outbox_sql` (`:660`); bump the plugin version constant so `maybe_upgrade()` (`:91`) → `dbDelta` (`:738`) heals existing installs |
| backend | `src/sovereign/sync/class-outbox-drain.php` | In `apply_result()` (`:320`): on retryable failure set `first_failed_at` (if unset) + compute `next_attempt_at` (exponential + jitter); replace count-only terminal (`:374-376`) with combined time+count decision; schedule next drain at earliest pending attempt |
| backend | `src/sovereign/sync/class-outbox-query-repository.php` | In `load_pending_operations()` (`:228`, `WHERE status='pending' ORDER BY created_at ASC`): gate claim SELECT on `next_attempt_at IS NULL OR next_attempt_at <= now`; add bulk-requeue-failed query |
| backend | `src/sovereign/sync/class-outbox-maintenance-service.php` | Add `retry_failed_operations_bulk( tenant_id )` (reset `failed`→`pending`, attempts→0, clear error/`first_failed_at`) with **paced** `next_attempt_at` spread so requeued rows do not all fire in one drain cycle |
| backend | `src/api/class-sync-status-controller.php` | Add `POST` bulk-retry route (nonce + capability guarded) |
| backend | `src/sovereign/sync/class-snapshot-projector.php` | Pre-count curated **cluster AND member** divergence before the member merge (`:490/:516`, `:131`); above threshold enter degraded mode: record one aggregate conflict (counts + `backend_version` + code-partitioned entity map, capped with `entity_set_truncated`) + suppress the per-entity cluster storm; thread a suppression flag into the member merge |
| backend | `src/sovereign/repositories/interface-identity-members-repository.php` | Add an optional-defaulted storm-suppression param to `merge_snapshot_for_tenant()` (`:15`) — the projector calls the member merge through this interface, so the flag must cross it |
| backend | `src/sovereign/repositories/class-identity-members-repository.php` | Thread the suppression flag through the concrete delegating `merge_snapshot_for_tenant()` (`:69`) to the merger; optional default keeps the 2nd caller (projector `:251` `project_delta`) safe |
| backend | `src/sovereign/repositories/class-identity-member-snapshot-merger.php` | Accept + honor the storm-suppression flag at `:100` (and `:85`) so the member merge skips per-entity recording in a suppressed cycle |
| backend | `src/sovereign/repositories/class-member-conflict-recorder.php` | Honor the suppression flag: skip `curated_member_deleted` (`:78`) + `member_cluster_reassignment` (`:48`) per-entity rows while the projector suppresses; expose the divergence entity keys **per conflict code** so the projector's aggregate payload can persist the code-partitioned map |
| backend | `src/sovereign/sync/class-conflict-repository.php` | Support the aggregate `backend_roster_regressed` conflict code (record/list), incl. cross-cycle dedup (no new aggregate while one is open for the same `backend_version`) |
| backend | `src/sovereign/sync/class-conflict-resolution-service.php` | Three changes: (1) add `restore_local` to the resolution-string whitelist in `resolve()` (`:72`) **and** give it its own top-level dispatch branch (guarded to `conflict_code === backend_roster_regressed` + non-truncated set; anything else → `resolution_not_allowed`) beside the `accepted`/`accept_backend`/`merge` branches — `resolve_projection_acceptance()` only runs under `accepted\|accept_backend` (`:138`), so a branch buried inside it is unreachable; extend the return array with optional `restore_report` and update the `@return` docblock (`:58`); (2) inject `OutboxWriterInterface` as a fifth optional-defaulted ctor dependency (`:45-55`) — the seam for synthesizing re-push ops ([TEST-04], [REF-15]); (3) add a `backend_roster_regressed` branch to `resolve_projection_acceptance()` (`:327`) for the `accept_backend` direction. Without (3) the code falls through to `return false` → `entity_mutation_failed` (outbox_id=0 path), so the conflict can never clear |
| backend | `src/sovereign/sync/class-curation-idempotency-key.php` (new) | Shared idempotency-key derivation extracted from `ClusterMutationsController::derive_curation_idempotency_key()`/`format_idempotency_key()` (`class-cluster-mutations-controller.php:352`); consumed by both the controller and the `restore_local` synthesis path |
| backend | `src/api/class-cluster-mutations-controller.php` | Turn the private `derive_curation_idempotency_key()` (`:352`) + `format_idempotency_key()` into thin delegates to the extracted helper (no behavior change; existing idempotency keys must remain byte-identical — assert in tests) |
| frontend | `js/admin/pages/workbench/DeadLetterPanel.tsx` | "Retry all failed (N)" control with confirm, progress, zero-state guard |
| frontend | `js/admin/api/**` (recognition sync hooks) | `useBulkRetryOperations()` mutation + invalidation |
| frontend | `js/admin/pages/workbench/syncVocabulary.ts`, `DegradedModeBanner.tsx`/`degradedModeBannerLogic.ts` | Copy + surface for the backend-regression aggregate signal |
| tests | `apps/prototype-wp-alt-context/tests/**`, `js/admin/pages/workbench/__tests__/**` | Per-slice PHP + TS coverage |

## Related Files

| File | Note |
| --- | --- |
| `src/sovereign/sync/class-outbox-dispatcher.php` | `normalize_batch_response:348-392` marks all N ops `unexpected_response` on count mismatch; source of the 55 failures — retryable class this task retries with backoff |
| `js/admin/pages/workbench/syncPresentation.ts` | Renders `failed`/`conflict` counters from `SyncStatusResponse`; aggregate signal must map cleanly here |
| `wp_acx_sync_state` (cache row) | Powers UI counters; reconcile-on-read is a stretch, not core |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && composer test` (PHP: backoff schedule, claim gating, time+count terminal, bulk requeue guard, projector threshold)
  - `cd apps/prototype-wp-alt-context/js && npm test` (TS: bulk-retry button gating/zero-state, aggregate banner)
- Runtime-parity / environment checks:
  - Recognition-service suite via the remote gate if the router stretch lands: `make check-remote`
- Contract/fixture verification:
  - Runtime column-heal assertion: `php -r "require 'vendor/autoload.php'; ..."` confirms `next_attempt_at`/`first_failed_at` exist after heal on a pre-existing schema
- Manual verification:
  - Filter-injected transient failure (`acx_curation_sync_endpoint_path` / a test double) that returns 5xx then 200: op backs off and **acknowledges** within the window instead of dead-lettering
  - Dead-Letter panel shows "Retry all failed (N)"; clicking requeues all and count drops to 0
  - Projector fed a snapshot missing > threshold curated clusters records one aggregate conflict + banner, not N rows

## Slice Delivery

### Slice 1: Exponential backoff + bounded (time+count) retry terminal

**Goal**: A retryable failure retries with backoff over a bounded window; only non-retryable, attempt-cap, or window-age exhaustion dead-letters.

Changes:

- Add `next_attempt_at`, `first_failed_at` (`datetime NULL`) to `$outbox_sql` (`class-life-cycle-manager.php:660`) and bump the plugin version so `maybe_upgrade()` (`:91`) → `dbDelta` (`:738`) heals existing installs (no `_ensure_columns`, no hand-rolled `ALTER TABLE`).
- **Project the new columns in the claim read** (PR-09): `OutboxQueryRepository::load_pending_operations()`'s SELECT column list (`class-outbox-query-repository.php:237-238`) must gain `first_failed_at` (and `next_attempt_at`) — `apply_result()` operates only on the `$operation` array that SELECT returns, and `wpdb->update()` cannot express `COALESCE(first_failed_at, now)`, so the "set if unset" + window-age logic needs the value read out, not just gated in the WHERE.
- On retryable failure in `OutboxDrain::apply_result()` (`class-outbox-drain.php:320`): set `first_failed_at` if unset, compute `next_attempt_at = now + min(base * 2^(n-1), cap) + jitter` where `n = max(1, attempts)` is the **post-increment** attempt count (floor at 1 so a just-requeued `attempts=0` row uses the `base` delay, not `2^-1`); terminal when non-retryable OR `attempts >= hard_cap` OR `first_failed_at` older than `retry_window`.
- **Bounded, additive jitter** (PR-08): jitter is `+[0, 0.1 * delay]` (additive-only, never negative) so `next_attempt_at` is always strictly `> now` and a low-attempt retry can never schedule into the past and re-drain immediately.
- Concrete defaults (all `apply_filters`-overridable, each **validated fail-safe at read time**, rg-008): `base=60s`, `cap=3600s`, `retry_window=24h` (`86400s`, **primary terminal**, ~attempt 29), `hard_cap=40` (backstop, ~35h; see Constraints for the worked margin and why `12` would make the window dead config). A filter returning a non-finite/non-positive value falls back to the default — the terminal ceiling cannot be disabled.
- **Retire the superseded count ceiling** (PR-12, delete-over-flag): the old `acx_outbox_max_attempts=5` filter is replaced by the `hard_cap` filter; delete the old filter name rather than leaving it as dead code, and note the rename in the changelog.
- Gate the claim SELECT in `OutboxQueryRepository::load_pending_operations()` (`:228`) on elapsed `next_attempt_at` (`next_attempt_at IS NULL OR next_attempt_at <= now`) and reschedule the drain for the earliest pending attempt (`as_schedule_single_action`).

Proof:

- PHP unit tests: backoff schedule values + **jitter is bounded additive so `next_attempt_at > now` at `attempts=1`**; **window fires before hard_cap under defaults** (a row whose `first_failed_at` is 24h old terminates while `attempts < hard_cap`); **filter validation** (bad filter → default, ceiling still enforced); claim skips not-yet-due rows; retryable op that recovers before window → `acknowledged`; retryable op past window → `failed`; non-retryable → `failed` at attempt 1 (unchanged).

### Slice 2: Bulk dead-letter recovery surface

**Goal**: An operator requeues every failed push for a tenant in one guarded action.

Changes:

- `retry_failed_operations_bulk( tenant_id )` in `OutboxMaintenanceService` (CAS-guarded per row, idempotency preserved), following REFA-6's thin-delegator convention if a public `OutboxDrain` entry point is needed by the controller.
- **Paced requeue (avoids the incident's thundering herd, PA-05):** rather than clearing `next_attempt_at` to `NULL` on all rows, seed a spread `next_attempt_at` (e.g. `now + i * stride`, or bound the reset to a batch size) so the next drain does not dispatch all requeued ops in one cycle against a still-fragile backend. Slice-1 backoff then paces subsequent retries.
- Nonce + capability-guarded `POST` bulk-retry route on the sync-status controller.
- `useBulkRetryOperations()` hook + "Retry all failed (N)" control in `DeadLetterPanel.tsx` (confirm, progress, disabled at zero).

Proof:

- PHP test: bulk requeue resets only `failed` rows for the tenant → `pending`, attempts 0, error cleared; other tenants/statuses untouched.
- PHP test: **pacing** — after a bulk requeue of N rows, a single drain cycle claims strictly fewer than N (spread `next_attempt_at` keeps later rows not-yet-due).
- TS test: button reflects count, disabled at zero, invalidates query and clears the list on success.

### Slice 3: Projection conflict-storm dampening

**Goal**: A single mass-divergence snapshot raises one aggregate conflict + banner instead of one row per entity — covering **all three** `curated_*` storm codes (cluster deletion, member deletion, member reassignment), which the incident produced as 40 + 10 + 10 rows.

**Scope note (PR-01):** the three storm codes are recorded in **two** places, not one:
- `curated_cluster_deleted` — recorded directly in `class-snapshot-projector.php` (`:516`, gated on `get_curated_clusters_for_tenant` `:490/:538`).
- `curated_member_deleted` + `member_cluster_reassignment` — recorded in `class-member-conflict-recorder.php` (`:78`, `:48`), invoked from `class-identity-member-snapshot-merger.php:100` deep inside `members_repository->merge_snapshot_for_tenant()` (projector `:131`).

Per the operator decision, Slice 3 **covers both** so the full curated_* storm collapses to one signal (not only the cluster half).

Changes:

- **Pre-count across both surfaces before recording.** In `class-snapshot-projector.php`, before the member merge, pre-count curated-cluster divergence (already fetched) *and* curated-member divergence (add a curated-member fetch parallel to `get_curated_clusters_for_tenant`). If total divergence exceeds the storm threshold (`>= 20` absolute **OR** `> 50%` of the tenant's curated clusters, both filterable + fail-safe-validated per the Constraints), enter **degraded mode for the cycle**.
- **Thread a suppression flag into the member path.** Pass a "storm-suppressed" flag from the projector through `merge_snapshot_for_tenant()` / `class-identity-member-snapshot-merger.php` into `class-member-conflict-recorder.php` so the member recorder skips per-entity rows in the same cycle the projector suppresses cluster rows. Both surfaces must suppress together or the aggregate is a half-measure.
- **Record one aggregate `backend_roster_regressed` conflict** carrying `backend_version`, per-code counts, **and the affected entity keys partitioned by originating conflict code** (PR-03, PR3-02): `machine_payload = {backend_version, counts, entities: {curated_cluster_deleted: [cluster_uuid...], curated_member_deleted: [identity_uuid...], member_cluster_reassignment: [identity_uuid...]}}`. The partition is load-bearing — the resolver must route each key to cluster-vs-member reads and `operation_type`/`entity_type` synthesis, which a flat key set cannot express. **Bound the persisted set** (PR3-04, [RES-05]): cap total persisted keys at a filterable, fail-safe-validated max (default `2000`, rg-008); above the cap set an `entity_set_truncated` flag in the payload — a truncated aggregate disables `restore_local` (fail closed; operator uses `accept_backend` or Slice-2 bulk recovery) rather than silently restoring a subset.
- **Cross-cycle suppression (PR-06):** do not record a new `backend_roster_regressed` while an open one already exists for the same `backend_version` (and short-circuit per-entity recording while degraded mode is active). Otherwise every projection cycle re-records the aggregate → operator resolves → next cycle re-creates it (resolve-whack-a-mole, a recurrence of the stuck-forever failure).
- `class-conflict-repository.php` records/lists the aggregate code; frontend surfaces it as a degraded-mode banner.
- **Wire two resolution directions (PR-04, PR-07; revised for PR2-01/PR2-02):** the two directions take **structurally different paths** through `ConflictResolutionService::resolve()`:
  - **Reachability first (PR2-01):** `resolve()` whitelists the resolution *string* at `:72` (`accepted|dismissed|accept_backend|merge`) **before** any `conflict_code` logic, and `resolve_projection_acceptance()` only runs under the `accepted|accept_backend` branch (`:138`). `restore_local` must therefore be (a) added to the `:72` whitelist and (b) dispatched as its **own top-level branch** parallel to `merge`/`accept_backend` — a `restore_local` case inside `resolve_projection_acceptance()` is dead code by construction. **Code-guarded (PR3-03):** the branch's first check is `conflict_code === 'backend_roster_regressed'` (and `entity_set_truncated` not set); any other code — or a truncated aggregate — returns `resolution_not_allowed`, so whitelisting the string for all conflicts cannot turn `restore_local` into a silent no-op resolve of ordinary conflicts.
  - **`restore_local` (primary/recommended default; PR2-02):** the signal is "backend rolled back," so local curation is the good copy. There is **no existing re-enqueue primitive for this**: `re_enqueue_with_current_base()` (`class-outbox-maintenance-service.php:284`) requires an existing `outbox_id`, and a projector aggregate has `outbox_id=0`. The branch must **synthesize new outbox ops** via `OutboxWriter::enqueue()` (`class-outbox-writer.php:44`), injected as `OutboxWriterInterface` (fifth optional-defaulted ctor dep, `:45-55` — object seam for tests, [TEST-04]/[REF-15]). Per the persisted, code-partitioned entity map (PR3-02): fetch curated state **in bulk** — `get_curated_clusters_for_tenant()` (keyed by `cluster_uuid`) for the cluster partition and `get_curated_members_for_tenant()` (keyed by `identity_uuid`) for the member partitions, both on already-injected interfaces — then look each key up in the map ([RES-12]/[ALG-04]: two queries, not 2N `find_by_*` calls). Rebuild `operation_type` + payload in the same shape `ClusterMutationsController` enqueues for that entity type, and derive the idempotency key via the extracted shared helper (PR3-01: new `src/sovereign/sync/class-curation-idempotency-key.php`, a static/value helper owning the current `derive_curation_idempotency_key()` + `format_idempotency_key()` derivation; the controller's private methods become thin delegates to it — [NAME-05]) so a replayed resolution cannot double-apply ([RES-01], [DATA-13], [API-02]). An `entity_key` whose local curated state no longer exists is **skipped and counted**, reported via a new optional `restore_report` field — `array{enqueued:int, skipped:int, skipped_keys:string[]}` — added to `resolve()`'s return array with the `@return` docblock shape updated accordingly (PR3-05; `reason` stays `success`, its union gains no member); a partially-restorable set must not fail the whole resolution ([REF-20]). The synthesis loop is bounded by the recorded entity cap (PR3-04): the projector never persists more than the filterable max (default `2000`), and truncated aggregates were already refused above, so worst-case work per `resolve()` is two bulk reads + ≤cap enqueues. This makes `restore_local` materially heavier than `accept_backend`; the weight is the cost of the no-data-loss default.
  - **`accept_backend` (secondary):** accept the regressed backend roster as truth — flows through the existing `:138` branch into the new `backend_roster_regressed` case in `resolve_projection_acceptance()` (`:327`), applying the per-entity deletes/reassignments across the persisted entity set (the same mutations the per-code branches use) and clearing the conflict. (Fall-through note stands: an unrecognized code returns `false` → `entity_mutation_failed`, **not** `resolution_not_allowed`.)
  - Reuse `ConflictResolutionStatus` — no new magic strings (sr-007).

Proof:

- PHP projector test: snapshot missing > threshold curated **clusters and members** → one aggregate conflict, **zero per-entity rows across both the projector and the member recorder**; below threshold → per-entity behavior unchanged on both surfaces.
- PHP suppression test: with an open `backend_roster_regressed` for a `backend_version`, a second divergent projection cycle records **no** new aggregate and no per-entity rows.
- PHP resolution test — `restore_local`: `resolve()` returns `ok`, the row → resolved, **and the outbox contains newly synthesized re-push ops** (correct `operation_type`/payload per entity, idempotency keys matching the shared derivation) while local curated state is preserved — not a status-only no-op. Plus: an `entity_key` with no surviving local state is skipped and counted in `restore_report` without failing the batch; a second `resolve()` on the same conflict returns `already_resolved` and enqueues nothing (existing open-status CAS guard), and the derived idempotency keys make the backend replay cache absorb a double-pushed op ([RES-01], [DATA-13]).
- PHP guard tests — `restore_local` on a non-`backend_roster_regressed` conflict returns `resolution_not_allowed` (no rows touched); `restore_local` on a truncated aggregate (`entity_set_truncated`) returns `resolution_not_allowed`; the extracted idempotency-key helper produces byte-identical keys to the pre-extraction controller derivation (characterization, [TEST-03]).
- PHP resolution test — `accept_backend`: `resolve()` returns `ok`, the row → resolved, **and the affected local entities reflect the accepted backend roster** (assert the deletes/reassignments applied across the entity set).
- TS test: aggregate conflict renders the backend-regression banner copy with both resolution actions.

## Not Doing (Out of Scope)

- **Split-topology command drain backoff (`class-split-topology-command-drain.php`).** This parallel drain shares the same count-only terminal defect — `DEFAULT_MAX_ATTEMPTS=5` (`:57`) with a `attempts < resolve_max_attempts() ? applied : failed` decision (`:259-264`) and no backoff — so a transient blip can permanently dead-letter topology commands too. It is **deliberately out of scope** here because: (1) it was **not** implicated in the 2026-07-15 incident (that was the curation-sync outbox drain); (2) it is a materially different state machine (`applied`/`conflict`/`failed` with `reconcile_attempts`, over `wp_acx_topology_commands`, inside a transaction-bearing `apply_member_delta`), so it needs its own schema columns and its own terminal redesign — not a shared Slice-1 change; (3) folding it in would roughly double Slice 1 and couple two unrelated failure surfaces. **Follow-up: reserved ref `E15-36` (split-topology drain resilience)** — apply the same backoff + bounded time+count terminal to the topology drain; to be filed before that drain's resilience is needed for GA.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded PHP + TS guidelines, testing rules, and the curation-sync contract before editing.
- [ ] Recorded outbox-schema and dead-letter-REST boundary ownership + heal-not-migrate expectation.

### Checklist for Slice 1: Backoff + bounded terminal

- [ ] Columns added to `$outbox_sql` (`:660`) + plugin version bump; dbDelta runtime column-heal check passes on a pre-existing schema.
- [ ] Backoff/jitter compute + concrete fail-safe-validated tunables (base/cap/hard_cap/retry_window) + time+count terminal + claim gating + drain reschedule implemented.
- [ ] PHP tests cover recover-within-window, exhaust-by-window, exhaust-by-cap, non-retryable-immediate, and bad-filter-falls-back-to-default.

### Checklist for Slice 2: Bulk recovery

- [ ] `retry_failed_operations_bulk` (in `OutboxMaintenanceService`, paced `next_attempt_at` spread) + guarded REST route implemented.
- [ ] Dead-Letter panel "Retry all failed (N)" + hook implemented.
- [ ] PHP + TS tests cover requeue scoping, **pacing (single drain claims < N)**, zero-state, and list invalidation.

### Checklist for Slice 3: Storm dampening

- [x] Projector pre-counts curated cluster **and** member divergence; threshold (`>=20` OR `>50%`) + aggregate conflict (counts + `backend_version` + code-partitioned entity map, capped at the filterable max with `entity_set_truncated` flag) implemented.
- [x] Suppression flag threaded projector → snapshot-merger → member-conflict-recorder so both surfaces suppress per-entity rows in the same cycle.
- [x] Cross-cycle dedup: no new aggregate while an open one exists for the same `backend_version`.
- [x] Conflict repository + frontend banner support the aggregate code (both resolution actions).
- [x] `restore_local` reachable end-to-end: `:72` whitelist entry + top-level dispatch branch (code-guarded to `backend_roster_regressed`, non-truncated; else `resolution_not_allowed`) + `OutboxWriterInterface` ctor injection + bulk-read op synthesis via the extracted `class-curation-idempotency-key.php` helper; missing local state skipped and reported via `restore_report` (docblock updated), not fatal.
- [x] `accept_backend` wired as a `backend_roster_regressed` branch in `resolve_projection_acceptance()` (current-state failure is `entity_mutation_failed`, not `resolution_not_allowed`).
- [x] PHP + TS tests cover above/below threshold on **both** surfaces, cross-cycle suppression, and both resolution directions asserting **post-resolution data outcome**, not just status.

## Review Readiness

- [ ] No boundary-touching change without matching test/heal-check evidence.
- [ ] Runtime column-heal check included (schema change can be masked by fresh-install tests).
- [ ] Handoff decision records the incident evidence, the change, and verification per slice.

## Stretch Goals

- [ ] Reconcile `wp_acx_sync_state` counters on read so UI never lags live tables.
- [ ] Harden `curation_router.py` `zip(strict=True)` to return a structured error instead of 500 on service-side length mismatch.
- [ ] TTL/auto-triage for long-open conflicts (operator-configurable) so an unattended tenant self-clears stale rows.

## Success Criteria

- [ ] A simulated transient backend outage that recovers within the retry window ends with retryable ops `acknowledged`, zero new dead-letters.
- [ ] A sustained outage still terminates cleanly (bounded attempts/window), no unbounded drain churn.
- [ ] "Retry all failed (N)" requeues all failed pushes for a tenant in one action; count reaches 0 when prod is healthy.
- [ ] A snapshot missing > threshold curated entities (clusters **and** members) records exactly one aggregate conflict + banner — zero per-entity rows across both the projector and the member recorder — and that aggregate conflict is operator-resolvable in both directions (`restore_local` preserves/re-enqueues local curation; `accept_backend` applies the backend roster), with a repeat divergent cycle recording no duplicate aggregate.
