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

```
+----------------------------------------------------------------------+
| auth_expired : "Your session expired — reload the page and sign in   |
|                 again."                              [Reload page]   |
| cooldown     : "Server busy — retrying in 12 s"     [Wait ▾]         |
| transport    : "Network error — check your connection"  [Retry]      |
| parse        : "Unexpected response from server"    [Retry]          |
| not_found    : "That item no longer exists"         (auto-dismiss)   |
| unknown      : "<caller fallback copy>"             [Retry]          |
+----------------------------------------------------------------------+
```

## Flows

- job-happy-path: idle → pending → running → completed
- job-stall-reconnect: running → stalled → running (SSE reopen) | failed (after bounded reconnects, RES-06)
- auth-expired-recovery: banner(auth_expired) → exit reload-page
- cooldown-429: banner(cooldown, Retry-After countdown) → running

## Critique against canon (advisory)

- Status pairs colour with a glyph (✓ ! ✗) — sr-004.
- Primary action reachable from idle (zero state) — rg-003.
- Cancel is irreversible → keep secondary hierarchy, no preview — CARD-07.
- Stall vs offline are distinct states because they have distinct recoveries (timer vs `online` event) — GRPH-27/28.
- Open: confirm the banner's owning component before L6c (see `open_questions`).
