# E21-13. Offline Read-Only Mode (remote-compute fail-fast gating)

> **Metadata**
>
> - **Date**: 2026-07-14
> - **Author**: Claude Opus 4.8 (claude-opus-4-8)
> - **Task**: E21-13 (E21-7 split-off — the read-only-mode half; the offline-honesty half shipped under E21-7 @ `77271b06`)
> - **Epic**: E21 (Public MVP UX/UI Polish), Phase 3
> - **Depends on**: E21-7 (done) — `isSyncOffline(health) = breaker.state === 'open'`
> - **Target Version**: v0.4.1
> - **Branch**: `feature/e21-13`

## Goal

When the recognition backend is unreachable (circuit breaker **open**), remote-compute actions must **fail fast** — disabled with a visible, announced reason — instead of firing a request that hangs or errors downstream. Local reads and queued curation writes stay fully live (data-sovereignty). Recovery affordances stay enabled so the operator can heal the breaker. The offline state resolves automatically when the breaker self-heals (~60s expiry / next successful 15s health poll).

## Grounding (audit @ `77271b06`)

- **No remote-compute action gates on the breaker today.** Taxonomy: **6 gated** (below) + **2 cancels** (kept) + **3 recovery affordances** (kept) + **retention export/import/purge** (deferred, §3) all fire and fail downstream today. Only 3 display-only consumers read the breaker (`DegradedModeBanner`, `DashboardPage:50`, `SyncStatusIndicator:185`).
- **No shared offline state** — `useSyncHealth()` is called independently in display components; React Query dedupes on `queryKeys.sync.health()` (15s). Introduce one shared `useSyncOffline()` derivation.
- **`fetchSyncHealth` is a WP-local read** — it returns `breaker.state` even while the remote service is down, so the gating signal is reliably available offline.
- **Recovery affordances must NOT be gated** — `testConnection` (settingsTest), `triggerSync` (manual + auto-heal on stale/visibilitychange), `resetMirror` reset/heal the breaker; gating them traps the operator offline.
- **Curation writes enqueue to a local WP outbox** (`class-cluster-mutations-controller.php:313`) — offline-safe, must stay live. A separate `projection_not_ready` 409 already guards empty-projection curation, independent of the breaker.
- **Transient breaker** — auto-expires ~60s; gated buttons must re-enable **reactively** off the 15s poll, never stale-disable.

## Design

### 1. Shared offline signal
Add `hooks/useSyncOffline.ts`: `useSyncOffline(): boolean` wrapping `useSyncHealth()` + `isSyncOffline`. Single-sources the derivation and copy semantics ([sr-007]). Returns `false` while health is loading (never gate before an authoritative result — mirrors the `!health` banner guard).

### 2. Disabled-with-reason affordance
Add a small presentational helper (shipped as `hooks/useRemoteActionGate.ts` returning `{disabled, 'aria-disabled', title}`) that pairs `disabled` + `aria-disabled` + `title` ([rg-004], [UI-02]/[sr-004], A11Y-11); the optional inline `<p className="description">` reason was dropped in implementation — `title` + the banner live-region carry the reason (see the a11y walkthrough doc). Reuses the existing `SettingsForm` inline-description convention (`:159-163`) and `title`-tooltip pattern (`SuggestionReviewPanel`). The global announcement leans on the existing `DegradedModeBanner` live-region (`role="alert"` + `aria-live`) — do not add a second assertive region per action.

### 3. Action classification (authoritative)

**GATE when breaker open** (remote-compute that starts new backend work):

| Action | Hook | Hook-owning container → gated affordance |
|---|---|---|
| Scan/analyze faces | `useScanIdentities` | `MediaAnalyzeCta.tsx` (hook + button `:30` co-located — gate here directly) |
| Cluster latest job | `useClusterIdentities` | container `ConfirmTabContent.tsx` (already uses `useJobPipeline`) → thread `disabled`/`offline` prop into `ConfirmPanelProps` → button `Panels.tsx:188` |
| Sensitive rescan | `useClusterActions.rescanMutation` | roster cluster-action owner (hook container) → disable trigger |
| Split cluster | `useClusterActionMutations.splitMutation` | cluster-action owner (hook container) → disable trigger |
| AI describe (single) | `useDescribeMedia` | `DescribePanel.tsx` — **fold `offline` into `canSubmit` AND the `handleSubmit` guard** (`:20`/`:50`), not just the button `disabled` (`:62`); the input sits in `<form onSubmit>` so Enter would otherwise bypass a button-only disable |
| AI describe (bulk/Florence) | `useBulkDescribe.submit` | container of `MediaSelection.tsx:155` → thread `disabled`/`offline` prop into `BulkDescribeCta` (child `:279`) |

**Wiring seam (mandatory):** call `useSyncOffline()` in the **hook-owning container**, then thread a `disabled`/`offline` prop into any pure presentational CTA (`ConfirmPanel`, `BulkDescribeCta`). Never call `useSyncOffline()` inside a presentational component — it breaks purity and crashes the existing provider-less component tests (`useQuery` needs a `QueryClientProvider`). For form-wrapped actions, gate the **submit handler**, not only the button, so keyboard submit can't bypass the gate.

**KEEP ENABLED — recovery affordances (never gate):** `testConnection` (settingsTest), `triggerSync` manual + auto, `resetMirror`. Add a regression test asserting each stays enabled while offline.

**KEEP ENABLED — local outbox writes + reads (never gate):** all curation (label/merge/reassign/pin/reject-suggestion, suggestion accept/reject/name, commit-to-roster, roster CRUD, conflict resolution, outbox retry/discard), apply-describe-drafts (WP-local write), and all local reads. Cancels (`cancelScanJob`, `cancelBulkDescribeRun`) stay enabled — they stop in-flight work, best-effort.

**DEFERRED — retention remote ops (out of scope, explicit):** `hooks/useRetentionStatus.ts` export/import/purge/`applyRetentionPreset` (via `retentionApi.ts` → `requireRetentionEndpoint`) are breaker-governed remote-compute and *will* hang offline (RES-03), but they live on the separate low-traffic `RetentionPage` admin surface, not the demo core loop. Deferred to a follow-up so this slice stays focused on the review-loop surfaces. Grok must **not** gate them here.

### 4. State matrix (A11Y-24)
For each gated surface, cover **loading / empty / error / offline** × focus + announcement. Offline = disabled + reason; the primary control must stay reachable from the zero state ([rg-003] — do not hide, disable-with-reason).

## Slices

### Slice 1 — Shared offline signal + gate affordance
- [x] `hooks/useSyncOffline.ts` (+ test): returns `false` while loading, `true` when breaker open.
- [x] `useRemoteActionGate`/`RemoteActionGate` helper (+ test): `disabled` + `aria-disabled` + `title` (inline reason dropped; see §2), token-styled.
- [x] Test seam: the `useSyncHealth`/`createMockQuery` breaker lever is for the **`useSyncOffline.ts` unit test only**. Extended *component* tests must **module-mock `useSyncOffline`** directly (`vi.mock('.../useSyncOffline')`, as `SyncStatusIndicator.test.tsx` mocks its hooks) — they render without a `QueryClientProvider`, so mocking `useSyncHealth` alone won't work.

### Slice 2 — Gate the 6 remote-compute actions
- [x] Wire `useSyncOffline()` into the 6 gate points above; disabled + reason when offline; reactively re-enable on heal.
- [x] Confirm recovery affordances (test-connection, triggerSync, resetMirror) and all curation/local actions remain enabled — assert with tests.
- [x] Extend (module-mock `useSyncOffline` per Slice 1 seam): `MediaAnalyzeCta.test.tsx`, `Panels.test.tsx`, `useBulkDescribe.test.tsx`, `DescribePanel.test.tsx` (assert the **form-submit/Enter** path is gated, not just the button), `SettingsPage.test.tsx` (test-connection stays enabled offline), roster/cluster action tests.

### Slice 3 — State matrix + a11y walkthrough
- [x] Offline column added to each gated surface's state coverage (loading/empty/error/offline).
- [x] `WorkbenchPage.integration.test.tsx`: end-to-end gating (breaker open → disabled+reason → breaker heals → re-enabled).
- [x] Keyboard-only + screen-reader walkthrough note (A11Y-23); confirm banner live-region announces the transition. → [`E21-13-offline-a11y-walkthrough.md`](./E21-13-offline-a11y-walkthrough.md)
- [x] Document breaker-vs-`navigator.onLine` (SSE hook) as the two offline notions; breaker governs gating. → same walkthrough doc.

## Engineering heuristics

- **[RES-15]** Circuit-break integration points — stop calling what's already failing; **expose breaker state to operations**. (Core of this task.)
- **[RES-03]** Slow failure worse than fast failure — a hung remote call ties up the UI worse than a refused one; fail fast.
- **[RES-13]** Bugs are survived, not eliminated — assume the recognition call fails; the gate is the crumple zone.
- **[UI-02]/[sr-004]** Never color alone — disabled affordance pairs an icon/reason with any color cue; text meets WCAG.
- **[rg-003]** Primary controls reachable from zero state — disable-with-reason, never hide.
- **[rg-004]** Role semantics match behavior — `aria-disabled` + reason; no misleading roles.
- **[sr-007]** Centralize the offline derivation (`useSyncOffline`), not scattered `breaker.state` checks.

## Acceptance criteria

1. With the breaker **open**, the 6 remote-compute controls are disabled with a visible + announced reason; with it **closed**, all are enabled — verified reactively across a 15s-poll heal.
2. `testConnection`, `triggerSync`, `resetMirror`, all curation writes, and all local reads remain enabled while offline (asserted by tests).
3. Full `vitest` green; new tests cover offline gating per gated surface + the recovery-stays-enabled invariant + one end-to-end heal cycle.
4. Keyboard-only + screen-reader walkthrough of the offline transition passes; the banner live-region announces it (A11Y-23).
5. No backend contract change; consumes existing sync-health envelope.

## Risks / open threads

- **Trap-the-operator**: gating a recovery affordance strands the user offline — the recovery-stays-enabled test is the guard. Highest-risk item.
- **Auto-heal reactivity**: buttons must re-enable off the 15s poll without a manual refresh; test the heal cycle explicitly.
- **Hidden remote-compute**: split + sensitive-rescan spawn jobs — easy to miss; enumerated above.
- **Two offline notions**: breaker vs `navigator.onLine` (SSE). Breaker governs gating; SSE stays on `navigator.onLine`. Document, don't merge (out of scope to unify).
- **Deferred from E21-7**: B-BR-03 (save onSuccess double-GET /settings) — not this task.
