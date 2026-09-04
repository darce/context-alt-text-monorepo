# FEBT-1 — job pipeline error & progress states (rendered from `febt-1-job-error-states.uxmap.json`)

Hand-rendered (ux-map CLI not installed locally). States are the `jobReducer` states; banner variants are the `AppError._tag` values.

## Screen: workbench-pipeline

```
+----------------------------------------------------------------------+
| Workbench                                                            |
+----------------------------------------------------------------------+
| [pipeline-banner]                                                    |
|  idle      : "No job running"                       [Start job]  (P) |
|  pending   : "Queued…"                              [Cancel]         |
|  running   : "Describing 42/120  ETA 1m 10s"        [Cancel]         |
|  stalled   : "! No progress for 35 s — reconnecting" [Cancel]        |
|  offline   : "! You are offline — will resume"                       |
|  completed : "✓ Done 120/120"                       [Start job]  (P) |
|  completed_with_errors : "✓ Done, 3 failed"         [Retry failed]   |
|  failed    : "✗ Job failed: <toUserMessage>"        [Retry] [Start]  |
+----------------------------------------------------------------------+
| [progress-meter]  ██████████░░░░░░░░░░  35 %   (running | stalled)   |
+----------------------------------------------------------------------+
| [job-actions]   Start job (P)   Cancel (irreversible)   Retry        |
+----------------------------------------------------------------------+
```

Reducer table (state × event → state) — every cell is explicit; `never` guards the rest (GRPH-27):

| state \ event | START | STREAM_OPEN | PROGRESS | STALL_TICK | RECONNECTED | OFFLINE | ONLINE | COMPLETE | COMPLETE_WITH_ERRORS | FAIL | CANCEL | RESET |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| idle | pending | — | — | — | — | offline | — | — | — | — | — | idle |
| pending | — | running | running | stalled (if quiet >= 30s) else pending | — | offline | — | completed | completed_with_errors | failed | idle | idle |
| running | — | — | running | stalled (if quiet >= 30s) else running | — | offline | — | completed | completed_with_errors | failed | idle | idle |
| stalled | — | running | running | stalled (if attempts <= 3) else failed | running | offline | — | completed | completed_with_errors | failed | idle | idle |
| offline | — | — | — | offline (if attempts <= 3) else failed | — | — | (prev) | — | — | failed | idle | idle |
| completed / completed_with_errors / failed | pending | — | — | — | — | — | — | — | — | — | — | idle |

## Overlay: request-error-banner (one row per `AppError._tag`)

`cooldown` and `not_found` are not tags: they are `isCooldown(http)` (429/503 + Retry-After) and `isHttpStatus(http, 404)`. Abort has copy but no recovery action (frozen poll, not a banner).

```
+----------------------------------------------------------------------+
| http         : HTTP error (404 auto-dismiss; 429/503 Wait ▾) [Retry] |
| parse        : "Unexpected response from server"    [Retry]          |
| auth_expired : "Your session expired — reload the page and sign in   |
|                 again."                              [Reload page]   |
| nonce_refresh: "Network error — check your connection"  [Retry]      |
|                (W2A-02: refresh timeout/transport is NOT expiry;     |
|                 reuses transport copy, no new string)                 |
| abort        : (silent / frozen poll — no banner)                    |
| timeout      : "The server took too long to respond — try again"     |
|                                                     [Retry]          |
|                (W2A-05: split from abort; the only new string)       |
| transport    : "Network error — check your connection"  [Retry]      |
| unknown      : "<caller fallback copy>"             [Retry]          |
+----------------------------------------------------------------------+
```

## Reconciliation — FEBT1F-L-02 (banner variants vs overlay states)

Codemap trace: `useJobStateMachine` ← `JobPipelineProvider` ← `WorkbenchProvider` ← `WorkbenchPage`. The view never
branches on a `stalled`/`offline` **state**: `useJobStateMachineDerivedState` renders `statusText` from `status`
(pending|running|completed|completed_with_errors|failed) and overlays two orthogonal **modifiers**,
`stalledForSeconds` (no-event timer) and `isOnline` (`navigator.onLine`). Same modifier-axis shape the dashboard map
already flagged (`dashboard.uxmap.json` note on `degraded`/`offline`).

Resolution (binding for F3 / W2D-01 adoption, GRPH-27/28, DATA-14):

- Reducer keeps `stalled` and `offline` as peer states — their recoveries differ (tick timer vs `online` event).
- The hook **derives** the existing view contract from reducer state: `stalledForSeconds = status==='stalled' ? (now-lastEventAt)/1000 : null`,
  `isOnline = status!=='offline'`. No view/copy changes in F3 (`not_doing` stands).
- Reconnect counter is internal (`reconnectAttempts`, W2D-02) and never rendered; the banner shows elapsed stall seconds only.
- `timeout` overlay row added above; `abort` stays silent. `nonce_refresh` reuses transport copy.

## Flows

- job-happy-path: idle → pending → running → completed
- job-stall-reconnect: running → stalled → running (SSE reopen) | failed (after bounded reconnects, RES-06)
- auth-expired-recovery: banner(auth_expired) → exit reload-page
- cooldown-429: banner(http + isCooldown, Retry-After countdown) → running

## Critique against canon (advisory)

- Status pairs colour with a glyph (✓ ! ✗) — sr-004.
- Primary action reachable from idle (zero state) — rg-003.
- Cancel is irreversible → keep secondary hierarchy, no preview — CARD-07.
- Stall vs offline are distinct states because they have distinct recoveries (timer vs `online` event) — GRPH-27/28.
- Banner owner resolved: `useJobStateMachineDerivedState.statusText` via `JobPipelineProvider` (see Reconciliation).
