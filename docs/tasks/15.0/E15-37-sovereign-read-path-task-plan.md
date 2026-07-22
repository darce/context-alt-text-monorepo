# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-16
> - **Author**: Claude (Fable 5)
> - **Owning Epic**: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md`
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-37`
> - **Review Coverage Target**: 2
> - **Scope Brief**: `docs/tasks/15.0/E15-37-sovereign-read-path-scope.md`

---

## E15-37. Sovereign Read Path — local-first curated identities in the workbench

## Objective

Curated labels render from the local projection on first paint, with the machine offline, for any tenant that has ever curated. The remote recognition proxy becomes a cold-start enrichment only (tenant has no local projection rows yet), and when that enrichment fails the UI says so — it never renders "no people" for "couldn't reach the service". The media library stops paying WAN latency for data the plugin already owns.

## Problem Statement

The product invariant — the WP plugin owns sovereign curation ground truth ([DATA-14]: the local projection is the system of record for curated labels; the backend copy is derived) — is violated by the workbench read path. Two operator-visible symptoms (2026-07-16): (1) curated labels sometimes blank on initial media-library load, appearing only after refresh; (2) the media library is slow to refresh.

Root causes, all verified at branch base `83a89b70` (scope-brief anchors re-checked; two claims re-anchored, see Current State Analysis):

1. **Remote-by-default gate.** `MediaIdentitiesController::get_media_identities()` serves the local projection only when `should_use_local_projection()` passes (`src/api/class-media-identities-controller.php:86`, `:198-201`): the tenant's sync-state row must carry a snapshot version or updated-at (`src/api/class-abstract-recognition-proxy-controller.php:247-260`) **and** projection rows must exist. Cold start, a missing/stale sync-state row, or projection rows regressed by a bad snapshot (the E15-35 storm incident) silently routes the read to the **remote** service — curated ground truth becomes reachable only through the network.
2. **Transport failure renders as "no people".** On proxy failure the controller returns `identities_by_media: {}` + `data_source: 'unavailable'` with HTTP 200 (`class-media-identities-controller.php:109-117`) — the UI handles that envelope (see re-anchor below). But when the **client** aborts first — `fetchMediaIdentities` times out at 2 s (`js/admin/api/recognition/identityQueriesApi.ts:51`) and the hook sets `retry: false`, `staleTime: 15_000` (`js/admin/hooks/useMediaIdentities.ts:29-30`) — the query errors with no envelope at all, `identitiesDataSource` stays `undefined`, and every row renders the genuine-empty copy "No identities detected yet." (`js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx:98`). A slow remote (cold container, WAN) reads as data loss ([RLSE-05] silent failure the user believes is truth; [OBS-08] "no events" indistinguishable from "capture broken"). The 2 s bound itself is correct ([RES-02]); local-first sourcing is what makes it a non-event ([RES-03]).
3. **Read-path load.** The hook always prefetches the next media page (`js/admin/hooks/useWorkbenchMedia.ts:59-76`, unconditional on success), doubling per-view load on the WP endpoint whose per-attachment srcset/terms lookups are N+1 (`src/api/class-api.php:243-245`). The identities leg additionally crosses the WAN whenever the gate in (1) fails.

## Constraints

- **Read-path only; no schema change.** No new tables or columns. If review surfaces a schema need, it goes directly into the `CREATE TABLE` source and heals via `LifeCycleManager::maybe_upgrade()` → `dbDelta` with a plugin version bump — greenfield, no migration shims, no hand-rolled `ALTER TABLE` (per the E15-35 canonical wording). Not expected here.
- **No recognition-service contract change.** The `data_source` vocabulary (`local_projection` / `backend_proxy` / `endpoint_error` / `unavailable`) already exists on both sides of the boundary; this task reuses it. The backend `/recognition/media/identities` route is reference-only.
- **Envelope compatibility** ([API-09]): the `{identities_by_media, data_source}` response shape is unchanged; only *which source* answers changes. Gate broadening is additive — no read that serves local today may become remote.
- **Preserve atomic write paths** (rg-002): curation mutations, the outbox, and the snapshot projector are untouched. This task changes reads only.
- **Schema parity** (rg-005): the only SQL touched is existing read queries (`list_for_media_ids`, `has_projection_rows_for_tenant` — `src/sovereign/repositories/class-identity-members-read-repository.php:184/:243`); no new column references.
- **Status enums centralized** (sr-007): TS already owns `DATA_SOURCE` as a single `as const` object (`js/admin/api/recognition/types/dataSource.ts:1-8`). PHP scatters the same literals across three controllers (`class-media-identities-controller.php:24-26`, `class-clusters-controller.php:49-51`, `class-suggestions-controller.php:20-22`) plus config strings (`class-cluster-read-config.php:16`); Slice 1 centralizes them. No new magic strings anywhere.
- **Do not regress the 429 cooldown seam** (UXP-2/UXP-NET-1): the shared cooldown module is `js/admin/utils/recognitionCooldown.ts` — `gateRefetchInterval` documents that a `false` interval is cleared permanently on idle pages, so during cooldown it always returns a real delay (floored at 1 s); the clustering-poll base fn's `false` returns (error, nothing pending) are **inside** the gate by design (`useMediaIdentities.ts:34-39`) and stay. Slice-3 non-negotiables: no new `refetchInterval` path of any kind; the existing `gateRefetchInterval` wrapper is untouched; `error → false` inside the base fn stays; recovery is a `refetch()` from a cancellable effect only — never an interval.
- **Plugin boundary only.** Changes confined to `apps/prototype-wp-alt-context/`. Never touch WP core, LocalWP config, or `~/Local Sites/`.
- **Client retry semantics are owned by UXP-2's shared `retryPolicy`** ([RES-06], [API-08]) — **already in force app-wide, no slice-3 wiring**: `js/admin/utils/retryPolicy.ts` is merged on `main` and applied through the app `QueryClient` defaults (`appQueryClient.ts:28-32`). Slice 3 adds **no query-level `retry`/`retryDelay` option** to `useMediaIdentities`; the hook's `retry: false` (`useMediaIdentities.ts:29`) stays per its recorded exception comment (`:27-28`). E15-37's recovery is a one-shot deferred `refetch()` per error episode built on the existing `recognitionCooldown` seam (`runAfterCooldown` / `subscribeToCooldown` / `cooldownRemainingMs`) — not a second retry vocabulary and not a parallel timer module (Slice 3).

## Workflow Principles

- One vocabulary owner per side: `data_source` values live in exactly one PHP class and one TS module ([REF-19]); producers and consumers import, never re-declare.
- Behavior + proof per slice: every slice lands a deterministic test reproducing the symptom condition and showing the new outcome.
- Delete-over-flag: the sync-state conjunct is removed from the media-identities read gate, not hidden behind a filter.
- Backend-first merge order; each slice independently mergeable.

## Terminology

- **Local projection**: plugin-owned copies of clusters/members/persons (`wp_acx_*` tables) written by snapshot sync; joined with curated person names by `list_for_media_ids`.
- **Sovereign read**: a read served from the local projection without touching the network.
- **Cold start**: a tenant with zero local projection rows (never synced, never curated) — the only state where the remote proxy is the legitimate source.
- **Gate**: `should_use_local_projection*` — the decision of which source serves a read.
- **Degraded affordance**: UI state that names the unavailable enrichment instead of rendering an empty result ([RLSE-04]: error/offline are designed states).

## Current State Analysis

- **Works**: local projection query path (`list_for_media_ids` joins members → clusters → persons with `COALESCE(p.name, c.label)`, `class-identity-members-read-repository.php:184-241`); proxy resilience (bounded timeout + retry + circuit breaker, `class-abstract-recognition-proxy-controller.php:105-191`, [RES-15] already in place); the `data_source: 'unavailable'` envelope **is** distinguished by the UI when it arrives — `MediaSelection.tsx:142` threads `identityQuery.data?.data_source` into `IdentityClusterList.tsx:62-70`, which renders an `EmptyStateWarning` with a retry affordance instead of the empty copy.
- **Broken**: gate precondition (sync-state freshness is a *sync* concern used as a *read-availability* concern); client-abort path (no envelope → no `data_source` → degraded state indistinguishable from genuine empty); unconditional next-page prefetch.
- **Re-anchored from the scope brief** (both claims narrowed, neither invalidates the slices):
  - *"Frontend merges `identities ?? []` without distinguishing `data_source`"* — partially drifted. The merge itself (`useWorkbenchMedia.ts:49-57`) is source-blind, but the leaf component distinguishes the `unavailable` envelope (above). The real gap is the query-**error** path (2 s abort, `retry: false`), where no envelope exists. Slice 3 targets that path.
  - *"Three-request waterfall … independent legs are not joined ([PERF-10])"* — drifted. Detail and identities queries both key off `mediaIds` and fire in the same render tick (`useWorkbenchMedia.ts:41-47`); the legs are already joined. The remaining pipeline is two-stage (page → detail ∥ identities), which is structural: the ids are input to stage 2. Slice 4 is reframed to prefetch discipline; folding identities into the detail endpoint is a measured stretch ([PERF-06]).
- **Asymmetric sibling gate**: cluster reads gate on sync-state only — `ClusterProjectionSyncService::should_use_local_projection` (`src/api/services/class-cluster-projection-sync-service.php:59-83`) calls the same abstract gate helper and treats staleness as a background-refresh trigger (inline sync pull), not a read block; `ClusterReadService` consults it at five call sites (`class-cluster-read-service.php:53/:94/:202/:233/:264`). It has no rows conjunct, so the E15-35 wipe class (sync-state row lost) flips cluster reads remote too.
- **Already local end-to-end** (scope-brief open question resolved): the media-library "tags" surface reads `wp_get_object_terms(..., 'post_tag')` inside `Api::get_workbench_media()` (`class-api.php:245`) — pure local WP data, no recognition dependency, no treatment needed.
- **Cold-start convergence exists for clusters only — and its cron fallback is a no-op**: after a successful proxy read the cluster path bootstraps the projection via `maybe_bootstrap_after_proxy_read` (`class-cluster-projection-sync-service.php:85-108`) — **inline** `perform_bypass_cooldown` first, `wp_schedule_single_event` fallback only when the inline pull fails (same dedup at `class-cluster-read-service.php:144-145`). Two gaps: (a) the media-identities proxy path never triggers any bootstrap, so a tenant whose workbench only exercises this route never converges to sovereign reads; (b) the `acx_bootstrap_sync` handler is **never bound in cron context** — the only `add_action` lives in `ClustersController::__construct` (`class-clusters-controller.php:117`, hook name at `:48`), and that controller is constructed solely inside `RecognitionController::ensureProjectionControllers()` (`class-recognition-controller.php:330-421`), reached only through route resolvers during `rest_api_init` (`class-api.php:71` → `:176`). wp-cron requests never fire `rest_api_init`, so the scheduled fallback event dispatches to zero listeners and convergence silently never happens.

## Target Outcome

`GET /acx/v1/recognition/media-identities` serves the local projection whenever the tenant has any projection rows — sync-state row present, missing, or stale — and proxies only on true cold start, converging after a successful proxy read (inline bootstrap pull, cron-scheduled fallback whose handler is bound at plugin load) so the next read is local; a local read with missing/stale sync-state schedules the same async heal. Cluster reads qualify for local the same rows-first way. In the workbench, a failed or timed-out identities fetch renders the existing unavailable affordance (one-shot-per-error-episode deferred recovery plus the manual retry affordance), never the genuine-empty copy; previously loaded labels stay visible through a failed refetch. Next-page prefetch waits until the current page's stage-2 fetches finish. With Wi-Fi off, a curated tenant's media library shows curated labels on first load.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-php.md`, `docs/workbay/rules/testing-typescript.md`
- Contracts: `data_source` vocabulary — `js/admin/api/recognition/types/dataSource.ts` (TS side), producer constants in the three PHP controllers listed under Constraints
- Handoff/MCP state: task ref `E15-37`; scope brief committed at `83a89b70`
- Epic phase: E15 Local Sync Correctness, read-side counterpart to E15-35 (push-side) and E15-26 (boundary resilience)

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `GET acx/v1/recognition/media-identities` | plugin (PHP) | `{identities_by_media, data_source}`; source picked by sync-state ∧ rows | envelope unchanged; source picked by rows-first rule | yes — envelope byte-compatible, `data_source` values unchanged ([API-09]) | controller tests pin envelope + `data_source` semantics per source state |
| `should_use_local_projection_gate` helper | plugin (PHP, abstract controller) | sync-state snapshot/updated-at presence (`:247-260`) | helper unchanged; callers stop using it as a read precondition (media identities) or OR it with rows presence (clusters) | no (protected internal) | unit tests on both callers |
| `data_source` vocabulary PHP ↔ TS | plugin (both) | same 4 literals declared in 4 PHP sites + 1 TS module | PHP literals centralized into one constants class; values byte-identical | yes — rg-005 parity; TS untouched | grep-clean (no stray literals) + existing envelope tests pass unmodified ([TEST-03]) |
| `acx_bootstrap_sync` scheduled hook | plugin (PHP) | scheduled by cluster read path; handler bound only during `rest_api_init` (lazy controller construction) | handler registered unconditionally at plugin load (`Api::init()`); hook name moves to the shared constants surface; new scheduler call sites: media-identities cold-start fallback and stale-local heals | no (additive; hook name and handler behavior unchanged) | unit tests assert the handler is bound in cron context (plugin bootstrapped, `rest_api_init` never fired) and single-event dedup via `wp_next_scheduled` |
| Backend `/recognition/media/identities` | recognition service | proxied verbatim | **none** — reference only | no | existing proxy tests |

## Coordination and Dependencies

- **UXP-2 is merged on `main` — dependency satisfied, rebase note moot.** The shared client retry seam `js/admin/utils/retryPolicy.ts` (`shouldRetryRequest`/`getRetryDelay`, `RETRY_MAX_ATTEMPTS = 3`, `MAX_RETRY_DELAY_MS = 30_000`) is in force app-wide via the `QueryClient` defaults (`appQueryClient.ts:28-32`), and UXP-2's slice 2 shipped the shared cooldown module `js/admin/utils/recognitionCooldown.ts` gating the seven recognition pollers. The `useMediaIdentities` hook on this branch base already carries all three reconciled pieces: the retry-exception comment (`:27-28`), `retry: false` (`:29`), and the `gateRefetchInterval` wrapper (`:34`). Slice 3 keeps the exception and wires no query-level retry (see Constraints).
- **No-overlap check (verified 2026-07-22 against handoff): open findings on `MAINT-e21-5-postmerge-review-20260718` (5: GROK-01/S5-03 `resolveMergeSurvivor.ts`, S5-02 `useLiveReviewTarget.ts`, CFR-02/S4-04 PHP curation/envelope) and `E15-23-REV-A` (3: all `useWorkbenchFindings.ts`) touch none of this task's slice-3/4 files** (`useMediaIdentities.ts`, `useWorkbenchMedia.ts`, `MediaSelection.tsx`, `MediaSelectionTableBody.tsx`, `IdentityClusterList.tsx`). Do not bundle fixes for those findings — GROK-01 survivor-ranking especially — into slice-3/4 diffs; record incidental discoveries under their owning ref.
- **E15-35 (outbox resilience)** is plan-stage on `feature/e15-35`; no file overlap — E15-35 touches the outbox drain/projector (write side), E15-37 touches read controllers/hooks. The two protect the same projection rows from opposite sides; no merge-ordering constraint.
- **UXP-NET-1 (merged)** owns the 429 cooldown seam this task must not regress (Constraints).
- No REFA-* extraction in flight on these files at base `83a89b70`.

## Proposed Solution

Four independently mergeable slices, backend-first:

1. **Local-first gate inversion for media identities (PHP)** — rows-first source selection + cold-start bootstrap convergence + PHP `data_source` centralization (the root cause).
2. **Rows-first qualification for cluster reads (PHP)** — close the same wipe-class hole in the sibling gate, additively.
3. **Honest degraded identity state (TS)** — the client-abort path renders the unavailable affordance, keeps cached labels, recovers via a one-shot-per-error-episode deferred refetch on the `recognitionCooldown` seam (no query-level retry wiring).
4. **Read-path load discipline (TS)** — prefetch waits for the current page to settle.

Recommended merge order: 1 → 2 → 3 → 4 (UXP-2 already on `main`, see Coordination; 1 removes the WAN from curated reads; 2 extends the fix; 3 makes the residual cold-start failure honest; 4 trims load).

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `src/api/class-recognition-data-source.php` (new) | Final constants class owning the four `data_source` literals (sr-007, [REF-19]); mirrors TS `DATA_SOURCE` byte-for-byte; also owns the `acx_bootstrap_sync` hook-name constant (single declaration consumed by `ClustersController`, the media path, and the plugin-load handler registration) |
| backend | `src/api/class-media-identities-controller.php` | `should_use_local_projection()` (`:198-201`) → rows-first (drop sync-state conjunct); after successful proxy read, converge via inline pull with deduped cron fallback; schedule the async heal when serving locally with missing/stale sync-state; consts delegate to the shared class |
| backend | `src/api/class-api.php` | `Api::init()` (`:68-71`, runs at `plugins_loaded`) registers the `acx_bootstrap_sync` handler unconditionally so cron dispatch has a listener; callback composes the sync pull job lazily on first fire |
| backend | `src/api/class-clusters-controller.php`, `src/api/class-suggestions-controller.php`, `src/api/services/class-cluster-read-config.php` (construction site) | Replace duplicated `data_source` literals with the shared class (no behavior change) |
| backend | `src/api/services/class-cluster-projection-sync-service.php` | `should_use_local_projection()` (`:59-83`): qualify on gate **OR** `clusters_repository->has_projection_rows_for_tenant`; inline stale pull retained for the previously-qualifying path; newly-qualifying path heals via a scheduled single event (async) |
| frontend | `js/admin/hooks/useMediaIdentities.ts` | Keep `retry: false` (`:29`, UXP-2 exception rationale); add the one-shot-per-error-episode deferred refetch (per-query-key latch, `RECOVERY_DELAY_FLOOR_MS`) built on the `recognitionCooldown` seam; no query-level retry wiring |
| frontend | `js/admin/pages/workbench/MediaSelection.tsx`, `MediaSelectionTableBody.tsx`, `identity-clusters/IdentityClusterList.tsx` | Derive a single availability input for the leaf: the no-envelope query-error path maps to `DATA_SOURCE.UNAVAILABLE`; genuine-empty copy reserved for successful responses per the component's three-way empty branch |
| frontend | `js/admin/hooks/useWorkbenchMedia.ts` | Next-page prefetch gated fetch-level on current-page settle (`:59-76`) with a once-per-page-key dedup ref; **contract change**: `identitiesSurface` (`:99-107`) gains `isPlaceholderData` + `isFetching` |
| tests | `tests/Unit/MediaIdentitiesControllerTest.php`, `tests/Unit/RecognitionDataSourceTest.php` (new), `tests/Unit/ClusterReadServiceTest.php`, `js/admin/pages/workbench/__tests__/**`, hook tests | Per-slice coverage below |

## Related Files

| File | Note |
| --- | --- |
| `src/api/class-abstract-recognition-proxy-controller.php` | Gate helper (`:247-260`) stays for the clusters OR-path; `is_projection_stale` (`:307-323`) unchanged |
| `src/api/class-cluster-mutations-controller.php` | Unchanged. `should_proxy_mutation_to_backend` (`:274-277`) proxies mutations **remotely** when the tenant has no projection rows — that no-rows path is untouched here. The safety argument is scoped to rows-present tenants: local mutations validate their target against the projection (`get_projected_cluster_or_error` `:292-311`, `projection_not_ready` 409 at `:302-308`), so serving stale-but-local reads cannot enable an unsafe local mutation |
| `js/admin/utils/recognitionCooldown.ts` | Shared cooldown seam; not modified. `gateRefetchInterval` keeps wrapping the clustering poll (`useMediaIdentities.ts:34`). Exports Slice 3 may call: `runAfterCooldown`, `subscribeToCooldown`, `cooldownRemainingMs`, `isCoolingDown`, `DEFAULT_COOLDOWN_SECONDS` (and the existing `gateRefetchInterval` use). Recovery builds on this seam — no parallel timer vocabulary |
| `js/admin/utils/retryPolicy.ts` (merged, UXP-2) | Shared client retry seam already in force via `appQueryClient.ts:28-32`; reference-only — Slice 3 neither wires nor modifies it |
| `src/api/class-recognition-proxy-policy.php` | `post_scan_read` proxy policy (`:40-46`) — reference for the retry-budget statement; not modified |
| `src/api/class-api.php` | `get_workbench_media()` N+1 (`:243-245`) — measured stretch only ([PERF-06]) |

## Verification Strategy

- Provisioning before any TEST_CMD: `cd apps/prototype-wp-alt-context && composer install && npm ci` (PHPUnit runs from `vendor/bin`, the JS suite from `node_modules`). `tests/Unit/RecognitionDataSourceTest.php` is a **new** file introduced by Slice 1 — its filter match relies on the file existing, not on prior fixtures.
- Deterministic tests per slice (TEST_CMDs inline below; scoped filters locally — full suites belong on the remote gate via `make check-remote`).
- Manual/runtime-parity: LocalWP tenant with curated rows, Wi-Fi off → media library shows curated labels on first load, no degraded banner; cold tenant with service down → unavailable affordance, not "No identities detected yet"; the proxy seam is faked at the HTTP boundary in unit tests ([TEST-04] — the existing `queueHttpResponse` harness in `tests/Unit/MediaIdentitiesControllerTest.php` is the seam).
- Characterization before change ([TEST-03]): existing controller/service/UI tests must pass unmodified except where the test itself pinned the defective gate semantics; those updates are named in the slice.

## Slice Delivery

### Slice 1: Local-first gate inversion for media identities (PHP)

**Goal**: A tenant with any projection rows is served locally — sync-state row present, absent, or wiped — and a cold-start proxy read converges the projection (inline pull, cron-scheduled fallback with a handler that actually runs in cron) so the proxy is used at most transiently.

Changes:

- `MediaIdentitiesController::should_use_local_projection()` (`:198-201`): return `members_repository->has_projection_rows_for_tenant( $tenant_id )` alone; the sync-state conjunct is deleted (staleness is a sync concern — the projection rows *are* the ground truth, and a derived freshness marker must not veto the source of record, [DATA-14], [REF-09]). Empty-tenant guard preserved (the repository already short-circuits, `class-identity-members-read-repository.php:243-249`).
- After a **successful** backend-proxy read (200-normalized path only), converge by mirroring `maybe_bootstrap_after_proxy_read` (`class-cluster-projection-sync-service.php:85-108`): run the **inline** pull first; when the inline pull does not succeed (failed, unreachable, or cooldown-skipped), schedule `wp_schedule_single_event( time(), <hook>, array( $tenant_id ) )` guarded by `wp_next_scheduled` — same dedup as `class-cluster-read-service.php:144-145`. The unavailable path does neither (no point bootstrapping from a dead backend). Per review, the inline leg is cooldown-gated (`perform()`, not `perform_bypass_cooldown`) — a deliberate divergence from the cluster sibling's bypass: this runs on the visitor read path, so the pull job's failure cooldowns bound repeated pull cost during partial outages and its cooldown transient dedups cross-request retries, while a cooldown-skipped pull still lands on the cron fallback (whose handler, matching the cluster cron handler, performs the bypass pull). The inline pull is wrapped in a `Throwable` guard (mirroring `class-cluster-projection-sync-service.php:70-82`) so a throwing pull logs `acx_sync_pull_failed`, schedules the fallback, and never breaks the proxy response.
- Register the `acx_bootstrap_sync` handler **unconditionally at plugin load**, so the cron fallback actually executes: `add_action` in `Api::init()` (`class-api.php:68-71`, which runs on `plugins_loaded` via `AltContext::init()`, `src/class-alt-context.php:35-42`, hooked at `alt-context.php:305-309`), with a callback that composes the sync pull job lazily on first fire — no eager controller construction at load. Today the only binding is `ClustersController::__construct` (`class-clusters-controller.php:117`), reachable solely through `RecognitionController::ensureProjectionControllers()` (`class-recognition-controller.php:330-421`) during `rest_api_init`; wp-cron never fires `rest_api_init`, so scheduled events currently dispatch to zero listeners. The constructor binding stays (duplicate registration of distinct callbacks on the same hook is harmless; the handler itself is idempotent via the pull job's own cooldown/dedup).
- Staleness trigger on the local path: when the read serves locally **and** the sync-state row is missing or stale (`is_projection_stale`, `class-abstract-recognition-proxy-controller.php:307-323`), schedule the same deduped single event — async only, never an inline pull here: the local read must return immediately with the machine offline. Staleness bound: locally served data may lag the backend by up to `acx_sync_stale_threshold_seconds` (default 3600 s, floor 60 s — `:317-318`) plus WP-cron dispatch latency, converging when the now-cron-bound handler runs.
- Add `src/api/class-recognition-data-source.php` — final class, four public string constants matching `dataSource.ts:1-8` exactly, plus the `acx_bootstrap_sync` hook-name constant (one declaration site; `ClustersController` `:48`, the `Api::init()` registration, and the media-path schedulers all consume it). `MediaIdentitiesController`, `ClustersController`, `SuggestionsController` consts and the `ClusterReadConfig` construction strings delegate to it. Pure mechanical centralization (sr-007, [REF-19], rg-005 parity); zero behavior change, existing envelope tests pass unmodified ([TEST-03]).

Proof (TEST_CMD: `cd apps/prototype-wp-alt-context && vendor/bin/phpunit --filter 'MediaIdentitiesControllerTest|RecognitionDataSourceTest'`):

- Rows present + `NullSyncStateRepository` (no snapshot version, no updated-at — the incident state) → `data_source: local_projection`, labels from the repository, **zero HTTP requests issued** (the seam harness asserts no queued response consumed).
- Rows present + fresh sync-state → local (unchanged; existing test still passes).
- Rows present + missing/stale sync-state → local response **and** exactly one deduped heal event scheduled; zero synchronous HTTP.
- No rows + proxy success → `backend_proxy`, inline bootstrap pull performed in-request (pull-job spy); with the inline pull forced to fail, exactly one `acx_bootstrap_sync` single event scheduled and no duplicate on a second read with a queued event.
- No rows + proxy failure → `data_source: unavailable`, HTTP 200, no pull and nothing scheduled (existing test extended with the scheduling assertion).
- Handler bound in cron context: plugin surface bootstrapped with `rest_api_init` never fired, then `do_action( 'acx_bootstrap_sync', $tenant )` → the sync pull job performs (spy-asserted). This pins the plugin-load registration, not the REST-lazy one.
- Vocabulary test: shared-class constants byte-equal to the TS values (fixture-pinned). Grep-guard scope, exactly: scan `apps/prototype-wp-alt-context/src/**/*.php` (runtime code only — `tests/`, `vendor/`, and all JS excluded) for the four literals in declaration contexts only — `const … = '<literal>'` and hardcoded `'data_source' => '<literal>'` array values — allowing only `class-recognition-data-source.php` itself. The context restriction is deliberate: bare-word matching would false-positive on UI copy ("Identity data unavailable") and on the distinct `PROJECTION_STATUS` vocabulary, whose `available`/`bootstrapping`/`unavailable` values are out of scope.

### Slice 2: Rows-first qualification for cluster reads (PHP)

**Goal**: The E15-35 wipe class (sync-state row lost while projection rows survive) no longer flips cluster/label/member reads to the remote proxy.

Changes:

- `ClusterProjectionSyncService::should_use_local_projection()` (`:59-83`): qualify when the sync-state gate passes **OR** `clusters_repository->has_projection_rows_for_tenant( $tenant_id )` is true. Strictly additive broadening — every read that served local before still serves local ([API-09] applied to an internal decision surface); the "sync-state present, rows empty" state keeps its current local path, whose emptiness the existing targeted-repair machinery already handles (`class-cluster-read-service.php:162-168`, `:275-277`).
- Heal split by qualification path. The **previously-qualifying** state (sync-state gate passes, projection stale) keeps its existing inline pull unchanged (`:65-80`). The **newly-qualifying** state (gate fails, rows present) heals **async**: schedule one deduped `acx_bootstrap_sync` single event and return — never run the inline pull there, because that is precisely the state that must keep serving with the machine offline, and an inline pull would hold the read for the proxy timeout. Offline latency bound: the newly-qualifying local read issues zero synchronous HTTP; added cost is one `wp_next_scheduled` lookup plus at most one cron-event insert (local DB only) — the response returns immediately. (`get_last_updated` returning `null` maps to stale — `is_projection_stale`, `class-abstract-recognition-proxy-controller.php:307-310` — so the scheduled heal covers the missing-row case.)
- No change to `ClustersController`, mutation guards, or the abstract gate helper.

Proof (TEST_CMD: `cd apps/prototype-wp-alt-context && vendor/bin/phpunit --filter ClusterReadServiceTest`):

- Sync-state row absent + projection rows present → `list_clusters` serves local (zero synchronous HTTP / zero proxy calls, response matches the local `build_cluster_list_envelope` shape) and schedules exactly one deduped `acx_bootstrap_sync` heal event (no inline pull on this path).
- Sync-state row absent + no rows → proxy path unchanged (existing fixtures `tests/fixtures/clusters-read/*` pass unmodified).
- Existing stale-projection fixture (`list_clusters_stale_projection_sync`) passes unmodified ([TEST-03]).

### Slice 3: Honest degraded identity state (TS)

**Goal**: A failed or timed-out identities fetch is visually distinct from "this image has no people", previously loaded labels survive a failed refetch, and recovery from a transient failure is a one-shot-per-error-episode deferred refetch on the existing `recognitionCooldown` seam — no query-level retry wiring, no second retry vocabulary, no new interval.

Changes:

- Availability derivation: in `MediaSelection.tsx` (`:142`), the value threaded to the table becomes `DATA_SOURCE.UNAVAILABLE` when `identityQuery.isError` (no envelope exists on this path, so presentation must derive the state; this is a UI-state derivation, not envelope fabrication — the API layer still never invents `data_source`, rg-015 respected). Implement as a small named union/`as const` derivation (sr-007) rather than inline ternaries, so `IdentityClusterList` keeps a single `dataSource`-shaped input and its existing `unavailable` branch (`IdentityClusterList.tsx:62-70`) renders for the error path exactly as for the envelope. The component's empty state is a **three-way branch** the derivation must respect: `unavailable` → `EmptyStateWarning` "Identity data unavailable" / "We could not load identities for this media item right now." (`:62-70`); `endpoint_error` (BR-05) → `EmptyStateWarning` "Identity data unavailable" / "Recognition is reachable but returned an error. Please retry." (`:75-83`); empty `local_projection` (BR-09) → "No identities synced for this item yet." (`:90-96`); only an empty `backend_proxy`/unknown success falls through to "No identities detected yet." (`:98`). The client-error path maps to `UNAVAILABLE`, never `ENDPOINT_ERROR` — `endpoint_error` is reserved for the server-produced envelope. Retry affordance already wired (`MediaSelection.tsx:143`).
- State matrix (observable cells the derivation and tests must cover; requires extending `useWorkbenchMedia`'s `identitiesSurface` — currently `data`/`isLoading`/`isError`/`refetch`, `useWorkbenchMedia.ts:99-107` — with `isPlaceholderData` and `isFetching` as an explicit contract change):
  1. `isError` × no cached data for the current key → unavailable affordance (covers post-placeholder errors too: RQ applies placeholder only while `status === 'pending'`, `@tanstack/query-core` `queryObserver.js:265-284`, so on error the placeholder is dropped and `data` is `undefined`).
  2. `isError` × same-key cached data → cached labels keep rendering (React Query retains last-success `data` on the same key); no unavailable override, no row-level stale notice in this slice.
  3. pending + placeholder (`isPlaceholderData && isFetching`, key changed) → previous-key rows render only as placeholder per the existing UX; asserted: they never coexist with an error state (cell 1 takes over the moment the fetch errors).
  4. success × empty map → the genuine-empty branch for that `data_source` (three-way copy above).
- Recovery — per-query-key one-shot latch on the `recognitionCooldown` seam: on query error, arm the deferred refetch **at most once per error episode** — a ref keyed on the serialized query key that resets only on success or key change, never on a subsequent error (so error → deferred refetch → error again does **not** re-arm; the manual retry affordance is the only further path). Delay: `Math.max(cooldownRemainingMs(), RECOVERY_DELAY_FLOOR_MS)` — a named constant (derived from `DEFAULT_COOLDOWN_SECONDS`) supplies the floor because the dominant failure (2 s `TimeoutError`) never opens the cooldown (`isCooldownSignal` is 429/503-only), and an unfloored delay would refetch immediately. Implemented as a cancellable effect (cleared on unmount, key change, success) calling `refetch()` once — deferring to any active cooldown via the seam's `runAfterCooldown`/`cooldownRemainingMs`, not a parallel timer vocabulary. Non-negotiables (Constraints): `retry: false` stays (`useMediaIdentities.ts:29`); no query-level retry wiring; no new `refetchInterval` path; `gateRefetchInterval` wrapper untouched (`:34`); `error → false` inside the base fn stays.
- Degraded-state accessibility DoD ([RLSE-04], [A11Y-24] state-matrix, [A11Y-21] announce status): the unavailable affordance must have a keyboard-reachable retry control with an accessible name and role (pin the existing `EmptyStateWarning` button, accessible name "Retry", `EmptyStateWarning.tsx:25-29`) and announce its appearance via a live region (pin the existing `role="status"` `aria-live="polite"` container, `EmptyStateWarning.tsx:17`). Both asserted in the component test — if either attribute is removed upstream, the test fails.
- End-to-end retry budget (stated so review can audit amplification): the server proxy for this route runs the `post_scan_read` policy — **one** upstream attempt, zero server-side retries, 10 s timeout, circuit disabled (`class-recognition-proxy-policy.php:40-46`); the client's 2 s abort does **not** cancel the in-flight PHP request, which still completes (or times out) server-side. Client side: zero automatic query retries (`retry: false`) plus the one-shot deferred refetch → at most two automatic client requests per error episode, each mapping to at most one upstream attempt — no client × server retry multiplication, and the latch guarantees the episode terminates. Further attempts are user-initiated via the retry affordance.

Proof (TEST_CMD: `cd apps/prototype-wp-alt-context && npm test -- js/admin/pages/workbench js/admin/hooks`):

- **S3-T1 error-affordance**: identities fetch rejects/aborts, media + detail succeed → rows render the unavailable affordance ("Identity data unavailable") with the retry button; the genuine-empty copies do not appear ([RLSE-05], [OBS-08]).
- **S3-T2 branch-copy matrix**: pins the branch-distinguishing message text — empty `local_projection` → "No identities synced for this item yet."; empty `backend_proxy` → "No identities detected yet."; `endpoint_error` → "Recognition is reachable but returned an error. Please retry."; client error → the `unavailable` copy, not the `endpoint_error` copy.
- **S3-T3 cached-persistence**: successful load → failed refetch on the same key → previously rendered labels still visible (matrix cell 2).
- **S3-T4 placeholder-pending**: key change with placeholder rows held and the new key's fetch pending, then erroring → placeholder rows never render alongside the error state; unavailable affordance renders once the error lands (matrix cells 3 → 1).
- **S3-T5 one-shot latch**: query error arms exactly one deferred refetch (fake timers, delay ≥ `RECOVERY_DELAY_FLOOR_MS`); a **second consecutive error does NOT re-arm**; unmount or key change cancels; success resets the latch; query-level `retry` remains `false` (asserted) ([TEST-06]: assert the failing expectation first, [TEST-15]: prove the latch assertion can go red by re-arming in a broken variant).
- **S3-T6 a11y**: retry control found by accessible role+name (`getByRole('button', { name: 'Retry' })`), and the affordance container asserts `role="status"`/`aria-live="polite"` ([A11Y-24], [A11Y-21]).

### Slice 4: Read-path load discipline (TS)

**Goal**: First paint of a media page never competes with speculative next-page work; per-view request volume drops when the user does not paginate.

Changes:

- Gate the next-page prefetch effect (`useWorkbenchMedia.ts:59-76`) **fetch-level**: `detailQuery.isFetching === false && identitiesQuery.isFetching === false` in addition to `mediaQuery.isSuccess`. Status-level "settled (success/error, not pending)" is insufficient: both stage-2 queries carry `placeholderData: (previousData) => previousData` (`:44`, `useMediaIdentities.ts:31`), and RQ flips a placeholder-holding query to `status: 'success'` while the real fetch is still in flight (`@tanstack/query-core` `queryObserver.js:265-284`, installed 5.100.5 / pinned `^5.90.7`) — so on a page change the old gate would open immediately. `isFetching` is false only when no fetch is in flight, covering both first load and page transitions. totalPages guard unchanged. (The detail ∥ identities join already exists — `useWorkbenchMedia.ts:41-47` — so no leg-joining work remains; [PERF-10] is satisfied by the current shape and this slice only removes the speculative competitor.)
- Single-prefetch dedup mechanism (named, because `fetchQuery` runs with `staleTime` 0 by default and adding settle inputs to the effect deps re-runs it on every poll transition): a **once-per-page-key ref** covering `(page, perPage, search, status)` — the effect records the serialized next-page key after issuing its one `fetchQuery` and skips when the recorded key matches; the ref resets when the page key changes. (Alternative considered: `fetchQuery` `staleTime` matching the page cache lifetime; the ref is chosen for being observable in tests without cache-timing coupling.)
- Clustering poll (3 s, gated) unchanged. Server-side N+1 in `get_workbench_media()` deliberately untouched — local, and unmeasured ([PERF-06]); see Stretch.

Proof (TEST_CMD: `cd apps/prototype-wp-alt-context && npm test -- js/admin/hooks`):

- **S4-T1 no-speculative-fetch**: hook test with instrumented fetch spies: while detail/identities for page N are in flight, zero `fetchWorkbenchMedia(page N+1)` calls; after both `isFetching` flags clear, exactly one prefetch fires (call-count asserted on the spy).
- **S4-T2 page-change gate**: page N → N+1 transition with placeholder held (stage-2 status `'success'`, `isPlaceholderData: true`, fetch in flight) → no page-N+2 prefetch until both `isFetching` flags clear ([TEST-15]: this is the case the status-level gate passes wrongly — prove it red against that variant).
- **S4-T3 dedup under re-runs**: after settle and the single prefetch, force effect re-runs (e.g. the identities 3 s poll flipping `isFetching` true→false) → the prefetch spy's call count for page N+1 stays 1.
- Existing prefetch behavior test (if pinned) updated to the fetch-level condition — named here as the one intentional test change.

## Not Doing (Out of Scope)

- **Folding identities into `GET /workbench/media/detail`** (one fewer round trip, [RES-12]): deferred. With Slice 1 the identities leg is local and cheap for curated tenants, shrinking the win; folding also couples two responses with different cache lifetimes (identities invalidate on curation, details are immutable). Decide on measurement after this task lands — recorded as an open question for planning review.
- **Server N+1 in `Api::get_workbench_media()`** (`class-api.php:243-245`): local-only cost, no measurement yet ([PERF-06]). Stretch.
- **Outbox/push-side resilience** — E15-35. **Split-topology drain** — reserved E15-36.
- **Offline caching of remote-only data**: cold-start tenants legitimately need the network once.
- **Raising or removing the 2 s client timeout**: the bound is correct ([RES-02]); sovereignty, not patience, is the fix.
- **Changing `is_projection_stale` thresholds or the sync-pull cadence**: staleness policy is sync-side scope.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded PHP + TS guidelines and testing rules; confirmed `data_source` vocabulary sites on both sides before editing.
- [ ] Recorded boundary decision: envelope unchanged, source-selection semantics change server-side only.

### Checklist for Slice 1: Media-identities gate inversion

- [x] Rows-first `should_use_local_projection()`; sync-state conjunct deleted (not flagged).
- [x] Cold-start convergence after successful proxy read: inline pull first, deduped cron fallback via `wp_next_scheduled`; nothing on unavailable.
- [x] `acx_bootstrap_sync` handler registered at plugin load in `Api::init()`; cron-context binding test green.
- [x] Local reads with missing/stale sync-state schedule the async heal; hook name consumed from the shared constant everywhere.
- [x] `RecognitionDataSource` constants class (incl. hook-name constant) adopted at all four PHP declaration sites; TS parity test added with the scoped grep guard.
- [x] PHP tests cover rows-without-sync-state (zero HTTP), cold-start proxy + inline-pull convergence + fallback scheduling, unavailable envelope unchanged.

### Checklist for Slice 2: Cluster-read rows-first qualification

- [x] OR-broadened qualification in `ClusterProjectionSyncService`; inline stale pull retained for the previously-qualifying path; newly-qualifying path heals async (scheduled event, zero synchronous HTTP).
- [x] Existing clusters-read fixtures pass unmodified; new wipe-class test (rows present, sync-state absent → local).

### Checklist for Slice 3: Honest degraded state

- [ ] Query-error path renders the unavailable affordance via the existing `IdentityClusterList` `unavailable` branch; branch-distinguishing copy pinned (S3-T1, S3-T2).
- [ ] Cached labels persist through failed refetch; placeholder rows never coexist with the error state; `identitiesSurface` extended with `isPlaceholderData` + `isFetching` (S3-T3, S3-T4).
- [ ] Per-query-key one-shot recovery latch with `RECOVERY_DELAY_FLOOR_MS`; second consecutive error does not re-arm; `retry: false` kept; no query-level retry wiring; no new `refetchInterval` path; `gateRefetchInterval` wrapper untouched (S3-T5 + code review against Constraints — the wiring prohibitions are review-checked, non-gating in CI).
- [ ] A11y: retry control asserted by role+accessible name; `role="status"`/`aria-live` pinned on the affordance (S3-T6).
- [ ] Retry-budget statement re-audited against the landed diff (manual-only, non-gating).

### Checklist for Slice 4: Load discipline

- [ ] Prefetch gated on `isFetching === false` for detail + identities; no speculative fetch while page N stage-2 is in flight (S4-T1).
- [ ] Page-change transition with placeholder held issues no premature prefetch (S4-T2).
- [ ] Once-per-page-key dedup holds under effect re-runs — prefetch spy call count stays 1 (S4-T3).

## Review Readiness

- [ ] No boundary-touching change without a matching test asserting the envelope/`data_source` outcome.
- [ ] Each slice's decision recorded in handoff (`record_event`) with the verified full-SHA provenance before review.
- [ ] Manual offline proof captured (Wi-Fi off, curated tenant, labels on first paint) and referenced from the slice-complete decision.

## Stretch Goals

- [ ] Measure `get_workbench_media()` per-page latency (server timing log or query count) and batch the srcset/terms lookups only if it dominates ([PERF-06]).
- [ ] Row-level "showing local curation; service unreachable" notice for stale-but-present data (currently only the empty case gets an affordance).
- [ ] Evaluate folding identities into the detail endpoint with real measurements (see Not Doing).

## Success Criteria

- [ ] Curated tenant, sync-state row deleted, network down: media library renders curated labels on first load from the local projection — proven by unit test (zero HTTP) and manual offline check.
- [ ] Cold tenant, service down: workbench shows the unavailable affordance with retry (S3-T1); genuine-empty copy appears only for successful responses, per branch — "No identities synced for this item yet." for empty `local_projection`, "No identities detected yet." only for empty `backend_proxy`/unknown (S3-T2); manual offline check is corroborating, non-gating.
- [ ] Cold tenant, service up: first read proxies and **converges** — the inline pull populates projection rows in-request, or (inline pull failing) the fallback event's cron-bound handler performs the sync when fired without `rest_api_init` ever running; asserted on the follow-up read serving `local_projection` with rows present, not on `wp_next_scheduled`.
- [ ] Cluster/label/member reads survive the sync-state wipe class without flipping to the proxy.
- [ ] No next-page prefetch before both stage-2 `isFetching` flags clear, and exactly one prefetch per page key thereafter — proven by instrumented fetch-spy call-count assertions (S4-T1, S4-T2, S4-T3), not by a runtime request-count metric.
- [ ] All four `data_source` literals originate from exactly one PHP class and one TS module; grep finds no stray declarations.
