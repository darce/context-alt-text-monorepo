# Refactoring Opportunities — `apps/prototype-wp-alt-context`

> Source-derived refactoring digest applying principles from _Release It!_ (Nygard), _Designing Data-Intensive Applications_ (Kleppmann), _Latency_ (Enberg), and _Refactoring UI_ (Wathan & Schoger) to the WP plugin surfaces. Sibling to [`wp-plugin-literature-digest.md`](../../../literature/extracted/wp/wp-plugin-literature-digest.md), which covers WP-canonical patterns; this file covers cross-cutting reliability, data, latency, and UX patterns.

**Scope**: PHP plugin (`src/`), admin SPA (`js/admin/`), shared UI (`js/components/`), CSS tokens (`js/admin/styles/`).
**Reading order**: §2 for the principle vocabulary, §3 for site-specific opportunities by surface, §4 for the top priorities to slot into a future task plan.

---

## 1. Method

Each opportunity below is anchored to a `file:line` reference and one or more named principles. Recommendations are **non-prescriptive** — they identify the antipattern or missing pattern; concrete fixes belong in task plans, not here.

Categories:

- **REL-\*** — _Release It!_ stability/capacity patterns
- **DDIA-\*** — Storage, schema evolution, idempotence, derived data
- **LAT-\*** — Tail latency, batching, async, optimistic UI
- **RUI-\*** — Hierarchy, whitespace, color systems, empty/loading states

A finding is logged here only if it is non-obvious from reading the code in isolation — i.e. the principle is what makes the call to action visible.

---

## 2. Principle Vocabulary

### Release It! (stability)

- **REL-IP** — _Integration Point_: every external call (recognition service, DB, file I/O) is a stability hazard until proven otherwise.
- **REL-CB** — _Circuit Breaker_: open after N failures within a window; half-open probe before closing.
- **REL-TO** — _Timeout_: every outbound call has a finite, explicit upper bound; no infinite blocks.
- **REL-FF** — _Fail Fast_: detect impossibility early and reject; do not enqueue work that will time out anyway.
- **REL-BH** — _Bulkhead_: partition resources so one slow integration cannot drain the whole pool.
- **REL-SS** — _Steady State_: every accumulating resource (logs, transients, outbox rows) needs a paired purge.
- **REL-URS** — _Unbounded Result Set_: any iteration whose size is supplied (directly or transitively) by an external actor must have a server-side cap.
- **REL-BT** — _Blocked Threads_: synchronous waits on a remote service occupy a request slot; on PHP-FPM/Apache mod_php this directly reduces concurrency.

### DDIA (data)

- **DDIA-SE** — _Schema Evolution_: column adds and renames must be backwards/forwards compatible across rolling code+schema.
- **DDIA-IDP** — _Idempotence_: every mutation must be safe to re-execute (deduplication key, conditional write, or upsert).
- **DDIA-DD** — _Derived Data / Materialized View_: keep a clear distinction between source-of-truth and projection; rebuild projections from source rather than mutating both.
- **DDIA-SI** — _Secondary Index_: queries used by hot UI surfaces must be supported by an index, not a full table scan.
- **DDIA-SE2** — _Sync Engine Discipline_: outbox rows are the contract; consumers idempotent, producers append-only.

### Latency (perceived performance)

- **LAT-TL** — _Tail Latency_: optimize p95/p99, not mean. One slow call stalls the whole UI.
- **LAT-LL** — _Little's Law_: bounded concurrency × arrival rate = latency; backpressure is mandatory at queue ingress.
- **LAT-BA** — _Batch & Amortize_: amortize fixed costs (round-trip, transaction, file open) across multiple items.
- **LAT-OP** — _Optimistic Update_: render the user's intended end-state immediately; reconcile on response.
- **LAT-PF** — _Prefetch_: speculatively load the next likely view while the user reads the current one.
- **LAT-CA** — _Cache-Aside_: read from cache; on miss, populate from source-of-truth; invalidate on write.

### Refactoring UI (visual)

- **RUI-HC** — _Hierarchy via Contrast_: weight, color saturation, and whitespace signal importance more than size.
- **RUI-SS** — _Spacing Scale_: a small fixed scale (4/8/12/16/24/32/48/64) replaces ad-hoc px values.
- **RUI-CS** — _Color System_: ~8–10 shades per hue, semantic tokens (success/warn/danger), avoid raw hex.
- **RUI-ES** — _Empty States_: every list or grid has a useful zero state with a primary action.
- **RUI-LS** — _Loading Skeletons_: layout-stable placeholders beat spinners for perceived speed.
- **RUI-EL** — _Elevation_: shadow depth disambiguates layering (cards vs. modals vs. menus).

---

## 3. Opportunities by Surface

### 3.1 PHP REST controllers — `src/api/`

| ID   | Anchor                                                                                                                | Observation                                                                                                                                                                         | Principles        |
| ---- | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| RX-1 | [class-abstract-recognition-proxy-controller.php:140-185](../src/api/class-abstract-recognition-proxy-controller.php) | Exponential-backoff retry uses blocking `usleep()` on the request thread. Worst-case ~3.5s of a PHP-FPM worker held idle per failing call.                                          | REL-BT, LAT-TL    |
| RX-2 | [class-abstract-recognition-proxy-controller.php:427-464](../src/api/class-abstract-recognition-proxy-controller.php) | Circuit-breaker state lives in the shared transient cache keyed by `md5(base_url)`; no namespace partition between policies, no eviction policy if cache pressure rises.            | REL-CB, REL-SS    |
| RX-3 | [class-media-detail-controller.php:24-75](../src/api/class-media-detail-controller.php)                               | `media_ids` query parameter is iterated without an explicit `MAX_IDS_PER_REQUEST` cap; size is set by client.                                                                       | REL-URS, REL-FF   |
| RX-4 | [class-clusters-controller.php](../src/api/class-clusters-controller.php)                                             | Constructor injects repositories + mappers (good IoC), but per-request result-set caps are enforced by repository defaults, not validated at the controller boundary.               | REL-URS, DDIA-SI  |
| RX-5 | [class-recognition-proxy-policy.php](../src/api/class-recognition-proxy-policy.php)                                   | Policy object centralizes timeouts/retries — preserve. Consider extending it to expose a single point where SLOs are declared (timeout, max retries, breaker threshold) per policy. | REL-IP (preserve) |
| RX-6 | All `*-controller.php` 5xx paths                                                                                      | 503 + `Retry-After` short-circuits cleanly; other 5xx codes still enter the retry loop, which can amplify pressure on a wounded backend.                                            | REL-CB, REL-FF    |

### 3.2 Database — sovereign repositories — `src/sovereign/repositories/`

| ID   | Anchor                                                                                                       | Observation                                                                                                                                                                                                              | Principles                |
| ---- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------- |
| DB-1 | [class-clusters-repository.php:51-87](../src/sovereign/repositories/class-clusters-repository.php)           | `merge_snapshot_for_tenant()` ingests an array-typed `clusters` payload and inserts row-at-a-time without a per-batch commit checkpoint. A 100k-cluster snapshot becomes one giant transaction.                          | REL-URS, LAT-BA, DDIA-IDP |
| DB-2 | [interface-clusters-repository.php](../src/sovereign/repositories/interface-clusters-repository.php)         | `list_for_tenant(...$limit=50, $offset=0)` — pagination contract is in the interface. Preserve and replicate to repositories that lack it.                                                                               | DDIA-SI (preserve)        |
| DB-3 | [class-identity-members-repository.php](../src/sovereign/repositories/class-identity-members-repository.php) | `list_for_cluster($limit=500)` — ceiling is hard-coded in the parameter default; not exposed as a typed cap or surfaced in the response envelope.                                                                        | DDIA-SI, REL-URS          |
| DB-4 | All sovereign repositories                                                                                   | No explicit composite indexes documented for hot UI queries (e.g. `(tenant_id, status, updated_at DESC)` for the dashboard). Migrations create tables but indexes beyond PK are not visible from the dbDelta call alone. | DDIA-SI                   |
| DB-5 | [class-life-cycle-manager.php:64-96](../src/support/class-life-cycle-manager.php)                            | `migrate_legacy_roster_data()` iterates legacy entries inside a single foreach with no batching/transaction boundary.                                                                                                    | REL-URS, LAT-BA           |

### 3.3 Sync engine — `src/sovereign/sync/`

| ID   | Anchor                                                                         | Observation                                                                                                                                                                                                                        | Principles         |
| ---- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| SY-1 | [class-sync-pull-job.php:50-67](../src/sovereign/sync/class-sync-pull-job.php) | Cooldown-gated sync (30s on failure, manual bypass for operator) — preserve.                                                                                                                                                       | REL-CB (preserve)  |
| SY-2 | `class-snapshot-client.php`                                                    | Snapshot pull does not appear to share the proxy controller's circuit-breaker state. A wedged backend re-enters the breaker per surface.                                                                                           | REL-CB, REL-IP     |
| SY-3 | `class-outbox-drain.php` / `class-curation-outbox-drain.php`                   | Outbox drain is the canonical DDIA write-side. Verify each row carries an idempotency key consumed by the backend; verify the drain fails closed (does not delete on a 5xx).                                                       | DDIA-IDP, DDIA-SE2 |
| SY-4 | `class-snapshot-projector.php`                                                 | Projector is the materialized-view writer. It must be safe to truncate-and-rebuild the projection from snapshot+outbox without touching the recognition service. Document this guarantee if it holds; add a CLI affordance if not. | DDIA-DD            |
| SY-5 | `class-conflict-repository.php`                                                | Conflict rows accumulate; no eviction or "resolved-N-days-ago" purge visible.                                                                                                                                                      | REL-SS             |

### 3.4 Media / XMP — `src/media/`

| ID   | Anchor                                                                      | Observation                                                                                                                                                                                                                                | Principles                   |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------- |
| MX-1 | [class-image-xmp-writer.php:54-90](../src/media/class-image-xmp-writer.php) | Pre-flight checks (mime, readability, writeability) are good — write is idempotent. Region serialization loop is unbounded by identity count; a pathological attachment with thousands of detected faces produces an oversized XMP packet. | DDIA-IDP (preserve), REL-URS |
| MX-2 | `class-jpeg-xmp-injector.php`, `class-png-xmp-injector.php`                 | In-place file mutation. Two concurrent writers (CLI + cron, or two cron beats) racing on the same attachment file path is an unguarded hazard. No advisory lock.                                                                           | REL-IP, DDIA-IDP             |
| MX-3 | `class-attachment-xmp-metrics-persistor.php`                                | Persists per-attachment metrics. Any retry path should key on `(attachment_id, source_run_id)` to dedupe.                                                                                                                                  | DDIA-IDP                     |

### 3.5 CLI commands — `src/cli/`

| ID   | Anchor                                                                              | Observation                                                                                                                                                           | Principles |
| ---- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| CL-1 | [class-xmp-backfill-command.php:51-83](../src/cli/class-xmp-backfill-command.php)   | Progress logging + summary present. `array_merge() + array_unique()` of `--all` IDs and explicit IDs implicitly composes (could double the cap when both are passed). | REL-URS    |
| CL-2 | [class-reset-projection-command.php](../src/cli/class-reset-projection-command.php) | If reset-projection is the documented rebuild path for SY-4 (materialized view rebuild), flag it explicitly in the file-level docblock.                               | DDIA-DD    |

### 3.6 Frontend admin SPA — `js/admin/`

| ID    | Anchor                                                                                                      | Observation                                                                                                                                                                                                                                                            | Principles                                      |
| ----- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| FE-1  | [pages/DashboardPage.tsx:28-40](../js/admin/pages/DashboardPage.tsx)                                        | 5 independent hooks fired on mount: `useMediaStats`, `useRecognitionJobHistory`, `useIdentityStats`, `useSyncStatus`, `useRetentionStatus`. No coordinated suspense boundary; each panel has its own loading/empty rendering branches.                                 | LAT-TL, RUI-LS, RUI-ES                          |
| FE-2  | [pages/DashboardPage.tsx:98+](../js/admin/pages/DashboardPage.tsx)                                          | Renders `"Unknown"` fallback strings rather than empty/error states. The dashboard's zero-state is a wall of "Unknown" cells.                                                                                                                                          | RUI-ES                                          |
| FE-3  | [hooks/useRecognitionJobHistory.ts:49-127](../js/admin/hooks/useRecognitionJobHistory.ts)                   | A single effect parallel-fetches all job statuses then issues 3 independent `setState` calls; no atomic update. A mid-stream failure leaves UI state internally inconsistent.                                                                                          | LAT-OP (negative), DDIA-IDP analog              |
| FE-4  | [hooks/useRecognitionJobHistory.ts:~120](../js/admin/hooks/useRecognitionJobHistory.ts)                     | 404 detection via `error.message.includes('(404)')` — fragile string match across error.toString boundaries.                                                                                                                                                           | (cross-reference: testing principles)           |
| FE-5  | [hooks/useJobCoordination.ts:39-80](../js/admin/hooks/useJobCoordination.ts)                                | BroadcastChannel tab-election with 200ms jitter + 30/60s heartbeat — preserve. This is the canonical "Bulkhead" of the SPA: only the elected tab holds the SSE bulkhead.                                                                                               | REL-BH (preserve)                               |
| FE-6  | [context/ToastContext.tsx:30-37](../js/admin/context/ToastContext.tsx)                                      | Toast IDs from `Math.random().toString(36)` — not collision-free under bursty toast emission (e.g. bulk-action errors). Use `crypto.randomUUID()` (modern browsers) or a monotonic counter.                                                                            | (cross-reference: sr-005 / boundary discipline) |
| FE-7  | [api/config.ts:28-79](../js/admin/api/config.ts)                                                            | `maxMediaPerBatch` defaults to 10000 if missing — explicit MVP de-chunking. Contradicts LAT-BA: a 10k-batch first paint dominates p99 and overshoots server `MULTIPART_MAX_IMAGES=5`. The chunking layer in `scanApi.ts` mitigates, but the config knob is misleading. | LAT-BA, REL-URS                                 |
| FE-8  | [api/recognition/scanApi.ts:12-34](../js/admin/api/recognition/scanApi.ts)                                  | `MULTIPART_MAX_IMAGES = 5` enforced client-side — preserve. Single canonical owner for the cap (per `docs/agentic/contracts/`).                                                                                                                                        | LAT-BA (preserve), DDIA-SE (preserve)           |
| FE-9  | [api/recognition/requestTimeout.ts:1-8](../js/admin/api/recognition/requestTimeout.ts)                      | 2s default abort — too aggressive for cold-start backends; no client-side retry/backoff (relies on server). On flaky networks this surfaces as user-visible failures rather than silent recovery.                                                                      | REL-TO, LAT-TL                                  |
| FE-10 | Multiple `use*` hooks reference `useJobStateMachine`, `useJobProgressStream`, `useJobStateMachineMutations` | Job state is split across hooks. Single source of truth for "what is the current job doing?" is non-obvious. Per project rule sr-007, prefer a canonical state enum + reducer.                                                                                         | (cross-reference: sr-007, sr-008)               |

### 3.7 CSS / design tokens — `js/admin/styles/`, `js/components/ui/`

| ID   | Anchor                                                                | Observation                                                                                                                                                                         | Principles             |
| ---- | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| UI-1 | [styles/tokens/\_colors.scss](../js/admin/styles/tokens/_colors.scss) | `--acx-color-*` and `--acx-gray-*` token surface in place — preserve. Verify all components consume the tokens (per sr-004).                                                        | RUI-CS (preserve)      |
| UI-2 | `styles/tokens/_spacing.scss`, `_typography.scss`                     | Token surface exists. Audit components for `px` literals that should resolve through `--acx-space-*` / `--acx-text-*`.                                                              | RUI-SS                 |
| UI-3 | `styles/components/_dashboard.scss` and similar                       | Responsive grids use `repeat(auto-fit, minmax(...))` — preserve.                                                                                                                    | RUI-HC (preserve)      |
| UI-4 | All page components                                                   | No dedicated `.acx-empty-state` / `.acx-loading-skeleton` / `.acx-error-state` primitive components found in `js/components/ui/`. Each page invents its own zero/loading rendering. | RUI-ES, RUI-LS         |
| UI-5 | All page components                                                   | Status indicators rely on color (per token `--acx-color-status-*`). Confirm pairing with an icon (per sr-004) — color-alone fails accessibility.                                    | RUI-CS                 |
| UI-6 | `js/components/ui/`                                                   | No central `Skeleton`, `EmptyState`, `ErrorState` primitive. These are the highest-leverage RUI fixes — one component pays for itself across every page.                            | RUI-ES, RUI-LS, RUI-EL |

---

## 4. Top Priorities

Ordered by leverage (impact × ease).

1. **Bound every server-side iteration.** Add typed `MAX_*` caps at controller boundaries (RX-3, DB-1, DB-5, MX-1, CL-1) and surface them in the response envelope (`limit`, `total`, `truncated`). Single conceptual fix; multiple sites.
   _Principles_: REL-URS, REL-FF, DDIA-SI

2. **Three shared UI primitives — `EmptyState`, `Skeleton`, `ErrorState`.** Place in `js/components/ui/`. Adopt across `Dashboard`, `Roster`, `Workbench`, `Settings` pages. Replaces the "Unknown" fallback wall (FE-2) and ad-hoc per-page rendering (UI-4).
   _Principles_: RUI-ES, RUI-LS, RUI-EL

3. **Unify breaker state across surfaces.** The proxy controller's circuit breaker (RX-2) and the sync engine (SY-2) currently maintain independent failure views of the same backend. Lift breaker state to a single keyed-by-base-url store consumed by both.
   _Principles_: REL-CB, REL-IP

4. **Replace blocking retry sleeps with caller-side fail-fast.** Move the retry/backoff loop (RX-1) off the request thread; either return 503 + `Retry-After` to the SPA and let the client back off (LAT-OP), or move retries into a queue worker.
   _Principles_: REL-BT, REL-FF, LAT-TL

5. **Atomic hook updates / canonical job state.** Convert `useRecognitionJobHistory` (FE-3) and the constellation around `useJobStateMachine*` (FE-10) into a single reducer with a canonical state enum (sr-007). One state mutation per network event.
   _Principles_: LAT-OP, DDIA-IDP (analog)

6. **Reset-projection as the documented rebuild path.** Promote `class-reset-projection-command.php` (CL-2) and the projector (SY-4) into a documented "rebuild materialized view from outbox+snapshot" affordance with a runbook entry. This is the backstop when the projection diverges.
   _Principles_: DDIA-DD

7. **`maxMediaPerBatch=10000` MVP knob is misleading.** Either remove the knob (let `MULTIPART_MAX_IMAGES=5` be the single canonical owner per the recent `docs(contracts)` commit) or rename it to clarify it controls the higher-level scan-job batch, not the multipart chunk.
   _Principles_: LAT-BA, DDIA-SE

8. **Steady-state purge for accumulating tables.** `acx_sync_conflicts` (SY-5), retained job history, transient breaker rows (RX-2). Each needs an explicit retention horizon.
   _Principles_: REL-SS

---

## 5. Preserve (already aligned)

These patterns are in place and **should not be refactored away**; flag as preserved good practice in any future review:

- Recognition proxy timeout + retry policy as a first-class object (RX-5).
- Pagination in the cluster + identity-member repository interfaces (DB-2, DB-3).
- Cooldown-gated sync pull with operator bypass (SY-1).
- XMP writer pre-flight checks; idempotent skip when no identities (MX-1).
- BroadcastChannel tab election as the SPA's bulkhead for SSE connection ownership (FE-5).
- Server-side `MULTIPART_MAX_IMAGES=5` with client-side chunker honoring it (FE-8).
- Design token surface (`--acx-color-*`, `--acx-space-*`, `--acx-text-*`) (UI-1, UI-2, UI-3).
- `dbDelta()` for idempotent schema migration (DB-4 partial).

---

## 6. Out of Scope

- Code-level micro-refactoring catalog (Fowler/Beck): not surveyed here. That book maps onto individual functions/methods and belongs in per-task plan slices, not a cross-cutting digest.
- Asyncio (Hattingh): the recognition service (out of repo scope per the Plugin Boundary Rule) is the natural consumer; not applied to PHP/JS surfaces.
- Recognition algorithm literature (`literature/extracted/recognition/`): orthogonal to this plugin's surface area.

---

## 7. References

- Nygard, _Release It! 2nd ed._ — `literature/extracted/refactoring/Release-it-...txt`
- Kleppmann, _Designing Data-Intensive Applications_ — `literature/extracted/refactoring/Designing-Data-Intensive-Applications-...txt`
- Enberg, _Latency: Reduce Delay in Software Systems_ — `literature/extracted/refactoring/Latency-...txt`
- Wathan & Schoger, _Refactoring UI_ — `literature/extracted/refactoring/Refactoring-UI.txt`
- Companion: [`literature/extracted/wp/wp-plugin-literature-digest.md`](../../../literature/extracted/wp/wp-plugin-literature-digest.md) — WP-canonical patterns digest.
- Project rules cross-referenced: sr-004 (design tokens), sr-005 (TS assertions), sr-007 (canonical enums), sr-008 (parameter slippery slope) — see `CLAUDE.md`.
