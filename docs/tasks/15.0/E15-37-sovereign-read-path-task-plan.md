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
2. **Transport failure renders as "no people".** On proxy failure the controller returns `identities_by_media: {}` + `data_source: 'unavailable'` with HTTP 200 (`class-media-identities-controller.php:109-117`) — the UI handles that envelope (see re-anchor below). But when the **client** aborts first — `fetchMediaIdentities` times out at 2 s (`js/admin/api/recognition/identityQueriesApi.ts:51`) and the hook sets `retry: false`, `staleTime: 15_000` (`js/admin/hooks/useMediaIdentities.ts:27-28`) — the query errors with no envelope at all, `identitiesDataSource` stays `undefined`, and every row renders the genuine-empty copy "No identities detected yet" (`js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx:55`). A slow remote (cold container, WAN) reads as data loss ([RLSE-05] silent failure the user believes is truth; [OBS-08] "no events" indistinguishable from "capture broken"). The 2 s bound itself is correct ([RES-02]); local-first sourcing is what makes it a non-event ([RES-03]).
3. **Read-path load.** The hook always prefetches the next media page (`js/admin/hooks/useWorkbenchMedia.ts:59-76`, unconditional on success), doubling per-view load on the WP endpoint whose per-attachment srcset/terms lookups are N+1 (`src/api/class-api.php:196`). The identities leg additionally crosses the WAN whenever the gate in (1) fails.

## Constraints

- **Read-path only; no schema change.** No new tables or columns. If review surfaces a schema need, it goes directly into the `CREATE TABLE` source and heals via `LifeCycleManager::maybe_upgrade()` → `dbDelta` with a plugin version bump — greenfield, no migration shims, no hand-rolled `ALTER TABLE` (per the E15-35 canonical wording). Not expected here.
- **No recognition-service contract change.** The `data_source` vocabulary (`local_projection` / `backend_proxy` / `endpoint_error` / `unavailable`) already exists on both sides of the boundary; this task reuses it. The backend `/recognition/media/identities` route is reference-only.
- **Envelope compatibility** ([API-09]): the `{identities_by_media, data_source}` response shape is unchanged; only *which source* answers changes. Gate broadening is additive — no read that serves local today may become remote.
- **Preserve atomic write paths** (rg-002): curation mutations, the outbox, and the snapshot projector are untouched. This task changes reads only.
- **Schema parity** (rg-005): the only SQL touched is existing read queries (`list_for_media_ids`, `has_projection_rows_for_tenant` — `src/sovereign/repositories/class-identity-members-read-repository.php:184/:243`); no new column references.
- **Status enums centralized** (sr-007): TS already owns `DATA_SOURCE` as a single `as const` object (`js/admin/api/recognition/types/dataSource.ts:1-8`). PHP scatters the same literals across three controllers (`class-media-identities-controller.php:24-26`, `class-clusters-controller.php:49-51`, `class-suggestions-controller.php:20-22`) plus config strings (`class-cluster-read-config.php:16`); Slice 1 centralizes them. No new magic strings anywhere.
- **Do not regress the 429 cooldown seam** (UXP-NET-1): `gateRefetchInterval` (`js/admin/utils/rateLimitCooldown.ts`) documents that a `false` interval freezes polling until a query event; the clustering-poll base fn's `false` returns are inside the gate by design. Slice 3 must not add a new bare-`false` polling path and must keep the cooldown gate wrapping any interval it touches.
- **Plugin boundary only.** Changes confined to `apps/prototype-wp-alt-context/`. Never touch WP core, LocalWP config, or `~/Local Sites/`.
- **Client retry stays bounded and 5xx/transport-only** ([RES-06], [API-08]): capped attempts, backoff, never retry a 4xx.

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

- **Works**: local projection query path (`list_for_media_ids` joins members → clusters → persons with `COALESCE(p.name, c.label)`, `class-identity-members-read-repository.php:184-241`); proxy resilience (bounded timeout + retry + circuit breaker, `class-abstract-recognition-proxy-controller.php:105-191`, [RES-15] already in place); the `data_source: 'unavailable'` envelope **is** distinguished by the UI when it arrives — `MediaSelection.tsx:134` threads `identityQuery.data?.data_source` into `IdentityClusterList.tsx:44-52`, which renders an `EmptyStateWarning` with a retry affordance instead of the empty copy.
- **Broken**: gate precondition (sync-state freshness is a *sync* concern used as a *read-availability* concern); client-abort path (no envelope → no `data_source` → degraded state indistinguishable from genuine empty); unconditional next-page prefetch.
- **Re-anchored from the scope brief** (both claims narrowed, neither invalidates the slices):
  - *"Frontend merges `identities ?? []` without distinguishing `data_source`"* — partially drifted. The merge itself (`useWorkbenchMedia.ts:49-57`) is source-blind, but the leaf component distinguishes the `unavailable` envelope (above). The real gap is the query-**error** path (2 s abort, `retry: false`), where no envelope exists. Slice 3 targets that path.
  - *"Three-request waterfall … independent legs are not joined ([PERF-10])"* — drifted. Detail and identities queries both key off `mediaIds` and fire in the same render tick (`useWorkbenchMedia.ts:41-47`); the legs are already joined. The remaining pipeline is two-stage (page → detail ∥ identities), which is structural: the ids are input to stage 2. Slice 4 is reframed to prefetch discipline; folding identities into the detail endpoint is a measured stretch ([PERF-06]).
- **Asymmetric sibling gate**: cluster reads gate on sync-state only — `ClusterProjectionSyncService::should_use_local_projection` (`src/api/services/class-cluster-projection-sync-service.php:59-83`) calls the same abstract gate helper and treats staleness as a background-refresh trigger (inline sync pull), not a read block; `ClusterReadService` consults it at five call sites (`class-cluster-read-service.php:53/:94/:202/:233/:264`). It has no rows conjunct, so the E15-35 wipe class (sync-state row lost) flips cluster reads remote too.
- **Already local end-to-end** (scope-brief open question resolved): the media-library "tags" surface reads `wp_get_object_terms(..., 'post_tag')` inside `Api::get_workbench_media()` (`class-api.php:196`) — pure local WP data, no recognition dependency, no treatment needed.
- **Cold-start convergence exists for clusters only**: after a successful proxy read the cluster path bootstraps the projection (`maybe_bootstrap_after_proxy_read`, `class-cluster-projection-sync-service.php:85-108`; scheduler fallback `class-cluster-read-service.php:144-145` on hook `acx_bootstrap_sync`, registered at `class-clusters-controller.php:48/:117`). The media-identities proxy path never schedules a bootstrap, so a tenant whose workbench only exercises this route never converges to sovereign reads.

## Target Outcome

`GET /acx/v1/recognition/media-identities` serves the local projection whenever the tenant has any projection rows — sync-state row present, missing, or stale — and proxies only on true cold start, scheduling a bootstrap sync after a successful proxy read so the next read is local. Cluster reads qualify for local the same rows-first way. In the workbench, a failed or timed-out identities fetch renders the existing unavailable affordance (with bounded retry), never the genuine-empty copy; previously loaded labels stay visible through a failed refetch. Next-page prefetch waits until the current page's queries settle. With Wi-Fi off, a curated tenant's media library shows curated labels on first load.

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
| `acx_bootstrap_sync` scheduled hook | plugin (PHP) | scheduled by cluster read path only | additional scheduler call site after successful media-identities proxy read | no (additive; handler unchanged) | unit test asserts single-event scheduled, deduped via `wp_next_scheduled` |
| Backend `/recognition/media/identities` | recognition service | proxied verbatim | **none** — reference only | no | existing proxy tests |

## Coordination and Dependencies

- **E15-35 (outbox resilience)** is plan-stage on `feature/e15-35`; no file overlap — E15-35 touches the outbox drain/projector (write side), E15-37 touches read controllers/hooks. The two protect the same projection rows from opposite sides; no merge-ordering constraint.
- **UXP-NET-1 (merged)** owns the 429 cooldown seam this task must not regress (Constraints).
- No REFA-* extraction in flight on these files at base `83a89b70`.

## Proposed Solution

Four independently mergeable slices, backend-first:

1. **Local-first gate inversion for media identities (PHP)** — rows-first source selection + cold-start bootstrap convergence + PHP `data_source` centralization (the root cause).
2. **Rows-first qualification for cluster reads (PHP)** — close the same wipe-class hole in the sibling gate, additively.
3. **Honest degraded identity state (TS)** — the client-abort path renders the unavailable affordance, keeps cached labels, retries boundedly.
4. **Read-path load discipline (TS)** — prefetch waits for the current page to settle.

Recommended merge order 1 → 2 → 3 → 4 (1 removes the WAN from curated reads; 2 extends the fix; 3 makes the residual cold-start failure honest; 4 trims load).

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `src/api/class-recognition-data-source.php` (new) | Final constants class owning the four `data_source` literals (sr-007, [REF-19]); mirrors TS `DATA_SOURCE` byte-for-byte |
| backend | `src/api/class-media-identities-controller.php` | `should_use_local_projection()` (`:198-201`) → rows-first (drop sync-state conjunct); schedule `acx_bootstrap_sync` after successful proxy read; consts delegate to the shared class |
| backend | `src/api/class-clusters-controller.php`, `src/api/class-suggestions-controller.php`, `src/api/services/class-cluster-read-config.php` (construction site) | Replace duplicated `data_source` literals with the shared class (no behavior change) |
| backend | `src/api/services/class-cluster-projection-sync-service.php` | `should_use_local_projection()` (`:59-83`): qualify on gate **OR** `clusters_repository->has_projection_rows_for_tenant`; stale-triggered inline pull retained |
| frontend | `js/admin/hooks/useMediaIdentities.ts` | Bounded retry (transport/5xx only, capped, backoff — [RES-06], [API-08]); expose error state unchanged |
| frontend | `js/admin/pages/workbench/MediaSelection.tsx`, `MediaSelectionTableBody.tsx`, `identity-clusters/IdentityClusterList.tsx` | Derive a single availability input for the leaf: query error (no envelope) renders the same unavailable affordance as `data_source: 'unavailable'`; genuine empty copy reserved for successful local/proxy responses |
| frontend | `js/admin/hooks/useWorkbenchMedia.ts` | Next-page prefetch gated on current-page queries settled (`:59-76`) |
| tests | `tests/Unit/MediaIdentitiesControllerTest.php`, `tests/Unit/ClusterReadServiceTest.php`, `js/admin/pages/workbench/__tests__/**`, hook tests | Per-slice coverage below |

## Related Files

| File | Note |
| --- | --- |
| `src/api/class-abstract-recognition-proxy-controller.php` | Gate helper (`:247-260`) stays for the clusters OR-path; `is_projection_stale` (`:307-323`) unchanged |
| `src/api/class-cluster-mutations-controller.php` | Mutation-side rows guards (`:275-276`, `:302`) unchanged — mutations already require local rows, so serving stale-but-local topology reads cannot enable an unsafe mutation |
| `js/admin/utils/rateLimitCooldown.ts` | Cooldown gate wrapping the clustering poll — must keep wrapping it |
| `src/api/class-api.php` | `get_workbench_media()` N+1 (`:196`) — measured stretch only ([PERF-06]) |

## Verification Strategy

- Deterministic tests per slice (TEST_CMDs inline below; scoped filters locally — full suites belong on the remote gate via `make check-remote`).
- Manual/runtime-parity: LocalWP tenant with curated rows, Wi-Fi off → media library shows curated labels on first load, no degraded banner; cold tenant with service down → unavailable affordance, not "No identities detected yet"; the proxy seam is faked at the HTTP boundary in unit tests ([TEST-04] — the existing `queueHttpResponse` harness in `tests/Unit/MediaIdentitiesControllerTest.php` is the seam).
- Characterization before change ([TEST-03]): existing controller/service/UI tests must pass unmodified except where the test itself pinned the defective gate semantics; those updates are named in the slice.

## Slice Delivery

### Slice 1: Local-first gate inversion for media identities (PHP)

**Goal**: A tenant with any projection rows is served locally — sync-state row present, absent, or wiped — and a cold-start proxy read schedules projection bootstrap so the proxy is used at most transiently.

Changes:

- `MediaIdentitiesController::should_use_local_projection()` (`:198-201`): return `members_repository->has_projection_rows_for_tenant( $tenant_id )` alone; the sync-state conjunct is deleted (staleness is a sync concern — the projection rows *are* the ground truth, and a derived freshness marker must not veto the source of record, [DATA-14], [REF-09]). Empty-tenant guard preserved (the repository already short-circuits, `class-identity-members-read-repository.php:243-249`).
- After a **successful** backend-proxy read (200-normalized path only, mirroring `maybe_bootstrap_after_proxy_read`'s status check), schedule `wp_schedule_single_event( time(), 'acx_bootstrap_sync', array( $tenant_id ) )` guarded by `wp_next_scheduled` — same dedup pattern as `class-cluster-read-service.php:144-145`. The unavailable path schedules nothing (no point bootstrapping from a dead backend).
- Add `src/api/class-recognition-data-source.php` — final class, four public string constants matching `dataSource.ts:1-8` exactly. `MediaIdentitiesController`, `ClustersController`, `SuggestionsController` consts and the `ClusterReadConfig` construction strings delegate to it. Pure mechanical centralization (sr-007, [REF-19], rg-005 parity); zero behavior change, existing envelope tests pass unmodified ([TEST-03]).

Proof (TEST_CMD: `cd apps/prototype-wp-alt-context && vendor/bin/phpunit --filter 'MediaIdentitiesControllerTest|RecognitionDataSourceTest'`):

- Rows present + `NullSyncStateRepository` (no snapshot version, no updated-at — the incident state) → `data_source: local_projection`, labels from the repository, **zero HTTP requests issued** (the seam harness asserts no queued response consumed).
- Rows present + fresh sync-state → local (unchanged; existing test still passes).
- No rows + proxy success → `backend_proxy` **and** exactly one `acx_bootstrap_sync` single event scheduled; second read with a queued event schedules no duplicate.
- No rows + proxy failure → `data_source: unavailable`, HTTP 200, nothing scheduled (existing test extended with the scheduling assertion).
- Vocabulary test: shared-class constants byte-equal to the TS values (fixture-pinned), and a repo-wide grep in the test guards against stray re-declared literals.

### Slice 2: Rows-first qualification for cluster reads (PHP)

**Goal**: The E15-35 wipe class (sync-state row lost while projection rows survive) no longer flips cluster/label/member reads to the remote proxy.

Changes:

- `ClusterProjectionSyncService::should_use_local_projection()` (`:59-83`): qualify when the sync-state gate passes **OR** `clusters_repository->has_projection_rows_for_tenant( $tenant_id )` is true. Strictly additive broadening — every read that served local before still serves local ([API-09] applied to an internal decision surface); the "sync-state present, rows empty" state keeps its current local path, whose emptiness the existing targeted-repair machinery already handles (`class-cluster-read-service.php:162-168`, `:275-277`).
- Stale-triggered inline sync pull retained unchanged (`:65-80`) — under rows-first it now also fires for tenants whose sync-state row is missing, which is exactly the state that should self-heal. Guard: `get_last_updated` returning `null` already maps to stale (`is_projection_stale`, `class-abstract-recognition-proxy-controller.php:307-310`).
- No change to `ClustersController`, mutation guards, or the abstract gate helper.

Proof (TEST_CMD: `cd apps/prototype-wp-alt-context && vendor/bin/phpunit --filter ClusterReadServiceTest`):

- Sync-state row absent + projection rows present → `list_clusters` serves local (`data_source: local_projection`), no proxy call, and the stale path triggers one inline sync-pull attempt.
- Sync-state row absent + no rows → proxy path unchanged (existing fixtures `tests/fixtures/clusters-read/*` pass unmodified).
- Existing stale-projection fixture (`list_clusters_stale_projection_sync`) passes unmodified ([TEST-03]).

### Slice 3: Honest degraded identity state (TS)

**Goal**: A failed or timed-out identities fetch is visually distinct from "this image has no people", previously loaded labels survive a failed refetch, and transient failures retry boundedly.

Changes:

- Availability derivation: in `MediaSelection.tsx` (`:134`), the value threaded to the table becomes unavailable-shaped when `identityQuery.isError` (no envelope exists on this path, so presentation must derive the state; this is a UI-state derivation, not envelope fabrication — the API layer still never invents `data_source`, rg-015 respected). Implement as a small named union/`as const` derivation (sr-007) rather than inline ternaries, so `IdentityClusterList` keeps a single `dataSource`-shaped input and its existing `unavailable` branch (`IdentityClusterList.tsx:44-52`) renders for both the envelope and the error path. Retry affordance already wired (`MediaSelection.tsx:135`).
- Cached-label persistence: React Query retains last-success `data` for an errored query on the same key, so labels persist through a failed refetch automatically — pin it with a test, and ensure the derivation only overrides to unavailable when there is **no data to show** (rows with cached identities keep rendering them; the row-level notice is not added for stale-but-present data in this slice).
- Bounded retry in `useMediaIdentities` (`:27`): replace `retry: false` with a capped policy — max 2 retries, exponential delay, and never retry HTTP 4xx ([RES-06], [API-08]); timeout/abort and 5xx-shaped failures are the retryable class. The clustering `refetchInterval` gate is untouched, stays wrapped in `gateRefetchInterval`, and no new code path returns a bare `false` interval outside the existing design (Constraints).

Proof (TEST_CMD: `cd apps/prototype-wp-alt-context && npm test -- js/admin/pages/workbench js/admin/hooks`):

- Integration test (identities fetch rejects/aborts, media + detail succeed): rows render the unavailable affordance ("Identity data unavailable") with retry button — the genuine-empty copy does not appear ([RLSE-05], [OBS-08]).
- Genuine empty (200, `data_source: local_projection`, empty map) → "No identities detected yet." (unchanged).
- Timeline test: successful load → failed refetch on the same key → previously rendered labels still visible.
- Retry policy unit test: 4xx not retried; abort/5xx retried at most twice with growing delay ([TEST-06]: assert the failing expectation first).

### Slice 4: Read-path load discipline (TS)

**Goal**: First paint of a media page never competes with speculative next-page work; per-view request volume drops when the user does not paginate.

Changes:

- Gate the next-page prefetch effect (`useWorkbenchMedia.ts:59-76`) on the current page's stage-2 queries having settled (detail and identities success/error, not pending) in addition to `mediaQuery.isSuccess`. Prefetch still fires once per page key thereafter; totalPages guard unchanged. (The detail ∥ identities join already exists — `useWorkbenchMedia.ts:41-47` — so no leg-joining work remains; [PERF-10] is satisfied by the current shape and this slice only removes the speculative competitor.)
- Clustering poll (3 s, gated) unchanged. Server-side N+1 in `get_workbench_media()` deliberately untouched — local, and unmeasured ([PERF-06]); see Stretch.

Proof (TEST_CMD: `cd apps/prototype-wp-alt-context && npm test -- js/admin/hooks`):

- Hook test with instrumented fetchers: while detail/identities for page N are in flight, no `fetchWorkbenchMedia(page N+1)` call occurs; after both settle, exactly one prefetch fires.
- Existing prefetch behavior test (if pinned) updated to the settled condition — named here as the one intentional test change.

## Not Doing (Out of Scope)

- **Folding identities into `GET /workbench/media/detail`** (one fewer round trip, [RES-12]): deferred. With Slice 1 the identities leg is local and cheap for curated tenants, shrinking the win; folding also couples two responses with different cache lifetimes (identities invalidate on curation, details are immutable). Decide on measurement after this task lands — recorded as an open question for planning review.
- **Server N+1 in `Api::get_workbench_media()`** (`class-api.php:196`): local-only cost, no measurement yet ([PERF-06]). Stretch.
- **Outbox/push-side resilience** — E15-35. **Split-topology drain** — reserved E15-36.
- **Offline caching of remote-only data**: cold-start tenants legitimately need the network once.
- **Raising or removing the 2 s client timeout**: the bound is correct ([RES-02]); sovereignty, not patience, is the fix.
- **Changing `is_projection_stale` thresholds or the sync-pull cadence**: staleness policy is sync-side scope.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded PHP + TS guidelines and testing rules; confirmed `data_source` vocabulary sites on both sides before editing.
- [ ] Recorded boundary decision: envelope unchanged, source-selection semantics change server-side only.

### Checklist for Slice 1: Media-identities gate inversion

- [ ] Rows-first `should_use_local_projection()`; sync-state conjunct deleted (not flagged).
- [ ] Bootstrap scheduling after successful proxy read, deduped via `wp_next_scheduled`; nothing scheduled on unavailable.
- [ ] `RecognitionDataSource` constants class adopted at all four PHP declaration sites; TS parity test added.
- [ ] PHP tests cover rows-without-sync-state (zero HTTP), cold-start proxy + bootstrap scheduling, unavailable envelope unchanged.

### Checklist for Slice 2: Cluster-read rows-first qualification

- [ ] OR-broadened qualification in `ClusterProjectionSyncService`; inline stale pull retained.
- [ ] Existing clusters-read fixtures pass unmodified; new wipe-class test (rows present, sync-state absent → local).

### Checklist for Slice 3: Honest degraded state

- [ ] Query-error path renders the unavailable affordance via the existing `IdentityClusterList` branch; genuine-empty copy unreachable from error states.
- [ ] Cached labels persist through failed refetch (test-pinned).
- [ ] Bounded retry (≤2, backoff, never 4xx); no new bare-`false` refetch interval; cooldown gate untouched.

### Checklist for Slice 4: Load discipline

- [ ] Prefetch gated on stage-2 settle; single prefetch per page key preserved.
- [ ] Hook test asserts no speculative fetch during first paint.

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
- [ ] Cold tenant, service down: workbench shows the unavailable affordance with retry; the "No identities detected yet" copy appears only for genuinely empty successful responses.
- [ ] Cold tenant, service up: first read proxies, schedules bootstrap; a subsequent read after sync serves `local_projection`.
- [ ] Cluster/label/member reads survive the sync-state wipe class without flipping to the proxy.
- [ ] No next-page prefetch before the current page's queries settle; per-view request count for a non-paginating user drops by the prefetch share.
- [ ] All four `data_source` literals originate from exactly one PHP class and one TS module; grep finds no stray declarations.
