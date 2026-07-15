# E21-13 — Offline keyboard / screen-reader walkthrough (A11Y-23)

Concise record for Slice 3 acceptance. Not a substitute for MCP findings.

## Keyboard + screen reader path

1. **Tab order reaches the offline banner** when the breaker is open: `DegradedModeBanner` mounts near the top of Workbench (before primary queues/actions). From page chrome, sequential Tab reaches the banner region and any debt recovery links inside it.
2. **Banner is a live region** announcing the offline transition:
   - `role="alert"`
   - `aria-live="assertive"` when offline (`breaker.state === 'open'`)
   - `aria-live="polite"` for advisory (warnings-only) mode
   - Asserted in `DegradedModeBanner.test.tsx` and the Workbench heal-cycle integration test.
3. **Disabled remote CTAs expose reason** via `title` + `aria-disabled` from `useRemoteActionGate` (copy: “Unavailable while the recognition service is offline”). Gate surfaces: analyze, cluster, bulk describe, single describe, sensitive rescan, split. Controls stay in the tree (disable-with-reason, not hide) so they remain discoverable from zero/empty state ([rg-003]).

## Two offline notions (do not unify)

| Notion | Source | Governs | Heal |
| --- | --- | --- | --- |
| **Breaker offline** | Sync-health envelope `breaker.state === 'open'` via `useSyncOffline` / `isSyncOffline` | Remote-compute **gating** (the 6 actions above) + degraded banner “Working offline” | Self-heals ~60s expiry; UI re-enables on next ~15s health poll (no remount) |
| **`navigator.onLine`** | Browser connectivity in `useJobProgressStream` | **SSE** job-progress stream connect/disconnect only | Browser online/offline events |

Breaker governs fail-fast remote-compute gates. SSE stays on `navigator.onLine`. Document only — out of scope to merge into one signal.
