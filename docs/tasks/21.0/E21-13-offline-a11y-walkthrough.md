# E21-13 — Offline keyboard / screen-reader walkthrough (A11Y-23)

Concise record for Slice 3 acceptance. Not a substitute for MCP findings.

## Keyboard + screen reader path

1. **The banner is announced, not focused**: `DegradedModeBanner` mounts in `App.tsx` above the route outlet, so it renders before every page's primary actions in document order. The banner itself is not focusable (no tabindex — live-region announcement is the notification channel); when sync debt exists, its recovery links (failed ops / conflicts) are anchors and are the first interactive elements in tab order after page chrome.
2. **Banner is a live region** announcing the offline transition:
   - `role="alert"` + `aria-live="assertive"` when offline (`breaker.state === 'open'`)
   - `role="status"` + `aria-live="polite"` for advisory (warnings-only) mode
   - Asserted in `DegradedModeBanner.test.tsx` (both modes). The Workbench heal-cycle integration test covers CTA gating reactivity only — the banner mounts in `App.tsx` and is not part of that tree.
3. **Disabled remote CTAs expose reason** via `title` + `aria-disabled` from `useRemoteActionGate` (copy: “Unavailable while the recognition service is offline”). Gate surfaces: analyze, cluster, bulk describe, single describe, sensitive rescan, split. Controls stay in the tree (disable-with-reason, not hide) so they remain discoverable from zero/empty state ([rg-003]).

## Two offline notions (do not unify)

| Notion | Source | Governs | Heal |
| --- | --- | --- | --- |
| **Breaker offline** | Sync-health envelope `breaker.state === 'open'` via `useSyncOffline` / `isSyncOffline` | Remote-compute **gating** (the 6 actions above) + degraded banner “Working offline” | Self-heals ~60s expiry; UI re-enables on next ~15s health poll (no remount) |
| **`navigator.onLine`** | Browser connectivity in `useJobProgressStream` | **SSE** job-progress stream connect/disconnect only | Browser online/offline events |

Breaker governs fail-fast remote-compute gates. SSE stays on `navigator.onLine`. Document only — out of scope to merge into one signal.
