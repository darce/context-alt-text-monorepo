# Guided live description — server-negotiated deadline (GUIDEDFIX-2)

Scope: what the operator sees once the panel stops guessing a local ceiling and
adopts `deadline_seconds` disclosed by the scene service at accept time.

Wire fact: `POST /scene/describe/run` returns `deadline_seconds` (float, may be
null). The panel computes `deadlineMs = min(localCeilingMs, deadline_seconds *
1000 + GUIDED_LIVE_DEADLINE_SLACK_MS)` once, at submit. Null keeps today's local
ceiling. The countdown is derived from that one value, never re-derived per poll.

## S1 — idle, before submit

```
+--------------------------------------------------------------+
| Live description                                     [ idle ] |
+--------------------------------------------------------------+
| Image: kitchen-window-2048.jpg                                |
| Context: "kitchen, morning light"                             |
|                                                               |
|                       [ Describe image ]                      |
+--------------------------------------------------------------+
```

No budget is shown before submit: the panel does not know the server's budget
until the run is accepted. Inventing one here is the bug this change removes.

## S2 — accepted, budget disclosed

```
+--------------------------------------------------------------+
| Live description                                  [ running ] |
+--------------------------------------------------------------+
| Run 8f2c-41ab accepted.                                       |
| [############--------------------]  0:38 / 3:00               |
| Server budget 3:00 - polling every 2s                         |
|                                                               |
|                          [ Cancel ]                           |
+--------------------------------------------------------------+
```

The "3:00" is the server's number, not ours. Progress bar fills against it.

## S3 — accepted, server disclosed no budget

```
+--------------------------------------------------------------+
| Live description                                  [ running ] |
+--------------------------------------------------------------+
| Run 8f2c-41ab accepted.                                       |
| [####----------------------------]  0:38 elapsed              |
| No server budget disclosed - local ceiling 8:30                |
|                                                               |
|                          [ Cancel ]                           |
+--------------------------------------------------------------+
```

Degraded, and says so. Elapsed replaces a ratio because the denominator is a
guess; showing a fake denominator would misstate certainty.

## S4 — deadline reached

```
+--------------------------------------------------------------+
| Live description                                 [ timed out ]|
+--------------------------------------------------------------+
| ! The server's 3:00 budget for run 8f2c-41ab elapsed.         |
|   The run may still finish; this panel stopped waiting.       |
|                                                               |
|              [ Keep waiting ]     [ Start over ]              |
+--------------------------------------------------------------+
```

Timeout names whose budget elapsed and does not claim the run failed. "Keep
waiting" resumes polling under a fresh local window; "Start over" submits a new
run with a new idempotency key.

## S5 — replayed submit (idempotency key hit)

```
+--------------------------------------------------------------+
| Live description                                  [ running ] |
+--------------------------------------------------------------+
| Reattached to run 8f2c-41ab (already in flight).              |
| [##################--------------]  1:52 / 3:00               |
+--------------------------------------------------------------+
```

A double submit returns 202 with the same run id. The panel reattaches instead
of starting a second generation. The countdown continues against the original
budget, so a replay never resets the clock.

## S6 — idempotency key rejected

```
+--------------------------------------------------------------+
| Live description                                     [ error ]|
+--------------------------------------------------------------+
| ! This submit could not be de-duplicated (invalid key).       |
|   Nothing was generated and nothing was charged.              |
|                                                               |
|                       [ Try again ]                           |
+--------------------------------------------------------------+
```

WordPress returns 400 `invalid_idempotency_key` before touching the backend. The
copy states the safe fact: no run started.

## State transitions

```
idle --submit--> accepted --deadline--> timed_out --keep waiting--> accepted
  |                 |                        |
  |                 +--terminal payload--> done
  +--400 invalid key--> error --try again--> idle
```

## Accessibility notes

- Status is text plus icon, never colour alone.
- The countdown is an `aria-live="polite"` region updated at most once per
  second so a screen reader is not flooded by the 2s poll.
- "timed out" is announced once, not on every tick.
