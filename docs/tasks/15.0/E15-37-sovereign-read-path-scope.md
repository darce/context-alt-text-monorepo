# Scope: E15-37 — Sovereign Read Path: Local-First Curated Identities

> **Metadata**
>
> - **Date**: 2026-07-16
> - **Author**: Claude (Fable 5)
> - **Owning Epic**: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md` (E15, Local Sync Correctness)
> - **Status**: Scope brief — precedes task plan + planning review
> - **Related**: E15-35 (outbox push-side resilience; storm dampening protects the projection rows this read path depends on). `E15-36` is reserved for split-topology drain resilience — this task is deliberately numbered E15-37.

## Problem Statement

The product invariant is: **the WP plugin owns sovereign curation ground truth** (human labels), the remote description service computes face embeddings and clusters, and curated labels **must render even when the machine is offline**. The current workbench read path violates this invariant, with two operator-visible symptoms (reported 2026-07-16):

1. Locally curated labels sometimes do not render on initial media-library load, then appear after a manual refresh.
2. The workbench media library is slow to refresh.

## Root-Cause Evidence (verified anchors, base `4a07a0ed`)

**Remote-by-default gate.** `MediaIdentitiesController::get_media_identities()` serves the local projection only when `should_use_local_projection()` passes (`src/api/class-media-identities-controller.php:86`, `:198-201`): the tenant's sync-state row must carry a snapshot version or updated-at (`class-abstract-recognition-proxy-controller.php:247-260`) **and** local member-projection rows must exist. Any other state — cold start, sync-state row missing/stale, projection rows wiped by a regressed snapshot (the exact E15-35 storm incident) — silently routes the read to the **remote** recognition service. Curated ground truth becomes reachable only through the network, inverting ownership ([DATA-14]: local projection is the system of record for curated labels; the backend copy is derived).

**Unavailable masquerades as empty.** On proxy failure the controller returns `identities_by_media: {}` with **HTTP 200** and `data_source: 'unavailable'` (`class-media-identities-controller.php:109-117`). The frontend merges `identities ?? []` (`js/admin/hooks/useWorkbenchMedia.ts`, `itemsWithIdentities`) without distinguishing `data_source`, so "the service is down" renders identically to "this image has no people" — a silent failure the user reads as data loss ([RLSE-05], [OBS-08]; rg-015: an adapter must not fabricate a healthy-looking envelope for an unavailable upstream).

**Tight client timeout, no retry, sticky error.** `fetchMediaIdentities` aborts at 2 s (`js/admin/api/recognition/identityQueriesApi.ts:51`) and the hook sets `retry: false`, `staleTime: 15_000` (`js/admin/hooks/useMediaIdentities.ts`). A slow remote proxy (cold container, WAN) → abort → query error → labels blank until a later refetch succeeds — matching "labels appear on refresh". The bounded timeout itself is correct ([RES-02]); the missing piece is the local-first source that makes the timeout a non-event, plus an honest degraded state ([RES-03]).

**Read-path latency.** Initial render is a three-request waterfall — media page → detail-by-ids → identities-by-ids (`useWorkbenchMedia.ts`) — where the third leg may cross the WAN; independent legs are not joined ([PERF-10]). The hook also always prefetches the next page (doubling backend load) and polls every 3 s while any identity has `clustering_pending`. Server-side, `Api::get_workbench_media()` (`src/api/class-api.php:196`) does per-attachment srcset/terms lookups (N+1, local — secondary).

## Target Outcome

Curated labels render from the local projection on first paint, with the machine offline, for any tenant that has ever curated. The remote proxy is a **cold-start enrichment only** (tenant has no local rows yet). When enrichment is unavailable, the UI says so — it never renders "no people" for "couldn't reach the service". Media-library refresh no longer waits on the WAN for data the plugin already owns.

## Proposed Slices (sketch — final shape belongs to the task plan)

1. **Local-first gate inversion (PHP).** In `MediaIdentitiesController` (and audit the sibling `ClustersController` gate use): if the tenant has *any* local projection/curated rows, serve local unconditionally — drop the sync-state-freshness conjunct as a precondition for reads (staleness is a sync concern, not a read-availability concern). Remote proxy fires only when no local rows exist. The `unavailable` result becomes an explicit machine-distinguishable state the contract already names (`data_source`), never conflatable with a genuine empty set ([API-06] the empty *answer* stays 200; the *unavailable* state must be distinguishable).
2. **Honest degraded state (TS).** Thread `data_source` through `useMediaIdentities`/`useWorkbenchMedia`: `unavailable`/error keeps prior cached labels visible, renders a "recognition service unreachable — showing local curation" affordance instead of blank identities, and enables a bounded retry ([RES-06]-consistent: small backoff, capped attempts, never a tight loop).
3. **Read-path latency.** Join independent legs ([PERF-10]) — start detail + identities fetches from the same tick the id page resolves (or fold identities into the `workbench/media/detail` batch endpoint to remove one round trip, [RES-12]); make next-page prefetch conditional; keep the 3 s clustering poll gated as-is. Server N+1 in `get_workbench_media()` only if measurement shows it matters ([PERF-06]).

## Verification Sketch

- PHP: tenant with curated rows + sync-state row deleted → local projection served (not proxy); proxy-unavailable on a cold tenant → response marked unavailable, not empty-equivalent; contract test pinning `data_source` semantics.
- TS: unavailable/data_source-error renders degraded affordance and preserves cached labels; genuine empty renders "no people"; timeline test that initial load with a hung remote still shows curated labels ([TEST-04]: fake the proxy at the seam).
- Manual/runtime-parity: LocalWP with network disabled (Wi-Fi off) → media library shows curated labels on first load; the degraded banner appears only for uncurated tenants.

## Non-Goals

- Outbox/push-side resilience (E15-35), split-topology drain (reserved E15-36).
- Changing the recognition-service contract; `data_source` vocabulary already exists.
- Offline caching of *remote-only* data (uncurated cold-start tenants legitimately need the network once).

## Open Questions (for the task plan)

- Should `sync_state` freshness still gate *cluster-topology* reads (`ClustersController`) differently from identity-label reads? (Same abstract gate, different staleness tolerance.)
- Does the media-library "tags" surface (`get_workbench_media()` post_tag terms) need the same local-first treatment, or is it already local-only end-to-end?
- Whether the aggregate detail endpoint should absorb identities (one round trip) or stay separate for cache-granularity reasons.
