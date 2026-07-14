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

- **No remote-compute action gates on the breaker today** — all 12 fire and fail downstream. Only 3 display-only consumers read the breaker (`DegradedModeBanner`, `DashboardPage:50`, `SyncStatusIndicator:185`).
- **No shared offline state** — `useSyncHealth()` is called independently in display components; React Query dedupes on `queryKeys.sync.health()` (15s). Introduce one shared `useSyncOffline()` derivation.
- **`fetchSyncHealth` is a WP-local read** — it returns `breaker.state` even while the remote service is down, so the gating signal is reliably available offline.
- **Recovery affordances must NOT be gated** — `testConnection` (settingsTest), `triggerSync` (manual + auto-heal on stale/visibilitychange), `resetMirror` reset/heal the breaker; gating them traps the operator offline.
- **Curation writes enqueue to a local WP outbox** (`class-cluster-mutations-controller.php:313`) — offline-safe, must stay live. A separate `projection_not_ready` 409 already guards empty-projection curation, independent of the breaker.
- **Transient breaker** — auto-expires ~60s; gated buttons must re-enable **reactively** off the 15s poll, never stale-disable.

## Design

### 1. Shared offline signal
Add `hooks/useSyncOffline.ts`: `useSyncOffline(): boolean` wrapping `useSyncHealth()` + `isSyncOffline`. Single-sources the derivation and copy semantics ([sr-007]). Returns `false` while health is loading (never gate before an authoritative result — mirrors the `!health` banner guard).

### 2. Disabled-with-reason affordance
Add a small presentational helper (e.g. `components/RemoteActionGate.tsx` or a `useRemoteActionGate({offline})` returning `{disabled, ariaDisabled, title, reason}`) that pairs `disabled` + `aria-disabled` + `title` + an optional inline `<p className="description">` reason ([rg-004], [UI-02]/[sr-004], A11Y-11). Reuses the existing `SettingsForm` inline-description convention (`:159-163`) and `title`-tooltip pattern (`SuggestionReviewPanel`). The global announcement leans on the existing `DegradedModeBanner` live-region (`role="alert"` + `aria-live`) — do not add a second assertive region per action.

### 3. Action classification (authoritative)

**GATE when breaker open** (remote-compute that starts new backend work):

| Action | Hook | Gate point |
|---|---|---|
| Scan/analyze faces | `useScanIdentities` | `MediaAnalyzeCta.tsx:30` |
| Cluster latest job | `useClusterIdentities` | `Panels.tsx:188` (ConfirmPanel) |
| Sensitive rescan | `useClusterActions.rescanMutation` | roster action |
| Split cluster | `useClusterActionMutations.splitMutation` | cluster action |
| AI describe (single) | `useDescribeMedia` | `DescribePanel.tsx:62` |
| AI describe (bulk/Florence) | `useBulkDescribe.submit` | `MediaSelection.tsx:155` |

**KEEP ENABLED — recovery affordances (never gate):** `testConnection` (settingsTest), `triggerSync` manual + auto, `resetMirror`. Add a regression test asserting each stays enabled while offline.

**KEEP ENABLED — local outbox writes + reads (never gate):** all curation (label/merge/reassign/pin/reject-suggestion, suggestion accept/reject/name, commit-to-roster, roster CRUD, conflict resolution, outbox retry/discard), apply-describe-drafts (WP-local write), and all local reads. Cancels (`cancelScanJob`, `cancelBulkDescribeRun`) stay enabled — they stop in-flight work, best-effort.

### 4. State matrix (A11Y-24)
For each gated surface, cover **loading / empty / error / offline** × focus + announcement. Offline = disabled + reason; the primary control must stay reachable from the zero state ([rg-003] — do not hide, disable-with-reason).

## Slices

### Slice 1 — Shared offline signal + gate affordance
- [ ] `hooks/useSyncOffline.ts` (+ test): returns `false` while loading, `true` when breaker open.
- [ ] `useRemoteActionGate`/`RemoteActionGate` helper (+ test): `disabled` + `aria-disabled` + `title` + inline reason, token-styled.
- [ ] `test-utils/mockHooks.ts`: add a `useSyncHealth`/breaker mock lever for gating tests.

### Slice 2 — Gate the 6 remote-compute actions
- [ ] Wire `useSyncOffline()` into the 6 gate points above; disabled + reason when offline; reactively re-enable on heal.
- [ ] Confirm recovery affordances (test-connection, triggerSync, resetMirror) and all curation/local actions remain enabled — assert with tests.
- [ ] Extend: `MediaAnalyzeCta.test.tsx`, `Panels.test.tsx`, `useBulkDescribe.test.tsx`, `useDescribeMedia.test.tsx`, `SettingsPage.test.tsx` (test-connection stays enabled), roster/cluster action tests.

### Slice 3 — State matrix + a11y walkthrough
- [ ] Offline column added to each gated surface's state coverage (loading/empty/error/offline).
- [ ] `WorkbenchPage.integration.test.tsx`: end-to-end gating (breaker open → disabled+reason → breaker heals → re-enabled).
- [ ] Keyboard-only + screen-reader walkthrough note (A11Y-23); confirm banner live-region announces the transition.
- [ ] Document breaker-vs-`navigator.onLine` (SSE hook) as the two offline notions; breaker governs gating.

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
